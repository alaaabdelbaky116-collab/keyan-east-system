import streamlit as st
import pandas as pd
from datetime import datetime
import traceback
import math
import base64
from PIL import Image
import io
import os
import psycopg2
import pytz
import plotly.express as px
import sqlite3
import tempfile

# ==========================================
# 1. الاتصال بقاعدة البيانات وتوقيت مصر
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

# ==========================================
# 2. الإعدادات الأساسية والواجهة (UI/UX) الآمنة
# ==========================================
try:
    from streamlit_js_eval import get_geolocation
    GEO_AVAILABLE = True
except ImportError:
    GEO_AVAILABLE = False

st.set_page_config(page_title="كيان الشرقية للاستثمار العقاري", page_icon="🏗️", layout="wide")

def apply_custom_theme():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&display=swap');
        html, body, [class*="css"], p, h1, h2, h3, h4, h5, h6, span, div, button, input, select, textarea {
            font-family: 'Tajawal', sans-serif !important;
        }
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stButton>button {
            border-radius: 8px !important;
            font-weight: 700 !important;
            transition: all 0.3s ease !important;
            border: 1px solid #D4AF37 !important;
        }
    </style>
    """, unsafe_allow_html=True)

def set_dynamic_background():
    image_path = "company_bg.webp"
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            encoded_string = base64.b64encode(f.read()).decode()
        st.markdown(
            f"""
            <style>
            .stApp {{
                background: linear-gradient(rgba(11, 23, 42, 0.85), rgba(11, 23, 42, 0.85)), url(data:image/webp;base64,{encoded_string}) !important;
                background-size: cover !important;
                background-position: center !important;
                background-attachment: fixed !important;
            }}
            </style>
            """,
            unsafe_allow_html=True
        )

apply_custom_theme()
set_dynamic_background()
# ----------------------------------------------

OFFICIAL_IN = '11:00'
OFFICIAL_OUT = '18:00'
GRACE_PERIOD_MINS = 60
REQUIRED_HOURS = 7
DEFAULT_ANNUAL_BALANCE = 21
LOGO_FILE = "image_c5a585.png"

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
    "مدير إداري (Admin Manager)": "admin_manager", "موارد بشرية (HR)": "hr", 
    "مبيعات (Sales)": "sales", "مسؤول عقود قانونية (Legal)": "legal", "مهندس (Engineer)": "engineer", 
    "مهندس إدارة وتخطيط (Planning Engineer)": "planning_engineer",
    "مهندس مستخلصات (Extracts Engineer)": "extracts_engineer", "محاسب (Accountant)": "accountant", 
    "مسؤول تراخيص (Licensing)": "licensing", "مهندس IT (IT)": "it", 
    "مسؤول نظام (Admin)": "admin", "مالك (Owner)": "owner"
}

ROLE_REVERSE_MAP = {v: k for k, v in ROLE_MAP.items()}
DISPLAY_MAP = {
    "none": "لا يوجد", "employee": "موظف عادي", "manager": "رئيس قسم", "admin_manager": "مدير إداري", 
    "hr": "موارد بشرية", "sales": "مبيعات", "legal": "عقود قانونية", "engineer": "مهندس", 
    "planning_engineer": "مهندس إدارة وتخطيط", "extracts_engineer": "مهندس مستخلصات", 
    "accountant": "محاسب", "licensing": "مسؤول تراخيص", "it": "مهندس IT", 
    "admin": "مسؤول نظام", "owner": "المالك"
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def format_hhmm(total_minutes):
    if not total_minutes or pd.isna(total_minutes) or total_minutes <= 0: return "00:00"
    hours = int(total_minutes // 60)
    mins = int(total_minutes % 60)
    return f"{hours}:{mins:02d}"

# ==========================================
# دالة مولد تقارير الطباعة الرسمية (HTML to PDF) - معدلة للصف التجميعي
# ==========================================
def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file: return base64.b64encode(img_file.read()).decode('utf-8')
    except: return ""

def generate_html_report(title, df):
    logo_b64 = get_base64_image(LOGO_FILE)
    logo_img = f'<img src="data:image/png;base64,{logo_b64}" alt="Logo" style="max-height: 80px;">' if logo_b64 else '<h2 style="color:#D4AF37;">كيان الشرقية</h2>'
    
    # تحويل الـ DataFrame لجدول HTML وتحديد كلاس خاص لصف الإجمالي
    html_table = df.to_html(index=False, classes='report-table', border=0)
    # إضافة تنسيق لصف الإجمالي إذا كان موجوداً
    html_table = html_table.replace("<tr>\n      <td>إجمالي الساعات</td>", "<tr class='total-row'>\n      <td>إجمالي الساعات</td>")
    
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
            .report-title {{ text-align: center; margin-bottom: 30px; }}
            .report-title h2 {{ color: #0b172a; display: inline-block; padding-bottom: 5px; border-bottom: 2px dashed #D4AF37; }}
            .report-table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 14px; text-align: right; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .report-table th, .report-table td {{ border: 1px solid #ddd; padding: 12px; }}
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
        {html_table}
        <div class="footer">
            <p>هذا التقرير مُصدر آلياً وموثق من نظام (ERP) الخاص بشركة كيان الشرقية © {get_egypt_time().strftime('%Y')}</p>
        </div>
    </body>
    </html>
    """
    return html_content

# ==========================================
# دالة التنبيهات الذكية للإدارة
# ==========================================
def render_smart_alerts():
    conn = get_db_connection()
    today = get_egypt_time()
    alerts = []

    try:
        lic_df = pd.read_sql_query("SELECT license_name, project_name, due_date FROM ProjectLicenses WHERE status != 'منتهية'", conn)
        for _, row in lic_df.iterrows():
            try:
                d_date = datetime.strptime(row['due_date'], "%Y/%m/%d").replace(tzinfo=pytz.timezone('Africa/Cairo'))
                days_left = (d_date - today).days
                if 0 <= days_left <= 15:
                    alerts.append(f"⚠️ **تنبيه ترخيص:** الترخيص '{row['license_name']}' لمشروع ({row['project_name']}) سينتهي خلال {days_left} أيام!")
                elif days_left < 0:
                    alerts.append(f"❌ **ترخيص منتهي:** الترخيص '{row['license_name']}' لمشروع ({row['project_name']}) انتهى منذ {-days_left} أيام!")
            except: pass
    except: pass

    try:
        fin_df = pd.read_sql_query("SELECT installment_type, project_name, due_date FROM ProjectFinancials WHERE status IN ('مستحق (لم يُدفع)', 'متأخر')", conn)
        for _, row in fin_df.iterrows():
            try:
                d_date = datetime.strptime(row['due_date'], "%Y/%m/%d").replace(tzinfo=pytz.timezone('Africa/Cairo'))
                days_left = (d_date - today).days
                if 0 <= days_left <= 10:
                    alerts.append(f"💸 **تنبيه مالي:** قسط '{row['installment_type']}' لمشروع ({row['project_name']}) يستحق الدفع خلال {days_left} أيام!")
                elif days_left < 0:
                    alerts.append(f"🚨 **قسط متأخر:** قسط '{row['installment_type']}' لمشروع ({row['project_name']}) متأخر الدفع منذ {-days_left} أيام!")
            except: pass
    except: pass

    conn.close()

    if alerts:
        with st.expander("🔔 اضغط هنا لرؤية التنبيهات الذكية الهامة!", expanded=True):
            for alert in alerts:
                if '❌' in alert or '🚨' in alert: st.error(alert)
                else: st.warning(alert)

# ==========================================
# دالة الشريط الجانبي (ومبدل الصلاحيات)
# ==========================================
def render_sidebar(role_title):
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, use_container_width=True)
        except: pass
        
        if st.session_state.get('secondary_role') and st.session_state['secondary_role'] != 'none':
            st.success(f"مرحباً: {st.session_state['username']}")
            st.markdown("🔄 **لوحة التحكم (الصلاحية المزدوجة):**")
            
            role1_disp = DISPLAY_MAP.get(st.session_state['primary_role'], st.session_state['primary_role'])
            role2_disp = DISPLAY_MAP.get(st.session_state['secondary_role'], st.session_state['secondary_role'])
            current_disp = DISPLAY_MAP.get(st.session_state['current_role'], st.session_state['current_role'])
            
            options = [role1_disp, role2_disp]
            if current_disp not in options: current_disp = options[0]
            
            selected_role_disp = st.selectbox("اختر الصلاحية للعمل بها الآن:", options, index=options.index(current_disp))
            
            if selected_role_disp != current_disp:
                if selected_role_disp == role1_disp:
                    st.session_state['current_role'] = st.session_state['primary_role']
                else:
                    st.session_state['current_role'] = st.session_state['secondary_role']
                st.rerun()
            st.info(f"القسم الحالي: {role_title}")
        else:
            st.success(f"مرحباً: {st.session_state['username']} ({role_title})")
        
        with st.expander("🔐 تغيير كلمة المرور الخاصة بي"):
            with st.form("pwd_form"):
                new_pwd = st.text_input("كلمة المرور الجديدة", type="password", placeholder="أدخل باسورد قوي")
                if st.form_submit_button("تحديث الحساب", use_container_width=True):
                    if len(new_pwd) >= 3:
                        db_execute("UPDATE Users SET password=%s WHERE username=%s", (new_pwd, st.session_state['username']))
                        st.success("تم التغيير بنجاح! احتفظ بها.")
                    else: st.error("كلمة المرور قصيرة جداً.")
                        
        st.divider()
        if st.button("🚪 تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()

# ==========================================
# 3. حماية وتجهيز جداول PostgreSQL
# ==========================================
def init_db():
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
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectFinancials (id SERIAL PRIMARY KEY, project_name TEXT, installment_type TEXT, amount REAL, due_date TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectLicenses (id SERIAL PRIMARY KEY, project_name TEXT, license_name TEXT, due_date TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectDrawings (id SERIAL PRIMARY KEY, project_name TEXT, drawing_name TEXT, due_date TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Tasks (id SERIAL PRIMARY KEY, emp_id TEXT, assigner TEXT, project_name TEXT, task_desc TEXT, assign_date TEXT, due_date TEXT, status TEXT, employee_reply TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Extracts (id SERIAL PRIMARY KEY, project_name TEXT, extract_name TEXT, amount REAL, date TEXT, created_by TEXT, status TEXT, file_data TEXT, impediment_notes TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS RealEstateUnits (id SERIAL PRIMARY KEY, project_name TEXT, unit_code TEXT, status TEXT, client_name TEXT, total_price REAL, notes TEXT, contract_file TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS UnitInstallments (id SERIAL PRIMARY KEY, unit_code TEXT, client_name TEXT, amount REAL, due_date TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Cheques (id SERIAL PRIMARY KEY, unit_code TEXT, client_name TEXT, cheque_number TEXT, amount REAL, due_date TEXT, file_data TEXT, status TEXT)''')
        
        try: cur.execute("ALTER TABLE ProjectLicenses ADD COLUMN file_data TEXT")
        except: pass
        try: cur.execute("ALTER TABLE ProjectDrawings ADD COLUMN file_data TEXT")
        except: pass
        try: cur.execute("ALTER TABLE Employees ADD COLUMN phone TEXT")
        except: pass
        try: cur.execute("ALTER TABLE Employees ADD COLUMN exempt_report BOOLEAN DEFAULT FALSE")
        except: pass
        try: cur.execute("ALTER TABLE Extracts ADD COLUMN impediment_notes TEXT")
        except: pass
        try: cur.execute("ALTER TABLE Users ADD COLUMN secondary_role TEXT DEFAULT 'none'")
        except: pass
        try: cur.execute("ALTER TABLE Employees ADD COLUMN secondary_department TEXT DEFAULT 'لا يوجد'")
        except: pass
        try: cur.execute("ALTER TABLE RealEstateUnits ADD COLUMN contract_file TEXT")
        except: pass
            
        cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('admin', 'admin123', 'admin', '0') ON CONFLICT (username) DO UPDATE SET role='admin'")
        cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('owner', 'owner123', 'owner', 'owner') ON CONFLICT (username) DO UPDATE SET role='owner'")
            
        cur.close()
        conn.close()
    except Exception as e: pass 

init_db()

def authenticate(username, password):
    return db_fetchone("SELECT role, secondary_role, emp_id FROM Users WHERE username=%s AND password=%s", (username, password))

def get_employee_info(emp_id):
    res = db_fetchone("SELECT name, department, annual_balance FROM Employees WHERE emp_id=%s", (emp_id,))
    return res if res else ("غير مسجل", "غير محدد", DEFAULT_ANNUAL_BALANCE)

def get_employee_stats(emp_id):
    res = db_fetchone("SELECT month, delay_mins, absent_dates, overtime_hours FROM MonthlyStats WHERE emp_id=%s ORDER BY month DESC LIMIT 1", (emp_id,))
    return res if res else (None, 0.0, "", 0.0)

# ==========================================
# 4. محرك تحليل الحضور من الإكسيل
# ==========================================
def process_excel(file):
    try: xls = pd.ExcelFile(file)
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
        if len(df) < 5: continue
        for r in range(len(df)):
            for c in range(len(df.columns)):
                val = str(df.iloc[r, c]).strip()
                if val in ['Name', 'الاسم', 'الإسم', 'اسم الموظف', 'Employee Name']:
                    try:
                        name = str(df.iloc[r, c + 1]).strip()
                        emp_id = str(df.iloc[r + 1, c + 1]).strip() 
                    except: continue
                    if name.lower() == 'nan' or not name: continue
                    start_col = max(0, c - 6)
                    try: department = str(df.iloc[r, start_col + 1]).strip()
                    except: department = "غير محدد"
                    
                    cur.execute("INSERT INTO Employees (emp_id, name, department, annual_balance) VALUES (%s, %s, %s, %s) ON CONFLICT (emp_id) DO UPDATE SET name=EXCLUDED.name, department=EXCLUDED.department", (emp_id, name, department, DEFAULT_ANNUAL_BALANCE))
                    cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES (%s, %s, 'employee', %s) ON CONFLICT (username) DO NOTHING", (emp_id, emp_id, emp_id))
                    conn.commit()
                    
                    try: year_month = str(df.iloc[r + 1, start_col + 1]).strip().split('-')[0][:7] 
                    except: year_month = "2026/10" 
                    daily_data = df.iloc[r + 9: r + 40, start_col:start_col+5] 
                    total_worked_mins, regular_days, total_shortage_mins, total_overtime_mins, absent_dates = 0, 0, 0, 0, []
                    cur.execute("SELECT date FROM Permissions WHERE emp_id=%s", (emp_id,))
                    emp_perms = [row[0] for row in cur.fetchall()]
                    
                    for _, row in daily_data.iterrows():
                        try:
                            day_num, day_name = row.iloc[0], str(row.iloc[1]).strip()
                            if pd.isna(day_num) or day_name == 'Fri.': continue
                            t_in_str, t_out_str = str(row.iloc[2]).strip(), str(row.iloc[3]).strip()
                            has_in, has_out = (t_in_str != 'nan' and t_in_str != '--:--'), (t_out_str != 'nan' and t_out_str != '--:--')
                        except: continue
                        
                        try: formatted_date = f"{year_month}/{int(float(day_num)):02d}"
                        except: formatted_date = f"{year_month}/--"
                        
                        if not has_in and not has_out:
                            if day_name != 'Thur.' and formatted_date not in emp_perms: absent_dates.append(formatted_date)
                        elif has_in and has_out:
                            try:
                                t_in_dt, t_out_dt = datetime.strptime(t_in_str, time_in_fmt), datetime.strptime(t_out_str, time_in_fmt)
                                worked_mins = (t_out_dt - t_in_dt).total_seconds() / 60
                                if worked_mins > 0:
                                    total_worked_mins += worked_mins; regular_days += 1
                                    late_arrival = (t_in_dt - official_in_dt).total_seconds() / 60
                                    daily_shortage = 0
                                    if late_arrival > GRACE_PERIOD_MINS:
                                        daily_shortage += late_arrival
                                        early_leave = (official_out_dt - t_out_dt).total_seconds() / 60
                                        if early_leave > 0: daily_shortage += early_leave
                                    elif late_arrival > 0:
                                        if worked_mins < required_mins: daily_shortage += (required_mins - worked_mins)
                                    else:
                                        early_leave = (official_out_dt - t_out_dt).total_seconds() / 60
                                        if early_leave > 0: daily_shortage += early_leave
                                    if daily_shortage > 0: total_shortage_mins += int(daily_shortage)
                                    overtime_mins = (t_out_dt - official_out_dt).total_seconds() / 60
                                    if overtime_mins > 0: total_overtime_mins += overtime_mins
                            except: pass
                    absent_str = ",".join(absent_dates)
                    cur.execute("INSERT INTO MonthlyStats (emp_id, month, delay_mins, absent_dates, overtime_hours) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (emp_id, month) DO UPDATE SET delay_mins=EXCLUDED.delay_mins, absent_dates=EXCLUDED.absent_dates, overtime_hours=EXCLUDED.overtime_hours", (emp_id, year_month, total_shortage_mins, absent_str, total_overtime_mins))
                    conn.commit()
                    extracted_data.append({'الكود': emp_id, 'الاسم': name, 'القسم': department, 'الحضور': regular_days, 'ساعات العمل': format_hhmm(total_worked_mins), 'إضافي': format_hhmm(total_overtime_mins), 'عجز وتأخير': format_hhmm(total_shortage_mins), 'غياب صريح': len(absent_dates)})
    cur.close()
    conn.close()
    return pd.DataFrame(extracted_data)

# ==========================================
# 5. واجهة تسجيل الدخول
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.update({'logged_in': False, 'role': None, 'emp_id': None, 'username': None, 'primary_role': None, 'secondary_role': 'none', 'current_role': None})

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            if os.path.exists(LOGO_FILE):
                img_c1, img_c2, img_c3 = st.columns([1, 2.5, 1])
                with img_c2: st.image(LOGO_FILE, use_container_width=True)
        except: pass
        
        st.markdown("<h1 style='text-align: center; font-weight: 900; font-size: 3.5rem; margin-bottom: 0px;'>كيان الشرقية</h1>", unsafe_allow_html=True)
        st.markdown("<h4 style='text-align: center; color: #D4AF37; margin-bottom: 30px;'>للمقاولات والاستثمار العقاري - الزقازيق 🏗️</h4>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            user = st.text_input("اسم المستخدم", placeholder="أدخل اسم المستخدم الخاص بك")
            pwd = st.text_input("كلمة المرور", type="password", placeholder="أدخل كلمة المرور")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("تسجيل الدخول", use_container_width=True):
                user_data = authenticate(user, pwd)
                if user_data:
                    role1, role2, emp_id = user_data
                    st.session_state.update({
                        'logged_in': True, 
                        'role': role1, 
                        'primary_role': role1,
                        'secondary_role': role2 if role2 else 'none',
                        'current_role': role1,
                        'emp_id': emp_id, 
                        'username': user
                    })
                    st.rerun()
                else: st.error("بيانات الدخول غير صحيحة! يرجى المراجعة.")

# ==========================================
# دالة لوحة القيادة الشاملة
# ==========================================
def render_company_dashboard():
    st.header("📊 المؤشرات الحيوية والتفاعلية للشركة")
    conn = get_db_connection()
    today = get_egypt_time().strftime("%Y/%m/%d")

    c1, c2, c3, c4 = st.columns(4)
    try:
        total_emps = int(db_fetchone("SELECT COUNT(*) FROM Employees")[0])
        present_today = int(db_fetchone("SELECT COUNT(DISTINCT emp_id) FROM WebAttendance WHERE date=%s AND action='حضور'", (today,))[0])
        pending_reqs = int(db_fetchone("SELECT COUNT(*) FROM Requests WHERE status='قيد الانتظار'")[0])
    except: total_emps, present_today, pending_reqs = 0, 0, 0

    c1.metric("👥 إجمالي الموظفين", total_emps)
    c2.metric("🟢 حضور اليوم", present_today)
    c3.metric("🔴 غياب محتمل اليوم", max(0, total_emps - present_today))
    c4.metric("🔔 طلبات معلقة", pending_reqs)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🏗️ نشاط المشاريع والأعمال")
        proj_df = pd.read_sql_query("SELECT project_name AS \"المشروع\", COUNT(*) AS \"عدد المهام\" FROM WebAttendance WHERE project_name IS NOT NULL AND project_name != '' GROUP BY project_name ORDER BY \"عدد المهام\" DESC LIMIT 7", conn)
        if not proj_df.empty:
            fig1 = px.bar(proj_df, x="المشروع", y="عدد المهام", color="عدد المهام", color_continuous_scale="Blues", text_auto=True)
            fig1.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="Tajawal", font_color="#fff")
            st.plotly_chart(fig1, use_container_width=True)
        else: st.info("لا توجد بيانات للمشاريع بعد.")

    with col2:
        st.subheader("💰 الموقف المالي للأقساط")
        fin_df = pd.read_sql_query("SELECT status AS \"الحالة\", SUM(amount) AS \"الإجمالي\" FROM ProjectFinancials GROUP BY status", conn)
        if not fin_df.empty:
            fig2 = px.pie(fin_df, values="الإجمالي", names="الحالة", hole=0.45, color_discrete_sequence=px.colors.sequential.YlOrBr)
            fig2.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="Tajawal", font_color="#fff")
            st.plotly_chart(fig2, use_container_width=True)
        else: st.info("لا توجد تعاملات مالية مسجلة.")

    conn.close()

# ==========================================
# دالة شيت تقارير البصمة (المعدلة لحساب الساعات والتحذير)
# ==========================================
def calculate_hours_diff(check_in, check_out):
    if pd.isna(check_in) or pd.isna(check_out) or not check_in or not check_out:
        return "⚠️ ناقصة بصمة"
    try:
        in_time = datetime.strptime(str(check_in).strip(), "%H:%M")
        out_time = datetime.strptime(str(check_out).strip(), "%H:%M")
        diff_mins = (out_time - in_time).total_seconds() / 60
        if diff_mins < 0: diff_mins += 24 * 60  # لحساب الورديات اللي بتعدي منتصف الليل
        hours = int(diff_mins // 60)
        mins = int(diff_mins % 60)
        return f"{hours}:{mins:02d}"
    except:
        return "خطأ في الوقت"

def render_attendance_report(department_filter=None):
    conn = get_db_connection()
    if department_filter: emps = db_fetchall("SELECT name FROM Employees WHERE department=%s OR secondary_department=%s ORDER BY name", (department_filter, department_filter))
    else: emps = db_fetchall("SELECT name FROM Employees ORDER BY name")
        
    emp_list = ["الكل"] + [e[0] for e in emps]
    months = db_fetchall("SELECT DISTINCT substring(date from 1 for 7) FROM WebAttendance")
    month_list = ["الكل"] + [m[0] for m in months if m[0]]
    
    st.write("📌 **أدوات الفلترة والبحث السريع:**")
    c1, c2, c3 = st.columns(3)
    selected_emp = c1.selectbox("👤 اختيار الموظف:", emp_list)
    filter_type = c2.radio("📅 فترة التقرير:", ["اليوم فقط", "شهر محدد", "كل السجلات"], horizontal=True)
    
    selected_month = "الكل"
    if filter_type == "شهر محدد": selected_month = c3.selectbox("اختر الشهر:", month_list)
        
    query = """
        SELECT 
            w.date AS date_val, e.name AS emp_name, e.department AS dept,
            MIN(CASE WHEN w.action = 'حضور' THEN w.time END) AS check_in,
            MAX(CASE WHEN w.action = 'انصراف' THEN w.time END) AS check_out,
            MAX(w.location_name) AS loc, STRING_AGG(w.project_name, ' + ') AS proj,
            STRING_AGG(w.project_name || ': ' || w.daily_report, ' | ') AS rep,
            MAX(CASE WHEN w.action = 'حضور' THEN w.photo END) AS photo
        FROM WebAttendance w JOIN Employees e ON w.emp_id = e.emp_id WHERE 1=1
    """
    params = []
    if department_filter: query += " AND (e.department = %s OR e.secondary_department = %s)"; params.extend([department_filter, department_filter])
    if selected_emp != "الكل": query += " AND e.name = %s"; params.append(selected_emp)
    if filter_type == "اليوم فقط": query += " AND w.date = %s"; params.append(get_egypt_time().strftime("%Y/%m/%d"))
    elif filter_type == "شهر محدد" and selected_month != "الكل": query += " AND w.date LIKE %s"; params.append(selected_month + "%")
        
    query += " GROUP BY w.date, e.name, e.department ORDER BY w.date DESC"
    
    rep_df = pd.read_sql_query(query, conn, params=tuple(params))
    conn.close()
    
    if not rep_df.empty:
        rep_df['date_val'] = pd.to_datetime(rep_df['date_val'])
        arabic_days = {'Monday': 'الإثنين', 'Tuesday': 'الثلاثاء', 'Wednesday': 'الأربعاء', 'Thursday': 'الخميس', 'Friday': 'الجمعة', 'Saturday': 'السبت', 'Sunday': 'الأحد'}
        rep_df['اسم اليوم'] = rep_df['date_val'].dt.day_name().map(arabic_days)
        rep_df['التاريخ'] = rep_df['date_val'].dt.strftime('%Y/%m/%d')
        
        # حساب ساعات العمل لكل صف (يوم)
        rep_df['ساعات العمل'] = rep_df.apply(lambda row: calculate_hours_diff(row['check_in'], row['check_out']), axis=1)
        
        final_df = rep_df[['التاريخ', 'اسم اليوم', 'emp_name', 'dept', 'check_in', 'check_out', 'ساعات العمل', 'loc', 'proj', 'rep', 'photo']]
        final_df.columns = ['التاريخ', 'اليوم', 'اسم الموظف', 'القسم الأساسي', 'الحضور', 'الانصراف', 'ساعات العمل', 'موقع البصمة', 'المشاريع', 'التقارير اليومية', 'صورة الإثبات']
        
        st.success(f"✅ تم العثور على {len(final_df)} سجل دوام.")
        st.dataframe(final_df, use_container_width=True, hide_index=True, column_config={"صورة الإثبات": st.column_config.ImageColumn("صورة الإثبات")})
        
        csv_df = final_df.drop(columns=['صورة الإثبات'])
        
        # حساب إجمالي الساعات للتقرير (الصف الأخير)
        total_mins = 0
        for val in csv_df['ساعات العمل']:
            if "⚠️" not in val and ":" in val:
                try:
                    h, m = val.split(":")
                    total_mins += int(h) * 60 + int(m)
                except: pass
        
        total_str = f"{total_mins // 60}:{(total_mins % 60):02d} ساعة"
        
        # إضافة صف التجميع
        summary_row = pd.DataFrame([{
            'التاريخ': 'إجمالي الساعات', 'اليوم': '', 'اسم الموظف': '', 'القسم الأساسي': '', 
            'الحضور': '', 'الانصراف': '', 'ساعات العمل': total_str, 
            'موقع البصمة': '', 'المشاريع': '', 'التقارير اليومية': ''
        }])
        csv_df_with_total = pd.concat([csv_df, summary_row], ignore_index=True)
        
        col_down1, col_down2 = st.columns(2)
        csv = csv_df_with_total.to_csv(index=False).encode('utf-8-sig')
        col_down1.download_button("📥 تحميل كـ شيت (Excel/CSV)", data=csv, file_name=f"Attendance_Sheet_{get_egypt_time().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)
        
        html_report = generate_html_report("تقرير الحضور والانصراف التفصيلي - كيان الشرقية", csv_df_with_total)
        col_down2.download_button("🖨️ تحميل للطباعة (رسمي PDF)", data=html_report, file_name=f"Attendance_Report_{get_egypt_time().strftime('%Y%m%d')}.html", mime='text/html', type="primary", use_container_width=True)
        
    else: st.info("لا توجد سجلات تطابق خيارات البحث.")

# ==========================================
# دالة مهام القسم
# ==========================================
def render_task_delegation(department):
    st.header("📋 إسناد مهام للموظفين (Task Delegation)")
    conn = get_db_connection()
    if department == "الكل": emps = pd.read_sql_query("SELECT emp_id, name FROM Employees ORDER BY name", conn)
    else: emps = pd.read_sql_query("SELECT emp_id, name FROM Employees WHERE department=%s OR secondary_department=%s ORDER BY name", conn, params=(department, department))
    conn.close()
    
    with st.form("assign_task_form"):
        c1, c2 = st.columns(2)
        selected_emp = c1.selectbox("اختر الموظف أو المهندس", emps['name'].tolist() if not emps.empty else ["لا يوجد موظفين"])
        proj = c2.selectbox("المشروع (الاتحاد)", [f"اتحاد {i}" for i in range(1, 46)])
        task_desc = st.text_area("تفاصيل المهمة المطلوبة بوضوح")
        due_date = st.date_input("تاريخ التسليم المتوقع")
        
        if st.form_submit_button("إرسال المهمة الآن 🚀", type="primary"):
            if selected_emp != "لا يوجد موظفين" and task_desc.strip():
                emp_id_selected = emps[emps['name'] == selected_emp].iloc[0]['emp_id']
                db_execute("INSERT INTO Tasks (emp_id, assigner, project_name, task_desc, assign_date, due_date, status) VALUES (%s, %s, %s, %s, %s, %s, 'قيد التنفيذ')",
                           (emp_id_selected, st.session_state['username'], proj, task_desc, get_egypt_time().strftime("%Y/%m/%d"), due_date.strftime("%Y/%m/%d")))
                st.success("تم إسناد المهمة للموظف بنجاح!")
            else: st.error("يرجى كتابة تفاصيل المهمة وتحديد الموظف.")

# ==========================================
# 6. بوابة الإدارة (Admin / IT) (مع الصلاحيات الإضافية)
# ==========================================
def admin_portal():
    render_sidebar("الإدارة التكنولوجية (IT/Admin)")
    nav = st.radio("القائمة الرئيسية:", ["📊 تحليل البصمة", "✅ الطلبات", "➕ إنشاء/تعديل حساب", "⚙ إدارة الحسابات", "📍 المواقع", "📌 تقارير المناديب", "💾 النسخ الاحتياطي"], horizontal=True)
    st.divider()
    
    if nav == "📊 تحليل البصمة":
        st.header("تحليل ملف الحضور والانصراف (من الإكسيل)")
        uploaded_file = st.file_uploader("ارفع شيت البصمة (Excel)", type=['xls', 'xlsx'])
        if uploaded_file and st.button("بدء التحليل", type="primary"):
            df = process_excel(uploaded_file)
            if df is not None and not df.empty:
                st.success("تم التحليل بنجاح!")
                st.dataframe(df, use_container_width=True, hide_index=True)

    elif nav == "✅ الطلبات":
        st.header("جميع طلبات الموظفين بالشركة")
        conn = get_db_connection()
        all_reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, e.department, r.date, r.req_type, r.notes, r.status FROM Requests r LEFT JOIN Employees e ON r.emp_id = e.emp_id ORDER BY r.id DESC LIMIT 50", conn)
        conn.close()
        if not all_reqs.empty: 
            all_reqs.columns = ['رقم', 'كود الموظف', 'الاسم', 'القسم', 'التاريخ', 'نوع الطلب', 'السبب', 'الحالة']
            st.dataframe(all_reqs, use_container_width=True, hide_index=True)
            
            html_report = generate_html_report("تقرير طلبات الموظفين - كيان الشرقية", all_reqs)
            st.download_button("🖨️ تحميل سجل الطلبات (رسمي PDF)", data=html_report, file_name=f"Requests_{get_egypt_time().strftime('%Y%m%d')}.html", mime='text/html')
        else: st.info("لا توجد طلبات مسجلة حالياً.")

    elif nav == "➕ إنشاء/تعديل حساب":
        st.header("إضافة حساب بصلاحيات متعددة (Dual Roles)")
        with st.form("new_user"):
            c1, c2 = st.columns(2)
            new_name = c1.text_input("اسم الموظف الرباعي")
            new_emp_id = c2.text_input("كود الموظف (ID)")
            
            c3, c4 = st.columns(2)
            new_dept = c3.selectbox("القسم الأساسي", COMPANY_DEPARTMENTS)
            new_sec_dept = c4.selectbox("القسم الإضافي (اختياري)", ["لا يوجد"] + COMPANY_DEPARTMENTS)
            
            c5, c6 = st.columns(2)
            role_choice = c5.selectbox("الصلاحية الأساسية", [r for r in ROLE_OPTIONS if r != "لا يوجد (None)"])
            sec_role_choice = c6.selectbox("الصلاحية الإضافية (اختياري)", ROLE_OPTIONS)
            
            c7, c8 = st.columns(2)
            new_user = c7.text_input("اسم المستخدم للدخول")
            new_pwd = c8.text_input("كلمة المرور")
            
            new_phone = c7.text_input("رقم الهاتف")
            new_exempt = st.checkbox("✔️ إعفاء الموظف من إجبارية كتابة التقرير اليومي")
            
            if st.form_submit_button("إنشاء الحساب", type="primary"):
                if new_user and new_pwd and new_emp_id and new_name:
                    try:
                        db_execute("INSERT INTO Employees (emp_id, name, department, secondary_department, annual_balance, phone, exempt_report) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (emp_id) DO UPDATE SET name=EXCLUDED.name, department=EXCLUDED.department, secondary_department=EXCLUDED.secondary_department, phone=EXCLUDED.phone, exempt_report=EXCLUDED.exempt_report", 
                                   (new_emp_id, new_name, new_dept, new_sec_dept, DEFAULT_ANNUAL_BALANCE, new_phone, new_exempt))
                        db_execute("INSERT INTO Users (username, password, role, secondary_role, emp_id) VALUES (%s, %s, %s, %s, %s)", 
                                   (new_user, new_pwd, ROLE_MAP[role_choice], ROLE_MAP[sec_role_choice], new_emp_id))
                        st.success(f"تم إنشاء حساب ({new_name}) بنجاح!")
                    except: st.error("اسم المستخدم مسجل مسبقاً!")

    elif nav == "⚙ إدارة الحسابات":
        st.header("إدارة حسابات المستخدمين")
        conn = get_db_connection()
        users_df = pd.read_sql_query("SELECT u.username, u.password, u.emp_id, e.name, e.department, e.secondary_department, e.phone, e.exempt_report, u.role, u.secondary_role FROM Users u LEFT JOIN Employees e ON u.emp_id = e.emp_id ORDER BY u.username ASC", conn)
        conn.close()
        
        if not users_df.empty:
            display_df = users_df.copy()
            display_df.columns = ['المستخدم', 'الباسورد', 'الكود', 'الاسم', 'القسم الأساسي', 'القسم الإضافي', 'الهاتف', 'معفى', 'الصلاحية 1', 'الصلاحية 2']
            display_df['الصلاحية 1'] = display_df['الصلاحية 1'].map(DISPLAY_MAP)
            display_df['الصلاحية 2'] = display_df['الصلاحية 2'].map(DISPLAY_MAP)
            display_df['معفى'] = display_df['معفى'].map({True: 'نعم', False: 'لا', None: 'لا'})
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            st.divider()
            st.subheader("تعديل بيانات حساب موجود")
            selected_user = st.selectbox("📌 اختر الحساب المطلوب تعديله:", users_df['username'].tolist(), key="select_edit_user")
            curr_data = users_df[users_df['username'] == selected_user].iloc[0]
            curr_emp_id = curr_data['emp_id']
            curr_name = curr_data['name'] if pd.notna(curr_data['name']) else ""
            curr_dept = curr_data['department'] if pd.notna(curr_data['department']) and curr_data['department'] in COMPANY_DEPARTMENTS else COMPANY_DEPARTMENTS[0]
            curr_sec_dept = curr_data['secondary_department'] if pd.notna(curr_data['secondary_department']) and curr_data['secondary_department'] in ["لا يوجد"] + COMPANY_DEPARTMENTS else "لا يوجد"
            curr_phone = curr_data['phone'] if pd.notna(curr_data['phone']) else ""
            curr_exempt = curr_data['exempt_report'] if pd.notna(curr_data['exempt_report']) else False
            
            r1_txt = ROLE_REVERSE_MAP.get(curr_data['role'], "موظف عادي (Employee)")
            r2_txt = ROLE_REVERSE_MAP.get(curr_data['secondary_role'], "لا يوجد (None)")
            
            with st.form("edit_user_form"):
                c1, c2 = st.columns(2)
                new_name = c2.text_input("تعديل اسم الموظف", value=curr_name)
                new_username = c1.text_input("اسم المستخدم الجديد", value=selected_user)
                
                c3, c4 = st.columns(2)
                new_dept = c4.selectbox("تعديل القسم الأساسي", COMPANY_DEPARTMENTS, index=COMPANY_DEPARTMENTS.index(curr_dept) if curr_dept in COMPANY_DEPARTMENTS else 0)
                new_sec_dept = c3.selectbox("القسم الإضافي", ["لا يوجد"] + COMPANY_DEPARTMENTS, index=(["لا يوجد"] + COMPANY_DEPARTMENTS).index(curr_sec_dept) if curr_sec_dept in (["لا يوجد"] + COMPANY_DEPARTMENTS) else 0)
                
                c5, c6 = st.columns(2)
                new_role_choice = c6.selectbox("الصلاحية الأساسية", [r for r in ROLE_OPTIONS if r != "لا يوجد (None)"], index=[r for r in ROLE_OPTIONS if r != "لا يوجد (None)"].index(r1_txt) if r1_txt in [r for r in ROLE_OPTIONS if r != "لا يوجد (None)"] else 0)
                new_sec_role_choice = c5.selectbox("الصلاحية الإضافية", ROLE_OPTIONS, index=ROLE_OPTIONS.index(r2_txt) if r2_txt in ROLE_OPTIONS else 0)
                
                new_pwd = c6.text_input("كلمة المرور الجديدة (اختياري)")
                edit_phone = c5.text_input("تعديل رقم الهاتف", value=curr_phone)
                edit_exempt = st.checkbox("✔️ إعفاء الموظف من إجبارية تقديم التقرير اليومي", value=bool(curr_exempt))
                
                if st.form_submit_button("تحديث البيانات الشامل", type="primary"):
                    final_username = new_username.strip() if new_username.strip() else selected_user
                    try:
                        updates = ["role=%s", "secondary_role=%s"]; params = [ROLE_MAP[new_role_choice], ROLE_MAP[new_sec_role_choice]]
                        if final_username != selected_user: updates.append("username=%s"); params.append(final_username)
                        if new_pwd.strip(): updates.append("password=%s"); params.append(new_pwd.strip())
                        params.append(selected_user)
                        db_execute(f"UPDATE Users SET {', '.join(updates)} WHERE username=%s", tuple(params))
                        if curr_emp_id and str(curr_emp_id) not in ['0', 'owner']:
                            db_execute("UPDATE Employees SET name=%s, department=%s, secondary_department=%s, phone=%s, exempt_report=%s WHERE emp_id=%s", 
                                       (new_name.strip() if new_name.strip() else curr_name, new_dept, new_sec_dept, edit_phone, edit_exempt, curr_emp_id))
                        st.success("تم التحديث بنجاح!"); st.rerun()
                    except Exception as e: st.error(f"حدث خطأ: {e}")

            st.divider()
            st.subheader("🗑️ حذف حساب نهائياً")
            with st.form("delete_user_form"):
                user_to_delete = st.selectbox("اختر اسم المستخدم المراد حذفه:", users_df['username'].tolist(), key="select_del_user")
                if st.form_submit_button("إيقاف وحذف الحساب 🗑️", type="primary"):
                    if user_to_delete.lower() in ['admin', 'owner']: st.error("❌ لا يمكن حذف حسابات النظام الأساسية!")
                    else:
                        emp_id_to_del = users_df[users_df['username'] == user_to_delete].iloc[0]['emp_id']
                        db_execute("DELETE FROM Users WHERE username=%s", (user_to_delete,))
                        if emp_id_to_del and str(emp_id_to_del) not in ['0', 'owner']: db_execute("DELETE FROM Employees WHERE emp_id=%s", (emp_id_to_del,))
                        st.success(f"تم مسح الحساب ({user_to_delete}) بنجاح!"); st.rerun()

    elif nav == "📍 المواقع":
        st.header("إضافة مواقع الشركة للمقاولات (بواسطة الـ GPS)")
        if not GEO_AVAILABLE: st.error("مكتبة 'streamlit-js-eval' غير مثبتة.")
        else:
            if st.button("🔄 تحديث موقعي الآن"): st.rerun()
            loc_admin = get_geolocation()
            admin_lat, admin_lon = 0.0, 0.0
            if loc_admin and isinstance(loc_admin, dict) and 'coords' in loc_admin:
                admin_lat = float(loc_admin['coords']['latitude']); admin_lon = float(loc_admin['coords']['longitude'])
                st.success(f"📍 موقعك الحالي: خط العرض: {admin_lat:.6f} | خط الطول: {admin_lon:.6f}")
        
        with st.form("add_location_form"):
            loc_name = st.text_input("اسم الموقع / المشروع")
            c1, c2, c3 = st.columns(3)
            new_lat = c1.number_input("خط العرض", value=admin_lat, format="%.6f")
            new_lon = c2.number_input("خط الطول", value=admin_lon, format="%.6f")
            new_rad = c3.number_input("النطاق المسموح (بالمتر)", value=100.0, min_value=10.0)
            if st.form_submit_button("حفظ الموقع", type="primary") and loc_name.strip() != "":
                db_execute("INSERT INTO Locations (name, lat, lon, radius) VALUES (%s, %s, %s, %s)", (loc_name, new_lat, new_lon, new_rad))
                st.success("تم حفظ الموقع بنجاح!"); st.rerun()
                
        conn = get_db_connection()
        locations_df = pd.read_sql_query("SELECT id, name, lat, lon, radius FROM Locations ORDER BY name", conn)
        conn.close()
        if not locations_df.empty:
            locations_df.columns = ['id', 'اسم الموقع', 'خط العرض', 'خط الطول', 'النطاق']
            st.dataframe(locations_df.drop(columns=['id']), use_container_width=True)
            with st.form("delete_loc"):
                loc_to_delete = st.selectbox("حذف موقع:", locations_df['اسم الموقع'].tolist())
                if st.form_submit_button("حذف الفرع 🗑️"):
                    db_execute("DELETE FROM Locations WHERE name=%s", (loc_to_delete,))
                    st.success("تم الحذف بنجاح!"); st.rerun()

    elif nav == "📌 تقارير المناديب":
        st.header("شيت الحضور والانصراف المجمع")
        render_attendance_report()
        
    elif nav == "💾 النسخ الاحتياطي":
        st.header("💾 النسخ الاحتياطي الشامل (Database Dump)")
        st.info("يمكنك الآن تحميل نسخة احتياطية حقيقية كقاعدة بيانات (SQLite) بصيغة `.db` تحتوي على كل الجداول والملفات (بما فيها ملفات الـ PDF المرفوعة) بدون أي فقدان للبيانات.")
        if st.button("📥 إنشاء وتحميل قاعدة البيانات (DB File)", type="primary"):
            with st.spinner("جاري استخراج قاعدة البيانات وتجهيز الملف..."):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
                tables = [row[0] for row in cur.fetchall()]
                cur.close()
                
                tmp_db_path = tempfile.mktemp(suffix=".db")
                sqlite_conn = sqlite3.connect(tmp_db_path)
                for table in tables:
                    try:
                        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
                        df.to_sql(table, sqlite_conn, if_exists='replace', index=False)
                    except: pass
                sqlite_conn.close()
                conn.close()
                
                with open(tmp_db_path, "rb") as f: db_bytes = f.read()
                st.download_button(label="💾 اضغط هنا لتحميل ملف قاعدة البيانات (.db) الآن", data=db_bytes, file_name=f"Keyan_DB_Backup_{get_egypt_time().strftime('%Y%m%d_%H%M')}.db", mime="application/x-sqlite3")

# ==========================================
# دالة تتبع المستخلص للمالك والمهندسين
# ==========================================
def get_extract_blocker(status):
    if status == 'قيد التجهيز': return "مهندس المستخلصات (قيد التجهيز/يوجد معوقات)"
    if status == 'بانتظار اعتماد التخطيط': return "إدارة التخطيط (للمراجعة والاعتماد)"
    if status == 'بانتظار الصرف': return "إدارة الحسابات (جاهز للصرف)"
    if status == 'تم الصرف': return "مكتمل وتم الصرف ✅"
    if status == 'مرفوض فنياً': return "مرفوض - عاد لمهندس المستخلصات للتعديل"
    if status == 'مطلوب تعديلات': return "عاد لمهندس المستخلصات للتعديل"
    if status == 'مرفوض': return "مرفوض من الحسابات/الإدارة"
    if status == 'مراجعة نهائية': return "عاد للمراجعة"
    return status

# ==========================================
# دالة موحدة لإدارة المستخلصات (التخطيط والحسابات)
# ==========================================
def render_manage_extracts():
    st.header("📄 إدارة ومراجعة المستخلصات الهندسية")
    conn = get_db_connection()
    
    role = st.session_state.get('role', '')
    emp_id = st.session_state.get('emp_id')
    _, emp_dept, _ = get_employee_info(emp_id)
    is_planning_auth = (role == 'planning_engineer') or (emp_dept == "مهندسين إدارة وتخطيط")

    try:
        if is_planning_auth:
            query = "SELECT id, project_name, extract_name, amount, date, created_by, status, file_data, impediment_notes FROM Extracts WHERE status = 'بانتظار اعتماد التخطيط' ORDER BY id DESC"
        else:
            query = "SELECT id, project_name, extract_name, amount, date, created_by, status, file_data, impediment_notes FROM Extracts WHERE status IN ('بانتظار الصرف', 'تم الصرف') ORDER BY id DESC"
            
        ext_df = pd.read_sql_query(query, conn)
        
        if not ext_df.empty:
            for _, row in ext_df.iterrows():
                with st.expander(f"مستخلص: {row['extract_name']} | المشروع: {row['project_name']} | الحالة: {row['status']}"):
                    st.write(f"**القيمة:** {row['amount']} | **بواسطة:** {row['created_by']} | **التاريخ:** {row['date']}")
                    if pd.notna(row['impediment_notes']) and row['impediment_notes'].strip() != "":
                        st.warning(f"**معوقات وملاحظات المهندس:** {row['impediment_notes']}")
                        
                    file_content = row['file_data']
                    if file_content and isinstance(file_content, str) and len(file_content) > 10:
                        try:
                            decoded_bytes = base64.b64decode(file_content)
                            st.download_button("📥 تحميل المستخلص للمراجعة", data=decoded_bytes, file_name=f"{row['extract_name']}.pdf", mime="application/octet-stream", key=f"dl_mng_ext_{row['id']}")
                        except: pass
                    else: st.info("لا يوجد ملف مرفق.")
                    
                    c1, c2 = st.columns(2)
                    if is_planning_auth:
                        if c1.button("✅ اعتماد فني وتحويل للحسابات", key=f"eng_app_{row['id']}", type="primary"):
                            db_execute("UPDATE Extracts SET status='بانتظار الصرف' WHERE id=%s", (row['id'],)); st.rerun()
                        if c2.button("❌ إرجاع لوجود مشاكل فنية", key=f"eng_rej_{row['id']}"):
                            db_execute("UPDATE Extracts SET status='مرفوض فنياً' WHERE id=%s", (row['id'],)); st.rerun()
                    else:
                        if row['status'] != 'تم الصرف':
                            if c1.button("✅ تم صرف المستخلص", key=f"pay_{row['id']}", type="primary"):
                                db_execute("UPDATE Extracts SET status='تم الصرف' WHERE id=%s", (row['id'],)); st.rerun()
        else: st.info("لا يوجد مستخلصات في صندوق الوارد الخاص بإدارتك حالياً.")
    except: st.warning("جاري تهيئة جداول المستخلصات.")
    conn.close()

# ==========================================
# بوابة العقود والشؤون القانونية (Legal Portal)
# ==========================================
def legal_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("مسؤول الشؤون القانونية والعقود")
    
    nav = st.radio("القائمة:", ["📄 أرشفة العقود الموقعة", "💳 إدارة الشيكات البنكية", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()
    
    if nav == "📄 أرشفة العقود الموقعة":
        st.header("إرفاق وحفظ العقود الأصلية (Scanned)")
        st.info("اختر الوحدة المباعة من قسم المبيعات لترفع نسختها الموقعة في أرشيف الشركة.")
        conn = get_db_connection()
        units = pd.read_sql_query("SELECT unit_code, client_name, project_name FROM RealEstateUnits WHERE status IN ('مباعة', 'محجوزة')", conn)
        
        with st.form("add_contract"):
            if not units.empty:
                unit_opts = units['unit_code'] + " - " + units['client_name'] + " (" + units['project_name'] + ")"
                sel_unit = st.selectbox("اختر الوحدة المباعة:", unit_opts)
            else:
                sel_unit = st.text_input("كود الوحدة")
                
            uploaded_contract = st.file_uploader("إرفاق نسخة العقد الموقعة (PDF/صورة عالية الجودة)", type=['pdf', 'jpg', 'png'])
            if st.form_submit_button("حفظ العقد في الأرشيف 🔒", type="primary"):
                if uploaded_contract and sel_unit:
                    file_b64 = base64.b64encode(uploaded_contract.read()).decode('utf-8')
                    u_code = str(sel_unit).split(" - ")[0]
                    db_execute("UPDATE RealEstateUnits SET contract_file=%s WHERE unit_code=%s", (file_b64, u_code))
                    st.success("تم أرشفة العقد وربطه بالوحدة بنجاح!")
                else:
                    st.error("يرجى إرفاق الملف واختيار الوحدة!")
        
        st.divider()
        st.subheader("العقود المؤرشفة حالياً")
        archived = pd.read_sql_query("SELECT unit_code, client_name, contract_file FROM RealEstateUnits WHERE contract_file IS NOT NULL AND length(contract_file) > 10", conn)
        if not archived.empty:
            for _, row in archived.iterrows():
                with st.expander(f"📄 عقد وحدة: {row['unit_code']} | العميل: {row['client_name']}"):
                    try:
                        decoded_bytes = base64.b64decode(row['contract_file'])
                        st.download_button("📥 تحميل / عرض العقد", data=decoded_bytes, file_name=f"Contract_{row['unit_code']}.pdf", mime="application/octet-stream", key=f"dl_contract_{row['unit_code']}")
                    except: pass
        else: st.info("لا توجد عقود مؤرشفة في النظام.")
        conn.close()
        
    elif nav == "💳 إدارة الشيكات البنكية":
        st.header("تسجيل وأرشفة الشيكات البنكية للعملاء")
        conn = get_db_connection()
        units = pd.read_sql_query("SELECT unit_code, client_name FROM RealEstateUnits WHERE status IN ('مباعة', 'محجوزة')", conn)
        
        with st.form("add_cheque"):
            c1, c2 = st.columns(2)
            if not units.empty:
                unit_opts = units['unit_code'] + " - " + units['client_name']
                chq_unit = c2.selectbox("اختر الوحدة والعميل:", unit_opts)
            else:
                chq_unit = c2.text_input("كود الوحدة")
            
            chq_num = c1.text_input("رقم الشيك")
            chq_amt = c2.number_input("قيمة الشيك", min_value=0.0)
            chq_date = c1.date_input("تاريخ الاستحقاق")
            chq_status = c2.selectbox("حالة الشيك", ["في الخزنة", "مُقدم للبنك", "مُحصل", "مرفوض (مرتد)"])
            chq_file = st.file_uploader("إرفاق صورة الشيك (Scanned)", type=['pdf', 'jpg', 'png'])
            
            if st.form_submit_button("تسجيل الشيك 💳", type="primary"):
                if chq_num and chq_amt > 0:
                    file_b64 = base64.b64encode(chq_file.read()).decode('utf-8') if chq_file else ""
                    u_code = str(chq_unit).split(" - ")[0]
                    u_client = str(chq_unit).split(" - ")[1] if " - " in str(chq_unit) else ""
                    db_execute("INSERT INTO Cheques (unit_code, client_name, cheque_number, amount, due_date, file_data, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                               (u_code, u_client, chq_num, chq_amt, chq_date.strftime("%Y/%m/%d"), file_b64, chq_status))
                    st.success("تم تسجيل الشيك وحفظه في النظام بنجاح!")
                else: st.error("يرجى إدخال رقم الشيك وقيمته.")
        
        st.divider()
        st.subheader("محفظة الشيكات")
        chq_df = pd.read_sql_query("SELECT id, unit_code, client_name, cheque_number, amount, due_date, status, file_data FROM Cheques ORDER BY due_date ASC", conn)
        if not chq_df.empty:
            display_df = chq_df.drop(columns=['id', 'file_data'])
            display_df.columns = ['رقم الوحدة', 'العميل', 'رقم الشيك', 'القيمة', 'تاريخ الاستحقاق', 'الحالة']
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            html_chq = generate_html_report("تقرير محفظة الشيكات البنكية - كيان الشرقية", display_df)
            st.download_button("🖨️ طباعة تقرير الشيكات (رسمي PDF)", data=html_chq, file_name=f"Cheques_{get_egypt_time().strftime('%Y%m%d')}.html", mime='text/html')
            
            for _, row in chq_df.iterrows():
                if row['file_data'] and len(row['file_data']) > 10:
                    with st.expander(f"صورة شيك رقم: {row['cheque_number']} | الوحدة: {row['unit_code']}"):
                        try:
                            dec = base64.b64decode(row['file_data'])
                            st.download_button("📥 تحميل صورة الشيك", data=dec, file_name=f"Cheque_{row['cheque_number']}.pdf", mime="application/octet-stream", key=f"dl_chq_{row['id']}")
                        except: pass
        else: st.info("لا توجد شيكات مسجلة.")
        conn.close()
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

# ==========================================
# باقي البوابات (حسابات، تراخيص، مبيعات، مهندس، موظف)
# ==========================================
def accountant_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("المحاسب")
    nav = st.radio("القائمة:", ["💰 إدارة الأقساط", "📄 إدارة المستخلصات", "👤 لوحتي الشخصية"], horizontal=True)
    if nav == "💰 إدارة الأقساط":
        with st.form("add_fin"):
            c1, c2 = st.columns(2)
            proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
            inst_type = c2.selectbox("النوع", ["قسط تنفيذ", "قسط جهاز", "أخرى"])
            amount = c1.number_input("المبلغ", min_value=0.0)
            due_date = c2.date_input("الاستحقاق")
            status = st.selectbox("الحالة", ["مستحق (لم يُدفع)", "مدفوع", "متأخر"])
            if st.form_submit_button("تسجيل القسط", type="primary"):
                db_execute("INSERT INTO ProjectFinancials (project_name, installment_type, amount, due_date, status) VALUES (%s, %s, %s, %s, %s)", (proj, inst_type, amount, due_date.strftime("%Y/%m/%d"), status))
                st.success("تم التسجيل بنجاح!")
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, installment_type, amount, due_date, status FROM ProjectFinancials", conn)
        conn.close()
        if not df.empty: st.dataframe(df.rename(columns={'project_name':'المشروع','installment_type':'النوع','amount':'المبلغ','due_date':'تاريخ','status':'الحالة'}), hide_index=True)
    elif nav == "📄 إدارة المستخلصات": render_manage_extracts()
    else: render_employee_dashboard(emp_id, balance)

def licensing_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("مسؤول التراخيص")
    nav = st.radio("القائمة:", ["📜 التراخيص (خزنة المستندات)", "👤 لوحتي الشخصية"], horizontal=True)
    if nav == "📜 التراخيص (خزنة المستندات)":
        with st.form("add_lic"):
            c1, c2 = st.columns(2)
            proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
            lic_name = c2.text_input("اسم الترخيص")
            due_date = c1.date_input("الانتهاء")
            status = c2.selectbox("الحالة", ["سارية", "تحت الإجراء", "منتهية"])
            uploaded_file = st.file_uploader("إرفاق ملف الترخيص (PDF/صورة) - أقل من 5 ميجا", type=['pdf', 'jpg', 'png'])
            if st.form_submit_button("تسجيل الترخيص", type="primary") and lic_name:
                file_b64 = base64.b64encode(uploaded_file.read()).decode('utf-8') if uploaded_file else ""
                db_execute("INSERT INTO ProjectLicenses (project_name, license_name, due_date, status, file_data) VALUES (%s, %s, %s, %s, %s)", (proj, lic_name, due_date.strftime("%Y/%m/%d"), status, file_b64))
                st.success("تم التسجيل ورفع المستند بنجاح!")
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, license_name, due_date, status FROM ProjectLicenses", conn)
        conn.close()
        if not df.empty: st.dataframe(df.rename(columns={'project_name':'المشروع','license_name':'الترخيص','due_date':'تاريخ الانتهاء','status':'الحالة'}), hide_index=True)
    else: render_employee_dashboard(emp_id, balance)

def engineer_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("المهندس")
    nav = st.radio("القائمة:", ["📐 الرسومات (خزنة الملفات)", "👤 لوحتي الشخصية"], horizontal=True)
    if nav == "📐 الرسومات (خزنة الملفات)":
        with st.form("add_draw"):
            c1, c2 = st.columns(2)
            proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
            draw_name = c2.text_input("اسم الرسم")
            due_date = c1.date_input("التسليم")
            status = c2.selectbox("الحالة", ["قيد التنفيذ", "تحت المراجعة", "مكتملة"])
            uploaded_file = st.file_uploader("إرفاق لوحة الرسم (PDF/صورة) - أقل من 5 ميجا", type=['pdf', 'jpg', 'png', 'dwg'])
            if st.form_submit_button("تسجيل الرسم", type="primary") and draw_name:
                file_b64 = base64.b64encode(uploaded_file.read()).decode('utf-8') if uploaded_file else ""
                db_execute("INSERT INTO ProjectDrawings (project_name, drawing_name, due_date, status, file_data) VALUES (%s, %s, %s, %s, %s)", (proj, draw_name, due_date.strftime("%Y/%m/%d"), status, file_b64))
                st.success("تم التسجيل ورفع اللوحة بنجاح!")
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, drawing_name, due_date, status FROM ProjectDrawings", conn)
        conn.close()
        if not df.empty: st.dataframe(df.rename(columns={'project_name':'المشروع','drawing_name':'اسم الرسم','due_date':'تاريخ التسليم','status':'الحالة'}), hide_index=True)
    else: render_employee_dashboard(emp_id, balance)

def extracts_engineer_portal():
    emp_id = st.session_state['emp_id']
    emp_name, _, balance = get_employee_info(emp_id)
    render_sidebar("مهندس المستخلصات")
    nav = st.radio("القائمة:", ["📄 إنشاء وتجهيز مستخلص", "👤 لوحتي الشخصية"], horizontal=True)
    if nav == "📄 إنشاء وتجهيز مستخلص":
        st.header("إضافة مستخلص جديد وتجهيزه")
        with st.form("add_extract"):
            c1, c2 = st.columns(2)
            proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
            ext_name = c2.text_input("اسم / رقم المستخلص")
            ext_amount = c1.number_input("القيمة المالية (المبدئية)", min_value=0.0)
            ext_date = c2.date_input("تاريخ الإنشاء")
            impediment = st.text_input("أسباب التعطيل / النواقص (إن وجدت) مثل: حصر موقع...")
            uploaded_ext = st.file_uploader("إرفاق مسودة المستخلص (PDF)", type=['pdf', 'jpg', 'png'])
            if st.form_submit_button("حفظ كمستخلص قيد التجهيز 💾", type="primary"):
                if ext_name and ext_amount > 0:
                    file_b64 = base64.b64encode(uploaded_ext.read()).decode('utf-8') if uploaded_ext else ""
                    db_execute("INSERT INTO Extracts (project_name, extract_name, amount, date, created_by, status, file_data, impediment_notes) VALUES (%s, %s, %s, %s, %s, 'قيد التجهيز', %s, %s)", (proj, ext_name, ext_amount, ext_date.strftime("%Y/%m/%d"), emp_name, file_b64, impediment))
                    st.success("تم إضافة المستخلص لحسابك للعمل عليه!")
                else: st.error("يرجى كتابة اسم المستخلص وتحديد قيمته!")
        st.divider()
        st.subheader("مستخلصاتي (العمل الحالي)")
        conn = get_db_connection()
        try:
            my_ext = pd.read_sql_query("SELECT id, project_name, extract_name, amount, status, impediment_notes FROM Extracts WHERE created_by=%s ORDER BY id DESC", conn, params=(emp_name,))
            if not my_ext.empty:
                for _, row in my_ext.iterrows():
                    with st.expander(f"{row['extract_name']} | المشروع: {row['project_name']} | الحالة: {row['status']}"):
                        st.write(f"**القيمة المبدئية:** {row['amount']}")
                        if row['status'] in ['قيد التجهيز', 'مرفوض فنياً', 'مطلوب تعديلات']:
                            new_imped = st.text_input("تحديث المعوقات أو النواقص:", value=row['impediment_notes'] if pd.notna(row['impediment_notes']) else "", key=f"imp_{row['id']}")
                            col1, col2 = st.columns(2)
                            if col1.button("تحديث النواقص 📝", key=f"upd_{row['id']}"):
                                db_execute("UPDATE Extracts SET impediment_notes=%s WHERE id=%s", (new_imped, row['id'])); st.rerun()
                            if col2.button("🚀 إصدار المستخلص (إرسال للتخطيط)", key=f"iss_{row['id']}", type="primary"):
                                db_execute("UPDATE Extracts SET status='بانتظار اعتماد التخطيط', impediment_notes='تم الإنجاز - بانتظار الاعتماد' WHERE id=%s", (row['id'],)); st.rerun()
                        else: st.info("تم إصدار هذا المستخلص ولم يعد في عهدتك.")
            else: st.info("لا توجد مستخلصات حالياً.")
        except: pass
        conn.close()
    else: render_employee_dashboard(emp_id, balance)

def planning_engineer_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("مهندس إدارة وتخطيط")
    nav = st.radio("القائمة:", ["📄 مراجعة واعتماد المستخلصات", "👤 لوحتي الشخصية"], horizontal=True)
    if nav == "📄 مراجعة واعتماد المستخلصات": render_manage_extracts()
    else: render_employee_dashboard(emp_id, balance)

def sales_portal():
    emp_id = st.session_state['emp_id']
    emp_name, _, balance = get_employee_info(emp_id)
    render_sidebar("المبيعات وخدمة العملاء")
    nav = st.radio("القائمة:", ["🏢 إدارة الوحدات والمبيعات", "💸 أقساط العملاء", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()
    if nav == "🏢 إدارة الوحدات والمبيعات":
        st.header("إضافة ومتابعة الوحدات العقارية")
        with st.form("add_unit"):
            c1, c2, c3 = st.columns(3)
            u_proj = c3.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
            u_code = c2.text_input("رقم / كود الوحدة")
            u_status = c1.selectbox("حالة الوحدة", ["متاحة", "مباعة", "محجوزة"])
            c4, c5 = st.columns(2)
            u_client = c5.text_input("اسم العميل (إن وجد)")
            u_price = c4.number_input("إجمالي السعر (جنية)", min_value=0.0)
            u_notes = st.text_input("ملاحظات إضافية")
            if st.form_submit_button("تسجيل / تحديث بيانات الوحدة", type="primary"):
                if u_code and u_proj:
                    db_execute("INSERT INTO RealEstateUnits (project_name, unit_code, status, client_name, total_price, notes) VALUES (%s, %s, %s, %s, %s, %s)", (u_proj, u_code, u_status, u_client, u_price, u_notes))
                    st.success("تم تحديث حالة الوحدة بنجاح!")
                else: st.error("يرجى إدخال اسم المشروع وكود الوحدة.")
        st.divider()
        st.subheader("حالة الوحدات المضافة")
        conn = get_db_connection()
        try:
            units_df = pd.read_sql_query("SELECT project_name, unit_code, status, client_name, total_price, notes FROM RealEstateUnits ORDER BY id DESC", conn)
            if not units_df.empty:
                disp_df = units_df.rename(columns={'project_name':'المشروع','unit_code':'الرقم/الكود','status':'الحالة','client_name':'اسم العميل','total_price':'الإجمالي','notes':'ملاحظات'})
                st.dataframe(disp_df, use_container_width=True, hide_index=True)
                
                html_sales = generate_html_report("تقرير المبيعات والوحدات العقارية - كيان الشرقية", disp_df)
                st.download_button("🖨️ طباعة تقرير المبيعات (رسمي PDF)", data=html_sales, file_name=f"Sales_{get_egypt_time().strftime('%Y%m%d')}.html", mime='text/html')
        except: pass
        conn.close()
    elif nav == "💸 أقساط العملاء":
        st.header("إدارة أقساط الوحدات المباعة ومواعيد الاستحقاق")
        conn = get_db_connection()
        try: units_list = pd.read_sql_query("SELECT unit_code, client_name FROM RealEstateUnits WHERE status IN ('مباعة', 'محجوزة')", conn)
        except: units_list = pd.DataFrame()
        with st.form("add_installment"):
            c1, c2 = st.columns(2)
            if not units_list.empty:
                unit_options = units_list['unit_code'] + " - " + units_list['client_name']
                i_unit = c2.selectbox("اختر الوحدة والعميل", unit_options)
            else: i_unit = c2.text_input("كود الوحدة والعميل (لا يوجد وحدات مباعة مسجلة)")
            i_amount = c1.number_input("قيمة القسط المستحق", min_value=0.0)
            i_date = c2.date_input("تاريخ الاستحقاق")
            i_status = c1.selectbox("حالة الدفع", ["مستحق (لم يُدفع)", "مدفوع", "متأخر"])
            if st.form_submit_button("تسجيل القسط", type="primary"):
                u_code = str(i_unit).split(" - ")[0] if " - " in str(i_unit) else str(i_unit)
                u_client = str(i_unit).split(" - ")[1] if " - " in str(i_unit) else ""
                db_execute("INSERT INTO UnitInstallments (unit_code, client_name, amount, due_date, status) VALUES (%s, %s, %s, %s, %s)", (u_code, u_client, i_amount, i_date.strftime("%Y/%m/%d"), i_status))
                st.success("تم تسجيل القسط بنجاح!")
        st.divider()
        st.subheader("جدول استحقاق الأقساط")
        try:
            inst_df = pd.read_sql_query("SELECT unit_code, client_name, amount, due_date, status FROM UnitInstallments ORDER BY due_date ASC", conn)
            if not inst_df.empty:
                disp_df = inst_df.rename(columns={'unit_code':'رقم الوحدة','client_name':'العميل','amount':'المبلغ','due_date':'تاريخ الاستحقاق','status':'الحالة'})
                st.dataframe(disp_df, use_container_width=True, hide_index=True)
                
                html_inst = generate_html_report("تقرير الأقساط المستحقة - كيان الشرقية", disp_df)
                st.download_button("🖨️ طباعة تقرير الأقساط (رسمي PDF)", data=html_inst, file_name=f"Installments_{get_egypt_time().strftime('%Y%m%d')}.html", mime='text/html')
        except: pass
        conn.close()
    elif nav == "👤 لوحتي الشخصية": render_employee_dashboard(emp_id, balance)

def hr_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("موارد بشرية (HR)")
    nav = st.radio("القائمة:", ["📝 تقارير الحضور والانصراف للشركة", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()
    if nav == "📝 تقارير الحضور والانصراف للشركة": render_attendance_report()
    elif nav == "👤 لوحتي الشخصية": render_employee_dashboard(emp_id, balance)

def admin_manager_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("المدير الإداري")
    render_smart_alerts()
    nav = st.radio("القائمة:", ["📊 لوحة القيادة", "✅ طلبات الموظفين", "📋 إسناد مهام", "📄 إدارة المستخلصات", "📝 تقارير الحضور", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()
    if nav == "📊 لوحة القيادة": render_company_dashboard()
    elif nav == "✅ طلبات الموظفين":
        st.header("إدارة طلبات الموظفين (جميع الأقسام)")
        conn = get_db_connection()
        reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, e.department, r.date, r.req_type, r.notes FROM Requests r JOIN Employees e ON r.emp_id = e.emp_id WHERE r.status = 'قيد الانتظار' AND r.emp_id != %s", conn, params=(emp_id,))
        conn.close()
        if reqs.empty: st.success("لا توجد طلبات معلقة في الشركة حالياً.")
        else:
            for _, row in reqs.iterrows():
                with st.expander(f"طلب من: {row['name']} (القسم: {row['department']}) - نوع الطلب: {row['req_type']}"):
                    st.write(f"**الملاحظات:** {row['notes']}")
                    c1, c2 = st.columns(2)
                    if c1.button("موافقة واعتماد", key=f"app_{row['id']}", type="primary"):
                        db_execute("UPDATE Requests SET status='مقبول' WHERE id=%s", (row['id'],)); db_execute("INSERT INTO Permissions VALUES (%s, %s, %s)", (row['emp_id'], row['date'], row['req_type'])); st.rerun()
                    if c2.button("رفض الطلب", key=f"rej_{row['id']}"):
                        db_execute("UPDATE Requests SET status='مرفوض' WHERE id=%s", (row['id'],)); st.rerun()
    elif nav == "📋 إسناد مهام": render_task_delegation("الكل")
    elif nav == "📄 إدارة المستخلصات": render_manage_extracts()
    elif nav == "📝 تقارير الحضور": render_attendance_report()
    elif nav == "👤 لوحتي الشخصية": render_employee_dashboard(emp_id, balance)

def manager_portal():
    emp_id = st.session_state['emp_id']
    _, emp_dept, balance = get_employee_info(emp_id)
    render_sidebar(f"رئيس قسم")
    nav = st.radio("القائمة:", ["✅ طلبات القسم", "📋 إسناد مهام للقسم", "📝 تقارير دوام القسم", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()
    if nav == "✅ طلبات القسم":
        st.header(f"طلبات الموظفين في قسمك")
        conn = get_db_connection()
        reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, r.date, r.req_type, r.notes FROM Requests r JOIN Employees e ON r.emp_id = e.emp_id WHERE (e.department = %s OR e.secondary_department = %s) AND r.status = 'قيد الانتظار' AND r.emp_id != %s", conn, params=(emp_dept, emp_dept, emp_id))
        conn.close()
        if reqs.empty: st.success("لا توجد طلبات معلقة لفريقك حالياً.")
        else:
            for _, row in reqs.iterrows():
                with st.expander(f"طلب من: {row['name']} - {row['req_type']}"):
                    c1, c2 = st.columns(2)
                    if c1.button("موافقة", key=f"app_{row['id']}", type="primary"):
                        db_execute("UPDATE Requests SET status='مقبول' WHERE id=%s", (row['id'],)); db_execute("INSERT INTO Permissions VALUES (%s, %s, %s)", (row['emp_id'], row['date'], row['req_type'])); st.rerun()
                    if c2.button("رفض", key=f"rej_{row['id']}"):
                        db_execute("UPDATE Requests SET status='مرفوض' WHERE id=%s", (row['id'],)); st.rerun()
    elif nav == "📋 إسناد مهام للقسم": render_task_delegation(emp_dept)
    elif nav == "📝 تقارير دوام القسم": render_attendance_report(department_filter=emp_dept)
    elif nav == "👤 لوحتي الشخصية": render_employee_dashboard(emp_id, balance)

def owner_portal():
    render_sidebar("المالك")
    render_smart_alerts()
    st.title("👑 لوحة تحكم المالك")
    nav = st.radio("القائمة:", ["📊 لوحة القيادة", "📑 تقارير المهام", "📈 الموقف المالي والهندسي", "📄 تتبع المستخلصات", "🏢 مبيعات وعقود وشيكات"], horizontal=True)
    st.divider()

    if nav == "📊 لوحة القيادة": render_company_dashboard()
    elif nav == "📑 تقارير المهام":
        conn = get_db_connection()
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع لعرض المهام:", project_list)
        reports = pd.read_sql_query("SELECT w.date, e.name, e.department, w.daily_report FROM WebAttendance w JOIN Employees e ON w.emp_id = e.emp_id WHERE w.project_name = %s AND w.action IN ('انصراف', 'تقرير', 'إنجاز مهمة') ORDER BY w.id DESC", conn, params=(selected_project,))
        if not reports.empty: 
            reports.columns = ['التاريخ', 'الموظف', 'القسم', 'الإنجاز']
            st.dataframe(reports, use_container_width=True, hide_index=True)
        else: st.info("لا يوجد تقارير مسجلة لهذا المشروع.")
        conn.close()
    elif nav == "📈 الموقف المالي والهندسي":
        conn = get_db_connection()
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع:", project_list)
        st.markdown("### 💰 الأقساط المالية (مقاولات)")
        fin_df = pd.read_sql_query("SELECT installment_type, amount, due_date, status FROM ProjectFinancials WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
        if not fin_df.empty: st.dataframe(fin_df, use_container_width=True, hide_index=True)
        else: st.info("لا يوجد أقساط")
        st.markdown("### 📜 التراخيص ومستنداتها")
        lic_df = pd.read_sql_query("SELECT license_name, due_date, status, file_data FROM ProjectLicenses WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
        if not lic_df.empty:
            for _, row in lic_df.iterrows():
                with st.expander(f"ترخيص: {row['license_name']} | الحالة: {row['status']}"):
                    st.write(f"تاريخ الانتهاء: {row['due_date']}")
                    file_content = row['file_data']
                    if file_content and isinstance(file_content, str) and len(file_content) > 10:
                        try:
                            decoded_bytes = base64.b64decode(file_content)
                            st.download_button("📥 تحميل المستند", data=decoded_bytes, file_name=f"{row['license_name']}.pdf", mime="application/octet-stream", key=f"dl_lic_{row['license_name']}")
                        except: pass
        else: st.info("لا يوجد تراخيص")
        st.markdown("### 📐 الرسومات الهندسية")
        draw_df = pd.read_sql_query("SELECT drawing_name, due_date, status, file_data FROM ProjectDrawings WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
        if not draw_df.empty:
            for _, row in draw_df.iterrows():
                with st.expander(f"رسم: {row['drawing_name']} | الحالة: {row['status']}"):
                    st.write(f"تاريخ التسليم: {row['due_date']}")
                    draw_content = row['file_data']
                    if draw_content and isinstance(draw_content, str) and len(draw_content) > 10:
                        try:
                            decoded_draw = base64.b64decode(draw_content)
                            st.download_button("📥 تحميل لوحة الرسم", data=decoded_draw, file_name=f"{row['drawing_name']}.pdf", mime="application/octet-stream", key=f"dl_drw_{row['drawing_name']}")
                        except: pass
        else: st.info("لا يوجد رسومات")
        conn.close()
    elif nav == "📄 تتبع المستخلصات":
        st.header("📄 رادار وتتبع مسار المستخلصات الهندسية")
        conn = get_db_connection()
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع لعرض مستخلصاته:", project_list)
        try:
            ext_df = pd.read_sql_query("SELECT id, extract_name, amount, date, created_by, status, impediment_notes, file_data FROM Extracts WHERE project_name = %s ORDER BY id DESC", conn, params=(selected_project,))
            if not ext_df.empty:
                for _, row in ext_df.iterrows():
                    blocker = get_extract_blocker(row['status'])
                    with st.expander(f"مستخلص: {row['extract_name']} | القيمة: {row['amount']} | الحالة: {row['status']}"):
                        st.write(f"**تاريخ الإنشاء:** {row['date']} | **بواسطة:** {row['created_by']}")
                        st.success(f"📍 **المستخلص الآن في عهدة:** {blocker}")
                        if pd.notna(row['impediment_notes']) and row['impediment_notes'].strip() != "":
                            st.warning(f"**معوقات وملاحظات مسجلة عليه:** {row['impediment_notes']}")
                        file_content = row['file_data']
                        if file_content and isinstance(file_content, str) and len(file_content) > 10:
                            try:
                                decoded_bytes = base64.b64decode(file_content)
                                st.download_button("📥 تحميل المستخلص (PDF)", data=decoded_bytes, file_name=f"{row['extract_name']}_extract.pdf", mime="application/octet-stream", key=f"dl_trk_ext_{row['id']}")
                            except: pass
            else: st.info("لا يوجد مستخلصات مسجلة لهذا المشروع حتى الآن.")
        except: pass
        conn.close()
    elif nav == "🏢 مبيعات وعقود وشيكات":
        st.header("إحصائيات المبيعات، العقود، والشيكات البنكية")
        conn = get_db_connection()
        try:
            units_df = pd.read_sql_query("SELECT project_name, unit_code, status, client_name, total_price, contract_file FROM RealEstateUnits ORDER BY id DESC", conn)
            if not units_df.empty:
                st.subheader("الوحدات المضافة وحالتها")
                display_units = units_df.copy()
                display_units['يوجد عقد؟'] = display_units['contract_file'].apply(lambda x: "نعم 📄" if pd.notna(x) and len(str(x))>10 else "لا ❌")
                display_units = display_units.drop(columns=['contract_file'])
                display_units.columns = ['المشروع', 'رقم الوحدة', 'الحالة', 'اسم العميل', 'الإجمالي', 'يوجد عقد؟']
                st.dataframe(display_units, use_container_width=True, hide_index=True)
                
                st.subheader("محفظة الشيكات البنكية")
                chq_df = pd.read_sql_query("SELECT unit_code, client_name, cheque_number, amount, due_date, status FROM Cheques ORDER BY due_date ASC", conn)
                if not chq_df.empty:
                    chq_df.columns = ['الوحدة', 'العميل', 'رقم الشيك', 'المبلغ', 'تاريخ الاستحقاق', 'الحالة']
                    st.dataframe(chq_df, use_container_width=True, hide_index=True)
                else: st.info("لا توجد شيكات مسجلة.")
            else:
                st.info("لا توجد وحدات أو مبيعات مسجلة حتى الآن.")
        except: pass
        conn.close()

def employee_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    render_sidebar("موظف")
    render_employee_dashboard(emp_id, balance)

# ==========================================
# 10. الشاشة المشتركة للجميع (البصمة، التقرير الحر، والمهام المسندة)
# ==========================================
def render_employee_dashboard(emp_id, balance):
    month, delay_mins, absent_str, overtime_mins = get_employee_stats(emp_id)
    today_date = get_egypt_time().strftime("%Y/%m/%d")
    now_dt = get_egypt_time()
    
    try:
        is_exempt = db_fetchone("SELECT exempt_report FROM Employees WHERE emp_id=%s", (emp_id,))
        is_exempt = is_exempt[0] if is_exempt and is_exempt[0] is not None else False
    except:
        is_exempt = False
    
    try:
        has_checked_in = db_fetchone("SELECT COUNT(*) FROM WebAttendance WHERE emp_id=%s AND date=%s AND action='حضور'", (emp_id, today_date))[0] > 0
        if not has_checked_in and (now_dt.hour > 11 or (now_dt.hour == 11 and now_dt.minute >= 30)):
            st.error("⏰ **تنبيه عاجل:** لقد تجاوزت الساعة 11:30 صباحاً ولم تقم بتسجيل حضورك اليوم! يرجى إثبات الحضور فوراً لتجنب خصم اليوم.")
    except: pass

    try:
        pending_tasks = db_fetchone("SELECT COUNT(*) FROM Tasks WHERE emp_id=%s AND status='قيد التنفيذ'", (emp_id,))[0]
        if pending_tasks > 0:
            st.warning(f"🔔 **تنبيه عمل:** لديك ({pending_tasks}) مهمة مسندة بانتظار إنجازها! راجع قسم 'بصمة وتقارير'.")
    except: pass

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("الرصيد المتبقي", f"{balance} يوم")
    c2.metric("التأخيرات الكلية", f"{format_hhmm(delay_mins)} ساعة")
    c3.metric("الوقت الإضافي", f"{format_hhmm(overtime_mins)} ساعة")
    
    try: pending = db_fetchone("SELECT COUNT(*) FROM Requests WHERE emp_id=%s AND status='قيد الانتظار'", (emp_id,))[0]
    except: pending = 0
    c4.metric("طلبات معلقة", pending)
    
    st.divider()
    sub_nav = st.radio("العمليات المتاحة:", ["📍 بصمة وتقارير وإنجاز مهام", "📝 تقديم طلب جديد", "🌴 سجلاتي"], horizontal=True)
    
    if sub_nav == "📍 بصمة وتقارير وإنجاز مهام":
        locations = db_fetchall("SELECT name, lat, lon, radius FROM Locations ORDER BY name")
        if not locations: st.error("لم يتم تسجيل فروع أو مواقع للشركة بعد.")
        elif not GEO_AVAILABLE: st.error("مكتبة Location غير مثبتة.")
        else:
            loc = get_geolocation()
            if loc and isinstance(loc, dict) and 'coords' in loc:
                emp_lat = float(loc['coords']['latitude']); emp_lon = float(loc['coords']['longitude'])
                min_distance, closest_loc_name, is_allowed = float('inf'), None, False
                for l_name, l_lat, l_lon, l_rad in locations:
                    dist = haversine(l_lat, l_lon, emp_lat, emp_lon)
                    if dist < min_distance: min_distance = dist; closest_loc_name = l_name; is_allowed = (dist <= l_rad)
                
                if is_allowed:
                    st.success(f"✅ أنت داخل نطاق: {closest_loc_name}")
                    camera_photo = st.camera_input("التقط صورة لإثبات الحضور أو الانصراف")
                    if camera_photo:
                        img = Image.open(camera_photo); img.thumbnail((300, 300)); buffered = io.BytesIO(); img.save(buffered, format="JPEG", quality=85)
                        photo_uri = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}"
                        
                        try: has_checked_in = db_fetchone("SELECT COUNT(*) FROM WebAttendance WHERE emp_id=%s AND date=%s AND action='حضور'", (emp_id, today_date))[0] > 0
                        except: has_checked_in = False

                        if not has_checked_in:
                            if st.button("🟢 تسجيل حضور اليوم", use_container_width=True):
                                db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo) VALUES (%s, %s, %s, 'حضور', %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri))
                                st.success("تم تسجيل الحضور بنجاح!"); st.rerun() 
                        else:
                            st.info("✅ تم تسجيل حضورك اليوم بنجاح.")
                            
                            conn = get_db_connection()
                            try: tasks = pd.read_sql_query("SELECT id, assigner, project_name, task_desc, due_date FROM Tasks WHERE emp_id=%s AND status='قيد التنفيذ'", conn, params=(emp_id,))
                            except: tasks = pd.DataFrame()
                            conn.close()
                            
                            if not tasks.empty:
                                st.markdown("### 📋 المهام المسندة إليك من الإدارة")
                                for _, row in tasks.iterrows():
                                    with st.expander(f"🔴 مهمة بمشروع: {row['project_name']} (التسليم: {row['due_date']})"):
                                        st.write(f"**التفاصيل:** {row['task_desc']}")
                                        task_reply = st.text_area("تقرير إنجاز المهمة", key=f"reply_{row['id']}")
                                        if st.button("إتمام المهمة ✅", key=f"done_{row['id']}", type="primary"):
                                            if task_reply.strip():
                                                db_execute("UPDATE Tasks SET status='مكتملة', employee_reply=%s WHERE id=%s", (task_reply, row['id']))
                                                db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'إنجاز مهمة', %s, %s, %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri, row['project_name'], "إنجاز مهمة مسندة: " + task_reply))
                                                st.success("تم الإغلاق وإرسال التقرير للمدير!"); st.rerun()
                                            else: st.error("اكتب تقرير الإنجاز أولاً!")
                            
                            st.markdown("---")
                            st.markdown("### 📝 إضافة تقرير حر أو تسجيل انصراف")
                            selected_proj = st.selectbox("المشروع (الاتحاد) / مهامك", [f"اتحاد {i}" for i in range(1, 46)] + ["أخرى"])
                            
                            if is_exempt:
                                st.info("💡 حسابك مُعفى من إجبارية تقديم التقرير اليومي، يمكنك تسجيل الانصراف مباشرة.")
                                daily_rep = st.text_area("تفاصيل الإنجاز اليومي (اختياري)", placeholder="يمكنك تركه فارغاً...")
                            else:
                                daily_rep = st.text_area("تفاصيل الإنجاز اليومي (إجباري)*", placeholder="يجب كتابة ما أنجزته اليوم لتتمكن من رفع التقرير أو الانصراف...")

                            c_btn1, c_btn2 = st.columns(2)
                            with c_btn1:
                                if st.button("➕ رفع التقرير الحر (مستمر بالعمل)", use_container_width=True):
                                    if is_exempt or daily_rep.strip():
                                        db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'تقرير', %s, %s, %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri, selected_proj, daily_rep))
                                        st.success("تم حفظ إنجازك!")
                                    else: st.error("❌ عذراً، يجب كتابة التقرير اليومي أولاً!")
                            with c_btn2:
                                if st.button("🔴 تسجيل انصراف نهائي اليوم", use_container_width=True):
                                    if is_exempt or daily_rep.strip():
                                        db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'انصراف', %s, %s, %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri, selected_proj, daily_rep))
                                        st.success("تم تسجيل الانصراف بنجاح!"); st.rerun() 
                                    else: st.error("❌ عذراً، لا يمكنك تسجيل الانصراف بدون كتابة التقرير اليومي!")
                else: st.error(f"❌ أنت خارج النطاق المسموح. أقرب موقع عمل لك هو ({closest_loc_name}) ويبعد عنك بمسافة {int(min_distance)} متر.")
            else: st.info("جاري تحديد موقعك الجغرافي... يرجى التأكد من تشغيل وتصريح الـ GPS للمتصفح.")

    elif sub_nav == "📝 تقديم طلب جديد":
        with st.form("emp_req"):
            req_type = st.selectbox("النوع", ["إجازة", "مأمورية", "إذن", "عمل من المنزل"])
            req_date = st.date_input("التاريخ")
            notes = st.text_input("السبب أو التفاصيل")
            if st.form_submit_button("إرسال الطلب", type="primary"):
                db_execute("INSERT INTO Requests (emp_id, date, req_type, notes, status) VALUES (%s, %s, %s, %s, 'قيد الانتظار')", (emp_id, req_date.strftime("%Y/%m/%d"), req_type, notes))
                st.success("تم إرسال الطلب لمديرك المباشر بنجاح.")
                
    elif sub_nav == "🌴 سجلاتي":
        conn = get_db_connection()
        try: df = pd.read_sql_query("SELECT date, req_type, status FROM Requests WHERE emp_id=%s ORDER BY id DESC", conn, params=(emp_id,))
        except: df = pd.DataFrame()
        conn.close()
        if not df.empty:
            df.columns = ['التاريخ', 'نوع الطلب', 'الحالة']
            st.dataframe(df, hide_index=True, use_container_width=True)
        else: st.info("لا توجد طلبات مسجلة لك حتى الآن.")

# ==========================================
# 11. نظام التوجيه (Routing) لجميع الصلاحيات
# ==========================================
if not st.session_state['logged_in']: login_page()
else:
    role = st.session_state.get('current_role', st.session_state.get('role', 'employee'))
    
    if role == 'admin' or role == 'it': admin_portal() 
    elif role == 'admin_manager': admin_manager_portal()
    elif role == 'manager': manager_portal()
    elif role == 'owner': owner_portal()
    elif role == 'accountant': accountant_portal()
    elif role == 'licensing': licensing_portal()
    elif role == 'engineer': engineer_portal()
    elif role == 'extracts_engineer': extracts_engineer_portal() 
    elif role == 'planning_engineer': planning_engineer_portal()
    elif role == 'sales': sales_portal()
    elif role == 'legal': legal_portal()
    elif role == 'hr': hr_portal()
    else: employee_portal()
