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
        
        # Create new student
        new_student = Student(
            name=name,
            parent_name=parent_name,
            parent_phone_1=sender.sender_phone,
            parent_phone_2=other_phone
        )
        session.add(new_student)
        session.flush() # Get student.id
        
        # Link all payments from this phone to the new student
        payments = session.query(Payment).filter(Payment.sender_phone == sender.sender_phone).all()
        for p in payments:
            p.student_id = new_student.id
            
        # Delete from unregistered
        session.delete(sender)
        
        session.commit()
        console.print(f"[green]Successfully registered {name} and linked {len(payments)} payments.[/green]")
    except Exception as e:
        console.print(f"[red]Error registering sender: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def scan_screenshots(scan_all=False, payment_id=None):
    """Scan command to re-run OCR on existing screenshots."""
    session = get_session()
    try:
        if payment_id:
            payments = [session.get(Payment, payment_id)]
            if not payments[0]:
                console.print(f"[red]Payment ID {payment_id} not found.[/red]")
                return
            console.print(f"[yellow]Re-scanning payment ID {payment_id}...[/yellow]")
        elif scan_all:
            payments = session.query(Payment).all()
            console.print("[yellow]Re-scanning ALL payment screenshots...[/yellow]")
        else:
            payments = session.query(Payment).filter((Payment.amount == None) | (Payment.amount == 0)).all()
            console.print("[yellow]Scanning payments with missing amounts...[/yellow]")
            
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
                else:
                    console.print(f"[red]Payment {p.id}: Still no amount found.[/red]")
        
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
    console.print("[yellow]Running data fix script to resolve LIDs and link payments...[/yellow]")
    try:
        subprocess.run(["python3", "fix_data.py"])
    except Exception as e:
        console.print(f"[red]Error running fix script: {e}[/red]")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("Usage: python cli.py [students|payments|unregistered|register|add-student|scan|fix-data]")
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
    elif cmd == "add-student":
        if len(sys.argv) < 4:
            console.print("Usage: python cli.py add-student <name> <phone1> [parent_name] [phone2]")
        else:
            parent_name = sys.argv[4] if len(sys.argv) > 4 else None
            phone2 = sys.argv[5] if len(sys.argv) > 5 else None
            add_student(sys.argv[2], sys.argv[3], parent_name, phone2)
    elif cmd == "scan" or cmd == "re-scan":
        scan_all = "--all" in sys.argv
        payment_id = None
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            payment_id = int(sys.argv[2])
        scan_screenshots(scan_all, payment_id)
    elif cmd == "fix-data":
        fix_data()
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
