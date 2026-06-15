import os
import time
import logging
import mimetypes
import re
from neonize.client import NewClient
from neonize.events import MessageEv, ReceiptEv, CallOfferEv, ConnectedEv, ConnectFailureEv, DisconnectedEv
from neonize.utils import log
from neonize.utils.jid import Jid2String, jid_is_lid
from models import get_session, Student, Payment, AllowedGroup, UnregisteredSender
from ocr_utils import extract_payment_details
import datetime
from sqlalchemy import literal

# Enable debug logging for neonize
log.setLevel(logging.DEBUG)

def is_group_allowed(chat_jid):
    """Checks if a group is in the allowed_groups table."""
    session = get_session()
    try:
        allowed = session.query(AllowedGroup).filter(AllowedGroup.group_jid == chat_jid).first()
        return allowed is not None
    finally:
        session.close()

# Buffer to store the last sender of an image to capture follow-up text messages
recent_image_senders = {}
BUFFER_TIMEOUT = 300  # 5 minutes

def on_connected(client: NewClient, message: ConnectedEv):
    print("✅ Connected to WhatsApp successfully!")

def on_connect_failure(client: NewClient, message: ConnectFailureEv):
    print(f"❌ Connection failed: {message}")

def on_disconnected(client: NewClient, message: DisconnectedEv):
    print("🔌 Disconnected from WhatsApp.")

def get_media_message(message_proto):
    """Unwraps nested messages and returns the specific media message and its type."""
    if not message_proto:
        return None, None
    
    if message_proto.imageMessage:
        return message_proto.imageMessage, "image"
    if message_proto.documentMessage:
        return message_proto.documentMessage, "document"
    if message_proto.videoMessage:
        return message_proto.videoMessage, "video"
    if hasattr(message_proto, "viewOnceMessage") and message_proto.viewOnceMessage:
        return get_media_message(message_proto.viewOnceMessage.message)
    if hasattr(message_proto, "viewOnceMessageV2") and message_proto.viewOnceMessageV2:
        return get_media_message(message_proto.viewOnceMessageV2.message)
    if hasattr(message_proto, "ephemeralMessage") and message_proto.ephemeralMessage:
        return get_media_message(message_proto.ephemeralMessage.message)
    return None, None

def handle_image(client, message: MessageEv, phone_number):
    """Processes an incoming image message."""
    session = get_session()
    try:
        # 1. Extract media message
        media_msg, msg_type = get_media_message(message.Message)
        if not media_msg:
            return

        # 2. Download media
        try:
            image_data = client.download_any(message.Message)
        except Exception as e:
            print(f"Download failed: {e}")
            return

        if not image_data:
            return

        # 3. Determine extension
        mimetype = getattr(media_msg, "mimetype", "image/jpeg")
        extension = mimetypes.guess_extension(mimetype) or ".jpg"
        is_image = "image" in mimetype or extension.lower() in [".jpg", ".jpeg", ".png"]

        timestamp = int(time.time())
        filename = f"screenshot_{phone_number}_{timestamp}{extension}"
        filepath = os.path.join("screenshots", filename)
        
        os.makedirs("screenshots", exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(image_data)
        
        if not is_image:
            return

        # 4. Run OCR
        details = extract_payment_details(filepath)
        if not details:
            return

        # 5. Find Student
        search_phone = phone_number
        if search_phone.startswith('91') and len(search_phone) == 12:
            search_phone = search_phone[2:]
            
        student = session.query(Student).filter(
            (Student.parent_phone_1.contains(search_phone)) | 
            (Student.parent_phone_2.contains(search_phone)) |
            (literal(phone_number).contains(Student.parent_phone_1))
        ).first()
        
        # 6. If not student, add/update UnregisteredSender
        if not student:
            push_name = message.Info.Pushname
            unregistered = session.query(UnregisteredSender).filter(UnregisteredSender.sender_phone == phone_number).first()
            if not unregistered:
                unregistered = UnregisteredSender(
                    sender_phone=phone_number,
                    push_name=push_name,
                    last_screenshot_path=filepath
                )
                session.add(unregistered)
                print(f"Logged unknown sender: {phone_number}")
            else:
                unregistered.last_screenshot_path = filepath
                unregistered.push_name = push_name

        # 7. Save to Payment Table
        caption = getattr(media_msg, "caption", "")
        amount = details["amount"]
        if not amount and caption:
            amount_match = re.search(r'(?:₹|INR|Rs\.?|Amount|Paid)[\s:]*([\d,]+(?:\.\d{2})?)', caption, re.IGNORECASE)
            if amount_match:
                try:
                    amount = float(amount_match.group(1).replace(',', ''))
                except:
                    pass

        new_payment = Payment(
            student_id=student.id if student else None,
            sender_phone=phone_number,
            amount=amount,
            transaction_id=details["transaction_id"],
            screenshot_path=filepath,
            ocr_text=details["raw_text"],
            status="Pending"
        )
        session.add(new_payment)
        session.commit()
        
        recent_image_senders[phone_number] = {
            "payment_id": new_payment.id,
            "timestamp": time.time()
        }
        
    except Exception as e:
        print(f"Error handling image: {e}")
        session.rollback()
    finally:
        session.close()

def handle_text(message: MessageEv, phone_number):
    if phone_number in recent_image_senders:
        data = recent_image_senders[phone_number]
        if time.time() - data["timestamp"] < BUFFER_TIMEOUT:
            session = get_session()
            try:
                payment = session.get(Payment, data["payment_id"])
                if payment:
                    text_content = ""
                    if message.Message.conversation:
                        text_content = message.Message.conversation
                    elif message.Message.extendedTextMessage:
                        text_content = message.Message.extendedTextMessage.text
                    
                    if text_content:
                        if payment.additional_notes:
                            payment.additional_notes += " | Msg: " + text_content
                        else:
                            payment.additional_notes = "Msg: " + text_content
                        session.commit()
            except Exception as e:
                session.rollback()
            finally:
                session.close()

def on_message(client: NewClient, message: MessageEv):
    chat_jid = Jid2String(message.Info.MessageSource.Chat)
    sender_jid = message.Info.MessageSource.Sender
    
    if jid_is_lid(sender_jid):
        try:
            pn_jid = client.get_pn_from_lid(sender_jid)
            phone_number = pn_jid.User
        except Exception:
            phone_number = sender_jid.User
    else:
        phone_number = sender_jid.User
    
    if not is_group_allowed(chat_jid):
        return

    media_msg, msg_type = get_media_message(message.Message)
    if msg_type == "image" or (msg_type == "document" and "image" in getattr(media_msg, "mimetype", "")):
        handle_image(client, message, phone_number)
    elif message.Message.conversation or message.Message.extendedTextMessage:
        handle_text(message, phone_number)

def main():
    import sys
    client = NewClient("feetrack_session.db")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--list-groups":
        @client.event(ConnectedEv)
        def on_connected_list(client: NewClient, message: ConnectedEv):
            print("\n--- Joined Groups ---")
            try:
                groups = client.get_joined_groups()
                for group in groups:
                    print(f"Name: {group.GroupName.Name}\nJID: {Jid2String(group.JID)}\n" + "-"*20)
            finally:
                client.disconnect()
                os._exit(0)
        client.connect()
        return

    client.event(MessageEv)(on_message)
    client.event(ConnectedEv)(on_connected)
    client.event(ConnectFailureEv)(on_connect_failure)
    client.event(DisconnectedEv)(on_disconnected)
    client.connect()

if __name__ == "__main__":
    main()
