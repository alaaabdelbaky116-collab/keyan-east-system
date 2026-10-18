import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import base64
from PIL import Image
import io
import os
import psycopg2
import pytz
import math
import plotly.express as px
import hashlib
import zipfile

try:
    from db import *
except Exception:
    pass

try:
    from streamlit_js_eval import get_geolocation
    GEO_AVAILABLE = True
except ImportError:
    GEO_AVAILABLE = False

# ==========================================
# 0. تأمين شامل لجميع الدوال والثوابت
# ==========================================
LOGO_FILE = "image_c5a585.png"
OFFICIAL_IN = '11:00'
OFFICIAL_OUT = '18:00'
GRACE_PERIOD_MINS = 60
REQUIRED_HOURS = 7
DEFAULT_ANNUAL_BALANCE = 21
SUPABASE_FREE_LIMIT_MB = 500.0

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

COMPANY_DEPARTMENTS = [
    "اتش ار (HR)", "مبيعات وخدمة عملاء", "عقود قانونية", "تراخيص", "حسابات", 
    "مهندسين مكتب فني", "مهندسين إدارة وتخطيط", "مهندسين تنفيذ", 
    "إدارة المستخلصات", "إدارة الـ IT", "إدارة عليا", "أخرى"
]

DISPLAY_MAP = {
    "none": "لا يوجد", "employee": "موظف عادي", "manager": "رئيس قسم", "admin_manager": "مدير إداري", 
    "hr": "موارد بشرية", "sales": "مبيعات وخدمة عملاء", "legal": "عقود قانونية", "engineer": "مهندس", 
    "planning_engineer": "مهندس إدارة وتخطيط", "extracts_engineer": "مهندس مستخلصات", 
    "accountant": "محاسب", "licensing": "مسؤول تراخيص", "it": "مهندس IT", 
    "admin": "مسؤول نظام", "owner": "المالك"
}

def get_egypt_time():
    return datetime.now(pytz.timezone('Africa/Cairo'))

def get_db_connection():
    db_url = st.secrets["DB_URL"]
    return psycopg2.connect(db_url)

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

def hash_password(password_str):
    if not password_str:
        return ""
    return hashlib.sha256(str(password_str).encode('utf-8')).hexdigest()

def log_event(action_type, details=""):
    try:
        user = st.session_state.get('username') or 'غير مسجل'
        role = st.session_state.get('current_role') or st.session_state.get('role') or 'غير محدد'
        now_str = get_egypt_time().strftime("%Y/%m/%d %H:%M:%S")
        db_execute(
            "INSERT INTO AuditLogs (log_time, username, role, action_type, details) VALUES (%s, %s, %s, %s, %s)",
            (now_str, user, role, action_type, details)
        )
    except Exception:
        pass

def get_employee_info(emp_id):
    try:
        res = db_fetchone("SELECT name, department, annual_balance FROM Employees WHERE emp_id=%s", (emp_id,))
        if res:
            return res
    except Exception:
        pass
    return ("غير مسجل", "غير محدد", DEFAULT_ANNUAL_BALANCE)

def get_employee_stats(emp_id):
    try:
        res = db_fetchone("SELECT month, delay_mins, absent_dates, overtime_hours FROM MonthlyStats WHERE emp_id=%s ORDER BY month DESC LIMIT 1", (emp_id,))
        if res:
            return res
    except Exception:
        pass
    return (None, 0.0, "", 0.0)

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
    except Exception:
        return "خطأ في الوقت"

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode('utf-8')
    except Exception:
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
        return "⚪ لم يتم جدولة مطالبات بعد", 100.0, 0, 0
        
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
        return "🟢 منتظم (لم يحن موعد الاستحقاق بعد)", 100.0, on_time_count, late_or_overdue_count
        
    score = (on_time_count / evaluated_installments) * 100.0
    
    if score >= 90:
        badge = f"🌟 مساهم ملتزم جداً - أولوية أولى ({score:.0f}%)"
    elif score >= 70:
        badge = f"👍 التزام جيد ({score:.0f}%)"
    elif score >= 50:
        badge = f"⚠️ التزام متوسط - يحتاج متابعة ({score:.0f}%)"
    else:
        badge = f"🚨 متأخر في سداد الأرباع ({score:.0f}%)"
        
    return badge, score, on_time_count, late_or_overdue_count

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
            except Exception:
                pass

        cur.close()
        conn.close()
        return True
    except Exception:
        return False

def cleanup_previous_months_photos(is_auto=False):
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
        res = db_fetchone("SELECT pg_database_size(current_database())")
        size_bytes = float(res[0]) if res and res[0] else 0.0
        size_mb = round(size_bytes / (1024 * 1024), 2)
        pct = round(min(100.0, (size_mb / SUPABASE_FREE_LIMIT_MB) * 100.0), 1)
        
        tables_query = """
            SELECT relname AS table_name,
                   pg_total_relation_size(relid) AS total_bytes
            FROM pg_catalog.pg_statio_user_tables
            ORDER BY pg_total_relation_size(relid) DESC LIMIT 6;
        """
        t_rows = db_fetchall(tables_query)
        table_breakdown = [{"الجدول": t_name, "المساحة (MB)": round(float(t_bytes) / (1024 * 1024), 2)} for t_name, t_bytes in t_rows]
        return size_mb, pct, pd.DataFrame(table_breakdown)
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
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            workbook = writer.book
            title_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 18, 'font_color': '#0b172a'})
            sub_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 14, 'bg_color': '#0b172a', 'font_color': '#D4AF37'})
            header_format = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#f2f2f2', 'border': 1})
            cell_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})

            for s_name, df in dfs.items():
                sheet_name = s_name[:31]
                df.to_excel(writer, sheet_name=sheet_name, startrow=4, index=False)
                worksheet = writer.sheets[sheet_name]
                worksheet.right_to_left()

                max_col = max(len(df.columns) - 1, 5)
                worksheet.merge_range(0, 1, 1, max_col, 'كيان الشرقية للمقاولات والاستثمار العقاري', title_format)
                worksheet.merge_range(2, 0, 2, max_col, f'سجل بيانات النظام - {sheet_name}', sub_format)

                try:
                    if os.path.exists(LOGO_FILE):
                        worksheet.insert_image('A1', LOGO_FILE, {'x_scale': 0.12, 'y_scale': 0.12, 'positioning': 1})
                except Exception:
                    pass

                for col_num, value in enumerate(df.columns.values):
                    worksheet.write(4, col_num, value, header_format)
                    worksheet.set_column(col_num, col_num, 20, cell_format)

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
        html, body, p, h1, h2, h3, h4, h5, h6, button, input, select, textarea, label, td, th {
            font-family: 'Tajawal', sans-serif !important;
        }
        [data-testid="stIconMaterial"], .material-icons, span[translate="no"] {
            font-family: 'Material Symbols Rounded', sans-serif !important;
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

def render_security_and_backup_center(key_prefix="sec_main_"):
    active_role = st.session_state.get('current_role') or st.session_state.get('role')
    if active_role not in ['owner', 'admin']:
        st.warning("🔒 هذه اللوحة مخصصة للمالك (Owner) ومسؤول النظام (Admin) فقط.")
        return

    st.subheader("🛡️ مركز الأمان والنسخ الاحتياطي وتنظيف مساحة السيرفر")
    used_mb, used_pct, tables_df = get_database_size_info_safe()
    remaining_mb = max(0.0, SUPABASE_FREE_LIMIT_MB - used_mb)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💾 المساحة المستهلكة حالياً", f"{used_mb} MB", f"{used_pct}% من الباقة المجانية")
    c2.metric("🟢 المساحة المتبقية (من 500 MB)", f"{remaining_mb:.2f} MB")
    c3.metric("🗓️ التنظيف التلقائي أول الشهر", "مفعّل آلياً ✅")
    
    st.progress(min(1.0, used_pct / 100.0), text=f"نسبة استهلاك قاعدة بيانات Supabase: {used_mb} ميجابايت من أصل 500 ميجابايت ({used_pct}%)")

    if not tables_df.empty:
        with st.expander("📊 تفاصيل استهلاك المساحة لكل جدول"):
            st.dataframe(tables_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        if active_role == 'admin':
            st.markdown("##### 🗓️ تنظيف صور البصمة الشهري (صلاحية الأدمن فقط)")
            st.caption("يقوم النظام تلقائياً يوم 1 من كل شهر بمسح صور كاميرا الشهور السابقة مع بقاء جميع سجلات وتواريخ الحضور والتقارير اليومية، ويمكنك تشغيله يدوياً الآن:")
            if st.button("🗓️ مسح صور الشهور السابقة (تنظيف أول الشهر)", key=f"{key_prefix}btn_monthly_cln", type="primary", use_container_width=True):
                del_cnt, cutoff_dt = cleanup_previous_months_photos(is_auto=False)
                st.success(f"✅ تم مسح صور الكاميرا لعدد ({del_cnt}) سجل أقدم من ({cutoff_dt}) بنجاح مع الاحتفاظ الكامل بسجلات الحضور والتقارير!")
                st.rerun()
        else:
            st.markdown("##### 🗓️ تنظيف صور البصمة الشهري")
            st.info("ℹ️ التنظيف اليدوي للصور متاح لمسؤول النظام (Admin) فقط. النظام يقوم بالتنظيف الآلي المبرمج يوم 1 من كل شهر.")

    with col_b2:
        st.markdown("##### 📦 النسخة الاحتياطية الشاملة (Excel Backup)")
        st.caption("تحميل جميع جداول الملاك المساهمين، الأرباع، المالية، والحضور في ملف Excel واحد.")
        if st.button("⚙️ تجهيز ملف النسخة الاحتياطية الآن", key=f"{key_prefix}prep_bk", use_container_width=True):
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
                key=f"{key_prefix}dl_bk"
            )

def render_sidebar(role_title):
    with st.sidebar:
        try:
            if os.path.exists(LOGO_FILE):
                st.image(LOGO_FILE, use_container_width=True)
        except Exception:
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
                        db_execute("UPDATE Users SET password=%s WHERE username=%s", (hash_password(new_pwd), st.session_state['username']))
                        log_event("تغيير كلمة المرور", "قام المستخدم بتحديث كلمة المرور الخاصة به")
                        st.success("تم التغيير بنجاح! احتفظ بها.")
                    else:
                        st.error("كلمة المرور قصيرة جداً.")

        active_role = st.session_state.get('current_role') or st.session_state.get('role')
        if active_role in ['owner', 'admin']:
            with st.expander("🛡️ المساحة والنسخ الاحتياطي"):
                used_mb, used_pct, _ = get_database_size_info_safe()
                st.caption(f"💾 مساحة Supabase: **{used_mb} MB** / 500 MB ({used_pct}%)")
                st.progress(min(1.0, used_pct / 100.0))
                
                if active_role == 'admin':
                    if st.button("🗓️ مسح صور الشهور السابقة", key="sb_monthly_cln", type="primary", use_container_width=True):
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
    today = get_egypt_time()
    alerts = []

    try:
        conn = get_db_connection()
        try:
            esc_owner_df = pd.read_sql_query("SELECT client_name, project_name, quarter_name, amount, COALESCE(currency, 'ج.م (EGP)') as currency FROM UnitInstallments WHERE collection_stage = 'محول للمالك (لتدخل الإدارة العليا)' AND status NOT IN ('مدفوع', 'مدفوع في الموعد', 'مدفوع متأخر', 'ملغي (تم تقسيم الربع)')", conn)
            for _, row in esc_owner_df.iterrows():
                alerts.append(f"🚨 **تدخل المالك عاجل:** المساهم ({row['client_name']}) في ({row['project_name']} - {row['quarter_name']}) متأخر في سداد ({row['amount']:,.0f} {row['currency']}) وتم تصعيده للمالك!")
        except Exception:
            pass

        try:
            split_pending = pd.read_sql_query("SELECT shareholder_name, project_name, quarter_name, split_count, original_amount, currency FROM QuarterSplitRequests WHERE status = 'بانتظار موافقة المالك'", conn)
            for _, row in split_pending.iterrows():
                alerts.append(f"👑 **طلب استثناء تقسيم ربع تنفيذ:** المساهم ({row['shareholder_name']} - {row['project_name']}) يطلب استثناء لتقسيم ({row['quarter_name']}) بقيمة ({row['original_amount']:,.0f} {row['currency']}) على ({row['split_count']} دفعات) بانتظار موافقة المالك!")
        except Exception:
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
                except Exception:
                    pass
        except Exception:
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
                except Exception:
                    pass
        except Exception:
            pass

        conn.close()
    except Exception:
        pass

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
# 2. إدارة الإجازات السنوية وإعفاء التقارير 
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
# 3. لوحة القيادة وكشف أسماء الحاضرين الغائبين
# ==========================================
def render_present_and_absent_employees_widget(key_prefix="dash_"):
    st.subheader("👥 كشف أسماء الموظفين الحاضرين والغائبين")
    col_dt, col_dept_f = st.columns([1, 2])
    sel_date = col_dt.date_input("📅 اختر التاريخ لعرض الحاضرين والغائبين:", value=get_egypt_time().date(), key=f"{key_prefix}att_dt")
    sel_date_str = sel_date.strftime("%Y/%m/%d")
    dept_filter_opts = ["كل الأقسام"] + COMPANY_DEPARTMENTS
    sel_dept_f = col_dept_f.selectbox("🏢 فلترة حسب القسم:", dept_filter_opts, key=f"{key_prefix}att_dept")

    conn = get_db_connection()
    all_emps_df = pd.read_sql_query("SELECT emp_id, name, department, COALESCE(phone, '') as phone FROM Employees ORDER BY name ASC", conn)
    att_day_df = pd.read_sql_query("""
        SELECT emp_id,
               MIN(CASE WHEN action = 'حضور' THEN time END) AS check_in,
               MAX(CASE WHEN action = 'انصراف' THEN time END) AS check_out,
               MAX(location_name) AS loc
        FROM WebAttendance
        WHERE date = %s
        GROUP BY emp_id
    """, conn, params=(sel_date_str,))
    perms_day_df = pd.read_sql_query("SELECT emp_id, type FROM Permissions WHERE date = %s", conn, params=(sel_date_str,))
    reqs_day_df = pd.read_sql_query("SELECT emp_id, req_type, status FROM Requests WHERE date = %s AND status = 'مقبول'", conn, params=(sel_date_str,))
    conn.close()

    if sel_dept_f != "كل الأقسام" and not all_emps_df.empty:
        all_emps_df = all_emps_df[all_emps_df['department'] == sel_dept_f]

    if all_emps_df.empty:
        st.info("لا يوجد موظفين مسجلين في هذا القسم.")
        return

    present_ids = set(att_day_df['emp_id'].dropna().astype(str).tolist()) if not att_day_df.empty else set()
    all_emps_df['emp_id_str'] = all_emps_df['emp_id'].astype(str)

    present_df = pd.merge(
        all_emps_df[all_emps_df['emp_id_str'].isin(present_ids)],
        att_day_df,
        on='emp_id',
        how='inner'
    )

    absent_df = all_emps_df[~all_emps_df['emp_id_str'].isin(present_ids)].copy()
    perm_map = {}
    if not perms_day_df.empty:
        for _, r in perms_day_df.iterrows():
            perm_map[str(r['emp_id'])] = f"مسجل له: {r['type']}"
    if not reqs_day_df.empty:
        for _, r in reqs_day_df.iterrows():
            perm_map[str(r['emp_id'])] = f"طلب مقبول: {r['req_type']}"

    if not absent_df.empty:
        absent_df['موقف الإجازة/الإذن'] = absent_df['emp_id_str'].map(lambda x: perm_map.get(x, "❌ غياب (بدون إذن مسجل)"))

    c_pres, c_abs = st.columns(2)
    with c_pres:
        st.success(f"🟢 **الموظفون الحاضرون ({len(present_df)} موظف)** - بتاريخ {sel_date_str}")
        if not present_df.empty:
            disp_p = present_df[['name', 'department', 'check_in', 'check_out', 'loc']].copy()
            disp_p.columns = ['اسم الموظف', 'القسم', 'وقت الحضور', 'وقت الانصراف', 'الموقع']
            st.dataframe(disp_p, use_container_width=True, hide_index=True)
        else:
            st.warning("لم يسجل أي موظف بصمة حضور في هذا التاريخ.")

    with c_abs:
        st.error(f"🔴 **الموظفون الغائبون ({len(absent_df)} موظف)** - بتاريخ {sel_date_str}")
        if not absent_df.empty:
            disp_a = absent_df[['name', 'department', 'phone', 'موقف الإجازة/الإذن']].copy()
            disp_a.columns = ['اسم الموظف', 'القسم', 'رقم الهاتف', 'موقف الإجازة / الإذن']
            st.dataframe(disp_a, use_container_width=True, hide_index=True)
        else:
            st.success("🎉 جميع الموظفين حاضرون اليوم! لا يوجد غياب.")

def render_company_dashboard():
    st.header("📊 المؤشرات الحيوية والتفاعلية للشركة")
    conn = get_db_connection()
    today = get_egypt_time().strftime("%Y/%m/%d")

    c1, c2, c3, c4 = st.columns(4)
    try:
        total_emps = int(db_fetchone("SELECT COUNT(*) FROM Employees")[0])
        present_today = int(db_fetchone("SELECT COUNT(DISTINCT emp_id) FROM WebAttendance WHERE date=%s AND action='حضور'", (today,))[0])
        pending_reqs = int(db_fetchone("SELECT COUNT(*) FROM Requests WHERE status='قيد الانتظار'")[0])
    except Exception:
        total_emps = 0
        present_today = 0
        pending_reqs = 0

    c1.metric("👥 إجمالي الموظفين", total_emps)
    c2.metric("🟢 حضور اليوم", present_today)
    c3.metric("🔴 غياب محتمل اليوم", max(0, total_emps - present_today))
    c4.metric("🔔 طلبات معلقة", pending_reqs)

    st.divider()
    render_present_and_absent_employees_widget(key_prefix="main_dash_")

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
                except Exception:
                    pass
                    
        total_str = f"{total_mins // 60}:{(total_mins % 60):02d} ساعة"
        
        summary_row = pd.DataFrame([{
            'التاريخ': 'إجمالي الساعات', 'اليوم': '', 'اسم الموظف': '', 'القسم الأساسي': '',
            'الحضور': '', 'الانصراف': '', 'ساعات العمل': total_str, 'موقع البصمة': '',
            'المشاريع': '', 'التقارير اليومية': ''
        }])
        
        csv_df_with_total = pd.concat([csv_df, summary_row], ignore_index=True)
        
        col_down1, col_down2 = st.columns(2)
        csv_data = csv_df_with_total.to_csv(index=False).encode('utf-8-sig')
        col_down1.download_button("📥 تحميل كـ شيت (Excel/CSV)", data=csv_data, file_name=f"Attendance_{get_egypt_time().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)
        html_report = generate_html_report("تقرير الحضور والانصراف التفصيلي - كيان الشرقية", csv_df_with_total)
        col_down2.download_button("🖨️ تحميل للطباعة (رسمي PDF)", data=html_report, file_name=f"Attendance_{get_egypt_time().strftime('%Y%m%d')}.html", mime='text/html', type="primary", use_container_width=True)
    else:
        st.info("لا توجد سجلات تطابق خيارات البحث.")

def render_task_delegation(department="الكل"):
    st.header("📋 إسناد مهام لموظفي الشركة ومتابعة تنفيذها")
    conn = get_db_connection()
    if department == "الكل":
        emps = pd.read_sql_query("SELECT emp_id, name, department FROM Employees ORDER BY name", conn)
    else:
        emps = pd.read_sql_query("SELECT emp_id, name, department FROM Employees WHERE department=%s OR secondary_department=%s ORDER BY name", conn, params=(department, department))
    
    tasks_log_df = pd.read_sql_query("""
        SELECT t.id, e.name as emp_name, e.department as dept, t.assigner, t.project_name, 
               t.task_desc, t.assign_date, t.due_date, t.status, COALESCE(t.employee_reply, '') as employee_reply
        FROM Tasks t LEFT JOIN Employees e ON t.emp_id = e.emp_id ORDER BY t.id DESC
    """, conn)
    conn.close()
    
    with st.form("assign_task_form"):
        st.subheader("➕ إرسال مهمة جديدة لموظف")
        c1, c2 = st.columns(2)
        if not emps.empty:
            emp_display_list = (emps['emp_id'].astype(str) + " - " + emps['name'] + " (" + emps['department'].fillna('بدون قسم') + ")").tolist()
        else:
            emp_display_list = ["لا يوجد موظفين"]
            
        selected_emp_str = c1.selectbox("👤 اختر الموظف أو المهندس (من أي قسم بالشركة):", emp_display_list)
        proj = c2.selectbox("🏗️ المشروع (الاتحاد):", [f"اتحاد {i}" for i in range(1, 46)] + ["مهمة إدارية عامة"])
        task_desc = st.text_area("📝 تفاصيل المهمة المطلوبة بوضوح:")
        due_date = st.date_input("📅 تاريخ التسليم المتوقع:")
        
        if st.form_submit_button("إرسال المهمة للموظف الآن 🚀", type="primary"):
            if selected_emp_str != "لا يوجد موظفين" and task_desc.strip():
                emp_id_selected = selected_emp_str.split(" - ")[0].strip()
                db_execute(
                    "INSERT INTO Tasks (emp_id, assigner, project_name, task_desc, assign_date, due_date, status) VALUES (%s, %s, %s, %s, %s, %s, 'قيد التنفيذ')",
                    (emp_id_selected, st.session_state['username'], proj, task_desc.strip(), get_egypt_time().strftime("%Y/%m/%d"), due_date.strftime("%Y/%m/%d"))
                )
                log_event("إسناد مهمة لموظف", f"إلى كود: {emp_id_selected} - مشروع: {proj}")
                st.success("✅ تم إسناد المهمة للموظف بنجاح وستظهر له في شاشته الشخصية فوراً!")
                st.rerun()
            else:
                st.error("يرجى كتابة تفاصيل المهمة وتحديد الموظف.")

    st.divider()
    st.subheader("📊 سجل متابعة المهام المسندة للموظفين وردودهم")
    if not tasks_log_df.empty:
        disp_tasks = tasks_log_df[['emp_name', 'dept', 'project_name', 'task_desc', 'assigner', 'assign_date', 'due_date', 'status', 'employee_reply']].copy()
        disp_tasks.columns = ['اسم الموظف', 'القسم', 'المشروع', 'تفاصيل المهمة', 'مُسند المهمة', 'تاريخ الإسناد', 'موعد التسليم', 'الحالة', 'تقرير إنجاز الموظف']
        st.dataframe(disp_tasks, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد مهام مسندة حتى الآن.")

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
    except Exception:
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
                        except Exception:
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
# 4. الموديول المالي
# ==========================================
def render_financials_module(can_edit=True):
    ensure_shareholders_union_schema()
    active_role = st.session_state.get('current_role') or st.session_state.get('role')
    
    if active_role == 'owner':
        can_edit = False
        
    st.header("💰 متابعة أقساط الجهاز والتزامات المشاريع")
    
    if not can_edit:
        st.info("👁️ **وضع الاطلاع فقط (للمالك):** يمكنك من هنا مراجعة وطباعة موقف أقساط الجهاز، بينما يتم تسجيل الأقساط وتحديثها من خلال القسم المختص.")
    else:
        with st.form("add_device_inst"):
            st.subheader("➕ تسجيل قسط جهاز جديد")
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

def render_quarter_split_exception_module(mode="sales", key_prefix=""):
    ensure_shareholders_union_schema()
    is_owner = (mode == "owner")
    is_sales = (mode == "sales")
    
    st.subheader("👑 استثناء المالك لتقسيم ربع التنفيذ (على دفعتين أو 3 دفعات)")
    st.info("💡 **القاعدة الأساسية:** يسدد المالك المساهم تكلفة الربع كاملة مرة واحدة. في حال رغبة المساهم في تقسيم الربع على **دفعتين (مرحلتين)** أو **3 دفعات**، تقوم **خدمة العملاء** برفع طلب استثناء هنا ولا يتم تقسيم الربع في حسابه إلا بعد **موافقة مالك الشركة (Owner)**.")
    
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
                        orig_inst = db_fetchone("SELECT due_date FROM UnitInstallments WHERE id=%s", (int(s_row['installment_id']),))
                        base_due_str = orig_inst[0] if orig_inst and orig_inst[0] else get_egypt_time().strftime("%Y/%m/%d")
                        try:
                            base_due_dt = datetime.strptime(base_due_str, "%Y/%m/%d")
                        except Exception:
                            base_due_dt = get_egypt_time()

                        db_execute(
                            "UPDATE UnitInstallments SET status='ملغي (تم تقسيم الربع بموافقة المالك)', collection_stage='تم السداد / مغلق' WHERE id=%s",
                            (int(s_row['installment_id']),)
                        )
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

    if is_sales:
        with st.form(f"{key_prefix}req_quarter_split_form"):
            st.markdown("#### 📝 تقديم طلب استثناء لمالك الشركة لتقسيم ربع تنفيذ لمساهم (خاص بخدمة العملاء)")
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
                        st.session_state.get('username', 'خدمة العملاء'), get_egypt_time().strftime("%Y/%m/%d")
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

# ==========================================
# 6. منظومة اتحاد الملاك والأولوية
# ==========================================
def calculate_shareholder_priority_ranking(sh_df, inst_df, project_filter="الكل"):
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
                        speed_days_list.append((p_dt - d_dt).days)
                    except Exception:
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
    
    can_add_clients_or_installments = is_sales
    
    st.header("🤝 منظومة اتحاد الملاك المساهمين، الأرباع الـ 4، وأولوية اختيار الوحدات")
    
    crm_tabs = st.tabs([
        "🥇 أولوية اختيار الوحدات المميزة وكشف الحساب",
        "🏗️ مراحل التنفيذ والأرباع الـ 4 والتحصيل", 
        "👑 استثناء المالك لتقسيم ربع التنفيذ",
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

    with crm_tabs[0]:
        st.subheader("🥇 ترتيب أولوية الملاك المساهمين لاختيار الوحدات المميزة (حسب أسبقية السداد)")
        st.info("💡 يرتب النظام الملاك المساهمين داخل كل اتحاد آلياً بناءً على **نسبة الالتزام، السداد الكامل للربع بدون تقسيم، وأسبقية تاريخ السداد الفعلي**.")

        proj_filter_list = ["الكل"] + [f"اتحاد {i}" for i in range(1, 46)]
        sel_proj_rank = st.selectbox("🏗️ اختر المشروع (الاتحاد):", proj_filter_list, key=f"{key_prefix}proj_rank_sel")

        rank_df = calculate_shareholder_priority_ranking(sh_df, inst_df, project_filter=sel_proj_rank)
        if not rank_df.empty:
            disp_rank = rank_df[['priority_badge', 'project_name', 'name', 'land_share_pct', 'total_required', 'total_paid', 'paid_ratio', 'last_paid_date', 'assigned_unit']].copy()
            disp_rank.columns = ['أولوية اختيار الوحدة', 'الاتحاد', 'اسم المالك المساهم', 'نسبة الأرض %', 'إجمالي المطالبات', 'إجمالي المسدد', 'نسبة السداد %', 'تاريخ آخر سداد فعلي', 'الوحدة المخصصة له']
            st.dataframe(disp_rank, use_container_width=True, hide_index=True)

            if is_sales:
                with st.expander("🏢 تثبيت وتخصيص الوحدة المختارة للمساهم (حسب أولويته)"):
                    ac1, ac2, ac3 = st.columns([2, 2, 1])
                    sh_alloc_opts = rank_df['id'].astype(str) + " - " + rank_df['name'] + " (" + rank_df['priority_badge'] + ")"
                    sel_sh_alloc = ac1.selectbox("اختر المساهم:", sh_alloc_opts, key=f"{key_prefix}alloc_sh")
                    chosen_unit_txt = ac2.text_input("الوحدة المميزة المختارة:", key=f"{key_prefix}alloc_u")
                    if ac3.button("تثبيت الوحدة ✅", key=f"{key_prefix}btn_alloc_u", type="primary"):
                        sh_id_alloc = int(sel_sh_alloc.split(" - ")[0])
                        db_execute("UPDATE Shareholders SET assigned_unit=%s WHERE id=%s", (chosen_unit_txt.strip(), sh_id_alloc))
                        st.success("تم تثبيت الوحدة المختارة للمساهم بنجاح!")
                        st.rerun()

            html_rank = generate_html_report(f"تقرير أولوية الملاك المساهمين لاختيار الوحدات المميزة ({sel_proj_rank})", disp_rank)
            st.download_button("🖨️ طباعة كشف الأولوية (PDF)", data=html_rank, file_name="Shareholders_Priority.html", mime="text/html", key=f"{key_prefix}dl_prio_pdf")
        else:
            st.info("لا يوجد ملاك مساهمين مسجلين في هذا الاتحاد حالياً.")

        st.divider()
        st.subheader("📄 إصدار كشف حساب تفصيلي لمالك مساهم (PDF)")
        all_sh_names = sorted(list(set(
            (sh_df['name'].dropna().tolist() if not sh_df.empty else []) +
            (inst_df['client_name'].dropna().tolist() if not inst_df.empty else [])
        )))
        all_sh_names = [n for n in all_sh_names if str(n).strip() != ""]

        if all_sh_names:
            sel_sh_stmt = st.selectbox("👤 اختر المالك المساهم:", all_sh_names, key=f"{key_prefix}sh_stmt_sel")
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

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("📐 نسبة المشاركة", f"{sh_pct_val:.2f}% ({sh_proj_val})")
            m2.metric("💰 إجمالي المطالبات", f"{tot_req:,.2f} {main_curr}")
            m3.metric("✅ إجمالي المسدد", f"{tot_paid:,.2f} {main_curr}")
            m4.metric("⏳ المتبقي", f"{tot_rem:,.2f} {main_curr}")

            if not sh_inst_all.empty:
                stmt_tbl = sh_inst_all[['project_name', 'phase_name', 'quarter_name', 'amount', 'currency', 'due_date', 'paid_date', 'status', 'collection_stage']].copy()
                stmt_tbl.columns = ['الاتحاد', 'المرحلة', 'الربع / الدفعة', 'المبلغ', 'العملة', 'تاريخ الاستحقاق', 'تاريخ السداد الفعلي', 'حالة الدفع', 'مرحلة المتابعة']
                st.dataframe(stmt_tbl, use_container_width=True, hide_index=True)

                extra_sum = f"""
                <div class="summary-box">
                    <div class="summary-item"><span>اسم المالك المساهم</span><strong>{sel_sh_stmt}</strong></div>
                    <div class="summary-item"><span>المشروع ونسبة الأرض</span><strong>{sh_proj_val} ({sh_pct_val}%)</strong></div>
                    <div class="summary-item"><span>إجمالي المسدد</span><strong style="color:green;">{tot_paid:,.2f} {main_curr}</strong></div>
                    <div class="summary-item"><span>المتبقي</span><strong style="color:#b80000;">{tot_rem:,.2f} {main_curr}</strong></div>
                </div>
                """
                html_sh_stmt = generate_html_report(f"كشف حساب - {sel_sh_stmt}", stmt_tbl, extra_summary_html=extra_sum)
                st.download_button("🖨️ طباعة كشف الحساب (PDF)", data=html_sh_stmt, file_name=f"Statement_{sel_sh_stmt}.html", mime="text/html", type="primary", use_container_width=True, key=f"{key_prefix}dl_sh_stmt_btn")

    with crm_tabs[1]:
        st.subheader("🏗️ مراحل التنفيذ (الأرباع الـ 4) ومتابعة التحصيل والتصعيد")
        
        if can_add_clients_or_installments:
            col_q_auto, col_q_single = st.columns(2)
            with col_q_auto:
                with st.expander("⚡ توزيع تكلفة ربع تنفيذ آلياً (خدمة العملاء)", expanded=True):
                    with st.form(f"{key_prefix}auto_dist_form"):
                        q_proj = st.selectbox("المشروع (الاتحاد)", [f"اتحاد {i}" for i in range(1, 46)], key=f"{key_prefix}ap_proj")
                        q_phase = st.text_input("مرحلة التنفيذ", value="مرحلة الإنشاءات")
                        q_quarter = st.selectbox("الربع", QUARTER_OPTIONS, key=f"{key_prefix}ap_q")
                        
                        qc1, qc2 = st.columns(2)
                        q_total_cost = qc1.number_input("إجمالي التكلفة للمشروع", min_value=0.0, step=10000.0)
                        q_curr = qc2.selectbox("العملة", CURRENCY_OPTIONS, key=f"{key_prefix}ap_curr")
                        q_due = st.date_input("تاريخ استحقاق السداد")
                        
                        if st.form_submit_button("توزيع الربع آلياً 📊", type="primary", use_container_width=True):
                            proj_shs = sh_df[sh_df['project_name'] == q_proj] if not sh_df.empty else pd.DataFrame()
                            if proj_shs.empty:
                                st.error("⚠️ لا يوجد ملاك مساهمين مسجلين في هذا الاتحاد.")
                            elif q_total_cost <= 0:
                                st.error("يرجى إدخال التكلفة.")
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
                                st.success(f"✅ تم التوزيع على ({count_inserted}) مساهم بنجاح!")
                                st.rerun()

            with col_q_single:
                with st.expander("➕ تسجيل مطالبة لمالك محدد (خدمة العملاء)", expanded=True):
                    with st.form(f"{key_prefix}single_sh_form"):
                        s_proj = st.selectbox("المشروع (الاتحاد)", [f"اتحاد {i}" for i in range(1, 46)], key=f"{key_prefix}sp_proj")
                        sh_names_in_list = sh_df['name'].dropna().unique().tolist() if not sh_df.empty else []
                        s_sh_name = st.selectbox("اختر المالك", sh_names_in_list, key=f"{key_prefix}sp_sh") if sh_names_in_list else st.text_input("اسم المالك")
                        
                        sc1, sc2 = st.columns(2)
                        s_phase = sc1.text_input("مرحلة التنفيذ", value="مرحلة الإنشاءات", key=f"{key_prefix}sp_ph")
                        s_quarter = sc2.selectbox("الربع", QUARTER_OPTIONS, key=f"{key_prefix}sp_q")
                        
                        sc3, sc4, sc5 = st.columns(3)
                        s_amt = sc3.number_input("المبلغ", min_value=0.0, step=5000.0)
                        s_curr = sc4.selectbox("العملة", CURRENCY_OPTIONS, key=f"{key_prefix}sp_curr")
                        s_due = sc5.date_input("الاستحقاق", key=f"{key_prefix}sp_due")
                        
                        if st.form_submit_button("إضافة ➕", type="primary", use_container_width=True):
                            if s_sh_name and s_amt > 0:
                                note_desc = f"{s_phase} - {s_quarter}"
                                db_execute("""
                                    INSERT INTO UnitInstallments 
                                    (unit_code, project_name, client_name, phase_name, quarter_name, amount, currency, due_date, paid_date, status, notes, collection_stage, call_notes, is_split_exception)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', 'مستحق (لم يُدفع)', %s, 'متابعة خدمة العملاء', '', FALSE)
                                """, (s_proj, s_proj, s_sh_name.strip(), s_phase, s_quarter, s_amt, s_curr, s_due.strftime("%Y/%m/%d"), note_desc))
                                st.success("تم التسجيل بنجاح!")
                                st.rerun()
                            else:
                                st.error("أكمل البيانات.")
        else:
            st.info("👁️ **وضع الاطلاع:** إضافة وجدولة الأقساط متاحة لخدمة العملاء فقط.")

        if not inst_df.empty:
            unpaid_df = inst_df[~inst_df['status'].isin(['مدفوع', 'مدفوع في الموعد', 'مدفوع متأخر']) & (~inst_df['status'].str.contains('ملغي', na=False))]
            
            if is_sales and not unpaid_df.empty:
                st.markdown("#### 📞 متابعة وتصعيد خدمة العملاء")
                cs_df = unpaid_df[unpaid_df['collection_stage'].isin(['متابعة خدمة العملاء', 'تمت المكالمة الأولى (خدمة العملاء)', 'تمت المكالمة الثانية (خدمة العملاء)'])]
                if not cs_df.empty:
                    cs_opts = cs_df['id'].astype(str) + " - " + cs_df['client_name'].fillna('') + " | " + cs_df['project_name'].fillna('') + " (" + cs_df['quarter_name'].fillna('') + ")"
                    sel_cs_inst = st.selectbox("اختر مطالبة:", cs_opts, key=f"{key_prefix}cs_esc_sel")
                    cs_note_input = st.text_input("ملاحظة المكالمة:", key=f"{key_prefix}cs_note_in")
                    b1, b2, b3, b4 = st.columns(4)
                    target_id = int(sel_cs_inst.split(" - ")[0])
                    old_notes = cs_df[cs_df['id'] == target_id].iloc[0]['call_notes'] or ""
                    now_tag = get_egypt_time().strftime("%Y/%m/%d %H:%M")
                    if b1.button("📞 1. مكالمة 1", key=f"{key_prefix}b1_cs", use_container_width=True):
                        new_log = f"{old_notes} | [مكالمة 1 {now_tag}: {cs_note_input}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='تمت المكالمة الأولى (خدمة العملاء)', status='متأخر', call_notes=%s WHERE id=%s", (new_log, target_id))
                        st.rerun()
                    if b2.button("📞 2. مكالمة 2", key=f"{key_prefix}b2_cs", use_container_width=True):
                        new_log = f"{old_notes} | [مكالمة 2 {now_tag}: {cs_note_input}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='تمت المكالمة الثانية (خدمة العملاء)', status='متأخر', call_notes=%s WHERE id=%s", (new_log, target_id))
                        st.rerun()
                    if b3.button("⚖️ 3. للشؤون القانونية", key=f"{key_prefix}b3_cs", type="primary", use_container_width=True):
                        new_log = f"{old_notes} | [قانونية {now_tag}: {cs_note_input}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='محول للشؤون القانونية', status='متأخر', call_notes=%s WHERE id=%s", (new_log, target_id))
                        st.rerun()
                    if b4.button("✅ تم السداد", key=f"{key_prefix}b4_cs", use_container_width=True):
                        db_execute("UPDATE UnitInstallments SET status='مدفوع في الموعد', paid_date=%s, collection_stage='تم السداد / مغلق' WHERE id=%s", (get_egypt_time().strftime("%Y/%m/%d"), target_id))
                        st.rerun()

            if is_legal and not unpaid_df.empty:
                st.markdown("#### ⚖️ مطالبات المساهمين المحولة للشؤون القانونية من خدمة العملاء")
                leg_df = unpaid_df[unpaid_df['collection_stage'].isin(['محول للشؤون القانونية', 'تمت مكالمة الشؤون القانونية'])]
                if not leg_df.empty:
                    leg_opts = leg_df['id'].astype(str) + " - المساهم: " + leg_df['client_name'].fillna('') + " | " + leg_df['project_name'].fillna('') + " (" + leg_df['quarter_name'].fillna('') + ")"
                    sel_leg_inst = st.selectbox("اختر الملف:", leg_opts, key=f"{key_prefix}leg_esc_sel")
                    target_leg_id = int(sel_leg_inst.split(" - ")[0])
                    
                    target_row = leg_df[leg_df['id'] == target_leg_id].iloc[0]
                    old_leg_notes = target_row['call_notes'] or ""
                    current_stage = target_row['collection_stage']
                    
                    st.warning(f"**سجل المكالمات السابق:** {old_leg_notes}")
                    leg_note_input = st.text_input("ملاحظة الشؤون القانونية الجديدة:", key=f"{key_prefix}leg_note_in")
                    
                    lb1, lb2, lb3 = st.columns(3)
                    now_tag = get_egypt_time().strftime("%Y/%m/%d %H:%M")
                    
                    if lb1.button("📞 تسجيل مكالمة/إنذار قانوني", key=f"{key_prefix}lb1", use_container_width=True):
                        new_log = f"{old_leg_notes} | [إنذار قانوني {now_tag}: {leg_note_input}]".strip(" |")
                        db_execute("UPDATE UnitInstallments SET collection_stage='تمت مكالمة الشؤون القانونية', call_notes=%s WHERE id=%s", (new_log, target_leg_id))
                        st.rerun()
                        
                    if current_stage == 'تمت مكالمة الشؤون القانونية':
                        if lb2.button("👑 تصعيد لمالك الشركة", key=f"{key_prefix}lb2", type="primary", use_container_width=True):
                            new_log = f"{old_leg_notes} | [تصعيد للمالك بعد محاولة {now_tag}: {leg_note_input}]".strip(" |")
                            db_execute("UPDATE UnitInstallments SET collection_stage='محول للمالك (لتدخل الإدارة العليا)', call_notes=%s WHERE id=%s", (new_log, target_leg_id))
                            st.rerun()
                    else:
                        lb2.info("⚠️ زر تصعيد للمالك سيظهر بعد تسجيل مكالمة/إنذار أولاً.")
                        
                    if lb3.button("✅ تم السداد والتسوية", key=f"{key_prefix}lb3", use_container_width=True):
                        db_execute("UPDATE UnitInstallments SET status='مدفوع متأخر', paid_date=%s, collection_stage='تم السداد / مغلق' WHERE id=%s", (get_egypt_time().strftime("%Y/%m/%d"), target_leg_id))
                        st.rerun()
                else:
                    st.success("🎉 لا توجد ملفات متأخرات محولة من خدمة العملاء للشؤون القانونية حالياً.")

            if is_owner and not unpaid_df.empty:
                own_esc_df = unpaid_df[unpaid_df['collection_stage'] == 'محول للمالك (لتدخل الإدارة العليا)']
                if not own_esc_df.empty:
                    st.error(f"🚨 يوجد ({len(own_esc_df)}) ملف متأخرات تم تصعيده إليك بعد محاولات خدمة العملاء والشؤون القانونية!")
                    for _, o_row in own_esc_df.iterrows():
                        with st.expander(f"👑 مصعد للمالك: المساهم ({o_row['client_name']}) | {o_row['project_name']} - {o_row['quarter_name']}", expanded=True):
                            st.warning(f"**سجل المكالمات:** {o_row['call_notes']}")
                            oc1, oc2 = st.columns(2)
                            if oc1.button("✅ تم السداد بتدخل المالك", key=f"{key_prefix}own_set_{o_row['id']}", type="primary", use_container_width=True):
                                db_execute("UPDATE UnitInstallments SET status='مدفوع متأخر', paid_date=%s, collection_stage='تم السداد / مغلق' WHERE id=%s", (get_egypt_time().strftime("%Y/%m/%d"), o_row['id']))
                                st.rerun()
                            if oc2.button("🔄 مهلة وإعادة لخدمة العملاء", key=f"{key_prefix}own_ret_{o_row['id']}", use_container_width=True):
                                db_execute("UPDATE UnitInstallments SET collection_stage='متابعة خدمة العملاء' WHERE id=%s", (o_row['id'],))
                                st.rerun()

            if is_sales or is_accountant:
                with st.expander("💳 تأكيد سداد وتحديث حالة الدفع (يدوياً)"):
                    up1, up2, up3, up4 = st.columns([2.5, 1.5, 1.5, 1])
                    inst_opts = inst_df['id'].astype(str) + " - " + inst_df['client_name'].fillna('') + " | " + inst_df['quarter_name'].fillna('')
                    sel_inst_to_upd = up1.selectbox("اختر دفعة:", inst_opts, key=f"{key_prefix}upd_q_sel")
                    new_inst_st = up2.selectbox("حالة الدفع:", ["مدفوع في الموعد", "مدفوع متأخر", "مستحق (لم يُدفع)", "متأخر"], key=f"{key_prefix}upd_q_st")
                    actual_paid_dt = up3.date_input("تاريخ السداد الفعلي", key=f"{key_prefix}upd_q_dt")
                    if up4.button("تأكيد ✅", key=f"{key_prefix}btn_upd_q", type="primary"):
                        inst_id_val = int(sel_inst_to_upd.split(" - ")[0])
                        paid_dt_val = actual_paid_dt.strftime("%Y/%m/%d") if "مدفوع" in new_inst_st else ""
                        new_stage = "تم السداد / مغلق" if "مدفوع" in new_inst_st else "متابعة خدمة العملاء"
                        db_execute("UPDATE UnitInstallments SET status=%s, paid_date=%s, collection_stage=%s WHERE id=%s", (new_inst_st, paid_dt_val, new_stage, inst_id_val))
                        st.success("تم تأكيد السداد بنجاح!")
                        st.rerun()

            if can_add_clients_or_installments:
                with st.expander("🗑️ حذف مطالبة مضافة بالخطأ (خدمة العملاء)"):
                    del_c1, del_c2 = st.columns([3, 1])
                    all_inst_opts = inst_df['id'].astype(str) + " - المساهم: " + inst_df['client_name'].fillna('') + " | " + inst_df['quarter_name'].fillna('')
                    sel_inst_del = del_c1.selectbox("اختر المطالبة:", all_inst_opts, key=f"{key_prefix}del_inst_sel")
                    if del_c2.button("حذف 🗑️", key=f"{key_prefix}btn_del_inst"):
                        inst_id_del = int(sel_inst_del.split(" - ")[0])
                        db_execute("DELETE FROM UnitInstallments WHERE id=%s", (inst_id_del,))
                        st.success("تم الحذف بنجاح!")
                        st.rerun()

            disp_inst = inst_df[['project_name', 'client_name', 'phase_name', 'quarter_name', 'amount', 'currency', 'due_date', 'paid_date', 'status', 'collection_stage', 'notes']].copy()
            disp_inst.columns = ['الاتحاد', 'المالك المساهم', 'المرحلة', 'الربع (1-4)', 'المبلغ المطلوب', 'العملة', 'تاريخ الاستحقاق', 'تاريخ السداد الفعلي', 'حالة الدفع', 'مرحلة المتابعة', 'ملاحظات']
            st.dataframe(disp_inst, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد مطالبات أرباع تنفيذ مسجلة بعد.")

    with crm_tabs[2]:
        render_quarter_split_exception_module(mode=mode, key_prefix=key_prefix)

    with crm_tabs[3]:
        st.subheader("🤝 سجل الملاك المساهمين وحصص المشاركة في الأرض (%)")
        if can_add_clients_or_installments:
            with st.form(f"{key_prefix}add_shareholder_form"):
                st.markdown("#### ➕ تسجيل مالك مساهم جديد (صلاحية خدمة العملاء فقط)")
                c1, c2, c3 = st.columns(3)
                sh_name = c1.text_input("اسم المالك المساهم رباعي *")
                sh_phone = c2.text_input("رقم الهاتف / واتساب *")
                sh_proj = c3.selectbox("المشروع (الاتحاد) *", [f"اتحاد {i}" for i in range(1, 46)], key=f"{key_prefix}sh_proj_in")
                
                c4, c5, c6 = st.columns(3)
                sh_pct = c4.number_input("نسبة الأرض (%) *", min_value=0.1, max_value=100.0, value=10.0, step=0.5)
                sh_land_amt = c5.number_input("قيمة الحصة في الأرض", min_value=0.0, step=10000.0)
                sh_curr = c6.selectbox("العملة", CURRENCY_OPTIONS, key=f"{key_prefix}sh_curr_in")
                
                c7, c8, c9 = st.columns(3)
                sh_nid = c7.text_input("الرقم القومي")
                sh_unit = c8.text_input("الوحدة المخصصة", value="تحدد حسب أولوية السداد")
                sh_notes = c9.text_input("ملاحظات")
                
                if st.form_submit_button("حفظ بيانات المالك 💾", type="primary"):
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
                        
                        st.success(f"تم حفظ بيانات المالك ({sh_name}) بنجاح!")
                        st.rerun()
                    else:
                        st.error("يرجى إدخال اسم المالك ورقم الهاتف.")
        else:
            st.info("👁️ **وضع الاطلاع:** إضافة الملاك المساهمين متاحة لقسم **خدمة العملاء** فقط.")

        if not sh_df.empty:
            proj_pct_sum = sh_df.groupby('project_name').agg(عدد_المساهمين=('id', 'count'), إجمالي_النسب_المسجلة=('land_share_pct', 'sum')).reset_index()
            proj_pct_sum['النسبة المتبقية %'] = (100.0 - proj_pct_sum['إجمالي_النسب_المسجلة']).round(2)
            st.dataframe(proj_pct_sum, use_container_width=True, hide_index=True)

            if can_add_clients_or_installments:
                with st.expander("🗑️ حذف مالك مساهم (خدمة العملاء)"):
                    dc1, dc2, dc3 = st.columns([2, 2, 1])
                    sh_del_opts = sh_df['id'].astype(str) + " - " + sh_df['name'].fillna('')
                    sel_sh_del = dc1.selectbox("اختر المساهم:", sh_del_opts, key=f"{key_prefix}sel_sh_del")
                    cascade_sh = dc2.checkbox("مسح مطالبات الأرباع المرتبطة به أيضاً", value=True, key=f"{key_prefix}casc_sh")
                    if dc3.button("حذف 🗑️", key=f"{key_prefix}btn_del_sh"):
                        sh_id_del = int(sel_sh_del.split(" - ")[0])
                        sh_row_del = sh_df[sh_df['id'] == sh_id_del].iloc[0]
                        db_execute("DELETE FROM Shareholders WHERE id=%s", (sh_id_del,))
                        if cascade_sh:
                            db_execute("DELETE FROM UnitInstallments WHERE client_name=%s AND project_name=%s", (sh_row_del['name'], sh_row_del['project_name']))
                        st.success("تم الحذف بنجاح!")
                        st.rerun()

            disp_sh = sh_df[['project_name', 'name', 'phone', 'land_share_pct', 'land_share_amount', 'currency', 'assigned_unit']].copy()
            disp_sh.columns = ['الاتحاد', 'اسم المالك', 'رقم الهاتف', 'النسبة %', 'الحصة', 'العملة', 'الوحدة المخصصة']
            st.dataframe(disp_sh, use_container_width=True, hide_index=True)

# ==========================================
# 7. الشاشة المشتركة للموظفين (البصمة والتقارير)
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
    except Exception:
        is_exempt = False
        
    try:
        used_leaves_year = db_fetchone("SELECT COUNT(*) FROM Permissions WHERE emp_id=%s AND type='إجازة' AND date LIKE %s", (emp_id, f"{current_year}/%"))[0]
    except Exception:
        used_leaves_year = 0
    
    try:
        has_checked_in = db_fetchone("SELECT COUNT(*) FROM WebAttendance WHERE emp_id=%s AND date=%s AND action='حضور'", (emp_id, today_date))[0] > 0
        if not has_checked_in and (now_dt.hour > 11 or (now_dt.hour == 11 and now_dt.minute >= 30)):
            st.error("⏰ **تنبيه عاجل:** لقد تجاوزت الساعة 11:30 صباحاً ولم تقم بتسجيل حضورك اليوم!")
    except Exception:
        pass

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"رصيد الإجازات ({current_year})", f"{balance} يوم", f"استنفاد {used_leaves_year} يوم")
    c2.metric("التأخيرات الكلية", f"{format_hhmm(delay_mins)} ساعة")
    c3.metric("الوقت الإضافي", f"{format_hhmm(overtime_mins)} ساعة")
    try:
        pending = db_fetchone("SELECT COUNT(*) FROM Requests WHERE emp_id=%s AND status='قيد الانتظار'", (emp_id,))[0]
        c4.metric("طلبات معلقة", pending)
    except Exception:
        c4.metric("طلبات معلقة", 0)
    
    st.divider()
    sub_nav = st.radio("العمليات المتاحة:", ["📍 بصمة وتقارير وإنجاز مهام", "📝 تقديم طلب جديد", "🌴 سجلاتي"], horizontal=True)
    
    if sub_nav == "📍 بصمة وتقارير وإنجاز مهام":
        locations = db_fetchall("SELECT name, lat, lon, radius FROM Locations ORDER BY name")
        if not locations:
            st.error("لم يتم تسجيل فروع للشركة بعد.")
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
                        except Exception:
                            has_checked_in = False

                        if not has_checked_in:
                            if st.button("🟢 تسجيل حضور اليوم", use_container_width=True):
                                db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo) VALUES (%s, %s, %s, 'حضور', %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri))
                                st.success("تم تسجيل الحضور بنجاح!")
                                st.rerun() 
                        else:
                            st.info("✅ تم تسجيل حضورك اليوم بنجاح.")
                            conn = get_db_connection()
                            try:
                                tasks = pd.read_sql_query("SELECT id, assigner, project_name, task_desc, due_date FROM Tasks WHERE emp_id=%s AND status='قيد التنفيذ'", conn, params=(emp_id,))
                            except Exception:
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
                                                st.success("تم الإغلاق وإرسال التقرير للمدير!")
                                                st.rerun()
                                            else:
                                                st.error("اكتب تقرير الإنجاز أولاً!")
                            
                            st.markdown("---")
                            st.markdown("### 📝 إضافة تقرير حر أو تسجيل انصراف")
                            selected_proj = st.selectbox("المشروع / مهامك", [f"اتحاد {i}" for i in range(1, 46)] + ["أخرى"])
                            
                            if is_exempt:
                                st.info("💡 حسابك مُعفى من إجبارية تقديم التقرير اليومي، يمكنك تسجيل الانصراف مباشرة.")
                                daily_rep = st.text_area("تفاصيل الإنجاز اليومي (اختياري)", placeholder="يمكنك تركه فارغاً...")
                            else:
                                daily_rep = st.text_area("تفاصيل الإنجاز اليومي (إجباري)*", placeholder="يجب كتابة ما أنجزته اليوم...")

                            c_btn1, c_btn2 = st.columns(2)
                            with c_btn1:
                                if st.button("➕ رفع التقرير الحر (مستمر بالعمل)", use_container_width=True):
                                    if is_exempt or daily_rep.strip():
                                        db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'تقرير', %s, %s, %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri, selected_proj, daily_rep))
                                        st.success("تم حفظ إنجازك!")
                                    else:
                                        st.error("❌ يجب كتابة التقرير اليومي أولاً!")
                            with c_btn2:
                                if st.button("🔴 تسجيل انصراف نهائي اليوم", use_container_width=True):
                                    if is_exempt or daily_rep.strip():
                                        db_execute("INSERT INTO WebAttendance (emp_id, date, time, action, distance, location_name, photo, project_name, daily_report) VALUES (%s, %s, %s, 'انصراف', %s, %s, %s, %s, %s)", (emp_id, today_date, now_dt.strftime("%H:%M"), int(min_distance), closest_loc_name, photo_uri, selected_proj, daily_rep))
                                        st.success("تم تسجيل الانصراف بنجاح!")
                                        st.rerun() 
                                    else:
                                        st.error("❌ لا يمكنك تسجيل الانصراف بدون التقرير اليومي!")
                else:
                    st.error("❌ أنت خارج النطاق المسموح للشركة.")
            else:
                st.info("جاري تحديد موقعك الجغرافي... تأكد من تشغيل الـ GPS.")

    elif sub_nav == "📝 تقديم طلب جديد":
        with st.form("emp_req"):
            req_type = st.selectbox("النوع", ["إجازة", "مأمورية", "إذن", "عمل من المنزل"])
            req_date = st.date_input("التاريخ")
            notes = st.text_input("السبب")
            if st.form_submit_button("إرسال الطلب", type="primary"):
                if req_type == "إجازة" and balance <= 0:
                    st.error("❌ استنفدت رصيد إجازاتك!")
                else:
                    db_execute("INSERT INTO Requests (emp_id, date, req_type, notes, status) VALUES (%s, %s, %s, %s, 'قيد الانتظار')", (emp_id, req_date.strftime("%Y/%m/%d"), req_type, notes))
                    st.success("تم الإرسال لمديرك المباشر.")
                
    elif sub_nav == "🌴 سجلاتي":
        conn = get_db_connection()
        try:
            df = pd.read_sql_query("SELECT id, date, req_type, status FROM Requests WHERE emp_id=%s ORDER BY id DESC", conn, params=(emp_id,))
        except Exception:
            df = pd.DataFrame()
        conn.close()
        
        if not df.empty:
            pending_my_reqs = df[df['status'] == 'قيد الانتظار']
            if not pending_my_reqs.empty:
                with st.expander("🗑️ إلغاء طلب قيد الانتظار"):
                    rc1, rc2 = st.columns([3, 1])
                    r_opts = pending_my_reqs['id'].astype(str) + " - " + pending_my_reqs['req_type'] + " (" + pending_my_reqs['date'] + ")"
                    sel_r_del = rc1.selectbox("اختر الطلب:", r_opts)
                    if rc2.button("إلغاء الطلب 🗑️"):
                        r_id_del = int(sel_r_del.split(" - ")[0])
                        db_execute("DELETE FROM Requests WHERE id=%s", (r_id_del,))
                        st.success("تم إلغاء الطلب بنجاح!")
                        st.rerun()
            disp_r = df.drop(columns=['id'])
            disp_r.columns = ['التاريخ', 'نوع الطلب', 'الحالة']
            st.dataframe(disp_r, hide_index=True, use_container_width=True)
        else:
            st.info("لا توجد طلبات مسجلة لك.")

# ==========================================
# 8. دوال الشؤون القانونية (العقود، التوكيلات، الشيكات)
# ==========================================
def render_legal_archive_module():
    st.subheader("📜 أرشفة العقود والتوكيلات القانونية")
    try:
        db_execute('''CREATE TABLE IF NOT EXISTS LegalArchive (
            id SERIAL PRIMARY KEY, doc_type TEXT, client_name TEXT, project_name TEXT, 
            doc_details TEXT, file_data TEXT, date_added TEXT
        )''')
    except Exception:
        pass

    with st.form("add_legal_doc"):
        c1, c2, c3 = st.columns(3)
        doc_type = c1.selectbox("نوع المستند", ["توكيل رسمي", "عقد وحدة / أرض", "مستندات ملكية", "أخرى"])
        client_name = c2.text_input("اسم العميل / المالك")
        project_name = c3.selectbox("المشروع", ["الكل", "الشركة"] + [f"اتحاد {i}" for i in range(1, 46)])
        
        c4, c5 = st.columns([2, 1])
        doc_details = c4.text_input("تفاصيل المستند (مثال: توكيل عام قضايا رقم 1234 لسنة 2026)")
        doc_file = c5.file_uploader("إرفاق المستند (PDF/صورة)", type=['pdf', 'png', 'jpg', 'jpeg'])
        
        if st.form_submit_button("حفظ في الأرشيف 💾", type="primary"):
            if client_name.strip() and doc_details.strip():
                file_b64 = ""
                if doc_file:
                    file_b64, err = encode_and_compress_uploaded_file(doc_file)
                db_execute("INSERT INTO LegalArchive (doc_type, client_name, project_name, doc_details, file_data, date_added) VALUES (%s, %s, %s, %s, %s, %s)", 
                           (doc_type, client_name.strip(), project_name, doc_details.strip(), file_b64, get_egypt_time().strftime("%Y/%m/%d")))
                st.success("تم أرشفة المستند بنجاح!")
                st.rerun()
            else:
                st.error("أدخل اسم العميل وتفاصيل المستند.")

    conn = get_db_connection()
    try:
        archive_df = pd.read_sql_query("SELECT id, doc_type, client_name, project_name, doc_details, date_added, file_data FROM LegalArchive ORDER BY id DESC", conn)
    except Exception:
        archive_df = pd.DataFrame()
    conn.close()

    if not archive_df.empty:
        st.markdown("#### 📂 السجل المؤرشف")
        for _, row in archive_df.iterrows():
            with st.expander(f"📁 {row['doc_type']} | {row['client_name']} | {row['project_name']} ({row['date_added']})"):
                st.write(f"**التفاصيل:** {row['doc_details']}")
                col_btn1, col_btn2 = st.columns(2)
                if pd.notna(row['file_data']) and len(str(row['file_data'])) > 10:
                    try:
                        decoded_file = base64.b64decode(row['file_data'])
                        col_btn1.download_button("📥 تحميل المستند", data=decoded_file, file_name=f"Document_{row['id']}.pdf", mime="application/octet-stream", key=f"dl_doc_{row['id']}")
                    except Exception:
                        pass
                if col_btn2.button("🗑️ حذف المستند", key=f"del_doc_{row['id']}"):
                    db_execute("DELETE FROM LegalArchive WHERE id=%s", (row['id'],))
                    st.rerun()
    else:
        st.info("لا توجد مستندات في الأرشيف القانوني حالياً.")

def render_cheques_module(can_edit=True):
    st.subheader("🏦 إدارة محفظة الشيكات البنكية")
    if can_edit:
        with st.form("add_cheque_form"):
            c1, c2, c3 = st.columns(3)
            ch_unit = c1.text_input("المشروع / رقم الوحدة")
            ch_client = c2.text_input("اسم العميل (صاحب الشيك)")
            ch_num = c3.text_input("رقم الشيك والبنك")
            
            c4, c5, c6 = st.columns(3)
            ch_amt = c4.number_input("قيمة الشيك", min_value=0.0, step=1000.0)
            ch_curr = c5.selectbox("العملة", CURRENCY_OPTIONS, key="chq_curr_m")
            ch_due = c6.date_input("تاريخ استحقاق الشيك")
            
            c7, c8 = st.columns(2)
            ch_status = c7.selectbox("حالة الشيك", ["بالحافظة (تحت التحصيل)", "تم الصرف والتحصيل", "مرتد / مرفوض", "مسلم للعميل"])
            ch_file = c8.file_uploader("صورة الشيك", type=['png', 'jpg', 'jpeg', 'pdf'])
            
            if st.form_submit_button("حفظ الشيك في المحفظة 💾", type="primary"):
                if ch_client.strip() and ch_num.strip() and ch_amt > 0:
                    file_b64 = ""
                    if ch_file:
                        file_b64, err = encode_and_compress_uploaded_file(ch_file)
                    db_execute(
                        "INSERT INTO Cheques (unit_code, client_name, cheque_number, amount, currency, due_date, file_data, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (ch_unit.strip(), ch_client.strip(), ch_num.strip(), ch_amt, ch_curr, ch_due.strftime("%Y/%m/%d"), file_b64, ch_status)
                    )
                    st.success("تم حفظ الشيك بنجاح!")
                    st.rerun()
                else:
                    st.error("أكمل بيانات الشيك.")

    conn = get_db_connection()
    try:
        chq_df = pd.read_sql_query("SELECT id, unit_code, client_name, cheque_number, amount, COALESCE(currency, 'ج.م (EGP)') as currency, due_date, status FROM Cheques ORDER BY due_date ASC", conn)
    except Exception:
        chq_df = pd.DataFrame()
    conn.close()

    if not chq_df.empty:
        if can_edit:
            with st.expander("🔄 تحديث حالة شيك أو حذفه"):
                uc1, uc2, uc3, uc4 = st.columns(4)
                ch_opts = chq_df['id'].astype(str) + " - " + chq_df['client_name'].fillna('') + " (" + chq_df['cheque_number'].fillna('') + ")"
                sel_ch = uc1.selectbox("اختر الشيك:", ch_opts)
                new_ch_st = uc2.selectbox("الحالة الجديدة:", ["تم الصرف والتحصيل", "بالحافظة (تحت التحصيل)", "مرتد / مرفوض", "مسلم للعميل"])
                if uc3.button("تحديث الحالة ✅", key="upd_chq_btn"):
                    ch_id = int(sel_ch.split(" - ")[0])
                    db_execute("UPDATE Cheques SET status=%s WHERE id=%s", (new_ch_st, ch_id))
                    st.rerun()
                if uc4.button("🗑️ حذف الشيك", key="del_chq_btn"):
                    ch_id = int(sel_ch.split(" - ")[0])
                    db_execute("DELETE FROM Cheques WHERE id=%s", (ch_id,))
                    st.rerun()

        disp_chq = chq_df.drop(columns=['id'])
        disp_chq.columns = ['المشروع/الوحدة', 'اسم العميل', 'رقم الشيك', 'المبلغ', 'العملة', 'تاريخ الاستحقاق', 'الحالة']
        st.dataframe(disp_chq, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد شيكات مسجلة حالياً.")
# ==========================================
# 9. لوحة تقارير إنجاز ومهام المشاريع (للمالك والإدارة)
# ==========================================
def render_project_daily_reports():
    st.subheader("🏗️ تقارير إنجاز المشاريع (التقارير اليومية للمهندسين والموظفين)")
    st.info("💡 يمكنك من هنا متابعة ما تم إنجازه يومياً في كل مشروع على حدة من خلال التقارير التي يرفعها الموظفون والمهندسون.")
    
    conn = get_db_connection()
    try:
        projs = db_fetchall("SELECT DISTINCT project_name FROM WebAttendance WHERE project_name IS NOT NULL AND project_name != ''")
        proj_list = ["الكل"] + sorted([p[0] for p in projs if str(p[0]).strip() != ""])
    except Exception:
        proj_list = ["الكل"]
        
    c1, c2 = st.columns(2)
    sel_proj = c1.selectbox("🏢 فلترة حسب المشروع (الاتحاد):", proj_list, key="proj_rep_sel")
    sel_date = c2.date_input("📅 تاريخ التقرير:", value=get_egypt_time().date(), key="proj_rep_dt")
    
    query = """
        SELECT e.name, e.department, w.time, w.action, w.project_name, w.daily_report 
        FROM WebAttendance w 
        JOIN Employees e ON w.emp_id = e.emp_id 
        WHERE w.date = %s AND w.action IN ('تقرير', 'انصراف', 'إنجاز مهمة')
          AND w.daily_report IS NOT NULL AND w.daily_report != ''
    """
    params = [sel_date.strftime("%Y/%m/%d")]
    
    if sel_proj != "الكل":
        query += " AND w.project_name = %s"
        params.append(sel_proj)
        
    query += " ORDER BY w.time DESC"
    
    try:
        rep_df = pd.read_sql_query(query, conn, params=tuple(params))
    except Exception:
        rep_df = pd.DataFrame()
    conn.close()
    
    if not rep_df.empty:
        st.success(f"تم العثور على ({len(rep_df)}) تقرير إنجاز بتاريخ {sel_date.strftime('%Y/%m/%d')}")
        disp_df = rep_df[['project_name', 'name', 'department', 'time', 'action', 'daily_report']].copy()
        disp_df.columns = ['المشروع / الاتحاد', 'اسم الموظف', 'القسم', 'وقت التسجيل', 'نوع الإجراء', 'تفاصيل الإنجاز (التقرير اليومي)']
        st.dataframe(disp_df, use_container_width=True, hide_index=True)
    else:
        st.warning("لا توجد تقارير إنجاز مسجلة في هذا التاريخ للمشروع المحدد.")
