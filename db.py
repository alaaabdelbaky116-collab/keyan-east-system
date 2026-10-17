import streamlit as st
import pandas as pd
from datetime import datetime
import base64
import os
import psycopg2
import pytz
import math
import io

# ==========================================
# 1. الثوابت والقوائم الأساسية للنظام
# ==========================================
LOGO_FILE = "image_c5a585.png"
OFFICIAL_IN = '11:00'
OFFICIAL_OUT = '18:00'
GRACE_PERIOD_MINS = 60
REQUIRED_HOURS = 7
DEFAULT_ANNUAL_BALANCE = 21

CURRENCY_OPTIONS = [
    "ج.م (EGP)", 
    "دولار (USD)", 
    "ريال سعودي (SAR)", 
    "درهم إماراتي (AED)", 
    "يورو (EUR)"
]

COMPANY_DEPARTMENTS = [
    "اتش ار (HR)", "مبيعات وخدمة عملاء", "عقود قانونية", "تراخيص", "حسابات", 
    "مهندسين مكتب فني", "مهندسين إدارة وتخطيط", "مهندسين تنفيذ", 
    "إدارة المستخلصات", "إدارة الـ IT", "إدارة عليا", "أخرى"
]

ROLE_OPTIONS = [
    "لا يوجد (None)", "موظف عادي (Employee)", "رئيس قسم / مدير (Manager)", "مدير إداري (Admin Manager)", 
    "موارد بشرية (HR)", "مبيعات (Sales)", "مسؤول عقود قانونية (Legal)", "مهندس (Engineer)", 
    "مهندس إدارة وتخطيط (Planning Engineer)", "مهندس مستخلصات (Extracts Engineer)", 
    "محاسب (Accountant)", "مسؤول تراخيص (Licensing)", "مهندس IT (IT)", 
    "مسؤول نظام (Admin)", "مالك (Owner)"
]

ROLE_MAP = {
    "لا يوجد (None)": "none", "موظف عادي (Employee)": "employee", "رئيس قسم / مدير (Manager)": "manager", 
    "مدير إداري (Admin Manager)": "admin_manager", "موارد بشرية (HR)": "hr", "مبيعات (Sales)": "sales", 
    "مسؤول عقود قانونية (Legal)": "legal", "مهندس (Engineer)": "engineer", "مهندس إدارة وتخطيط (Planning Engineer)": "planning_engineer",
    "مهندس مستخلصات (Extracts Engineer)": "extracts_engineer", "محاسب (Accountant)": "accountant", "مسؤول تراخيص (Licensing)": "licensing", 
    "مهندس IT (IT)": "it", "مسؤول نظام (Admin)": "admin", "مالك (Owner)": "owner"
}

ROLE_REVERSE_MAP = {v: k for k, v in ROLE_MAP.items()}
DISPLAY_MAP = {
    "none": "لا يوجد", "employee": "موظف عادي", "manager": "رئيس قسم", "admin_manager": "مدير إداري", 
    "hr": "موارد بشرية", "sales": "مبيعات", "legal": "عقود قانونية", "engineer": "مهندس", 
    "planning_engineer": "مهندس إدارة وتخطيط", "extracts_engineer": "مهندس مستخلصات", 
    "accountant": "محاسب", "licensing": "مسؤول تراخيص", "it": "مهندس IT", 
    "admin": "مسؤول نظام", "owner": "المالك"
}

# ==========================================
# 2. الاتصال بقاعدة البيانات وتسجيل الـ Logs
# ==========================================
try:
    DB_URL = st.secrets["DB_URL"]
except:
    st.error("⚠️ يرجى إضافة رابط قاعدة البيانات (DB_URL) في إعدادات Secrets في منصة Streamlit!")
    st.stop()

def get_egypt_time():
    return datetime.now(pytz.timezone('Africa/Cairo'))

def get_db_connection():
    return psycopg2.connect(DB_URL)

def db_execute(query, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    cur.close()
    conn.close()

def db_fetchone(query, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res

def db_fetchall(query, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    res = cur.fetchall()
    cur.close()
    conn.close()
    return res

def is_valid_file(val):
    return pd.notna(val) and isinstance(val, str) and len(val.strip()) > 10

def log_event(action_type, details=""):
    try:
        user = st.session_state.get('username') or 'غير مسجل'
        role = st.session_state.get('current_role') or st.session_state.get('role') or 'غير محدد'
        now_str = get_egypt_time().strftime("%Y/%m/%d %H:%M:%S")
        db_execute(
            "INSERT INTO AuditLogs (log_time, username, role, action_type, details) VALUES (%s, %s, %s, %s, %s)",
            (now_str, user, role, action_type, details)
        )
    except:
        pass

# ==========================================
# 3. تهيئة وتحديث الجداول تلقائياً (شامل العملة)
# ==========================================
@st.cache_resource
def setup_database_v6():
    try:
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        cur.execute('''CREATE TABLE IF NOT EXISTS Users (username TEXT PRIMARY KEY, password TEXT, role TEXT, secondary_role TEXT DEFAULT 'none', emp_id TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Employees (emp_id TEXT PRIMARY KEY, name TEXT, department TEXT, secondary_department TEXT DEFAULT 'لا يوجد', annual_balance INTEGER, phone TEXT, exempt_report BOOLEAN DEFAULT FALSE)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Permissions (emp_id TEXT, date TEXT, type TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Requests (id SERIAL PRIMARY KEY, emp_id TEXT, date TEXT, req_type TEXT, notes TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS MonthlyStats (emp_id TEXT, month TEXT, delay_mins REAL, absent_dates TEXT, overtime_hours REAL DEFAULT 0, PRIMARY KEY(emp_id, month))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Locations (id SERIAL PRIMARY KEY, name TEXT, lat REAL, lon REAL, radius REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS WebAttendance (id SERIAL PRIMARY KEY, emp_id TEXT, date TEXT, time TEXT, action TEXT, distance REAL, location_name TEXT, photo TEXT, project_name TEXT, daily_report TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectFinancials (id SERIAL PRIMARY KEY, project_name TEXT, installment_type TEXT, amount REAL, currency TEXT DEFAULT 'ج.م (EGP)', due_date TEXT, status TEXT, category TEXT DEFAULT 'قسط جهاز', shareholder_name TEXT DEFAULT 'الشركة', share_percentage REAL DEFAULT 100.0, notes TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectLicenses (id SERIAL PRIMARY KEY, project_name TEXT, license_name TEXT, due_date TEXT, status TEXT, file_data TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectDrawings (id SERIAL PRIMARY KEY, project_name TEXT, drawing_name TEXT, due_date TEXT, status TEXT, file_data TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Tasks (id SERIAL PRIMARY KEY, emp_id TEXT, assigner TEXT, project_name TEXT, task_desc TEXT, assign_date TEXT, due_date TEXT, status TEXT, employee_reply TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Extracts (id SERIAL PRIMARY KEY, project_name TEXT, extract_name TEXT, amount REAL, date TEXT, created_by TEXT, status TEXT, file_data TEXT, impediment_notes TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Clients (id SERIAL PRIMARY KEY, name TEXT, phone TEXT, national_id TEXT, address TEXT, notes TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS RealEstateUnits (id SERIAL PRIMARY KEY, project_name TEXT, unit_code TEXT, status TEXT, client_name TEXT, total_price REAL, currency TEXT DEFAULT 'ج.م (EGP)', notes TEXT, contract_file TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS UnitInstallments (id SERIAL PRIMARY KEY, unit_code TEXT, client_name TEXT, amount REAL, currency TEXT DEFAULT 'ج.م (EGP)', due_date TEXT, paid_date TEXT, status TEXT, notes TEXT, collection_stage TEXT DEFAULT 'متابعة خدمة العملاء', call_notes TEXT DEFAULT '')''')
        cur.execute('''CREATE TABLE IF NOT EXISTS UnitResaleRequests (id SERIAL PRIMARY KEY, unit_code TEXT, project_name TEXT, old_client_name TEXT, old_price REAL, new_evaluated_price REAL, currency TEXT DEFAULT 'ج.م (EGP)', reason TEXT, requested_by TEXT, request_date TEXT, status TEXT DEFAULT 'بانتظار موافقة المالك', owner_notes TEXT DEFAULT '')''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Cheques (id SERIAL PRIMARY KEY, unit_code TEXT, client_name TEXT, cheque_number TEXT, amount REAL, currency TEXT DEFAULT 'ج.م (EGP)', due_date TEXT, file_data TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS AuditLogs (id SERIAL PRIMARY KEY, log_time TEXT, username TEXT, role TEXT, action_type TEXT, details TEXT)''')
        
        alter_queries = [
            "ALTER TABLE ProjectLicenses ADD COLUMN file_data TEXT",
            "ALTER TABLE ProjectDrawings ADD COLUMN file_data TEXT",
            "ALTER TABLE Employees ADD COLUMN phone TEXT",
            "ALTER TABLE Employees ADD COLUMN exempt_report BOOLEAN DEFAULT FALSE",
            "ALTER TABLE Employees ADD COLUMN secondary_department TEXT DEFAULT 'لا يوجد'",
            "ALTER TABLE Extracts ADD COLUMN impediment_notes TEXT",
            "ALTER TABLE Users ADD COLUMN secondary_role TEXT DEFAULT 'none'",
            "ALTER TABLE RealEstateUnits ADD COLUMN contract_file TEXT",
            "ALTER TABLE RealEstateUnits ADD COLUMN notes TEXT",
            "ALTER TABLE RealEstateUnits ADD COLUMN total_price REAL DEFAULT 0.0",
            "ALTER TABLE RealEstateUnits ADD COLUMN client_name TEXT",
            "ALTER TABLE RealEstateUnits ADD COLUMN currency TEXT DEFAULT 'ج.م (EGP)'",
            "ALTER TABLE ProjectFinancials ADD COLUMN category TEXT DEFAULT 'قسط جهاز'",
            "ALTER TABLE ProjectFinancials ADD COLUMN shareholder_name TEXT DEFAULT 'الشركة'",
            "ALTER TABLE ProjectFinancials ADD COLUMN share_percentage REAL DEFAULT 100.0",
            "ALTER TABLE ProjectFinancials ADD COLUMN notes TEXT",
            "ALTER TABLE ProjectFinancials ADD COLUMN currency TEXT DEFAULT 'ج.م (EGP)'",
            "ALTER TABLE UnitInstallments ADD COLUMN paid_date TEXT",
            "ALTER TABLE UnitInstallments ADD COLUMN notes TEXT",
            "ALTER TABLE UnitInstallments ADD COLUMN collection_stage TEXT DEFAULT 'متابعة خدمة العملاء'",
            "ALTER TABLE UnitInstallments ADD COLUMN call_notes TEXT DEFAULT ''",
            "ALTER TABLE UnitInstallments ADD COLUMN currency TEXT DEFAULT 'ج.م (EGP)'",
            "ALTER TABLE UnitResaleRequests ADD COLUMN currency TEXT DEFAULT 'ج.م (EGP)'",
            "ALTER TABLE Cheques ADD COLUMN currency TEXT DEFAULT 'ج.م (EGP)'",
            "ALTER TABLE Clients ADD COLUMN name TEXT",
            "ALTER TABLE Clients ADD COLUMN phone TEXT",
            "ALTER TABLE Clients ADD COLUMN national_id TEXT",
            "ALTER TABLE Clients ADD COLUMN address TEXT",
            "ALTER TABLE Clients ADD COLUMN notes TEXT",
            "ALTER TABLE AuditLogs ADD COLUMN log_time TEXT",
            "ALTER TABLE AuditLogs ADD COLUMN username TEXT",
            "ALTER TABLE AuditLogs ADD COLUMN role TEXT",
            "ALTER TABLE AuditLogs ADD COLUMN action_type TEXT",
            "ALTER TABLE AuditLogs ADD COLUMN details TEXT"
        ]
        for q in alter_queries:
            try:
                cur.execute(q)
            except:
                pass
            
        cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('admin', 'admin123', 'admin', '0') ON CONFLICT (username) DO UPDATE SET role='admin'")
        cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('owner', 'owner123', 'owner', 'owner') ON CONFLICT (username) DO UPDATE SET role='owner'")
            
        cur.close()
        conn.close()
        return True
    except Exception as e:
        return False

# دعم التوافق مع أي إصدار في app.py
setup_database_v4 = setup_database_v6
setup_database_v5 = setup_database_v6

def authenticate(username, password):
    return db_fetchone("SELECT role, secondary_role, emp_id FROM Users WHERE username=%s AND password=%s", (username, password))

def get_employee_info(emp_id):
    res = db_fetchone("SELECT name, department, annual_balance FROM Employees WHERE emp_id=%s", (emp_id,))
    if res:
        return res
    return ("غير مسجل", "غير محدد", DEFAULT_ANNUAL_BALANCE)

def get_employee_stats(emp_id):
    res = db_fetchone("SELECT month, delay_mins, absent_dates, overtime_hours FROM MonthlyStats WHERE emp_id=%s ORDER BY month DESC LIMIT 1", (emp_id,))
    if res:
        return res
    return (None, 0.0, "", 0.0)

# ==========================================
# 4. دوال الحسابات والتقارير وتقييم العملاء
# ==========================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def format_hhmm(total_minutes):
    if not total_minutes or pd.isna(total_minutes) or total_minutes <= 0:
        return "00:00"
    hours = int(total_minutes // 60)
    mins = int(total_minutes % 60)
    return f"{hours}:{mins:02d}"

def calculate_hours_diff(check_in, check_out):
    if pd.isna(check_in) or pd.isna(check_out) or not check_in or not check_out:
        return "⚠️ ناقصة بصمة"
    try:
        in_time = datetime.strptime(str(check_in).strip(), "%H:%M")
        out_time = datetime.strptime(str(check_out).strip(), "%H:%M")
        diff_mins = (out_time - in_time).total_seconds() / 60
        if diff_mins < 0:
            diff_mins += 24 * 60  
        hours = int(diff_mins // 60)
        mins = int(diff_mins % 60)
        return f"{hours}:{mins:02d}"
    except:
        return "خطأ في الوقت"

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode('utf-8')
    except:
        return ""

def generate_html_report(title, df, extra_summary_html=""):
    logo_b64 = get_base64_image(LOGO_FILE)
    if logo_b64:
        logo_img = f'<img src="data:image/png;base64,{logo_b64}" alt="Logo" style="max-height: 80px;">'
    else:
        logo_img = '<h2 style="color:#D4AF37;">كيان الشرقية</h2>'
        
    html_table = df.to_html(index=False, classes='report-table', border=0)
    html_table = html_table.replace("<tr>\n      <td>إجمالي الساعات</td>", "<tr class='total-row'>\n      <td>إجمالي الساعات</td>")
    html_table = html_table.replace("<tr>\n      <td>الإجمالي</td>", "<tr class='total-row'>\n      <td>الإجمالي</td>")
    
    html_content = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <title>{title}</title>
        <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Tajawal', sans-serif; padding: 40px; color: #0b172a; background: #fff; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #D4AF37; padding-bottom: 15px; margin-bottom: 30px; }}
            .company-info h1 {{ margin: 0; color: #0b172a; font-size: 28px; font-weight: 900; }}
            .company-info p {{ margin: 5px 0 0; color: #555; font-size: 16px; font-weight: 700; }}
            .report-title {{ text-align: center; margin-bottom: 25px; }}
            .report-title h2 {{ color: #0b172a; display: inline-block; padding-bottom: 5px; border-bottom: 2px dashed #D4AF37; margin-bottom: 5px; }}
            .summary-box {{ background: #f8f9fa; border: 2px solid #D4AF37; border-radius: 8px; padding: 15px; margin-bottom: 25px; display: flex; justify-content: space-around; flex-wrap: wrap; }}
            .summary-item {{ text-align: center; margin: 5px 15px; }}
            .summary-item span {{ display: block; font-size: 13px; color: #555; }}
            .summary-item strong {{ font-size: 18px; color: #0b172a; }}
            .report-table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 14px; text-align: right; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .report-table th, .report-table td {{ border: 1px solid #ddd; padding: 10px 12px; }}
            .report-table th {{ background-color: #0b172a; color: #D4AF37; font-weight: 900; }}
            .report-table tr:nth-child(even) {{ background-color: #f8f9fa; }}
            .total-row {{ background-color: #D4AF37 !important; color: #0b172a; font-weight: 900; }}
            .total-row td {{ border-top: 2px solid #0b172a; }}
            .footer {{ margin-top: 50px; text-align: center; font-size: 13px; color: #666; border-top: 2px solid #eee; padding-top: 15px; }}
            .print-btn {{ display: block; width: 250px; margin: 0 auto 30px auto; padding: 12px; background: #D4AF37; color: #0b172a; text-align: center; text-decoration: none; border-radius: 8px; font-weight: bold; cursor: pointer; border: none; font-family: 'Tajawal', sans-serif; font-size: 16px; }}
            .print-btn:hover {{ background: #b8952b; }}
            @media print {{
                body {{ padding: 0; }}
                .print-btn {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        <button class="print-btn" onclick="window.print()">🖨️ طباعة أو حفظ التقرير كـ PDF</button>
        <div class="header">
            <div class="company-info">
                <h1>كيان الشرقية</h1>
                <p>للمقاولات والاستثمار العقاري - إدارة نظم المعلومات</p>
            </div>
            <div>{logo_img}</div>
        </div>
        <div class="report-title">
            <h2>{title}</h2>
            <p>تاريخ الإصدار: {get_egypt_time().strftime('%Y/%m/%d %H:%M')}</p>
        </div>
        {extra_summary_html}
        {html_table}
        <div class="footer">
            <p>هذا المستند مُصدر آلياً وموثق من نظام (ERP) الخاص بشركة كيان الشرقية © {get_egypt_time().strftime('%Y')}</p>
        </div>
    </body>
    </html>
    """
    return html_content

def evaluate_client_commitment(inst_df):
    if inst_df.empty:
        return "⚪ لم يتم جدولة أقساط بعد", 100.0, 0, 0
        
    today_str = get_egypt_time().strftime("%Y/%m/%d")
    on_time_count = 0
    late_or_overdue_count = 0
    evaluated_installments = 0
    
    for _, row in inst_df.iterrows():
        status = str(row['status'])
        if "ملغي" in status:
            continue
        due_date = str(row['due_date'])
        
        if status == "مدفوع في الموعد" or status == "مدفوع":
            on_time_count += 1
            evaluated_installments += 1
        elif status == "مدفوع متأخر":
            late_or_overdue_count += 1
            evaluated_installments += 1
        elif status == "متأخر":
            late_or_overdue_count += 1
            evaluated_installments += 1
        elif status == "مستحق (لم يُدفع)":
            if due_date < today_str:
                late_or_overdue_count += 1
                evaluated_installments += 1
                
    if evaluated_installments == 0:
        return "🟢 منتظم (الأقساط لم يحن موعدها بعد)", 100.0, on_time_count, late_or_overdue_count
        
    score = (on_time_count / evaluated_installments) * 100.0
    
    if score >= 90:
        badge = f"🌟 عميل VIP ملتزم جداً ({score:.0f}%)"
    elif score >= 70:
        badge = f"👍 التزام جيد ({score:.0f}%)"
    elif score >= 50:
        badge = f"⚠️ التزام متوسط - يحتاج متابعة ({score:.0f}%)"
    else:
        badge = f"🚨 عميل متعثر / متأخر السداد ({score:.0f}%)"
        
    return badge, score, on_time_count, late_or_overdue_count

def process_excel(file):
    try:
        xls = pd.ExcelFile(file)
    except Exception as e:
        st.error(f"خطأ في قراءة الملف: {e}")
        return pd.DataFrame()

    extracted_data = []
    time_in_fmt = '%H:%M'
    official_in_dt = datetime.strptime(OFFICIAL_IN, time_in_fmt)
    official_out_dt = datetime.strptime(OFFICIAL_OUT, time_in_fmt)
    required_mins = REQUIRED_HOURS * 60
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        if len(df) < 5:
            continue
            
        for r in range(len(df)):
            for c in range(len(df.columns)):
                val = str(df.iloc[r, c]).strip()
                if val in ['Name', 'الاسم', 'الإسم', 'اسم الموظف', 'Employee Name']:
                    try:
                        name = str(df.iloc[r, c + 1]).strip()
                        emp_id = str(df.iloc[r + 1, c + 1]).strip() 
                    except:
                        continue
                        
                    if name.lower() == 'nan' or not name:
                        continue
                        
                    start_col = max(0, c - 6)
                    try:
                        department = str(df.iloc[r, start_col + 1]).strip()
                    except:
                        department = "غير محدد"
                    
                    cur.execute("INSERT INTO Employees (emp_id, name, department, annual_balance) VALUES (%s, %s, %s, %s) ON CONFLICT (emp_id) DO UPDATE SET name=EXCLUDED.name, department=EXCLUDED.department", (emp_id, name, department, DEFAULT_ANNUAL_BALANCE))
                    cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES (%s, %s, 'employee', %s) ON CONFLICT (username) DO NOTHING", (emp_id, emp_id, emp_id))
                    conn.commit()
                    
                    try:
                        year_month = str(df.iloc[r + 1, start_col + 1]).strip().split('-')[0][:7] 
                    except:
                        year_month = "2026/10" 
                        
                    daily_data = df.iloc[r + 9: r + 40, start_col:start_col+5] 
                    total_worked_mins = 0
                    regular_days = 0
                    total_shortage_mins = 0
                    total_overtime_mins = 0
                    absent_dates = []
                    
                    cur.execute("SELECT date FROM Permissions WHERE emp_id=%s", (emp_id,))
                    emp_perms = [row[0] for row in cur.fetchall()]
                    
                    for _, row in daily_data.iterrows():
                        try:
                            day_num = row.iloc[0]
                            day_name = str(row.iloc[1]).strip()
                            if pd.isna(day_num) or day_name == 'Fri.':
                                continue
                            t_in_str = str(row.iloc[2]).strip()
                            t_out_str = str(row.iloc[3]).strip()
                            has_in = (t_in_str != 'nan' and t_in_str != '--:--')
                            has_out = (t_out_str != 'nan' and t_out_str != '--:--')
                            formatted_date = f"{year_month}/{int(float(day_num)):02d}"
                        except:
                            continue
                        
                        if not has_in and not has_out:
                            if day_name != 'Thur.' and formatted_date not in emp_perms:
                                absent_dates.append(formatted_date)
                        elif has_in and has_out:
                            try:
                                t_in_dt = datetime.strptime(t_in_str, time_in_fmt)
                                t_out_dt = datetime.strptime(t_out_str, time_in_fmt)
                                worked_mins = (t_out_dt - t_in_dt).total_seconds() / 60
                                
                                if worked_mins > 0:
                                    total_worked_mins += worked_mins
                                    regular_days += 1
                                    late_arrival = (t_in_dt - official_in_dt).total_seconds() / 60
                                    daily_shortage = 0
                                    
                                    if late_arrival > GRACE_PERIOD_MINS:
                                        daily_shortage += late_arrival
                                        early_leave = (official_out_dt - t_out_dt).total_seconds() / 60
                                        if early_leave > 0:
                                            daily_shortage += early_leave
                                    elif late_arrival > 0:
                                        if worked_mins < required_mins:
                                            daily_shortage += (required_mins - worked_mins)
                                    else:
                                        early_leave = (official_out_dt - t_out_dt).total_seconds() / 60
                                        if early_leave > 0:
                                            daily_shortage += early_leave
                                            
                                    if daily_shortage > 0:
                                        total_shortage_mins += int(daily_shortage)
                                        
                                    overtime_mins = (t_out_dt - official_out_dt).total_seconds() / 60
                                    if overtime_mins > 0:
                                        total_overtime_mins += overtime_mins
                            except:
                                pass
                                
                    absent_str = ",".join(absent_dates)
                    cur.execute("INSERT INTO MonthlyStats (emp_id, month, delay_mins, absent_dates, overtime_hours) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (emp_id, month) DO UPDATE SET delay_mins=EXCLUDED.delay_mins, absent_dates=EXCLUDED.absent_dates, overtime_hours=EXCLUDED.overtime_hours", (emp_id, year_month, total_shortage_mins, absent_str, total_overtime_mins))
                    conn.commit()
                    
                    extracted_data.append({
                        'الكود': emp_id,
                        'الاسم': name,
                        'القسم': department,
                        'الحضور': regular_days,
                        'ساعات العمل': format_hhmm(total_worked_mins),
                        'إضافي': format_hhmm(total_overtime_mins),
                        'عجز وتأخير': format_hhmm(total_shortage_mins),
                        'غياب صريح': len(absent_dates)
                    })
                    
    cur.close()
    conn.close()
    log_event("تحليل شيت بصمة", f"تم تحليل ملف إكسيل لعدد {len(extracted_data)} موظف")
    return pd.DataFrame(extracted_data)
