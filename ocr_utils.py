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
        
        # Also try without thresholding if text is empty? 
        # For now, let's stick to one good path.

        # Regex patterns for Amount
        # We try to be careful about leading characters that might be misread symbols
        amount_patterns = [
            r'(?:₹|INR|Amount|Paid|Total|Amt|Sum|Value)[\s:]*([1-9][\d,]+(?:\.\d{2})?)', # Starts with 1-9
            r'Successfully\s+paid[\s:]*([1-9][\d,]+(?:\.\d{2})?)',
            r'Rs\.?[\s]*([1-9][\d,]+(?:\.\d{2})?)',
            r'([\d,]+\.\d{2})' # Any number with two decimal places
        ]
        
        all_amounts = []
        for pattern in amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                try:
                    # Clean and convert
                    val = float(m.replace(',', ''))
                    # Sanity check: Amount should probably be > 0 and not too huge for a fee
                    if 0 < val < 100000:
                        all_amounts.append(val)
                except ValueError:
                    continue
        
        final_amount = None
        if all_amounts:
            # If multiple amounts found, the one with decimal places is often the most accurate
            # or just take the max if they are all valid.
            final_amount = max(all_amounts)

        # Regex pattern for Transaction ID
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
            "transaction_id": txn_id,
            "raw_text": text
        }
    except Exception as e:
        print(f"OCR Error: {e}")
        return None

if __name__ == "__main__":
    # Test with a dummy path if needed
    pass
