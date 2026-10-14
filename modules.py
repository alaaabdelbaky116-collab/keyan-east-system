import streamlit as st
import pandas as pd
from datetime import datetime
import base64
from PIL import Image
import io
import os
import pytz
import plotly.express as px
from db import *

try:
    from streamlit_js_eval import get_geolocation
    GEO_AVAILABLE = True
except ImportError:
    GEO_AVAILABLE = False

# ==========================================
# 1. التصميم العام والشريط الجانبي والتنبيهات
# ==========================================
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

def render_sidebar(role_title):
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE):
                st.image(LOGO_FILE, use_container_width=True)
        except:
            pass
        
        if st.session_state.get('secondary_role') and st.session_state['secondary_role'] != 'none':
            st.success(f"مرحباً: {st.session_state['username']}")
            st.markdown("🔄 **لوحة التحكم (الصلاحية المزدوجة):**")
            
            role1_disp = DISPLAY_MAP.get(st.session_state['primary_role'], st.session_state['primary_role'])
            role2_disp = DISPLAY_MAP.get(st.session_state['secondary_role'], st.session_state['secondary_role'])
            current_disp = DISPLAY_MAP.get(st.session_state['current_role'], st.session_state['current_role'])
            
            options = [role1_disp, role2_disp]
            if current_disp not in options:
                current_disp = options[0]
            
            selected_role_disp = st.selectbox("اختر الصلاحية للعمل بها الآن:", options, index=options.index(current_disp))
            
            if selected_role_disp != current_disp:
                if selected_role_disp == role1_disp:
                    st.session_state['current_role'] = st.session_state['primary_role']
                else:
                    st.session_state['current_role'] = st.session_state['secondary_role']
                log_event("تبديل الصلاحية", f"التحويل إلى صلاحية: {selected_role_disp}")
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
                        log_event("تغيير كلمة المرور", "قام المستخدم بتحديث كلمة المرور الخاصة به")
                        st.success("تم التغيير بنجاح! احتفظ بها.")
                    else:
                        st.error("كلمة المرور قصيرة جداً.")
                        
        st.divider()
        if st.button("🚪 تسجيل الخروج", use_container_width=True):
            log_event("تسجيل خروج", "خروج من النظام")
            st.session_state['logged_in'] = False
            st.rerun()

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
            except:
                pass
    except:
        pass

    try:
        fin_df = pd.read_sql_query("SELECT installment_type, project_name, due_date, category, shareholder_name FROM ProjectFinancials WHERE status IN ('مستحق (لم يُدفع)', 'متأخر')", conn)
        for _, row in fin_df.iterrows():
            try:
                d_date = datetime.strptime(row['due_date'], "%Y/%m/%d").replace(tzinfo=pytz.timezone('Africa/Cairo'))
                days_left = (d_date - today).days
                cat_label = row['category'] if pd.notna(row['category']) else 'قسط'
                sh_label = f" - المساهم: {row['shareholder_name']}" if pd.notna(row['shareholder_name']) and row['shareholder_name'] != 'الشركة' else ""
                if 0 <= days_left <= 10:
                    alerts.append(f"💸 **تنبيه مالي ({cat_label}):** '{row['installment_type']}' لمشروع ({row['project_name']}{sh_label}) يستحق خلال {days_left} أيام!")
                elif days_left < 0:
                    alerts.append(f"🚨 **متأخرات ({cat_label}):** '{row['installment_type']}' لمشروع ({row['project_name']}{sh_label}) متأخر منذ {-days_left} أيام!")
            except:
                pass
    except:
        pass

    conn.close()

    if alerts:
        with st.expander("🔔 اضغط هنا لرؤية التنبيهات الذكية الهامة!", expanded=True):
            for alert in alerts:
                if '❌' in alert or '🚨' in alert:
                    st.error(alert)
                else:
                    st.warning(alert)

# ==========================================
# 2. إدارة الإجازات السنوية (للـ HR) وإعفاء التقارير (لرؤساء الأقسام)
# ==========================================
def render_leave_balance_management():
    st.header("🌴 إدارة أرصدة الإجازات السنوية للموظفين (طوال العام)")
    st.info("💡 يمكنك من هنا التحكم في رصيد الإجازات المتبقي لكل موظف (مثلاً: تحديد رصيد مخصص لموظف التحق بالشركة في آخر شهرين من السنة، أو تعديل الرصيد السنوي).")
    
    conn = get_db_connection()
    current_year = get_egypt_time().strftime("%Y")
    emps_df = pd.read_sql_query("SELECT emp_id, name, department, annual_balance FROM Employees ORDER BY name ASC", conn)
    perms_df = pd.read_sql_query("SELECT emp_id, COUNT(*) as used_days FROM Permissions WHERE type='إجازة' AND date LIKE %s GROUP BY emp_id", conn, params=(f"{current_year}/%",))
    conn.close()
    
    if not emps_df.empty:
        merged_df = pd.merge(emps_df, perms_df, on='emp_id', how='left')
        merged_df['used_days'] = merged_df['used_days'].fillna(0).astype(int)
        merged_df['annual_balance'] = merged_df['annual_balance'].fillna(DEFAULT_ANNUAL_BALANCE).astype(int)
        
        with st.form("hr_update_leave_balance"):
            st.subheader("✏️ تعديل أو تخصيص رصيد إجازات موظف")
            c1, c2 = st.columns(2)
            emp_options = merged_df['emp_id'].astype(str) + " - " + merged_df['name'] + " (الرصيد المتبقي حالياً: " + merged_df['annual_balance'].astype(str) + " يوم)"
            selected_emp_str = c1.selectbox("اختر الموظف:", emp_options)
            new_balance = c2.number_input("الرصيد المتبقي الجديد خلال السنة (بالأيام):", min_value=0, max_value=365, value=21, step=1)
            reason_note = st.text_input("ملاحظة التعديل (مثال: تعيين جديد في آخر شهرين من السنة / تسوية رصيد)")
            
            if st.form_submit_button("تحديث رصيد الإجازات 💾", type="primary"):
                emp_id_to_upd = selected_emp_str.split(" - ")[0].strip()
                db_execute("UPDATE Employees SET annual_balance=%s WHERE emp_id=%s", (int(new_balance), emp_id_to_upd))
                log_event("تعديل رصيد إجازات (HR)", f"كود الموظف: {emp_id_to_upd} - الرصيد الجديد: {new_balance} يوم - السبب: {reason_note}")
                st.success(f"تم تحديث رصيد الإجازات للموظف بنجاح إلى ({new_balance}) يوم!")
                st.rerun()
                
        st.divider()
        st.subheader(f"📊 بيان أرصدة إجازات الموظفين لعام {current_year}")
        disp_leaves = merged_df[['emp_id', 'name', 'department', 'used_days', 'annual_balance']].copy()
        disp_leaves.columns = ['كود الموظف', 'اسم الموظف', 'القسم', f'إجازات مستنفدة في {current_year}', 'الرصيد المتبقي حالياً (يوم)']
        st.dataframe(disp_leaves, use_container_width=True, hide_index=True)
        
        html_leaves = generate_html_report(f"تقرير أرصدة الإجازات السنوية لعام {current_year} - كيان الشرقية", disp_leaves)
        st.download_button("🖨️ طباعة تقرير أرصدة الإجازات (PDF)", data=html_leaves, file_name=f"Leave_Balances_{current_year}.html", mime="text/html")
    else:
        st.info("لا يوجد موظفين مسجلين حالياً.")

def render_department_exemption_manager(department_filter="الكل"):
    st.header("🛡️ التحكم في إعفاء موظفي القسم من تقرير الانصراف اليومي")
    st.info("💡 يمكنك من هنا استثناء أي موظف في قسمك من شرط كتابة التقرير اليومي عند تسجيل بصمة الانصراف، أو إلغاء الاستثناء عنه.")
    
    conn = get_db_connection()
    if department_filter == "الكل":
        emps_df = pd.read_sql_query("SELECT emp_id, name, department, exempt_report FROM Employees ORDER BY name ASC", conn)
    else:
        emps_df = pd.read_sql_query(
            "SELECT emp_id, name, department, exempt_report FROM Employees WHERE department=%s OR secondary_department=%s ORDER BY name ASC", 
            conn, params=(department_filter, department_filter)
        )
    conn.close()
    
    if not emps_df.empty:
        emps_df['حالة الإعفاء الحالية'] = emps_df['exempt_report'].apply(lambda x: "معفى من التقرير ✅" if bool(x) else "ملزم بالتقرير ❌")
        
        with st.form("dept_exempt_form"):
            c1, c2 = st.columns(2)
            emp_opts = emps_df['emp_id'].astype(str) + " - " + emps_df['name'] + " (" + emps_df['حالة الإعفاء الحالية'] + ")"
            sel_emp = c1.selectbox("اختر الموظف من قسمك:", emp_opts)
            new_exempt_status = c2.radio("قرار رئيس القسم:", ["✔️ إعفاء الموظف من التقرير اليومي", "❌ إلزام الموظف بكتابة التقرير اليومي"], horizontal=True)
            
            if st.form_submit_button("حفظ وتطبيق القرار 🚀", type="primary"):
                target_emp_id = sel_emp.split(" - ")[0].strip()
                is_exempt_bool = True if "إعفاء" in new_exempt_status else False
                db_execute("UPDATE Employees SET exempt_report=%s WHERE emp_id=%s", (is_exempt_bool, target_emp_id))
                log_event("تعديل إعفاء التقرير اليومي", f"الموظف: {target_emp_id} - معفى: {is_exempt_bool}")
                st.success("تم تحديث حالة إعفاء الموظف بنجاح!")
                st.rerun()
                
        st.divider()
        disp_ex = emps_df[['emp_id', 'name', 'department', 'حالة الإعفاء الحالية']].copy()
        disp_ex.columns = ['كود الموظف', 'اسم الموظف', 'القسم', 'حالة التقرير اليومي']
        st.dataframe(disp_ex, use_container_width=True, hide_index=True)
    else:
        st.info("لا يوجد موظفين مسجلين في هذا القسم حالياً.")

# ==========================================
# 3. لوحة القيادة وتقارير الحضور والمهام والمستخلصات
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
    except:
        total_emps = 0
        present_today = 0
        pending_reqs = 0

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
        else:
            st.info("لا توجد بيانات للمشاريع بعد.")

    with col2:
        st.subheader("💰 الموقف المالي للأقساط")
        fin_df = pd.read_sql_query("SELECT status AS \"الحالة\", SUM(amount) AS \"الإجمالي\" FROM ProjectFinancials GROUP BY status", conn)
        if not fin_df.empty:
            fig2 = px.pie(fin_df, values="الإجمالي", names="الحالة", hole=0.45, color_discrete_sequence=px.colors.sequential.YlOrBr)
            fig2.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="Tajawal", font_color="#fff")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("لا توجد تعاملات مالية مسجلة.")
    conn.close()

def render_attendance_report(department_filter=None):
    conn = get_db_connection()
    if department_filter:
        emps = db_fetchall("SELECT name FROM Employees WHERE department=%s OR secondary_department=%s ORDER BY name", (department_filter, department_filter))
    else:
        emps = db_fetchall("SELECT name FROM Employees ORDER BY name")
        
    emp_list = ["الكل"] + [e[0] for e in emps]
    months = db_fetchall("SELECT DISTINCT substring(date from 1 for 7) FROM WebAttendance")
    month_list = ["الكل"] + [m[0] for m in months if m[0]]
    
    st.write("📌 **أدوات الفلترة والبحث السريع:**")
    c1, c2, c3 = st.columns(3)
    selected_emp = c1.selectbox("👤 اختيار الموظف:", emp_list)
    filter_type = c2.radio("📅 فترة التقرير:", ["اليوم فقط", "شهر محدد", "كل السجلات"], horizontal=True)
    
    if filter_type == "شهر محدد":
        selected_month = c3.selectbox("اختر الشهر:", month_list)
    else:
        selected_month = "الكل"
        
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
    
    if department_filter:
        query += " AND (e.department = %s OR e.secondary_department = %s)"
        params.extend([department_filter, department_filter])
        
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
        
        rep_df['ساعات العمل'] = rep_df.apply(lambda row: calculate_hours_diff(row['check_in'], row['check_out']), axis=1)
        
        final_df = rep_df[['التاريخ', 'اسم اليوم', 'emp_name', 'dept', 'check_in', 'check_out', 'ساعات العمل', 'loc', 'proj', 'rep', 'photo']]
        final_df.columns = ['التاريخ', 'اليوم', 'اسم الموظف', 'القسم الأساسي', 'الحضور', 'الانصراف', 'ساعات العمل', 'موقع البصمة', 'المشاريع', 'التقارير اليومية', 'صورة الإثبات']
        
        st.success(f"✅ تم العثور على {len(final_df)} سجل دوام.")
        st.dataframe(final_df, use_container_width=True, hide_index=True, column_config={"صورة الإثبات": st.column_config.ImageColumn("صورة الإثبات")})
        
        csv_df = final_df.drop(columns=['صورة الإثبات'])
        
        total_mins = 0
        for val in csv_df['ساعات العمل']:
            if "⚠️" not in val and ":" in val:
                try:
                    parts = val.split(":")
                    total_mins += int(parts[0]) * 60 + int(parts[1])
                except:
                    pass
                    
        total_str = f"{total_mins // 60}:{(total_mins % 60):02d} ساعة"
        
        summary_row = pd.DataFrame([{
            'التاريخ': 'إجمالي الساعات',
            'اليوم': '',
            'اسم الموظف': '',
            'القسم الأساسي': '',
            'الحضور': '',
            'الانصراف': '',
            'ساعات العمل': total_str,
            'موقع البصمة': '',
            'المشاريع': '',
            'التقارير اليومية': ''
        }])
        
        csv_df_with_total = pd.concat([csv_df, summary_row], ignore_index=True)
        
        col_down1, col_down2 = st.columns(2)
        csv_data = csv_df_with_total.to_csv(index=False).encode('utf-8-sig')
        
        col_down1.download_button(
            "📥 تحميل كـ شيت (Excel/CSV)",
            data=csv_data,
            file_name=f"Attendance_{get_egypt_time().strftime('%Y%m%d')}.csv",
            mime='text/csv',
            use_container_width=True
        )
        
        html_report = generate_html_report("تقرير الحضور والانصراف التفصيلي - كيان الشرقية", csv_df_with_total)
        
        col_down2.download_button(
            "🖨️ تحميل للطباعة (رسمي PDF)",
            data=html_report,
            file_name=f"Attendance_{get_egypt_time().strftime('%Y%m%d')}.html",
            mime='text/html',
            type="primary",
            use_container_width=True
        )
    else:
        st.info("لا توجد سجلات تطابق خيارات البحث.")

def render_task_delegation(department):
    st.header("📋 إسناد مهام للموظفين (Task Delegation)")
    conn = get_db_connection()
    if department == "الكل":
        emps = pd.read_sql_query("SELECT emp_id, name FROM Employees ORDER BY name", conn)
    else:
        emps = pd.read_sql_query("SELECT emp_id, name FROM Employees WHERE department=%s OR secondary_department=%s ORDER BY name", conn, params=(department, department))
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
                log_event("إسناد مهمة", f"إلى: {selected_emp} - مشروع: {proj}")
                st.success("تم إسناد المهمة للموظف بنجاح!")
            else:
                st.error("يرجى كتابة تفاصيل المهمة وتحديد الموظف.")

def get_extract_blocker(status):
    blocker_map = {
        "قيد التجهيز": "مهندس المستخلصات (قيد التجهيز/يوجد معوقات)",
        "بانتظار اعتماد التخطيط": "إدارة التخطيط (للمراجعة والاعتماد)",
        "بانتظار الصرف": "إدارة الحسابات (جاهز للصرف)",
        "تم الصرف": "مكتمل وتم الصرف ✅",
        "مرفوض فنياً": "مرفوض - عاد لمهندس المستخلصات للتعديل",
        "مطلوب تعديلات": "عاد لمهندس المستخلصات للتعديل",
        "مرفوض": "مرفوض من الحسابات/الإدارة",
        "مراجعة نهائية": "عاد للمراجعة"
    }
    return blocker_map.get(status, status)

def render_manage_extracts():
    st.header("📄 إدارة ومراجعة المستخلصات الهندسية")
    conn = get_db_connection()
    current_role = st.session_state.get('current_role', st.session_state.get('role', ''))
    emp_id = st.session_state.get('emp_id')
    
    try:
        res = db_fetchone("SELECT department, secondary_department FROM Employees WHERE emp_id=%s", (emp_id,))
        if res:
            emp_dept = res[0]
            sec_dept = res[1]
        else:
            emp_dept = ""
            sec_dept = ""
    except:
        emp_dept = ""
        sec_dept = ""
        
    is_planning_auth = (current_role == 'planning_engineer') or ("مهندسين إدارة وتخطيط" in [emp_dept, sec_dept])

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
                    
                    if pd.notna(row['impediment_notes']) and str(row['impediment_notes']).strip() != "":
                        st.warning(f"**معوقات وملاحظات المهندس:** {row['impediment_notes']}")
                        
                    file_content = row['file_data']
                    if is_valid_file(file_content):
                        try:
                            decoded_bytes = base64.b64decode(file_content)
                            st.download_button("📥 تحميل المستخلص للمراجعة", data=decoded_bytes, file_name=f"{row['extract_name']}.pdf", mime="application/octet-stream", key=f"dl_mng_ext_{row['id']}")
                        except:
                            pass
                    else:
                        st.info("لا يوجد ملف مرفق.")
                    
                    c1, c2, c3 = st.columns(3)
                    if is_planning_auth:
                        if c1.button("✅ اعتماد فني وتحويل للحسابات", key=f"eng_app_{row['id']}", type="primary"):
                            db_execute("UPDATE Extracts SET status='بانتظار الصرف' WHERE id=%s", (row['id'],))
                            log_event("اعتماد مستخلص (تخطيط)", f"مستخلص: {row['extract_name']} - مشروع: {row['project_name']}")
                            st.rerun()
                        if c2.button("❌ إرجاع لوجود مشاكل فنية", key=f"eng_rej_{row['id']}"):
                            db_execute("UPDATE Extracts SET status='مرفوض فنياً' WHERE id=%s", (row['id'],))
                            log_event("رفض مستخلص (تخطيط)", f"مستخلص: {row['extract_name']} - مشروع: {row['project_name']}")
                            st.rerun()
                    else:
                        if row['status'] != 'تم الصرف':
                            if c1.button("✅ تم صرف المستخلص", key=f"pay_{row['id']}", type="primary"):
                                db_execute("UPDATE Extracts SET status='تم الصرف' WHERE id=%s", (row['id'],))
                                log_event("صرف مستخلص (حسابات)", f"مستخلص: {row['extract_name']} - مشروع: {row['project_name']}")
                                st.rerun()
                    if c3.button("🗑️ حذف المستخلص", key=f"del_ext_mng_{row['id']}"):
                        db_execute("DELETE FROM Extracts WHERE id=%s", (row['id'],))
                        log_event("حذف مستخلص", f"حذف المستخلص رقم {row['id']} ({row['extract_name']})")
                        st.rerun()
        else:
            st.info("لا يوجد مستخلصات في صندوق الوارد الخاص بإدارتك حالياً.")
    except Exception as e:
        st.warning(f"جاري تهيئة جداول المستخلصات. {e}")
        
    conn.close()

# ==========================================
# 4. الموديول المالي (أقساط الجهاز vs أقساط التنفيذ ومساهمات الملاك)
# ==========================================
def render_financials_module(can_edit=True):
    st.header("💰 إدارة الالتزامات المالية للمشاريع (الجهاز vs التنفيذ ومساهمات الملاك)")
    
    fin_tabs = st.tabs(["🏛️ أقساط الجهاز (التزامات الهيئة/الأرض)", "🏗️ أقساط التنفيذ ومساهمات الملاك"])
    
    with fin_tabs[0]:
        st.subheader("🏛️ متابعة وجدولة أقساط الجهاز")
        if can_edit:
            with st.form("add_device_inst"):
                c1, c2, c3 = st.columns(3)
                d_proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)], key="dev_proj")
                d_name = c2.text_input("بيان / رقم قسط الجهاز (مثال: القسط الثالث للأرض)")
                d_amt = c3.number_input("قيمة قسط الجهاز (جنيه)", min_value=0.0, step=1000.0)
                
                c4, c5, c6 = st.columns(3)
                d_due = c4.date_input("تاريخ استحقاق القسط")
                d_status = c5.selectbox("حالة السداد", ["مستحق (لم يُدفع)", "مدفوع", "متأخر"], key="dev_st")
                d_notes = c6.text_input("ملاحظات (رقم الشيك / إيصال السداد)")
                
                if st.form_submit_button("تسجيل قسط الجهاز 🏛️", type="primary"):
                    if d_name and d_amt > 0:
                        db_execute(
                            "INSERT INTO ProjectFinancials (project_name, installment_type, amount, due_date, status, category, shareholder_name, share_percentage, notes) VALUES (%s, %s, %s, %s, %s, 'قسط جهاز', 'الشركة', 100.0, %s)",
                            (d_proj, d_name, d_amt, d_due.strftime("%Y/%m/%d"), d_status, d_notes)
                        )
                        log_event("إضافة قسط جهاز", f"مشروع: {d_proj} - بيان: {d_name} - قيمة: {d_amt}")
                        st.success("تم تسجيل قسط الجهاز بنجاح!")
                        st.rerun()
                    else:
                        st.error("يرجى إدخال بيان القسط وقيمته.")
                        
        conn = get_db_connection()
        dev_df = pd.read_sql_query("SELECT id, project_name, installment_type, amount, due_date, status, notes FROM ProjectFinancials WHERE category = 'قسط جهاز' OR installment_type = 'قسط جهاز' ORDER BY due_date ASC", conn)
        conn.close()
        
        if not dev_df.empty:
            if can_edit:
                with st.expander("🔄 تحديث حالة أو حذف قسط جهاز"):
                    u_c1, u_c2, u_c3, u_c4 = st.columns(4)
                    dev_opts = dev_df['id'].astype(str) + " - " + dev_df['project_name'] + " (" + dev_df['installment_type'] + ")"
                    sel_dev = u_c1.selectbox("اختر القسط:", dev_opts)
                    new_dev_st = u_c2.selectbox("الحالة الجديدة:", ["مدفوع", "مستحق (لم يُدفع)", "متأخر"], key="upd_dev_st")
                    if u_c3.button("تحديث الحالة ✅", key="btn_upd_dev"):
                        dev_id = int(sel_dev.split(" - ")[0])
                        db_execute("UPDATE ProjectFinancials SET status=%s WHERE id=%s", (new_dev_st, dev_id))
                        log_event("تحديث قسط جهاز", f"تغيير حالة قسط رقم {dev_id} إلى {new_dev_st}")
                        st.success("تم التحديث!")
                        st.rerun()
                    if u_c4.button("🗑️ حذف القسط نهائياً", key="btn_del_dev"):
                        dev_id = int(sel_dev.split(" - ")[0])
                        db_execute("DELETE FROM ProjectFinancials WHERE id=%s", (dev_id,))
                        log_event("حذف قسط جهاز", f"حذف قسط جهاز رقم {dev_id}")
                        st.success("تم مسح القسط!")
                        st.rerun()
                        
            disp_dev = dev_df.drop(columns=['id'])
            disp_dev.columns = ['المشروع', 'بيان القسط', 'المبلغ', 'تاريخ الاستحقاق', 'الحالة', 'ملاحظات']
            st.dataframe(disp_dev, use_container_width=True, hide_index=True)
            
            html_dev = generate_html_report("تقرير التزامات وأقساط الجهاز - كيان الشرقية", disp_dev)
            st.download_button("🖨️ طباعة تقرير أقساط الجهاز (PDF)", data=html_dev, file_name="Device_Installments.html", mime="text/html")
        else:
            st.info("لا توجد أقساط جهاز مسجلة حالياً.")

    with fin_tabs[1]:
        st.subheader("🏗️ أقساط التنفيذ وحصص الملاك المساهمين")
        st.info("💡 في هذا القسم يتم تسجيل دفعات وأقساط التنفيذ المطلوبة لكل مشروع وتوزيعها على الملاك المساهمين لمعرفة التزام كل شريك/مالك.")
        
        if can_edit:
            with st.form("add_exec_inst"):
                c1, c2, c3 = st.columns(3)
                e_proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)], key="exec_proj")
                e_phase = c2.text_input("بند / مرحلة التنفيذ (مثال: دفعة صب سقف الأول)")
                e_sh_name = c3.text_input("اسم المالك المساهم / الشريك")
                
                c4, c5, c6 = st.columns(3)
                e_share_pct = c4.number_input("نسبة مساهمة المالك (%)", min_value=1.0, max_value=100.0, value=100.0, step=5.0)
                e_amt = c5.number_input("المبلغ المطلوب من المساهم (جنيه)", min_value=0.0, step=1000.0)
                e_due = c6.date_input("تاريخ استحقاق الدفعة")
                
                c7, c8 = st.columns(2)
                e_status = c7.selectbox("حالة سداد المساهم", ["مستحق (لم يُدفع)", "مدفوع", "متأخر"], key="exec_st")
                e_notes = c8.text_input("ملاحظات المساهمة")
                
                if st.form_submit_button("تسجيل دفعة التنفيذ ومساهمة المالك 🏗️", type="primary"):
                    if e_phase and e_sh_name and e_amt > 0:
                        db_execute(
                            "INSERT INTO ProjectFinancials (project_name, installment_type, amount, due_date, status, category, shareholder_name, share_percentage, notes) VALUES (%s, %s, %s, %s, %s, 'قسط تنفيذ', %s, %s, %s)",
                            (e_proj, e_phase, e_amt, e_due.strftime("%Y/%m/%d"), e_status, e_sh_name.strip(), e_share_pct, e_notes)
                        )
                        log_event("إضافة قسط تنفيذ ومساهمة مالك", f"مشروع: {e_proj} - المساهم: {e_sh_name} - المبلغ: {e_amt}")
                        st.success("تم تسجيل قسط التنفيذ وحصة المالك المساهم بنجاح!")
                        st.rerun()
                    else:
                        st.error("يرجى إدخال بند التنفيذ، اسم المالك المساهم، والمبلغ.")
                        
        conn = get_db_connection()
        exec_df = pd.read_sql_query("SELECT id, project_name, installment_type, shareholder_name, share_percentage, amount, due_date, status, notes FROM ProjectFinancials WHERE category = 'قسط تنفيذ' OR installment_type = 'قسط تنفيذ' ORDER BY due_date ASC", conn)
        conn.close()
        
        if not exec_df.empty:
            if can_edit:
                with st.expander("🔄 تحديث حالة أو حذف مساهمة مالك في التنفيذ"):
                    u_c1, u_c2, u_c3, u_c4 = st.columns(4)
                    exec_opts = exec_df['id'].astype(str) + " - " + exec_df['project_name'] + " | المساهم: " + exec_df['shareholder_name'].fillna('') + " (" + exec_df['installment_type'] + ")"
                    sel_exec = u_c1.selectbox("اختر دفعة المساهم:", exec_opts)
                    new_exec_st = u_c2.selectbox("الحالة الجديدة:", ["مدفوع", "مستحق (لم يُدفع)", "متأخر"], key="upd_exec_st")
                    if u_c3.button("تحديث سداد المساهم ✅", key="btn_upd_exec"):
                        exec_id = int(sel_exec.split(" - ")[0])
                        db_execute("UPDATE ProjectFinancials SET status=%s WHERE id=%s", (new_exec_st, exec_id))
                        log_event("تحديث سداد مساهمة تنفيذ", f"تغيير حالة دفعة رقم {exec_id} إلى {new_exec_st}")
                        st.success("تم التحديث!")
                        st.rerun()
                    if u_c4.button("🗑️ حذف الدفعة نهائياً", key="btn_del_exec"):
                        exec_id = int(sel_exec.split(" - ")[0])
                        db_execute("DELETE FROM ProjectFinancials WHERE id=%s", (exec_id,))
                        log_event("حذف دفعة تنفيذ", f"حذف دفعة تنفيذ رقم {exec_id}")
                        st.success("تم مسح الدفعة!")
                        st.rerun()
                        
            disp_exec = exec_df.drop(columns=['id'])
            disp_exec.columns = ['المشروع', 'بند التنفيذ', 'اسم المالك المساهم', 'نسبة المساهمة %', 'المبلغ المطلوب', 'تاريخ الاستحقاق', 'حالة السداد', 'ملاحظات']
            st.dataframe(disp_exec, use_container_width=True, hide_index=True)
            
            st.markdown("#### 📊 ملخص موقف الملاك المساهمين في أقساط التنفيذ")
            sh_summary = exec_df.groupby(['project_name', 'shareholder_name', 'status'])['amount'].sum().unstack(fill_value=0).reset_index()
            sh_summary.rename(columns={'project_name': 'المشروع', 'shareholder_name': 'اسم المالك المساهم'}, inplace=True)
            st.dataframe(sh_summary, use_container_width=True, hide_index=True)
            
            html_exec = generate_html_report("تقرير أقساط التنفيذ ومساهمات الملاك - كيان الشرقية", disp_exec)
            st.download_button("🖨️ طباعة تقرير أقساط التنفيذ والمساهمين (PDF)", data=html_exec, file_name="Execution_Shareholders.html", mime="text/html")
        else:
            st.info("لا توجد أقساط تنفيذ أو مساهمات ملاك مسجلة حالياً.")

# ==========================================
# 5. موديول العملاء الشامل (مع إمكانية الحذف والتراجع)
# ==========================================
def render_clients_and_crm_module(mode="view"):
    is_sales = (mode == "sales")
    is_accountant = (mode == "accountant")
    is_owner = (mode == "owner")
    can_delete = is_sales or is_accountant or is_owner
    
    st.header("👥 إدارة العملاء، جدولة الأقساط، التقييم، وكشف الحساب")
    
    crm_tabs = st.tabs([
        "📊 تقييم العميل وكشف الحساب (PDF)",
        "💸 جدولة ومتابعة أقساط العملاء", 
        "📇 سجل بيانات العملاء", 
        "🏢 الوحدات العقارية"
    ])
    
    conn = get_db_connection()
    try:
        clients_df = pd.read_sql_query("SELECT id, name, phone, national_id, address, notes FROM Clients ORDER BY name ASC", conn)
    except:
        clients_df = pd.DataFrame(columns=['id', 'name', 'phone', 'national_id', 'address', 'notes'])
        
    try:
        units_df = pd.read_sql_query("SELECT id, project_name, unit_code, status, client_name, total_price, notes FROM RealEstateUnits ORDER BY id DESC", conn)
    except:
        units_df = pd.DataFrame(columns=['id', 'project_name', 'unit_code', 'status', 'client_name', 'total_price', 'notes'])
        
    try:
        inst_df = pd.read_sql_query("SELECT id, unit_code, client_name, amount, due_date, paid_date, status, notes FROM UnitInstallments ORDER BY due_date ASC", conn)
    except:
        inst_df = pd.DataFrame(columns=['id', 'unit_code', 'client_name', 'amount', 'due_date', 'paid_date', 'status', 'notes'])
    conn.close()
    
    client_names_list = clients_df['name'].dropna().tolist() if not clients_df.empty else []

    with crm_tabs[0]:
        st.subheader("📊 التقييم الائتماني للعميل وإصدار كشف الحساب (Statement of Account)")
        
        all_known_clients = sorted(list(set(
            client_names_list + 
            (units_df['client_name'].dropna().unique().tolist() if not units_df.empty else []) +
            (inst_df['client_name'].dropna().unique().tolist() if not inst_df.empty else [])
        )))
        all_known_clients = [c for c in all_known_clients if str(c).strip() != ""]
        
        if not all_known_clients:
            st.info("يرجى تسجيل عملاء وأقساط أولاً لعرض التقييم وكشف الحساب.")
        else:
            selected_client_stmt = st.selectbox("👤 اختر العميل لعرض تقييمه وكشف حسابه المفصل:", all_known_clients)
            
            cl_info_row = clients_df[clients_df['name'] == selected_client_stmt] if not clients_df.empty else pd.DataFrame()
            cl_phone_val = cl_info_row.iloc[0]['phone'] if not cl_info_row.empty else "غير مسجل"
            
            cl_units = units_df[units_df['client_name'] == selected_client_stmt] if not units_df.empty else pd.DataFrame()
            cl_inst = inst_df[inst_df['client_name'] == selected_client_stmt] if not inst_df.empty else pd.DataFrame()
            
            total_contracts_val = cl_units['total_price'].fillna(0).sum() if not cl_units.empty else 0.0
            paid_inst_val = cl_inst[cl_inst['status'].isin(['مدفوع', 'مدفوع في الموعد', 'مدفوع متأخر'])]['amount'].fillna(0).sum() if not cl_inst.empty else 0.0
            unpaid_inst_val = cl_inst[cl_inst['status'].isin(['مستحق (لم يُدفع)', 'متأخر'])]['amount'].fillna(0).sum() if not cl_inst.empty else 0.0
            remaining_from_contract = max(0.0, total_contracts_val - paid_inst_val)
            
            badge_text, score_val, on_time_cnt, late_cnt = evaluate_client_commitment(cl_inst)
            
            st.markdown("---")
            if score_val >= 80:
                st.success(f"### تقييم التزام العميل: {badge_text}")
            elif score_val >= 50:
                st.warning(f"### تقييم التزام العميل: {badge_text}")
            else:
                st.error(f"### تقييم التزام العميل: {badge_text}")
                
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("💰 إجمالي قيمة التعاقدات", f"{total_contracts_val:,.2f} ج.م")
            m2.metric("✅ إجمالي المسدد", f"{paid_inst_val:,.2f} ج.م")
            m3.metric("⏳ المتبقي من التعاقد", f"{remaining_from_contract:,.2f} ج.م")
            m4.metric("📌 أقساط منتظمة / متأخرة", f"{on_time_cnt} منتظم | {late_cnt} متأخر")
            
            st.markdown("#### 🏢 الوحدات المتعاقد عليها:")
            if not cl_units.empty:
                u_view = cl_units[['project_name', 'unit_code', 'status', 'total_price', 'notes']].copy()
                u_view.columns = ['المشروع', 'كود الوحدة', 'الحالة', 'سعر الوحدة', 'ملاحظات']
                st.dataframe(u_view, use_container_width=True, hide_index=True)
            else:
                st.write("لا توجد وحدات مربوطة بهذا الاسم مباشرة.")
                
            st.markdown("#### 💸 جدول الأقساط والدفعات (كشف الحساب):")
            if not cl_inst.empty:
                stmt_table = cl_inst[['unit_code', 'notes', 'amount', 'due_date', 'paid_date', 'status']].copy()
                stmt_table.columns = ['الوحدة', 'البيان', 'قيمة القسط', 'تاريخ الاستحقاق', 'تاريخ السداد', 'حالة الدفع']
                
                total_stmt_row = pd.DataFrame([{
                    'الوحدة': 'الإجمالي',
                    'البيان': f'إجمالي المسدد: {paid_inst_val:,.2f} ج.م | غير مسدد: {unpaid_inst_val:,.2f} ج.م',
                    'قيمة القسط': cl_inst['amount'].fillna(0).sum(),
                    'تاريخ الاستحقاق': '',
                    'تاريخ السداد': '',
                    'حالة الدفع': badge_text
                }])
                stmt_table_with_total = pd.concat([stmt_table, total_stmt_row], ignore_index=True)
                st.dataframe(stmt_table_with_total, use_container_width=True, hide_index=True)
                
                extra_summary = f"""
                <div class="summary-box">
                    <div class="summary-item"><span>اسم العميل</span><strong>{selected_client_stmt}</strong></div>
                    <div class="summary-item"><span>رقم الهاتف</span><strong>{cl_phone_val}</strong></div>
                    <div class="summary-item"><span>إجمالي التعاقد</span><strong>{total_contracts_val:,.2f} ج.م</strong></div>
                    <div class="summary-item"><span>إجمالي المسدد</span><strong style="color:green;">{paid_inst_val:,.2f} ج.م</strong></div>
                    <div class="summary-item"><span>المتبقي</span><strong style="color:#b80000;">{remaining_from_contract:,.2f} ج.م</strong></div>
                    <div class="summary-item"><span>تقييم الالتزام</span><strong>{badge_text}</strong></div>
                </div>
                """
                
                html_stmt = generate_html_report(f"كشف حساب عميل تفصيلي - {selected_client_stmt}", stmt_table_with_total, extra_summary_html=extra_summary)
                st.download_button(
                    "🖨️ طباعة / تصدير كشف حساب العميل وتقييمه (PDF)",
                    data=html_stmt,
                    file_name=f"Client_Statement_{selected_client_stmt}_{get_egypt_time().strftime('%Y%m%d')}.html",
                    mime="text/html",
                    type="primary",
                    use_container_width=True
                )
            else:
                st.info("لا توجد أقساط مسجلة لهذا العميل لإصدار كشف الحساب.")

    with crm_tabs[1]:
        st.subheader("💸 جدولة أقساط العملاء ومتابعة السداد")
        sold_units = units_df[units_df['status'].isin(['مباعة', 'محجوزة'])] if not units_df.empty else pd.DataFrame()
        
        if is_sales:
            st.info("📝 **صلاحية خدمة العملاء:** يمكنك هنا إضافة وجدولة أقساط العميل بمواعيد استحقاقها، وستسمّع تلقائياً لدى قسم الحسابات لمتابعة التحصيل.")
            with st.form("add_client_installment"):
                c1, c2, c3 = st.columns(3)
                if not sold_units.empty:
                    u_opts = sold_units['unit_code'].fillna('') + " | " + sold_units['client_name'].fillna('')
                    sel_u_cl = c1.selectbox("اختر الوحدة والعميل", u_opts)
                elif client_names_list:
                    sel_u_cl = c1.selectbox("اختر العميل", client_names_list)
                else:
                    sel_u_cl = c1.text_input("كود الوحدة | اسم العميل")
                    
                i_amt = c2.number_input("قيمة القسط (جنيه)", min_value=0.0, step=1000.0)
                i_due = c3.date_input("تاريخ الاستحقاق")
                
                i_notes = st.text_input("بيان القسط (مثال: دفعة تعاقد / قسط ربع سنوي 1)")
                
                if st.form_submit_button("إضافة القسط وإرساله للحسابات ➕", type="primary"):
                    if i_amt > 0 and sel_u_cl:
                        if " | " in str(sel_u_cl):
                            parts = str(sel_u_cl).split(" | ")
                            u_code_val = parts[0].strip()
                            u_cl_val = parts[1].strip() if len(parts) > 1 else ""
                        else:
                            u_code_val = "وحدة عقارية"
                            u_cl_val = str(sel_u_cl).strip()
                            
                        db_execute(
                            "INSERT INTO UnitInstallments (unit_code, client_name, amount, due_date, paid_date, status, notes) VALUES (%s, %s, %s, %s, '', 'مستحق (لم يُدفع)', %s)",
                            (u_code_val, u_cl_val, i_amt, i_due.strftime("%Y/%m/%d"), i_notes)
                        )
                        log_event("جدولة قسط عميل (خدمة عملاء)", f"عميل: {u_cl_val} - وحدة: {u_code_val} - مبلغ: {i_amt}")
                        st.success("تم جدولة القسط بنجاح وسمّع في شاشة الحسابات لمتابعة التحصيل!")
                        st.rerun()
                    else:
                        st.error("يرجى تحديد العميل/الوحدة وإدخال قيمة القسط.")
        elif is_accountant:
            st.info("💼 **صلاحية الحسابات:** الأقساط المجدولة أدناه مضافة بواسطة خدمة العملاء. دورك هنا هو متابعة الدفع فقط وتحديد ما إذا كان العميل قد دفع أم لا.")

        if not inst_df.empty:
            inst_opts = inst_df['id'].astype(str) + " - العميل: " + inst_df['client_name'].fillna('') + " | وحدة: " + inst_df['unit_code'].fillna('') + " | مبلغ: " + inst_df['amount'].astype(str) + " (" + inst_df['due_date'].fillna('') + ")"
            
            if is_accountant:
                with st.expander("💳 متابعة السداد وتأكيد الدفع (خاص بالمحاسب فقط)", expanded=True):
                    up1, up2, up3 = st.columns(3)
                    sel_inst_to_upd = up1.selectbox("اختر القسط لتحديث حالة دفعه:", inst_opts)
                    new_inst_st = up2.selectbox("هل دفع العميل؟ اختر الحالة:", ["مدفوع في الموعد", "مدفوع متأخر", "مستحق (لم يُدفع)", "متأخر"])
                    if up3.button("تأكيد حالة الدفع ✅", type="primary"):
                        inst_id_val = int(sel_inst_to_upd.split(" - ")[0])
                        paid_dt_val = get_egypt_time().strftime("%Y/%m/%d") if "مدفوع" in new_inst_st else ""
                        db_execute("UPDATE UnitInstallments SET status=%s, paid_date=%s WHERE id=%s", (new_inst_st, paid_dt_val, inst_id_val))
                        log_event("تحديث دفع قسط عميل (حسابات)", f"تحديث قسط رقم {inst_id_val} إلى {new_inst_st}")
                        st.success("تم تحديث حالة الدفع وتحديث التقييم الائتماني للعميل!")
                        st.rerun()
                        
            if can_delete:
                with st.expander("🗑️ حذف قسط عميل (التراجع عن قسط مضاف بالخطأ)"):
                    del_c1, del_c2 = st.columns([3, 1])
                    sel_inst_del = del_c1.selectbox("اختر القسط المراد حذفه:", inst_opts, key="del_inst_sel")
                    if del_c2.button("حذف القسط 🗑️", key="btn_del_inst"):
                        inst_id_del = int(sel_inst_del.split(" - ")[0])
                        db_execute("DELETE FROM UnitInstallments WHERE id=%s", (inst_id_del,))
                        log_event("حذف قسط عميل", f"حذف القسط رقم {inst_id_del}")
                        st.success("تم مسح القسط بنجاح!")
                        st.rerun()
                        
            disp_inst = inst_df.drop(columns=['id'])
            disp_inst.columns = ['كود الوحدة', 'اسم العميل', 'قيمة القسط', 'تاريخ الاستحقاق', 'تاريخ السداد الفعلي', 'الحالة', 'بيان / ملاحظات']
            st.dataframe(disp_inst, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد أقساط مجدولة للعملاء بعد.")

    with crm_tabs[2]:
        st.subheader("📇 سجل بيانات العملاء")
        if is_sales:
            with st.form("add_client_form"):
                c1, c2 = st.columns(2)
                cl_name = c1.text_input("اسم العميل رباعي *")
                cl_phone = c2.text_input("رقم الهاتف / واتساب *")
                
                c3, c4 = st.columns(2)
                cl_nid = c3.text_input("الرقم القومي")
                cl_addr = c4.text_input("العنوان بالتفصيل")
                cl_notes = st.text_input("ملاحظات عن العميل")
                
                if st.form_submit_button("حفظ بيانات العميل 💾", type="primary"):
                    if cl_name.strip() and cl_phone.strip():
                        try:
                            existing = db_fetchone("SELECT id FROM Clients WHERE name=%s", (cl_name.strip(),))
                            if existing:
                                db_execute(
                                    "UPDATE Clients SET phone=%s, national_id=%s, address=%s, notes=%s WHERE id=%s",
                                    (cl_phone.strip(), cl_nid.strip(), cl_addr.strip(), cl_notes.strip(), existing[0])
                                )
                            else:
                                db_execute(
                                    "INSERT INTO Clients (name, phone, national_id, address, notes) VALUES (%s, %s, %s, %s, %s)",
                                    (cl_name.strip(), cl_phone.strip(), cl_nid.strip(), cl_addr.strip(), cl_notes.strip())
                                )
                            log_event("إضافة/تحديث عميل", f"العميل: {cl_name.strip()} - هاتف: {cl_phone.strip()}")
                            st.success(f"تم حفظ بيانات العميل ({cl_name}) بنجاح!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"حدث خطأ: {e}")
                    else:
                        st.error("يرجى إدخال اسم العميل ورقم الهاتف.")
                        
        if not clients_df.empty:
            if can_delete:
                with st.expander("🗑️ حذف عميل من السجل (مع إمكانية مسح وحداته وأقساطه)"):
                    dc1, dc2, dc3 = st.columns([2, 2, 1])
                    cl_del_opts = clients_df['id'].astype(str) + " - " + clients_df['name'].fillna('')
                    sel_cl_del = dc1.selectbox("اختر العميل المراد مسحه:", cl_del_opts, key="sel_cl_del")
                    cascade_del = dc2.checkbox("مسح جميع وحداته وأقساطه المرتبطة به أيضاً", value=True)
                    if dc3.button("حذف العميل 🗑️", key="btn_del_cl"):
                        cl_id_del = int(sel_cl_del.split(" - ")[0])
                        cl_name_del = sel_cl_del.split(" - ")[1].strip()
                        db_execute("DELETE FROM Clients WHERE id=%s", (cl_id_del,))
                        if cascade_del:
                            db_execute("DELETE FROM RealEstateUnits WHERE client_name=%s", (cl_name_del,))
                            db_execute("DELETE FROM UnitInstallments WHERE client_name=%s", (cl_name_del,))
                            db_execute("DELETE FROM Cheques WHERE client_name=%s", (cl_name_del,))
                        log_event("حذف عميل", f"تم مسح العميل: {cl_name_del}")
                        st.success(f"تم مسح العميل ({cl_name_del}) بنجاح!")
                        st.rerun()
                        
            disp_cl = clients_df.drop(columns=['id'])
            disp_cl.columns = ['اسم العميل', 'رقم الهاتف', 'الرقم القومي', 'العنوان', 'ملاحظات']
            st.dataframe(disp_cl, use_container_width=True, hide_index=True)
        else:
            st.info("لا يوجد عملاء مسجلين بعد.")

    with crm_tabs[3]:
        st.subheader("🏢 تسكين الوحدات وربطها بالعملاء")
        if is_sales:
            with st.form("add_unit_crm"):
                c1, c2, c3 = st.columns(3)
                u_proj = c1.selectbox("المشروع", [f"اتحاد {i}" for i in range(1, 46)])
                u_code = c2.text_input("رقم / كود الوحدة (مثال: شقة 301 - اتحاد 5)")
                u_status = c3.selectbox("حالة الوحدة", ["متاحة", "مباعة", "محجوزة"])
                
                c4, c5 = st.columns(2)
                if client_names_list:
                    u_client = c4.selectbox("اختر العميل المشتري (من سجل العملاء)", ["بدون عميل (متاحة)"] + client_names_list)
                else:
                    u_client = c4.text_input("اسم العميل (يفضل إضافته في سجل العملاء أولاً)")
                    
                u_price = c5.number_input("إجمالي سعر الوحدة (جنيه)", min_value=0.0, step=5000.0)
                u_notes = st.text_input("ملاحظات التعاقد")
                
                if st.form_submit_button("تسجيل / تحديث الوحدة 🏢", type="primary"):
                    if u_code.strip():
                        final_cl = "" if u_client == "بدون عميل (متاحة)" else u_client
                        db_execute(
                            "INSERT INTO RealEstateUnits (project_name, unit_code, status, client_name, total_price, notes) VALUES (%s, %s, %s, %s, %s, %s)",
                            (u_proj, u_code.strip(), u_status, final_cl, u_price, u_notes)
                        )
                        log_event("تسجيل وحدة عقارية", f"وحدة: {u_code} - مشروع: {u_proj} - عميل: {final_cl}")
                        st.success("تم حفظ بيانات الوحدة بنجاح!")
                        st.rerun()
                    else:
                        st.error("يرجى كتابة كود الوحدة.")
                        
        if not units_df.empty:
            if can_delete:
                with st.expander("🗑️ حذف وحدة عقارية (التراجع عن تسجيل وحدة)"):
                    du1, du2 = st.columns([3, 1])
                    u_del_opts = units_df['id'].astype(str) + " - " + units_df['unit_code'].fillna('') + " (" + units_df['project_name'].fillna('') + " | العميل: " + units_df['client_name'].fillna('') + ")"
                    sel_u_del = du1.selectbox("اختر الوحدة المراد مسحها:", u_del_opts, key="sel_u_del")
                    if du2.button("حذف الوحدة 🗑️", key="btn_del_u"):
                        u_id_del = int(sel_u_del.split(" - ")[0])
                        db_execute("DELETE FROM RealEstateUnits WHERE id=%s", (u_id_del,))
                        log_event("حذف وحدة عقارية", f"تم مسح الوحدة رقم {u_id_del}")
                        st.success("تم مسح بيانات الوحدة بنجاح!")
                        st.rerun()
                        
            disp_u = units_df.drop(columns=['id'])
            disp_u.columns = ['المشروع', 'كود الوحدة', 'الحالة', 'اسم العميل', 'إجمالي السعر', 'ملاحظات']
            st.dataframe(disp_u, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد وحدات مسجلة.")

# ==========================================
# 6. الشاشة المشتركة للموظفين (البصمة والتقارير والرصيد السنوي)
# ==========================================
def render_employee_dashboard(emp_id, balance):
    stats = get_employee_stats(emp_id)
    delay_mins = stats[1]
    overtime_mins = stats[3]
    
    today_date = get_egypt_time().strftime("%Y/%m/%d")
    current_year = get_egypt_time().strftime("%Y")
    now_dt = get_egypt_time()
    
    try:
        is_exempt = db_fetchone("SELECT exempt_report FROM Employees WHERE emp_id=%s", (emp_id,))
        is_exempt = is_exempt[0] if is_exempt and is_exempt[0] is not None else False
    except:
        is_exempt = False
        
    try:
        used_leaves_year = db_fetchone("SELECT COUNT(*) FROM Permissions WHERE emp_id=%s AND type='إجازة' AND date LIKE %s", (emp_id, f"{current_year}/%"))[0]
    except:
        used_leaves_year = 0
    
    try:
        has_checked_in = db_fetchone("SELECT COUNT(*) FROM WebAttendance WHERE emp_id=%s AND date=%s AND action='حضور'", (emp_id, today_date))[0] > 0
        if not has_checked_in and (now_dt.hour > 11 or (now_dt.hour == 11 and now_dt.minute >= 30)):
            st.error("⏰ **تنبيه عاجل:** لقد تجاوزت الساعة 11:30 صباحاً ولم تقم بتسجيل حضورك اليوم! يرجى إثبات الحضور فوراً لتجنب خصم اليوم.")
    except:
        pass

    try:
        pending_tasks = db_fetchone("SELECT COUNT(*) FROM Tasks WHERE emp_id=%s AND status='قيد التنفيذ'", (emp_id,))[0]
        if pending_tasks > 0:
            st.warning(f"🔔 **تنبيه عمل:** لديك ({pending_tasks}) مهمة مسندة بانتظار إنجازها! راجع قسم 'بصمة وتقارير'.")
    except:
        pass

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"رصيد الإجازات المتبقي ({current_year})", f"{balance} يوم", f"تم استنفاد {used_leaves_year} يوم هذا العام")
    c2.metric("التأخيرات الكلية", f"{format_hhmm(delay_mins)} ساعة")
    c3.metric("الوقت الإضافي", f"{format_hhmm(overtime_mins)} ساعة")
    
    try:
        pending = db_fetchone("SELECT COUNT(*) FROM Requests WHERE emp_id=%s AND status='قيد الانتظار'", (emp_id,))[0]
        c4.metric("طلبات معلقة", pending)
    except:
        c4.metric("طلبات معلقة", 0)
    
    st.divider()
    sub_nav = st.radio("العمليات المتاحة:", ["📍 بصمة وتقارير وإنجاز مهام", "📝 تقديم طلب جديد", "🌴 سجلاتي"], horizontal=True)
    
    if sub_nav == "📍 بصمة وتقارير وإنجاز مهام":
        locations = db_fetchall("SELECT name, lat, lon, radius FROM Locations ORDER BY name")
        if not locations:
            st.error("لم يتم تسجيل فروع أو مواقع للشركة بعد.")
        elif not GEO_AVAILABLE:
            st.error("مكتبة Location غير مثبتة.")
        else:
            loc = get_geolocation()
            if loc and isinstance(loc, dict) and 'coords' in loc:
                emp_lat = float(loc['coords']['latitude'])
                emp_lon = float(loc['coords']['longitude'])
                
                min_distance = float('inf')
                closest_loc_name = None
                is_allowed = False
                
                for l_name, l_lat, l_lon, l_rad in locations:
                    dist = haversine(l_lat, l_lon, emp_lat, emp_lon)
                    if dist < min_distance:
                        min_distance = dist
                        closest_loc_name = l_name
                        is_allowed = (dist <= l_rad)
                
                if is_allowed:
                    st.success(f"✅ أنت داخل نطاق: {closest_loc_name}")
                    camera_photo = st.camera_input("التقط صورة لإثبات الحضور أو الانصراف")
                    
                    if camera_photo:
                        img = Image.open(camera_photo)
                        img.thumbnail((300, 300))
                        buffered = io.BytesIO()
                        img.save(buffered, format="JPEG", quality=85)
                        photo_uri = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}"
                        
                        try:
                            has_checked_in = db_fetchone("SELECT COUNT(*) FROM WebAttendance WHERE emp_id=%s AND date=%s AND action='حضور'", (emp_id, today_date))[0] > 0
                        except:
                            has_checked_in = False

                        if not has_checked_in:
                            if st.button("🟢 تسجيل حضور اليوم", use_container_width=True):
                                db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo) VALUES (%s, %s, %s, 'حضور', %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri))
                                log_event("بصمة حضور", f"الموقع: {closest_loc_name}")
                                st.success("تم تسجيل الحضور بنجاح!")
                                st.rerun() 
                        else:
                            st.info("✅ تم تسجيل حضورك اليوم بنجاح.")
                            
                            conn = get_db_connection()
                            try:
                                tasks = pd.read_sql_query("SELECT id, assigner, project_name, task_desc, due_date FROM Tasks WHERE emp_id=%s AND status='قيد التنفيذ'", conn, params=(emp_id,))
                            except:
                                tasks = pd.DataFrame()
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
                                                log_event("إنجاز مهمة", f"مشروع: {row['project_name']}")
                                                st.success("تم الإغلاق وإرسال التقرير للمدير!")
                                                st.rerun()
                                            else:
                                                st.error("اكتب تقرير الإنجاز أولاً!")
                            
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
                                        log_event("رفع تقرير يومي", f"مشروع: {selected_proj}")
                                        st.success("تم حفظ إنجازك!")
                                    else:
                                        st.error("❌ عذراً، يجب كتابة التقرير اليومي أولاً!")
                            with c_btn2:
                                if st.button("🔴 تسجيل انصراف نهائي اليوم", use_container_width=True):
                                    if is_exempt or daily_rep.strip():
                                        db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'انصراف', %s, %s, %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri, selected_proj, daily_rep))
                                        log_event("بصمة انصراف", f"الموقع: {closest_loc_name} - مشروع: {selected_proj}")
                                        st.success("تم تسجيل الانصراف بنجاح!")
                                        st.rerun() 
                                    else:
                                        st.error("❌ عذراً، لا يمكنك تسجيل الانصراف بدون كتابة التقرير اليومي!")
                else:
                    st.error(f"❌ أنت خارج النطاق المسموح. أقرب موقع عمل لك هو ({closest_loc_name}) ويبعد عنك بمسافة {int(min_distance)} متر.")
            else:
                st.info("جاري تحديد موقعك الجغرافي... يرجى التأكد من تشغيل وتصريح الـ GPS للمتصفح.")

    elif sub_nav == "📝 تقديم طلب جديد":
        with st.form("emp_req"):
            req_type = st.selectbox("النوع", ["إجازة", "مأمورية", "إذن", "عمل من المنزل"])
            req_date = st.date_input("التاريخ")
            notes = st.text_input("السبب أو التفاصيل")
            
            if st.form_submit_button("إرسال الطلب", type="primary"):
                if req_type == "إجازة" and balance <= 0:
                    st.error("❌ عذراً، لقد استنفدت رصيد إجازاتك السنوية المتبقي بالكامل! يرجى مراجعة الـ HR.")
                else:
                    db_execute("INSERT INTO Requests (emp_id, date, req_type, notes, status) VALUES (%s, %s, %s, %s, 'قيد الانتظار')", (emp_id, req_date.strftime("%Y/%m/%d"), req_type, notes))
                    log_event("تقديم طلب إجازة/إذن", f"النوع: {req_type} - التاريخ: {req_date}")
                    st.success("تم إرسال الطلب لمديرك المباشر بنجاح.")
                
    elif sub_nav == "🌴 سجلاتي":
        conn = get_db_connection()
        try:
            df = pd.read_sql_query("SELECT id, date, req_type, status FROM Requests WHERE emp_id=%s ORDER BY id DESC", conn, params=(emp_id,))
        except:
            df = pd.DataFrame()
        conn.close()
        
        if not df.empty:
            pending_my_reqs = df[df['status'] == 'قيد الانتظار']
            if not pending_my_reqs.empty:
                with st.expander("🗑️ إلغاء طلب قيد الانتظار (التراجع عن طلب)"):
                    rc1, rc2 = st.columns([3, 1])
                    r_opts = pending_my_reqs['id'].astype(str) + " - " + pending_my_reqs['req_type'] + " (" + pending_my_reqs['date'] + ")"
                    sel_r_del = rc1.selectbox("اختر الطلب المراد إلغاؤه:", r_opts)
                    if rc2.button("إلغاء الطلب 🗑️"):
                        r_id_del = int(sel_r_del.split(" - ")[0])
                        db_execute("DELETE FROM Requests WHERE id=%s", (r_id_del,))
                        log_event("إلغاء طلب موظف", f"قام الموظف بإلغاء طلبه رقم {r_id_del}")
                        st.success("تم إلغاء الطلب بنجاح!")
                        st.rerun()
                        
            disp_r = df.drop(columns=['id'])
            disp_r.columns = ['التاريخ', 'نوع الطلب', 'الحالة']
            st.dataframe(disp_r, hide_index=True, use_container_width=True)
        else:
            st.info("لا توجد طلبات مسجلة لك حتى الآن.")
