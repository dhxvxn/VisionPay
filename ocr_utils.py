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
        original_img = Image.open(image_path)
        
        # Try different preprocessing strategies
        strategies = [
            {"threshold": 140, "psm": 6},
            {"threshold": 180, "psm": 6},
            {"threshold": None, "psm": 6}, # Grayscale only
            {"threshold": 140, "psm": 3}, # Auto
            {"threshold": 160, "psm": 11}, # Sparse text
        ]
        
        best_details = None
        max_score = -1
        
        for strategy in strategies:
            img = original_img.copy()
            # Convert to grayscale
            img = img.convert('L')
            
            # Optional thresholding
            if strategy["threshold"] is not None:
                img = img.point(lambda p: 255 if p > strategy["threshold"] else 0)
            
            # Optional scaling
            width, height = img.size
            if width < 1000:
                img = img.resize((width * 2, height * 2), Image.Resampling.LANCZOS)

            custom_config = f'--oem 3 --psm {strategy["psm"]}'
            text = pytesseract.image_to_string(img, config=custom_config)
            
            details = _parse_text_for_details(text)
            
            # Scoring the result
            score = 0
            if details["amount"]: score += 10
            if details["transaction_id"]: score += 5
            if details["date"]: score += 2
            
            if score > max_score:
                max_score = score
                best_details = details
                best_details["raw_text"] = text
            
            if max_score >= 15: # Found amount and txn_id, good enough
                break
                
        return best_details
    except Exception as e:
        print(f"OCR Error: {e}")
        return None

def _parse_text_for_details(text):
    # Check if it's likely a payment screenshot
    payment_keywords = ['successful', 'transaction', 'utr', 'upi', 'paid', 'sent', 'debited', 'received', 'transfer', 'reference', 'fee', 'payment', 'amt', 'total']
    text_lower = text.lower()
    is_likely_payment = any(kw in text_lower for kw in payment_keywords)
    
    # Regex patterns for Amount with high priority keywords
    priority_amount_patterns = [
        r'Successfully\s+paid[\s:]*(?:₹|INR|Rs\.?|~|z|2|«)?\s*([\d,]+(?:\.\d{2})?)',
        r'Paid\s+to[\s:]*(?:.*?)[\s:]*(?:₹|INR|Rs\.?|~|z|2|«)?\s*([\d,]+(?:\.\d{2})?)',
        r'Sent\s+([\d,]+(?:\.\d{2})?)',
        r'Amount[\s:]*(?:₹|INR|Rs\.?|~|z|2|«)?\s*([\d,]+(?:\.\d{2})?)',
        r'Total\s+Paid[\s:]*(?:₹|INR|Rs\.?|~|z|2|«)?\s*([\d,]+(?:\.\d{2})?)',
        r'Fee[\s:]*(?:₹|INR|Rs\.?|~|z|2|«)?\s*([\d,]+(?:\.\d{2})?)',
    ]
    
    # Try priority patterns first
    for pattern in priority_amount_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                val = float(m.replace(',', ''))
                if 10 <= val < 100000:
                    return _finalize_details(val, text)
            except ValueError:
                continue
                
    # If no priority, but it IS a likely payment, look for ANY amount with currency symbol
    general_amount_patterns = [
        r'(?:₹|INR|Rs\.?|~|z|«|@)[\s:]*([\d,]+(?:\.\d{2})?)',
        r'([\d,]+\.\d{2})',
    ]
    
    all_amounts = []
    for pattern in general_amount_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                val = float(m.replace(',', ''))
                if 10 <= val < 100000 and val not in [2024, 2025, 2026]:
                    all_amounts.append(val)
            except ValueError:
                continue
    
    if not all_amounts and is_likely_payment:
        potential_numbers = re.findall(r'(?<!\d)(?:₹|Rs\.?|~|z|«)?\s*([\d,]{3,})(?!\d)', text)
        for m in potential_numbers:
            try:
                val = float(m.replace(',', ''))
                if 100 <= val < 100000 and val not in [2024, 2025, 2026]:
                    all_amounts.append(val)
            except ValueError:
                continue

    final_amount = None
    if all_amounts:
        # If it's a likely payment, take the first one found or max
        final_amount = max(all_amounts)

    return _finalize_details(final_amount, text)

def _finalize_details(amount, text):
    # Transaction ID
    txn_patterns = [
        r'(?:Transaction ID|Txn ID|Ref No|UTR|UPI Ref No|Reference|Reference No)[\s:]*([A-Z0-9]{10,})',
        r'(?<!\d)(\d{12})(?!\d)', # UTR is usually 12 digits
        r'ID[:\s]*([A-Z0-9]{10,})'
    ]
    txn_id = None
    for pattern in txn_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            candidates = [m for m in matches if any(c.isalpha() for c in m) or len(m) == 12]
            if candidates:
                txn_id = max(candidates, key=len)
                break

    # Date
    date_patterns = [
        r'(?:Date|Paid on|Time|Value Date|Timestamp)[\s:]*(\d{1,2}[/\-\s](?:\d{1,2}|[A-Za-z]{3,})[/\-\s]\d{2,4})',
        r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})',
        r'(\d{2}/\d{2}/\d{2,4})',
        r'(\d{4}-\d{2}-\d{2})'
    ]
    extracted_date = None
    for pattern in date_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            extracted_date = matches[0].strip()
            break

    # Note
    note_patterns = [
        r'(?:Note|Message|Remark|Description|For)[\s:]+([^\n]+)',
        r'Add a note[\s:]+([^\n]+)'
    ]
    extracted_note = None
    for pattern in note_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            extracted_note = matches[0].strip()
            break

    return {
        "amount": amount,
        "date": extracted_date,
        "transaction_id": txn_id,
        "note": extracted_note
    }

if __name__ == "__main__":
    # Test with a dummy path if needed
    # print(extract_payment_details("test_screenshot.jpg"))
    pass
