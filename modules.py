import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import base64
from PIL import Image
import io
import os
import pytz
import plotly.express as px
import hashlib
import zipfile
from db import *

try:
    from streamlit_js_eval import get_geolocation
    GEO_AVAILABLE = True
except ImportError:
    GEO_AVAILABLE = False

# ==========================================
# 0. تهيئة جداول اتحاد الملاك والتنظيف التلقائي أول الشهر
# ==========================================
SUPABASE_FREE_LIMIT_MB = 500.0

if 'CURRENCY_OPTIONS' not in globals():
    CURRENCY_OPTIONS = [
        "ج.م (EGP)", 
        "دولار (USD)", 
        "ريال سعودي (SAR)", 
        "درهم إماراتي (AED)", 
        "يورو (EUR)"
    ]

QUARTER_OPTIONS = [
    "الربع الأول (Q1)",
    "الربع الثاني (Q2)",
    "الربع الثالث (Q3)",
    "الربع الرابع (Q4)",
    "دفعة أرض / تأسيس"
]

@st.cache_resource
def ensure_shareholders_union_schema():
    try:
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute('''CREATE TABLE IF NOT EXISTS SystemMeta (
            meta_key TEXT PRIMARY KEY,
            meta_value TEXT
        )''')

        cur.execute('''CREATE TABLE IF NOT EXISTS Shareholders (
            id SERIAL PRIMARY KEY,
            name TEXT,
            phone TEXT,
            national_id TEXT,
            address TEXT,
            project_name TEXT,
            land_share_pct REAL DEFAULT 0.0,
            land_share_amount REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'ج.م (EGP)',
            assigned_unit TEXT DEFAULT 'لم يخصص بعد',
            notes TEXT
        )''')

        cur.execute('''CREATE TABLE IF NOT EXISTS QuarterSplitRequests (
            id SERIAL PRIMARY KEY,
            installment_id INTEGER,
            project_name TEXT,
            shareholder_name TEXT,
            phase_name TEXT,
            quarter_name TEXT,
            original_amount REAL,
            currency TEXT DEFAULT 'ج.م (EGP)',
            split_count INTEGER DEFAULT 2,
            reason TEXT,
            requested_by TEXT,
            request_date TEXT,
            status TEXT DEFAULT 'بانتظار موافقة المالك',
            owner_notes TEXT DEFAULT ''
        )''')

        alter_stmts = [
            "ALTER TABLE UnitInstallments ADD COLUMN project_name TEXT DEFAULT 'اتحاد 1'",
            "ALTER TABLE UnitInstallments ADD COLUMN phase_name TEXT DEFAULT 'مرحلة تنفيذ'",
            "ALTER TABLE UnitInstallments ADD COLUMN quarter_name TEXT DEFAULT 'الربع الأول (Q1)'",
            "ALTER TABLE UnitInstallments ADD COLUMN currency TEXT DEFAULT 'ج.م (EGP)'",
            "ALTER TABLE UnitInstallments ADD COLUMN is_split_exception BOOLEAN DEFAULT FALSE",
            "ALTER TABLE ProjectFinancials ADD COLUMN quarter_name TEXT DEFAULT 'الربع الأول (Q1)'",
            "ALTER TABLE ProjectFinancials ADD COLUMN currency TEXT DEFAULT 'ج.م (EGP)'"
        ]
        for q in alter_stmts:
            try:
                cur.execute(q)
            except:
                pass

        cur.close()
        conn.close()
        return True
    except Exception:
        return False

def cleanup_previous_months_photos(is_auto=False):
    """مسح صور كاميرا البصمة للشهور السابقة فقط مع الحفاظ الكامل على سجلات وتواريخ الحضور والتقارير"""
    now_eg = get_egypt_time()
    first_day_current_month = now_eg.strftime("%Y/%m") + "/01"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE WebAttendance SET photo='' WHERE date < %s AND photo IS NOT NULL AND photo != ''",
        (first_day_current_month,)
    )
    deleted_count = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    mode_str = "تلقائي أول الشهر" if is_auto else "يدوي بواسطة الإدارة"
    if deleted_count > 0 or not is_auto:
        log_event("تنظيف صور البصمة الشهرية", f"({mode_str}) تم مسح صور {deleted_count} سجل أقدم من {first_day_current_month}")
    return deleted_count, first_day_current_month

def run_auto_monthly_photo_cleanup():
    """يعمل تلقائياً مع بداية كل شهر جديد لتفريغ صور الشهور السابقة"""
    try:
        ensure_shareholders_union_schema()
        current_month_tag = get_egypt_time().strftime("%Y/%m")
        res = db_fetchone("SELECT meta_value FROM SystemMeta WHERE meta_key='last_photo_cleanup_month'")
        last_cleaned = res[0] if res else ""
        if last_cleaned != current_month_tag:
            cleanup_previous_months_photos(is_auto=True)
            db_execute(
                "INSERT INTO SystemMeta (meta_key, meta_value) VALUES ('last_photo_cleanup_month', %s) ON CONFLICT (meta_key) DO UPDATE SET meta_value=EXCLUDED.meta_value",
                (current_month_tag,)
            )
    except Exception:
        pass

def get_database_size_info_safe():
    try:
        if 'get_database_size_info' in globals():
            return get_database_size_info()
        res = db_fetchone("SELECT pg_database_size(current_database())")
        size_bytes = float(res[0]) if res and res[0] else 0.0
        size_mb = round(size_bytes / (1024 * 1024), 2)
        pct = round(min(100.0, (size_mb / SUPABASE_FREE_LIMIT_MB) * 100.0), 1)
        return size_mb, pct, pd.DataFrame()
    except Exception:
        return 0.0, 0.0, pd.DataFrame()

def generate_full_backup_safe():
    conn = get_db_connection()
    tables_to_export = {
        "الملاك_المساهمين_Shareholders": "SELECT * FROM Shareholders ORDER BY id DESC",
        "أرباع_التنفيذ_Installments": "SELECT * FROM UnitInstallments ORDER BY id DESC",
        "استثناءات_التقسيم_Splits": "SELECT * FROM QuarterSplitRequests ORDER BY id DESC",
        "أقساط_الجهاز_والمالية": "SELECT * FROM ProjectFinancials ORDER BY id DESC",
        "الموظفين_Employees": "SELECT emp_id, name, department, secondary_department, annual_balance, phone, exempt_report FROM Employees ORDER BY emp_id",
        "سجل_الحضور_Attendance": "SELECT id, emp_id, date, time, action, distance, location_name, project_name, daily_report FROM WebAttendance ORDER BY id DESC",
        "المستخلصات_Extracts": "SELECT id, project_name, extract_name, amount, date, created_by, status, impediment_notes FROM Extracts ORDER BY id DESC",
        "سجل_المراقبة_AuditLogs": "SELECT * FROM AuditLogs ORDER BY id DESC LIMIT 2000"
    }
    dfs = {}
    for s_name, q in tables_to_export.items():
        try:
            dfs[s_name] = pd.read_sql_query(q, conn)
        except Exception:
            dfs[s_name] = pd.DataFrame()
    conn.close()

    try:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            for s_name, df in dfs.items():
                df.to_excel(writer, sheet_name=s_name[:31], index=False)
        buf.seek(0)
        return buf.getvalue(), f"Keyan_Backup_{get_egypt_time().strftime('%Y%m%d_%H%M')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception:
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
            for s_name, df in dfs.items():
                zf.writestr(f"{s_name}.csv", df.to_csv(index=False).encode('utf-8-sig'))
        zbuf.seek(0)
        return zbuf.getvalue(), f"Keyan_Backup_{get_egypt_time().strftime('%Y%m%d_%H%M')}.zip", "application/zip"

# ==========================================
# 1. التصميم العام والشريط الجانبي ومركز الأمان والتنبيهات
# ==========================================
def apply_custom_theme():
    run_auto_monthly_photo_cleanup()
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

def render_security_and_backup_center():
    active_role = st.session_state.get('current_role') or st.session_state.get('role')
    if active_role not in ['owner', 'admin']:
        st.warning("🔒 هذه اللوحة مخصصة للمالك (Owner) ومسؤول النظام (Admin) فقط.")
        return

    st.subheader("🛡️ مركز الأمان والنسخ الاحتياطي وتنظيف مساحة السيرفر (للمالك والأدمن فقط)")
    used_mb, used_pct, tables_df = get_database_size_info_safe()
    remaining_mb = max(0.0, SUPABASE_FREE_LIMIT_MB - used_mb)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💾 المساحة المستهلكة حالياً", f"{used_mb} MB", f"{used_pct}% من الباقة المجانية")
    c2.metric("🟢 المساحة المتبقية (من 500 MB)", f"{remaining_mb:.2f} MB")
    c3.metric("🗓️ التنظيف التلقائي أول الشهر", "مفعّل آلياً ✅")
    
    st.progress(min(1.0, used_pct / 100.0), text=f"نسبة استهلاك قاعدة بيانات Supabase: {used_mb} ميجابايت من أصل 500 ميجابايت ({used_pct}%)")

    st.markdown("---")
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        st.markdown("##### 🗓️ تنظيف صور البصمة الشهري (صلاحية المالك والأدمن)")
        st.caption("يقوم النظام تلقائياً يوم 1 من كل شهر بمسح صور كاميرا الشهور السابقة مع بقاء جميع سجلات وتواريخ الحضور والتقارير اليومية، ويمكنك تشغيله يدوياً الآن:")
        if st.button("🗓️ مسح صور الشهور السابقة (تنظيف أول الشهر)", key="btn_monthly_cln_main", type="primary", use_container_width=True):
            del_cnt, cutoff_dt = cleanup_previous_months_photos(is_auto=False)
            st.success(f"✅ تم مسح صور الكاميرا لعدد ({del_cnt}) سجل أقدم من ({cutoff_dt}) بنجاح مع الاحتفاظ الكامل بسجلات الحضور والتقارير!")
            st.rerun()

    with col_b2:
        st.markdown("##### 📦 النسخة الاحتياطية الشاملة (Excel Backup)")
        st.caption("تحميل جميع جداول الملاك المساهمين، الأرباع، المالية، والحضور في ملف Excel واحد.")
        if st.button("⚙️ تجهيز ملف النسخة الاحتياطية الآن", key="prep_bk_main", use_container_width=True):
            with st.spinner("جاري تجميع كافة جداول الشركة..."):
                bk_bytes, bk_filename, bk_mime = generate_full_backup_safe()
                st.session_state['ready_backup_data'] = (bk_bytes, bk_filename, bk_mime)
        if 'ready_backup_data' in st.session_state:
            b_bytes, b_name, b_mime = st.session_state['ready_backup_data']
            st.download_button(
                label=f"📥 اضغط لتحميل ({b_name})",
                data=b_bytes,
                file_name=b_name,
                mime=b_mime,
                type="primary",
                use_container_width=True,
                key="dl_bk_main"
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
                        pwd_to_save = hash_password(new_pwd) if 'hash_password' in globals() else new_pwd
                        db_execute("UPDATE Users SET password=%s WHERE username=%s", (pwd_to_save, st.session_state['username']))
                        log_event("تغيير كلمة المرور", "قام المستخدم بتحديث كلمة المرور الخاصة به")
                        st.success("تم التغيير بنجاح! احتفظ بها.")
                    else:
                        st.error("كلمة المرور قصيرة جداً.")

        # يظهر للمالك (owner) والأدمن (admin) فقط حسب الطلب
        active_role = st.session_state.get('current_role') or st.session_state.get('role')
        if active_role in ['owner', 'admin']:
            with st.expander("🛡️ المساحة وتنظيف أول الشهر (للمالك والأدمن)"):
                used_mb, used_pct, _ = get_database_size_info_safe()
                st.caption(f"💾 مساحة Supabase: **{used_mb} MB** / 500 MB ({used_pct}%)")
                st.progress(min(1.0, used_pct / 100.0))
                
                if st.button("🗓️ مسح صور الشهور السابقة (تنظيف أول الشهر)", key="sb_monthly_cln", type="primary", use_container_width=True):
                    del_cnt, cutoff_dt = cleanup_previous_months_photos(is_auto=False)
                    st.success(f"تم مسح صور ({del_cnt}) سجل أقدم من {cutoff_dt}!")
                    
                if st.button("📦 تجهيز نسخة احتياطية (Excel)", key="sb_prep_bk", use_container_width=True):
                    bk_bytes, bk_filename, bk_mime = generate_full_backup_safe()
                    st.session_state['sb_backup_data'] = (bk_bytes, bk_filename, bk_mime)
                if 'sb_backup_data' in st.session_state:
                    sb_bytes, sb_name, sb_mime = st.session_state['sb_backup_data']
                    st.download_button(
                        label="📥 تحميل النسخة الاحتياطية الآن",
                        data=sb_bytes,
                        file_name=sb_name,
                        mime=sb_mime,
                        use_container_width=True,
                        key="sb_dl_bk"
                    )
                        
        st.divider()
        if st.button("🚪 تسجيل الخروج", use_container_width=True):
            log_event("تسجيل خروج", "خروج من النظام")
            st.session_state['logged_in'] = False
            st.rerun()

def render_smart_alerts():
    ensure_shareholders_union_schema()
    conn = get_db_connection()
    today = get_egypt_time()
    alerts = []

    try:
        esc_owner_df = pd.read_sql_query("SELECT client_name, project_name, quarter_name, amount, COALESCE(currency, 'ج.م (EGP)') as currency FROM UnitInstallments WHERE collection_stage = 'محول للمالك (لتدخل الإدارة العليا)' AND status NOT IN ('مدفوع', 'مدفوع في الموعد', 'مدفوع متأخر', 'ملغي (تم تقسيم الربع)')", conn)
        for _, row in esc_owner_df.iterrows():
            alerts.append(f"🚨 **تدخل المالك عاجل:** المساهم ({row['client_name']}) في ({row['project_name']} - {row['quarter_name']}) متأخر في سداد ({row['amount']:,.0f} {row['currency']}) وتم تصعيده للمالك!")
    except:
        pass

    try:
        split_pending = pd.read_sql_query("SELECT shareholder_name, project_name, quarter_name, split_count, original_amount, currency FROM QuarterSplitRequests WHERE status = 'بانتظار موافقة المالك'", conn)
        for _, row in split_pending.iterrows():
            alerts.append(f"👑 **طلب استثناء تقسيم ربع تنفيذ:** المساهم ({row['shareholder_name']} - {row['project_name']}) يطلب استثناء لتقسيم ({row['quarter_name']}) بقيمة ({row['original_amount']:,.0f} {row['currency']}) على ({row['split_count']} دفعات) بانتظار موافقة المالك!")
    except:
        pass

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
                elif '👑' in alert:
                    st.info(alert)
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
    
    active_role = st.session_state.get('current_role') or st.session_state.get('role')
    if active_role in ['owner', 'admin']:
        with st.expander("🛡️ مركز الأمان والنسخ الاحتياطي وتنظيف صور البصمة الشهري (للمالك والأدمن)", expanded=False):
            render_security_and_backup_center()

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
        st.subheader("💰 الموقف المالي لأرباع التنفيذ وأقساط الجهاز")
        fin_df = pd.read_sql_query("SELECT status AS \"الحالة\", SUM(amount) AS \"الإجمالي\" FROM UnitInstallments GROUP BY status", conn)
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
# 4. الموديول المالي (أقساط الجهاز + ملخص أرباع التنفيذ للمساهمين)
# ==========================================
def render_financials_module(can_edit=True):
    ensure_shareholders_union_schema()
    st.header("💰 إدارة الالتزامات المالية للمشاريع (أقساط الجهاز وأرباع التنفيذ للمساهمين)")
    
    fin_tabs = st.tabs([
        "🏛️ أقساط الجهاز (التزامات الهيئة/الأرض)", 
        "🏗️ إدارة أرباع التنفيذ الـ 4 ومساهمات اتحاد الملاك"
    ])
    
    with fin_tabs[0]:
        st.subheader("🏛️ متابعة وجدولة أقساط الجهاز")
        if can_edit:
            with st.form("add_device_inst"):
                c1, c2, c3, c4 = st.columns(4)
                d_proj = c1.selectbox("المشروع (الاتحاد)", [f"اتحاد {i}" for i in range(1, 46)], key="dev_proj")
                d_name = c2.text_input("بيان / رقم قسط الجهاز (مثال: القسط الثالث للأرض)")
                d_amt = c3.number_input("قيمة قسط الجهاز", min_value=0.0, step=1000.0)
                d_curr = c4.selectbox("العملة", CURRENCY_OPTIONS, key="dev_curr")
                
                c5, c6, c7 = st.columns(3)
                d_due = c5.date_input("تاريخ استحقاق القسط")
                d_status = c6.selectbox("حالة السداد", ["مستحق (لم يُدفع)", "مدفوع", "متأخر"], key="dev_st")
                d_notes = c7.text_input("ملاحظات (رقم الشيك / إيصال السداد)")
                
                if st.form_submit_button("تسجيل قسط الجهاز 🏛️", type="primary"):
                    if d_name and d_amt > 0:
                        db_execute(
                            "INSERT INTO ProjectFinancials (project_name, installment_type, amount, currency, due_date, status, category, shareholder_name, share_percentage, notes) VALUES (%s, %s, %s, %s, %s, %s, 'قسط جهاز', 'الشركة', 100.0, %s)",
                            (d_proj, d_name, d_amt, d_curr, d_due.strftime("%Y/%m/%d"), d_status, d_notes)
                        )
                        log_event("إضافة قسط جهاز", f"مشروع: {d_proj} - بيان: {d_name} - قيمة: {d_amt} {d_curr}")
                        st.success("تم تسجيل قسط الجهاز بنجاح!")
                        st.rerun()
                    else:
                        st.error("يرجى إدخال بيان القسط وقيمته.")
                        
        conn = get_db_connection()
        dev_df = pd.read_sql_query("SELECT id, project_name, installment_type, amount, COALESCE(currency, 'ج.م (EGP)') as currency, due_date, status, notes FROM ProjectFinancials WHERE category = 'قسط جهاز' OR installment_type = 'قسط جهاز' ORDER BY due_date ASC", conn)
        conn.close()
        
        if not dev_df.empty:
            if can_edit:
                with st.expander("🔄 تحديث حالة أو حذف قسط جهاز"):
                    u_c1, u_c2, u_c3, u_c4 = st.columns(4)
                    dev_opts = dev_df['id'].astype(str) + " - " + dev_df['project_name'] + " (" + dev_df['installment_type'] + " - " + dev_df['amount'].astype(str) + " " + dev_df['currency'] + ")"
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
            disp_dev.columns = ['المشروع', 'بيان القسط', 'المبلغ', 'العملة', 'تاريخ الاستحقاق', 'الحالة', 'ملاحظات']
            st.dataframe(disp_dev, use_container_width=True, hide_index=True)
            
            html_dev = generate_html_report("تقرير التزامات وأقساط الجهاز - كيان الشرقية", disp_dev)
            st.download_button("🖨️ طباعة تقرير أقساط الجهاز (PDF)", data=html_dev, file_name="Device_Installments.html", mime="text/html")
        else:
            st.info("لا توجد أقساط جهاز مسجلة حالياً.")

    with fin_tabs[1]:
        active_role = st.session_state.get('current_role') or st.session_state.get('role')
        mode_to_pass = "owner" if active_role in ["owner", "admin"] else ("accountant" if can_edit else "view")
        render_clients_and_crm_module(mode=mode_to_pass, key_prefix="fin_")

# ==========================================
# 5. نظام استثناء المالك لتقسيم ربع التنفيذ (على دفعتين أو 3)
# ==========================================
def render_quarter_split_exception_module(mode="sales", key_prefix=""):
    ensure_shareholders_union_schema()
    is_owner = (mode == "owner")
    can_request = mode in ["sales", "accountant", "legal", "owner"]
    
    st.subheader("👑 استثناء المالك لتقسيم ربع التنفيذ (على دفعتين أو 3 دفعات)")
    st.info("💡 **القاعدة الأساسية:** يسدد المالك المساهم تكلفة الربع كاملة مرة واحدة. في حال رغبة المساهم في تقسيم الربع على **دفعتين (مرحلتين)** أو **3 دفعات**، يتم رفع طلب استثناء هنا ولا يتم تقسيم الربع في حسابه إلا بعد **موافقة مالك الشركة (Owner)**.")
    
    conn = get_db_connection()
    try:
        unpaid_q_df = pd.read_sql_query("""
            SELECT id, COALESCE(project_name, unit_code) as project_name, client_name, 
                   COALESCE(phase_name, 'مرحلة تنفيذ') as phase_name, 
                   COALESCE(quarter_name, notes) as quarter_name, 
                   amount, COALESCE(currency, 'ج.م (EGP)') as currency, due_date, status 
            FROM UnitInstallments 
            WHERE status IN ('مستحق (لم يُدفع)', 'متأخر') 
              AND (is_split_exception IS NULL OR is_split_exception = FALSE)
            ORDER BY id DESC
        """, conn)
    except Exception:
        unpaid_q_df = pd.DataFrame()
        
    try:
        split_reqs_df = pd.read_sql_query("SELECT * FROM QuarterSplitRequests ORDER BY id DESC", conn)
    except Exception:
        split_reqs_df = pd.DataFrame()
    conn.close()

    # 1. قسم اعتماد مالك الشركة (Owner Only)
    if is_owner and not split_reqs_df.empty:
        pending_splits = split_reqs_df[split_reqs_df['status'] == 'بانتظار موافقة المالك']
        if not pending_splits.empty:
            st.warning(f"🔔 لديك ({len(pending_splits)}) طلب استثناء لتقسيم ربع تنفيذ بانتظار موافقتك كمالك للشركة!")
            for _, s_row in pending_splits.iterrows():
                curr_v = s_row['currency'] or 'ج.م (EGP)'
                split_n = int(s_row['split_count'])
                part_val = float(s_row['original_amount']) / split_n
                with st.expander(f"👑 طلب استثناء: المساهم ({s_row['shareholder_name']}) | {s_row['project_name']} - {s_row['quarter_name']} | تقسيم ({s_row['original_amount']:,.2f} {curr_v}) على ({split_n} دفعات)", expanded=True):
                    st.write(f"**المرحلة:** {s_row['phase_name']} | **الربع:** {s_row['quarter_name']} | **قيمة كل دفعة بعد التقسيم:** `{part_val:,.2f} {curr_v}`")
                    st.write(f"**سبب طلب الاستثناء:** {s_row['reason']} | **مقدم الطلب:** {s_row['requested_by']} ({s_row['request_date']})")
                    
                    own_note = st.text_input("ملاحظات وقرار مالك الشركة:", value=f"موافقة استثنائية على تقسيم الربع إلى {split_n} دفعات", key=f"{key_prefix}own_sp_nt_{s_row['id']}")
                    bc1, bc2 = st.columns(2)
                    
                    if bc1.button(f"✅ موافقة المالك وتقسيم الربع آلياً إلى ({split_n}) دفعات", key=f"{key_prefix}app_sp_{s_row['id']}", type="primary", use_container_width=True):
                        # التحقق من القسط الأصلي
                        orig_inst = db_fetchone("SELECT due_date FROM UnitInstallments WHERE id=%s", (int(s_row['installment_id']),))
                        base_due_str = orig_inst[0] if orig_inst and orig_inst[0] else get_egypt_time().strftime("%Y/%m/%d")
                        try:
                            base_due_dt = datetime.strptime(base_due_str, "%Y/%m/%d")
                        except:
                            base_due_dt = get_egypt_time()

                        # 1. إلغاء القسط الموحد القديم بسبب التقسيم
                        db_execute(
                            "UPDATE UnitInstallments SET status='ملغي (تم تقسيم الربع بموافقة المالك)', collection_stage='تم السداد / مغلق' WHERE id=%s",
                            (int(s_row['installment_id']),)
                        )
                        # 2. إنشاء الدفعات المقسمة (2 أو 3 دفعات) آلياً
                        for i in range(1, split_n + 1):
                            inst_due = (base_due_dt + timedelta(days=30 * (i - 1))).strftime("%Y/%m/%d")
                            part_label = f"{s_row['quarter_name']} - الدفعة ({i} من {split_n}) [استثناء مالك]"
                            note_label = f"{s_row['phase_name']} | {part_label}"
                            db_execute("""
                                INSERT INTO UnitInstallments 
                                (unit_code, project_name, client_name, phase_name, quarter_name, amount, currency, due_date, paid_date, status, notes, collection_stage, call_notes, is_split_exception)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', 'مستحق (لم يُدفع)', %s, 'متابعة خدمة العملاء', %s, TRUE)
                            """, (
                                s_row['project_name'], s_row['project_name'], s_row['shareholder_name'],
                                s_row['phase_name'], part_label, round(part_val, 2), curr_v, inst_due,
                                note_label, f"مقسم بموافقة المالك: {own_note}"
                            ))

                        # 3. تحديث حالة الطلب
                        db_execute(
                            "UPDATE QuarterSplitRequests SET status='معتمد من المالك وتم التقسيم', owner_notes=%s WHERE id=%s",
                            (own_note, s_row['id'])
                        )
                        log_event("اعتماد المالك لتقسيم ربع تنفيذ", f"المساهم: {s_row['shareholder_name']} - {s_row['quarter_name']} إلى {split_n} دفعات")
                        st.success(f"✅ تم اعتماد الاستثناء وتقسيم الربع آلياً إلى ({split_n}) دفعات في كشف حساب المساهم!")
                        st.rerun()

                    if bc2.button("❌ رفض طلب التقسيم (يلتزم بسداد الربع دفعة واحدة)", key=f"{key_prefix}rej_sp_{s_row['id']}", use_container_width=True):
                        db_execute(
                            "UPDATE QuarterSplitRequests SET status='مرفوض من المالك (يسدد دفعة واحدة)', owner_notes=%s WHERE id=%s",
                            (own_note, s_row['id'])
                        )
                        log_event("رفض تقسيم ربع تنفيذ", f"المساهم: {s_row['shareholder_name']}")
                        st.rerun()
            st.divider()

    # 2. نموذج تقديم طلب استثناء لتقسيم ربع تنفيذ
    if can_request:
        with st.form(f"{key_prefix}req_quarter_split_form"):
            st.markdown("#### 📝 تقديم طلب استثناء لمالك الشركة لتقسيم ربع تنفيذ لمساهم")
            if not unpaid_q_df.empty:
                q_opts = (
                    unpaid_q_df['id'].astype(str) + " | " +
                    unpaid_q_df['project_name'].fillna('') + " | المساهم: " +
                    unpaid_q_df['client_name'].fillna('') + " | " +
                    unpaid_q_df['phase_name'].fillna('') + " - " +
                    unpaid_q_df['quarter_name'].fillna('') + " | المبلغ: " +
                    unpaid_q_df['amount'].astype(str) + " " +
                    unpaid_q_df['currency'].fillna('')
                ).tolist()
                sel_q_str = st.selectbox("اختر مطالبة الربع غير المسددة المراد تقسيمها:", q_opts)
            else:
                sel_q_str = ""
                st.info("لا توجد مطالبات أرباع غير مسددة حالياً لتقسيمها.")

            c1, c2 = st.columns(2)
            split_choice = c1.radio("عدد الدفعات المطلوب تقسيم الربع عليها (استثناء):", [2, 3], format_func=lambda x: f"تقسيم الربع على دفعتين (مرحلتين - 50% لكل دفعة)" if x == 2 else f"تقسيم الربع على 3 دفعات (3 مراحل - 33.3% لكل دفعة)", horizontal=True)
            split_reason = c2.text_input("سبب طلب الاستثناء (يُعرض على مالك الشركة) *")

            if st.form_submit_button("إرسال طلب الاستثناء لمالك الشركة للموافقة 🚀", type="primary"):
                if sel_q_str and split_reason.strip():
                    inst_id_v = int(sel_q_str.split(" | ")[0])
                    row_match = unpaid_q_df[unpaid_q_df['id'] == inst_id_v].iloc[0]
                    db_execute("""
                        INSERT INTO QuarterSplitRequests 
                        (installment_id, project_name, shareholder_name, phase_name, quarter_name, original_amount, currency, split_count, reason, requested_by, request_date, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'بانتظار موافقة المالك')
                    """, (
                        inst_id_v, row_match['project_name'], row_match['client_name'],
                        row_match['phase_name'], row_match['quarter_name'], float(row_match['amount']),
                        row_match['currency'], int(split_choice), split_reason.strip(),
                        st.session_state.get('username', 'موظف'), get_egypt_time().strftime("%Y/%m/%d")
                    ))
                    log_event("طلب استثناء تقسيم ربع تنفيذ", f"المساهم: {row_match['client_name']} - {row_match['quarter_name']} إلى {split_choice} دفعات")
                    st.success("تم إرسال طلب الاستثناء إلى مالك الشركة (Owner) وبانتظار اعتماده!")
                    st.rerun()
                else:
                    st.error("يرجى اختيار مطالبة الربع وكتابة سبب الاستثناء.")

    st.markdown("#### 📋 سجل طلبات استثناء تقسيم الأرباع وقرارات المالك")
    if not split_reqs_df.empty:
        disp_sp = split_reqs_df[['project_name', 'shareholder_name', 'phase_name', 'quarter_name', 'original_amount', 'currency', 'split_count', 'reason', 'requested_by', 'request_date', 'status', 'owner_notes']].copy()
        disp_sp.columns = ['الاتحاد', 'المالك المساهم', 'المرحلة', 'الربع', 'المبلغ الأصلي', 'العملة', 'عدد الدفعات', 'السبب', 'مقدم الطلب', 'تاريخ الطلب', 'حالة موافقة المالك', 'قرار المالك']
        st.dataframe(disp_sp, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد طلبات استثناء لتقسيم الأرباع مسجلة حتى الآن.")

def render_unit_resale_module(mode="sales"):
    render_quarter_split_exception_module(mode=mode, key_prefix="resale_compat_")

# ==========================================
# 6. منظومة اتحاد الملاك المساهمين، الأرباع الـ 4، وأولوية اختيار الوحدات المميزة
# ==========================================
def calculate_shareholder_priority_ranking(sh_df, inst_df, project_filter="الكل"):
    """ترتيب الملاك المساهمين آلياً حسب أسبقية السداد الفعلي ونسبة الالتزام لتحديد أولوية اختيار الوحدات المميزة"""
    if sh_df.empty:
        return pd.DataFrame()

    filtered_sh = sh_df if project_filter == "الكل" else sh_df[sh_df['project_name'] == project_filter]
    if filtered_sh.empty:
        return pd.DataFrame()

    ranking_rows = []
    for _, sh in filtered_sh.iterrows():
        sh_name = sh['name']
        sh_proj = sh['project_name']
        sh_inst = inst_df[(inst_df['client_name'] == sh_name) & (~inst_df['status'].str.contains('ملغي', na=False))] if not inst_df.empty else pd.DataFrame()

        total_due_amt = float(sh_inst['amount'].fillna(0).sum()) if not sh_inst.empty else 0.0
        paid_rows = sh_inst[sh_inst['status'].isin(['مدفوع', 'مدفوع في الموعد', 'مدفوع متأخر'])] if not sh_inst.empty else pd.DataFrame()
        total_paid_amt = float(paid_rows['amount'].fillna(0).sum()) if not paid_rows.empty else 0.0
        
        paid_ratio = (total_paid_amt / total_due_amt * 100.0) if total_due_amt > 0 else 0.0
        on_time_cnt = len(sh_inst[sh_inst['status'].isin(['مدفوع', 'مدفوع في الموعد'])]) if not sh_inst.empty else 0
        late_cnt = len(sh_inst[sh_inst['status'].isin(['مدفوع متأخر', 'متأخر'])]) if not sh_inst.empty else 0

        # حساب سرعة وأسبقية السداد باليوم (كلما دفع مبكراً قبل الاستحقاق أو في تاريخ أسبق كلما زادت أولويته)
        speed_days_list = []
        valid_paid_dates = []
        if not paid_rows.empty:
            for _, p_r in paid_rows.iterrows():
                p_dt_str = str(p_r['paid_date']).strip()
                d_dt_str = str(p_r['due_date']).strip()
                if p_dt_str and p_dt_str != 'None':
                    valid_paid_dates.append(p_dt_str)
                    try:
                        p_dt = datetime.strptime(p_dt_str[:10], "%Y/%m/%d")
                        d_dt = datetime.strptime(d_dt_str[:10], "%Y/%m/%d")
                        # الفرق بالأيام (سالب يعني دفع قبل الموعد، صفر في الموعد، موجب متأخر)
                        speed_days_list.append((p_dt - d_dt).days)
                    except:
                        pass

        avg_delay_days = sum(speed_days_list) / len(speed_days_list) if speed_days_list else 9999.0
        last_paid_date = max(valid_paid_dates) if valid_paid_dates else "9999/99/99"
        has_split_exc = bool(sh_inst['is_split_exception'].any()) if (not sh_inst.empty and 'is_split_exception' in sh_inst.columns) else False

        ranking_rows.append({
            'id': sh['id'],
            'project_name': sh_proj,
            'name': sh_name,
            'land_share_pct': float(sh['land_share_pct'] or 0.0),
            'land_share_amount': float(sh['land_share_amount'] or 0.0),
            'currency': sh['currency'] or 'ج.م (EGP)',
            'total_required': total_due_amt,
            'total_paid': total_paid_amt,
            'paid_ratio': round(paid_ratio, 1),
            'on_time_cnt': on_time_cnt,
            'late_cnt': late_cnt,
            'avg_delay_days': avg_delay_days,
            'last_paid_date': last_paid_date if last_paid_date != "9999/99/99" else "لم يسدد بعد",
            '_sort_paid_has': 1 if total_paid_amt > 0 else 0,
            '_sort_no_split': 0 if has_split_exc else 1,
            '_sort_date': last_paid_date,
            'assigned_unit': sh.get('assigned_unit') or 'لم يخصص بعد'
        })

    rank_df = pd.DataFrame(ranking_rows)
    if rank_df.empty:
        return rank_df

    # الترتيب: 1. أعلى نسبة سداد والتزام، 2. من سدد الربع دفعة واحدة بدون تقسيم، 3. الأسرع سداداً (أقل تأخيراً/مبكراً)، 4. أسبقية تاريخ السداد الفعلي
    rank_df = rank_df.sort_values(
        by=['_sort_paid_has', 'paid_ratio', '_sort_no_split', 'avg_delay_days', '_sort_date', 'total_paid'],
        ascending=[False, False, False, True, True, False]
    ).reset_index(drop=True)

    medals = []
    for idx in range(len(rank_df)):
        order_num = idx + 1
        if order_num == 1:
            medals.append("🥇 الأولوية (1) - اختيار أول مميز")
        elif order_num == 2:
            medals.append("🥈 الأولوية (2) - اختيار ثاني")
        elif order_num == 3:
            medals.append("🥉 الأولوية (3) - اختيار ثالث")
        else:
            medals.append(f"الترتيب ({order_num})")
    rank_df['priority_badge'] = medals
    return rank_df

def render_clients_and_crm_module(mode="view", key_prefix=""):
    ensure_shareholders_union_schema()
    is_sales = (mode == "sales")
    is_accountant = (mode == "accountant")
    is_legal = (mode == "legal")
    is_owner = (mode == "owner")
    can_edit = is_sales or is_accountant or is_owner
    can_delete = is_sales or is_accountant or is_owner
    
    st.header("🤝 منظومة اتحاد الملاك المساهمين، الأرباع الـ 4، وأولوية اختيار الوحدات")
    
    crm_tabs = st.tabs([
        "🥇 أولوية اختيار الوحدات المميزة وكشف الحساب (PDF)",
        "🏗️ مراحل التنفيذ والأرباع الـ 4 والتحصيل والتصعيد", 
        "👑 استثناء المالك لتقسيم ربع التنفيذ (دفعتين أو 3)",
        "🤝 سجل الملاك المساهمين وحصص الأرض (%)"
    ])
    
    conn = get_db_connection()
    try:
        sh_df = pd.read_sql_query("SELECT id, name, phone, national_id, address, project_name, land_share_pct, land_share_amount, COALESCE(currency, 'ج.م (EGP)') as currency, COALESCE(assigned_unit, 'لم يخصص بعد') as assigned_unit, notes FROM Shareholders ORDER BY project_name ASC, land_share_pct DESC", conn)
    except Exception:
        sh_df = pd.DataFrame(columns=['id', 'name', 'phone', 'national_id', 'address', 'project_name', 'land_share_pct', 'land_share_amount', 'currency', 'assigned_unit', 'notes'])

    try:
        inst_df = pd.read_sql_query("""
            SELECT id, COALESCE(project_name, unit_code) as project_name, unit_code, client_name, 
                   COALESCE(phase_name, 'مرحلة تنفيذ') as phase_name, 
                   COALESCE(quarter_name, 'الربع الأول (Q1)') as quarter_name,
                   amount, COALESCE(currency, 'ج.م (EGP)') as currency, 
                   due_date, paid_date, status, notes, 
                   COALESCE(collection_stage, 'متابعة خدمة العملاء') as collection_stage, 
                   COALESCE(call_notes, '') as call_notes,
                   COALESCE(is_split_exception, FALSE) as is_split_exception
            FROM UnitInstallments ORDER BY due_date ASC, id ASC
        """, conn)
    except Exception:
        inst_df = pd.DataFrame(columns=['id', 'project_name', 'unit_code', 'client_name', 'phase_name', 'quarter_name', 'amount', 'currency', 'due_date', 'paid_date', 'status', 'notes', 'collection_stage', 'call_notes', 'is_split_exception'])
    conn.close()

    # =========================================================
    # التبويب 1: أولوية اختيار الوحدات المميزة + كشف حساب المساهم
    # =========================================================
    with crm_tabs[0]:
        st.subheader("🥇 ترتيب أولوية الملاك المساهمين لاختيار الوحدات المميزة (حسب أسبقية السداد)")
        st.info("💡 يرتب النظام الملاك المساهمين داخل كل اتحاد آلياً بناءً على **نسبة الالتزام، السداد الكامل للربع بدون تقسيم، وأسبقية تاريخ السداد الفعلي**، بحيث يحصل المالك الأسرع التزاماً وسداداً على **الأولوية رقم (1) 🥇** عند تقسيم الأرض واختيار الوحدات المميزة.")

        proj_filter_list = ["الكل"] + [f"اتحاد {i}" for i in range(1, 46)]
        sel_proj_rank = st.selectbox("🏗️ اختر المشروع (الاتحاد) لعرض ترتيب أولوية الملاك المساهمين:", proj_filter_list, key=f"{key_prefix}proj_rank_sel")

        rank_df = calculate_shareholder_priority_ranking(sh_df, inst_df, project_filter=sel_proj_rank)
        if not rank_df.empty:
            disp_rank = rank_df[['priority_badge', 'project_name', 'name', 'land_share_pct', 'total_required', 'total_paid', 'paid_ratio', 'last_paid_date', 'assigned_unit']].copy()
            disp_rank.columns = ['أولوية اختيار الوحدة', 'الاتحاد', 'اسم المالك المساهم', 'نسبة الأرض %', 'إجمالي المطالبات', 'إجمالي المسدد', 'نسبة السداد %', 'تاريخ آخر سداد فعلي', 'الوحدة المخصصة له']
            st.dataframe(disp_rank, use_container_width=True, hide_index=True)

            if can_edit:
                with st.expander("🏢 تثبيت وتخصيص الوحدة المختارة للمساهم (حسب أولويته)"):
                    ac1, ac2, ac3 = st.columns([2, 2, 1])
                    sh_alloc_opts = rank_df['id'].astype(str) + " - " + rank_df['name'] + " (" + rank_df['priority_badge'] + ")"
                    sel_sh_alloc = ac1.selectbox("اختر المساهم:", sh_alloc_opts, key=f"{key_prefix}alloc_sh")
                    chosen_unit_txt = ac2.text_input("الوحدة المميزة المختارة (مثال: واجهة بحري - الدور الأول شقة 101):", key=f"{key_prefix}alloc_u")
                    if ac3.button("تثبيت الوحدة ✅", key=f"{key_prefix}btn_alloc_u", type="primary"):
                        sh_id_alloc = int(sel_sh_alloc.split(" - ")[0])
                        db_execute("UPDATE Shareholders SET assigned_unit=%s WHERE id=%s", (chosen_unit_txt.strip(), sh_id_alloc))
                        log_event("تخصيص وحدة لمساهم حسب الأولوية", f"مساهم رقم {sh_id_alloc} - الوحدة: {chosen_unit_txt}")
                        st.success("تم تثبيت الوحدة المختارة للمساهم بنجاح!")
                        st.rerun()

            html_rank = generate_html_report(f"تقرير أولوية الملاك المساهمين لاختيار الوحدات المميزة ({sel_proj_rank})", disp_rank)
            st.download_button("🖨️ طباعة كشف أولوية اختيار الوحدات (PDF)", data=html_rank, file_name="Shareholders_Priority.html", mime="text/html", key=f"{key_prefix}dl_prio_pdf")
        else:
            st.info("لا يوجد ملاك مساهمين مسجلين في هذا الاتحاد حالياً. يرجى إضافتهم من تبويب (سجل الملاك المساهمين).")

        st.divider()
        st.subheader("📄 إصدار كشف حساب تفصيلي لمالك مساهم (PDF)")
        all_sh_names = sorted(list(set(
            (sh_df['name'].dropna().tolist() if not sh_df.empty else []) +
            (inst_df['client_name'].dropna().tolist() if not inst_df.empty else [])
        )))
        all_sh_names = [n for n in all_sh_names if str(n).strip() != ""]

        if all_sh_names:
            sel_sh_stmt = st.selectbox("👤 اختر المالك المساهم لعرض وطباعة كشف حسابه:", all_sh_names, key=f"{key_prefix}sh_stmt_sel")
            sh_info = sh_df[sh_df['name'] == sel_sh_stmt] if not sh_df.empty else pd.DataFrame()
            sh_inst_all = inst_df[inst_df['client_name'] == sel_sh_stmt] if not inst_df.empty else pd.DataFrame()
            sh_inst_active = sh_inst_all[~sh_inst_all['status'].str.contains('ملغي', na=False)] if not sh_inst_all.empty else pd.DataFrame()

            sh_pct_val = float(sh_info['land_share_pct'].iloc[0]) if not sh_info.empty else 0.0
            sh_land_val = float(sh_info['land_share_amount'].iloc[0]) if not sh_info.empty else 0.0
            sh_proj_val = sh_info['project_name'].iloc[0] if not sh_info.empty else "غير محدد"
            sh_unit_val = sh_info['assigned_unit'].iloc[0] if not sh_info.empty else "لم يخصص بعد"
            main_curr = sh_info['currency'].iloc[0] if not sh_info.empty else (sh_inst_active['currency'].iloc[0] if not sh_inst_active.empty else "ج.م (EGP)")

            tot_req = float(sh_inst_active['amount'].fillna(0).sum()) if not sh_inst_active.empty else 0.0
            tot_paid = float(sh_inst_active[sh_inst_active['status'].isin(['مدفوع', 'مدفوع في الموعد', 'مدفوع متأخر'])]['amount'].fillna(0).sum()) if not sh_inst_active.empty else 0.0
            tot_rem = max(0.0, tot_req - tot_paid)

            badge_text, _, _, _ = evaluate_client_commitment(sh_inst_active)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("📐 نسبة المشاركة في الأرض", f"{sh_pct_val:.2f}% ({sh_proj_val})")
            m2.metric("💰 إجمالي مطالبات الأرباع والأرض", f"{tot_req:,.2f} {main_curr}")
            m3.metric("✅ إجمالي المسدد الفعلي", f"{tot_paid:,.2f} {main_curr}")
            m4.metric("⏳ المتبقي على المساهم", f"{tot_rem:,.2f} {main_curr}")

            if not sh_inst_all.empty:
                stmt_tbl = sh_inst_all[['project_name', 'phase_name', 'quarter_name', 'amount', 'currency', 'due_date', 'paid_date', 'status', 'collection_stage']].copy()
                stmt_tbl.columns = ['الاتحاد', 'المرحلة', 'الربع / الدفعة', 'المبلغ', 'العملة', 'تاريخ الاستحقاق', 'تاريخ السداد الفعلي', 'حالة الدفع', 'مرحلة المتابعة']
                st.dataframe(stmt_tbl, use_container_width=True, hide_index=True)

                extra_sum = f"""
                <div class="summary-box">
                    <div class="summary-item"><span>اسم المالك المساهم</span><strong>{sel_sh_stmt}</strong></div>
                    <div class="summary-item"><span>المشروع ونسبة الأرض</span><strong>{sh_proj_val} ({sh_pct_val}%)</strong></div>
                    <div class="summary-item"><span>حصة الأرض المالية</span><strong>{sh_land_val:,.2f} {main_curr}</strong></div>
                    <div class="summary-item"><span>إجمالي المسدد</span><strong style="color:green;">{tot_paid:,.2f} {main_curr}</strong></div>
                    <div class="summary-item"><span>المتبقي</span><strong style="color:#b80000;">{tot_rem:,.2f} {main_curr}</strong></div>
                    <div class="summary-item"><span>الوحدة المخصصة</span><strong>{sh_unit_val}</strong></div>
                </div>
                """
                html_sh_stmt = generate_html_report(f"كشف حساب مالك مساهم - {sel_sh_stmt}", stmt_tbl, extra_summary_html=extra_sum)
                st.download_button(
                    "🖨️ طباعة / تصدير كشف حساب المساهم (PDF)",
                    data=html_sh_stmt,
                    file_name=f"Shareholder_Statement_{sel_sh_stmt}.html",
                    mime="text/html",
                    type="primary",
                    use_container_width=True,
                    key=f"{key_prefix}dl_sh_stmt_btn"
                )

    # =========================================================
    # التبويب 2: مراحل التنفيذ والأرباع الـ 4 والتحصيل والتصعيد
    # =========================================================
    with crm_tabs[1]:
        st.subheader("🏗️ جدولة مراحل التنفيذ (الأرباع الـ 4) ومتابعة التحصيل والتصعيد")
        
        if can_edit:
            col_q_auto, col_q_single = st.columns(2)
            
            # 1. توزيع ربع تنفيذ آلياً على كل مساهمي الاتحاد حسب نسبهم في الأرض (%)
            with col_q_auto:
                with st.expander("⚡ توزيع تكلفة ربع تنفيذ آلياً على مساهمي الاتحاد (حسب نسبة كل مالك %)", expanded=True):
                    with st.form(f"{key_prefix}auto_dist_quarter_form"):
                        q_proj = st.selectbox("اختر المشروع (الاتحاد)", [f"اتحاد {i}" for i in range(1, 46)], key=f"{key_prefix}ap_proj")
                        q_phase = st.text_input("اسم مرحلة التنفيذ (مثال: مرحلة الأساسات / الهيكل الخرساني)", value="مرحلة الإنشاءات")
                        q_quarter = st.selectbox("اختر الربع (من الأرباع الـ 4 للمرحلة)", QUARTER_OPTIONS, key=f"{key_prefix}ap_q")
                        
                        qc1, qc2 = st.columns(2)
                        q_total_cost = qc1.number_input("إجمالي تكلفة هذا الربع للمشروع بالكامل", min_value=0.0, step=10000.0)
                        q_curr = qc2.selectbox("العملة", CURRENCY_OPTIONS, key=f"{key_prefix}ap_curr")
                        q_due = st.date_input("تاريخ استحقاق سداد الربع (دفعة واحدة)")
                        
                        if st.form_submit_button("توزيع الربع آلياً على جميع مساهمي الاتحاد 📊", type="primary", use_container_width=True):
                            proj_shs = sh_df[sh_df['project_name'] == q_proj] if not sh_df.empty else pd.DataFrame()
                            if proj_shs.empty:
                                st.error(f"⚠️ لا يوجد ملاك مساهمين مسجلين في ({q_proj}) بعد! سجلهم أولاً في تبويب (سجل الملاك المساهمين).")
                            elif q_total_cost <= 0:
                                st.error("يرجى إدخال إجمالي تكلفة الربع للمشروع.")
                            else:
                                count_inserted = 0
                                for _, sh_r in proj_shs.iterrows():
                                    pct = float(sh_r['land_share_pct'] or 0.0)
                                    if pct > 0:
                                        sh_amount = round((q_total_cost * pct) / 100.0, 2)
                                        note_desc = f"{q_phase} - {q_quarter} (نسبة المساهم {pct}%)"
                                        db_execute("""
                                            INSERT INTO UnitInstallments 
                                            (unit_code, project_name, client_name, phase_name, quarter_name, amount, currency, due_date, paid_date, status, notes, collection_stage, call_notes, is_split_exception)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', 'مستحق (لم يُدفع)', %s, 'متابعة خدمة العملاء', '', FALSE)
                                        """, (q_proj, q_proj, sh_r['name'], q_phase, q_quarter, sh_amount, q_curr, q_due.strftime("%Y/%m/%d"), note_desc))
                                        count_inserted += 1
                                log_event("توزيع ربع تنفيذ آلياً", f"{q_proj} - {q_phase} ({q_quarter}) بقيمة كلية {q_total_cost} على {count_inserted} مساهم")
                                st.success(f"✅ تم توزيع ({q_quarter}) آلياً على ({count_inserted}) مالك مساهم في ({q_proj}) كلٌ حسب نسبته!")
                                st.rerun()

            # 2. إضافة ربع تنفيذ لمساهم محدد بشكل فردي
            with col_q_single:
                with st.expander("➕ تسجيل مطالبة ربع تنفيذ لمالك مساهم محدد", expanded=True):
                    with st.form(f"{key_prefix}single_sh_quarter_form"):
                        s_proj = st.selectbox("المشروع (الاتحاد)", [f"اتحاد {i}" for i in range(1, 46)], key=f"{key_prefix}sp_proj")
                        sh_names_in_list = sh_df['name'].dropna().unique().tolist() if not sh_df.empty else []
                        if sh_names_in_list:
                            s_sh_name = st.selectbox("اختر المالك المساهم", sh_names_in_list, key=f"{key_prefix}sp_sh")
                        else:
                            s_sh_name = st.text_input("اسم المالك المساهم")
                            
                        sc1, sc2 = st.columns(2)
                        s_phase = sc1.text_input("مرحلة التنفيذ", value="مرحلة الإنشاءات", key=f"{key_prefix}sp_ph")
                        s_quarter = sc2.selectbox("الربع (1 / 2 / 3 / 4)", QUARTER_OPTIONS, key=f"{key_prefix}sp_q")
                        
                        sc3, sc4, sc5 = st.columns(3)
                        s_amt = sc3.number_input("المبلغ المطلوب (دفعة واحدة)", min_value=0.0, step=5000.0)
                        s_curr = sc4.selectbox("العملة", CURRENCY_OPTIONS, key=f"{key_prefix}sp_curr")
                        s_due = sc5.date_input("تاريخ الاستحقاق", key=f"{key_prefix}sp_due")
                        
                        if st.form_submit_button("إضافة مطالبة الربع للمساهم ➕", type="primary", use_container_width=True):
                            if s_sh_name and s_amt > 0:
                                note_desc = f"{s_phase} - {s_quarter}"
                                db_execute("""
                                    INSERT INTO UnitInstallments 
                                    (unit_code, project_name, client_name, phase_name, quarter_name, amount, currency, due_date, paid_date, status, notes, collection_stage, call_notes, is_split_exception)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', 'مستحق (لم يُدفع)', %s, 'متابعة خدمة العملاء', '', FALSE)
                                """, (s_proj, s_proj, s_sh_name.strip(), s_phase, s_quarter, s_amt, s_curr, s_due.strftime("%Y/%m/%d"), note_desc))
                                log_event("إضافة ربع تنفيذ لمساهم", f"المساهم: {s_sh_name} - {s_proj} - {s_quarter}: {s_amt} {s_curr}")
                                st.success("تم تسجيل مطالبة الربع للمساهم بنجاح!")
                                st.rerun()
                            else:
                                st.error("يرجى اختيار المساهم وإدخال المبلغ.")

        # متابعة التحصيل والتصعيد وتأكيد تاريخ السداد الفعلي (الذي يحدد الأولوية)
        if not inst_df.empty:
            unpaid_df = inst_df[~inst_df['status'].isin(['مدفوع', 'مدفوع في الموعد', 'مدفوع متأخر']) & (~inst_df['status'].str.contains('ملغي', na=False))]
            
            if is_sales and not unpaid_df.empty:
                st.markdown("#### 📞 متابعة وتصعيد خدمة العملاء مع المساهمين المتأخرين")
                cs_df = unpaid_df[unpaid_df['collection_stage'].isin(['متابعة خدمة العملاء', 'تمت المكالمة الأولى (خدمة العملاء)', 'تمت المكالمة الثانية (خدمة العملاء)'])]
                if not cs_df.empty:
                    cs_opts = cs_df['id'].astype(str) + " - المساهم: " + cs_df['client_name'].fillna('') + " | " + cs_df['project_name'].fillna('') + " (" + cs_df['quarter_name'].fillna('') + ") | " + cs_df['amount'].astype(str) + " " + cs_df['currency'].fillna('')
                    sel_cs_inst = st.selectbox("اختر مطالبة المساهم:", cs_opts, key=f"{key_prefix}cs_esc_sel")
                    cs_note_input = st.text_input("ملاحظة المكالمة:", key=f"{key_prefix}cs_note_in")
                    
                    b1, b2, b3, b4 = st.columns(4)
                    target_id = int(sel_cs_inst.split(" - ")[0])
                    old_notes = cs_df[cs_df['id'] == target_id].iloc[0]['call_notes'] or ""
                    now_tag = get_egypt_time().strftime("%Y/%m/%d %H:%M")
                    
                    if b1.button("📞 1. المكالمة الأولى", key=f"{key_prefix}b1_cs", use_container_width=True):
                        new_log = f"{old_notes} | [مكالمة 1 خدمة عملاء {now_tag}: {cs_note_input or 'تم الاتصال'}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='تمت المكالمة الأولى (خدمة العملاء)', status='متأخر', call_notes=%s WHERE id=%s", (new_log, target_id))
                        st.rerun()
                    if b2.button("📞 2. المكالمة الثانية", key=f"{key_prefix}b2_cs", use_container_width=True):
                        new_log = f"{old_notes} | [مكالمة 2 خدمة عملاء {now_tag}: {cs_note_input or 'تم الاتصال 2'}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='تمت المكالمة الثانية (خدمة العملاء)', status='متأخر', call_notes=%s WHERE id=%s", (new_log, target_id))
                        st.rerun()
                    if b3.button("⚖️ 3. تحويل للشؤون القانونية", key=f"{key_prefix}b3_cs", type="primary", use_container_width=True):
                        new_log = f"{old_notes} | [تحويل للقانونية {now_tag}: {cs_note_input}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='محول للشؤون القانونية', status='متأخر', call_notes=%s WHERE id=%s", (new_log, target_id))
                        st.rerun()
                    if b4.button("✅ تم السداد وتثبيت الأسبقية", key=f"{key_prefix}b4_cs", use_container_width=True):
                        new_log = f"{old_notes} | [تم السداد {now_tag}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET status='مدفوع في الموعد', paid_date=%s, collection_stage='تم السداد / مغلق', call_notes=%s WHERE id=%s", (get_egypt_time().strftime("%Y/%m/%d"), new_log, target_id))
                        st.rerun()

            if is_legal and not unpaid_df.empty:
                st.markdown("#### ⚖️ مطالبات المساهمين المحولة للشؤون القانونية")
                leg_df = unpaid_df[unpaid_df['collection_stage'].isin(['محول للشؤون القانونية', 'تمت مكالمة الشؤون القانونية'])]
                if not leg_df.empty:
                    leg_opts = leg_df['id'].astype(str) + " - المساهم: " + leg_df['client_name'].fillna('') + " | " + leg_df['project_name'].fillna('') + " (" + leg_df['quarter_name'].fillna('') + ")"
                    sel_leg_inst = st.selectbox("اختر الملف:", leg_opts, key=f"{key_prefix}leg_esc_sel")
                    target_leg_id = int(sel_leg_inst.split(" - ")[0])
                    old_leg_notes = leg_df[leg_df['id'] == target_leg_id].iloc[0]['call_notes'] or ""
                    leg_note_input = st.text_input("ملاحظة الشؤون القانونية:", key=f"{key_prefix}leg_note_in")
                    lb1, lb2, lb3 = st.columns(3)
                    now_tag = get_egypt_time().strftime("%Y/%m/%d %H:%M")
                    if lb1.button("📞 تسجيل مكالمة إنذار قانوني", key=f"{key_prefix}lb1", use_container_width=True):
                        new_log = f"{old_leg_notes} | [إنذار قانوني {now_tag}: {leg_note_input}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='تمت مكالمة الشؤون القانونية', call_notes=%s WHERE id=%s", (new_log, target_leg_id))
                        st.rerun()
                    if lb2.button("👑 تصعيد لمالك الشركة", key=f"{key_prefix}lb2", type="primary", use_container_width=True):
                        new_log = f"{old_leg_notes} | [تصعيد للمالك {now_tag}: {leg_note_input}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='محول للمالك (لتدخل الإدارة العليا)', call_notes=%s WHERE id=%s", (new_log, target_leg_id))
                        st.rerun()
                    if lb3.button("✅ تم السداد", key=f"{key_prefix}lb3", use_container_width=True):
                        db_execute("UPDATE UnitInstallments SET status='مدفوع متأخر', paid_date=%s, collection_stage='تم السداد / مغلق' WHERE id=%s", (get_egypt_time().strftime("%Y/%m/%d"), target_leg_id))
                        st.rerun()

            if can_edit:
                with st.expander("💳 تأكيد سداد ربع تنفيذ وتحديد تاريخ السداد الفعلي (لتحديث أولوية اختيار الوحدات 🥇)"):
                    up1, up2, up3, up4 = st.columns([2.5, 1.5, 1.5, 1])
                    inst_opts = inst_df['id'].astype(str) + " - " + inst_df['client_name'].fillna('') + " | " + inst_df['project_name'].fillna('') + " (" + inst_df['quarter_name'].fillna('') + " - " + inst_df['amount'].astype(str) + " " + inst_df['currency'].fillna('') + ")"
                    sel_inst_to_upd = up1.selectbox("اختر دفعة الربع:", inst_opts, key=f"{key_prefix}upd_q_sel")
                    new_inst_st = up2.selectbox("حالة الدفع:", ["مدفوع في الموعد", "مدفوع متأخر", "مستحق (لم يُدفع)", "متأخر"], key=f"{key_prefix}upd_q_st")
                    actual_paid_dt = up3.date_input("تاريخ السداد الفعلي", key=f"{key_prefix}upd_q_dt")
                    if up4.button("تأكيد السداد ✅", key=f"{key_prefix}btn_upd_q", type="primary"):
                        inst_id_val = int(sel_inst_to_upd.split(" - ")[0])
                        paid_dt_val = actual_paid_dt.strftime("%Y/%m/%d") if "مدفوع" in new_inst_st else ""
                        new_stage = "تم السداد / مغلق" if "مدفوع" in new_inst_st else "متابعة خدمة العملاء"
                        db_execute("UPDATE UnitInstallments SET status=%s, paid_date=%s, collection_stage=%s WHERE id=%s", (new_inst_st, paid_dt_val, new_stage, inst_id_val))
                        log_event("تأكيد سداد ربع تنفيذ", f"دفعة رقم {inst_id_val} - الحالة: {new_inst_st} - تاريخ السداد: {paid_dt_val}")
                        st.success("تم تسجيل السداد وتحديث ترتيب أولوية المساهم لاختيار الوحدات!")
                        st.rerun()

            if can_delete:
                with st.expander("🗑️ حذف مطالبة ربع مضافة بالخطأ"):
                    del_c1, del_c2 = st.columns([3, 1])
                    all_inst_opts = inst_df['id'].astype(str) + " - المساهم: " + inst_df['client_name'].fillna('') + " | " + inst_df['quarter_name'].fillna('') + " (" + inst_df['amount'].astype(str) + ")"
                    sel_inst_del = del_c1.selectbox("اختر المطالبة المراد حذفها:", all_inst_opts, key=f"{key_prefix}del_inst_sel")
                    if del_c2.button("حذف المطالبة 🗑️", key=f"{key_prefix}btn_del_inst"):
                        inst_id_del = int(sel_inst_del.split(" - ")[0])
                        db_execute("DELETE FROM UnitInstallments WHERE id=%s", (inst_id_del,))
                        st.success("تم الحذف بنجاح!")
                        st.rerun()

            disp_inst = inst_df[['project_name', 'client_name', 'phase_name', 'quarter_name', 'amount', 'currency', 'due_date', 'paid_date', 'status', 'collection_stage', 'notes']].copy()
            disp_inst.columns = ['الاتحاد', 'اسم المالك المساهم', 'المرحلة', 'الربع (1-4)', 'المبلغ المطلوب', 'العملة', 'تاريخ الاستحقاق', 'تاريخ السداد الفعلي', 'حالة الدفع', 'مرحلة المتابعة', 'ملاحظات']
            st.dataframe(disp_inst, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد مطالبات أرباع تنفيذ مسجلة بعد.")

    # =========================================================
    # التبويب 3: استثناء المالك لتقسيم ربع التنفيذ (على دفعتين أو 3)
    # =========================================================
    with crm_tabs[2]:
        render_quarter_split_exception_module(mode=mode, key_prefix=key_prefix)

    # =========================================================
    # التبويب 4: سجل الملاك المساهمين وحصص الأرض (%)
    # =========================================================
    with crm_tabs[3]:
        st.subheader("🤝 سجل الملاك المساهمين وحصص المشاركة في الأرض (%)")
        if can_edit:
            with st.form(f"{key_prefix}add_shareholder_form"):
                c1, c2, c3 = st.columns(3)
                sh_name = c1.text_input("اسم المالك المساهم رباعي *")
                sh_phone = c2.text_input("رقم الهاتف / واتساب *")
                sh_proj = c3.selectbox("المشروع المشترك فيه (الاتحاد) *", [f"اتحاد {i}" for i in range(1, 46)], key=f"{key_prefix}sh_proj_in")
                
                c4, c5, c6 = st.columns(3)
                sh_pct = c4.number_input("نسبة مشاركته في الأرض (%) *", min_value=0.1, max_value=100.0, value=10.0, step=0.5)
                sh_land_amt = c5.number_input("قيمة حصته المالية في الأرض", min_value=0.0, step=10000.0)
                sh_curr = c6.selectbox("العملة", CURRENCY_OPTIONS, key=f"{key_prefix}sh_curr_in")
                
                c7, c8, c9 = st.columns(3)
                sh_nid = c7.text_input("الرقم القومي")
                sh_unit = c8.text_input("الوحدة المخصصة (اختياري - يحدد حسب الأولوية)", value="تحدد حسب أولوية السداد")
                sh_notes = c9.text_input("ملاحظات المساهمة")
                
                if st.form_submit_button("حفظ بيانات المالك المساهم وحصته 💾", type="primary"):
                    if sh_name.strip() and sh_phone.strip():
                        existing_sh = db_fetchone("SELECT id FROM Shareholders WHERE name=%s AND project_name=%s", (sh_name.strip(), sh_proj))
                        if existing_sh:
                            db_execute("""
                                UPDATE Shareholders 
                                SET phone=%s, national_id=%s, land_share_pct=%s, land_share_amount=%s, currency=%s, assigned_unit=%s, notes=%s
                                WHERE id=%s
                            """, (sh_phone.strip(), sh_nid.strip(), sh_pct, sh_land_amt, sh_curr, sh_unit.strip(), sh_notes.strip(), existing_sh[0]))
                        else:
                            db_execute("""
                                INSERT INTO Shareholders (name, phone, national_id, address, project_name, land_share_pct, land_share_amount, currency, assigned_unit, notes)
                                VALUES (%s, %s, %s, '', %s, %s, %s, %s, %s, %s)
                            """, (sh_name.strip(), sh_phone.strip(), sh_nid.strip(), sh_proj, sh_pct, sh_land_amt, sh_curr, sh_unit.strip(), sh_notes.strip()))
                        
                        # حفظ في جدول Clients أيضاً للتوافق
                        try:
                            db_execute("INSERT INTO Clients (name, phone, national_id, address, notes) VALUES (%s, %s, %s, %s, %s)", (sh_name.strip(), sh_phone.strip(), sh_nid.strip(), sh_proj, f"مساهم بنسبة {sh_pct}%"))
                        except:
                            pass

                        log_event("تسجيل مالك مساهم", f"المساهم: {sh_name} - {sh_proj} - نسبة الأرض: {sh_pct}% - قيمة: {sh_land_amt} {sh_curr}")
                        st.success(f"تم حفظ بيانات المالك المساهم ({sh_name}) في ({sh_proj}) بنسبة ({sh_pct}%) بنجاح!")
                        st.rerun()
                    else:
                        st.error("يرجى إدخال اسم المالك المساهم ورقم الهاتف.")

        if not sh_df.empty:
            st.markdown("#### 📊 ملخص إجمالي نسب الملكية المسجلة في كل اتحاد")
            proj_pct_sum = sh_df.groupby('project_name').agg(
                عدد_المساهمين=('id', 'count'),
                إجمالي_النسب_المسجلة=('land_share_pct', 'sum'),
                إجمالي_حصص_الأرض=('land_share_amount', 'sum')
            ).reset_index()
            proj_pct_sum['النسبة المتبقية غير الموزعة %'] = (100.0 - proj_pct_sum['إجمالي_النسب_المسجلة']).round(2)
            proj_pct_sum.columns = ['الاتحاد', 'عدد الملاك المساهمين', 'إجمالي النسب المسجلة %', 'إجمالي قيمة حصص الأرض', 'النسبة المتبقية %']
            st.dataframe(proj_pct_sum, use_container_width=True, hide_index=True)

            if can_delete:
                with st.expander("🗑️ حذف مالك مساهم من السجل"):
                    dc1, dc2, dc3 = st.columns([2, 2, 1])
                    sh_del_opts = sh_df['id'].astype(str) + " - " + sh_df['name'].fillna('') + " (" + sh_df['project_name'].fillna('') + " - " + sh_df['land_share_pct'].astype(str) + "%)"
                    sel_sh_del = dc1.selectbox("اختر المساهم المراد حذفه:", sh_del_opts, key=f"{key_prefix}sel_sh_del")
                    cascade_sh = dc2.checkbox("مسح مطالبات الأرباع المرتبطة به أيضاً", value=True, key=f"{key_prefix}casc_sh")
                    if dc3.button("حذف المساهم 🗑️", key=f"{key_prefix}btn_del_sh"):
                        sh_id_del = int(sel_sh_del.split(" - ")[0])
                        sh_row_del = sh_df[sh_df['id'] == sh_id_del].iloc[0]
                        db_execute("DELETE FROM Shareholders WHERE id=%s", (sh_id_del,))
                        if cascade_sh:
                            db_execute("DELETE FROM UnitInstallments WHERE client_name=%s AND project_name=%s", (sh_row_del['name'], sh_row_del['project_name']))
                        log_event("حذف مالك مساهم", f"تم مسح المساهم: {sh_row_del['name']}")
                        st.success("تم الحذف بنجاح!")
                        st.rerun()

            disp_sh = sh_df[['project_name', 'name', 'phone', 'land_share_pct', 'land_share_amount', 'currency', 'assigned_unit', 'national_id', 'notes']].copy()
            disp_sh.columns = ['الاتحاد', 'اسم المالك المساهم', 'رقم الهاتف', 'نسبة المشاركة في الأرض %', 'الحصة المالية للأرض', 'العملة', 'الوحدة المخصصة', 'الرقم القومي', 'ملاحظات']
            st.dataframe(disp_sh, use_container_width=True, hide_index=True)
        else:
            st.info("لا يوجد ملاك مساهمين مسجلين بعد.")

# ==========================================
# 7. الشاشة المشتركة للموظفين (البصمة والتقارير والرصيد السنوي)
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
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        img.thumbnail((220, 220))
                        buffered = io.BytesIO()
                        img.save(buffered, format="JPEG", quality=60, optimize=True)
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
