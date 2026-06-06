import sys
from models import get_session, Student, Payment, AllowedGroup
from rich.console import Console
from rich.table import Table
import subprocess

console = Console()

def list_students():
    session = get_session()
    students = session.query(Student).all()
    
    table = Table(title="Students Registered")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Parent Name", style="green")
    table.add_column("Phone Number", style="yellow")
    
    for s in students:
        table.add_row(str(s.id), s.name, s.parent_name or "N/A", s.phone_number)
    
    console.print(table)
    session.close()

def list_payments():
    session = get_session()
    payments = session.query(Payment).all()
    
    table = Table(title="Fee Payments")
    table.add_column("ID", style="cyan")
    table.add_column("Student", style="magenta")
    table.add_column("Amount", style="green")
    table.add_column("Date", style="blue")
    table.add_column("Status", style="yellow")
    table.add_column("Notes", style="white")
    
    for p in payments:
        student_name = p.student.name if p.student else "Unknown"
        table.add_row(
            str(p.id), 
            student_name, 
            f"₹{p.amount}" if p.amount else "N/A", 
            p.date_received.strftime("%Y-%m-%d %H:%M"),
            p.status,
            p.additional_notes or ""
        )
    
    console.print(table)
    session.close()

def add_student(name, phone, parent=None):
    session = get_session()
    try:
        new_student = Student(name=name, phone_number=phone, parent_name=parent)
        session.add(new_student)
        session.commit()
        console.print(f"[green]Successfully added student: {name}[/green]")
    except Exception as e:
        console.print(f"[red]Error adding student: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def link_payment(payment_id, student_id):
    session = get_session()
    try:
        payment = session.query(Payment).get(payment_id)
        student = session.query(Student).get(student_id)
        if not payment:
            console.print(f"[red]Payment {payment_id} not found.[/red]")
            return
        if not student:
            console.print(f"[red]Student {student_id} not found.[/red]")
            return
        
        payment.student_id = student.id
        session.commit()
        console.print(f"[green]Payment {payment_id} linked to student {student.name}.[/green]")
    except Exception as e:
        console.print(f"[red]Error linking payment: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def list_allowed_groups():
    session = get_session()
    groups = session.query(AllowedGroup).all()
    
    table = Table(title="Allowed Groups")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("JID", style="yellow")
    
    for g in groups:
        table.add_row(str(g.id), g.group_name or "N/A", g.group_jid)
    
    console.print(table)
    session.close()

def add_allowed_group(jid, name=None):
    session = get_session()
    try:
        new_group = AllowedGroup(group_jid=jid, group_name=name)
        session.add(new_group)
        session.commit()
        console.print(f"[green]Successfully added group: {name or jid}[/green]")
    except Exception as e:
        console.print(f"[red]Error adding group: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def remove_allowed_group(group_id):
    session = get_session()
    try:
        group = session.query(AllowedGroup).get(group_id)
        if group:
            name = group.group_name or group.group_jid
            session.delete(group)
            session.commit()
            console.print(f"[green]Successfully removed group: {name}[/green]")
        else:
            console.print(f"[red]Group with ID {group_id} not found.[/red]")
    except Exception as e:
        console.print(f"[red]Error removing group: {e}[/red]")
        session.rollback()
    finally:
        session.close()

def fetch_whatsapp_groups():
    console.print("[yellow]Connecting to WhatsApp to fetch groups...[/yellow]")
    try:
        # Run main.py with --list-groups flag
        subprocess.run(["python3", "main.py", "--list-groups"])
    except Exception as e:
        console.print(f"[red]Error fetching groups from WhatsApp: {e}[/red]")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("Usage: python cli.py [students|payments|add-student|link-payment|allowed-groups|add-group|remove-group|fetch-groups]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "students":
        list_students()
    elif cmd == "payments":
        list_payments()
    elif cmd == "add-student":
        if len(sys.argv) < 4:
            console.print("Usage: python cli.py add-student <name> <phone> [parent_name]")
        else:
            parent = sys.argv[4] if len(sys.argv) > 4 else None
            add_student(sys.argv[2], sys.argv[3], parent)
    elif cmd == "link-payment":
        if len(sys.argv) < 3:
            console.print("Usage: python cli.py link-payment <payment_id> <student_id>")
        else:
            link_payment(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "allowed-groups":
        list_allowed_groups()
    elif cmd == "add-group":
        if len(sys.argv) < 3:
            console.print("Usage: python cli.py add-group <jid> [name]")
        else:
            name = sys.argv[3] if len(sys.argv) > 3 else None
            add_allowed_group(sys.argv[2], name)
    elif cmd == "remove-group":
        if len(sys.argv) < 3:
            console.print("Usage: python cli.py remove-group <group_id>")
        else:
            remove_allowed_group(int(sys.argv[2]))
    elif cmd == "fetch-groups":
        fetch_whatsapp_groups()
