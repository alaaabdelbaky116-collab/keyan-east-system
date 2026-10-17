import streamlit as st
import pandas as pd
from datetime import datetime
import base64
import os
from db import *
from modules import *

st.set_page_config(page_title="Keyan-East ERP System", page_icon="🏢", layout="wide")

# تهيئة الجداول والتصميم والتنظيف التلقائي أول الشهر
setup_database_v6()
ensure_shareholders_union_schema()
apply_custom_theme()
set_dynamic_background()

if 'logged_in' not in st.session_state:
    st.session_state.update({
        'logged_in': False,
        'role': None,
        'primary_role': None,
        'secondary_role': 'none',
        'current_role': None,
        'emp_id': None,
        'username': None
    })

def login_page():
    col1, col2, col3 = st.columns([1, 1.6, 1])
    with col2:
        try:
            if os.path.exists(LOGO_FILE):
                c_img1, c_img2, c_img3 = st.columns([1, 1.5, 1])
                with c_img2:
                    st.image(LOGO_FILE, use_container_width=True)
        except:
            pass
            
        st.markdown("<h2 style='text-align: center; color: #D4AF37;'>بوابة كيان الشرقية الرقمية (ERP)</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            user = st.text_input("اسم المستخدم / كود الموظف")
            pwd = st.text_input("كلمة المرور", type="password")
            if st.form_submit_button("تسجيل الدخول 🚀", use_container_width=True, type="primary"):
                auth_res = authenticate(user.strip(), pwd.strip())
                if auth_res:
                    p_role, s_role, e_id = auth_res
                    st.session_state.update({
                        'logged_in': True,
                        'role': p_role,
                        'primary_role': p_role,
                        'secondary_role': s_role if s_role else 'none',
                        'current_role': p_role,
                        'emp_id': e_id,
                        'username': user.strip()
                    })
                    log_event("تسجيل دخول", f"دخول ناجح بصلاحية: {p_role}")
                    st.rerun()
                else:
                    st.error("❌ اسم المستخدم أو كلمة المرور غير صحيحة!")

if not st.session_state['logged_in']:
    login_page()
else:
    role = st.session_state.get('current_role') or st.session_state.get('role')
    emp_id = st.session_state.get('emp_id')
    name, dept, balance = get_employee_info(emp_id)
    role_title = DISPLAY_MAP.get(role, role)

    render_sidebar(role_title)
    render_smart_alerts()

    # ==========================================
    # 1. لوحة المالك (Owner) أو مسؤول النظام (Admin)
    # ==========================================
    if role in ['owner', 'admin']:
        st.title(f"👑 لوحة القيادة العليا ({role_title})")
        nav_tabs = st.tabs([
            "🏠 لوحتي الشخصية (البصمة)",
            "📊 المؤشرات والأمان وتنظيف أول الشهر",
            "🤝 اتحاد الملاك والأرباع والأولوية",
            "💰 أقساط الجهاز والمالية",
            "📄 رادار المستخلصات الهندسية",
            "👥 الموظفين والـ HR والحضور",
            "⚙️ إعدادات النظام والـ Logs"
        ])
        
        with nav_tabs[0]:
            render_employee_dashboard(emp_id, balance)
        with nav_tabs[1]:
            render_company_dashboard()
        with nav_tabs[2]:
            render_clients_and_crm_module(mode="owner", key_prefix="own_crm_")
        with nav_tabs[3]:
            render_financials_module(can_edit=True)
        with nav_tabs[4]:
            render_manage_extracts()
        with nav_tabs[5]:
            hr_sub = st.tabs(["📸 سجل الحضور والانصراف", "🌴 أرصدة الإجازات السنوية", "🛡️ إعفاء التقارير اليومية", "📋 إسناد المهام"])
            with hr_sub[0]:
                render_attendance_report()
            with hr_sub[1]:
                render_leave_balance_management()
            with hr_sub[2]:
                render_department_exemption_manager("الكل")
            with hr_sub[3]:
                render_task_delegation("الكل")
        with nav_tabs[6]:
            render_security_and_backup_center()
            st.divider()
            st.subheader("🕵️ سجل مراقبة العمليات (Audit Logs)")
            conn = get_db_connection()
            logs_df = pd.read_sql_query("SELECT log_time AS \"التوقيت\", username AS \"المستخدم\", role AS \"الصلاحية\", action_type AS \"العملية\", details AS \"التفاصيل\" FROM AuditLogs ORDER BY id DESC LIMIT 300", conn)
            conn.close()
            st.dataframe(logs_df, use_container_width=True, hide_index=True)

    # ==========================================
    # 2. لوحة خدمة العملاء والمبيعات (اتحاد الملاك)
    # ==========================================
    elif role == 'sales':
        st.title("🤝 إدارة اتحاد الملاك المساهمين وخدمة العملاء")
        tabs = st.tabs(["🏠 لوحتي الشخصية (البصمة)", "🤝 منظومة اتحاد الملاك والأرباع والأولوية"])
        with tabs[0]:
            render_employee_dashboard(emp_id, balance)
        with tabs[1]:
            render_clients_and_crm_module(mode="sales", key_prefix="sales_")

    # ==========================================
    # 3. لوحة الحسابات والمالية (Accountant)
    # ==========================================
    elif role == 'accountant':
        st.title("💰 الإدارة المالية والحسابات")
        tabs = st.tabs([
            "🏠 لوحتي الشخصية (البصمة)",
            "🤝 حسابات اتحاد الملاك والأرباع الـ 4",
            "🏛️ أقساط الجهاز والالتزامات",
            "📄 صرف المستخلصات المعتمدة"
        ])
        with tabs[0]:
            render_employee_dashboard(emp_id, balance)
        with tabs[1]:
            render_clients_and_crm_module(mode="accountant", key_prefix="acc_")
        with tabs[2]:
            render_financials_module(can_edit=True)
        with tabs[3]:
            render_manage_extracts()

    # ==========================================
    # 4. لوحة الشؤون القانونية (Legal)
    # ==========================================
    elif role == 'legal':
        st.title("⚖️ إدارة العقود والشؤون القانونية")
        tabs = st.tabs(["🏠 لوحتي الشخصية (البصمة)", "⚖️ متابعة المتأخرات واتحاد الملاك"])
        with tabs[0]:
            render_employee_dashboard(emp_id, balance)
        with tabs[1]:
            render_clients_and_crm_module(mode="legal", key_prefix="leg_")

    # ==========================================
    # 5. لوحة الموارد البشرية (HR) أو المدير الإداري
    # ==========================================
    elif role in ['hr', 'admin_manager']:
        st.title("👥 إدارة الموارد البشرية والشؤون الإدارية")
        tabs = st.tabs([
            "🏠 لوحتي الشخصية (البصمة)",
            "📸 تقارير الحضور والانصراف",
            "🌴 إدارة أرصدة الإجازات السنوية",
            "📤 رفع شيت البصمة الشهري"
        ])
        with tabs[0]:
            render_employee_dashboard(emp_id, balance)
        with tabs[1]:
            render_attendance_report()
        with tabs[2]:
            render_leave_balance_management()
        with tabs[3]:
            uploaded_xl = st.file_uploader("اختر ملف إكسيل البصمة", type=['xls', 'xlsx'])
            if uploaded_xl and st.button("تحليل وحفظ البيانات ⚙️", type="primary"):
                res_df = process_excel(uploaded_xl)
                if not res_df.empty:
                    st.dataframe(res_df, use_container_width=True, hide_index=True)

    # ==========================================
    # 6. لوحة رؤساء الأقسام والمهندسين وبقية الموظفين
    # ==========================================
    elif role in ['manager', 'planning_engineer', 'extracts_engineer', 'engineer', 'licensing', 'it']:
        st.title(f"🛠️ لوحة عمل: {name} ({role_title})")
        tabs = st.tabs([
            "🏠 لوحتي الشخصية (البصمة)",
            "📄 المستخلصات الهندسية",
            "📸 حضور قسمي",
            "🛡️ إعفاء موظفي قسمي من التقرير",
            "📋 إسناد مهام لقسمي"
        ])
        with tabs[0]:
            render_employee_dashboard(emp_id, balance)
        with tabs[1]:
            render_manage_extracts()
        with tabs[2]:
            render_attendance_report(department_filter=dept if role == 'manager' else None)
        with tabs[3]:
            render_department_exemption_manager(department_filter=dept if role == 'manager' else "الكل")
        with tabs[4]:
            render_task_delegation(department=dept if role == 'manager' else "الكل")

    else:
        st.title(f"👋 مرحباً بك: {name}")
        render_employee_dashboard(emp_id, balance)
