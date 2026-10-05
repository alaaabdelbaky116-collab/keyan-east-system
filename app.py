import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3
import traceback
import base64
from PIL import Image
import io
import os

# ==========================================
# 1. الإعدادات الأساسية
# ==========================================
st.set_page_config(page_title="Keyan-East HR Portal", page_icon="🏢", layout="wide")

OFFICIAL_IN = '11:00'
OFFICIAL_OUT = '18:00'
GRACE_PERIOD_MINS = 60
REQUIRED_HOURS = 7
DEFAULT_ANNUAL_BALANCE = 21
LOGO_FILE = "logo.png"

def format_hhmm(total_minutes):
    if not total_minutes or pd.isna(total_minutes) or total_minutes <= 0:
        return "00:00"
    hours = int(total_minutes // 60)
    mins = int(total_minutes % 60)
    return f"{hours}:{mins:02d}"

# ==========================================
# 2. حماية وتجهيز قاعدة البيانات (تعمل مرة واحدة فقط)
# ==========================================
def init_db():
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS Users (username TEXT PRIMARY KEY, password TEXT, role TEXT, emp_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS Employees (emp_id TEXT PRIMARY KEY, name TEXT, department TEXT, annual_balance INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS Permissions (emp_id TEXT, date TEXT, type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS Requests (id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id TEXT, date TEXT, req_type TEXT, notes TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS MonthlyStats (emp_id TEXT, month TEXT, delay_mins REAL, absent_dates TEXT, overtime_hours REAL DEFAULT 0, PRIMARY KEY(emp_id, month))''')
    c.execute('''CREATE TABLE IF NOT EXISTS WebAttendance (id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id TEXT, date TEXT, time TEXT, action TEXT, location_name TEXT, photo TEXT, project_name TEXT, daily_report TEXT)''')
        
    c.execute("SELECT COUNT(*) FROM Users WHERE role='admin'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('admin', 'admin123', 'admin', '0')")
        
    c.execute("SELECT COUNT(*) FROM Users WHERE role='owner'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO Users (username, password, role, emp_id) VALUES ('owner', 'owner123', 'owner', 'owner')")
        
    conn.commit(); conn.close()

# 💡 هذه هي الثغرة التي تم سدها لمنع تعليق الموقع
if 'db_setup_done' not in st.session_state:
    init_db()
    st.session_state['db_setup_done'] = True

def authenticate(username, password):
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT role, emp_id FROM Users WHERE username=? AND password=?", (username, password))
    user = c.fetchone()
    conn.close()
    return user

def get_employee_info(emp_id):
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT name, department, annual_balance FROM Employees WHERE emp_id=?", (emp_id,))
    res = c.fetchone()
    conn.close()
    return res if res else ("غير مسجل", "غير محدد", DEFAULT_ANNUAL_BALANCE)

def get_employee_stats(emp_id):
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT month, delay_mins, absent_dates, overtime_hours FROM MonthlyStats WHERE emp_id=? ORDER BY month DESC LIMIT 1", (emp_id,))
    res = c.fetchone()
    conn.close()
    return res if res else (None, 0.0, "", 0.0)

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
    conn = sqlite3.connect('hr_system.db')
    
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
                    
                    conn.execute("INSERT OR IGNORE INTO Employees (emp_id, name, department, annual_balance) VALUES (?, ?, ?, ?)", (emp_id, name, department, DEFAULT_ANNUAL_BALANCE))
                    conn.execute("INSERT OR IGNORE INTO Users (username, password, role, emp_id) VALUES (?, ?, 'employee', ?)", (emp_id, emp_id, emp_id))
                    conn.commit()
                    
                    try: year_month = str(df.iloc[r + 1, start_col + 1]).strip().split('-')[0][:7] 
                    except: year_month = "2026/10" 
                    
                    daily_data = df.iloc[r + 9: r + 40, start_col:start_col+5] 
                    total_worked_mins, regular_days, total_shortage_mins, total_overtime_mins, absent_dates = 0, 0, 0, 0, []
                    
                    cur = conn.cursor()
                    cur.execute("SELECT date FROM Permissions WHERE emp_id=?", (emp_id,))
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
                    conn.execute("INSERT OR REPLACE INTO MonthlyStats (emp_id, month, delay_mins, absent_dates, overtime_hours) VALUES (?, ?, ?, ?, ?)", 
                                 (emp_id, year_month, total_shortage_mins, absent_str, total_overtime_mins))
                    conn.commit()

                    extracted_data.append({
                        'الكود': emp_id, 'الاسم': name, 'القسم': department,
                        'الحضور': regular_days, 'ساعات العمل': format_hhmm(total_worked_mins),
                        'إضافي': format_hhmm(total_overtime_mins), 'عجز وتأخير': format_hhmm(total_shortage_mins),
                        'غياب صريح': len(absent_dates)
                    })
    conn.close()
    return pd.DataFrame(extracted_data)

# ==========================================
# 4. واجهة تسجيل الدخول
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.update({'logged_in': False, 'role': None, 'emp_id': None, 'username': None})

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            if os.path.exists(LOGO_FILE):
                img_c1, img_c2, img_c3 = st.columns([1, 1, 1])
                with img_c2: st.image(LOGO_FILE, width=120)
        except: pass
        
        st.markdown("<h2 style='text-align: center; color: #172B4D;'>بوابة Keyan-East</h2>", unsafe_allow_html=True)
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
# 5. بوابة الإدارة (Admin)
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

    nav = st.radio("القائمة الرئيسية:", ["📊 تحليل البصمة", "✅ الطلبات العامة", "➕ إنشاء حساب", "⚙ إدارة الحسابات", "📍 سجل الحضور والتقارير"], horizontal=True)
    st.divider()
    
    if nav == "📊 تحليل البصمة":
        st.header("تحليل ملف الحضور والانصراف")
        uploaded_file = st.file_uploader("ارفع شيت البصمة (Excel)", type=['xls', 'xlsx'])
        if uploaded_file and st.button("بدء التحليل", type="primary"):
            with st.spinner("جاري المطابقة وإنشاء الحسابات..."):
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
        conn = sqlite3.connect('hr_system.db')
        all_reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, e.department, r.date, r.req_type, r.notes, r.status FROM Requests r LEFT JOIN Employees e ON r.emp_id = e.emp_id ORDER BY r.id DESC LIMIT 50", conn)
        if not all_reqs.empty: st.dataframe(all_reqs, use_container_width=True, hide_index=True)
        else: st.info("لا توجد طلبات مسجلة حالياً.")
        conn.close()

    elif nav == "➕ إنشاء حساب":
        st.header("إضافة حساب يدوياً")
        with st.form("new_user"):
            c1, c2 = st.columns(2)
            new_emp_id = c1.text_input("كود الموظف")
            new_user = c2.text_input("اسم المستخدم للدخول")
            new_pwd = c1.text_input("كلمة المرور")
            role_choice = c2.selectbox("صلاحيات الحساب", ["موظف عادي (Employee)", "مدير قسم (Manager)", "مسؤول نظام (Admin)", "مالك (Owner)"])
            role_map = {"موظف عادي (Employee)": "employee", "مدير قسم (Manager)": "manager", "مسؤول نظام (Admin)": "admin", "مالك (Owner)": "owner"}
            if st.form_submit_button("إنشاء الحساب", type="primary"):
                conn = sqlite3.connect('hr_system.db')
                try:
                    conn.execute("INSERT INTO Users VALUES (?, ?, ?, ?)", (new_user, new_pwd, role_map[role_choice], new_emp_id))
                    conn.commit()
                    st.success("تم الإضافة بنجاح!")
                except: st.error("اسم المستخدم موجود مسبقاً!")
                conn.close()

    elif nav == "⚙ إدارة الحسابات":
        st.header("إدارة حسابات المستخدمين")
        conn = sqlite3.connect('hr_system.db')
        users_df = pd.read_sql_query("SELECT username AS 'اسم المستخدم', password AS 'كلمة المرور', emp_id AS 'كود الموظف', role AS 'الصلاحية الحالية' FROM Users", conn)
        display_map = {"employee": "موظف عادي", "manager": "مدير قسم", "admin": "مسؤول نظام", "owner": "المالك"}
        users_df['الصلاحية الحالية'] = users_df['الصلاحية الحالية'].map(display_map)
        st.dataframe(users_df, use_container_width=True, hide_index=True)
        
        st.divider()
        with st.form("edit_user_form"):
            c1, c2 = st.columns(2)
            selected_user = c1.selectbox("اختر الحساب المطلوب تعديله", users_df['اسم المستخدم'].tolist())
            new_username = c2.text_input("اسم المستخدم الجديد (للاحتفاظ به اتركه فارغاً)")
            new_pwd = c1.text_input("كلمة المرور الجديدة (للاحتفاظ بها اتركها فارغة)")
            new_role_choice = c2.selectbox("الصلاحية الجديدة", ["موظف عادي (Employee)", "مدير قسم (Manager)", "مسؤول نظام (Admin)", "مالك (Owner)"])
            if st.form_submit_button("تحديث البيانات", type="primary"):
                role_map = {"موظف عادي (Employee)": "employee", "مدير قسم (Manager)": "manager", "مسؤول نظام (Admin)": "admin", "مالك (Owner)": "owner"}
                final_username = new_username.strip() if new_username.strip() else selected_user
                updates, params = ["role=?"], [role_map[new_role_choice]]
                if final_username != selected_user:
                    updates.append("username=?")
                    params.append(final_username)
                if new_pwd.strip():
                    updates.append("password=?")
                    params.append(new_pwd.strip())
                params.append(selected_user)
                conn.execute(f"UPDATE Users SET {', '.join(updates)} WHERE username=?", params)
                conn.commit()
                st.success("تم التحديث!")
        conn.close()

    elif nav == "📍 سجل الحضور والتقارير":
        st.header("سجل حضور المناديب والتقارير")
        conn = sqlite3.connect('hr_system.db')
        today_str = datetime.now().strftime("%Y/%m/%d")
        try:
            web_logs = pd.read_sql_query("SELECT e.name AS 'الاسم', w.time AS 'الوقت', w.action AS 'النوع', w.project_name AS 'المشروع', w.photo AS 'صورة الموظف' FROM WebAttendance w JOIN Employees e ON w.emp_id = e.emp_id WHERE w.date=? ORDER BY w.id DESC", conn, params=(today_str,))
            if not web_logs.empty:
                st.dataframe(web_logs, use_container_width=True, hide_index=True, column_config={"صورة الموظف": st.column_config.ImageColumn("صورة الإثبات")})
            else: st.info("لا توجد سجلات حضور لليوم.")
        except Exception as e:
            st.info("لا توجد سجلات حضور بالصور حتى الآن.")
        conn.close()

# ==========================================
# 6. بوابة مدير القسم (Manager)
# ==========================================
def manager_portal():
    emp_id = st.session_state['emp_id']
    emp_name, emp_dept, balance = get_employee_info(emp_id)
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE)
        except: pass
        st.info(f"مرحباً: {st.session_state['username']}")
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()

    nav = st.radio("القائمة:", ["✅ طلبات القسم", "📝 تقارير العمل اليومية", "👤 لوحتي الشخصية"], horizontal=True)
    st.divider()

    if nav == "✅ طلبات القسم":
        st.header(f"طلبات الموظفين في قسم: {emp_dept}")
        conn = sqlite3.connect('hr_system.db')
        reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, r.date, r.req_type, r.notes FROM Requests r JOIN Employees e ON r.emp_id = e.emp_id WHERE e.department = ? AND r.status = 'قيد الانتظار' AND r.emp_id != ?", conn, params=(emp_dept, emp_id))
        if reqs.empty: st.success("لا توجد طلبات معلقة لفريقك حالياً.")
        else:
            for _, row in reqs.iterrows():
                with st.expander(f"طلب من: {row['name']} (كود: {row['emp_id']}) - {row['req_type']}"):
                    st.write(f"الملاحظات: {row['notes']}")
                    c1, c2 = st.columns(2)
                    if c1.button("موافقة", key=f"app_{row['id']}", type="primary"):
                        conn.execute("UPDATE Requests SET status='مقبول' WHERE id=?", (row['id'],))
                        conn.execute("INSERT INTO Permissions VALUES (?, ?, ?)", (row['emp_id'], row['date'], row['req_type']))
                        conn.commit(); st.rerun()
                    if c2.button("رفض", key=f"rej_{row['id']}"):
                        conn.execute("UPDATE Requests SET status='مرفوض' WHERE id=?", (row['id'],))
                        conn.commit(); st.rerun()
        conn.close()
        
    elif nav == "📝 تقارير العمل اليومية":
        st.header(f"تقارير الإنجاز اليومية لموظفي قسم: {emp_dept}")
        conn = sqlite3.connect('hr_system.db')
        rep_df = pd.read_sql_query("""
            SELECT w.date AS 'التاريخ', e.name AS 'الموظف', w.project_name AS 'المشروع', w.daily_report AS 'ما تم إنجازه' 
            FROM WebAttendance w 
            JOIN Employees e ON w.emp_id = e.emp_id 
            WHERE e.department = ? AND w.action = 'انصراف' AND w.daily_report IS NOT NULL
            ORDER BY w.id DESC
        """, conn, params=(emp_dept,))
        
        if not rep_df.empty:
            st.dataframe(rep_df, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد تقارير إنجاز مسجلة لفريقك حتى الآن.")
        conn.close()
        
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

# ==========================================
# 7. بوابة الأونر / المالك
# ==========================================
def owner_portal():
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE)
        except: pass
        st.success(f"مرحباً بك: {st.session_state['username']} (المالك)")
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()

    st.title("👑 لوحة تحكم المالك")
    nav = st.radio("القائمة:", ["📊 متابعة المشاريع (اتحادات)", "👥 ملخص الإنجازات"], horizontal=True)
    st.divider()

    conn = sqlite3.connect('hr_system.db')
    
    if nav == "📊 متابعة المشاريع (اتحادات)":
        st.subheader("تقارير الإنجاز اليومية حسب المشروع")
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع لعرض المهام:", project_list)
        
        reports = pd.read_sql_query("""
            SELECT w.date AS 'التاريخ', e.name AS 'الموظف', e.department AS 'القسم', w.daily_report AS 'ما تم إنجازه'
            FROM WebAttendance w
            JOIN Employees e ON w.emp_id = e.emp_id
            WHERE w.project_name = ? AND w.action = 'انصراف'
            ORDER BY w.id DESC
        """, conn, params=(selected_project,))
        
        if not reports.empty:
            st.success(f"تم العثور على {len(reports)} تقرير لمشروع '{selected_project}'")
            st.dataframe(reports, use_container_width=True, hide_index=True)
        else:
            st.info("لم يتم تسجيل أي إنجازات في هذا المشروع حتى الآن.")
            
    elif nav == "👥 ملخص الإنجازات":
        st.subheader("إحصائيات الإنجاز للمشاريع النشطة")
        summary = pd.read_sql_query("""
            SELECT project_name AS 'اسم المشروع', COUNT(*) AS 'إجمالي التقارير/المهام المنجزة' 
            FROM WebAttendance 
            WHERE action='انصراف' AND project_name IS NOT NULL 
            GROUP BY project_name 
            ORDER BY COUNT(*) DESC
        """, conn)
        
        if not summary.empty:
            st.dataframe(summary, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد إحصائيات بعد.")
            
    conn.close()

# ==========================================
# 8. بوابة الموظف (Employee)
# ==========================================
def employee_portal():
    emp_id = st.session_state['emp_id']
    emp_name, emp_dept, balance = get_employee_info(emp_id)
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE)
        except: pass
        st.info(f"مرحباً: {st.session_state['username']}")
        if st.button("تسجيل الخروج", use_container_width=True):
            st.session_state['logged_in'] = False
            st.rerun()
    render_employee_dashboard(emp_id, balance)

def render_employee_dashboard(emp_id, balance):
    month, delay_mins, absent_str, overtime_mins = get_employee_stats(emp_id)
    absent_list = [d for d in absent_str.split(",") if d.strip()] if absent_str else []
    
    st.header("لوحة معلومات الموظف")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("الرصيد السنوي", f"{balance} يوم")
    c2.metric("تأخيرات", f"{format_hhmm(delay_mins)} ساعة")
    c3.metric("إضافي", f"{format_hhmm(overtime_mins)} ساعة")
    
    conn = sqlite3.connect('hr_system.db')
    pending = conn.execute("SELECT COUNT(*) FROM Requests WHERE emp_id=? AND status='قيد الانتظار'", (emp_id,)).fetchone()[0]
    c4.metric("طلبات معلقة", pending)
    
    if absent_list:
        st.warning(f"⚠️ غياب غير مبرر: ({' ، '.join(absent_list)}) برجاء تقديم إجازة.")
    
    st.divider()
    
    nav = st.radio("العمليات:", ["📍 تسجيل حضور وانصراف", "📝 تقديم طلب جديد", "🌴 سجلاتي"], horizontal=True)
    st.divider()
    
    if nav == "📍 تسجيل حضور وانصراف":
        st.subheader("تسجيل الحضور / الانصراف")
        
        camera_photo = st.camera_input("التقط صورة لإثبات الحضور أو الانصراف")
        
        if camera_photo is not None:
            img = Image.open(camera_photo)
            img.thumbnail((300, 300))
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=85)
            photo_uri = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}"
            
            st.success("تم التقاط الصورة بنجاح! اختر العملية المطلوبة:")
            
            if st.button("تسجيل حضور 🟢", use_container_width=True):
                now_date = datetime.now().strftime("%Y/%m/%d")
                now_time = datetime.now().strftime("%H:%M")
                conn.execute("INSERT INTO WebAttendance (emp_id, date, time, action, location_name, photo) VALUES (?, ?, ?, 'حضور', ?, ?)", 
                             (emp_id, now_date, now_time, "مقر العمل", photo_uri))
                conn.commit()
                st.success(f"تم تسجيل الحضور بنجاح الساعة {now_time}")
            
            st.markdown("---")
            st.markdown("### 📝 تسجيل الانصراف والتقرير اليومي")
            
            project_choices = [f"اتحاد {i}" for i in range(1, 46)]
            selected_proj = st.selectbox("المشروع (الاتحاد) الذي عملت عليه اليوم", project_choices)
            daily_rep = st.text_area("ملخص ما تم إنجازه اليوم", placeholder="اكتب بالتفصيل المهام التي أنجزتها...")
            
            if st.button("تسجيل انصراف 🔴", use_container_width=True):
                if not daily_rep.strip():
                    st.error("❌ يجب كتابة تقرير بما تم إنجازه اليوم لتتمكن من تسجيل الانصراف!")
                else:
                    now_date = datetime.now().strftime("%Y/%m/%d")
                    now_time = datetime.now().strftime("%H:%M")
                    conn.execute("INSERT INTO WebAttendance (emp_id, date, time, action, location_name, photo, project_name, daily_report) VALUES (?, ?, ?, 'انصراف', ?, ?, ?, ?)", 
                                 (emp_id, now_date, now_time, "مقر العمل", photo_uri, selected_proj, daily_rep))
                    conn.commit()
                    st.success(f"تم تسجيل الانصراف وحفظ التقرير بنجاح الساعة {now_time}")

    elif nav == "📝 تقديم طلب جديد":
        with st.form(f"emp_req_{emp_id}"):
            req_type = st.selectbox("نوع الطلب", ["إجازة اعتيادية", "إجازة عارضة", "عمل من المنزل", "مأمورية", "إذن"])
            req_date = st.date_input("التاريخ")
            notes = st.text_area("السبب")
            if st.form_submit_button("إرسال للاعتماد", type="primary"):
                conn.execute("INSERT INTO Requests (emp_id, date, req_type, notes, status) VALUES (?, ?, ?, ?, 'قيد الانتظار')", (emp_id, req_date.strftime("%Y/%m/%d"), req_type, notes))
                conn.commit()
                st.success("تم إرسال الطلب!")
                
    elif nav == "🌴 سجلاتي":
        req_hist = pd.read_sql_query("SELECT date, req_type, status FROM Requests WHERE emp_id=? ORDER BY id DESC", conn, params=(emp_id,))
        if not req_hist.empty: st.dataframe(req_hist, use_container_width=True, hide_index=True)
        else: st.info("لا توجد طلبات.")
        
    conn.close()

# ==========================================
# التوجيه (Routing)
# ==========================================
if not st.session_state['logged_in']: login_page()
else:
    role = st.session_state['role']
    if role == 'admin': admin_portal()
    elif role == 'manager': manager_portal()
    elif role == 'owner': owner_portal()
    else: employee_portal()
