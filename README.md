# Feetrack

A WhatsApp-based fee management system for tracking student payments using OCR and automated linking.

## Features

- **Automated Payment Logging:** Captures screenshots and UPI share cards from WhatsApp groups, extracts payment details (Amount, Transaction ID) using OCR, and links them to students.
- **Unregistered Sender Management:** Automatically identifies payments from unknown numbers and allows for easy registration and linking.
- **Robust OCR:** Uses multi-strategy preprocessing (including dark-mode inversion) to accurately identify payment amounts from both light and dark-background receipts.
- **Rich CLI:** A comprehensive command-line interface for managing students, payments, and system maintenance.

## Installation

1. Install Tesseract OCR on your system.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your WhatsApp session:
   ```bash
   python main.py
   ```
   (Scan the QR code when prompted)

## CLI Usage Reference

The CLI tool (`cli.py`) is the primary way to interact with the system.

### Student Management

- **List all students:**
  ```bash
  python cli.py students
  ```
- **Add a new student:**
  ```bash
  python cli.py add-student "Student Name" "Phone 1" "Parent Name" "Phone 2"
  ```
- **Delete a student:**
  ```bash
  python cli.py delete-student <student_id>
  ```

### Payment Tracking

- **List all payments:**
  ```bash
  python cli.py payments
  ```
- **Link a payment to a student manually:**
  ```bash
  python cli.py link-payment <payment_id> <student_id>
  ```
- **Run data fix (LID resolution & linking):**
  ```bash
  python cli.py fix-data
  ```

### Unregistered Senders

- **List unknown senders:**
  ```bash
  python cli.py unregistered
  ```
- **Register an unknown sender as a new student:**
  ```bash
  python cli.py register <sender_id> "Student Name" "Parent Name" "Phone 2"
  ```
  *(Automatically links all their previous payments to the new profile)*
- **Link an unknown sender to an existing student:**
  ```bash
  python cli.py link-sender <sender_id> <student_id>
  ```

### Maintenance & Re-scanning

- **Re-scan payments with missing amounts:**
  ```bash
  python cli.py re-scan
  ```
- **Re-scan ALL screenshots in the database:**
  ```bash
  python cli.py re-scan --all
  ```
- **Re-scan a specific payment by ID:**
  ```bash
  python cli.py re-scan <payment_id>
  ```
- **Fetch and process historical WhatsApp messages:**
  ```bash
  python cli.py rescan-month [limit]
  ```
  *(Default limit: 500 messages. Requires main.py to NOT be running.)*

### System Configuration

- **List all joined WhatsApp groups (to get JIDs):**
  ```bash
  python main.py --list-groups
  ```
  *(Copy the JID, then insert it into the `allowed_groups` table in `feetrack.db` to allow the bot to monitor that group.)*

## Project Structure

- `main.py`: The WhatsApp listener and real-time processor.
- `cli.py`: The command-line management tool.
- `models.py`: Database schema (SQLAlchemy).
- `ocr_utils.py`: Image processing and OCR logic.
- `fix_data.py`: Background utility for resolving LIDs and fixing legacy data.
