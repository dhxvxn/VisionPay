import os
import time
import logging
from neonize.client import NewClient
from neonize.events import ConnectedEv
from models import get_session, Student, Payment
from ocr_utils import extract_payment_details
from neonize.utils.jid import build_jid, jid_is_lid, JID
import sys

def fix_payments(client: NewClient):
    print("Connected! Starting to fix payments...")
    session = get_session()
    try:
        payments = session.query(Payment).all()
        fixed_count = 0
        
        for p in payments:
            updated = False
            
            # 1. Resolve LID to Phone Number
            # A 15-digit number is likely a LID
            if p.sender_phone and (len(p.sender_phone) > 12 or not p.sender_phone.startswith('91')):
                print(f"Attempting to resolve LID: {p.sender_phone}")
                try:
                    # Construct LID JID
                    lid_jid = JID(User=p.sender_phone, Server="lid", Device=0, RawAgent=0, Integrator=0, IsEmpty=False)
                    pn_jid = client.get_pn_from_lid(lid_jid)
                    if pn_jid and pn_jid.User:
                        print(f"  Resolved to: {pn_jid.User}")
                        p.sender_phone = pn_jid.User
                        updated = True
                        
                        # Try to link to student if not linked
                        if not p.student_id:
                            student = session.query(Student).filter(
                                (Student.phone_number.contains(pn_jid.User)) |
                                (Student.parent_phone.contains(pn_jid.User))
                            ).first()
                            if student:
                                p.student_id = student.id
                                print(f"  Linked to student: {student.name}")
                except Exception as e:
                    print(f"  Failed to resolve LID {p.sender_phone}: {e}")

            # 2. Re-run OCR if amount is missing or was N/A
            if (p.amount is None or p.amount == 0) and p.screenshot_path and os.path.exists(p.screenshot_path):
                print(f"Re-running OCR for payment ID {p.id} ({p.screenshot_path})")
                details = extract_payment_details(p.screenshot_path)
                if details and details['amount']:
                    print(f"  Extracted amount: {details['amount']}")
                    p.amount = details['amount']
                    if details['transaction_id'] and not p.transaction_id:
                        p.transaction_id = details['transaction_id']
                    updated = True
                else:
                    print("  Still could not extract amount.")

            if updated:
                fixed_count += 1
        
        session.commit()
        print(f"Finished. Fixed {fixed_count} payment records.")
    except Exception as e:
        print(f"Error during fix: {e}")
        session.rollback()
    finally:
        session.close()
        client.disconnect()
        os._exit(0) # Force exit to stop the event loop

def main():
    print("Initializing WhatsApp client to resolve LIDs... Please wait.")
    client = NewClient("feetrack_session.db")
    
    @client.event(ConnectedEv)
    def on_connected(client: NewClient, message: ConnectedEv):
        fix_payments(client)

    client.connect()

if __name__ == "__main__":
    main()
