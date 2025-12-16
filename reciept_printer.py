import datetime
import os
try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

def print_receipt(data):
    # Unpack data
    sale_id = data.get('receipt_no', '0')
    items = data.get('items', [])
    total_amount = data.get('total', 0.0)
    shop_name = data.get('shop_name', 'Shop')
    address = data.get('address', '')
    phone = data.get('phone', '')
    currency = data.get('currency', '$')
    customer_name = data.get('customer', 'Walk-in')
    
    # If FPDF is missing, fall back to console print simulation
    if not FPDF:
        print("Error: FPDF not installed. Cannot generate receipt PDF.")
        filename = f"receipt_{sale_id}.txt"
        return filename

    class Receipt(FPDF):
        def header(self):
            # Header
            self.set_font('Arial', 'B', 12)
            self.cell(0, 10, str(shop_name), 0, 1, 'C')
            self.set_font('Arial', '', 9)
            if address: self.cell(0, 5, str(address), 0, 1, 'C')
            if phone: self.cell(0, 5, f"Tel: {str(phone)}", 0, 1, 'C')
            self.line(10, self.get_y()+2, 70, self.get_y()+2)
            self.ln(5)

    # 80mm width typical for receipts, height auto
    pdf = Receipt(format=(80, 200)) 
    pdf.set_margins(5, 5, 5)
    pdf.add_page()
    
    # Timestamp
    timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5))).strftime("%Y-%m-%d %H:%M:%S")
    
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 5, f"Date: {timestamp}", 0, 1)
    pdf.cell(0, 5, f"Receipt #: {sale_id}", 0, 1)
    pdf.cell(0, 5, f"Cashier: {data.get('cashier', '')}", 0, 1)
    pdf.cell(0, 5, f"Customer: {str(customer_name)}", 0, 1)
    
    pdf.ln(2)
    pdf.line(5, pdf.get_y(), 75, pdf.get_y())
    pdf.ln(2)
    
    # Items Header
    pdf.set_font('Arial', 'B', 9)
    pdf.cell(35, 5, "Item", 0, 0)
    pdf.cell(10, 5, "Qty", 0, 0, 'C')
    pdf.cell(25, 5, "Total", 0, 1, 'R')
    pdf.set_font('Arial', '', 9)
    
    # Items
    for item in items:
        name = str(item['name'])[:18] # Truncate for small width
        qty = str(item['qty'])
        # item['total'] is already calculated in pos.py, or calc here
        line_total = item.get('total', float(item['price']) * item['qty'])
        price_display = f"{currency}{line_total:.2f}"
        
        pdf.cell(35, 5, name, 0, 0)
        pdf.cell(10, 5, qty, 0, 0, 'C')
        pdf.cell(25, 5, price_display, 0, 1, 'R')
        
    pdf.ln(2)
    pdf.line(5, pdf.get_y(), 75, pdf.get_y())
    pdf.ln(2)
    
    # Totals Section
    pdf.set_font('Arial', '', 9)
    pdf.cell(50, 5, "Subtotal:", 0, 0, 'R')
    pdf.cell(20, 5, f"{currency}{data.get('subtotal', 0):.2f}", 0, 1, 'R')
    
    if data.get('discount', 0) > 0:
        pdf.cell(50, 5, "Discount:", 0, 0, 'R')
        pdf.cell(20, 5, f"-{currency}{data.get('discount', 0):.2f}", 0, 1, 'R')
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(50, 10, "TOTAL:", 0, 0, 'R')
    pdf.cell(20, 10, f"{currency}{total_amount:.2f}", 0, 1, 'R')
    
    pdf.set_font('Arial', '', 9)
    pdf.cell(50, 5, "Cash:", 0, 0, 'R')
    pdf.cell(20, 5, f"{currency}{data.get('cash', 0):.2f}", 0, 1, 'R')
    
    pdf.cell(50, 5, "Change:", 0, 0, 'R')
    pdf.cell(20, 5, f"{currency}{data.get('change', 0):.2f}", 0, 1, 'R')
    
    pdf.ln(5)

    # Footer
    pdf.set_font('Arial', 'I', 8)
    pdf.cell(0, 5, "Thank you for your business!", 0, 1, 'C')

    # Save logic
    file_timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5))).strftime("%Y%m%d_%H%M%S")
    filename = f"receipt_{sale_id}_{file_timestamp}.pdf"
    
    try:
        user_profile = os.environ.get('USERPROFILE') or os.path.expanduser("~")
        desktop_path = os.path.join(user_profile, "Desktop")
        if not os.path.exists(desktop_path): os.makedirs(desktop_path)
        filepath = os.path.join(desktop_path, filename)
    except:
        filepath = filename

    print(f"Generating PDF Receipt: {filepath}")
    pdf.output(filepath)
    return filepath
