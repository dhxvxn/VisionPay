# VisionPay 👁️💰
An automated WhatsApp-based fee tracking system. It monitors specific WhatsApp groups for payment screenshots, extracts transaction details using OCR (Tesseract), and logs them into a local database.

## Features
- **WhatsApp Integration**: Monitors specific WhatsApp groups for payment screenshots.
- **OCR Extraction**: Automatically extracts **Amount**, **Date**, and **Transaction ID** from payment receipts using Tesseract OCR.
- **Student-Parent Linking**: Supports linking two phone numbers (Student & Parent) to a single record, allowing either to send proof of payment.
- **Payment Summary**: Generates a clean terminal table showing payment status, student details, and screenshot paths.
- **LID Resolution**: Automatically resolves WhatsApp "LIDs" to actual phone numbers for accurate tracking.

## CLI Commands
The project includes a `cli.py` for managing data:

- **List Students**: `python cli.py students`
- **Add Student**: `python cli.py add-student <name> <phone> [parent_name] [parent_phone]`
  - *Note: You can add both student and parent numbers to ensure payments from either are tracked.*
- **Payment Summary**: `python cli.py summary`
  - *Shows Name, Phone Number, Transaction ID, and Photo path.*
- **Detailed Payments**: `python cli.py payments`
- **Link Payment**: `python cli.py link-payment <payment_id> <student_id>`
- **Manage Groups**: `python cli.py allowed-groups`, `add-group <jid>`, `remove-group <id>`
- **Fetch Groups**: `python cli.py fetch-groups` (Connects to WA to list your group JIDs)
- **Fix Data**: `python cli.py fix-data` (Re-runs OCR and resolves phone numbers)

## Project Structure
- `main.py`: The WhatsApp listener and OCR coordinator.
- `cli.py`: Command-line management tool.
- `models.py`: Database schema (SQLAlchemy).
- `ocr_utils.py`: OCR logic for extracting text from images.
- `screenshots/`: Local storage for downloaded payment proofs.
- `feetrack.db`: SQLite database containing all records.

## License
MIT
