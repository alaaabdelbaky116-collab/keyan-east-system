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
# 2. الإعدادات الأساسية والأقسام
# ==========================================
try:
    from streamlit_js_eval import get_geolocation
    GEO_AVAILABLE = True
except ImportError:
    GEO_AVAILABLE = False

st.set_page_config(page_title="Keyan-East HR Portal", page_icon="🏢", layout="wide")

OFFICIAL_IN = '11:00'
OFFICIAL_OUT = '18:00'
GRACE_PERIOD_MINS = 60
REQUIRED_HOURS = 7
DEFAULT_ANNUAL_BALANCE = 21
LOGO_FILE = "image_c5a585.png"

# قائمة الأقسام المعتمدة في الشركة
COMPANY_DEPARTMENTS = [
    "اتش ار (HR)", 
    "خدمة عملاء", 
    "تراخيص", 
    "حسابات", 
    "عقود قانونية", 
    "مهندسين مكتب فني", 
    "مهندسين إدارة وتخطيط", 
    "مهندسين تنفيذ",
    "إدارة عليا",
    "أخرى"
]

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
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

# ==========================================
# 3. حماية وتجهيز جداول PostgreSQL
# ==========================================
def init_db():
    try:
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        cur.execute('''CREATE TABLE IF NOT EXISTS Users (username TEXT PRIMARY KEY, password TEXT, role TEXT, emp_id TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Employees (emp_id TEXT PRIMARY KEY, name TEXT, department TEXT, annual_balance INTEGER)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Permissions (emp_id TEXT, date TEXT, type TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Requests (id SERIAL PRIMARY KEY, emp_id TEXT, date TEXT, req_type TEXT, notes TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS MonthlyStats (emp_id TEXT, month TEXT, delay_mins REAL, absent_dates TEXT, overtime_hours REAL DEFAULT 0, PRIMARY KEY(emp_id, month))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS Locations (id SERIAL PRIMARY KEY, name TEXT, lat REAL, lon REAL, radius REAL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS WebAttendance (id SERIAL PRIMARY KEY, emp_id TEXT, date TEXT, time TEXT, action TEXT, distance REAL, location_name TEXT, photo TEXT, project_name TEXT, daily_report TEXT)''')
        
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectFinancials (id SERIAL PRIMARY KEY, project_name TEXT, installment_type TEXT, amount REAL, due_date TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectLicenses (id SERIAL PRIMARY KEY, project_name TEXT, license_name TEXT, due_date TEXT, status TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS ProjectDrawings (id SERIAL PRIMARY KEY, project_name TEXT, drawing_name TEXT, due_date TEXT, status TEXT)''')
            
        cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('admin', 'admin123', 'admin', '0') ON CONFLICT (username) DO UPDATE SET role='admin'")
        cur.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('owner', 'owner123', 'owner', 'owner') ON CONFLICT (username) DO UPDATE SET role='owner'")
            
        cur.close()
        conn.close()
    except Exception as e:
        st.error(f"خطأ في تهيئة قاعدة البيانات: {e}")

if 'db_setup_done' not in st.session_state:
    init_db()
    st.session_state['db_setup_done'] = True

def authenticate(username, password):
    return db_fetchone("SELECT role, emp_id FROM Users WHERE username=%s AND password=%s", (username, password))

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
                    start_col = c - 6
                    if start_col < 0: start_col = 0 
                    
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
                            has_in = t_in_str != 'nan' and t_in_str != '--:--'
                            has_out = t_out_str != 'nan' and t_out_str != '--:--'
                        except: continue
                        
                        try: formatted_date = f"{year_month}/{int(float(day_num)):02d}"
                        except: formatted_date = f"{year_month}/--"
                        
                        if not has_in and not has_out:
                            if day_name != 'Thur.' and formatted_date not in emp_perms: 
                                absent_dates.append(formatted_date)
                        elif has_in and has_out:
                            try:
                                t_in_dt, t_out_dt = datetime.strptime(t_in_str, time_in_fmt), datetime.strptime(t_out_str, time_in_fmt)
                                worked_mins = (t_out_dt - t_in_dt).total_seconds() / 60
                                if worked_mins > 0:
                                    total_worked_mins += worked_mins
                                    regular_days += 1
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

                    extracted_data.append({
                        'الكود': emp_id, 'الاسم': name, 'القسم': department,
                        'الحضور': regular_days, 'ساعات العمل': format_hhmm(total_worked_mins),
                        'إضافي': format_hhmm(total_overtime_mins), 'عجز وتأخير': format_hhmm(total_shortage_mins),
                        'غياب صريح': len(absent_dates)
                    })
    cur.close()
    conn.close()
    return pd.DataFrame(extracted_data)

# ==========================================
# 5. واجهة تسجيل الدخول
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.update({'logged_in': False, 'role': None, 'emp_id': None, 'username': None})

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            if os.path.exists(LOGO_FILE):
                img_c1, img_c2, img_c3 = st.columns([1, 2.5, 1])
                with img_c2: st.image(LOGO_FILE, use_container_width=True)
        except: pass
        
        st.markdown("<h2 style='text-align: center; color: #172B4D;'>بوابة Keyan-East</h2>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        with st.form("login_form"):
            user = st.text_input("اسم المستخدم")
            pwd = st.text_input("كلمة المرور", type="password")
            if st.form_submit_button("تسجيل الدخول", use_container_width=True):
                user_data = authenticate(user, pwd)
                if user_data:
                    st.session_state.update({'logged_in': True, 'role': user_data[0], 'emp_id': user_data[1], 'username': user})
                    st.rerun()
                else: st.error("بيانات الدخول غير صحيحة!")

# ==========================================
# دالة موحدة لإنشاء وعرض شيت تقارير البصمة
# ==========================================
def render_attendance_report(department_filter=None, exclude_emp_id=None):
    conn = get_db_connection()
    
    if department_filter:
        emps = db_fetchall("SELECT name FROM Employees WHERE department=%s", (department_filter,))
    else:
        emps = db_fetchall("SELECT name FROM Employees")
    emp_list = ["الكل"] + [e[0] for e in emps]
    
    months = db_fetchall("SELECT DISTINCT substring(date from 1 for 7) FROM WebAttendance")
    month_list = ["الكل"] + [m[0] for m in months if m[0]]
    
    st.write("📌 **أدوات الفلترة والبحث السريع:**")
    c1, c2, c3 = st.columns(3)
    selected_emp = c1.selectbox("👤 اختيار الموظف:", emp_list)
    filter_type = c2.radio("📅 فترة التقرير:", ["اليوم فقط", "شهر محدد", "كل السجلات"], horizontal=True)
    
    selected_month = "الكل"
    if filter_type == "شهر محدد":
        selected_month = c3.selectbox("اختر الشهر:", month_list)
        
    query = """
        SELECT 
            w.date AS date_val,
            e.name AS emp_name,
            e.department AS dept,
            MIN(CASE WHEN w.action = 'حضور' THEN w.time END) AS check_in,
            MAX(CASE WHEN w.action = 'انصراف' THEN w.time END) AS check_out,
            MAX(w.location_name) AS loc,
            STRING_AGG(w.project_name, ' + ') AS proj,
            STRING_AGG(w.project_name || ': ' || w.daily_report, ' | ') AS rep,
            MAX(CASE WHEN w.action = 'حضور' THEN w.photo END) AS photo
        FROM WebAttendance w 
        JOIN Employees e ON w.emp_id = e.emp_id 
        WHERE 1=1
    """
    params = []
    
    if department_filter:
        query += " AND e.department = %s"
        params.append(department_filter)
        
    if selected_emp != "الكل":
        query += " AND e.name = %s"
        params.append(selected_emp)
        
    if filter_type == "اليوم فقط":
        query += " AND w.date = %s"
        params.append(get_egypt_time().strftime("%Y/%m/%d"))
    elif filter_type == "شهر محدد" and selected_month != "الكل":
        query += " AND w.date LIKE %s"
        params.append(selected_month + "%")
        
    query += " GROUP BY w.date, e.name, e.department ORDER BY w.date DESC"
    
    rep_df = pd.read_sql_query(query, conn, params=tuple(params))
    conn.close()
    
    if not rep_df.empty:
        rep_df['date_val'] = pd.to_datetime(rep_df['date_val'])
        arabic_days = {'Monday': 'الإثنين', 'Tuesday': 'الثلاثاء', 'Wednesday': 'الأربعاء', 'Thursday': 'الخميس', 'Friday': 'الجمعة', 'Saturday': 'السبت', 'Sunday': 'الأحد'}
        rep_df['اسم اليوم'] = rep_df['date_val'].dt.day_name().map(arabic_days)
        rep_df['التاريخ'] = rep_df['date_val'].dt.strftime('%Y/%m/%d')
        
        final_df = rep_df[['التاريخ', 'اسم اليوم', 'emp_name', 'dept', 'check_in', 'check_out', 'loc', 'proj', 'rep', 'photo']]
        final_df.columns = ['التاريخ', 'اليوم', 'اسم الموظف', 'القسم', 'الحضور', 'الانصراف', 'موقع البصمة', 'المشاريع', 'التقارير اليومية', 'صورة الإثبات']
        
        st.success(f"✅ تم العثور على {len(final_df)} سجل دوام.")
        st.dataframe(final_df, use_container_width=True, hide_index=True, column_config={"صورة الإثبات": st.column_config.ImageColumn("صورة الإثبات")})
        
        csv_df = final_df.drop(columns=['صورة الإثبات'])
        csv = csv_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 تحميل شيت التقرير (Excel/CSV) لحساب الرواتب", 
            data=csv, 
            file_name=f"Attendance_Sheet_{get_egypt_time().strftime('%Y%m%d')}.csv", 
            mime='text/csv',
            type="primary",
            use_container_width=True
        )
    else:
        st.info("لا توجد سجلات حضور وانصراف تطابق خيارات البحث.")

# ==========================================
# 6. بوابة الإدارة (Admin)
# ==========================================
def admin_portal():
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE)
        except: pass
        st.success(f"مرحباً بك: {st.session_state['username']} (مدير النظام)")
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()

    nav = st.radio("القائمة الرئيسية:", ["📊 تحليل البصمة", "✅ الطلبات العامة", "➕ إنشاء حساب", "⚙ إدارة الحسابات", "📍 إدارة المواقع", "📌 تقارير المناديب (شيت البصمة)"], horizontal=True)
    st.divider()
    
    if nav == "📊 تحليل البصمة":
        st.header("تحليل ملف الحضور والانصراف")
        uploaded_file = st.file_uploader("ارفع شيت البصمة (Excel)", type=['xls', 'xlsx'])
        if uploaded_file and st.button("بدء التحليل", type="primary"):
            with st.spinner("جاري المطابقة..."):
                try:
                    df = process_excel(uploaded_file)
                    if df is not None and not df.empty:
                        st.success("تم التحليل بنجاح!")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error("❌ حدث خطأ غير متوقع")
                    st.code(traceback.format_exc(), language="python")

    elif nav == "✅ الطلبات العامة":
        st.header("جميع طلبات الموظفين بالشركة")
        conn = get_db_connection()
        all_reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, e.department, r.date, r.req_type, r.notes, r.status FROM Requests r LEFT JOIN Employees e ON r.emp_id = e.emp_id ORDER BY r.id DESC LIMIT 50", conn)
        conn.close()
        if not all_reqs.empty: 
            all_reqs.columns = ['رقم', 'كود الموظف', 'الاسم', 'القسم', 'التاريخ', 'نوع الطلب', 'السبب', 'الحالة']
            st.dataframe(all_reqs, use_container_width=True, hide_index=True)
        else: st.info("لا توجد طلبات مسجلة حالياً.")

    elif nav == "➕ إنشاء حساب":
        st.header("إضافة حساب وتحديد القسم")
        st.info("💡 ملاحظة: إذا اخترت صلاحية 'رئيس قسم / مدير' لموظف، سيتمكن هذا الموظف تلقائياً من رؤية واعتماد طلبات الموظفين التابعين لنفس قسمه.")
        
        with st.form("new_user"):
            c1, c2 = st.columns(2)
            new_name = c1.text_input("اسم الموظف الرباعي")
            new_emp_id = c2.text_input("كود الموظف (ID)")
            
            # قائمة الأقسام المحددة
            new_dept = c1.selectbox("القسم / الإدارة التابع لها", COMPANY_DEPARTMENTS)
            
            role_choice = c2.selectbox("صلاحيات الحساب", [
                "موظف عادي (Employee)", 
                "رئيس قسم / مدير (Manager)", 
                "مدير إداري (Admin Manager)", 
                "مهندس (Engineer)", 
                "محاسب (Accountant)", 
                "مسؤول تراخيص (Licensing)", 
                "مسؤول نظام (Admin)", 
                "مالك (Owner)"
            ])
            
            new_user = c1.text_input("اسم المستخدم للدخول")
            new_pwd = c2.text_input("كلمة المرور")
            
            role_map = {
                "موظف عادي (Employee)": "employee", 
                "رئيس قسم / مدير (Manager)": "manager", 
                "مدير إداري (Admin Manager)": "admin_manager", 
                "مهندس (Engineer)": "engineer", 
                "محاسب (Accountant)": "accountant", 
                "مسؤول تراخيص (Licensing)": "licensing", 
                "مسؤول نظام (Admin)": "admin", 
                "مالك (Owner)": "owner"
            }
            
            if st.form_submit_button("إنشاء الحساب", type="primary"):
                if new_user and new_pwd and new_emp_id and new_name:
                    try:
                        # 1. إدخال أو تحديث بيانات الموظف (الاسم والقسم)
                        db_execute("INSERT INTO Employees (emp_id, name, department, annual_balance) VALUES (%s, %s, %s, %s) ON CONFLICT (emp_id) DO UPDATE SET name=EXCLUDED.name, department=EXCLUDED.department", (new_emp_id, new_name, new_dept, DEFAULT_ANNUAL_BALANCE))
                        
                        # 2. إنشاء الحساب وربطه بالموظف
                        db_execute("INSERT INTO Users (username, password, role, emp_id) VALUES (%s, %s, %s, %s)", (new_user, new_pwd, role_map[role_choice], new_emp_id))
                        
                        st.success(f"✅ تم إنشاء حساب ({new_name}) بنجاح! وتم تعيينه في قسم: {new_dept}.")
                    except Exception as e:
                        st.error("اسم المستخدم أو كود الموظف مسجل مسبقاً! الرجاء تغييره.")
                else:
                    st.error("يرجى تعبئة جميع الحقول المطلوبة أولاً!")

    elif nav == "⚙ إدارة الحسابات":
        st.header("إدارة حسابات المستخدمين")
        conn = get_db_connection()
        # جلب البيانات الشاملة للمستخدمين
        users_df = pd.read_sql_query("SELECT u.username, u.password, u.emp_id, e.name, e.department, u.role FROM Users u LEFT JOIN Employees e ON u.emp_id = e.emp_id", conn)
        conn.close()
        
        display_df = users_df.copy()
        display_df.columns = ['اسم المستخدم', 'كلمة المرور', 'كود الموظف', 'اسم الموظف', 'القسم', 'الصلاحية الحالية']
        display_map = {"employee": "موظف عادي", "manager": "رئيس قسم", "admin_manager": "مدير إداري", "engineer": "مهندس", "accountant": "محاسب", "licensing": "مسؤول تراخيص", "admin": "مسؤول نظام", "owner": "المالك"}
        display_df['الصلاحية الحالية'] = display_df['الصلاحية الحالية'].map(display_map)
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        st.divider()
        st.subheader("تعديل بيانات حساب موجود")
        with st.form("edit_user_form"):
            c1, c2 = st.columns(2)
            selected_user = c1.selectbox("اختر الحساب المطلوب تعديله", users_df['username'].tolist())
            
            # استخراج بيانات الحساب المحدد لعرضها كقيم افتراضية
            curr_data = users_df[users_df['username'] == selected_user].iloc[0]
            curr_emp_id = curr_data['emp_id']
            curr_name = curr_data['name'] if pd.notna(curr_data['name']) else ""
            curr_dept = curr_data['department'] if pd.notna(curr_data['department']) and curr_data['department'] in COMPANY_DEPARTMENTS else COMPANY_DEPARTMENTS[0]
            
            new_name = c2.text_input("تعديل اسم الموظف", value=curr_name)
            new_dept = c1.selectbox("تعديل القسم", COMPANY_DEPARTMENTS, index=COMPANY_DEPARTMENTS.index(curr_dept) if curr_dept in COMPANY_DEPARTMENTS else 0)
            
            new_username = c2.text_input("اسم المستخدم الجديد (اتركه لتجاهل التعديل)")
            new_pwd = c1.text_input("كلمة المرور الجديدة (اتركها لتجاهل التعديل)")
            
            new_role_choice = c2.selectbox("الصلاحية الجديدة", [
                "موظف عادي (Employee)", "رئيس قسم / مدير (Manager)", "مدير إداري (Admin Manager)", 
                "مهندس (Engineer)", "محاسب (Accountant)", "مسؤول تراخيص (Licensing)", 
                "مسؤول نظام (Admin)", "مالك (Owner)"
            ])
            
            if st.form_submit_button("تحديث البيانات", type="primary"):
                role_map = {"موظف عادي (Employee)": "employee", "رئيس قسم / مدير (Manager)": "manager", "مدير إداري (Admin Manager)": "admin_manager", "مهندس (Engineer)": "engineer", "محاسب (Accountant)": "accountant", "مسؤول تراخيص (Licensing)": "licensing", "مسؤول نظام (Admin)": "admin", "مالك (Owner)": "owner"}
                final_username = new_username.strip() if new_username.strip() else selected_user
                
                try:
                    # 1. تحديث جدول المستخدمين (Users)
                    updates = ["role=%s"]; params = [role_map[new_role_choice]]
                    if final_username != selected_user:
                        updates.append("username=%s"); params.append(final_username)
                    if new_pwd.strip():
                        updates.append("password=%s"); params.append(new_pwd.strip())
                    
                    params.append(selected_user)
                    db_execute(f"UPDATE Users SET {', '.join(updates)} WHERE username=%s", tuple(params))
                    
                    # 2. تحديث جدول الموظفين (Employees) بالاسم والقسم الجديد
                    if curr_emp_id and str(curr_emp_id) not in ['0', 'owner']:
                        final_name = new_name.strip() if new_name.strip() else curr_name
                        db_execute("UPDATE Employees SET name=%s, department=%s WHERE emp_id=%s", (final_name, new_dept, curr_emp_id))
                        
                    st.success("تم التحديث بنجاح!")
                    st.rerun()
                except Exception as e:
                    st.error(f"حدث خطأ: {e}")

    elif nav == "📍 إدارة المواقع":
        st.header("📍 إضافة فروع ومواقع الشركة (بواسطة الـ GPS)")
        if not GEO_AVAILABLE:
            st.error("مكتبة 'streamlit-js-eval' غير مثبتة.")
            admin_lat, admin_lon = 0.0, 0.0
        else:
            c1, c2 = st.columns([3, 1])
            with c1: st.info("النظام يقوم بقراءة موقعك الجغرافي الحالي. للذهاب لموقع جديد وتسجيله، اذهب للموقع واضغط زر التحديث.")
            with c2: 
                if st.button("🔄 تحديث موقعي الآن", use_container_width=True):
                    st.rerun()
                    
            loc_admin = get_geolocation()
            admin_lat, admin_lon = 0.0, 0.0
            if loc_admin and isinstance(loc_admin, dict) and 'coords' in loc_admin:
                admin_lat = float(loc_admin['coords']['latitude'])
                admin_lon = float(loc_admin['coords']['longitude'])
                st.success(f"📍 تم التقاط موقعك بنجاح! خط العرض: {admin_lat:.6f} | خط الطول: {admin_lon:.6f}")
        
        with st.form("add_location_form"):
            loc_name = st.text_input("اسم الفرع أو الموقع (مثال: موقع التجمع، مقر الشركة)")
            c1, c2, c3 = st.columns(3)
            new_lat = c1.number_input("خط العرض (Latitude)", value=admin_lat, format="%.6f")
            new_lon = c2.number_input("خط الطول (Longitude)", value=admin_lon, format="%.6f")
            new_rad = c3.number_input("النطاق المسموح (بالمتر)", value=100.0, min_value=10.0)
            
            if st.form_submit_button("حفظ الموقع", type="primary"):
                if loc_name.strip() != "":
                    db_execute("INSERT INTO Locations (name, lat, lon, radius) VALUES (%s, %s, %s, %s)", (loc_name, new_lat, new_lon, new_rad))
                    st.success("تم حفظ الموقع بنجاح!")
                    st.rerun()
                else: st.error("يرجى كتابة اسم الموقع!")
        
        st.divider()
        st.subheader("المواقع المسجلة حالياً")
        conn = get_db_connection()
        locations_df = pd.read_sql_query("SELECT id, name, lat, lon, radius FROM Locations", conn)
        conn.close()
        if not locations_df.empty:
            locations_df.columns = ['id', 'اسم الموقع', 'خط العرض', 'خط الطول', 'النطاق (متر)']
            st.dataframe(locations_df.drop(columns=['id']), use_container_width=True)
            with st.form("delete_loc"):
                loc_to_delete = st.selectbox("حذف موقع:", locations_df['اسم الموقع'].tolist())
                if st.form_submit_button("حذف الفرع 🗑️"):
                    db_execute("DELETE FROM Locations WHERE name=%s", (loc_to_delete,))
                    st.success("تم الحذف بنجاح!")
                    st.rerun()

    elif nav == "📌 تقارير المناديب (شيت البصمة)":
        st.header("شيت الحضور والانصراف المجمع")
        render_attendance_report()

# ==========================================
# 7. بوابة المدير الإداري (Admin Manager)
# ==========================================
def admin_manager_portal():
    emp_id = st.session_state['emp_id']
    emp_name, emp_dept, balance = get_employee_info(emp_id)
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE)
        except: pass
        st.success(f"مرحباً: {st.session_state['username']} (المدير الإداري)")
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()

    nav = st.radio("القائمة:", ["✅ طلبات جميع الموظفين", "📝 تقارير الحضور والإنجاز", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()

    if nav == "✅ طلبات جميع الموظفين":
        st.header("إدارة طلبات الموظفين (جميع الأقسام)")
        conn = get_db_connection()
        reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, e.department, r.date, r.req_type, r.notes FROM Requests r JOIN Employees e ON r.emp_id = e.emp_id WHERE r.status = 'قيد الانتظار' AND r.emp_id != %s", conn, params=(emp_id,))
        conn.close()
        
        if reqs.empty: st.success("لا توجد طلبات معلقة في الشركة حالياً.")
        else:
            for _, row in reqs.iterrows():
                with st.expander(f"طلب من: {row['name']} (القسم: {row['department']}) - نوع الطلب: {row['req_type']}"):
                    st.write(f"**تاريخ الطلب:** {row['date']}")
                    st.write(f"**الملاحظات/السبب:** {row['notes']}")
                    c1, c2 = st.columns(2)
                    if c1.button("موافقة واعتماد", key=f"app_{row['id']}", type="primary"):
                        db_execute("UPDATE Requests SET status='مقبول' WHERE id=%s", (row['id'],))
                        db_execute("INSERT INTO Permissions VALUES (%s, %s, %s)", (row['emp_id'], row['date'], row['req_type']))
                        st.success("تم الاعتماد!")
                        st.rerun()
                    if c2.button("رفض الطلب", key=f"rej_{row['id']}"):
                        db_execute("UPDATE Requests SET status='مرفوض' WHERE id=%s", (row['id'],))
                        st.warning("تم الرفض!")
                        st.rerun()
        
    elif nav == "📝 تقارير الحضور والإنجاز":
        st.header("شيت الحضور والتقارير الشامل")
        render_attendance_report()
        
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

# ==========================================
# 8. بوابة رئيس القسم (Manager)
# ==========================================
def manager_portal():
    emp_id = st.session_state['emp_id']
    emp_name, emp_dept, balance = get_employee_info(emp_id)
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE)
        except: pass
        st.info(f"مرحباً: {st.session_state['username']} (رئيس قسم: {emp_dept})")
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()

    nav = st.radio("القائمة:", ["✅ طلبات القسم", "📝 تقارير دوام القسم", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()

    if nav == "✅ طلبات القسم":
        st.header(f"طلبات الموظفين في قسم: {emp_dept}")
        conn = get_db_connection()
        reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, r.date, r.req_type, r.notes FROM Requests r JOIN Employees e ON r.emp_id = e.emp_id WHERE e.department = %s AND r.status = 'قيد الانتظار' AND r.emp_id != %s", conn, params=(emp_dept, emp_id))
        conn.close()
        if reqs.empty: st.success("لا توجد طلبات معلقة لفريقك حالياً.")
        else:
            for _, row in reqs.iterrows():
                with st.expander(f"طلب من: {row['name']} (كود: {row['emp_id']}) - {row['req_type']}"):
                    st.write(f"الملاحظات: {row['notes']}")
                    c1, c2 = st.columns(2)
                    if c1.button("موافقة", key=f"app_{row['id']}", type="primary"):
                        db_execute("UPDATE Requests SET status='مقبول' WHERE id=%s", (row['id'],))
                        db_execute("INSERT INTO Permissions VALUES (%s, %s, %s)", (row['emp_id'], row['date'], row['req_type']))
                        st.rerun()
                    if c2.button("رفض", key=f"rej_{row['id']}"):
                        db_execute("UPDATE Requests SET status='مرفوض' WHERE id=%s", (row['id'],))
                        st.rerun()
        
    elif nav == "📝 تقارير دوام القسم":
        st.header(f"شيت حضور وانصراف قسم: {emp_dept}")
        render_attendance_report(department_filter=emp_dept)
        
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

# ==========================================
# 9. بوابات المالك، الحسابات، التراخيص، والمهندس
# ==========================================
def owner_portal():
    with st.sidebar:
        st.success(f"مرحباً بك: {st.session_state['username']} (المالك)")
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False; st.rerun()

    st.title("👑 لوحة تحكم المالك")
    nav = st.radio("القائمة:", ["📊 تقارير المهام", "📈 الموقف المالي والهندسي والقانوني", "👥 ملخص الإنجازات"], horizontal=True)
    st.divider()

    conn = get_db_connection()
    if nav == "📊 تقارير المهام":
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع لعرض المهام:", project_list)
        reports = pd.read_sql_query("SELECT w.date, e.name, e.department, w.daily_report FROM WebAttendance w JOIN Employees e ON w.emp_id = e.emp_id WHERE w.project_name = %s AND w.action IN ('انصراف', 'تقرير') ORDER BY w.id DESC", conn, params=(selected_project,))
        if not reports.empty: 
            reports.columns = ['التاريخ', 'الموظف', 'القسم', 'ما تم إنجازه']
            st.dataframe(reports, use_container_width=True, hide_index=True)
        else: st.info("لا يوجد.")
            
    elif nav == "📈 الموقف المالي والهندسي والقانوني":
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع:", project_list)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("### 💰 الأقساط")
            fin_df = pd.read_sql_query("SELECT installment_type, amount, due_date, status FROM ProjectFinancials WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
            if not fin_df.empty:
                fin_df.columns = ['النوع', 'المبلغ', 'تاريخ الاستحقاق', 'الحالة']
                st.dataframe(fin_df, use_container_width=True, hide_index=True)
            else: st.info("لا يوجد")
        with c2:
            st.markdown("### 📜 التراخيص")
            lic_df = pd.read_sql_query("SELECT license_name, due_date, status FROM ProjectLicenses WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
            if not lic_df.empty:
                lic_df.columns = ['الترخيص', 'الانتهاء', 'الحالة']
                st.dataframe(lic_df, use_container_width=True, hide_index=True)
            else: st.info("لا يوجد")
        with c3:
            st.markdown("### 📐 الرسومات")
            draw_df = pd.read_sql_query("SELECT drawing_name, due_date, status FROM ProjectDrawings WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
            if not draw_df.empty:
                draw_df.columns = ['الرسم', 'التسليم', 'الحالة']
                st.dataframe(draw_df, use_container_width=True, hide_index=True)
            else: st.info("لا يوجد")
            
    elif nav == "👥 ملخص الإنجازات":
        summary = pd.read_sql_query("SELECT project_name, COUNT(*) FROM WebAttendance WHERE action IN ('انصراف', 'تقرير') AND project_name IS NOT NULL GROUP BY project_name ORDER BY COUNT(*) DESC", conn)
        if not summary.empty:
            summary.columns = ['اسم المشروع', 'إجمالي المهام']
            st.dataframe(summary, use_container_width=True, hide_index=True)
        else: st.info("لا يوجد")
    conn.close()

def accountant_portal():
    emp_id = st.session_state['emp_id']
    emp_name, emp_dept, balance = get_employee_info(emp_id)
    with st.sidebar:
        st.info(f"مرحباً: {st.session_state['username']}")
        if st.button("تسجيل الخروج", use_container_width=True): st.session_state['logged_in'] = False; st.rerun()
    nav = st.radio("القائمة:", ["💰 إدارة الأقساط", "👤 لوحتي الشخصية"], horizontal=True)
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
                st.success("تم!")
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, installment_type, amount, due_date, status FROM ProjectFinancials", conn)
        conn.close()
        if not df.empty:
            df.columns = ['المشروع', 'النوع', 'المبلغ', 'تاريخ', 'الحالة']
            st.dataframe(df, hide_index=True)
    else: render_employee_dashboard(emp_id, balance)

def licensing_portal():
    emp_id = st.session_state['emp_id']
    emp_name, emp_dept, balance = get_employee_info(emp_id)
    with st.sidebar:
        st.info(f"مرحباً: {st.session_state['username']}")
        if st.button("تسجيل الخروج", use_container_width=True): st.session_state['logged_in'] = False; st.rerun()
    nav = st.radio("القائمة:", ["📜 التراخيص", "👤 لوحتي الشخصية"], horizontal=True)
    if nav == "📜 التراخيص":
        with st.form("add_lic"):
            c1, c2 = st.columns(2)
            proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
            lic_name = c2.text_input("اسم الترخيص")
            due_date = c1.date_input("الانتهاء")
            status = c2.selectbox("الحالة", ["سارية", "تحت الإجراء", "منتهية"])
            if st.form_submit_button("تسجيل", type="primary") and lic_name:
                db_execute("INSERT INTO ProjectLicenses (project_name, license_name, due_date, status) VALUES (%s, %s, %s, %s)", (proj, lic_name, due_date.strftime("%Y/%m/%d"), status))
                st.success("تم!")
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, license_name, due_date, status FROM ProjectLicenses", conn)
        conn.close()
        if not df.empty:
            df.columns = ['المشروع', 'الترخيص', 'تاريخ الانتهاء', 'الحالة']
            st.dataframe(df, hide_index=True)
    else: render_employee_dashboard(emp_id, balance)

def engineer_portal():
    emp_id = st.session_state['emp_id']
    emp_name, emp_dept, balance = get_employee_info(emp_id)
    with st.sidebar:
        st.info(f"مرحباً: {st.session_state['username']}")
        if st.button("تسجيل الخروج", use_container_width=True): st.session_state['logged_in'] = False; st.rerun()
    nav = st.radio("القائمة:", ["📐 الرسومات", "👤 لوحتي الشخصية"], horizontal=True)
    if nav == "📐 الرسومات":
        with st.form("add_draw"):
            c1, c2 = st.columns(2)
            proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
            draw_name = c2.text_input("اسم الرسم")
            due_date = c1.date_input("التسليم")
            status = c2.selectbox("الحالة", ["قيد التنفيذ", "تحت المراجعة", "مكتملة"])
            if st.form_submit_button("تسجيل", type="primary") and draw_name:
                db_execute("INSERT INTO ProjectDrawings (project_name, drawing_name, due_date, status) VALUES (%s, %s, %s, %s)", (proj, draw_name, due_date.strftime("%Y/%m/%d"), status))
                st.success("تم!")
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, drawing_name, due_date, status FROM ProjectDrawings", conn)
        conn.close()
        if not df.empty:
            df.columns = ['المشروع', 'اسم الرسم', 'تاريخ التسليم', 'الحالة']
            st.dataframe(df, hide_index=True)
    else: render_employee_dashboard(emp_id, balance)

def employee_portal():
    emp_id = st.session_state['emp_id']
    _, _, balance = get_employee_info(emp_id)
    with st.sidebar:
        if st.button("تسجيل الخروج", use_container_width=True): st.session_state['logged_in'] = False; st.rerun()
    render_employee_dashboard(emp_id, balance)

# ==========================================
# 10. الشاشة المشتركة للجميع (البصمة وتقارير الإنجاز الذكية)
# ==========================================
def render_employee_dashboard(emp_id, balance):
    month, delay_mins, absent_str, overtime_mins = get_employee_stats(emp_id)
    absent_list = [d for d in absent_str.split(",") if d.strip()] if absent_str else []
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("الرصيد", f"{balance} يوم")
    c2.metric("تأخيرات", f"{format_hhmm(delay_mins)} ساعة")
    c3.metric("إضافي", f"{format_hhmm(overtime_mins)} ساعة")
    
    pending = db_fetchone("SELECT COUNT(*) FROM Requests WHERE emp_id=%s AND status='قيد الانتظار'", (emp_id,))[0]
    c4.metric("طلبات معلقة", pending)
    
    st.divider()
    sub_nav = st.radio("العمليات:", ["📍 بصمة وتقارير الإنجاز", "📝 طلب جديد", "🌴 سجلاتي"], horizontal=True)
    
    if sub_nav == "📍 بصمة وتقارير الإنجاز":
        locations = db_fetchall("SELECT name, lat, lon, radius FROM Locations")
        if not locations: st.error("لم يتم تسجيل فروع للشركة بعد.")
        elif not GEO_AVAILABLE: st.error("مكتبة Location غير مثبتة.")
        else:
            loc = get_geolocation()
            if loc and isinstance(loc, dict) and 'coords' in loc:
                emp_lat, emp_lon = float(loc['coords']['latitude']), float(loc['coords']['longitude'])
                closest_loc_name, min_distance, is_allowed = None, float('inf'), False
                for l_name, l_lat, l_lon, l_rad in locations:
                    dist = haversine(l_lat, l_lon, emp_lat, emp_lon)
                    if dist < min_distance: min_distance, closest_loc_name, is_allowed = dist, l_name, (dist <= l_rad)
                
                if is_allowed:
                    st.success(f"✅ أنت داخل نطاق: {closest_loc_name}")
                    camera_photo = st.camera_input("التقط صورة لإثبات الحضور أو الانصراف")
                    
                    if camera_photo:
                        img = Image.open(camera_photo); img.thumbnail((300, 300)); buffered = io.BytesIO()
                        img.save(buffered, format="JPEG", quality=85)
                        photo_uri = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}"
                        
                        today_date = get_egypt_time().strftime("%Y/%m/%d")
                        now_time = get_egypt_time().strftime("%H:%M")
                        
                        has_checked_in = db_fetchone(
                            "SELECT COUNT(*) FROM WebAttendance WHERE emp_id=%s AND date=%s AND action='حضور'", 
                            (emp_id, today_date)
                        )[0] > 0
                        
                        if not has_checked_in:
                            if st.button("🟢 تسجيل حضور", use_container_width=True):
                                db_execute(
                                    "INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo) VALUES (%s, %s, %s, 'حضور', %s, %s, %s)", 
                                    (emp_id, today_date, now_time, int(min_distance), closest_loc_name, photo_uri)
                                )
                                st.success("تم تسجيل الحضور بنجاح!")
                                st.rerun() 
                        else:
                            st.info("✅ تم تسجيل حضورك اليوم. يمكنك الآن رفع تقارير المشاريع أو تسجيل الانصراف.")
                            st.markdown("---")
                            st.markdown("### 📝 إضافة تقارير المشاريع (أثناء اليوم أو عند الانصراف)")
                            
                            selected_proj = st.selectbox("المشروع (الاتحاد)", [f"اتحاد {i}" for i in range(1, 46)])
                            daily_rep = st.text_area("تفاصيل الإنجاز", placeholder="ماذا أنجزت في هذا المشروع؟")
                            
                            c_btn1, c_btn2 = st.columns(2)
                            with c_btn1:
                                if st.button("➕ رفع التقرير فقط (مستمر بالعمل)", use_container_width=True):
                                    if daily_rep.strip():
                                        db_execute(
                                            "INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'تقرير', %s, %s, %s, %s, %s)", 
                                            (emp_id, today_date, now_time, int(min_distance), closest_loc_name, photo_uri, selected_proj, daily_rep)
                                        )
                                        st.success("تم حفظ إنجازك في هذا المشروع! يمكنك تغيير المشروع وإضافة تقرير آخر.")
                                    else: st.error("اكتب التفاصيل أولاً!")
                                    
                            with c_btn2:
                                if st.button("🔴 رفع التقرير + تسجيل انصراف", use_container_width=True):
                                    if daily_rep.strip():
                                        db_execute(
                                            "INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'انصراف', %s, %s, %s, %s, %s)", 
                                            (emp_id, today_date, now_time, int(min_distance), closest_loc_name, photo_uri, selected_proj, daily_rep)
                                        )
                                        st.success("تم تسجيل الانصراف وحفظ التقرير بنجاح!")
                                        st.rerun() 
                                    else: st.error("اكتب التفاصيل أولاً!")
                else: st.error(f"❌ أنت خارج النطاق. أقرب فرع ({closest_loc_name}) يبعد {int(min_distance)} متر.")
            else: st.info("جاري جلب الموقع... يرجى السماح للمتصفح.")

    elif sub_nav == "📝 طلب جديد":
        with st.form("emp_req"):
            req_type = st.selectbox("النوع", ["إجازة", "مأمورية", "إذن"])
            req_date = st.date_input("التاريخ")
            notes = st.text_input("السبب")
            if st.form_submit_button("إرسال"):
                db_execute("INSERT INTO Requests (emp_id, date, req_type, notes, status) VALUES (%s, %s, %s, %s, 'قيد الانتظار')", (emp_id, req_date.strftime("%Y/%m/%d"), req_type, notes))
                st.success("تم!")
    elif sub_nav == "🌴 سجلاتي":
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT date, req_type, status FROM Requests WHERE emp_id=%s ORDER BY id DESC", conn, params=(emp_id,))
        conn.close()
        if not df.empty:
            df.columns = ['التاريخ', 'نوع الطلب', 'الحالة']
            st.dataframe(df, hide_index=True)
        else: st.info("لا توجد طلبات.")

# ==========================================
# 11. نظام التوجيه (Routing) لجميع الصلاحيات
# ==========================================
if not st.session_state['logged_in']: login_page()
else:
    role = st.session_state['role']
    if role == 'admin': admin_portal()
    elif role == 'admin_manager': admin_manager_portal()
    elif role == 'manager': manager_portal()
    elif role == 'owner': owner_portal()
    elif role == 'accountant': accountant_portal()
    elif role == 'licensing': licensing_portal()
    elif role == 'engineer': engineer_portal()
    else: employee_portal()
