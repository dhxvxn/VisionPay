import pytesseract
from PIL import Image
import re
import os

def extract_payment_details(image_path):
    """
    Extracts amount and transaction ID from a payment screenshot using OCR.
    """
    try:
        # Load image
        img = Image.open(image_path)
        
        # Preprocessing: Convert to grayscale
        img = img.convert('L')
        
        # Preprocessing: Thresholding (to make text sharper)
        img = img.point(lambda p: 255 if p > 140 else 0)
        
        # Preprocessing: Optional scaling (Tesseract works better with larger text)
        width, height = img.size
        if width < 1000:
            img = img.resize((width * 2, height * 2), Image.Resampling.LANCZOS)

        # Perform OCR
        # We use --psm 6 (Assume a single uniform block of text) or 3 (Fully automatic)
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(img, config=custom_config)
        
        # If text is very short or no amount found, try without thresholding
        if len(text) < 20:
            img_gray = Image.open(image_path).convert('L')
            text = pytesseract.image_to_string(img_gray, config=custom_config)

        # Regex patterns for Amount
        # We try to be careful about leading characters that might be misread symbols
        # Added common OCR misreads: ~, z, 2, «, ₹
        amount_patterns = [
            r'(?:₹|INR|Rs\.?|Amount|Paid|Total|Amt|Sum|Value|~|z|2|«)[\s:]*([\d,]+(?:\.\d{2})?)',
            r'Successfully\s+paid[\s:]*([\d,]+(?:\.\d{2})?)',
            r'Sent\s+([\d,]+(?:\.\d{2})?)',
            r'([\d,]+\.\d{2})', # Any number with two decimal places
            r'(?:₹|INR|Rs\.?|~|z|«)\s*([\d,]+)' # Currency symbol followed by digits
        ]
        
        all_amounts = []
        # First, try to find amounts with common keywords/symbols
        for pattern in amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                try:
                    # Clean and convert
                    val = float(m.replace(',', ''))
                    # Sanity check: Amount should probably be > 0 and not too huge for a fee
                    if 1 <= val < 100000:
                        all_amounts.append(val)
                except ValueError:
                    continue
        
        # If no amount found with keywords, look for any reasonably large number in the text
        # that might be the amount (e.g. 500, 1000, 2500)
        if not all_amounts:
            # Look for 3+ digit numbers that aren't dates or phone numbers
            potential_numbers = re.findall(r'(?<!\d)(?:₹|Rs\.?|~|z|«)?\s*([\d,]{3,})(?!\d)', text)
            for m in potential_numbers:
                try:
                    val = float(m.replace(',', ''))
                    if 100 <= val < 100000:
                        # Avoid matching 2024, 2025, 2026 (years)
                        if val not in [2024, 2025, 2026]:
                            all_amounts.append(val)
                except ValueError:
                    continue

        final_amount = None
        if all_amounts:
            # Often the largest amount is the total paid (rather than taxes or fees)
            # or it might be the only one found.
            final_amount = max(all_amounts)

        # Regex pattern for Note/Message from the screenshot
        note_patterns = [
            r'(?:Note|Message|Remark|Description|For)[\s:]+([^\n]+)',
            r'Add a note[\s:]+([^\n]+)'
        ]
        
        extracted_note = None
        for pattern in note_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Clean up the note
                extracted_note = matches[0].strip()
                break

        # Regex patterns for Date
        date_patterns = [
            r'(?:Date|Paid on|Time|Value Date|Timestamp)[\s:]*(\d{1,2}[/\-\s](?:\d{1,2}|[A-Za-z]{3,})[/\-\s]\d{2,4})',
            r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})', # 12 Jan 2024
            r'(\d{2}/\d{2}/\d{2,4})', # 12/01/2024
            r'(\d{4}-\d{2}-\d{2})' # 2024-01-12
        ]
        
        extracted_date = None
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                extracted_date = matches[0].strip()
                break

        # Regex patterns for Transaction ID
        txn_patterns = [
            r'(?:Transaction ID|Txn ID|Ref No|UTR|UPI Ref No|Reference|Reference No)[\s:]*([A-Z0-9]{10,})',
            r'(\d{12})',  # Many UTRs are just 12 digits
            r'ID[:\s]*([A-Z0-9]{10,})'
        ]
        
        txn_id = None
        for pattern in txn_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Find the longest alphanumeric string that looks like an ID
                candidates = [m for m in matches if any(c.isalpha() for c in m) or len(m) == 12]
                if candidates:
                    txn_id = max(candidates, key=len)
                    break

        return {
            "amount": final_amount,
            "date": extracted_date,
            "transaction_id": txn_id,
            "note": extracted_note,
            "raw_text": text
        }
    except Exception as e:
        print(f"OCR Error: {e}")
        return None

if __name__ == "__main__":
    # Test with a dummy path if needed
    # print(extract_payment_details("test_screenshot.jpg"))
    pass
