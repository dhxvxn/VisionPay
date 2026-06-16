import sys
import os
from models import get_session, Student, Payment, AllowedGroup, UnregisteredSender
from rich.console import Console
from rich.table import Table
import subprocess
from ocr_utils import extract_payment_details

console = Console()

def list_students():
    session = get_session()
    students = session.query(Student).all()
    
    table = Table(title="Students Registered")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Parent Name", style="green")
    table.add_column("Parent Phone 1", style="yellow")
    table.add_column("Parent Phone 2", style="yellow")
    table.add_column("Total Paid", style="green")
    
    for s in students:
        total_paid = sum(p.amount for p in s.payments if p.amount)
        table.add_row(str(s.id), s.name, s.parent_name or "N/A", s.parent_phone_1, s.parent_phone_2 or "N/A", f"₹{total_paid:.2f}")
    
    console.print(table)
    session.close()

def list_payments():
    session = get_session()
    payments = session.query(Payment).all()
    
    table = Table(title="Fee Payments")
    table.add_column("ID", style="cyan")
    table.add_column("Student Name", style="magenta")
    table.add_column("Sender Phone", style="yellow")
    table.add_column("Amount Paid", style="green")
    table.add_column("Transaction ID", style="cyan")
    table.add_column("Date", style="blue")
    table.add_column("Status", style="yellow")
    
    for p in payments:
        student_name = "Unknown"
        if p.student:
            student_name = p.student.name
        
        table.add_row(
            str(p.id), 
            student_name,
            p.sender_phone or "N/A",
            f"₹{p.amount}" if p.amount else "N/A", 
            p.transaction_id or "N/A",
            p.date_received.strftime("%Y-%m-%d %H:%M"),
            p.status
        )
    
    console.print(table)
    session.close()

def list_unregistered():
    session = get_session()
    senders = session.query(UnregisteredSender).all()
    
    table = Table(title="Unregistered Senders")
    table.add_column("ID", style="cyan")
    table.add_column("Phone Number", style="yellow")
    table.add_column("Push Name", style="magenta")
    table.add_column("Last Screenshot", style="blue")
    table.add_column("First Seen", style="green")
    
    for s in senders:
        table.add_row(
            str(s.id),
            s.sender_phone,
            s.push_name or "N/A",
            s.last_screenshot_path or "N/A",
            s.first_seen.strftime("%Y-%m-%d %H:%M")
        )
    
    console.print(table)
    session.close()

def register_sender(sender_id, name, parent_name=None, other_phone=None):
    session = get_session()
    try:
        sender = session.get(UnregisteredSender, sender_id)
        if not sender:
            console.print(f"[red]Sender {sender_id} not found.[/red]")
            return
        
        new_student = Student(
            name=name,
            parent_name=parent_name,
            parent_phone_1=sender.sender_phone,
            parent_phone_2=other_phone
        )
        session.add(new_student)
        session.flush()
        
        payments = session.query(Payment).filter(Payment.sender_phone == sender.sender_phone).all()
        for p in payments:
            p.student_id = new_student.id
            
        session.delete(sender)
        session.commit()
        console.print(f"[green]Successfully registered {name} and linked {len(payments)} payments.[/green]")
    except Exception as e:
        console.print(f"[red]Error registering sender: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def link_sender_to_student(sender_id, student_id):
    session = get_session()
    try:
        sender = session.get(UnregisteredSender, sender_id)
        student = session.get(Student, student_id)
        
        if not sender:
            console.print(f"[red]Sender {sender_id} not found.[/red]")
            return
        if not student:
            console.print(f"[red]Student {student_id} not found.[/red]")
            return
            
        if not student.parent_phone_2:
            student.parent_phone_2 = sender.sender_phone
            
        payments = session.query(Payment).filter(Payment.sender_phone == sender.sender_phone).all()
        for p in payments:
            p.student_id = student.id
            
        session.delete(sender)
        session.commit()
        console.print(f"[green]Successfully linked sender {sender.sender_phone} to {student.name} and updated {len(payments)} payments.[/green]")
    except Exception as e:
        console.print(f"[red]Error linking sender: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def link_payment(payment_id, student_id):
    session = get_session()
    try:
        payment = session.get(Payment, payment_id)
        student = session.get(Student, student_id)
        if not payment or not student:
            console.print("[red]Payment or Student not found.[/red]")
            return
        payment.student_id = student.id
        session.commit()
        console.print(f"[green]Payment {payment_id} linked to {student.name}.[/green]")
    except Exception as e:
        console.print(f"[red]Error linking payment: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def delete_student(student_id):
    session = get_session()
    try:
        student = session.get(Student, student_id)
        if not student:
            console.print(f"[red]Student {student_id} not found.[/red]")
            return
        
        name = student.name
        # Unlink payments before deleting
        payments = session.query(Payment).filter(Payment.student_id == student.id).all()
        for p in payments:
            p.student_id = None
            
        session.delete(student)
        session.commit()
        console.print(f"[green]Successfully deleted student {name} and unlinked {len(payments)} payments.[/green]")
    except Exception as e:
        console.print(f"[red]Error deleting student: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def scan_screenshots(scan_all=False, payment_id=None):
    session = get_session()
    try:
        if payment_id:
            payments = [session.get(Payment, payment_id)]
            if not payments[0]:
                console.print(f"[red]Payment ID {payment_id} not found.[/red]")
                return
        elif scan_all:
            payments = session.query(Payment).all()
        else:
            payments = session.query(Payment).filter((Payment.amount == None) | (Payment.amount == 0)).all()
            
        count = 0
        for p in payments:
            if p and p.screenshot_path and os.path.exists(p.screenshot_path):
                details = extract_payment_details(p.screenshot_path)
                if details and details['amount']:
                    p.amount = details['amount']
                    p.ocr_text = details['raw_text']
                    if details['transaction_id']:
                        p.transaction_id = details['transaction_id']
                    count += 1
                    console.print(f"[green]Updated payment {p.id}: ₹{p.amount}[/green]")
        
        session.commit()
        console.print(f"[green]Scan complete. Updated {count} records.[/green]")
    except Exception as e:
        console.print(f"[red]Error during scan: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def add_student(name, phone, parent_name=None, parent_phone2=None):
    session = get_session()
    try:
        new_student = Student(name=name, parent_phone_1=phone, parent_name=parent_name, parent_phone_2=parent_phone2)
        session.add(new_student)
        session.commit()
        console.print(f"[green]Successfully added student: {name}[/green]")
    except Exception as e:
        console.print(f"[red]Error adding student: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def fix_data():
    subprocess.run(["python3", "fix_data.py"])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("Usage: python cli.py [students|payments|unregistered|register|link-sender|link-payment|add-student|delete-student|scan|re-scan|fix-data]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "students":
        list_students()
    elif cmd == "payments":
        list_payments()
    elif cmd == "unregistered":
        list_unregistered()
    elif cmd == "register":
        if len(sys.argv) < 4:
            console.print("Usage: python cli.py register <sender_id> <student_name> [parent_name] [phone2]")
        else:
            parent_name = sys.argv[4] if len(sys.argv) > 4 else None
            phone2 = sys.argv[5] if len(sys.argv) > 5 else None
            register_sender(int(sys.argv[2]), sys.argv[3], parent_name, phone2)
    elif cmd == "link-sender":
        if len(sys.argv) < 3:
            console.print("Usage: python cli.py link-sender <sender_id> <student_id>")
        else:
            link_sender_to_student(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "link-payment":
        if len(sys.argv) < 3:
            console.print("Usage: python cli.py link-payment <payment_id> <student_id>")
        else:
            link_payment(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "add-student":
        if len(sys.argv) < 4:
            console.print("Usage: python cli.py add-student <name> <phone1> [parent_name] [phone2]")
        else:
            parent_name = sys.argv[4] if len(sys.argv) > 4 else None
            phone2 = sys.argv[5] if len(sys.argv) > 5 else None
            add_student(sys.argv[2], sys.argv[3], parent_name, phone2)
    elif cmd == "delete-student":
        if len(sys.argv) < 3:
            console.print("Usage: python cli.py delete-student <student_id>")
        else:
            delete_student(int(sys.argv[2]))
    elif cmd in ["scan", "re-scan"]:
        scan_all = "--all" in sys.argv
        payment_id = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
        scan_screenshots(scan_all, payment_id)
    elif cmd == "fix-data":
        fix_data()
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
