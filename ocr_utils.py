import pytesseract
from PIL import Image
import re
import os

def extract_payment_details(image_path):
    """
    Extracts amount and transaction ID from a payment screenshot using OCR.
    Returns a list of payment detail dictionaries.
    """
    try:
        # Load image
        original_img = Image.open(image_path)
        
        # Try different preprocessing strategies.
        # invert=True handles dark-mode UPI share cards (white text on dark background):
        # invert first so dark bg → light, white text → dark, then threshold normally.
        strategies = [
            {"threshold": 140, "psm": 6,  "invert": False},
            {"threshold": 180, "psm": 6,  "invert": False},
            {"threshold": None, "psm": 6,  "invert": False},  # grayscale only
            {"threshold": 140, "psm": 3,  "invert": False},  # auto layout
            {"threshold": 160, "psm": 11, "invert": False},  # sparse text
            {"threshold": 140, "psm": 4,  "invert": False},  # single column
            # dark-background variants (PhonePe/GPay share cards)
            {"threshold": 140, "psm": 6,  "invert": True},
            {"threshold": 100, "psm": 6,  "invert": True},
            {"threshold": None, "psm": 6,  "invert": True},  # invert grayscale only
            {"threshold": 140, "psm": 11, "invert": True},
        ]

        all_found_payments = []
        seen_txn_ids = set()
        raw_texts = []

        for strategy in strategies:
            img = original_img.copy()
            # Convert to grayscale
            img = img.convert('L')

            # Invert before thresholding for dark-background images
            if strategy.get("invert"):
                img = img.point(lambda p: 255 - p)

            # Optional thresholding
            if strategy["threshold"] is not None:
                img = img.point(lambda p: 255 if p > strategy["threshold"] else 0)

            # Optional scaling
            width, height = img.size
            if width < 1000:
                img = img.resize((width * 2, height * 2), Image.Resampling.LANCZOS)

            custom_config = f'--oem 3 --psm {strategy["psm"]}'
            text = pytesseract.image_to_string(img, config=custom_config)
            raw_texts.append(text)
            
            payments = parse_payment_text(text)
            
            for p in payments:
                if p["transaction_id"] and p["transaction_id"] not in seen_txn_ids:
                    seen_txn_ids.add(p["transaction_id"])
                    all_found_payments.append(p)
                elif not p["transaction_id"] and p["amount"]:
                    # Deduplicate by amount with 2% tolerance (guards against OCR variance, e.g. 5500 vs 5506)
                    def _close(a, b): return abs(a - b) / max(a, 1) < 0.02
                    if not any(ap["amount"] and _close(ap["amount"], p["amount"]) for ap in all_found_payments):
                        all_found_payments.append(p)
            
            # If we found at least one solid payment, we can potentially stop early 
            # but for multiple payments, better to run a few strategies
            if len(all_found_payments) >= 1 and strategy["psm"] == 6:
                # If we found something with default psm, maybe that's enough?
                # Actually, let's keep going for a few more to be sure.
                pass
                
        if not all_found_payments:
            return []
            
        # Add raw_text to the first payment or all? 
        # For simplicity, let's just return the list and the caller can handle it.
        # We'll attach the aggregate raw text to each.
        full_raw_text = "\n---\n".join(raw_texts)
        for p in all_found_payments:
            p["raw_text"] = full_raw_text
            
        return all_found_payments
    except Exception as e:
        print(f"OCR Error: {e}")
        return []

def extract_pdf_details(pdf_path):
    """
    Extracts text from a PDF and parses payment details.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        
        payments = parse_payment_text(text)
        for p in payments:
            p["raw_text"] = text
        return payments
    except Exception as e:
        print(f"PDF Error: {e}")
        return []

def parse_payment_text(text):
    """
    Parses raw text (from OCR or messages) for payment details.
    Returns a list of dictionaries.
    """
    if not text:
        return []

    # Check if it's likely a payment screenshot
    payment_keywords = ['successful', 'transaction', 'utr', 'upi', 'paid', 'sent', 'debited', 'received', 'transfer', 'reference', 'fee', 'payment', 'amt', 'total', 'phonepe', 'gpay', 'google pay', 'paytm']
    text_lower = text.lower()
    is_likely_payment = any(kw in text_lower for kw in payment_keywords)
    
    # --- TRANSACTION ID EXTRACTION ---
    txn_regex = r'(?:Transaction ID|Txn ID|Ref No|UTR|UPI Ref No|Reference|Reference No|Google Pay Transaction ID|PhonePe Transaction ID|Ref|ID)[\s:]*([A-Z0-9]{10,})|(?<!\d)(\d{12})(?!\d)|\b(T\d{15,25})\b'
    
    all_txn_ids = []
    for match in re.finditer(txn_regex, text, re.IGNORECASE):
        m = match.group(1) or match.group(2) or match.group(3)
        if not m or m in all_txn_ids:
            continue
        has_digits = any(c.isdigit() for c in m)
        has_alpha = any(c.isalpha() for c in m)
        # valid = alphanumeric mix (T260..., UTR-style), or pure 12-digit UTR
        if (has_alpha and has_digits) or (not has_alpha and len(m) == 12):
            all_txn_ids.append(m)

    # --- AMOUNT EXTRACTION ---
    amount_regex = r'(?:Successfully\s+paid|Paid|Sent|Amount|Total\s+Paid|Fee|Transfer\s+of|Payment\s+of|Debited\s+from)[\s:]*(?:₹|INR|Rs\.?|~|z|2|«)?\s*([\d,]+(?:\.\d{2})?)'
    
    found_amounts = []
    for match in re.finditer(amount_regex, text, re.IGNORECASE):
        val_str = match.group(1).replace(',', '')
        try:
            val = float(val_str)
            if 10 <= val < 100000:
                found_amounts.append(val)
        except ValueError:
            continue
                
    if not found_amounts:
        general_amount_patterns = [
            # % # = are common OCR misreads of ₹ on dark backgrounds; @ removed (false-matches UPI IDs)
            r'(?:₹|INR|Rs\.?|~|z|«|%|#|=)[\s:]*([\d,]+(?:\.\d{2})?)',
            r'([\d,]+\.\d{2})',
        ]
        for pattern in general_amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                try:
                    val = float(m.replace(',', ''))
                    if 10 <= val < 100000 and val not in [2024, 2025, 2026] and val not in found_amounts:
                        found_amounts.append(val)
                except ValueError:
                    continue

    # --- DATE EXTRACTION ---
    date_patterns = [
        r'(?:Date|Paid on|Time|Value Date|Timestamp)[\s:]*(\d{1,2}[/\-\s](?:\d{1,2}|[A-Za-z]{3,})[/\-\s]\d{2,4})',
        r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})',
        r'(\d{2}/\d{2}/\d{2,4})',
    ]
    extracted_date = None
    for pattern in date_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            extracted_date = matches[0].strip()
            break

    # --- PAIRING ---
    payments = []
    if all_txn_ids:
        for i, tid in enumerate(all_txn_ids):
            amt = found_amounts[i] if i < len(found_amounts) else (found_amounts[0] if found_amounts else None)
            payments.append({
                "amount": amt,
                "date": extracted_date,
                "transaction_id": tid,
                "note": None
            })
    elif found_amounts:
        for amt in found_amounts:
            payments.append({
                "amount": amt,
                "date": extracted_date,
                "transaction_id": None,
                "note": None
            })
            
    return payments

if __name__ == "__main__":
    # Test
    sample = "Paid ₹3,000 to S DEEKSHITH using PhonePe. Transaction ID T2606052031383091795483"
    print(parse_payment_text(sample))
