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
from ocr_utils import extract_payment_details, extract_pdf_details, parse_payment_text
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

def handle_media(client, message: MessageEv, phone_number):
    """Processes an incoming media message (image or PDF)."""
    session = get_session()
    try:
        # 1. Extract media message
        media_msg, msg_type = get_media_message(message.Message)
        if not media_msg:
            return

        # 2. Download media
        try:
            media_data = client.download_any(message.Message)
        except Exception as e:
            print(f"Download failed: {e}")
            return

        if not media_data:
            return

        # 3. Determine extension and type
        mimetype = getattr(media_msg, "mimetype", "")
        if not mimetype:
            if msg_type == "image": mimetype = "image/jpeg"
            elif msg_type == "document": mimetype = "application/pdf"
            
        extension = mimetypes.guess_extension(mimetype) or (".jpg" if msg_type == "image" else ".pdf")
        is_image = "image" in mimetype or extension.lower() in [".jpg", ".jpeg", ".png"]
        is_pdf = "pdf" in mimetype or extension.lower() == ".pdf"

        timestamp = int(time.time())
        filename = f"media_{phone_number}_{timestamp}{extension}"
        filepath = os.path.join("screenshots", filename)
        
        os.makedirs("screenshots", exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(media_data)
        
        # 4. Extract details
        payments_found = []
        if is_image:
            payments_found = extract_payment_details(filepath)
        elif is_pdf:
            payments_found = extract_pdf_details(filepath)
        else:
            return

        if not payments_found:
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

        # 7. Supplemental info from caption
        caption = getattr(media_msg, "caption", "")
        caption_details = []
        if caption:
            caption_details = parse_payment_text(caption)

        # 8. Save to Payment Table
        for i, details in enumerate(payments_found):
            # Merge caption info if missing in this specific payment
            if caption_details and i < len(caption_details):
                c_det = caption_details[i]
                if not details["amount"] and c_det["amount"]: details["amount"] = c_det["amount"]
                if not details["transaction_id"] and c_det["transaction_id"]: details["transaction_id"] = c_det["transaction_id"]

            # Check if transaction already exists
            if details["transaction_id"]:
                existing = session.query(Payment).filter(Payment.transaction_id == details["transaction_id"]).first()
                if existing:
                    continue

            new_payment = Payment(
                student_id=student.id if student else None,
                sender_phone=phone_number,
                amount=details["amount"],
                transaction_id=details["transaction_id"],
                screenshot_path=filepath,
                ocr_text=details.get("raw_text", ""),
                status="Pending",
                additional_notes=f"Caption: {caption}" if caption else None
            )
            session.add(new_payment)
            session.commit()
            
            # Update buffer with the first (or last?) payment ID
            recent_image_senders[phone_number] = {
                "payment_id": new_payment.id,
                "timestamp": time.time()
            }
            print(f"Logged payment {i+1}: ₹{details['amount']} from {phone_number}")
        
    except Exception as e:
        print(f"Error handling media: {e}")
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
                        # Try to parse text for missing details
                        from ocr_utils import parse_payment_text
                        text_details = parse_payment_text(text_content)
                        
                        updated = False
                        if not payment.amount and text_details["amount"]:
                            payment.amount = text_details["amount"]
                            updated = True
                        if not payment.transaction_id and text_details["transaction_id"]:
                            payment.transaction_id = text_details["transaction_id"]
                            updated = True
                        
                        if payment.additional_notes:
                            payment.additional_notes += " | Msg: " + text_content
                        else:
                            payment.additional_notes = "Msg: " + text_content
                        session.commit()
            except Exception as e:
                print(f"Error handling text: {e}")
                session.rollback()
            finally:
                session.close()

def on_message(client: NewClient, message: MessageEv):
    process_whatsapp_message(client, message)

def process_whatsapp_message(client: NewClient, message: MessageEv):
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
    if msg_type == "image" or msg_type == "document":
        handle_media(client, message, phone_number)
    elif message.Message.conversation or message.Message.extendedTextMessage:
        # Check if it's a follow-up message
        if phone_number in recent_image_senders:
            handle_text(message, phone_number)
        else:
            # Check if it's a text-only payment receipt
            text_content = message.Message.conversation or message.Message.extendedTextMessage.text
            payments_found = parse_payment_text(text_content)
            
            if any(p["amount"] and p["transaction_id"] for p in payments_found):
                session = get_session()
                try:
                    # Find Student
                    search_phone = phone_number
                    if search_phone.startswith('91') and len(search_phone) == 12:
                        search_phone = search_phone[2:]
                        
                    student = session.query(Student).filter(
                        (Student.parent_phone_1.contains(search_phone)) | 
                        (Student.parent_phone_2.contains(search_phone)) |
                        (literal(phone_number).contains(Student.parent_phone_1))
                    ).first()

                    for details in payments_found:
                        if not details["amount"] or not details["transaction_id"]:
                            continue
                            
                        # Check if transaction already exists to avoid duplicates during rescan
                        existing = session.query(Payment).filter(Payment.transaction_id == details["transaction_id"]).first()
                        if existing:
                            continue

                        new_payment = Payment(
                            student_id=student.id if student else None,
                            sender_phone=phone_number,
                            amount=details["amount"],
                            transaction_id=details["transaction_id"],
                            screenshot_path="TEXT_ONLY",
                            ocr_text=text_content,
                            status="Pending",
                            additional_notes="Text-only receipt"
                        )
                        session.add(new_payment)
                        session.commit()
                        print(f"Logged text-only payment: {details['amount']} from {phone_number}")
                except Exception as e:
                    print(f"Error handling text-only payment: {e}")
                    session.rollback()
                finally:
                    session.close()

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
