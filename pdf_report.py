import sqlite3
import datetime
import os
import tempfile
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

from db_connector import DBHandler

def generate_business_report(shop_name, period="Daily", is_native=False):
    """
    Generates a printable PDF report.
    Args:
        is_native (bool): If True, saves to Desktop (Local App). If False, saves to assets/reports (Web App).
    """
    if not FPDF:
        return "Error: FPDF library not found. Please install headers."

    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"HornERP_Analysis_{timestamp}.pdf"

        if is_native:
            # Native Mode: Save to Desktop
            desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
            filepath = os.path.join(desktop, filename)
        else:
            # Web Mode: Save to assets/reports
            base_dir = os.path.dirname(os.path.abspath(__file__))
            reports_dir = os.path.join(base_dir, "assets", "reports")
            if not os.path.exists(reports_dir):
                os.makedirs(reports_dir)
            filepath = os.path.join(reports_dir, filename)
        
        conn = DBHandler.get_connection()
        cursor = conn.cursor()
        
        # --- TIMEZONE FIX (Match POS) ---
        tz_offset = datetime.timezone(datetime.timedelta(hours=5))
        now_pak = datetime.datetime.now(tz_offset)
        today_str = now_pak.strftime("%Y-%m-%d") # YYYY-MM-DD
        month_str = now_pak.strftime("%Y-%m")    # YYYY-MM

        # Logic for Period
        # Generic SQL string casting
        date_col_cast = "CAST(date_created AS TEXT)"
        
        if period == "Daily":
            filter_clause = f"{date_col_cast} LIKE '{today_str}%'"
            period_label = f"Daily Report ({today_str})"
        elif period == "Weekly":
            start_date = (now_pak - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
            filter_clause = f"{date_col_cast} >= '{start_date}'"
            period_label = f"Weekly Report (Since {start_date})"
        elif period == "Monthly":
            filter_clause = f"{date_col_cast} LIKE '{month_str}%'"
            period_label = f"Monthly Report ({month_str})"
        else:
            filter_clause = f"{date_col_cast} LIKE '{today_str}%'"
            period_label = f"Daily Report ({today_str})"

        # Define p_filter immediately for JOINs
        p_filter = filter_clause.replace('date_created', 's.date_created').replace('CAST(s.date_created AS TEXT)', f"CAST(s.date_created AS TEXT)")

        # 1. Stats (Revenue for Period - NET)
        cursor.execute(f"SELECT SUM(total_amount) FROM offline_sales WHERE {filter_clause}")
        res = cursor.fetchone()
        revenue_amt = res[0] if res and res[0] else 0.0
        
        # 1b. Gross Sales (Sum of Items)
        cursor.execute(f"""
            SELECT SUM(i.quantity * i.price) 
            FROM offline_sale_items i
            JOIN offline_sales s ON i.sale_id = s.id
            WHERE {p_filter}
        """)
        res_gross = cursor.fetchone()
        gross_amt = res_gross[0] if res_gross and res_gross[0] else 0.0
        
        discounts = gross_amt - revenue_amt

        # 2. Daily Revenue Trend (Last 7 Days - Static Context)
        try:
             cursor.execute(f"""
                SELECT date(date_created) as d, SUM(total_amount) 
                FROM offline_sales 
                GROUP BY d
                ORDER BY d DESC LIMIT 7
            """)
        except:
             conn.rollback() # PG fallback
             cursor.execute("""
                SELECT date_created, total_amount FROM offline_sales ORDER BY id DESC LIMIT 50
             """)
             
        trend_data = cursor.fetchall()

        # 3. Top Products (For Period)
        cursor.execute(f"""
            SELECT i.product_name, SUM(i.quantity) as qty 
            FROM offline_sale_items i
            JOIN offline_sales s ON i.sale_id = s.id
            WHERE {p_filter}
            GROUP BY i.product_name 
            ORDER BY qty DESC LIMIT 5
        """)
        top_products = cursor.fetchall()
        
        # 4. Detailed List (For Period)
        query_period = f"""
            SELECT s.id, s.date_created, s.customer_name, i.product_name, i.quantity, i.price
            FROM offline_sale_items i
            JOIN offline_sales s ON i.sale_id = s.id
            WHERE {p_filter}
            ORDER BY s.id ASC
        """
        cursor.execute(query_period)
        sales_data = cursor.fetchall()
        
        conn.close()


        class PDFReport(FPDF):
            def header(self):
                # Logo area (colored strip)
                self.set_fill_color(26, 35, 126) # #1A237E (Deep Blue)
                self.rect(0, 0, 210, 25, 'F') # Increased height slightly
                
                self.set_y(5) # Start text a bit down
                self.set_font('Arial', 'B', 20)
                self.set_text_color(255, 255, 255)
                self.cell(0, 8, shop_name, 0, 1, 'C')
                
                self.set_font('Arial', 'I', 10)
                self.set_text_color(200, 200, 200)
                self.cell(0, 5, "Enterprise Management System", 0, 1, 'C')
                self.ln(10)
            
            def footer(self):
                self.set_y(-15)
                self.set_font('Arial', 'I', 8)
                self.set_text_color(128, 128, 128)
                self.cell(0, 10, f'Page {self.page_no()} - Generated by Horn ERP', 0, 0, 'C')

        pdf = PDFReport()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # --- EXECUTIVE SUMMARY ---
        pdf.set_text_color(26, 35, 126)
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, period_label, 0, 1, 'L')
        
        # Revenue Box (Expanded)
        pdf.set_fill_color(240, 248, 255) # AliceBlue
        pdf.set_draw_color(26, 35, 126)
        pdf.set_line_width(0.5)
        pdf.rect(10, pdf.get_y(), 190, 35, 'DF')
        
        pdf.set_y(pdf.get_y() + 5)
        
        # Row 1: Net Revenue (Big)
        pdf.set_font('Arial', 'B', 16)
        pdf.set_text_color(0, 100, 0) # Green
        pdf.cell(190, 10, f"Net Revenue: ${revenue_amt:,.2f}", 0, 1, 'C')
        
        # Row 2: Breakdown (Small)
        pdf.set_font('Arial', '', 11)
        pdf.set_text_color(80, 80, 80) # Grey
        pdf.cell(190, 6, f"Gross Sales: ${gross_amt:,.2f}   |   Discounts Given: -${discounts:,.2f}", 0, 1, 'C')
        pdf.set_font('Arial', 'I', 9)
        pdf.cell(190, 6, "(Net Revenue = Gross Sales - Discounts)", 0, 1, 'C')

        pdf.ln(10)

        # --- CHARTS ---
        temp_dir = tempfile.gettempdir()
        chart1_path = os.path.join(temp_dir, f"chart1_{timestamp}.png")
        chart2_path = os.path.join(temp_dir, f"chart2_{timestamp}.png")

        # Layout: Row of 2 charts
        y_charts = pdf.get_y()
        
        # Chart 1
        if trend_data:
            # Safe extraction
            dates = []
            revs = []
            for row in trend_data:
                # row could be ('2025-01-01', 100) or ('2025-01-01 10:00:00', 100)
                try: d_str = str(row[0])[:10]
                except: d_str = "?"
                val = row[1] or 0
                dates.append(d_str[5:]) # MM-DD
                revs.append(val)
                
            dates = dates[::-1]
            revs = revs[::-1]
            
            plt.figure(figsize=(5, 3.5)) # Compact
            plt.bar(dates, revs, color='#1A237E', alpha=0.8)
            plt.title('Revenue Trend', fontsize=10, fontweight='bold', color='#1A237E')
            plt.xticks(fontsize=8)
            plt.yticks(fontsize=8)
            plt.tight_layout()
            plt.savefig(chart1_path, dpi=100)
            plt.close()
            pdf.image(chart1_path, x=10, y=y_charts, w=90)
        else:
             pdf.rect(10, y_charts, 90, 60)
             pdf.text(35, y_charts+30, "No Trend Data")

        # Chart 2
        if top_products:
            sh = sorted(top_products, key=lambda x: x[1])
            labels = [x[0][:15] for x in sh]
            values = [x[1] for x in sh]
            plt.figure(figsize=(5, 3.5))
            plt.barh(labels, values, color='#009688', alpha=0.8)
            plt.title('Top Products', fontsize=10, fontweight='bold', color='#009688')
            plt.xticks(fontsize=8)
            plt.yticks(fontsize=8)
            plt.tight_layout()
            plt.savefig(chart2_path, dpi=100)
            plt.close()
            pdf.image(chart2_path, x=110, y=y_charts, w=90)
        
        pdf.set_y(y_charts + 70) # Move past charts

        # --- DETAILED TRANSACTIONS ---
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Arial', 'B', 14)
        pdf.set_fill_color(230, 230, 250) # Lavender
        pdf.cell(0, 10, "Transaction Details", 0, 1, 'L', fill=True)
        pdf.ln(2)

        # Header
        pdf.set_font('Arial', 'B', 9)
        pdf.set_fill_color(26, 35, 126)
        pdf.set_text_color(255, 255, 255)
        
        # Adjusted Model: Add "ID" column
        col_widths = [15, 40, 40, 45, 15, 15, 20] 
        headers = ["ID", "Time", "Customer", "Item", "Qty", "Price", "Total"]
        
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 7, h, 1, 0, 'C', fill=True)
        pdf.ln()

        # Data
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Arial', '', 8)
        
        fill = False
        pdf.set_fill_color(245, 248, 250) # Very light blue
        
        for row in sales_data:
            # row: id, date, cust, prod, qty, price
            # Need strict extraction
            sid = str(row[0])
            dt = str(row[1])[11:16] if row[1] else "" # extract HH:MM from YYYY-MM-DD HH:MM:SS
            cust = row[2][:20]
            prod = row[3][:25]
            qty = str(row[4])
            price = f"{row[5]:.2f}"
            total = f"{(row[4] * row[5]):.2f}"
            
            pdf.cell(col_widths[0], 6, sid, 1, 0, 'C', fill=fill)
            pdf.cell(col_widths[1], 6, dt, 1, 0, 'C', fill=fill)
            pdf.cell(col_widths[2], 6, cust, 1, 0, 'L', fill=fill)
            pdf.cell(col_widths[3], 6, prod, 1, 0, 'L', fill=fill)
            pdf.cell(col_widths[4], 6, qty, 1, 0, 'C', fill=fill)
            pdf.cell(col_widths[5], 6, price, 1, 0, 'R', fill=fill)
            pdf.cell(col_widths[6], 6, total, 1, 0, 'R', fill=fill)
            pdf.ln()
            fill = not fill

        pdf.output(filepath)
        
        if os.path.exists(chart1_path): os.remove(chart1_path)
        if os.path.exists(chart2_path): os.remove(chart2_path)
            
        print(f"Generated PDF: {filepath}")
        return filename
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}"

# Placeholder for barcode - kept simple
def generate_barcode_sheet(barcode_data, product_name, price, quantity):
    return "Error: Barcode logic skipped for Cloud Update"
