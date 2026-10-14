import streamlit as st

# إعداد الصفحة يجب أن يكون أول أمر في الملف الرئيسي
st.set_page_config(page_title="كيان الشرقية للاستثمار العقاري", page_icon="🏗️", layout="wide")

import pandas as pd
import base64
import os
import sqlite3
import tempfile
from db import *
from modules import *

# تهيئة الجلسة والتصميم وقاعدة البيانات
if 'logged_in' not in st.session_state:
    st.session_state.update({
        'logged_in': False, 
        'role': None, 
        'emp_id': None, 
        'username': None, 
        'primary_role': None, 
        'secondary_role': 'none', 
        'current_role': None
    })

apply_custom_theme()
set_dynamic_background()
setup_database_v4()

# ==========================================
# 1. شاشة تسجيل الدخول
# ==========================================
def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            if os.path.exists(LOGO_FILE):
                img_c1, img_c2, img_c3 = st.columns([1, 2.5, 1])
                with img_c2:
                    st.image(LOGO_FILE, use_container_width=True)
        except:
            pass
        
        st.markdown("<h1 style='text-align: center; font-weight: 900; font-size: 3.5rem; margin-bottom: 0px;'>كيان الشرقية</h1>", unsafe_allow_html=True)
        st.markdown("<h4 style='text-align: center; color: #D4AF37; margin-bottom: 30px;'>للمقاولات والاستثمار العقاري - الزقازيق 🏗️</h4>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            user = st.text_input("اسم المستخدم", placeholder="أدخل اسم المستخدم الخاص بك")
            pwd = st.text_input("كلمة المرور", type="password", placeholder="أدخل كلمة المرور")
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.form_submit_button("تسجيل الدخول", use_container_width=True):
                user_data = authenticate(user, pwd)
                if user_data:
                    role1 = user_data[0]
                    role2 = user_data[1]
                    emp_id = user_data[2]
                    
                    st.session_state.update({
                        'logged_in': True, 
                        'role': role1, 
                        'primary_role': role1,
                        'secondary_role': role2 if role2 else 'none',
                        'current_role': role1,
                        'emp_id': emp_id, 
                        'username': user
                    })
                    log_event("تسجيل دخول", f"دخول ناجح بصلاحية {role1}")
                    st.rerun()
                else:
                    st.error("بيانات الدخول غير صحيحة! يرجى المراجعة.")

# ==========================================
# 2. بوابة الإدارة التكنولوجية (Admin / IT)
# ==========================================
def admin_portal():
    render_sidebar("الإدارة التكنولوجية (IT/Admin)")
    nav = st.radio(
        "القائمة الرئيسية:", 
        ["🕵️ سجل المراقبة (Logs)", "📊 تحليل البصمة", "✅ الطلبات", "➕ إنشاء/تعديل حساب", "⚙ إدارة الحسابات", "📍 المواقع", "📌 تقارير المناديب", "💾 النسخ الاحتياطي"], 
        horizontal=True
    )
    st.divider()
    
    if nav == "🕵️ سجل المراقبة (Logs)":
        st.header("🕵️ سجل حركات النظام والمراقبة (System Audit Logs)")
        st.info("يعرض هذا السجل جميع الحركات والعمليات التي تمت على النظام بالتاريخ، الوقت، واسم المستخدم.")
        conn = get_db_connection()
        try:
            logs_df = pd.read_sql_query("SELECT log_time, username, role, action_type, details FROM AuditLogs ORDER BY id DESC LIMIT 500", conn)
        except:
            logs_df = pd.DataFrame()
        conn.close()
        
        if not logs_df.empty:
            f_c1, f_c2 = st.columns(2)
            user_filter = f_c1.selectbox("فلترة حسب المستخدم:", ["الكل"] + sorted(logs_df['username'].dropna().unique().tolist()))
            action_filter = f_c2.selectbox("فلترة حسب نوع العملية:", ["الكل"] + sorted(logs_df['action_type'].dropna().unique().tolist()))
            
            filtered_logs = logs_df.copy()
            if user_filter != "الكل":
                filtered_logs = filtered_logs[filtered_logs['username'] == user_filter]
            if action_filter != "الكل":
                filtered_logs = filtered_logs[filtered_logs['action_type'] == action_filter]
                
            filtered_logs.columns = ['التاريخ والوقت', 'اسم المستخدم', 'الصلاحية', 'نوع العملية', 'التفاصيل']
            st.dataframe(filtered_logs, use_container_width=True, hide_index=True)
            
            html_logs = generate_html_report("تقرير سجل مراقبة النظام (Audit Logs) - كيان الشرقية", filtered_logs)
            st.download_button("🖨️ طباعة سجل المراقبة (PDF)", data=html_logs, file_name="System_Audit_Logs.html", mime="text/html", type="primary")
        else:
            st.info("لا توجد حركات مسجلة بعد.")

    elif nav == "📊 تحليل البصمة":
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
        else:
            st.info("لا توجد طلبات مسجلة حالياً.")

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
                        log_event("إنشاء حساب موظف", f"الاسم: {new_name} - المستخدم: {new_user}")
                        st.success(f"تم إنشاء حساب ({new_name}) بنجاح!")
                    except:
                        st.error("اسم المستخدم مسجل مسبقاً!")

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
            curr_role = curr_data['role']
            curr_name = curr_data['name'] if pd.notna(curr_data['name']) else ""
            curr_dept = curr_data['department'] if pd.notna(curr_data['department']) and curr_data['department'] in COMPANY_DEPARTMENTS else COMPANY_DEPARTMENTS[0]
            curr_sec_dept = curr_data['secondary_department'] if pd.notna(curr_data['secondary_department']) and curr_data['secondary_department'] in ["لا يوجد"] + COMPANY_DEPARTMENTS else "لا يوجد"
            curr_phone = curr_data['phone'] if pd.notna(curr_data['phone']) else ""
            curr_exempt = curr_data['exempt_report'] if pd.notna(curr_data['exempt_report']) else False
            
            r1_txt = ROLE_REVERSE_MAP.get(curr_role, "موظف عادي (Employee)")
            r2_txt = ROLE_REVERSE_MAP.get(curr_data['secondary_role'], "لا يوجد (None)")
            
            with st.form("edit_user_form"):
                c1, c2 = st.columns(2)
                new_name = c2.text_input("تعديل اسم الموظف", value=curr_name)
                new_username = c1.text_input("اسم المستخدم الجديد", value=selected_user)
                
                c3, c4 = st.columns(2)
                new_dept = c4.selectbox("تعديل القسم الأساسي", COMPANY_DEPARTMENTS, index=COMPANY_DEPARTMENTS.index(curr_dept) if curr_dept in COMPANY_DEPARTMENTS else 0)
                new_sec_dept = c3.selectbox("القسم الإضافي", ["لا يوجد"] + COMPANY_DEPARTMENTS, index=(["لا يوجد"] + COMPANY_DEPARTMENTS).index(curr_sec_dept) if curr_sec_dept in (["لا يوجد"] + COMPANY_DEPARTMENTS) else 0)
                
                c5, c6 = st.columns(2)
                valid_roles = [r for r in ROLE_OPTIONS if r != "لا يوجد (None)"]
                idx1 = valid_roles.index(r1_txt) if r1_txt in valid_roles else 0
                idx2 = ROLE_OPTIONS.index(r2_txt) if r2_txt in ROLE_OPTIONS else 0
                    
                new_role_choice = c6.selectbox("الصلاحية الأساسية", valid_roles, index=idx1)
                new_sec_role_choice = c5.selectbox("الصلاحية الإضافية", ROLE_OPTIONS, index=idx2)
                
                new_pwd = c6.text_input("كلمة المرور الجديدة (اختياري)")
                edit_phone = c5.text_input("تعديل رقم الهاتف", value=curr_phone)
                edit_exempt = st.checkbox("✔️ إعفاء الموظف من إجبارية تقديم التقرير اليومي", value=bool(curr_exempt))
                
                if st.form_submit_button("تحديث البيانات الشامل", type="primary"):
                    final_username = new_username.strip() if new_username.strip() else selected_user
                    try:
                        updates = ["role=%s", "secondary_role=%s"]
                        params = [ROLE_MAP[new_role_choice], ROLE_MAP[new_sec_role_choice]]
                        
                        if final_username != selected_user:
                            updates.append("username=%s")
                            params.append(final_username)
                            
                        if new_pwd.strip():
                            updates.append("password=%s")
                            params.append(new_pwd.strip())
                            
                        params.append(selected_user)
                        db_execute(f"UPDATE Users SET {', '.join(updates)} WHERE username=%s", tuple(params))
                        
                        if curr_emp_id and str(curr_emp_id) not in ['0', 'owner']:
                            db_execute("UPDATE Employees SET name=%s, department=%s, secondary_department=%s, phone=%s, exempt_report=%s WHERE emp_id=%s", 
                                       (new_name.strip() if new_name.strip() else curr_name, new_dept, new_sec_dept, edit_phone, edit_exempt, curr_emp_id))
                        log_event("تعديل حساب مستخدم", f"تعديل بيانات وصلاحيات الحساب: {selected_user}")
                        st.success("تم التحديث بنجاح!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"حدث خطأ: {e}")

            st.divider()
            st.subheader("🗑️ حذف حساب نهائياً")
            with st.form("delete_user_form"):
                user_to_delete = st.selectbox("اختر اسم المستخدم المراد حذفه:", users_df['username'].tolist(), key="select_del_user")
                if st.form_submit_button("إيقاف وحذف الحساب 🗑️", type="primary"):
                    if user_to_delete.lower() in ['admin', 'owner']:
                        st.error("❌ لا يمكن حذف حسابات النظام الأساسية!")
                    else:
                        emp_id_to_del = users_df[users_df['username'] == user_to_delete].iloc[0]['emp_id']
                        db_execute("DELETE FROM Users WHERE username=%s", (user_to_delete,))
                        if emp_id_to_del and str(emp_id_to_del) not in ['0', 'owner']:
                            db_execute("DELETE FROM Employees WHERE emp_id=%s", (emp_id_to_del,))
                        log_event("حذف حساب مستخدم", f"حذف الحساب: {user_to_delete}")
                        st.success(f"تم مسح الحساب ({user_to_delete}) بنجاح!")
                        st.rerun()

    elif nav == "📍 المواقع":
        st.header("إضافة مواقع الشركة للمقاولات (بواسطة الـ GPS)")
        if not GEO_AVAILABLE:
            st.error("مكتبة 'streamlit-js-eval' غير مثبتة.")
        else:
            if st.button("🔄 تحديث موقعي الآن"):
                st.rerun()
            loc_admin = get_geolocation()
            admin_lat = 0.0
            admin_lon = 0.0
            
            if loc_admin and isinstance(loc_admin, dict) and 'coords' in loc_admin:
                admin_lat = float(loc_admin['coords']['latitude'])
                admin_lon = float(loc_admin['coords']['longitude'])
                st.success(f"📍 موقعك الحالي: خط العرض: {admin_lat:.6f} | خط الطول: {admin_lon:.6f}")
                
            with st.form("add_location_form"):
                loc_name = st.text_input("اسم الموقع / المشروع")
                c1, c2, c3 = st.columns(3)
                new_lat = c1.number_input("خط العرض", value=admin_lat, format="%.6f")
                new_lon = c2.number_input("خط الطول", value=admin_lon, format="%.6f")
                new_rad = c3.number_input("النطاق المسموح (بالمتر)", value=100.0, min_value=10.0)
                if st.form_submit_button("حفظ الموقع", type="primary") and loc_name.strip() != "":
                    db_execute("INSERT INTO Locations (name, lat, lon, radius) VALUES (%s, %s, %s, %s)", (loc_name, new_lat, new_lon, new_rad))
                    log_event("إضافة موقع GPS", f"الموقع: {loc_name}")
                    st.success("تم حفظ الموقع بنجاح!")
                    st.rerun()
                    
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
                    log_event("حذف موقع GPS", f"حذف الموقع: {loc_to_delete}")
                    st.success("تم الحذف بنجاح!")
                    st.rerun()

    elif nav == "📌 تقارير المناديب":
        st.header("شيت الحضور والانصراف المجمع")
        render_attendance_report()
        
    elif nav == "💾 النسخ الاحتياطي":
        st.header("💾 النسخ الاحتياطي الشامل (Database Dump)")
        st.info("يمكنك تحميل قاعدة بيانات (SQLite) بصيغة `.db` تحتوي على كل البيانات.")
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
                    except:
                        pass
                        
                sqlite_conn.close()
                conn.close()
                log_event("نسخ احتياطي", "قام المسؤول بتحميل نسخة كاملة من قاعدة البيانات")
                
                with open(tmp_db_path, "rb") as f:
                    db_bytes = f.read()
                    
                st.download_button(label="💾 اضغط هنا لتحميل ملف قاعدة البيانات (.db) الآن", data=db_bytes, file_name=f"Keyan_DB_Backup_{get_egypt_time().strftime('%Y%m%d_%H%M')}.db", mime="application/x-sqlite3")

# ==========================================
# 3. بوابة المالك (Owner Portal)
# ==========================================
def owner_portal():
    render_sidebar("المالك")
    render_smart_alerts()
    st.title("👑 لوحة تحكم المالك")
    nav = st.radio(
        "القائمة:", 
        ["📊 لوحة القيادة", "💰 أقساط الجهاز والتنفيذ (المساهمين)", "👥 العملاء وكشف الحساب", "📈 التراخيص والرسومات", "📄 تتبع المستخلصات", "📑 تقارير المهام"], 
        horizontal=True
    )
    st.divider()

    if nav == "📊 لوحة القيادة":
        render_company_dashboard()
        
    elif nav == "💰 أقساط الجهاز والتنفيذ (المساهمين)":
        render_financials_module(can_edit=True)
        
    elif nav == "👥 العملاء وكشف الحساب":
        render_clients_and_crm_module(mode="owner")
        
    elif nav == "📈 التراخيص والرسومات":
        conn = get_db_connection()
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع:", project_list)
            
        st.markdown("### 📜 التراخيص ومستنداتها")
        lic_df = pd.read_sql_query("SELECT id, license_name, due_date, status, file_data FROM ProjectLicenses WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
        if not lic_df.empty:
            for _, row in lic_df.iterrows():
                with st.expander(f"ترخيص: {row['license_name']} | الحالة: {row['status']}"):
                    st.write(f"تاريخ الانتهاء: {row['due_date']}")
                    if is_valid_file(row['file_data']):
                        try:
                            dec = base64.b64decode(row['file_data'])
                            st.download_button("📥 تحميل المستند", data=dec, file_name=f"{row['license_name']}.pdf", mime="application/octet-stream", key=f"dl_lic_{row['id']}")
                        except:
                            pass
                    else:
                        st.info("لا يوجد مستند مرفق لهذا الترخيص.")
        else:
            st.info("لا يوجد تراخيص")
            
        st.markdown("### 📐 الرسومات الهندسية")
        draw_df = pd.read_sql_query("SELECT id, drawing_name, due_date, status, file_data FROM ProjectDrawings WHERE project_name = %s ORDER BY due_date ASC", conn, params=(selected_project,))
        if not draw_df.empty:
            for _, row in draw_df.iterrows():
                with st.expander(f"رسم: {row['drawing_name']} | الحالة: {row['status']}"):
                    st.write(f"تاريخ التسليم: {row['due_date']}")
                    if is_valid_file(row['file_data']):
                        try:
                            dec = base64.b64decode(row['file_data'])
                            st.download_button("📥 تحميل لوحة الرسم", data=dec, file_name=f"{row['drawing_name']}.pdf", mime="application/octet-stream", key=f"dl_drw_{row['id']}")
                        except:
                            pass
                    else:
                        st.info("لا توجد لوحة مرفقة لهذا الرسم.")
        else:
            st.info("لا يوجد رسومات")
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
                        
                        if pd.notna(row['impediment_notes']) and str(row['impediment_notes']).strip() != "":
                            st.warning(f"**معوقات وملاحظات مسجلة عليه:** {row['impediment_notes']}")
                            
                        if is_valid_file(row['file_data']):
                            try:
                                dec = base64.b64decode(row['file_data'])
                                st.download_button("📥 تحميل المستخلص (PDF)", data=dec, file_name=f"{row['extract_name']}_extract.pdf", mime="application/octet-stream", key=f"dl_trk_ext_{row['id']}")
                            except:
                                pass
            else:
                st.info("لا يوجد مستخلصات مسجلة لهذا المشروع حتى الآن.")
        except:
            pass
        conn.close()
        
    elif nav == "📑 تقارير المهام":
        conn = get_db_connection()
        project_list = [f"اتحاد {i}" for i in range(1, 46)]
        selected_project = st.selectbox("اختر المشروع لعرض المهام:", project_list)
        reports = pd.read_sql_query("SELECT w.date, e.name, e.department, w.daily_report FROM WebAttendance w JOIN Employees e ON w.emp_id = e.emp_id WHERE w.project_name = %s AND w.action IN ('انصراف', 'تقرير', 'إنجاز مهمة') ORDER BY w.id DESC", conn, params=(selected_project,))
        
        if not reports.empty: 
            reports.columns = ['التاريخ', 'الموظف', 'القسم', 'الإنجاز']
            st.dataframe(reports, use_container_width=True, hide_index=True)
        else:
            st.info("لا يوجد تقارير مسجلة لهذا المشروع.")
        conn.close()

# ==========================================
# 4. بوابات الموظفين والمديرين والأقسام
# ==========================================
def hr_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("موارد بشرية (HR)")
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "📝 تقارير الحضور والانصراف للشركة"], horizontal=True)
    st.divider()
    
    if nav == "📝 تقارير الحضور والانصراف للشركة":
        render_attendance_report()
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

def admin_manager_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("المدير الإداري")
    render_smart_alerts()
    
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "📊 لوحة القيادة", "✅ طلبات الموظفين", "📋 إسناد مهام", "📄 إدارة المستخلصات", "📝 تقارير الحضور"], horizontal=True)
    st.divider()
    
    if nav == "📊 لوحة القيادة":
        render_company_dashboard()
    elif nav == "✅ طلبات الموظفين":
        st.header("إدارة طلبات الموظفين (جميع الأقسام)")
        conn = get_db_connection()
        reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, e.department, r.date, r.req_type, r.notes FROM Requests r JOIN Employees e ON r.emp_id = e.emp_id WHERE r.status = 'قيد الانتظار' AND r.emp_id != %s", conn, params=(emp_id,))
        conn.close()
        
        if reqs.empty:
            st.success("لا توجد طلبات معلقة في الشركة حالياً.")
        else:
            for _, row in reqs.iterrows():
                with st.expander(f"طلب من: {row['name']} (القسم: {row['department']}) - نوع الطلب: {row['req_type']}"):
                    st.write(f"**الملاحظات:** {row['notes']}")
                    c1, c2 = st.columns(2)
                    if c1.button("موافقة واعتماد", key=f"app_{row['id']}", type="primary"):
                        db_execute("UPDATE Requests SET status='مقبول' WHERE id=%s", (row['id'],))
                        db_execute("INSERT INTO Permissions VALUES (%s, %s, %s)", (row['emp_id'], row['date'], row['req_type']))
                        log_event("اعتماد طلب موظف", f"طلب رقم {row['id']} للموظف {row['name']}")
                        st.rerun()
                    if c2.button("رفض الطلب", key=f"rej_{row['id']}"):
                        db_execute("UPDATE Requests SET status='مرفوض' WHERE id=%s", (row['id'],))
                        log_event("رفض طلب موظف", f"طلب رقم {row['id']} للموظف {row['name']}")
                        st.rerun()
    elif nav == "📋 إسناد مهام":
        render_task_delegation("الكل")
    elif nav == "📄 إدارة المستخلصات":
        render_manage_extracts()
    elif nav == "📝 تقارير الحضور":
        render_attendance_report()
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

def manager_portal():
    emp_id = st.session_state['emp_id']
    
    try:
        conn = get_db_connection()
        res = pd.read_sql_query("SELECT department, secondary_department, annual_balance FROM Employees WHERE emp_id=%s", conn, params=(emp_id,))
        conn.close()
        if not res.empty:
            emp_dept = res.iloc[0]['department']
            sec_dept = res.iloc[0]['secondary_department']
            balance = res.iloc[0]['annual_balance']
        else:
            emp_dept = ""
            sec_dept = ""
            balance = 21
    except:
        emp_dept = ""
        sec_dept = ""
        balance = 21
        
    render_sidebar("رئيس قسم")
    nav_options = ["👤 لوحتي الشخصية", "✅ طلبات القسم", "📋 إسناد مهام للقسم", "📝 تقارير دوام القسم"]
    
    if "مهندسين إدارة وتخطيط" in [emp_dept, sec_dept]:
        nav_options.append("📄 مراجعة المستخلصات")
    if "مبيعات وخدمة عملاء" in [emp_dept, sec_dept]:
        nav_options.append("👥 إدارة العملاء (CRM)")

    nav = st.radio("القائمة:", nav_options, horizontal=True)
    st.divider()
    
    if nav == "✅ طلبات القسم":
        st.header(f"طلبات الموظفين في إدارتك")
        conn = get_db_connection()
        reqs = pd.read_sql_query("SELECT r.id, r.emp_id, e.name, r.date, r.req_type, r.notes FROM Requests r JOIN Employees e ON r.emp_id = e.emp_id WHERE (e.department = %s OR e.secondary_department = %s) AND r.status = 'قيد الانتظار' AND r.emp_id != %s", conn, params=(emp_dept, emp_dept, emp_id))
        conn.close()
        
        if reqs.empty:
            st.success("لا توجد طلبات معلقة لفريقك حالياً.")
        else:
            for _, row in reqs.iterrows():
                with st.expander(f"طلب من: {row['name']} - {row['req_type']}"):
                    c1, c2 = st.columns(2)
                    if c1.button("موافقة", key=f"app_{row['id']}", type="primary"):
                        db_execute("UPDATE Requests SET status='مقبول' WHERE id=%s", (row['id'],))
                        db_execute("INSERT INTO Permissions VALUES (%s, %s, %s)", (row['emp_id'], row['date'], row['req_type']))
                        log_event("موافقة رئيس قسم على طلب", f"طلب رقم {row['id']} للموظف {row['name']}")
                        st.rerun()
                    if c2.button("رفض", key=f"rej_{row['id']}"):
                        db_execute("UPDATE Requests SET status='مرفوض' WHERE id=%s", (row['id'],))
                        log_event("رفض رئيس قسم لطلب", f"طلب رقم {row['id']} للموظف {row['name']}")
                        st.rerun()
    elif nav == "📋 إسناد مهام للقسم":
        render_task_delegation(emp_dept)
    elif nav == "📝 تقارير دوام القسم":
        render_attendance_report(department_filter=emp_dept)
    elif nav == "📄 مراجعة المستخلصات":
        render_manage_extracts()
    elif nav == "👥 إدارة العملاء (CRM)":
        render_clients_and_crm_module(mode="sales")
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

def accountant_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("المحاسب")
    nav = st.radio(
        "القائمة:", 
        ["👤 لوحتي الشخصية", "💰 أقساط الجهاز والتنفيذ (المساهمين)", "👥 متابعة دفع أقساط العملاء وكشف الحساب", "📄 إدارة المستخلصات"], 
        horizontal=True
    )
    st.divider()
    
    if nav == "💰 أقساط الجهاز والتنفيذ (المساهمين)":
        render_financials_module(can_edit=True)
    elif nav == "👥 متابعة دفع أقساط العملاء وكشف الحساب":
        render_clients_and_crm_module(mode="accountant")
    elif nav == "📄 إدارة المستخلصات":
        render_manage_extracts()
    else:
        render_employee_dashboard(emp_id, balance)

def licensing_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("مسؤول التراخيص")
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "📜 التراخيص (خزنة المستندات)"], horizontal=True)
    
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
                log_event("إضافة ترخيص", f"ترخيص: {lic_name} - مشروع: {proj}")
                st.success("تم التسجيل ورفع المستند بنجاح!")
                
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, license_name, due_date, status FROM ProjectLicenses", conn)
        conn.close()
        
        if not df.empty:
            st.dataframe(df.rename(columns={'project_name':'المشروع','license_name':'الترخيص','due_date':'تاريخ الانتهاء','status':'الحالة'}), hide_index=True)
    else:
        render_employee_dashboard(emp_id, balance)

def engineer_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("المهندس")
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "📐 الرسومات (خزنة الملفات)"], horizontal=True)
    
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
                log_event("إضافة رسم هندسي", f"لوحة: {draw_name} - مشروع: {proj}")
                st.success("تم التسجيل ورفع اللوحة بنجاح!")
                
        conn = get_db_connection()
        df = pd.read_sql_query("SELECT project_name, drawing_name, due_date, status FROM ProjectDrawings", conn)
        conn.close()
        
        if not df.empty:
            st.dataframe(df.rename(columns={'project_name':'المشروع','drawing_name':'اسم الرسم','due_date':'تاريخ التسليم','status':'الحالة'}), hide_index=True)
    else:
        render_employee_dashboard(emp_id, balance)

def extracts_engineer_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    emp_name = emp_info[0]
    balance = emp_info[2]
    
    render_sidebar("مهندس المستخلصات")
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "📄 إنشاء وتجهيز مستخلص"], horizontal=True)
    
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
                    log_event("إنشاء مسودة مستخلص", f"مستخلص: {ext_name} - مشروع: {proj} - قيمة: {ext_amount}")
                    st.success("تم إضافة المستخلص لحسابك للعمل عليه!")
                else:
                    st.error("يرجى كتابة اسم المستخلص وتحديد قيمته!")
                    
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
                                db_execute("UPDATE Extracts SET impediment_notes=%s WHERE id=%s", (new_imped, row['id']))
                                log_event("تحديث نواقص مستخلص", f"مستخلص: {row['extract_name']}")
                                st.rerun()
                                
                            if col2.button("🚀 إصدار المستخلص (إرسال للتخطيط)", key=f"iss_{row['id']}", type="primary"):
                                db_execute("UPDATE Extracts SET status='بانتظار اعتماد التخطيط', impediment_notes='تم الإنجاز - بانتظار الاعتماد' WHERE id=%s", (row['id'],))
                                log_event("إصدار مستخلص للتخطيط", f"مستخلص: {row['extract_name']} - مشروع: {row['project_name']}")
                                st.rerun()
                        else:
                            st.info("تم إصدار هذا المستخلص ولم يعد في عهدتك.")
            else:
                st.info("لا توجد مستخلصات حالياً.")
        except:
            pass
        conn.close()
    else:
        render_employee_dashboard(emp_id, balance)

def planning_engineer_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("مهندس إدارة وتخطيط")
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "📄 مراجعة واعتماد المستخلصات"], horizontal=True)
    
    if nav == "📄 مراجعة واعتماد المستخلصات":
        render_manage_extracts()
    else:
        render_employee_dashboard(emp_id, balance)

def legal_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("مسؤول الشؤون القانونية والعقود")
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "📄 أرشفة العقود الموقعة", "💳 إدارة الشيكات البنكية", "📊 كشف حساب وتقييم عميل"], horizontal=True)
    st.divider()
    
    if nav == "📄 أرشفة العقود الموقعة":
        st.header("إرفاق وحفظ العقود الأصلية (Scanned)")
        st.info("اختر الوحدة المباعة من قسم المبيعات لترفع نسختها الموقعة في أرشيف الشركة.")
        conn = get_db_connection()
        units = pd.read_sql_query("SELECT unit_code, client_name, project_name FROM RealEstateUnits WHERE status IN ('مباعة', 'محجوزة')", conn)
        
        with st.form("add_contract"):
            if not units.empty:
                unit_opts = units['unit_code'].fillna('') + " - " + units['client_name'].fillna('') + " (" + units['project_name'].fillna('') + ")"
                sel_unit = st.selectbox("اختر الوحدة المباعة:", unit_opts)
            else:
                sel_unit = st.text_input("كود الوحدة")
                
            uploaded_contract = st.file_uploader("إرفاق نسخة العقد الموقعة (PDF/صورة عالية الجودة)", type=['pdf', 'jpg', 'png'])
            
            if st.form_submit_button("حفظ العقد في الأرشيف 🔒", type="primary"):
                if uploaded_contract and sel_unit:
                    file_b64 = base64.b64encode(uploaded_contract.read()).decode('utf-8')
                    u_code = str(sel_unit).split(" - ")[0]
                    db_execute("UPDATE RealEstateUnits SET contract_file=%s WHERE unit_code=%s", (file_b64, u_code))
                    log_event("أرشفة عقد قانوني", f"وحدة: {u_code}")
                    st.success("تم أرشفة العقد وربطه بالوحدة بنجاح!")
                else:
                    st.error("يرجى إرفاق الملف واختيار الوحدة!")
                    
        st.divider()
        st.subheader("العقود المؤرشفة حالياً")
        archived = pd.read_sql_query("SELECT id, unit_code, client_name, contract_file FROM RealEstateUnits WHERE contract_file IS NOT NULL", conn)
        
        has_archived = False
        if not archived.empty:
            for _, row in archived.iterrows():
                if is_valid_file(row['contract_file']):
                    has_archived = True
                    with st.expander(f"📄 عقد وحدة: {row['unit_code']} | العميل: {row['client_name']}"):
                        try:
                            dec = base64.b64decode(row['contract_file'])
                            st.download_button("📥 تحميل / عرض العقد", data=dec, file_name=f"Contract_{row['unit_code']}.pdf", mime="application/octet-stream", key=f"dl_contract_{row['id']}")
                        except:
                            pass
        if not has_archived:
            st.info("لا توجد عقود مؤرشفة في النظام.")
        conn.close()
        
    elif nav == "💳 إدارة الشيكات البنكية":
        st.header("تسجيل وأرشفة الشيكات البنكية للعملاء")
        conn = get_db_connection()
        units = pd.read_sql_query("SELECT unit_code, client_name FROM RealEstateUnits WHERE status IN ('مباعة', 'محجوزة')", conn)
        
        with st.form("add_cheque"):
            c1, c2 = st.columns(2)
            if not units.empty:
                unit_opts = units['unit_code'].fillna('') + " - " + units['client_name'].fillna('')
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
                    log_event("تسجيل شيك بنكي", f"شيك رقم: {chq_num} - العميل: {u_client} - قيمة: {chq_amt}")
                    st.success("تم تسجيل الشيك وحفظه في النظام بنجاح!")
                else:
                    st.error("يرجى إدخال رقم الشيك وقيمته.")
                    
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
                if is_valid_file(row['file_data']):
                    with st.expander(f"صورة شيك رقم: {row['cheque_number']} | الوحدة: {row['unit_code']}"):
                        try:
                            dec = base64.b64decode(row['file_data'])
                            st.download_button("📥 تحميل صورة الشيك", data=dec, file_name=f"Cheque_{row['cheque_number']}.pdf", mime="application/octet-stream", key=f"dl_chq_{row['id']}")
                        except:
                            pass
        else:
            st.info("لا توجد شيكات مسجلة.")
        conn.close()
    elif nav == "📊 كشف حساب وتقييم عميل":
        render_clients_and_crm_module(mode="owner")
    elif nav == "👤 لوحتي الشخصية":
        render_employee_dashboard(emp_id, balance)

def sales_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("المبيعات وخدمة العملاء")
    nav = st.radio("القائمة:", ["👤 لوحتي الشخصية", "👥 إدارة العملاء وجدولة الأقساط وكشف الحساب"], horizontal=True)
    st.divider()
    
    if nav == "👥 إدارة العملاء وجدولة الأقساط وكشف الحساب":
        render_clients_and_crm_module(mode="sales")
    else:
        render_employee_dashboard(emp_id, balance)

def employee_portal():
    emp_id = st.session_state['emp_id']
    emp_info = get_employee_info(emp_id)
    balance = emp_info[2]
    
    render_sidebar("موظف")
    render_employee_dashboard(emp_id, balance)

# ==========================================
# 5. نظام التوجيه (Routing) لجميع الصلاحيات
# ==========================================
if not st.session_state['logged_in']: 
    login_page()
else:
    role = st.session_state.get('current_role', st.session_state.get('role', 'employee'))
    
    if role == 'admin' or role == 'it':
        admin_portal() 
    elif role == 'admin_manager':
        admin_manager_portal()
    elif role == 'manager':
        manager_portal()
    elif role == 'owner':
        owner_portal()
    elif role == 'accountant':
        accountant_portal()
    elif role == 'licensing':
        licensing_portal()
    elif role == 'engineer':
        engineer_portal()
    elif role == 'extracts_engineer':
        extracts_engineer_portal() 
    elif role == 'planning_engineer':
        planning_engineer_portal()
    elif role == 'sales':
        sales_portal()
    elif role == 'legal':
        legal_portal()
    elif role == 'hr':
        hr_portal()
    else:
        employee_portal()
