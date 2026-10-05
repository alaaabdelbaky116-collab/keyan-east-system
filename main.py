import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
from datetime import datetime
import os
import sqlite3
import shutil
from PIL import Image
import traceback
import arabic_reshaper
from bidi.algorithm import get_display

# ----------------- دالة ضبط اللغة العربية -----------------
def ar(text):
    """دالة لضبط الحروف والكلمات العربية في الواجهة الحديثة"""
    if not text: return text
    reshaped_text = arabic_reshaper.reshape(str(text))
    return get_display(reshaped_text)

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

current_df = None
CURRENT_USER = None  

OFFICIAL_IN = '11:00'
OFFICIAL_OUT = '18:00'
GRACE_PERIOD_MINS = 60
REQUIRED_HOURS = 7
DEFAULT_ANNUAL_BALANCE = 21
LOGO_FILE = "image_c5a585.png"

# ==========================================
# 1. طبقة قاعدة البيانات
# ==========================================
def init_db():
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS Employees (emp_id TEXT PRIMARY KEY, name TEXT, department TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS Permissions (emp_id TEXT, date TEXT, type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS Holidays (date TEXT PRIMARY KEY, name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS Users (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS WFH_Overtime (emp_id TEXT, date TEXT, hours REAL, task_desc TEXT)''')
    
    c.execute("SELECT COUNT(*) FROM Users")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO Users (username, password, role) VALUES ('admin', 'admin123', 'admin')")
        
    try: c.execute(f"ALTER TABLE Employees ADD COLUMN annual_balance INTEGER DEFAULT {DEFAULT_ANNUAL_BALANCE}")
    except: pass
    conn.commit()
    conn.close()

def upsert_employee(emp_id, name, department):
    conn = sqlite3.connect('hr_system.db')
    conn.execute("INSERT OR IGNORE INTO Employees (emp_id, name, department, annual_balance) VALUES (?, ?, ?, ?)", 
                 (emp_id, name, department, DEFAULT_ANNUAL_BALANCE))
    conn.commit(); conn.close()

def get_all_employees():
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT emp_id, name, annual_balance FROM Employees ORDER BY CAST(emp_id AS INTEGER)")
    emps = c.fetchall()
    conn.close()
    return emps

def get_employee_permissions(emp_id):
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT date, type FROM Permissions WHERE emp_id=?", (emp_id,))
    perms = c.fetchall()
    conn.close()
    return perms

def save_permission_to_db(emp_id, date, p_type):
    conn = sqlite3.connect('hr_system.db')
    conn.execute("INSERT INTO Permissions VALUES (?, ?, ?)", (emp_id, date, p_type))
    conn.commit(); conn.close()

def get_all_holidays():
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT date, name FROM Holidays")
    hols = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return hols

def save_holiday_to_db(date, name):
    conn = sqlite3.connect('hr_system.db')
    conn.execute("INSERT OR REPLACE INTO Holidays (date, name) VALUES (?, ?)", (date, name))
    conn.commit(); conn.close()

def get_wfh_hours(emp_id):
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT date, hours, task_desc FROM WFH_Overtime WHERE emp_id=?", (emp_id,))
    wfh_data = c.fetchall()
    conn.close()
    return wfh_data

def save_wfh_hours_to_db(emp_id, date, hours, task_desc):
    conn = sqlite3.connect('hr_system.db')
    conn.execute("INSERT INTO WFH_Overtime VALUES (?, ?, ?, ?)", (emp_id, date, hours, task_desc))
    conn.commit(); conn.close()

init_db()

# ==========================================
# 2. منطق تحليل الحضور والأوفر تايم
# ==========================================
def calculate_detailed_attendance(file_path):
    try: xls = pd.ExcelFile(file_path)
    except Exception as e:
        messagebox.showerror("خطأ", f"حدث خطأ:\n{e}")
        return None

    extracted_data = []
    time_in_fmt = '%H:%M'
    official_in_dt = datetime.strptime(OFFICIAL_IN, time_in_fmt)
    official_out_dt = datetime.strptime(OFFICIAL_OUT, time_in_fmt)
    required_mins = REQUIRED_HOURS * 60
    company_holidays = get_all_holidays()

    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        if len(df) < 15: continue
            
        for r in range(len(df)):
            for c in range(len(df.columns)):
                val = str(df.iloc[r, c]).strip()
                if val == 'Name' or val == 'الاسم':
                    name = str(df.iloc[r, c + 1]).strip()
                    emp_id = str(df.iloc[r + 1, c + 1]).strip()
                    
                    if name.lower() == 'nan' or not name: continue
                    start_col = c - 6
                    if start_col < 0: continue
                    department = str(df.iloc[r, start_col + 1]).strip()
                    upsert_employee(emp_id, name, department)
                    
                    try: year_month = str(df.iloc[r + 1, start_col + 1]).strip().split('-')[0][:7] 
                    except: year_month = "2026/09" 
                    
                    daily_data = df.iloc[r + 9: r + 40, start_col:start_col+5] 
                    
                    regular_hours, regular_days = 0.0, 0
                    total_shortage_mins = 0
                    total_overtime_hours = 0.0
                    single_punch_dates, absent_dates, approved_leaves = [], [], []
                    
                    emp_perms = {row[0]: row[1] for row in get_employee_permissions(emp_id)}
                    wfh_records = get_wfh_hours(emp_id)
                    wfh_total_hours = sum([float(record[1]) for record in wfh_records if record[0].startswith(year_month)])
                    
                    for _, row in daily_data.iterrows():
                        day_num, day_name = row.iloc[0], str(row.iloc[1]).strip()
                        if pd.isna(day_num) or day_name == 'Fri.': continue
                            
                        t_in_str, t_out_str = str(row.iloc[2]).strip(), str(row.iloc[3]).strip()
                        has_in = t_in_str != 'nan' and t_in_str != '--:--'
                        has_out = t_out_str != 'nan' and t_out_str != '--:--'
                        
                        try: formatted_date = f"{year_month}/{int(float(day_num)):02d}"
                        except: formatted_date = f"{year_month}/--"
                        
                        if (has_in and not has_out) or (not has_in and has_out):
                            single_punch_dates.append(formatted_date)
                        elif not has_in and not has_out:
                            if day_name != 'Thur.': 
                                if formatted_date in company_holidays: pass
                                elif formatted_date in emp_perms: approved_leaves.append(formatted_date)
                                else: absent_dates.append(formatted_date)
                        elif has_in and has_out:
                            try:
                                t_in_dt = datetime.strptime(t_in_str, time_in_fmt)
                                t_out_dt = datetime.strptime(t_out_str, time_in_fmt)
                                worked_mins = (t_out_dt - t_in_dt).total_seconds() / 60
                                
                                if worked_mins > 0:
                                    regular_hours += (worked_mins / 60)
                                    regular_days += 1
                                    
                                    late_arrival = (t_in_dt - official_in_dt).total_seconds() / 60
                                    daily_shortage = 0
                                    if late_arrival > GRACE_PERIOD_MINS:
                                        daily_shortage += late_arrival
                                        early_leave = (official_out_dt - t_out_dt).total_seconds() / 60
                                        if early_leave > 0: daily_shortage += early_leave
                                    elif late_arrival > 0:
                                        if worked_mins < required_mins:
                                            daily_shortage += (required_mins - worked_mins)
                                    else:
                                        early_leave = (official_out_dt - t_out_dt).total_seconds() / 60
                                        if early_leave > 0: daily_shortage += early_leave
                                        
                                    if daily_shortage > 0:
                                        total_shortage_mins += int(daily_shortage)
                                        
                                    overtime_mins = (t_out_dt - official_out_dt).total_seconds() / 60
                                    if overtime_mins > 0:
                                        total_overtime_hours += (overtime_mins / 60)
                            except: pass
                                
                    extracted_data.append({
                        'الكود': emp_id, 'الاسم': name, 'القسم': department,
                        'الحضور': regular_days, 'الساعات': round(regular_hours, 1),
                        'إضافي كلي (ساعات)': round(total_overtime_hours + wfh_total_hours, 1),
                        'عجز وتقصير (دقيقة)': total_shortage_mins,
                        'غياب صريح': len(absent_dates),
                        'بصمة ناقصة': len(single_punch_dates)
                    })
                    
    return pd.DataFrame(extracted_data)

# ==========================================
# 3. جميع الشاشات الفرعية 
# ==========================================
def open_analytics_dashboard():
    if current_df is None or current_df.empty:
        messagebox.showwarning("تنبيه", "يجب تحليل ملف البصمة أولاً.")
        return
        
    win = ctk.CTkToplevel(app)
    win.title(ar("Keyan-East | لوحة الإحصائيات"))
    win.geometry("850x550")
    win.grab_set()
    
    header = ctk.CTkFrame(win, fg_color="transparent")
    header.pack(fill="x", pady=20, padx=30)
    ctk.CTkLabel(header, text=ar("مؤشرات وإحصائيات الأداء"), font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold")).pack(side="right")
    
    top_control = ctk.CTkFrame(win, fg_color="transparent")
    top_control.pack(pady=10)
    
    emp_list = ["الشركة بالكامل"] + current_df['الاسم'].tolist()
    combo_target = ctk.CTkComboBox(top_control, values=[ar(e) for e in emp_list], font=ctk.CTkFont(size=14), width=300, justify="right")
    combo_target.set(ar("الشركة بالكامل"))
    combo_target.pack(side="right", padx=10)
    ctk.CTkLabel(top_control, text=ar("اختر التقرير:"), font=ctk.CTkFont(size=14, weight="bold")).pack(side="right")

    cards_frame = ctk.CTkFrame(win, fg_color="transparent")
    cards_frame.pack(fill="both", expand=True, padx=30, pady=20)
    
    def create_card(parent, title, row, col, text_color):
        card = ctk.CTkFrame(parent, corner_radius=15)
        card.grid(row=row, column=col, padx=15, pady=15, sticky="nsew")
        ctk.CTkLabel(card, text=ar(title), font=ctk.CTkFont(size=14, weight="bold"), text_color="gray").pack(pady=(20, 10))
        val_lbl = ctk.CTkLabel(card, text="0", font=ctk.CTkFont(size=32, weight="bold"), text_color=text_color)
        val_lbl.pack(pady=(0, 20))
        parent.grid_columnconfigure(col, weight=1)
        return val_lbl

    lbl_late = create_card(cards_frame, "دقائق العجز والتقصير", 0, 1, "#FF5630")
    lbl_absent = create_card(cards_frame, "أيام الغياب بدون إذن", 0, 0, "#FFAB00")
    lbl_overtime = create_card(cards_frame, "إجمالي الإضافي (ساعات)", 1, 1, "#36B37E")
    lbl_attend = create_card(cards_frame, "إجمالي أيام الحضور", 1, 0, "#0052CC")

    def refresh_stats(*args):
        selected = combo_target.get()
        target = "الشركة بالكامل" if selected == ar("الشركة بالكامل") else None
        if not target:
            for e in emp_list:
                if ar(e) == selected: target = e; break
                
        df_target = current_df if target == "الشركة بالكامل" else current_df[current_df['الاسم'] == target]
        
        lbl_late.configure(text=f"{df_target['عجز وتقصير (دقيقة)'].sum()} {ar('دقيقة')}")
        lbl_absent.configure(text=f"{df_target['غياب صريح'].sum()} {ar('يوم')}")
        lbl_overtime.configure(text=f"{round(df_target['إضافي كلي (ساعات)'].sum(), 1)} {ar('ساعة')}")
        lbl_attend.configure(text=f"{df_target['الحضور'].sum()} {ar('يوم')}")

    combo_target.configure(command=refresh_stats)
    refresh_stats()

def open_users_settings():
    win = ctk.CTkToplevel(app)
    win.title(ar("Keyan-East | إعدادات النظام"))
    win.geometry("500x550")
    win.grab_set()

    ctk.CTkLabel(win, text=ar("إدارة مستخدمي النظام"), font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold")).pack(pady=20)
    
    frame_pwd = ctk.CTkFrame(win, corner_radius=15)
    frame_pwd.pack(fill="x", padx=40, pady=10)
    ctk.CTkLabel(frame_pwd, text=ar(f"تغيير كلمة المرور لـ ({CURRENT_USER})"), font=ctk.CTkFont(weight="bold")).pack(pady=(15, 5))
    
    ent_new_pwd = ctk.CTkEntry(frame_pwd, width=200, justify="center", placeholder_text=ar("كلمة المرور الجديدة"))
    ent_new_pwd.pack(pady=10)
    
    def change_password():
        new_pw = ent_new_pwd.get().strip()
        if not new_pw: return
        conn = sqlite3.connect('hr_system.db')
        conn.execute("UPDATE Users SET password=? WHERE username=?", (new_pw, CURRENT_USER))
        conn.commit(); conn.close()
        messagebox.showinfo("نجاح", "تم تغيير كلمة المرور بنجاح!")
        ent_new_pwd.delete(0, 'end')

    ctk.CTkButton(frame_pwd, text=ar("تحديث كلمة المرور"), fg_color="#FFAB00", text_color="black", command=change_password).pack(pady=(5, 15))

    frame_add = ctk.CTkFrame(win, corner_radius=15)
    frame_add.pack(fill="x", padx=40, pady=20)
    ctk.CTkLabel(frame_add, text=ar("إضافة مستخدم جديد للبرنامج"), font=ctk.CTkFont(weight="bold")).pack(pady=(15, 5))
    
    ent_new_user = ctk.CTkEntry(frame_add, width=200, justify="center", placeholder_text=ar("اسم المستخدم الجديد"))
    ent_new_user.pack(pady=10)
    ent_new_user_pwd = ctk.CTkEntry(frame_add, width=200, justify="center", placeholder_text=ar("كلمة المرور"))
    ent_new_user_pwd.pack(pady=10)

    def add_user():
        u, p = ent_new_user.get().strip(), ent_new_user_pwd.get().strip()
        if not u or not p: return
        conn = sqlite3.connect('hr_system.db')
        try:
            conn.execute("INSERT INTO Users (username, password, role) VALUES (?, ?, ?)", (u, p, 'user'))
            conn.commit()
            messagebox.showinfo("نجاح", f"تم إضافة المستخدم '{u}' بنجاح!")
            ent_new_user.delete(0, 'end'); ent_new_user_pwd.delete(0, 'end')
        except sqlite3.IntegrityError:
            messagebox.showerror("خطأ", "اسم المستخدم موجود مسبقاً!")
        conn.close()

    ctk.CTkButton(frame_add, text=ar("إضافة المستخدم"), fg_color="#36B37E", command=add_user).pack(pady=(5, 15))

def open_wfh_dashboard():
    emps = get_all_employees()
    if not emps: 
        messagebox.showinfo("تنبيه", "برجاء تحليل ملف البصمة أولاً لتسجيل الموظفين.")
        return
    
    win = ctk.CTkToplevel(app)
    win.title(ar("Keyan-East | العمل الإضافي وعن بعد"))
    win.geometry("750x650")
    win.grab_set()

    ctk.CTkLabel(win, text=ar("تسجيل الساعات الإضافية والعمل من المنزل"), font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold")).pack(pady=20)
    
    top_control = ctk.CTkFrame(win, fg_color="transparent")
    top_control.pack(pady=5)
    combo_emps = ctk.CTkComboBox(top_control, values=[ar(f"{e[0]} - {e[1]}") for e in emps], width=300, justify="right")
    combo_emps.pack(side="right", padx=10)
    ctk.CTkLabel(top_control, text=ar("اختر الموظف:"), font=ctk.CTkFont(size=14, weight="bold")).pack(side="right")

    add_frame = ctk.CTkFrame(win, corner_radius=15)
    add_frame.pack(fill="x", padx=40, pady=20)
    
    inner_add = ctk.CTkFrame(add_frame, fg_color="transparent")
    inner_add.pack(pady=15)
    
    ent_date = ctk.CTkEntry(inner_add, width=150, justify="center", placeholder_text="2026/09/05")
    ent_date.grid(row=0, column=0, padx=10, pady=10)
    ctk.CTkLabel(inner_add, text=ar("التاريخ:")).grid(row=0, column=1, padx=10, sticky="e")
    
    ent_hours = ctk.CTkEntry(inner_add, width=150, justify="center", placeholder_text=ar("مثال: 2.5"))
    ent_hours.grid(row=1, column=0, padx=10, pady=10)
    ctk.CTkLabel(inner_add, text=ar("عدد الساعات:")).grid(row=1, column=1, padx=10, sticky="e")

    ent_task = ctk.CTkEntry(inner_add, width=300, justify="right", placeholder_text=ar("المهام المنجزة (دليل الاعتماد)"))
    ent_task.grid(row=2, column=0, columnspan=2, padx=10, pady=10)

    cols = ('التاريخ', 'الساعات', 'المهام المنجزة')
    tree_wfh = ttk.Treeview(win, columns=cols, show='headings', height=5)
    for c in cols: tree_wfh.heading(c, text=c)
    tree_wfh.column('التاريخ', anchor="center", width=100)
    tree_wfh.column('الساعات', anchor="center", width=80)
    tree_wfh.column('المهام المنجزة', anchor="right", width=300)
    tree_wfh.pack(fill="x", padx=40, pady=15)

    def refresh_wfh(*args):
        for row in tree_wfh.get_children(): tree_wfh.delete(row)
        if not combo_emps.get(): return
        selected_text = combo_emps.get()
        emp_id = None
        for e in emps:
            if ar(f"{e[0]} - {e[1]}") == selected_text: emp_id = e[0]; break
        if not emp_id: return
        
        for w in get_wfh_hours(emp_id):
            tree_wfh.insert("", "end", values=(w[0], w[1], w[2]))

    combo_emps.configure(command=refresh_wfh)

    def save_wfh():
        if not combo_emps.get() or not ent_date.get() or not ent_hours.get(): return
        selected_text = combo_emps.get()
        emp_id = None
        for e in emps:
            if ar(f"{e[0]} - {e[1]}") == selected_text: emp_id = e[0]; break
        
        date, hours, task = ent_date.get().strip(), ent_hours.get().strip(), ent_task.get().strip()
        try:
            float(hours)
            save_wfh_hours_to_db(emp_id, date, float(hours), task)
            ent_date.delete(0, 'end'); ent_hours.delete(0, 'end'); ent_task.delete(0, 'end')
            refresh_wfh()
            messagebox.showinfo("نجاح", "تم تسجيل الساعات واعتمادها بملف الموظف.")
        except ValueError:
            messagebox.showerror("خطأ", "يجب إدخال عدد الساعات كأرقام فقط!")
            
    ctk.CTkButton(add_frame, text=ar("تسجيل واعتماد الساعات"), font=ctk.CTkFont(weight="bold"), fg_color="#36B37E", command=save_wfh).pack(pady=15)

def open_holidays_dashboard():
    win = ctk.CTkToplevel(app)
    win.title(ar("Keyan-East | العطلات الرسمية"))
    win.geometry("600x550")
    win.grab_set()

    ctk.CTkLabel(win, text=ar("تقويم العطلات الرسمية للشركة"), font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold")).pack(pady=20)
    
    add_frame = ctk.CTkFrame(win, corner_radius=15)
    add_frame.pack(fill="x", padx=40, pady=10)
    
    inner_add = ctk.CTkFrame(add_frame, fg_color="transparent")
    inner_add.pack(pady=15)
    
    ent_date = ctk.CTkEntry(inner_add, width=150, justify="center", placeholder_text="2026/10/06")
    ent_date.grid(row=0, column=0, padx=10, pady=10)
    ctk.CTkLabel(inner_add, text=ar("تاريخ العطلة:")).grid(row=0, column=1, padx=10, sticky="e")
    
    ent_name = ctk.CTkEntry(inner_add, width=150, justify="right", placeholder_text=ar("مثال: إجازة 6 أكتوبر"))
    ent_name.grid(row=1, column=0, padx=10, pady=10)
    ctk.CTkLabel(inner_add, text=ar("اسم العطلة:")).grid(row=1, column=1, padx=10, sticky="e")

    cols = ('التاريخ', 'اسم العطلة')
    tree_holidays = ttk.Treeview(win, columns=cols, show='headings', height=6)
    for c in cols: tree_holidays.heading(c, text=c)
    tree_holidays.column('التاريخ', anchor="center")
    tree_holidays.column('اسم العطلة', anchor="center")
    tree_holidays.pack(fill="x", padx=40, pady=20)

    def refresh_holidays():
        for row in tree_holidays.get_children(): tree_holidays.delete(row)
        for d, n in get_all_holidays().items():
            tree_holidays.insert("", "end", values=(d, n))

    def save_holiday():
        d, n = ent_date.get().strip(), ent_name.get().strip()
        if not d or not n:
            messagebox.showwarning("تنبيه", "برجاء كتابة التاريخ واسم العطلة!")
            return
        save_holiday_to_db(d, n)
        messagebox.showinfo("نجاح", "تم تسجيل العطلة الرسمية بنجاح.")
        ent_date.delete(0, 'end'); ent_name.delete(0, 'end')
        refresh_holidays()

    ctk.CTkButton(inner_add, text=ar("تسجيل العطلة"), font=ctk.CTkFont(weight="bold"), fg_color="#6554C0", command=save_holiday).grid(row=2, column=0, columnspan=2, pady=15)
    refresh_holidays()

def open_employee_dashboard():
    emps = get_all_employees()
    if not emps:
        messagebox.showinfo("تنبيه", "برجاء تحليل ملف البصمة أولاً لتسجيل الموظفين.")
        return
    win = ctk.CTkToplevel(app)
    win.title(ar("Keyan-East | ملف الموظف"))
    win.geometry("750x700")
    win.grab_set() 

    ctk.CTkLabel(win, text=ar("إدارة الإجازات والرصيد السنوي"), font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold")).pack(pady=20)
    top_control = ctk.CTkFrame(win, fg_color="transparent")
    top_control.pack(pady=5)
    combo_emps = ctk.CTkComboBox(top_control, values=[ar(f"{e[0]} - {e[1]}") for e in emps], width=300, justify="right")
    combo_emps.pack(side="right", padx=10)
    ctk.CTkLabel(top_control, text=ar("اختر الموظف:"), font=ctk.CTkFont(size=14, weight="bold")).pack(side="right")

    balance_frame = ctk.CTkFrame(win, corner_radius=15)
    balance_frame.pack(fill="x", padx=40, pady=15)
    lbl_total = ctk.CTkLabel(balance_frame, text=ar("الرصيد: --"), font=ctk.CTkFont(size=16, weight="bold"))
    lbl_total.pack(side="right", expand=True, pady=15)
    lbl_consumed = ctk.CTkLabel(balance_frame, text=ar("المستهلك: --"), font=ctk.CTkFont(size=16, weight="bold"), text_color="#FF5630")
    lbl_consumed.pack(side="right", expand=True, pady=15)
    lbl_remain = ctk.CTkLabel(balance_frame, text=ar("المتبقي: --"), font=ctk.CTkFont(size=16, weight="bold"), text_color="#36B37E")
    lbl_remain.pack(side="right", expand=True, pady=15)

    add_frame = ctk.CTkFrame(win, corner_radius=15)
    add_frame.pack(fill="x", padx=40, pady=10)
    inner_add = ctk.CTkFrame(add_frame, fg_color="transparent")
    inner_add.pack(pady=15)
    ent_date = ctk.CTkEntry(inner_add, width=150, justify="center", placeholder_text="2026/09/05")
    ent_date.grid(row=0, column=0, padx=10, pady=10)
    ctk.CTkLabel(inner_add, text=ar("التاريخ:")).grid(row=0, column=1, padx=10, sticky="e")
    combo_type = ctk.CTkComboBox(inner_add, values=[ar("إجازة اعتيادية"), ar("إجازة عارضة"), ar("مرضي"), ar("مأمورية"), ar("إذن شخصي")], width=150, justify="right")
    combo_type.grid(row=1, column=0, padx=10, pady=10)
    ctk.CTkLabel(inner_add, text=ar("النوع:")).grid(row=1, column=1, padx=10, sticky="e")

    cols = ('التاريخ', 'النوع')
    tree_history = ttk.Treeview(win, columns=cols, show='headings', height=4)
    for c in cols: tree_history.heading(c, text=c)
    tree_history.column('التاريخ', anchor="center")
    tree_history.column('النوع', anchor="center")
    tree_history.pack(fill="x", padx=40, pady=15)

    def refresh_profile(*args):
        for row in tree_history.get_children(): tree_history.delete(row)
        if not combo_emps.get(): return
        selected_text = combo_emps.get()
        emp_id = None
        for e in emps:
            if ar(f"{e[0]} - {e[1]}") == selected_text: emp_id = e[0]; break
        if not emp_id: return
            
        history = get_employee_permissions(emp_id)
        consumed_leaves = sum(1 for h in history if h[1] in ["إجازة اعتيادية", "إجازة عارضة"])
        for h in history: tree_history.insert("", "end", values=(h[0], h[1]))
        emp_data = next((e for e in emps if e[0] == emp_id), None)
        if emp_data:
            lbl_total.configure(text=ar(f"الرصيد: {emp_data[2]}"))
            lbl_consumed.configure(text=ar(f"المستهلك: {consumed_leaves}"))
            remain = emp_data[2] - consumed_leaves
            lbl_remain.configure(text=ar(f"المتبقي: {remain}"), text_color="#FF5630" if remain < 0 else "#36B37E")

    combo_emps.configure(command=refresh_profile)

    def save_leave():
        if not combo_emps.get() or not ent_date.get().strip(): return
        selected_text = combo_emps.get()
        emp_id = None
        for e in emps:
            if ar(f"{e[0]} - {e[1]}") == selected_text: emp_id = e[0]; break
            
        date = ent_date.get().strip()
        l_type = "إجازة اعتيادية"
        types = ["إجازة اعتيادية", "إجازة عارضة", "مرضي", "مأمورية", "إذن شخصي"]
        for t in types:
            if ar(t) == combo_type.get(): l_type = t; break
            
        if l_type in ["إجازة اعتيادية", "إجازة عارضة"]:
            current_remain = int(lbl_remain.cget("text").split(":")[1].strip())
            if current_remain <= 0:
                if not messagebox.askyesno("تحذير", "الرصيد غير كافٍ! هل تسجلها إجازة بدون أجر؟"): return
                l_type = "إجازة بدون أجر"
        save_permission_to_db(emp_id, date, l_type)
        ent_date.delete(0, 'end'); refresh_profile()
        
    ctk.CTkButton(inner_add, text=ar("تسجيل الإجازة"), font=ctk.CTkFont(weight="bold"), fg_color="#36B37E", command=save_leave).grid(row=2, column=0, columnspan=2, pady=10)

# ==========================================
# 4. التأسيس العام (App & Login)
# ==========================================
app = ctk.CTk()
app.title("Keyan-East | HR Management System")
app.geometry("1400x780")
app.withdraw()

login_win = ctk.CTkToplevel(app)
login_win.title(ar("تسجيل الدخول - Keyan-East"))
login_win.geometry("400x500")
login_win.protocol("WM_DELETE_WINDOW", app.destroy)

if os.path.exists(LOGO_FILE):
    try:
        login_img = ctk.CTkImage(light_image=Image.open(LOGO_FILE), size=(150, 75))
        ctk.CTkLabel(login_win, image=login_img, text="").pack(pady=(40, 20))
    except: pass

ctk.CTkLabel(login_win, text=ar("تسجيل الدخول للنظام"), font=ctk.CTkFont(size=20, weight="bold")).pack(pady=10)

ent_user = ctk.CTkEntry(login_win, width=250, justify="center", placeholder_text=ar("اسم المستخدم (admin)"))
ent_user.pack(pady=15)
ent_pass = ctk.CTkEntry(login_win, width=250, justify="center", placeholder_text=ar("كلمة المرور (admin123)"), show="*")
ent_pass.pack(pady=15)

def check_login():
    global CURRENT_USER
    u, p = ent_user.get(), ent_pass.get()
    conn = sqlite3.connect('hr_system.db')
    c = conn.cursor()
    c.execute("SELECT * FROM Users WHERE username=? AND password=?", (u, p))
    user_data = c.fetchone()
    conn.close()
    
    if user_data:
        CURRENT_USER = user_data[0]
        login_win.destroy()
        app.deiconify()
    else:
        messagebox.showerror("خطأ", "اسم المستخدم أو كلمة المرور غير صحيحة!")

ctk.CTkButton(login_win, text=ar("دخول"), font=ctk.CTkFont(weight="bold"), width=250, command=check_login).pack(pady=20)

# ==========================================
# 5. الواجهة الرئيسية
# ==========================================
style = ttk.Style()
style.theme_use("clam")
style.configure("Treeview.Heading", font=('Segoe UI', 11, 'bold'), background="#EAECEE", foreground="#172B4D", borderwidth=0)
style.configure("Treeview", font=('Segoe UI', 10), rowheight=40, borderwidth=0, background="#FFFFFF")
style.map('Treeview', background=[('selected', '#DEEBFF')], foreground=[('selected', '#172B4D')])

def backup_database():
    dest = filedialog.asksaveasfilename(defaultextension=".db", initialfile=f"Keyan_Backup_{datetime.now().strftime('%Y%m%d')}.db", filetypes=[("Database files", "*.db")])
    if dest:
        try:
            shutil.copy2('hr_system.db', dest)
            messagebox.showinfo("نجاح", "تم حفظ النسخة الاحتياطية بنجاح!")
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل النسخ الاحتياطي:\n{e}")

def update_status(msg):
    lbl_status.configure(text=ar(msg))
    app.update()

def select_file():
    file_path = filedialog.askopenfilename(title="اختر ملف الحضور", filetypes=[("Excel files", "*.xls *.xlsx")])
    if file_path:
        lbl_file_path.configure(text=os.path.basename(file_path))
        app.file_path = file_path
        btn_process.configure(state="normal")

def process_data():
    global current_df
    if not hasattr(app, 'file_path'): return
    
    btn_process.configure(state="disabled")
    update_status("جاري قراءة البصمات ومعالجة البيانات...")
    
    try:
        current_df = calculate_detailed_attendance(app.file_path)
        if current_df is None:
            update_status("فشل التحليل بسبب خطأ في الملف.")
            btn_process.configure(state="normal")
            return
            
        for row in tree.get_children(): tree.delete(row)
        if not current_df.empty:
            current_df['الكود_رقم'] = pd.to_numeric(current_df['الكود'], errors='coerce')
            current_df = current_df.sort_values('الكود_رقم').drop('الكود_رقم', axis=1)
            for i, row in enumerate(current_df.iterrows()):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree.insert("", "end", values=list(row[1])[::-1], tags=(tag,))
            update_status("تم الانتهاء من التحليل بنجاح!")
        else:
            update_status("لم يتم العثور على بيانات صالحة في الملف.")
    except Exception as e:
        error_details = traceback.format_exc()
        print(error_details)
        messagebox.showerror("خطأ غير متوقع", f"حدث خطأ أثناء التحليل:\n{str(e)}")
        update_status("توقف التحليل بسبب خطأ.")
        
    btn_process.configure(state="normal")

header_frame = ctk.CTkFrame(app, fg_color="transparent")
header_frame.pack(fill="x", pady=25, padx=40)
if os.path.exists(LOGO_FILE):
    try:
        logo_img = ctk.CTkImage(light_image=Image.open(LOGO_FILE), size=(120, 60))
        ctk.CTkLabel(header_frame, image=logo_img, text="").pack(side="left")
    except: pass
ctk.CTkLabel(header_frame, text=ar("نظام Keyan-East للحضور والانصراف"), font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"), text_color="#172B4D").pack(side="right")

action_frame = ctk.CTkFrame(app, corner_radius=15, fg_color="#FFFFFF")
action_frame.pack(fill="x", padx=40, pady=10)

btn_select = ctk.CTkButton(action_frame, text=ar("رفع ملف البصمة"), font=ctk.CTkFont(weight="bold"), command=select_file, width=120)
btn_select.pack(side="right", padx=10, pady=15)

lbl_file_path = ctk.CTkLabel(action_frame, text=ar("لم يتم اختيار ملف"), font=ctk.CTkFont(size=12), text_color="gray")
lbl_file_path.pack(side="right", padx=10)

btn_process = ctk.CTkButton(action_frame, text=ar("بدء التحليل"), font=ctk.CTkFont(weight="bold"), fg_color="#36B37E", hover_color="#2D9A6B", command=process_data, state="disabled", width=100)
btn_process.pack(side="right", padx=10, pady=15)

# الأزرار المفصولة
ctk.CTkButton(action_frame, text=ar("إعدادات النظام"), font=ctk.CTkFont(weight="bold"), fg_color="#172B4D", hover_color="#091E42", command=open_users_settings, width=100).pack(side="left", padx=5, pady=15)
ctk.CTkButton(action_frame, text=ar("نسخ احتياطي"), font=ctk.CTkFont(weight="bold"), fg_color="#00875A", hover_color="#006644", command=backup_database, width=100).pack(side="left", padx=5, pady=15)

ctk.CTkButton(action_frame, text=ar("الإحصائيات"), font=ctk.CTkFont(weight="bold"), fg_color="#6554C0", hover_color="#5243AA", command=open_analytics_dashboard, width=100).pack(side="left", padx=5, pady=15)
ctk.CTkButton(action_frame, text=ar("أوفر تايم / WFH"), font=ctk.CTkFont(weight="bold"), fg_color="#0052CC", hover_color="#0043A6", command=open_wfh_dashboard, width=110).pack(side="left", padx=5, pady=15)
ctk.CTkButton(action_frame, text=ar("العطلات"), font=ctk.CTkFont(weight="bold"), fg_color="#FF5630", hover_color="#DE350B", command=open_holidays_dashboard, width=80).pack(side="left", padx=5, pady=15)
ctk.CTkButton(action_frame, text=ar("الموظفين"), font=ctk.CTkFont(weight="bold"), fg_color="#FFAB00", hover_color="#E59900", command=open_employee_dashboard, width=80).pack(side="left", padx=5, pady=15)

table_frame = ctk.CTkFrame(app, corner_radius=15, fg_color="#FFFFFF")
table_frame.pack(fill="both", expand=True, padx=40, pady=15)

raw_columns = ('الكود', 'الاسم', 'القسم', 'الحضور', 'الساعات', 'إضافي كلي (ساعات)', 'عجز وتقصير (دقيقة)', 'غياب صريح', 'بصمة ناقصة')
columns = raw_columns[::-1]

tree = ttk.Treeview(table_frame, columns=columns, show='headings')
tree.tag_configure('oddrow', background="#FFFFFF")
tree.tag_configure('evenrow', background="#F8F9FA")
scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
tree.configure(yscroll=scrollbar.set)
scrollbar.pack(side="right", fill="y", pady=10)
tree.pack(side="left", fill="both", expand=True, padx=10, pady=10)

for col in columns:
    tree.heading(col, text=col)
    width = 160 if col == 'الاسم' else (120 if col == 'القسم' else 95)
    tree.column(col, anchor="center", width=width)

lbl_status = ctk.CTkLabel(app, text=ar("مستعد للعمل..."), font=ctk.CTkFont(size=14, weight="bold"), text_color="gray", anchor="w")
lbl_status.pack(fill="x", side="bottom", padx=40, pady=10)

app.mainloop()