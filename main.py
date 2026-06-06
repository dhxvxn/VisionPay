import os
import time
import logging
import mimetypes
from neonize.client import NewClient
from neonize.events import MessageEv, ReceiptEv, CallOfferEv, ConnectedEv, ConnectFailureEv, DisconnectedEv
from neonize.utils import log
from neonize.utils.jid import Jid2String
from models import get_session, Student, Payment, AllowedGroup
from ocr_utils import extract_payment_details
import datetime

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
# Format: {phone_number: {"payment_id": id, "timestamp": time}}
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
            print(f"Failed to extract media from message from {phone_number}")
            return

        # 2. Download media
        # Using download_any on the full Message object first, fallback to media_msg
        try:
            image_data = client.download_any(message.Message)
        except Exception as e:
            print(f"Download failed with top-level message, trying specific media message: {e}")
            # Some versions of neonize might only support download_any on the Message proto
            # or might have a different method for specific parts.
            # We'll stick to download_any but if it fails we might need to investigate further.
            return

        if not image_data:
            print(f"Failed to download image from {phone_number}")
            return

        # 3. Determine extension
        mimetype = getattr(media_msg, "mimetype", "image/jpeg")
        extension = mimetypes.guess_extension(mimetype) or ".jpg"
        
        # If it's not an image, we might still save it but OCR will fail
        is_image = "image" in mimetype or extension.lower() in [".jpg", ".jpeg", ".png"]

        timestamp = int(time.time())
        filename = f"screenshot_{phone_number}_{timestamp}{extension}"
        filepath = os.path.join("screenshots", filename)
        
        # Ensure screenshots directory exists
        os.makedirs("screenshots", exist_ok=True)
        
        with open(filepath, "wb") as f:
            f.write(image_data)
        
        if not is_image:
            print(f"Received non-image file ({mimetype}) from {phone_number}, skipping OCR.")
            return

        # 4. Run OCR
        details = extract_payment_details(filepath)
        if not details:
            print(f"OCR failed for {filepath}")
            return

        # 5. Find Student
        student = session.query(Student).filter(Student.phone_number.contains(phone_number)).first()
        
        # 6. Save to Database
        new_payment = Payment(
            student_id=student.id if student else None,
            amount=details["amount"],
            transaction_id=details["transaction_id"],
            screenshot_path=filepath,
            ocr_text=details["raw_text"],
            status="Pending"
        )
        session.add(new_payment)
        session.commit()
        
        # 7. Update buffer for follow-up notes
        recent_image_senders[phone_number] = {
            "payment_id": new_payment.id,
            "timestamp": time.time()
        }
        
        print(f"Logged payment for {student.name if student else 'Unknown'} ({phone_number}): {details['amount']} (Txn: {details['transaction_id']})")
        
    except Exception as e:
        print(f"Error handling image: {e}")
        session.rollback()
    finally:
        session.close()

def handle_text(message: MessageEv, phone_number):
    """Checks if a text message is a follow-up note for a recent payment."""
    if phone_number in recent_image_senders:
        data = recent_image_senders[phone_number]
        # Check if it's within timeout
        if time.time() - data["timestamp"] < BUFFER_TIMEOUT:
            session = get_session()
            try:
                payment = session.query(Payment).get(data["payment_id"])
                if payment:
                    text_content = ""
                    if message.Message.conversation:
                        text_content = message.Message.conversation
                    elif message.Message.extendedTextMessage:
                        text_content = message.Message.extendedTextMessage.text
                    
                    if text_content:
                        if payment.additional_notes:
                            payment.additional_notes += " | " + text_content
                        else:
                            payment.additional_notes = text_content
                        session.commit()
                        print(f"Added note to payment {payment.id}: {text_content}")
            except Exception as e:
                print(f"Error updating note: {e}")
                session.rollback()
            finally:
                session.close()

def on_message(client: NewClient, message: MessageEv):
    chat_jid = Jid2String(message.Info.MessageSource.Chat)
    phone_number = message.Info.MessageSource.Sender.User
    
    # Check if the chat is allowed
    if not is_group_allowed(chat_jid):
        # Optional: Print only once per chat or something to avoid spam
        # For now, just ignore it.
        return

    # Check if message has media (image, video, document, or nested)
    media_msg, msg_type = get_media_message(message.Message)
    
    if msg_type == "image" or (msg_type == "document" and "image" in getattr(media_msg, "mimetype", "")):
        print(f"Received image from {phone_number} in {chat_jid}")
        handle_image(client, message, phone_number)
    
    # Check if message has text
    elif message.Message.conversation or message.Message.extendedTextMessage:
        handle_text(message, phone_number)

def main():
    import sys
    
    # Initialize Neonize client
    # "feetrack_session" is the name of the database where session info is stored
    client = NewClient("feetrack_session.db")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--list-groups":
        def on_connected_list(client: NewClient, message: ConnectedEv):
            print("\n--- Joined Groups ---")
            try:
                groups = client.get_joined_groups()
                for group in groups:
                    jid_str = Jid2String(group.JID)
                    print(f"Name: {group.GroupName.Name}")
                    print(f"JID: {jid_str}")
                    print("-" * 20)
            except Exception as e:
                print(f"Error fetching groups: {e}")
            finally:
                client.disconnect()
                sys.exit(0)

        client.event(ConnectedEv)(on_connected_list)
        client.connect()
        return

    # Register event handlers
    client.event(MessageEv)(on_message)
    client.event(ConnectedEv)(on_connected)
    client.event(ConnectFailureEv)(on_connect_failure)
    client.event(DisconnectedEv)(on_disconnected)
    
    print("Starting WhatsApp client... Please scan the QR code if prompted.")
    client.connect()

if __name__ == "__main__":
    main()

