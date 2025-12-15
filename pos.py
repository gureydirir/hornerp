import flet as ft
import sqlite3
import os
import datetime
import csv
import webbrowser
import random
from urllib.parse import quote

# --- CLOUD DATABASE SUPPORT ---
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

# --- SAFE IMPORTS ---
try:
    import openpyxl 
    from openpyxl.styles import Font, PatternFill, Alignment
except ImportError: openpyxl = None

try:
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.graphics.barcode import code128
except ImportError: pdf_canvas = None

print("--------------------------------------------------")
print("🚀 STARTING HORN ERP - VERSION 24.0 (CLOUD HYBRID)")
print("--------------------------------------------------")

# --- GLOBAL STATE ---
app_data = {
    "user": {"name": "", "role": "", "id": 0},
    "customer": {"id": 0, "name": "Walk-in Client", "points": 0, "debt": 0},
    "cart": {}
}

# --- THEME COLORS ---
PRIMARY = "#1565C0" 
SECONDARY = "#00BCD4"
BG = "#F4F6F8"
WHITE = "#FFFFFF"
ERROR = "#C62828"
SUCCESS = "#2E7D32"
WARNING = "#F9A825"
CARD_SHADOW = ft.BoxShadow(blur_radius=15, color="#1A000000")

# --- DATABASE MANAGER (THE MAGIC ENGINE) ---
class DB:
    @staticmethod
    def get_conn():
        # CHECK: Are we on Render? (Look for DATABASE_URL)
        db_url = os.environ.get("DATABASE_URL")
        if db_url and psycopg2:
            return psycopg2.connect(db_url)
        else:
            return sqlite3.connect("horn.db", timeout=30)

    @staticmethod
    def execute(sql, params=(), fetch_one=False, fetch_all=False):
        conn = DB.get_conn()
        cur = conn.cursor()
        
        # TRANSLATOR: Convert SQLite '?' to Postgres '%s' if on Cloud
        if os.environ.get("DATABASE_URL"):
            sql = sql.replace("?", "%s")
        
        try:
            cur.execute(sql, params)
            conn.commit()
            
            res = None
            if fetch_one: res = cur.fetchone()
            if fetch_all: res = cur.fetchall()
            
            conn.close()
            return res
        except Exception as e:
            print(f"DB Error: {e} | SQL: {sql}")
            return None

def main(page: ft.Page):
    page.title = "Horn ERP - Cloud Edition"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = BG
    page.padding = 0
    # page.window_maximized = True # Commented out for Web compatibility
    
    # --- 1. DATABASE INIT ---
    def init_db():
        tables = [
            "CREATE TABLE IF NOT EXISTS products (barcode TEXT PRIMARY KEY, name TEXT, price REAL, stock INTEGER DEFAULT 0, expiry_date TEXT)",
            "CREATE TABLE IF NOT EXISTS offline_sales (id SERIAL PRIMARY KEY, total_amount REAL, cashier_name TEXT, customer_name TEXT, payment_method TEXT, date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)", # Changed for Postgres compat
            "CREATE TABLE IF NOT EXISTS offline_sale_items (id SERIAL PRIMARY KEY, sale_id INTEGER, product_name TEXT, price REAL, quantity INTEGER, status TEXT DEFAULT 'sold')",
            "CREATE TABLE IF NOT EXISTS stock_logs (id SERIAL PRIMARY KEY, date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, product_name TEXT, change_amount INTEGER, reason TEXT, user_role TEXT)",
            "CREATE TABLE IF NOT EXISTS shop_settings (key TEXT PRIMARY KEY, value TEXT)",
            "CREATE TABLE IF NOT EXISTS expenses (id SERIAL PRIMARY KEY, date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, description TEXT, amount REAL, category TEXT)",
            "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT, pin TEXT, role TEXT)",
            "CREATE TABLE IF NOT EXISTS customers (id SERIAL PRIMARY KEY, name TEXT, phone TEXT UNIQUE, points INTEGER DEFAULT 0, debt REAL DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS suppliers (id SERIAL PRIMARY KEY, name TEXT, phone TEXT, address TEXT)",
            "CREATE TABLE IF NOT EXISTS attendance (id SERIAL PRIMARY KEY, user_name TEXT, action TEXT, date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ]
        
        # SQLite vs Postgres Table Creation Differences fix
        if not os.environ.get("DATABASE_URL"):
            # Revert SERIAL to AUTOINCREMENT for Local SQLite
            tables = [t.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT") for t in tables]

        for t in tables: DB.execute(t)

        # Defaults
        if DB.execute("SELECT count(*) FROM users", fetch_one=True)[0] == 0:
            DB.execute("INSERT INTO users (username, pin, role) VALUES (?, ?, ?)", ('Admin', '9999', 'Manager'))
            DB.execute("INSERT INTO users (username, pin, role) VALUES (?, ?, ?)", ('Cashier 1', '1234', 'Cashier'))
        
        if DB.execute("SELECT count(*) FROM shop_settings", fetch_one=True)[0] == 0:
            DB.execute("INSERT INTO shop_settings VALUES (?, ?)", ('shop_name', 'HORN ERP'))
            DB.execute("INSERT INTO shop_settings VALUES (?, ?)", ('currency', '$'))
            DB.execute("INSERT INTO shop_settings VALUES (?, ?)", ('rate', '26000'))

    init_db()

    # --- 2. HELPERS ---
    def get_setting(key):
        res = DB.execute("SELECT value FROM shop_settings WHERE key=?", (key,), fetch_one=True)
        return res[0] if res else ""

    def show_snack(msg, color=SUCCESS):
        page.snack_bar = ft.SnackBar(ft.Text(msg), bgcolor=color); page.snack_bar.open = True; page.update()

    def log_activity(p_name, amount, reason):
        user = app_data["user"]["name"] if app_data["user"]["name"] else "System"
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        DB.execute("INSERT INTO stock_logs (date_time, product_name, change_amount, reason, user_role) VALUES (?, ?, ?, ?, ?)", (now, p_name, amount, reason, user))

    # --- 3. WHATSAPP & BARCODES ---
    def send_whatsapp(phone, sale_id, total, items):
        if not phone: show_snack("No phone number found!", ERROR); return
        clean_phone = phone.replace(" ", "").replace("+", "")
        if len(clean_phone) < 10: clean_phone = "252" + clean_phone 
        shop = get_setting('shop_name')
        msg = f"*{shop} Receipt*\nSale ID: #{sale_id}\nDate: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n----------------\n"
        for i in items: msg += f"{i['name']} x{i['qty']} - ${i['price']*i['qty']:.2f}\n"
        msg += "----------------\n"
        msg += f"*TOTAL: ${total:.2f}*\nThank you!"
        url = f"https://wa.me/{clean_phone}?text={quote(msg)}"
        webbrowser.open(url); show_snack("✅ WhatsApp Opened")

    def generate_barcode_pdf(e):
        if not pdf_canvas: show_snack("PDF Engine Missing", ERROR); return
        try:
            path = os.path.join(os.environ['USERPROFILE'], 'Desktop', "Shelf_Labels.pdf")
            c = pdf_canvas.Canvas(path, pagesize=A4); w, h = A4
            items = DB.execute("SELECT barcode, name, price FROM products LIMIT 24", fetch_all=True)
            
            x = 50; y = h - 100
            for item in items:
                c.drawString(x, y+10, item[1][:15]) # Name
                c.drawString(x, y, f"${item[2]}") # Price
                try:
                    barcode = code128.Code128(item[0], barHeight=30, barWidth=1.2)
                    barcode.drawOn(c, x, y-40)
                except: c.drawString(x, y-20, f"||| {item[0]} |||")
                x += 180
                if x > 500: x = 50; y -= 120
                if y < 50: c.showPage(); y = h - 100
            
            c.save(); webbrowser.open(path); show_snack("✅ Labels Generated!")
        except Exception as ex: show_snack(f"Error: {ex}", ERROR)

    # --- 4. EXCEL IMPORT ---
    def import_excel_data(e: ft.FilePickerResultEvent):
        if not e.files: return
        if not openpyxl: show_snack("Install openpyxl first!", ERROR); return
        file_path = e.files[0].path
        try:
            wb = openpyxl.load_workbook(file_path); ws = wb.active; count = 0
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0]:
                    DB.execute("INSERT INTO products (barcode, name, price, stock) VALUES (?, ?, ?, ?)", (str(row[0]), str(row[1]), float(row[2] or 0), int(row[3] or 0)))
                    count += 1
            show_snack(f"✅ Imported {count} Items!")
        except Exception as ex: show_snack(f"Import Failed: {ex}", ERROR)

    file_picker = ft.FilePicker(on_result=import_excel_data)
    page.overlay.append(file_picker)

    # --- 5. UI COMPONENTS ---
    def get_appbar(title, back_func=None):
        actions = [ft.Container(content=ft.Row([ft.Icon("person", color=WHITE), ft.Text(app_data['user']['name'], color=WHITE, weight="bold")]), padding=10)]
        leading = ft.IconButton(icon="arrow_back", icon_color=WHITE, on_click=back_func) if back_func else ft.Icon("store", color=WHITE)
        return ft.AppBar(leading=leading, title=ft.Text(title, weight="bold", color=WHITE), center_title=True, bgcolor=PRIMARY, actions=actions, elevation=2)

    def menu_btn(text, icon, func, color=PRIMARY):
        return ft.Container(content=ft.Row([ft.Icon(icon, color=color), ft.Text(text, color=color, weight="bold", size=16)], alignment="center"), bgcolor=WHITE, height=60, border_radius=10, ink=True, on_click=func, shadow=ft.BoxShadow(blur_radius=5, color="#1A000000"), border=ft.border.all(1, "grey200"))

    # --- 6. SCREENS ---
    
    # LOGIN
    def show_login():
        page.clean(); page.appbar = None
        def login_action(e):
            user = DB.execute("SELECT * FROM users WHERE pin=?", (pin.value,), fetch_one=True)
            if user:
                app_data["user"] = {"id": user[0], "name": user[1], "role": user[3]}
                app_data["cart"] = {}; app_data["customer"] = {"id": 0, "name": "Walk-in Client", "points": 0, "debt": 0}
                if user[3] == "Manager": show_dashboard()
                else: show_pos()
            else: pin.error_text = "Invalid PIN"; page.update()
        
        pin = ft.TextField(label="Enter PIN", password=True, width=200, text_align="center", on_submit=login_action, border_color=PRIMARY)
        page.add(ft.Container(content=ft.Column([
            ft.Icon("lock_outline", size=80, color=PRIMARY), ft.Text("HORN ERP", size=40, weight="bold", color=PRIMARY), pin, 
            ft.ElevatedButton("LOGIN", on_click=login_action, bgcolor=PRIMARY, color=WHITE, width=200, height=50)
        ], alignment="center", horizontal_alignment="center", spacing=20), alignment=ft.alignment.center, expand=True, bgcolor=BG))

    # DASHBOARD
    def show_dashboard():
        page.clean(); page.appbar = get_appbar("DASHBOARD")
        curr = get_setting('currency')
        rev = DB.execute("SELECT SUM(total_amount) FROM offline_sales WHERE date(date_created) = date('now')", fetch_one=True)[0] or 0
        sales = DB.execute("SELECT COUNT(*) FROM offline_sales WHERE date(date_created) = date('now')", fetch_one=True)[0] or 0
        
        page.add(ft.Container(content=ft.Column([
            ft.Row([
                ft.Container(content=ft.Column([ft.Icon("attach_money", size=30, color=WHITE), ft.Text("Revenue", color=WHITE), ft.Text(f"{curr}{rev:,.2f}", size=24, color=WHITE, weight="bold")], alignment="center"), width=200, height=120, bgcolor=PRIMARY, border_radius=15, padding=20),
                ft.Container(content=ft.Column([ft.Icon("receipt", size=30, color=WHITE), ft.Text("Sales", color=WHITE), ft.Text(str(sales), size=24, color=WHITE, weight="bold")], alignment="center"), width=200, height=120, bgcolor=SECONDARY, border_radius=15, padding=20),
            ], alignment="center", spacing=20),
            ft.Divider(height=40, color="transparent"),
            ft.Row([
                ft.Container(content=ft.Column([
                    ft.Text("Management", size=18, weight="bold", color="#546E7A"),
                    menu_btn("OPEN POS", "point_of_sale", lambda e: show_pos(), SUCCESS),
                    menu_btn("SUPPLY CHAIN", "local_shipping", lambda e: show_supply()),
                    menu_btn("FINANCIALS (P&L)", "account_balance", lambda e: show_financials(), "purple"), 
                    menu_btn("AUDIT LOGS", "security", lambda e: show_logs(), "black"), 
                    menu_btn("STAFF", "people", lambda e: show_staff()),
                    menu_btn("SETTINGS", "settings", lambda e: show_settings()),
                    menu_btn("LOGOUT", "logout", lambda e: show_login(), ERROR),
                ], spacing=10), width=300),
            ], alignment="center", vertical_alignment="start", spacing=30)
        ], scroll="auto"), padding=30, expand=True))

    # POS SCREEN
    def show_pos():
        page.clean(); curr = get_setting('currency'); rate = float(get_setting('rate') or 1)
        back_func = lambda e: show_dashboard() if app_data['user']['role'] == 'Manager' else show_login()
        page.appbar = get_appbar("POS TERMINAL", back_func)
        grid = ft.GridView(expand=1, runs_count=5, child_aspect_ratio=1.0, spacing=10); cart_list = ft.Column(scroll="auto", expand=True)
        total_txt = ft.Text(f"{curr}0.00", size=30, weight="bold", color=PRIMARY)
        forex_txt = ft.Text(f"(0.00 Local)", size=16, color="orange", weight="bold")
        
        scan_input = ft.TextField(label="Scan Barcode", autofocus=True, prefix_icon="qr_code_scanner", on_submit=lambda e: manual_scan(e))
        phone_input = ft.TextField(label="Client Phone", width=200); client_lbl = ft.Text("Walk-in", color="grey")
        
        def manual_scan(e):
            code = scan_input.value.strip()
            if not code: return
            item = DB.execute("SELECT barcode, name, price, stock FROM products WHERE barcode=?", (code,), fetch_one=True)
            if item: add(item); scan_input.value = ""; scan_input.focus(); page.update()
            else: show_snack("❌ Product not found", ERROR); scan_input.value = ""; page.update()

        def check_client(e):
            row = DB.execute("SELECT * FROM customers WHERE phone=?", (phone_input.value,), fetch_one=True)
            if row: 
                app_data["customer"] = {"id": row[0], "name": row[1], "debt": row[4]}
                client_lbl.value = f"{row[1]} (Debt: ${row[4]})"; client_lbl.color="red" if row[4]>0 else "blue"
            else: client_lbl.value = "New Client"; client_lbl.color="orange"
            page.update()

        def render_cart():
            cart_list.controls.clear(); total = 0
            for b, i in app_data["cart"].items():
                t = i['price'] * i['qty']; total += t
                cart_list.controls.append(ft.Container(content=ft.Row([ft.Text(f"{i['name']} x{i['qty']}"), ft.Text(f"{curr}{t:.2f}", weight="bold"), ft.IconButton("delete", icon_color="red", on_click=lambda e, x=b: remove(x))], alignment="spaceBetween"), padding=5, bgcolor=WHITE, border_radius=5))
            total_txt.value = f"{curr}{total:.2f}"; forex_txt.value = f"({total * rate:,.0f} Local)"; page.update()
        
        def add(p):
            b = p[0]
            if b in app_data["cart"]: app_data["cart"][b]['qty'] += 1
            else: app_data["cart"][b] = {'name': p[1], 'price': p[2], 'qty': 1, 'barcode': b}
            render_cart()
        def remove(b): del app_data["cart"][b]; render_cart()
        
        def pay(is_credit=False):
            if not app_data["cart"]: return show_snack("Cart Empty", ERROR)
            total = sum(i['price'] * i['qty'] for i in app_data["cart"].values())
            
            def finalize_pay(e):
                if phone_input.value and app_data["customer"]["id"] == 0:
                    DB.execute("INSERT INTO customers (name, phone) VALUES (?, ?)", (f"Client {phone_input.value}", phone_input.value))
                    app_data["customer"]["id"] = DB.execute("SELECT id FROM customers WHERE phone=?", (phone_input.value,), fetch_one=True)[0]

                method = "Credit" if is_credit else "Cash"
                if is_credit: DB.execute("UPDATE customers SET debt = debt + ? WHERE id = ?", (total, app_data["customer"]["id"]))
                
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # INSERT SALE (RETURNING ID for Postgres/SQLite difference handling)
                DB.execute("INSERT INTO offline_sales (total_amount, cashier_name, customer_name, payment_method, date_created) VALUES (?, ?, ?, ?, ?)", (total, app_data['user']['name'], app_data['customer']['name'], method, now))
                sid = DB.execute("SELECT MAX(id) FROM offline_sales", fetch_one=True)[0]

                items_copy = list(app_data["cart"].values()) 
                for i in items_copy: 
                    DB.execute("INSERT INTO offline_sale_items (sale_id, product_name, price, quantity) VALUES (?, ?, ?, ?)", (sid, i['name'], i['price'], i['qty']))
                    DB.execute("UPDATE products SET stock = stock - ? WHERE barcode=?", (i['qty'], i['barcode']))
                
                app_data["cart"] = {}; render_cart(); page.dialog.open = False
                def send_wa(e): send_whatsapp(phone_input.value, sid, total, items_copy)
                page.dialog = ft.AlertDialog(title=ft.Text("✅ Sale Complete!"), content=ft.Column([ft.Text(f"Amount: {curr}{total:.2f}"), ft.ElevatedButton("SEND RECEIPT (WHATSAPP) 📱", bgcolor="green", color="white", on_click=send_wa), ft.ElevatedButton("Close", on_click=lambda e: page.close(page.dialog))], height=150))
                page.dialog.open = True; page.update()

            page.dialog = ft.AlertDialog(title=ft.Text("Confirm Payment"), content=ft.Text(f"Total: {curr}{total:.2f}"), actions=[ft.TextButton("CONFIRM", on_click=finalize_pay)])
            page.dialog.open = True; page.update()

        prods = DB.execute("SELECT * FROM products", fetch_all=True)
        for p in prods:
            grid.controls.append(ft.Container(content=ft.Column([ft.Icon("shopping_bag", color=PRIMARY, size=30), ft.Text(p[1], weight="bold"), ft.Text(f"{curr}{p[2]}", color="green"), ft.Text(f"Stock: {p[3]}", size=10)], alignment="center"), bgcolor=WHITE, border_radius=10, ink=True, on_click=lambda e, x=p: add(x), padding=10, shadow=CARD_SHADOW))
        
        page.add(ft.Row([
            ft.Container(content=ft.Column([scan_input, grid], spacing=10), expand=2, padding=20),
            ft.Container(content=ft.Column([
                ft.Text("Order", size=20, weight="bold", color=PRIMARY),
                ft.Row([phone_input, ft.IconButton("check", on_click=check_client)]), client_lbl,
                ft.Divider(), cart_list, ft.Divider(),
                ft.Row([ft.Text("Total:"), total_txt], alignment="spaceBetween"),
                ft.Row([ft.Text("Forex:"), forex_txt], alignment="spaceBetween"),
