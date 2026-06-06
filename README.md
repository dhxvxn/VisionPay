# VisionPay 👁️💰
An automated WhatsApp-based fee tracking system. It monitors specific WhatsApp groups for payment screenshots, extracts transaction details using OCR (Tesseract), and logs them into a local database.

## Features
- **WhatsApp Integration**: Uses `neonize` to listen for messages in real-time.
- **OCR Processing**: Automatically extracts amounts and transaction IDs from payment screenshots.
- **CLI Management**: Easy-to-use command line tool to manage students, payments, and allowed groups.
- **SQLite Database**: Lightweight and portable storage for all tracking data.

## Prerequisites
- Python 3.10+
- Tesseract OCR engine
  - Linux: `sudo apt install tesseract-ocr`
  - Windows: [Install Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
- A WhatsApp account to scan the QR code.

## Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/dhxvxn/VisionPay.git
   cd VisionPay
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: Ensure you have `neonize` and `pytesseract` installed)*

## Usage

### 1. Start the WhatsApp Client
This starts the listener. If it's your first time, it will generate a QR code in the terminal for you to scan via WhatsApp "Linked Devices".
```bash
python3 main.py
```

### 2. Manage the System (CLI Commands)

#### **WhatsApp Groups**
- **List joined groups**: (Fetches your WhatsApp groups and JIDs)
  ```bash
  python3 cli.py fetch-groups
  ```
- **Add a group to track**:
  ```bash
  python3 cli.py add-group "<GROUP_JID>" "<GROUP_NAME>"
  ```
- **List allowed groups**:
  ```bash
  python3 cli.py allowed-groups
  ```

#### **Students**
- **Add a student**:
  ```bash
  python3 cli.py add-student "<NAME>" "<PHONE_NUMBER>" ["<PARENT_NAME>"]
  ```
- **View all students**:
  ```bash
  python3 cli.py students
  ```

#### **Payments**
- **View all logged payments**:
  ```bash
  python3 cli.py payments
  ```
- **Link an unknown payment to a student**:
  ```bash
  python3 cli.py link-payment <PAYMENT_ID> <STUDENT_ID>
  ```

## Project Structure
- `main.py`: The WhatsApp listener and OCR coordinator.
- `cli.py`: Command-line management tool.
- `models.py`: Database schema (SQLAlchemy).
- `ocr_utils.py`: OCR logic for extracting text from images.
- `screenshots/`: Local storage for downloaded payment proofs.
- `feetrack.db`: SQLite database containing all records.

## License
MIT
