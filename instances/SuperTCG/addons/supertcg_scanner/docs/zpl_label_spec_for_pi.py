# SuperTCG ZPL Label Specification
# For Raspberry Pi Implementation
# Label size: 1.5" x 0.5" @ 203dpi (304 x 101 dots)
# Printer: Zebra GK420d / ZD410 / ZD420

# ═══════════════════════════════════════════════════════════════
# IMPORTS (Python)
# ═══════════════════════════════════════════════════════════════

# The Pi needs these standard library modules:
# import urllib.request  # to send ZPL to printer
# import json            # to parse card data

# ═══════════════════════════════════════════════════════════════
# LABEL GENERATOR FUNCTION
# ═══════════════════════════════════════════════════════════════

def generate_card_zpl(card_data):
    """Generate ZPL for a single card label.
    
    Args:
        card_data: dict with these fields:
            - card_name: str (e.g., "Charizard")
            - remark: str (condition, e.g., "LP", "NM")
            - set_code: str (e.g., "BS", "DP")
            - card_number: str (e.g., "4/102")
            - printing: str (e.g., "Normal", "Reverse Holofoil")
            - sales_price: float (e.g., 15.50)
            - unique_barcode: str (EAN-13 barcode, e.g., "2012345678901")
            
    Returns:
        str: Complete ZPL command string
    """
    
    # ── Sanitize text (remove ZPL control characters) ──
    def safe_text(text, max_len=30):
        t = str(text or '').replace("^", " ").replace("~", " ")
        # Strip non-ASCII to prevent encoding issues
        t = t.encode("ascii", "ignore").decode("ascii")
        return t[:max_len]
    
    # ── Extract & format data ──
    raw_name = safe_text(card_data.get('card_name'), 30)
    price = float(card_data.get('sales_price', 0) or 0)
    price_str = f"EUR{price:,.2f}".replace(",", ".") if price else "EUR0.00"
    
    remark = safe_text(card_data.get('remark'), 6)
    set_code = safe_text(card_data.get('set_code'), 6)
    card_number = safe_text(card_data.get('card_number'), 8)
    printing = safe_text(card_data.get('printing'), 10)
    barcode = str(card_data.get('unique_barcode') or card_data.get('product_id') or '0')
    
    # ── Label Dimensions ──
    LABEL_W = 304    # 1.5" @ 203dpi
    LABEL_H = 101    # 0.5" @ 203dpi
    
    # ── Font Sizes ──
    PRICE_FONT_H = 34    # Height of price text (dots)
    PRICE_FONT_W = 20    # Width of price text per char (dots)
    NAME_FONT_H = 22     # Height of card name
    NAME_FONT_W = 12     # Width of card name per char
    SMALL_FONT_H = 18    # Height of condition/set/printing
    SMALL_FONT_W = 14    # Width of small text per char
    
    # ── Positions ──
    LEFT_MARGIN = 22     # Left edge padding
    COND_X = 158         # Center column for condition/printing
    RIGHT_MARGIN = 2     # Right edge padding
    
    # Right-align price: calculate x position
    price_width = len(price_str) * PRICE_FONT_W
    price_x = LABEL_W - RIGHT_MARGIN - price_width
    if price_x < 170:
        price_x = 170  # Minimum: don't overlap with name
    
    # Truncate name to fit before price
    max_name_width = price_x - LEFT_MARGIN - 8
    max_name_chars = max_name_width // NAME_FONT_W
    if max_name_chars < 6:
        max_name_chars = 6
    name = raw_name[:max_name_chars] if len(raw_name) > max_name_chars else raw_name
    
    # Row 2: Set + Number (e.g., "BS  4/102")
    set_num = f"{set_code}  {card_number}".strip() if (set_code or card_number) else ""
    
    # ═══════════════════════════════════════════════════════
    # ZPL OUTPUT
    # ═══════════════════════════════════════════════════════
    zpl = f"""^XA
^PW{LABEL_W}
^LL{LABEL_H}
^LH0,0
^CI28

; Row 1 — Card Name (left), Condition (center), Price (right, biggest)
^FO{LEFT_MARGIN},12^A0N,{NAME_FONT_H},{NAME_FONT_W}^FD{name}^FS
^FO{COND_X},14^A0N,{SMALL_FONT_H},{SMALL_FONT_W}^FD{remark}^FS
^FO{price_x},12^A0N,{PRICE_FONT_H},{PRICE_FONT_W}^FD{price_str}^FS

; Row 2 — Set Code + Card Number (left), Printing (center)
^FO{LEFT_MARGIN},46^A0N,{SMALL_FONT_H},{SMALL_FONT_W}^FD{set_num}^FS
^FO{COND_X},46^A0N,{SMALL_FONT_H},{SMALL_FONT_W}^FD{printing}^FS

; Row 3 — Barcode (thick bars for better scanning)
^FO{LEFT_MARGIN},68^BY4^BCN,32,N,N,N,A^FD{barcode}^FS

^XZ"""
    
    return zpl


# ═══════════════════════════════════════════════════════════════
# EXAMPLE USAGE
# ═══════════════════════════════════════════════════════════════

example_card = {
    'card_name': 'Charizard',
    'remark': 'LP',
    'set_code': 'BS',
    'card_number': '4/102',
    'printing': 'Normal',
    'sales_price': 150.00,
    'unique_barcode': '2012345678901',
}

# Generate ZPL
zpl_code = generate_card_zpl(example_card)
print(zpl_code)

# Send to printer via raw TCP (port 9100 is standard for Zebra)
# import socket
# printer_ip = '192.168.1.100'
# with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#     s.connect((printer_ip, 9100))
#     s.sendall(zpl_code.encode('utf-8'))


# ═══════════════════════════════════════════════════════════════
# LABEL LAYOUT VISUAL
# ═══════════════════════════════════════════════════════════════
#
#  ┌─────────────────────────────────────────────────────┐  ▲
#  │ Charizard              LP           EUR150.00       │  │
#  │ (name, truncated)   (condition)     (price, right)  │  │ 0.5"
#  │ BS  4/102         Normal                            │  │
#  │ (set+number)      (printing)                        │  │
#  │ ||||||||||||||||||||||||||||||||||||||||            │  │
#  │ (barcode, Code 128, thick bars)                     │  ▼
#  └─────────────────────────────────────────────────────┘
#  ◄────────────────────── 1.5" ─────────────────────────►
#
# DPI: 203 dots per inch
# Width:  304 dots (1.5")
# Height: 101 dots (0.5")


# ═══════════════════════════════════════════════════════════════
# ZPL COMMAND REFERENCE
# ═══════════════════════════════════════════════════════════════
#
# ^XA          = Start label
# ^XZ          = End label
# ^PW304       = Print width: 304 dots
# ^LL101       = Label length: 101 dots
# ^LH0,0       = Label home position (0,0)
# ^CI28        = UTF-8 encoding
#
# ^FOx,y       = Field origin (x,y position in dots)
# ^FDtext^FS   = Field data (the text to print)
#
# ^A0N,h,w     = Font: Arial, Normal orientation, height, width
#                h=height in dots, w=width in dots
#
# ^BY4         = Barcode field default: module width 4 dots
# ^BCN,h,d,f,g = Barcode: Code 128, Normal, height h dots
#                d=interpretation line (N=no), f=fixed print ratio
#                g=UCC check digit (A=automatic)
#
# The barcode uses Code 128 (^BCN) which supports alphanumeric.
# EAN-13 barcodes (20xxxxxxxxx) scan correctly with this format.


# ═══════════════════════════════════════════════════════════════
# IMPORTANT NOTES
# ═══════════════════════════════════════════════════════════════
#
# 1. BARCODE FORMAT
#    - Use EAN-13 format: 20 + 10-digit identifier + 1 check digit = 13 digits
#    - Prefix "20" is internal (not a real GS1 country code)
#    - Generate check digit using the same algorithm as the Odoo backend
#    - Or just use the barcode string provided by Odoo in the card data
#
# 2. PRICE FORMAT
#    - Always format as "EURxx.xx" (e.g., "EUR150.00", "EUR0.50")
#    - Use dot as decimal separator
#    - Right-align: calculate x position based on string length
#
# 3. TEXT SANITIZATION
#    - Remove "^" and "~" characters (ZPL control characters)
#    - Strip non-ASCII characters to prevent encoding issues
#    - Truncate long names to fit the label width
#
# 4. FONT SIZES
#    - Price: 34h x 20w dots (largest, right side)
#    - Name: 22h x 12w dots (left side, truncated if needed)
#    - Small text: 18h x 14w dots (condition, set, printing)
#
# 5. MULTIPLE LABELS
#    - For multiple cards, generate one ^XA...^XZ block per card
#    - Concatenate with newlines: zpl1 + "\n" + zpl2 + "\n" + ...
#    - Send all at once to the printer
#
# 6. PRINTER CONNECTION
#    - Zebra printers listen on TCP port 9100 by default
#    - Send raw ZPL text via socket connection
#    - No driver needed — just raw TCP to port 9100
