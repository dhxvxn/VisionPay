# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Feetrack is a WhatsApp bot that monitors designated group chats for payment screenshots sent by parents. It runs OCR on the images to extract UPI transaction IDs and amounts, then links payments to registered students in a SQLite database. A CLI (`cli.py`) handles all management tasks.

## Running the Project

```bash
# Activate venv first
source venv/bin/activate

# Start the WhatsApp listener (first run shows QR code to scan)
python main.py

# List all joined WhatsApp groups (to get JIDs for allow-listing)
python main.py --list-groups

# CLI management tool
python cli.py students
python cli.py payments
python cli.py unregistered
python cli.py add-student "Name" "phone" "Parent" "phone2"
python cli.py register <sender_id> "Name" "Parent" "phone2"
python cli.py link-sender <sender_id> <student_id>
python cli.py link-payment <payment_id> <student_id>
python cli.py re-scan          # re-OCR payments with missing amounts
python cli.py re-scan --all    # re-OCR all payments
python cli.py rescan-month     # fetch historical WhatsApp messages
python cli.py fix-data         # resolve LIDs and backfill missing links

# There are no automated tests
```

## Architecture

**Two databases:**
- `feetrack.db` — application data (students, payments, allowed groups)
- `feetrack_session.db` — neonize's WhatsApp auth session (do not touch)

**Message flow:**
1. `main.py:on_message` → `process_whatsapp_message`
2. Checks `AllowedGroup` table — messages from non-whitelisted groups are silently dropped
3. Image/PDF → `handle_media` → OCR → save `Payment` row
4. Follow-up text within 5 minutes → `handle_text` fills in missing fields on the same payment
5. Text-only receipts with both amount and transaction ID are saved directly without OCR

**`recent_image_senders` global dict** (main.py) buffers the most recent payment ID per phone number so a follow-up text message can be appended to it. Keyed by phone number, expires after `BUFFER_TIMEOUT` (300s).

**OCR pipeline** (`ocr_utils.py`): `extract_payment_details()` tries 6 different threshold/PSM combinations, deduplicates by transaction ID, and returns a **list of dicts** — not a single dict. Each dict has keys: `amount`, `transaction_id`, `date`, `note`, `raw_text`.

**Phone number handling:** WhatsApp delivers sender numbers with country code (e.g. `919876543210`). `Student.parent_phone_1` stores without the country code (`9876543210`). Lookups use SQLAlchemy `.contains()` to match either format.

**WhatsApp LIDs:** Some group members appear as anonymized LID identifiers instead of phone numbers. `fix_data.py` connects to WhatsApp and calls `client.get_pn_from_lid()` to resolve them. This is why `fix-data` requires an active WhatsApp connection.

**Session pattern:** Every function that touches the DB calls `get_session()`, wraps work in try/except with `session.rollback()` on error, and closes in `finally`. There is no shared session — each function owns its own.

**`os._exit(0)`** is used in one-shot WhatsApp operations (`--list-groups`, `fix_data.py`, `rescan-month`) to force-stop neonize's event loop after the task completes.

## Key Constraints

- `AllowedGroup` rows must be inserted manually into the DB before the bot will process any messages. Use `python main.py --list-groups` to find group JIDs, then insert with raw SQL or add an `add-group` CLI command.
- neonize requires the WhatsApp session to be authenticated. If `feetrack_session.db` is missing or expired, `python main.py` will show a QR code to re-authenticate.
- Only one process should connect to `feetrack_session.db` at a time — running `main.py` and `fix-data` / `rescan-month` simultaneously will cause neonize conflicts.
