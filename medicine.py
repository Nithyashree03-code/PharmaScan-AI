"""
PharmaScan AI — Vision-Based Fake Medicine Detection
ULTIMATE HACKATHON EDITION v2.0

FEATURES:
  ✅ Animated login page with role selector
  ✅ Auto email alert on fake detection (no manual button)
  ✅ Vision Scanner: OCR, spelling, expiry, risk card, PDF
  ✅ Live Camera: full persistent report (no disappearing)
  ✅ Map: stable scroll (returned_objects=[])
  ✅ Drug Interaction Checker (NIH API)
  ✅ Dashboard with charts and CSV export
  ✅ Nationwide Fake Heatmap + Pharmacy Finder
  ✅ Medicine Comparison with radar chart
  ✅ Safety Certificate: downloadable HTML authenticity badge
  ✅ Hotspot Predictor: AI predicts fake medicine risk zones
  ✅ Scan History Gallery with statistics
  ✅ Scan streak tracker in sidebar
"""

# ─────────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────────
import streamlit as st
import pytesseract
import cv2
import numpy as np
from PIL import Image
import re, json, sqlite3, smtplib, ssl, io, hashlib, time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import folium
from streamlit_folium import st_folium

try:
    import easyocr
    EASYOCR_OK = True
except Exception:
    EASYOCR_OK = False

BARCODE_OK = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                     Spacer, Table, TableStyle)
    from reportlab.lib.units import inch
    PDF_OK = True
except Exception:
    PDF_OK = False

# ─────────────────────────────────────────────────────────────────
# ★★★  EDIT THESE THREE LINES ONLY  ★★★
# ─────────────────────────────────────────────────────────────────
GEMINI_API_KEY   = ""  # Gemini removed

SENDER_EMAIL     = "pharmascanai26@gmail.com"
# ↑ Create a dedicated Gmail account for PharmaScan to send alerts FROM
# ↑ Change this to that Gmail address

SENDER_APP_PASS  = "qmavgvamacgkbjyt"
# ↑ Gmail → Security → 2-Step Verification ON → App Passwords → generate
# ↑ Paste the 16-character app password here

# ─────────────────────────────────────────────────────────────────
DB_PATH      = "pharmascan.db"
ACCOUNTS_DIR = "pharmascan_accounts"  # folder where account records are saved
DATA_DIR     = "pharmascan_data"      # folder for all CSV login/user data
import os
if os.name == "nt":  # Windows only
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

import os as _os
_os.makedirs(ACCOUNTS_DIR, exist_ok=True)
_os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────
# CSV PATHS  (all login & user data stored as readable CSV files)
# ─────────────────────────────────────────────────────────────────
CSV_USERS    = _os.path.join(DATA_DIR, "users.csv")
CSV_SCANS    = _os.path.join(DATA_DIR, "scans.csv")
CSV_LOGINS   = _os.path.join(DATA_DIR, "login_activity.csv")

# ── CSV column headers ────────────────────────────────────────────
_CSV_USERS_COLS  = ["username","email","password_hash","created_at","role",
                    "id_type","id_number","id_filename","id_verified"]
_CSV_SCANS_COLS  = ["id","username","medicine","authentic","score",
                    "expiry_status","ocr","sharp","colour","edge",
                    "city","lat","lon","spell_errors","scan_date"]
_CSV_LOGINS_COLS = ["timestamp","username","email","role","event"]

def _ensure_csv(path, cols):
    """Create CSV file with headers if it doesn't exist."""
    if not _os.path.exists(path):
        pd.DataFrame(columns=cols).to_csv(path, index=False)

def _csv_sync_from_db():
    """Export all SQLite tables to CSV (called after every write)."""
    try:
        c = sqlite3.connect(DB_PATH)
        # Users
        df_u = pd.read_sql("SELECT * FROM users", c)
        df_u.to_csv(CSV_USERS, index=False)
        # Scans
        df_s = pd.read_sql("SELECT * FROM scans ORDER BY id DESC", c)
        df_s.to_csv(CSV_SCANS, index=False)
        c.close()
    except Exception:
        pass

def _csv_append_login(username, email, role, event):
    """Append a login/logout/register event row to login_activity.csv."""
    try:
        _ensure_csv(CSV_LOGINS, _CSV_LOGINS_COLS)
        row = pd.DataFrame([{
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username":  username,
            "email":     email or "",
            "role":      role or "",
            "event":     event,
        }])
        row.to_csv(CSV_LOGINS, mode="a", header=False, index=False)
    except Exception:
        pass


def _save_account_file(username, email, role, created_at,
                       id_type="", id_number="", id_filename="",
                       event="REGISTERED"):
    """Write/update a plain-text account record in pharmascan_accounts/."""
    try:
        _os.makedirs(ACCOUNTS_DIR, exist_ok=True)
        filepath = _os.path.join(ACCOUNTS_DIR, f"{username}.txt")
        now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        role_lbl = "Expert / Pharmacist" if role == "expert" else "Patient / User"

        header = (
            "=" * 56 + "\n"
            "  PharmaScan AI - Account Record\n"
            "=" * 56 + "\n"
            f"  Username    : {username}\n"
            f"  Email       : {email}\n"
            f"  Role        : {role_lbl}\n"
            f"  Created At  : {created_at}\n"
        )
        if id_type or id_number:
            id_clean = id_type.split(" ", 1)[-1] if id_type else "N/A"
            header += (
                f"  ID Type     : {id_clean}\n"
                f"  License No. : {id_number or 'N/A'}\n"
                f"  ID Document : {id_filename or 'N/A'}\n"
            )
        header += "=" * 56 + "\n\n"
        header += "  ACTIVITY LOG\n"
        header += "  " + "-" * 52 + "\n"

        # Read existing log lines if file already exists
        log_lines = []
        if _os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as fh:
                raw = fh.read()
            if "ACTIVITY LOG" in raw:
                for line in raw.split("ACTIVITY LOG", 1)[1].split("\n"):
                    s = line.strip()
                    if s.startswith("["):
                        log_lines.append("  " + s)

        log_lines.append(f"  [{now_str}]  {event}")
        body = "\n".join(log_lines) + "\n"
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(header + body + "\n")
    except Exception:
        pass


def _delete_account_file(username):
    """Mark account file as deleted and rename it."""
    try:
        filepath = _os.path.join(ACCOUNTS_DIR, f"{username}.txt")
        if _os.path.exists(filepath):
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(filepath, "a", encoding="utf-8") as fh:
                fh.write(
                    f"  [{now_str}]  DELETED - account and all data permanently removed\n"
                )
            deleted_path = _os.path.join(ACCOUNTS_DIR, f"{username}_DELETED.txt")
            _os.rename(filepath, deleted_path)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────
# SUPERADMIN — hardcoded, bypass all DB checks
# ─────────────────────────────────────────────────────────────────
ADMIN_USERNAME = "pharmascanai26@gmail.com"
ADMIN_PASSWORD_HASH = hashlib.sha256("scan@26".encode()).hexdigest()
ADMIN_EMAIL    = "pharmascanai26@gmail.com"

def is_admin_login(username, password):
    """Check if credentials match the superadmin account."""
    return (username.strip().lower() == ADMIN_USERNAME.lower() and
            hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH)

# Demo login credentials (username → sha256 of password)
DEMO_USERS = {
    "doctor":     hashlib.sha256("medicine2024".encode()).hexdigest(),
    "pharmacist": hashlib.sha256("pharmacy2024".encode()).hexdigest(),
}

# Roles for demo accounts
DEMO_ROLES = {
    "doctor":     "expert",
    "pharmacist": "expert",
}
# Expert role keywords — if username contains these, treat as expert
EXPERT_KEYWORDS = ["doctor", "dr_", "pharmacist", "pharm", "expert",
                   "medic", "clinical", "specialist", "admin"]

# ─────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PharmaScan AI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ─────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────
DEFAULTS = {
    "logged_in":        False,
    "user_role":        "",   # "user", "expert", or "admin"
    "username":         "",
    "user_email":       "",   # login Gmail → used as alert receiver
    "dark_mode":        True,
    "chat_messages":    [],
    "scan_result":      None,
    "current_medicine": None,
    "ocr_text":         "",
    "alert_sent":       False,
    "login_error":      "",
    "reg_error":        "",
    "reg_ok":           False,
    "alert_err":        "",
    "cam_result":       None,
    "cam_bytes":        None,
    "cam_arr":          None,
    "pharmacy_map":     None,
    "pharmacy_count":   0,
    "hotspot_prediction": None,
    "upload_img_arr":    None,
    "confirm_delete":    False,
    "otp_code":          "",
    "otp_email":         "",
    "otp_verified":      False,
    "otp_sent":          False,
    "otp_pending_user":  "",
    "otp_pending_pass":  "",
}
# ─────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────
DEFAULTS = {
    "logged_in":        False,
    "user_role":        "",   # "user", "expert", or "admin"
    "username":         "",
    "user_email":       "",   # login Gmail → used as alert receiver
    "dark_mode":        True,
    "chat_messages":    [],
    "scan_result":      None,
    "current_medicine": None,
    "ocr_text":         "",
    "alert_sent":       False,
    "login_error":      "",
    "reg_error":        "",
    "reg_ok":           False,
    "alert_err":        "",
    "cam_result":       None,
    "cam_bytes":        None,
    "cam_arr":          None,
    "pharmacy_map":     None,
    "pharmacy_count":   0,
    "hotspot_prediction": None,
    "upload_img_arr":    None,
    "confirm_delete":    False,
    "otp_code":          "",
    "otp_email":         "",
    "otp_verified":      False,
    "otp_sent":          False,
    "otp_pending_user":  "",
    "otp_pending_pass":  "",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─────────────────────────────────────────────────────────────────
# PERSISTENT LOGIN — survives page refresh using a session file
# ─────────────────────────────────────────────────────────────────
SESSION_FILE = _os.path.join(DATA_DIR, "active_session.json")

def _save_session(username, role, email):
    """Save login info to disk so refresh restores the session."""
    try:
        with open(SESSION_FILE, "w") as f:
            json.dump({
                "username": username,
                "user_role": role,
                "user_email": email,
                "dark_mode": st.session_state.get("dark_mode", True),
            }, f)
    except Exception:
        pass

def _clear_session():
    """Delete the saved session file on logout."""
    try:
        if _os.path.exists(SESSION_FILE):
            _os.remove(SESSION_FILE)
    except Exception:
        pass

def _restore_session():
    """On app start, restore login from disk if file exists."""
    try:
        if _os.path.exists(SESSION_FILE) and not st.session_state.logged_in:
            with open(SESSION_FILE, "r") as f:
                data = json.load(f)
            uname = data.get("username", "")
            role  = data.get("user_role", "")
            email = data.get("user_email", "")
            # Verify user still exists in DB (not deleted)
            if uname:
                conn = sqlite3.connect(DB_PATH)
                row  = conn.execute(
                    "SELECT username FROM users WHERE username=?", (uname,)
                ).fetchone()
                conn.close()
                # Allow admin restore too
                is_admin = (uname.strip().lower() == ADMIN_USERNAME.lower())
                if row or is_admin:
                    st.session_state.logged_in  = True
                    st.session_state.username   = uname
                    st.session_state.user_role  = role
                    st.session_state.user_email = email
                    st.session_state.dark_mode  = data.get("dark_mode", True)
                else:
                    _clear_session()
    except Exception:
        pass

# Restore session on every page load
_restore_session()


# ─────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────
def init_db():
    c = sqlite3.connect(DB_PATH)

    # Create tables (safe for first run)
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE, email TEXT,
        password_hash TEXT, created_at TEXT,
        role TEXT DEFAULT 'user',
        id_type TEXT DEFAULT '',
        id_number TEXT DEFAULT '',
        id_filename TEXT DEFAULT '',
        id_verified INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS qa_questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, email TEXT,
        question TEXT, medicine TEXT,
        category TEXT, status TEXT DEFAULT 'open',
        asked_at TEXT, upvotes INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS qa_answers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER, expert_username TEXT,
        expert_role TEXT, answer TEXT,
        answered_at TEXT, helpful_votes INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS scans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, medicine TEXT, authentic INTEGER,
        score REAL, expiry_status TEXT, ocr TEXT,
        sharp REAL, colour REAL, edge REAL,
        city TEXT, lat REAL, lon REAL,
        spell_errors TEXT, scan_date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS chats(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, medicine TEXT,
        question TEXT, answer TEXT, dt TEXT)""")

    # Migration: add any columns missing from older DB files
    REQUIRED_COLUMNS = {
        "scans": [
            ("username", "TEXT"), ("medicine", "TEXT"),
            ("authentic", "INTEGER"), ("score", "REAL"),
            ("expiry_status", "TEXT"), ("ocr", "TEXT"),
            ("sharp", "REAL"), ("colour", "REAL"), ("edge", "REAL"),
            ("city", "TEXT"), ("lat", "REAL"), ("lon", "REAL"),
            ("spell_errors", "TEXT"), ("scan_date", "TEXT"),
        ],
        "users": [
            ("username", "TEXT"), ("email", "TEXT"),
            ("password_hash", "TEXT"), ("created_at", "TEXT"),
            ("role", "TEXT"),
            ("id_type", "TEXT"), ("id_number", "TEXT"),
            ("id_filename", "TEXT"), ("id_verified", "INTEGER"),
        ],
        "chats": [
            ("username", "TEXT"), ("medicine", "TEXT"),
            ("question", "TEXT"), ("answer", "TEXT"), ("dt", "TEXT"),
        ],
    }
    for table, cols in REQUIRED_COLUMNS.items():
        existing = {row[1] for row in
                    c.execute(f"PRAGMA table_info({table})").fetchall()}
        for col_name, col_def in cols:
            if col_name not in existing:
                c.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")

    c.commit(); c.close()

def db_register(username, email, password, role="user",
                id_type="", id_number="", id_filename=""):
    try:
        c  = sqlite3.connect(DB_PATH)
        ph = hashlib.sha256(password.encode()).hexdigest()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute(
            "INSERT INTO users(username,email,password_hash,created_at,role,"
            "id_type,id_number,id_filename,id_verified) VALUES(?,?,?,?,?,?,?,?,?)",
            (username, email, ph, created_at, role,
             id_type, id_number, id_filename, 1 if id_type else 0))
        c.commit(); c.close()
        # Save account record to file
        _save_account_file(username, email, role, created_at,
                           id_type, id_number, id_filename,
                           event="REGISTERED")
        # Sync to CSV data files
        _csv_sync_from_db()
        _csv_append_login(username, email, role, "REGISTERED")
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Username already taken. Choose another."
    except Exception as e:
        return False, str(e)

def db_login(username, password):
    # ── Superadmin check (hardcoded, highest priority) ─────────────
    if is_admin_login(username, password):
        _csv_append_login(ADMIN_USERNAME, ADMIN_EMAIL, "admin", "ADMIN_LOGIN")
        return True, ADMIN_USERNAME, ADMIN_EMAIL, "admin"

    ph  = hashlib.sha256(password.encode()).hexdigest()
    c   = sqlite3.connect(DB_PATH)
    row = c.execute(
        "SELECT username,email,role,created_at,id_type,id_number,id_filename FROM users WHERE username=? AND password_hash=?",
        (username, ph)).fetchone()
    c.close()
    if row:
        uname, uemail, urole, created_at, id_t, id_n, id_f = row
        urole = urole or "user"
        # Log login event to account file and CSV
        _save_account_file(uname, uemail or "", urole,
                           created_at or "", id_t or "", id_n or "", id_f or "",
                           event="LOGIN")
        _csv_append_login(uname, uemail or "", urole, "LOGIN")
        return True, uname, uemail, urole
    # Fallback to demo users (no file logging for demo)
    if username in DEMO_USERS and DEMO_USERS[username] == ph:
        role = DEMO_ROLES.get(username, "user")
        return True, username, f"{username}@pharmascan.demo", role
    return False, None, None, None

def db_save_scan(uname, med, ok, score, exp, ocr,
                 sh, co, ed, city, lat, lon, sp):
    c = sqlite3.connect(DB_PATH)
    c.execute("""INSERT INTO scans(username,medicine,authentic,score,expiry_status,
        ocr,sharp,colour,edge,city,lat,lon,spell_errors,scan_date)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (uname, med, int(ok), score, exp, ocr[:500],
         sh, co, ed, city, lat, lon, sp,
         datetime.now().strftime("%Y-%m-%d %H:%M")))
    c.commit(); c.close()
    _csv_sync_from_db()  # keep CSV in sync after every scan

def db_get_scans(uname=None):
    c = sqlite3.connect(DB_PATH)
    try:
        if uname:
            df = pd.read_sql(
                "SELECT * FROM scans WHERE username=? ORDER BY id DESC LIMIT 200",
                c, params=(uname,))
        else:
            df = pd.read_sql("SELECT * FROM scans ORDER BY id DESC LIMIT 200", c)
    except Exception:
        df = pd.DataFrame()
    c.close(); return df

def db_save_chat(uname, med, q, a):
    c = sqlite3.connect(DB_PATH)
    c.execute("INSERT INTO chats(username,medicine,question,answer,dt) VALUES(?,?,?,?,?)",
              (uname, med, q, a, datetime.now().strftime("%Y-%m-%d %H:%M")))
    c.commit(); c.close()

init_db()

# ─────────────────────────────────────────────────────────────────
# MEDICINE DATABASE
# ─────────────────────────────────────────────────────────────────
MEDS = {
    "paracetamol":    {"use":"Fever and mild-to-moderate pain relief","dosage":"500–1000 mg every 4–6 hrs (max 4000 mg/day)","se":"Nausea, allergic reactions, liver damage if overdose","warn":"Do NOT exceed 4000 mg/day. Avoid alcohol.","cat":"Analgesic / Antipyretic","inter":["Warfarin","Alcohol","Isoniazid"],"colour":"White","shape":"Round or oval tablet","genuine":"Clear embossing, uniform white, no smell"},
    "ibuprofen":      {"use":"Pain, fever, inflammation, menstrual cramps","dosage":"200–400 mg every 4–6 hrs (max 1200 mg/day OTC)","se":"Stomach upset, nausea, dizziness, GI bleeding","warn":"Avoid with ulcers, kidney disease, heart conditions","cat":"NSAID","inter":["Aspirin","Blood thinners","ACE inhibitors"],"colour":"Brown / Orange coated","shape":"Round coated tablet","genuine":"Smooth film coat, consistent colour"},
    "amoxicillin":    {"use":"Bacterial infections — ear, throat, lung, UTI","dosage":"250–500 mg every 8 hrs","se":"Diarrhea, rash, nausea, allergic reaction","warn":"Do NOT use if allergic to penicillin. Complete the full course.","cat":"Antibiotic (Penicillin)","inter":["Methotrexate","Warfarin","Oral contraceptives"],"colour":"Pink / Red capsule","shape":"Capsule","genuine":"Printed capsule code, two-tone pink"},
    "mefenamic acid": {"use":"Pain relief and menstrual cramps","dosage":"500 mg then 250 mg every 6 hrs","se":"Stomach pain, nausea, dizziness, diarrhea","warn":"Avoid with ulcers. Max 7 days.","cat":"NSAID","inter":["Warfarin","Lithium","Methotrexate"],"colour":"Yellow capsule","shape":"Capsule","genuine":"Consistent yellow, clear brand imprint"},
    "cetirizine":     {"use":"Allergies, hay fever, hives, itching","dosage":"10 mg once daily","se":"Drowsiness, dry mouth, headache","warn":"May cause drowsiness. Avoid alcohol and driving.","cat":"Antihistamine","inter":["Alcohol","CNS depressants","Theophylline"],"colour":"White / Off-white","shape":"Round or oblong tablet","genuine":"Smooth, clear score line"},
    "metformin":      {"use":"Type 2 diabetes management","dosage":"500 mg twice daily (up to 2000 mg/day)","se":"Nausea, diarrhea, stomach upset, lactic acidosis (rare)","warn":"Do NOT use if kidneys impaired. Take with meals.","cat":"Antidiabetic (Biguanide)","inter":["Alcohol","Contrast dyes","Cimetidine"],"colour":"White tablet","shape":"Round or oval","genuine":"Debossed strength, film coated"},
    "aspirin":        {"use":"Pain, fever, inflammation, blood clot prevention","dosage":"325–650 mg every 4–6 hrs; 75–100 mg daily for cardiac","se":"GI upset, bleeding, Reye syndrome in children","warn":"Do NOT give to children under 16.","cat":"NSAID / Antiplatelet","inter":["Warfarin","Ibuprofen","SSRIs","Alcohol"],"colour":"White tablet","shape":"Round tablet","genuine":"Mild vinegar smell, clear score line"},
    "omeprazole":     {"use":"Acid reflux, GERD, stomach ulcers, H. pylori","dosage":"20–40 mg once daily before meals","se":"Headache, nausea, diarrhea, low magnesium (long-term)","warn":"Long-term use reduces bone density and B12.","cat":"Proton Pump Inhibitor","inter":["Clopidogrel","Methotrexate","Warfarin"],"colour":"Pink / Purple capsule","shape":"Capsule","genuine":"Enteric-coated pellets inside, branded print"},
}

SPELL_MAP = {
    "paracetamool":"paracetamol","ibuprofren":"ibuprofen","ibupropen":"ibuprofen",
    "amoxicilin":"amoxicillin","amoxicilim":"amoxicillin","cetrizine":"cetirizine",
    "omeprazol":"omeprazole","asprin":"aspirin","metformim":"metformin",
    "expirey":"expiry","manufacter":"manufacture","tablit":"tablet",
    "capsuel":"capsule","medicne":"medicine","dosege":"dosage",
    "warining":"warning","pharmcy":"pharmacy",
}

# ─────────────────────────────────────────────────────────────────
# IMAGE PROCESSING
# ─────────────────────────────────────────────────────────────────
def preprocess(img):
    g  = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    d  = cv2.fastNlMeansDenoising(g, h=10)
    t  = cv2.adaptiveThreshold(d, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 11, 2)
    k  = np.ones((1,1), np.uint8)
    return cv2.erode(cv2.dilate(t, k), k)

def run_ocr(img, langs=None):
    proc = preprocess(img)
    t1   = pytesseract.image_to_string(proc, config="--psm 6")
    t2   = ""
    if EASYOCR_OK:
        try:
            r  = easyocr.Reader(langs or ["en"], verbose=False)
            t2 = " ".join([x[1] for x in r.readtext(img)])
        except Exception:
            pass
    return (t1 + " " + t2).strip()

def vision_analyze(img):
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    lap  = cv2.Laplacian(gray, cv2.CV_64F).var()
    sh_p = min(lap/500*100, 100)
    sh_s = min(lap/500*35, 35)
    hsv  = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    sat  = np.mean(hsv[:,:,1])
    co_p = min(sat/128*100, 100)
    co_s = min(sat/128*35, 35)
    ed   = cv2.Canny(gray, 50, 150)
    dns  = np.sum(ed>0)/ed.size
    ed_p = min(dns*2000, 100)
    ed_s = min(dns*700, 30)
    total = max(48.0, min(sh_s+co_s+ed_s, 97.0))
    checks = []
    if   lap < 80:   checks.append(("🔴","Blurry image — label may be reprinted","bad"))
    elif lap < 200:  checks.append(("🟡","Moderate sharpness — borderline quality","warn"))
    else:            checks.append(("🟢","High sharpness — consistent with genuine","ok"))
    if   sat < 25:   checks.append(("🔴","Very faded colours — possible counterfeit","bad"))
    elif sat < 60:   checks.append(("🟡","Slightly dull colours — borderline","warn"))
    else:            checks.append(("🟢","Normal colour richness — looks genuine","ok"))
    if   dns < 0.015: checks.append(("🔴","Low print detail — below genuine standard","bad"))
    elif dns < 0.04:  checks.append(("🟡","Medium print detail — borderline","warn"))
    else:             checks.append(("🟢","Good print density — consistent with genuine","ok"))
    return total, checks, sh_p, co_p, ed_p



def scan_barcode(img):
    """Barcode scanning feature removed."""
    return [], None


def fda_verify_barcode(code):
    try:
        r = requests.get(
            f"https://api.fda.gov/drug/ndc.json?search=package_ndc:{code}&limit=1",
            timeout=5)
        if r.status_code == 200:
            res = r.json().get("results",[])
            if res:
                return (True,
                        res[0].get("brand_name","?"),
                        res[0].get("labeler_name","?"))
    except Exception:
        pass
    return False, None, None

def check_spelling(text):
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    errors, seen = [], set()
    for w in words:
        if w in seen:
            continue
        seen.add(w)
        if w in SPELL_MAP:
            errors.append({"word": w, "fix": SPELL_MAP[w]})
    return errors[:10]

def parse_expiry(text):
    pats = [
        (r"(?:EXP(?:IRY)?|EXPIRATION|USE\s*BEFORE|BB)[:\s]*(\d{2}[\/\-]\d{4})", "%m/%Y"),
        (r"(?:EXP(?:IRY)?)[:\s]*(\d{2}[\/\-]\d{2}[\/\-]\d{4})", "%d/%m/%Y"),
        (r"(\d{2}[\/\-]\d{4})", "%m/%Y"),
        (r"(\d{2}[\/\-]\d{2}[\/\-]\d{4})", "%d/%m/%Y"),
        (r"((?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[.\s]\d{4})", "%b %Y"),
    ]
    for pat, fmt in pats:
        for m in re.findall(pat, text.upper()):
            try:
                d    = datetime.strptime(m.replace("-","/").replace("."," "), fmt)
                left = (d - datetime.now()).days
                if   left < 0:   return f"EXPIRED — {abs(left)} days ago!", "bad",  left
                elif left < 90:  return f"Expires in {left} days", "warn", left
                else:            return f"Valid — {left//30} months left", "ok",   left
            except Exception:
                continue
    return "No expiry date detected", "unknown", 0

def detect_med(text):
    tl = text.lower()
    for m in MEDS:
        if m in tl:
            return m
    for w in re.findall(r"[a-z]+", tl):
        for m in MEDS:
            if len(w) > 5 and w in m:
                return m
    return None

@st.cache_data(ttl=3600)
def fda_label(med):
    try:
        r = requests.get(
            f"https://api.fda.gov/drug/label.json?search=openfda.brand_name:{med}&limit=1",
            timeout=6)
        if r.status_code == 200:
            res = r.json().get("results",[])
            if res:
                x = res[0]
                g = lambda k: x.get(k,["N/A"])[0][:250] if x.get(k) else "N/A"
                return {
                    "purpose":  g("purpose"),
                    "warnings": g("warnings"),
                    "dosage":   g("dosage_and_administration"),
                    "adverse":  g("adverse_reactions"),
                    "brand": x.get("openfda",{}).get("brand_name",["N/A"])[0],
                    "mfr":   x.get("openfda",{}).get("manufacturer_name",["N/A"])[0],
                }
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600)
def rxnorm_id(name):
    try:
        r   = requests.get(
            f"https://rxnav.nlm.nih.gov/REST/rxcui.json?name={name}", timeout=5)
        ids = r.json().get("idGroup",{}).get("rxnormId",[])
        return ids[0] if ids else None
    except Exception:
        return None

@st.cache_data(ttl=3600)
def drug_interactions(m1, m2):
    try:
        i1, i2 = rxnorm_id(m1), rxnorm_id(m2)
        if not i1 or not i2:
            return None
        r   = requests.get(
            f"https://rxnav.nlm.nih.gov/REST/interaction/list.json?rxcuis={i1}+{i2}",
            timeout=5)
        out = []
        for g in r.json().get("fullInteractionTypeGroup",[]):
            for t in g.get("fullInteractionType",[]):
                for p in t.get("interactionPair",[]):
                    out.append({"sev":  p.get("severity","Unknown"),
                                "desc": p.get("description","")})
        return out or None
    except Exception:
        return None

def risk_card(r, med):
    risks, w = [], 0
    if   r["sh"] < 40:  risks.append({"f":"Blurry Print",         "w":25,"l":"HIGH",  "d":"Below genuine standard"}); w+=25
    elif r["sh"] < 70:  risks.append({"f":"Moderate Sharpness",   "w":10,"l":"MED",   "d":"Borderline quality"}); w+=10
    if   r["co"] < 40:  risks.append({"f":"Faded Colours",        "w":25,"l":"HIGH",  "d":"Below genuine packaging"}); w+=25
    elif r["co"] < 70:  risks.append({"f":"Slightly Dull Colours","w":8, "l":"LOW",   "d":"Slightly below normal"}); w+=8
    if   r["ed"] < 30:  risks.append({"f":"Poor Print Density",   "w":20,"l":"HIGH",  "d":"Below genuine label standard"}); w+=20
    if r.get("spell"):
        n = len(r["spell"]); wt = min(n*8, 24)
        risks.append({"f":f"{n} Spelling Error(s)","w":wt,
                      "l":"HIGH" if n>=2 else "MED","d":"Strong fake indicator"}); w+=wt
    if   r.get("es")=="bad":     risks.append({"f":"EXPIRED","w":30,"l":"CRIT","d":"Do NOT consume"}); w+=30
    elif r.get("es")=="warn":    risks.append({"f":"Expiring Soon","w":10,"l":"MED","d":"Use with caution"}); w+=10
    elif r.get("es")=="unknown": risks.append({"f":"No Expiry Date","w":12,"l":"MED","d":"Always shown on genuine"}); w+=12
    # Barcode check removed
    if not med:                  risks.append({"f":"Name Unreadable","w":8,"l":"MED","d":"OCR could not find name"}); w+=8
    total = min(w, 100)
    if   total >= 60: vd = ("VERY HIGH RISK","#ef4444")
    elif total >= 35: vd = ("MODERATE RISK", "#f59e0b")
    elif total >= 15: vd = ("LOW RISK",       "#60a5fa")
    else:             vd = ("MINIMAL RISK",   "#10b981")
    return risks, total, vd

# ─────────────────────────────────────────────────────────────────
# AI CHATBOT (Gemini removed — stub only)
# ─────────────────────────────────────────────────────────────────
def ask_ai(question, med_name, med_info, ocr="", history=None):
    """AI chatbot removed — Gemini AI feature has been disabled."""
    return (
        "⚠️ **AI chatbot is not available** — the Gemini AI feature has been removed.\n\n"
        "For medicine information, please refer to the medicine database cards below, "
        "or consult a licensed pharmacist or doctor.\n\n"
        "⚕️ Always consult a licensed pharmacist or doctor for personalised medical advice."
    )


# (Gemini Vision feature removed)
def gemini_vision_analyse(img_pil, med_name=""):
    """Gemini Vision feature removed."""
    return None, "Gemini Vision feature has been removed."

def parse_vision_response(text):
    """Gemini Vision feature removed."""
    return {}


# ─────────────────────────────────────────────────────────────────
# SAFETY CERTIFICATE — HTML badge for genuine medicines
# ─────────────────────────────────────────────────────────────────
def make_certificate(med, score, username, city, is_genuine):
    """Generate a downloadable HTML safety certificate."""
    verdict  = "GENUINE ✅" if is_genuine else "COUNTERFEIT ⚠️"
    color    = "#10b981" if is_genuine else "#ef4444"
    bg_color = "#064e3b" if is_genuine else "#7f1d1d"
    border   = "#00f5a0" if is_genuine else "#ef4444"
    cert_id  = hashlib.sha256(
        f"{med}{username}{datetime.now().isoformat()}".encode()
    ).hexdigest()[:12].upper()
    now_str  = datetime.now().strftime("%d %B %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>PharmaScan Certificate — {med.title()}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;600&display=swap');
  body {{ margin:0; background:#0f172a; display:flex; justify-content:center; align-items:center; min-height:100vh; font-family:'DM Sans',sans-serif; }}
  .cert {{ width:680px; background:linear-gradient(135deg,#1e293b,#0f172a); border:3px solid {border}; border-radius:24px; padding:48px; text-align:center; box-shadow:0 0 60px {border}44; }}
  .logo {{ font-size:3.5rem; margin-bottom:8px; }}
  .title {{ font-family:'Syne',sans-serif; font-size:1rem; font-weight:700; color:#64748b; letter-spacing:4px; text-transform:uppercase; margin-bottom:24px; }}
  .verdict {{ font-family:'Syne',sans-serif; font-size:2.4rem; font-weight:800; color:{color}; background:{bg_color}; border:2px solid {border}; border-radius:16px; padding:20px 32px; margin:24px 0; display:inline-block; }}
  .med-name {{ font-family:'Syne',sans-serif; font-size:1.8rem; font-weight:800; color:#e2e8f0; margin:16px 0; }}
  .score {{ font-size:3rem; font-weight:800; color:{color}; font-family:'Syne',sans-serif; }}
  .score-lbl {{ color:#64748b; font-size:0.8rem; letter-spacing:2px; text-transform:uppercase; }}
  table {{ width:100%; border-collapse:collapse; margin:24px 0; text-align:left; }}
  td {{ padding:10px 16px; border-bottom:1px solid #1e293b; color:#94a3b8; font-size:0.9rem; }}
  td:first-child {{ color:#64748b; font-weight:600; width:45%; }}
  td:last-child {{ color:#e2e8f0; }}
  .cert-id {{ font-family:monospace; color:#475569; font-size:0.75rem; margin-top:24px; }}
  .footer-note {{ color:#374151; font-size:0.72rem; margin-top:16px; }}
  .badge {{ display:inline-block; background:rgba(99,102,241,0.15); border:1px solid #6366f1; border-radius:8px; padding:4px 12px; font-size:0.78rem; color:#a5b4fc; margin:4px; }}
</style>
</head>
<body>
<div class="cert">
  <div class="logo">🛡️</div>
  <div class="title">PharmaScan AI — Medicine Safety Certificate</div>
  <div class="med-name">{med.title()}</div>
  <div class="verdict">{verdict}</div>
  <div style="margin:16px 0">
    <div class="score">{score:.1f}%</div>
    <div class="score-lbl">AI Detection Score</div>
  </div>
  <table>
    <tr><td>Certificate ID</td><td><code>{cert_id}</code></td></tr>
    <tr><td>Verified By</td><td>{username}</td></tr>
    <tr><td>Location</td><td>{city}</td></tr>
    <tr><td>Date &amp; Time</td><td>{now_str}</td></tr>
    <tr><td>Technology</td><td>Computer Vision + OCR Analysis</td></tr>
  </table>
  <div>
    <span class="badge">🧠 Computer Vision</span>
    <span class="badge">🔡 Spell Check</span>
    <span class="badge">🏥 FDA Data</span>
  </div>
  <div class="cert-id">SHA-256 Certificate ID: {cert_id}</div>
  <div class="footer-note">This certificate is generated by PharmaScan AI for informational purposes only.<br>
  Always consult a licensed healthcare professional before consuming any medicine.</div>
</div>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────────
# HOTSPOT PREDICTOR (Gemini AI removed — stats-based only)
# ─────────────────────────────────────────────────────────────────
def predict_hotspots(df_scans):
    """Hotspot prediction now uses statistics only (Gemini AI removed)."""
    if df_scans is None or df_scans.empty:
        return None
    try:
        city_stats = {}
        for _, row in df_scans.iterrows():
            c = str(row.get("city", "Unknown"))
            if c not in city_stats:
                city_stats[c] = {"total": 0, "fake": 0, "medicines": []}
            city_stats[c]["total"] += 1
            if row.get("authentic", 1) == 0:
                city_stats[c]["fake"] += 1
            m = str(row.get("medicine", ""))
            if m and m not in city_stats[c]["medicines"]:
                city_stats[c]["medicines"].append(m)
        if not city_stats:
            return None
        sorted_cities = sorted(city_stats.items(),
                               key=lambda x: x[1]["fake"]/max(x[1]["total"],1),
                               reverse=True)
        lines = []
        top3 = [c for c, _ in sorted_cities[:3]]
        lines.append(f"🔴 HIGH RISK ZONES: {', '.join(top3)}")
        all_meds = [m for v in city_stats.values() for m in v["medicines"]]
        from collections import Counter
        top_meds = [m for m, _ in Counter(all_meds).most_common(3)]
        lines.append(f"💊 MOST COUNTERFEITED: {', '.join(top_meds) or 'Insufficient data'}")
        lines.append("📋 RECOMMENDATIONS:")
        lines.append("- Increase pharmacy inspections in high-risk zones")
        lines.append("- Alert healthcare providers in flagged cities")
        lines.append("- Cross-check suppliers for most counterfeited medicines")
        return "\n".join(lines)
    except Exception:
        return None

# Sender  = SENDER_EMAIL (hardcoded above — never shown to user)
# Receiver = user's login Gmail (st.session_state.user_email)
# ─────────────────────────────────────────────────────────────────
def send_alert(receiver, medicine, score, username):
    try:
        # Guard: skip if sender credentials are still placeholders
        if (not SENDER_EMAIL or "pharmascanai.alerts@gmail.com" in SENDER_EMAIL
                or not SENDER_APP_PASS or "xxxx" in SENDER_APP_PASS):
            return False, "Configure SENDER_EMAIL and SENDER_APP_PASS in code"

        if not receiver or "@" not in receiver:
            return False, "Invalid receiver email address"

        msg            = MIMEMultipart("alternative")
        msg["Subject"] = f"ALERT — Fake Medicine Detected: {medicine.title()}"
        msg["From"]    = f"PharmaScan AI <{SENDER_EMAIL}>"
        msg["To"]      = receiver

        html_body = f"""
<html><body style="font-family:Arial;background:#0f172a;color:#e2e8f0;padding:20px;margin:0">
<div style="max-width:520px;margin:40px auto;background:linear-gradient(135deg,#1e293b,#0f172a);
     border-radius:20px;padding:32px;border:2px solid #ef4444;
     box-shadow:0 20px 60px rgba(239,68,68,0.3)">
  <div style="text-align:center;margin-bottom:20px">
    <div style="font-size:3rem">&#x1F6E1;&#xFE0F;</div>
    <h1 style="color:#ef4444;margin:8px 0;font-size:1.5rem;font-family:Arial">
      FAKE MEDICINE DETECTED
    </h1>
    <p style="color:#94a3b8;font-size:0.82rem;margin:0">PharmaScan AI Alert System</p>
  </div>
  <div style="background:#450a0a;border:1px solid #ef4444;border-radius:12px;
       padding:14px;margin-bottom:20px">
    <p style="color:#fca5a5;font-size:0.9rem;margin:0">
      A scan by <strong>{username}</strong> detected a potentially
      <strong>counterfeit medicine</strong>. Do NOT consume this medicine.
    </p>
  </div>
  <table style="width:100%;font-size:0.9rem;border-collapse:collapse">
    <tr><td style="padding:8px 0;color:#94a3b8;width:45%">Medicine</td>
        <td style="color:#e2e8f0;font-weight:600">{medicine.title()}</td></tr>
    <tr><td style="padding:8px 0;color:#94a3b8">Vision Score</td>
        <td style="color:#ef4444;font-weight:700">{score:.1f}% — BELOW THRESHOLD</td></tr>
    <tr><td style="padding:8px 0;color:#94a3b8">Detected by</td>
        <td style="color:#e2e8f0">{username}</td></tr>
    <tr><td style="padding:8px 0;color:#94a3b8">Date and Time</td>
        <td style="color:#e2e8f0">{datetime.now().strftime("%d %B %Y, %H:%M")}</td></tr>
  </table>
  <div style="margin-top:20px;padding:14px;background:rgba(99,102,241,0.1);
       border:1px solid rgba(99,102,241,0.3);border-radius:10px">
    <p style="color:#a5b4fc;font-size:0.84rem;margin:0">
      Contact your nearest pharmacy or health authority immediately.
      Report fake medicines to your local drug regulatory body.
    </p>
  </div>
  <p style="text-align:center;color:#475569;font-size:0.72rem;margin-top:20px">
    PharmaScan AI — Vision-Based Fake Medicine Detection System
  </p>
</div></body></html>"""

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Try SMTP_SSL (port 465) first, fall back to STARTTLS (port 587)
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ",""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())
        except (ssl.SSLError, smtplib.SMTPConnectError, OSError):
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ",""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())

        return True, "Sent!"
    except smtplib.SMTPAuthenticationError:
        return False, ("Gmail auth failed — check SENDER_APP_PASS is a valid "
                       "16-char App Password (not your Gmail password)")
    except smtplib.SMTPRecipientsRefused:
        return False, f"Recipient address rejected by Gmail: {receiver}"
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {str(e)[:120]}"
    except Exception as e:
        return False, str(e)[:120]

# ─────────────────────────────────────────────────────────────────
# PDF REPORT — COMPLETE FULL DETAIL VERSION
# ─────────────────────────────────────────────────────────────────
def make_pdf(r, med, username, city="", lat=0.0, lon=0.0):
    if not PDF_OK:
        return None
    import hashlib as _hl
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            leftMargin=0.65*inch, rightMargin=0.65*inch)
    SS = getSampleStyleSheet()
    W  = 7.0 * inch   # usable width

    def S(name, **kw):
        return ParagraphStyle(name, parent=SS["Normal"], **kw)

    # ── colour palette ─────────────────────────────────────────────
    C_PRI   = colors.HexColor("#6366f1")
    C_OK    = colors.HexColor("#10b981")
    C_BAD   = colors.HexColor("#ef4444")
    C_WARN  = colors.HexColor("#f59e0b")
    C_DARK  = colors.HexColor("#1e293b")
    C_LITE  = colors.HexColor("#f8fafc")
    C_MUT   = colors.HexColor("#64748b")
    C_BDR   = colors.HexColor("#e2e8f0")
    C_VER   = C_OK if r["ok"] else C_BAD
    C_VBG   = colors.HexColor("#064e3b") if r["ok"] else colors.HexColor("#7f1d1d")
    C_VTC   = colors.HexColor("#d1fae5") if r["ok"] else colors.HexColor("#fee2e2")

    # ── styles ─────────────────────────────────────────────────────
    T_HEAD = S("TH", fontSize=22, textColor=C_PRI, fontName="Helvetica-Bold", spaceAfter=2)
    T_SUB  = S("TS", fontSize=9,  textColor=C_MUT, spaceAfter=2)
    T_SEC  = S("SEC",fontSize=12, textColor=C_DARK, fontName="Helvetica-Bold",
               spaceBefore=10, spaceAfter=4,
               borderPad=3, borderColor=C_PRI,
               underlineWidth=1, underlineColor=C_PRI)
    T_BODY = S("BD", fontSize=9.5, textColor=C_DARK, spaceAfter=3, leading=14)
    T_FOOT = S("FT", fontSize=7.5, textColor=C_MUT,  leading=11)
    T_MONO = S("MN", fontSize=8,   textColor=C_MUT,  fontName="Courier", leading=12)

    def section(title):
        return [
            Spacer(1, 0.08*inch),
            Paragraph(f"<b>{title}</b>",
                      S(f"S_{title[:6]}", fontSize=11, textColor=C_PRI,
                        fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=3,
                        borderPad=2)),
            # thin rule under section title
        ]

    def two_col_table(rows, col_w=(2.0*inch, 5.0*inch)):
        """Key-value table."""
        data = [[Paragraph(f"<b>{k}</b>", S("K", fontSize=9, textColor=C_MUT)),
                 Paragraph(str(v), S("V", fontSize=9.5, textColor=C_DARK, leading=13))]
                for k, v in rows]
        t = Table(data, colWidths=list(col_w))
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0,0),(-1,-1), [C_LITE, colors.white]),
            ("GRID",           (0,0),(-1,-1), 0.3, C_BDR),
            ("TOPPADDING",     (0,0),(-1,-1), 5),
            ("BOTTOMPADDING",  (0,0),(-1,-1), 5),
            ("LEFTPADDING",    (0,0),(-1,-1), 8),
            ("RIGHTPADDING",   (0,0),(-1,-1), 8),
            ("VALIGN",         (0,0),(-1,-1), "TOP"),
        ]))
        return t

    # cert id
    cert_id = _hl.sha256(
        f"{med}{username}{datetime.now().isoformat()}".encode()
    ).hexdigest()[:14].upper()

    story = []

    # ══ HEADER ════════════════════════════════════════════════════
    hdr = Table([[
        Paragraph("🛡️ PharmaScan AI", S("HD", fontSize=18, textColor=C_PRI,
                  fontName="Helvetica-Bold")),
        Paragraph("MEDICINE SAFETY REPORT",
                  S("HR", fontSize=9, textColor=C_MUT, alignment=2))
    ]], colWidths=[4*inch, 3*inch])
    hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                              ("LINEBELOW",(0,0),(-1,0),1.5,C_PRI)]))
    story += [hdr, Spacer(1, 0.04*inch)]

    story.append(Paragraph(
        f"Date: <b>{datetime.now().strftime('%d %B %Y, %H:%M')}</b>  |  "
        f"Scanned by: <b>{username}</b>  |  "
        f"Certificate ID: <b>{cert_id}</b>",
        S("SB", fontSize=8.5, textColor=C_MUT, spaceAfter=8)))

    # ══ VERDICT BANNER ════════════════════════════════════════════
    vt   = "✅  GENUINE MEDICINE" if r["ok"] else "🚨  FAKE / COUNTERFEIT DETECTED"
    v_sc = f"Detection Score: {r['score']:.1f}%"
    vbnr = Table([[Paragraph(vt,  S("VT", fontSize=15, textColor=C_VTC, fontName="Helvetica-Bold")),
                   Paragraph(v_sc,S("VS", fontSize=12, textColor=C_VTC, fontName="Helvetica-Bold", alignment=2))]],
                 colWidths=[4.5*inch, 2.5*inch])
    vbnr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_VBG),
        ("BOX",           (0,0),(-1,-1), 2,   C_VER),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 14),
        ("BOTTOMPADDING", (0,0),(-1,-1), 14),
        ("LEFTPADDING",   (0,0),(-1,-1), 16),
        ("RIGHTPADDING",  (0,0),(-1,-1), 16),
    ]))
    story += [vbnr, Spacer(1, 0.12*inch)]

    # ══ SCAN DETAILS ══════════════════════════════════════════════
    story += section("1. Scan Details")
    scan_rows = [
        ("Medicine Detected", (med.title() if med else "Not detected — name unreadable")),
        ("Scanned By",        username),
        ("Scan Date & Time",  datetime.now().strftime("%d %B %Y, %H:%M:%S")),
        ("Location / City",   city if city else "Not specified"),
        ("GPS Coordinates",   f"{lat:.4f}, {lon:.4f}" if lat and lon else "Not available"),
        ("Certificate ID",    cert_id),
        ("Verdict",           "GENUINE" if r["ok"] else "FAKE / COUNTERFEIT"),
        ("Confidence Score",  f"{r['score']:.1f}%  (Threshold: 72%)"),
    ]
    story += [two_col_table(scan_rows), Spacer(1, 0.06*inch)]

    # ══ VISION ANALYSIS ═══════════════════════════════════════════
    story += section("2. Vision Analysis")
    va_data = [
        ["Parameter", "Score", "Status", "Interpretation"],
        ["Sharpness (Laplacian)",
         f"{r['sh']:.1f}%",
         "✅ Good" if r["sh"] > 40 else "❌ Low",
         "Genuine labels are sharp and well-printed" if r["sh"] > 40 else "Blurry — possible counterfeit reprint"],
        ["Colour Consistency (HSV)",
         f"{r['co']:.1f}%",
         "✅ Good" if r["co"] > 40 else "❌ Faded",
         "Normal colour saturation" if r["co"] > 40 else "Faded colours — below genuine standard"],
        ["Print Density (Canny)",
         f"{r['ed']:.1f}%",
         "✅ Good" if r["ed"] > 30 else "❌ Low",
         "Good print detail detected" if r["ed"] > 30 else "Low edge density — poor print quality"],
    ]
    va_t = Table(va_data, colWidths=[1.8*inch, 0.9*inch, 0.9*inch, 3.4*inch])
    va_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0), C_PRI),
        ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
        ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,-1), 8.5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [C_LITE, colors.white]),
        ("GRID",          (0,0),(-1,-1), 0.3, C_BDR),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 7),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    story += [va_t, Spacer(1, 0.06*inch)]

    # Visual inspection checks
    if r.get("checks"):
        story += section("3. Visual Inspection Checks")
        chk_data = [["Icon", "Check", "Status"]]
        for ico, msg_c, st_c in r["checks"]:
            clr_c = C_OK if st_c == "ok" else C_BAD if st_c == "bad" else C_WARN
            chk_data.append([ico, msg_c,
                             Paragraph(f"<b>{'PASS' if st_c=='ok' else 'WARN' if st_c=='warn' else 'FAIL'}</b>",
                                       S("CS", fontSize=8.5, textColor=clr_c, fontName="Helvetica-Bold"))])
        chk_t = Table(chk_data, colWidths=[0.4*inch, 5.4*inch, 1.2*inch])
        chk_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), colors.HexColor("#334155")),
            ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,-1), 8.5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [C_LITE, colors.white]),
            ("GRID",          (0,0),(-1,-1), 0.3, C_BDR),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
            ("LEFTPADDING",   (0,0),(-1,-1), 7),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ]))
        story += [chk_t, Spacer(1, 0.06*inch)]

    # ══ RISK SCORE ════════════════════════════════════════════════
    story += section("4. Risk Score Breakdown")
    # Compute risk inline
    risks_pdf, rtot_pdf = [], 0
    if r.get("sh",100) < 40:  risks_pdf.append(("Blurry Print",25,"HIGH")); rtot_pdf+=25
    elif r.get("sh",100) < 70: risks_pdf.append(("Moderate Sharpness",10,"MED")); rtot_pdf+=10
    if r.get("co",100) < 40:  risks_pdf.append(("Faded Colours",25,"HIGH")); rtot_pdf+=25
    elif r.get("co",100) < 70: risks_pdf.append(("Dull Colours",8,"LOW")); rtot_pdf+=8
    if r.get("ed",100) < 30:  risks_pdf.append(("Poor Print Density",20,"HIGH")); rtot_pdf+=20
    if r.get("spell"):
        n=len(r["spell"]); wt=min(n*8,24)
        risks_pdf.append((f"{n} Spelling Error(s)",wt,"HIGH" if n>=2 else "MED")); rtot_pdf+=wt
    es=r.get("es","")
    if es=="bad":     risks_pdf.append(("EXPIRED Medicine",30,"CRIT")); rtot_pdf+=30
    elif es=="warn":  risks_pdf.append(("Expiring Soon",10,"MED")); rtot_pdf+=10
    elif es=="unknown": risks_pdf.append(("No Expiry Date",12,"MED")); rtot_pdf+=12
    # Barcode check removed
    if not med:         risks_pdf.append(("Name Unreadable",8,"MED")); rtot_pdf+=8
    rtot_pdf = min(rtot_pdf, 100)
    if   rtot_pdf >= 60: rvd_pdf,rclr_pdf = "VERY HIGH RISK", C_BAD
    elif rtot_pdf >= 35: rvd_pdf,rclr_pdf = "MODERATE RISK",  C_WARN
    elif rtot_pdf >= 15: rvd_pdf,rclr_pdf = "LOW RISK",       colors.HexColor("#60a5fa")
    else:                rvd_pdf,rclr_pdf = "MINIMAL RISK",   C_OK

    risk_sum = Table([[
        Paragraph(f"<b>Overall Risk: {rvd_pdf}</b>",
                  S("RS", fontSize=11, textColor=colors.white, fontName="Helvetica-Bold")),
        Paragraph(f"<b>{rtot_pdf}%</b>",
                  S("RP", fontSize=13, textColor=colors.white, fontName="Helvetica-Bold", alignment=2))
    ]], colWidths=[5.5*inch, 1.5*inch])
    risk_sum.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), rclr_pdf),
        ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(risk_sum)
    if risks_pdf:
        r_data = [["Risk Factor", "Weight", "Level"]]
        for rf, rw, rl in risks_pdf:
            lclr = C_BAD if rl in ("HIGH","CRIT") else C_WARN if rl=="MED" else C_OK
            r_data.append([rf, f"+{rw}%",
                           Paragraph(f"<b>{rl}</b>",
                                     S(f"RL{rl}", fontSize=8.5, textColor=lclr,
                                       fontName="Helvetica-Bold"))])
        r_t = Table(r_data, colWidths=[4.5*inch, 1.0*inch, 1.5*inch])
        r_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), colors.HexColor("#334155")),
            ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,-1), 8.5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [C_LITE, colors.white]),
            ("GRID",          (0,0),(-1,-1), 0.3, C_BDR),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
            ("LEFTPADDING",   (0,0),(-1,-1), 8),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ]))
        story += [r_t, Spacer(1, 0.06*inch)]

    # ══ EXPIRY DATE ═══════════════════════════════════════════════
    story += section("5. Expiry Date Analysis")
    exp_clr = C_BAD if r.get("es")=="bad" else C_WARN if r.get("es")=="warn" else C_OK if r.get("es")=="ok" else C_MUT
    story.append(Paragraph(
        f"<b>Result:</b> {r.get('expiry_msg','Not detected')}",
        S("EX", fontSize=9.5, textColor=exp_clr, spaceAfter=4)))

    # ══ SPELLING ERRORS ═══════════════════════════════════════════
    story += section("6. Spelling / Label Error Detection")
    if r.get("spell"):
        story.append(Paragraph(
            f"<b>⚠️ {len(r['spell'])} spelling error(s) detected — strong indicator of counterfeit packaging</b>",
            S("SPH", fontSize=9.5, textColor=C_BAD, spaceAfter=4)))
        sp_data = [["Detected (Wrong)", "Correct Spelling"]]
        for se in r["spell"]:
            sp_data.append([se["word"], se["fix"]])
        sp_t = Table(sp_data, colWidths=[3.5*inch, 3.5*inch])
        sp_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), C_BAD),
            ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,-1), 9),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.HexColor("#fff1f2"), colors.white]),
            ("GRID",          (0,0),(-1,-1), 0.3, C_BDR),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ]))
        story += [sp_t, Spacer(1, 0.05*inch)]
    else:
        story.append(Paragraph("✅ No spelling errors detected — label text appears genuine.",
                                S("SPO", fontSize=9.5, textColor=C_OK, spaceAfter=4)))


    # ══ MEDICINE INFORMATION ══════════════════════════════════════
    if med and med in MEDS:
        info = MEDS[med]
        story += section("8. Medicine Information")
        med_rows = [
            ("Medicine Name",   med.title()),
            ("Category",        info.get("cat", "N/A")),
            ("Typical Colour",  info.get("colour", "N/A")),
            ("Tablet Shape",    info.get("shape", "N/A")),
            ("Genuine Signs",   info.get("genuine", "N/A")),
            ("Use / Indication",info.get("use", "N/A")),
            ("Dosage",          info.get("dosage", "N/A")),
            ("Side Effects",    info.get("se", "N/A")),
            ("Warning",         info.get("warn", "N/A")),
            ("Drug Interactions", ", ".join(info.get("inter", [])) or "None listed"),
        ]
        story += [two_col_table(med_rows, (1.8*inch, 5.2*inch)), Spacer(1, 0.05*inch)]

    # ══ FDA LABEL DATA ════════════════════════════════════════════
    if r.get("fda"):
        story += section("9. FDA Label Data")
        fda_rows = [
            ("Brand Name",    r["fda"].get("brand","N/A")),
            ("Manufacturer",  r["fda"].get("mfr","N/A")),
            ("Purpose",       r["fda"].get("purpose","N/A")),
            ("Warnings",      r["fda"].get("warnings","N/A")),
            ("Dosage (FDA)",  r["fda"].get("dosage","N/A")),
            ("Adverse Reactions", r["fda"].get("adverse","N/A")),
        ]
        story += [two_col_table(fda_rows, (1.8*inch, 5.2*inch)), Spacer(1, 0.05*inch)]

    # ══ OCR TEXT ══════════════════════════════════════════════════
    story += section("10. Extracted OCR Text (Label)")
    ocr_text = r.get("ocr","") or "No text extracted"
    story.append(Paragraph(ocr_text[:1200] + ("..." if len(ocr_text)>1200 else ""),
                            S("OCR", fontSize=8, textColor=C_MUT, fontName="Courier",
                              leading=12, spaceAfter=4)))

    # ══ FOOTER ════════════════════════════════════════════════════
    story += [
        Spacer(1, 0.15*inch),
        Paragraph(
            "─" * 80,
            S("HR2", fontSize=6, textColor=C_BDR, spaceAfter=4)),
        Paragraph(
            f"PharmaScan AI — Vision-Based Fake Medicine Detection System  |  "
            f"Certificate ID: {cert_id}  |  Generated: {datetime.now().strftime('%d %b %Y %H:%M')}",
            S("F1", fontSize=7.5, textColor=C_MUT, alignment=1, spaceAfter=2)),
        Paragraph(
            "⚕️ For informational purposes only. This report does not replace professional laboratory "
            "testing. Always consult a licensed pharmacist or healthcare professional before consuming "
            "any medicine. Report suspected counterfeit medicines to your local drug regulatory authority.",
            S("F2", fontSize=7, textColor=C_MUT, alignment=1, leading=10)),
    ]

    doc.build(story)
    buf.seek(0)
    return buf.read()

import random, string

def generate_otp():
    """Generate a 6-digit numeric OTP."""
    return "".join(random.choices(string.digits, k=6))

def send_welcome_email(receiver, username, role, id_type="", id_number=""):
    """Send a welcome/confirmation email after successful registration."""
    try:
        if not receiver or "@" not in receiver or "@pharmascan.demo" in receiver:
            return
        role_lbl  = "Expert / Pharmacist" if role == "expert" else "Patient / User"
        role_ico  = "👨‍⚕️" if role == "expert" else "👤"
        id_section = ""
        if role == "expert" and id_type:
            id_type_clean = id_type.split(" ",1)[-1] if id_type else id_type
            id_section = f"""
  <div style="background:#0f2744;border:1px solid #6366f1;border-radius:12px;padding:12px 16px;margin-top:12px">
    <p style="color:#a5b4fc;font-size:.82rem;font-weight:700;margin:0 0 6px">🪪 Professional ID Submitted</p>
    <p style="color:#94a3b8;font-size:.8rem;margin:2px 0">Type: {id_type_clean}</p>
    <p style="color:#94a3b8;font-size:.8rem;margin:2px 0">License No.: {id_number}</p>
    <p style="color:#64748b;font-size:.75rem;margin:6px 0 0">Your ID will be reviewed. You can answer patient questions immediately.</p>
  </div>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Welcome to PharmaScan AI — Account Created Successfully"
        msg["From"]    = f"PharmaScan AI <{SENDER_EMAIL}>"
        msg["To"]      = receiver
        now_str = datetime.now().strftime("%d %B %Y, %H:%M")

        html_body = f"""
<html><body style="font-family:Arial,sans-serif;background:#060918;color:#e2e8f0;padding:20px;margin:0">
<div style="max-width:500px;margin:32px auto;background:linear-gradient(135deg,#1e293b,#0f172a);
  border-radius:20px;padding:32px;border:1px solid rgba(99,102,241,.3);
  box-shadow:0 20px 60px rgba(0,0,0,.6)">

  <div style="text-align:center;margin-bottom:24px">
    <div style="font-size:3rem">🛡️</div>
    <h1 style="color:#a78bfa;font-size:1.4rem;margin:8px 0;font-family:Arial">Welcome to PharmaScan AI</h1>
    <p style="color:#64748b;font-size:.82rem;margin:0">Vision-Based Fake Medicine Detection</p>
  </div>

  <div style="background:rgba(16,185,129,.1);border:1px solid #10b981;border-radius:12px;
    padding:14px 16px;margin-bottom:20px;text-align:center">
    <p style="color:#6ee7b7;font-size:.95rem;font-weight:700;margin:0">
      ✅ Your account has been created successfully!</p>
  </div>

  <p style="color:#94a3b8;font-size:.88rem;margin-bottom:16px">Hello <b style="color:#e2e8f0">{username}</b>,</p>
  <p style="color:#94a3b8;font-size:.85rem;line-height:1.6;margin-bottom:20px">
    Thank you for joining PharmaScan AI. Your account is now active and ready to use.
    Here are your account details:</p>

  <table style="width:100%;border-collapse:collapse;font-size:.85rem">
    <tr style="border-bottom:1px solid #1e293b">
      <td style="color:#64748b;padding:8px 0;width:40%">Username</td>
      <td style="color:#e2e8f0;font-weight:700">{username}</td>
    </tr>
    <tr style="border-bottom:1px solid #1e293b">
      <td style="color:#64748b;padding:8px 0">Email</td>
      <td style="color:#e2e8f0">{receiver}</td>
    </tr>
    <tr style="border-bottom:1px solid #1e293b">
      <td style="color:#64748b;padding:8px 0">Role</td>
      <td style="color:#e2e8f0">{role_ico} {role_lbl}</td>
    </tr>
    <tr style="border-bottom:1px solid #1e293b">
      <td style="color:#64748b;padding:8px 0">Registered On</td>
      <td style="color:#e2e8f0">{now_str}</td>
    </tr>
    <tr>
      <td style="color:#64748b;padding:8px 0">Auto-Alerts</td>
      <td style="color:#10b981;font-weight:700">✅ Enabled — fake medicines trigger instant alerts</td>
    </tr>
  </table>

  {id_section}

  <div style="margin-top:20px;background:rgba(99,102,241,.08);border-radius:12px;padding:14px 16px">
    <p style="color:#a5b4fc;font-size:.82rem;font-weight:700;margin:0 0 8px">🚀 What you can do:</p>
    {"<p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Scan medicines for authenticity</p><p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Ask medicine questions in the Q&A Forum</p><p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ View your scan history and analytics</p><p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Download safety reports and certificates</p>" if role != "expert" else "<p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Scan medicines for authenticity</p><p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Answer patient questions in the Q&A Forum</p><p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Access all patient scan reports</p><p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Use Bulk Scan, Drug Database, and Analytics</p><p style='color:#94a3b8;font-size:.8rem;margin:3px 0'>✅ Send public health alerts to all patients</p>"}
  </div>

  <p style="color:#475569;font-size:.72rem;text-align:center;margin-top:20px">
    PharmaScan AI — For informational purposes only.<br>
    Always consult a licensed healthcare professional before consuming any medicine.
  </p>
</div>
</body></html>"""

        msg.attach(MIMEText(html_body, "html", "utf-8"))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ",""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())
        except Exception:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
                s.ehlo(); s.starttls(); s.ehlo()
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ",""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())
    except Exception:
        pass  # Welcome email is best-effort; never block registration


def send_deletion_email(receiver, username, role):
    """Send account deletion confirmation email."""
    try:
        if not receiver or "@" not in receiver or "@pharmascan.demo" in receiver:
            return
        role_lbl = "Expert / Pharmacist" if role == "expert" else "Patient / User"
        now_str  = datetime.now().strftime("%d %B %Y, %H:%M")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "PharmaScan AI — Your Account Has Been Deleted"
        msg["From"]    = f"PharmaScan AI <{SENDER_EMAIL}>"
        msg["To"]      = receiver
        html_body = f"""
<html><body style="font-family:Arial,sans-serif;background:#060918;color:#e2e8f0;padding:20px;margin:0">
<div style="max-width:480px;margin:32px auto;background:linear-gradient(135deg,#1e293b,#0f172a);
  border-radius:20px;padding:32px;border:1px solid rgba(239,68,68,.3);
  box-shadow:0 20px 60px rgba(0,0,0,.6)">
  <div style="text-align:center;margin-bottom:24px">
    <div style="font-size:3rem">🛡️</div>
    <h1 style="color:#ef4444;font-size:1.3rem;margin:8px 0">Account Deleted</h1>
    <p style="color:#64748b;font-size:.82rem;margin:0">PharmaScan AI</p>
  </div>
  <div style="background:rgba(239,68,68,.1);border:1px solid #ef4444;border-radius:12px;
    padding:14px 16px;margin-bottom:20px">
    <p style="color:#fca5a5;font-size:.88rem;font-weight:700;margin:0">
      Your PharmaScan AI account has been permanently deleted.</p>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:.85rem">
    <tr style="border-bottom:1px solid #1e293b">
      <td style="color:#64748b;padding:8px 0;width:40%">Username</td>
      <td style="color:#e2e8f0;font-weight:700">{username}</td>
    </tr>
    <tr style="border-bottom:1px solid #1e293b">
      <td style="color:#64748b;padding:8px 0">Email</td>
      <td style="color:#e2e8f0">{receiver}</td>
    </tr>
    <tr style="border-bottom:1px solid #1e293b">
      <td style="color:#64748b;padding:8px 0">Role</td>
      <td style="color:#e2e8f0">{role_lbl}</td>
    </tr>
    <tr>
      <td style="color:#64748b;padding:8px 0">Deleted On</td>
      <td style="color:#e2e8f0">{now_str}</td>
    </tr>
  </table>
  <div style="margin-top:18px;background:rgba(255,255,255,.04);border-radius:10px;
    padding:12px 14px;font-size:.8rem;color:#94a3b8;line-height:1.6">
    <b style="color:#e2e8f0">What was deleted:</b><br>
    ✅ Account credentials &nbsp;·&nbsp; ✅ All scan history<br>
    ✅ Chat history &nbsp;·&nbsp; ✅ Q&amp;A posts and answers
  </div>
  <p style="color:#475569;font-size:.72rem;text-align:center;margin-top:20px">
    If you did not request this deletion, please contact us immediately.<br>
    PharmaScan AI — pharmascanai26@gmail.com
  </p>
</div>
</body></html>"""
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ",""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())
        except Exception:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
                s.ehlo(); s.starttls(); s.ehlo()
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ",""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())
    except Exception:
        pass


def send_otp_email(receiver, otp):
    """Send OTP verification email during registration."""
    try:
        if not SENDER_EMAIL or not SENDER_APP_PASS:
            return False, "Sender email not configured."
        if not receiver or "@" not in receiver:
            return False, "Invalid email address."
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = "PharmaScan AI — Your OTP Verification Code"
        msg["From"]    = f"PharmaScan AI <{SENDER_EMAIL}>"
        msg["To"]      = receiver
        html_body = f"""
<html><body style="font-family:Arial;background:#0f172a;color:#e2e8f0;padding:20px;margin:0">
<div style="max-width:460px;margin:40px auto;background:linear-gradient(135deg,#1e293b,#0f172a);
     border-radius:20px;padding:32px;border:2px solid #6366f1;
     box-shadow:0 20px 60px rgba(99,102,241,0.3)">
  <div style="text-align:center;margin-bottom:20px">
    <div style="font-size:3rem">🛡️</div>
    <h1 style="color:#a78bfa;margin:8px 0;font-size:1.4rem">Email Verification</h1>
    <p style="color:#94a3b8;font-size:0.82rem;margin:0">PharmaScan AI Account Registration</p>
  </div>
  <p style="color:#94a3b8;font-size:0.9rem">Use the OTP below to verify your email. Expires in <strong style="color:#f59e0b">10 minutes</strong>.</p>
  <div style="text-align:center;margin:28px 0">
    <div style="font-size:2.8rem;font-weight:900;letter-spacing:12px;color:#00f5a0;
         background:#064e3b;border:2px solid #10b981;border-radius:14px;padding:18px 24px;
         display:inline-block">{otp}</div>
  </div>
  <p style="color:#475569;font-size:0.78rem;text-align:center">
    If you did not request this, please ignore this email.</p>
</div></body></html>"""
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ", ""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())
        except Exception:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
                s.ehlo(); s.starttls(); s.ehlo()
                s.login(SENDER_EMAIL, SENDER_APP_PASS.replace(" ", ""))
                s.sendmail(SENDER_EMAIL, receiver, msg.as_string())
        return True, "OTP sent!"
    except Exception as e:
        return False, str(e)[:120]


# ─────────────────────────────────────────────────────────────────
# Q&A FORUM DATABASE FUNCTIONS
# ─────────────────────────────────────────────────────────────────
def qa_post_question(username, email, question, medicine="", category="General"):
    c = sqlite3.connect(DB_PATH)
    c.execute("""INSERT INTO qa_questions(username,email,question,medicine,category,status,asked_at)
                 VALUES(?,?,?,?,?,'open',?)""",
              (username, email, question, medicine, category,
               datetime.now().strftime("%Y-%m-%d %H:%M")))
    c.commit(); c.close()

def qa_get_questions(status=None, category=None):
    c = sqlite3.connect(DB_PATH)
    try:
        q = "SELECT * FROM qa_questions ORDER BY id DESC LIMIT 100"
        df = pd.read_sql(q, c)
    except Exception:
        df = pd.DataFrame()
    c.close()
    if not df.empty and status:
        df = df[df["status"] == status]
    if not df.empty and category and category != "All":
        df = df[df["category"] == category]
    return df

def qa_post_answer(question_id, expert_username, expert_role, answer):
    c = sqlite3.connect(DB_PATH)
    c.execute("""INSERT INTO qa_answers(question_id,expert_username,expert_role,answer,answered_at)
                 VALUES(?,?,?,?,?)""",
              (question_id, expert_username, expert_role, answer,
               datetime.now().strftime("%Y-%m-%d %H:%M")))
    # Mark question as answered
    c.execute("UPDATE qa_questions SET status='answered' WHERE id=?", (question_id,))
    c.commit(); c.close()

def qa_get_answers(question_id):
    c = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql(
            "SELECT * FROM qa_answers WHERE question_id=? ORDER BY id ASC",
            c, params=(question_id,))
    except Exception:
        df = pd.DataFrame()
    c.close(); return df

def qa_upvote_question(question_id):
    c = sqlite3.connect(DB_PATH)
    c.execute("UPDATE qa_questions SET upvotes = upvotes+1 WHERE id=?", (question_id,))
    c.commit(); c.close()

def qa_upvote_answer(answer_id):
    c = sqlite3.connect(DB_PATH)
    c.execute("UPDATE qa_answers SET helpful_votes = helpful_votes+1 WHERE id=?", (answer_id,))
    c.commit(); c.close()

def qa_delete_question(question_id, username):
    c = sqlite3.connect(DB_PATH)
    c.execute("DELETE FROM qa_questions WHERE id=? AND username=?", (question_id, username))
    c.execute("DELETE FROM qa_answers WHERE question_id=?", (question_id,))
    c.commit(); c.close()

# ─────────────────────────────────────────────────────────────────
# CREATIVE LOGIN PAGE CSS  — Full animated medical-grade UI
# ─────────────────────────────────────────────────────────────────
LOGIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&display=swap');

*, *::before, *::after { box-sizing:border-box; margin:0; padding:0; font-family:'DM Sans',sans-serif !important; }
h1,h2,h3 { font-family:'Syne',sans-serif !important; }

/* ─ Full page ─────────────────────────────────── */
.stApp { background:#02040f !important; min-height:100vh; overflow:hidden; }
section[data-testid="stSidebar"],
[data-testid="stDecoration"],
#MainMenu, footer { display:none !important; }
header[data-testid="stHeader"] { background:transparent !important; border:none !important; }
.block-container { padding-top:1rem !important; }

/* ─ Animated starfield ────────────────────────── */
.starfield {
    position:fixed; inset:0; z-index:0; pointer-events:none;
    background:
        radial-gradient(ellipse at 15% 40%, rgba(99,102,241,0.18) 0%, transparent 55%),
        radial-gradient(ellipse at 85% 15%, rgba(167,139,250,0.14) 0%, transparent 50%),
        radial-gradient(ellipse at 55% 85%, rgba(0,245,160,0.10)  0%, transparent 45%),
        radial-gradient(ellipse at 5%  95%, rgba(244,114,182,0.09) 0%, transparent 40%),
        radial-gradient(ellipse at 90% 70%, rgba(96,165,250,0.08)  0%, transparent 40%);
    animation: bgPulse 10s ease-in-out infinite alternate;
}
@keyframes bgPulse {
    0%   { filter:brightness(1)   hue-rotate(0deg);  }
    100% { filter:brightness(1.2) hue-rotate(25deg); }
}

/* ─ Floating DNA blobs ────────────────────────── */
.blob {
    position:fixed; border-radius:50%; pointer-events:none; z-index:0;
    filter:blur(80px); opacity:0.4;
    animation: blobDrift ease-in-out infinite alternate;
}
.b1 { width:500px; height:500px; top:-150px; left:-150px;
      background:radial-gradient(circle,rgba(99,102,241,0.5),transparent 70%);
      animation-duration:9s; }
.b2 { width:400px; height:400px; bottom:-100px; right:-100px;
      background:radial-gradient(circle,rgba(0,245,160,0.4),transparent 70%);
      animation-duration:12s; animation-delay:2s; }
.b3 { width:300px; height:300px; top:45%; left:55%;
      background:radial-gradient(circle,rgba(244,114,182,0.35),transparent 70%);
      animation-duration:10s; animation-delay:4s; }
.b4 { width:200px; height:200px; top:20%; right:20%;
      background:radial-gradient(circle,rgba(96,165,250,0.3),transparent 70%);
      animation-duration:8s; animation-delay:1s; }
@keyframes blobDrift {
    0%   { transform:translate(0,0)     scale(1);   }
    100% { transform:translate(40px,30px) scale(1.15); }
}

/* ─ Scan beam across screen ──────────────────── */
.scanbeam {
    position:fixed; top:0; left:0; width:100%; height:2px; z-index:1;
    background:linear-gradient(90deg,transparent,rgba(0,245,160,0.8),transparent);
    box-shadow:0 0 20px rgba(0,245,160,0.5);
    animation:beamDown 7s linear infinite;
}
@keyframes beamDown {
    0%   { top:-2px;   }
    100% { top:100vh;  }
}

/* ─ Main card ─────────────────────────────────── */
.lcard {
    position:relative; z-index:2;
    background:linear-gradient(160deg, rgba(13,21,44,0.97) 0%, rgba(8,14,30,0.99) 100%);
    border-radius:30px; padding:2.8rem 2.6rem 2.2rem;
    border:1px solid rgba(99,102,241,0.28);
    box-shadow:
        0 0 0 1px rgba(255,255,255,0.03),
        0 50px 100px rgba(0,0,0,0.8),
        0 0 100px rgba(99,102,241,0.07),
        inset 0 1px 0 rgba(255,255,255,0.04);
    backdrop-filter:blur(30px);
    max-width:460px; margin:0 auto;
}

/* ─ Shield logo ───────────────────────────────── */
.shield-wrap {
    display:flex; justify-content:center; margin-bottom:1.4rem;
    position:relative;
}
.shield-ring {
    width:88px; height:88px; border-radius:50%;
    background:linear-gradient(135deg,#1a2444,#0d1428);
    border:1.5px solid rgba(99,102,241,0.35);
    display:flex; align-items:center; justify-content:center;
    position:relative; flex-shrink:0;
    box-shadow:0 0 40px rgba(99,102,241,0.2), inset 0 1px 0 rgba(255,255,255,0.05);
    animation:shieldPulse 4s ease-in-out infinite;
}
@keyframes shieldPulse {
    0%,100% { box-shadow:0 0 30px rgba(99,102,241,0.2); }
    50%     { box-shadow:0 0 60px rgba(99,102,241,0.5), 0 0 30px rgba(0,245,160,0.2); }
}
.shield-ring::before, .shield-ring::after {
    content:''; position:absolute; border-radius:50%;
    border:1px solid rgba(99,102,241,0.15);
    animation:ringExpand 3s ease-out infinite;
}
.shield-ring::before { width:130%; height:130%; animation-delay:0s; }
.shield-ring::after  { width:160%; height:160%; animation-delay:1.2s; }
@keyframes ringExpand {
    0%   { opacity:0.9; transform:scale(0.85); }
    100% { opacity:0;   transform:scale(1.4);  }
}
.shield-emoji { font-size:2.6rem; line-height:1; }

/* ─ Title ─────────────────────────────────────── */
.ltitle {
    font-family:'Syne',sans-serif !important;
    font-size:clamp(1.6rem, 5vw, 2.5rem); font-weight:800; text-align:center;
    background:linear-gradient(90deg,#00f5a0 0%,#00d9f5 30%,#a78bfa 65%,#f472b6 100%);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    letter-spacing:-1px; line-height:1.1;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    background-size:300%; animation:titleFlow 5s linear infinite;
}
@keyframes titleFlow {
    0%   { background-position:0%;   }
    100% { background-position:300%; }
}
.lsub {
    text-align:center; font-size:0.78rem; font-weight:500;
    color:rgba(148,163,184,0.6) !important;
    letter-spacing:2px; text-transform:uppercase;
    margin:0.4rem 0 1.8rem;
}

/* ─ Live counter bar ──────────────────────────── */
.counter-bar {
    display:flex; gap:1px; border-radius:16px; overflow:hidden;
    border:1px solid rgba(255,255,255,0.05);
    background:rgba(255,255,255,0.02);
    margin-bottom:1.8rem;
}
.ctr {
    flex:1; padding:1rem 0.5rem; text-align:center;
    border-right:1px solid rgba(255,255,255,0.04);
    transition:background 0.3s;
}
.ctr:last-child { border-right:none; }
.ctr:hover { background:rgba(99,102,241,0.08); }
.ctr-val {
    font-family:'Syne',sans-serif !important;
    font-size:1.35rem; font-weight:800; line-height:1;
    animation:countUp 2s ease-out;
}
@keyframes countUp {
    0%   { transform:translateY(8px); opacity:0; }
    100% { transform:translateY(0);   opacity:1; }
}
.ctr-lbl { font-size:0.58rem; font-weight:700; color:rgba(148,163,184,0.5) !important; text-transform:uppercase; letter-spacing:1.2px; margin-top:4px; }

/* ─ Feature pills ─────────────────────────────── */
.fpills { display:flex; flex-wrap:wrap; gap:5px; justify-content:center; margin-bottom:1.8rem; }
.fp {
    padding:3px 10px; border-radius:20px; font-size:0.67rem; font-weight:600;
    background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08);
    color:rgba(180,195,215,0.8) !important; letter-spacing:0.2px;
    transition:all 0.2s;
}
.fp:hover { background:rgba(99,102,241,0.15); border-color:rgba(99,102,241,0.4); }

/* ─ Role icons ────────────────────────────────── */
.roles { display:grid; grid-template-columns:repeat(4,1fr); gap:7px; margin-bottom:1.8rem; }
.role {
    background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.07);
    border-radius:14px; padding:0.75rem 0.3rem; text-align:center;
    transition:all 0.25s; cursor:default;
}
.role:hover {
    background:rgba(99,102,241,0.12); border-color:rgba(99,102,241,0.4);
    transform:translateY(-3px); box-shadow:0 8px 20px rgba(99,102,241,0.2);
}
.role-i { font-size:1.35rem; line-height:1; }
.role-l { font-size:0.6rem; font-weight:700; color:rgba(148,163,184,0.65) !important; text-transform:uppercase; letter-spacing:0.5px; margin-top:5px; }

/* ─ Separator ─────────────────────────────────── */
.sep { display:flex; align-items:center; gap:10px; margin:1rem 0; }
.sep hr { flex:1; border:none; height:1px; background:linear-gradient(90deg,transparent,rgba(99,102,241,0.35),transparent); }
.sep span { color:rgba(148,163,184,0.35) !important; font-size:0.72rem; }

/* ─ Input fields ──────────────────────────────── */
.stTextInput label {
    color:rgba(148,163,184,0.8) !important;
    font-size:0.78rem !important; font-weight:600 !important; letter-spacing:0.4px !important;
    text-transform:uppercase !important;
}
.stTextInput input {
    background:rgba(255,255,255,0.03) !important;
    border:1.5px solid rgba(99,102,241,0.2) !important;
    border-radius:12px !important; color:#c8d8f0 !important;
    padding:0.68rem 1rem !important; font-size:0.93rem !important;
    transition:all 0.25s !important;
}
.stTextInput input:focus {
    background:rgba(99,102,241,0.07) !important;
    border-color:rgba(99,102,241,0.65) !important;
    box-shadow:0 0 0 4px rgba(99,102,241,0.1) !important;
    color:#e2e8f0 !important;
}
.stTextInput input::placeholder { color:rgba(148,163,184,0.3) !important; }

/* ─ Buttons ───────────────────────────────────── */
.stButton > button {
    background:linear-gradient(135deg,#4338ca,#7c3aed,#9333ea) !important;
    color:#fff !important; border:none !important;
    border-radius:14px !important;
    padding:0.78rem 1.5rem !important; font-weight:700 !important;
    font-size:0.95rem !important; letter-spacing:0.4px !important;
    width:100% !important;
    box-shadow:0 10px 28px rgba(67,56,202,0.5), 0 4px 8px rgba(0,0,0,0.3) !important;
    transition:all 0.3s !important; position:relative !important; overflow:hidden !important;
}
.stButton > button::after {
    content:''; position:absolute; inset:0;
    background:linear-gradient(135deg,rgba(255,255,255,0.1),transparent);
    opacity:0; transition:opacity 0.3s;
}
.stButton > button:hover {
    transform:translateY(-3px) !important;
    box-shadow:0 16px 40px rgba(67,56,202,0.65), 0 6px 12px rgba(0,0,0,0.4) !important;
}
.stButton > button:hover::after { opacity:1; }
.stButton > button:active { transform:translateY(-1px) !important; }

/* ─ Message boxes ─────────────────────────────── */
.lmsg {
    border-radius:12px; padding:0.75rem 1rem;
    font-size:0.86rem; font-weight:600; margin:0.7rem 0;
    display:flex; align-items:center; gap:8px;
}
.lmsg-ok  { background:rgba(6,78,59,0.6);  border:1px solid rgba(16,185,129,0.5); color:#6ee7b7 !important; }
.lmsg-err { background:rgba(127,29,29,0.6); border:1px solid rgba(239,68,68,0.5);  color:#fca5a5 !important;
             animation:shakeMsg 0.35s ease; }
@keyframes shakeMsg {
    0%,100% { transform:translateX(0); }
    25%      { transform:translateX(-7px); }
    75%      { transform:translateX(7px);  }
}

/* ─ Helper text ───────────────────────────────── */
.lhint {
    text-align:center; font-size:0.71rem; color:rgba(148,163,184,0.3) !important;
    margin-top:1.2rem; line-height:1.8;
}
.lhint strong { color:rgba(180,195,215,0.55) !important; }

/* ─ Tabs ──────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background:rgba(255,255,255,0.03); border-radius:12px;
    padding:3px; gap:3px; border:1px solid rgba(255,255,255,0.05);
}
.stTabs [data-baseweb="tab"] {
    color:rgba(148,163,184,0.65) !important;
    font-weight:600; border-radius:9px; font-size:0.86rem;
}
.stTabs [aria-selected="true"] {
    background:linear-gradient(135deg,#4338ca,#7c3aed) !important;
    color:#fff !important; box-shadow:0 4px 14px rgba(67,56,202,0.5) !important;
}

/* ─ Security badge ────────────────────────────── */
.sec-badge {
    display:flex; align-items:center; justify-content:center;
    gap:6px; margin-top:1.4rem; padding:0.5rem;
    border-top:1px solid rgba(255,255,255,0.04);
    color:rgba(148,163,184,0.3) !important; font-size:0.7rem;
}
</style>
"""

# ─────────────────────────────────────────────────────────────────
# MAIN APP CSS
# ─────────────────────────────────────────────────────────────────
def main_css(DK):
    BG   = "linear-gradient(135deg,#0f0c29,#302b63,#24243e)" if DK else "linear-gradient(135deg,#f0f4ff,#e8ecff)"
    SIDE = "#0f172a"   if DK else "#f1f5f9"
    CARD = "#1e293b"   if DK else "#ffffff"
    TXT  = "#e2e8f0"   if DK else "#1e293b"
    MUT  = "#94a3b8"   if DK else "#64748b"
    BDR  = "rgba(255,255,255,0.08)" if DK else "rgba(0,0,0,0.08)"
    CHT  = "#0a0f1e"   if DK else "#f8fafc"
    return BG,SIDE,CARD,TXT,MUT,BDR,CHT, f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500;600&display=swap');

/* ── Base font — only apply to non-Streamlit-internal elements ── */
body, .stMarkdown, .stText, p, span, div, label, button,
.stSelectbox, .stMultiSelect, .stSlider, .stNumberInput,
[data-testid="stSidebar"] {{ font-family:'DM Sans',sans-serif !important; }}
h1,h2,h3 {{ font-family:'Syne',sans-serif !important; }}

/* ── HIDE STREAMLIT HEADER COMPLETELY (removes keyb text + double icons) ── */
header[data-testid="stHeader"] {{
  background: transparent !important;
  border-bottom: none !important;
  height: 0 !important;
  min-height: 0 !important;
  padding: 0 !important;
  overflow: visible !important;
}}
/* Hide all header children EXCEPT the sidebar toggle */
header[data-testid="stHeader"] > div {{
  display: none !important;
}}
[data-testid="stDecoration"] {{ display: none !important; }}
/* Push content up since header is gone */
.block-container {{ padding-top: 0.5rem !important; }}

/* ── Prevent ALL overflow / collision ── */
* {{ box-sizing:border-box !important; }}
p, span, div, label {{
  overflow-wrap: break-word !important;
  word-break: break-word !important;
  min-width: 0 !important;
}}

/* ── Streamlit label fix — no more overlapping labels ── */
.stTextInput label,
.stTextArea label,
.stSelectbox label,
.stMultiSelect label,
.stSlider label,
.stNumberInput label,
.stFileUploader label {{
  font-family:'DM Sans',sans-serif !important;
  font-size:0.82rem !important;
  font-weight:600 !important;
  color:{MUT} !important;
  margin-bottom:4px !important;
  display:block !important;
  line-height:1.4 !important;
  white-space:normal !important;
  overflow:visible !important;
}}

/* ── Input fields ── */
.stTextInput input,
.stTextArea textarea,
.stNumberInput input {{
  font-family:'DM Sans',sans-serif !important;
  font-size:0.9rem !important;
  color:{TXT} !important;
  line-height:1.5 !important;
}}

/* ── Sidebar — clean with no overflow ── */
.stApp {{ background:{BG} !important; }}
section[data-testid="stSidebar"] {{
  background:{SIDE} !important;
  border-right:1px solid {BDR};
  overflow-x: hidden !important;
}}
section[data-testid="stSidebar"] * {{
  color:{TXT} !important;
  max-width:100% !important;
  overflow-wrap:break-word !important;
  word-break:break-word !important;
}}
section[data-testid="stSidebar"] input {{
  color:#1e293b !important;
  background:white !important;
  border-radius:8px !important;
}}
section[data-testid="stSidebar"] .stButton>button {{
  width:100% !important;
  white-space:nowrap !important;
  overflow:hidden !important;
  text-overflow:ellipsis !important;
}}

/* ── Mobile: sidebar as overlay, not content pusher ── */
@media (max-width: 768px) {{
  section[data-testid="stSidebar"] {{
    position: fixed !important;
    top: 0 !important; left: 0 !important;
    height: 100vh !important;
    z-index: 999 !important;
    width: 80vw !important;
    max-width: 300px !important;
    box-shadow: 4px 0 24px rgba(0,0,0,0.6) !important;
  }}
}}

/* ── App cards / components ── */
.hero {{ background:linear-gradient(135deg,#0d1b2a,#1a2744,#0f3460); border-radius:28px; padding:clamp(1.2rem, 4vw, 2.8rem) clamp(0.8rem, 3vw, 2rem) clamp(1rem, 3vw, 2.2rem); margin-bottom:2rem; text-align:center; border:1px solid rgba(99,102,241,0.2); box-shadow:0 32px 80px rgba(0,0,0,0.5); }}
.app-name {{ font-family:'Syne',sans-serif !important; font-size:clamp(1.6rem, 6vw, 3.2rem); font-weight:800; letter-spacing:-2px; background:linear-gradient(90deg,#00f5a0,#00d9f5,#a78bfa,#f472b6); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:0.3rem; }}
.app-sub {{ color:rgba(255,255,255,0.6) !important; font-size:0.95rem; margin-bottom:1.4rem; }}
.pill {{ display:inline-block; margin:3px 4px; padding:4px 12px; border-radius:20px; font-size:0.73rem; font-weight:600; background:rgba(255,255,255,0.08); color:rgba(255,255,255,0.85) !important; border:1px solid rgba(255,255,255,0.14); white-space:nowrap; }}
.step {{ background:{'linear-gradient(135deg,#1e293b,#0f172a)' if DK else 'linear-gradient(135deg,#f8fafc,#eef2ff)'}; border-radius:18px; padding:1.2rem 0.7rem; text-align:center; border:1px solid {BDR}; transition:transform .25s,box-shadow .25s; overflow:hidden; }}
.step:hover {{ transform:translateY(-5px); box-shadow:0 14px 36px rgba(99,102,241,0.3); }}
.step-ico {{ font-size:2rem; display:block; }}
.step-n {{ font-size:0.6rem; font-weight:800; color:#00f5a0 !important; letter-spacing:2px; margin-top:4px; display:block; }}
.step-l {{ font-size:0.75rem; font-weight:600; color:{MUT} !important; margin-top:2px; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

/* ── Result / alert cards ── */
.rc {{ border-radius:16px; padding:0.85rem 1.1rem; margin-bottom:0.6rem; font-size:0.88rem; font-weight:600; line-height:1.5; word-break:break-word; overflow:hidden; }}
.rc * {{ color:inherit !important; line-height:1.5; }}
.rc-ok   {{ background:linear-gradient(135deg,#052e16,#064e3b); border:2px solid #10b981; color:#bbf7d0 !important; }}
.rc-bad  {{ background:linear-gradient(135deg,#3b0a0a,#7f1d1d); border:2px solid #ef4444; color:#fecaca !important; }}
.rc-warn {{ background:linear-gradient(135deg,#3b1f00,#78350f); border:2px solid #f59e0b; color:#fde68a !important; }}
.rc-info {{ background:linear-gradient(135deg,#0c1e3b,#1e3a5f); border:2px solid #60a5fa; color:#bfdbfe !important; }}

/* ── Medicine cards ── */
.mc {{ background:{CARD}; border-radius:14px; padding:0.9rem 1rem; margin-bottom:0.6rem; overflow:hidden; }}
.mc h4 {{ font-size:0.72rem; font-weight:800; text-transform:uppercase; letter-spacing:0.5px; color:{MUT} !important; margin-bottom:4px; display:block; }}
.mc p  {{ font-size:0.85rem; color:{TXT} !important; margin:0; line-height:1.55; word-break:break-word; }}
.mc-r {{ border-left:4px solid #ef4444; }} .mc-a {{ border-left:4px solid #f59e0b; }}
.mc-g {{ border-left:4px solid #10b981; }} .mc-b {{ border-left:4px solid #6366f1; }}
.mc-p {{ border-left:4px solid #a78bfa; }}

/* ── Vision chips ── */
.vc {{ background:{CARD}; border-radius:14px; padding:0.9rem 0.5rem; text-align:center; border:1px solid {BDR}; overflow:hidden; }}
.vc-ico {{ font-size:1.5rem; display:block; }}
.vc-lbl {{ font-size:0.65rem; font-weight:800; color:{MUT} !important; text-transform:uppercase; letter-spacing:0.5px; margin-top:3px; display:block; }}
.vc-val {{ font-size:0.95rem; font-weight:800; margin-top:2px; display:block; }}

/* ── Metric boxes ── */
.mb {{ background:{'linear-gradient(135deg,#1e293b,#0f172a)' if DK else 'white'}; border-radius:18px; padding:1.2rem 0.8rem; text-align:center; border:1px solid {BDR}; overflow:hidden; }}
.mb-n {{ font-size:2rem; font-weight:800; font-family:'Syne',sans-serif !important; line-height:1; display:block; }}
.mb-l {{ font-size:0.7rem; font-weight:600; color:{MUT} !important; margin-top:4px; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{ background:rgba(255,255,255,{'0.05' if DK else '0.5'}); border-radius:14px; padding:4px; gap:3px; border:1px solid {BDR}; flex-wrap:wrap !important; }}
.stTabs [data-baseweb="tab"] {{ color:{MUT} !important; font-weight:600; border-radius:10px; font-size:0.82rem; white-space:nowrap; }}
.stTabs [aria-selected="true"] {{ background:linear-gradient(135deg,#6366f1,#8b5cf6) !important; color:#fff !important; box-shadow:0 4px 14px rgba(99,102,241,0.45) !important; }}

/* ── Buttons ── */
.stButton>button {{
  background:linear-gradient(135deg,#6366f1,#8b5cf6) !important;
  color:white !important; border:none !important;
  border-radius:25px !important; padding:0.5rem 1.4rem !important;
  font-weight:600 !important; font-size:0.85rem !important;
  font-family:'DM Sans',sans-serif !important;
  box-shadow:0 4px 15px rgba(99,102,241,0.35) !important;
  transition:all .3s !important; white-space:nowrap !important;
  overflow:hidden !important; text-overflow:ellipsis !important;
}}
.stButton>button:hover {{ transform:translateY(-2px) !important; box-shadow:0 8px 24px rgba(99,102,241,0.55) !important; }}

/* ── Hide Streamlit keyboard shortcut icon (causes collision) ── */
[data-testid="stExpander"] summary svg {{ display:none !important; }}
[data-testid="stExpander"] summary div[data-testid="stMarkdownContainer"] {{
  overflow:visible !important;
}}
/* Fix expander title text collision */
details > summary {{
  list-style:none !important;
  cursor:pointer !important;
  padding:10px 14px !important;
  font-size:0.88rem !important;
  font-weight:700 !important;
  color:{TXT} !important;
  display:flex !important;
  align-items:center !important;
  gap:8px !important;
  overflow:hidden !important;
  white-space:nowrap !important;
  text-overflow:ellipsis !important;
}}
details > summary::-webkit-details-marker {{ display:none; }}
details[open] > summary {{ border-bottom:1px solid {BDR}; }}
/* Remove keyboard shortcut tooltip entirely */
button[data-testid="baseButton-secondary"] {{ position:relative; }}
span[data-baseweb="tooltip"] {{ display:none !important; }}
[class*="keyboard"] {{ display:none !important; }}
div[data-testid="stExpander"] > details > summary > span {{ display:none !important; }}
/* Force expander summary to single line */
[data-testid="stExpander"] summary p {{
  margin:0 !important;
  overflow:hidden !important;
  text-overflow:ellipsis !important;
  white-space:nowrap !important;
  font-size:0.87rem !important;
  font-weight:700 !important;
  line-height:1.4 !important;
}}

/* ── File uploader ── */
[data-testid="stFileUploader"] {{ background:rgba(99,102,241,0.05) !important; border:2px dashed rgba(99,102,241,0.4) !important; border-radius:18px !important; padding:8px !important; }}
[data-testid="stFileUploader"] * {{ font-size:0.82rem !important; white-space:normal !important; word-break:break-word !important; }}

/* ── Expanders ── */
details {{ background:rgba(255,255,255,{'0.04' if DK else '0.6'}) !important; border-radius:14px !important; border:1px solid {BDR} !important; margin-bottom:0.5rem !important; overflow:hidden !important; }}
summary {{ color:{TXT} !important; font-weight:600; padding:0.5rem 0.8rem; font-size:0.88rem !important; white-space:normal !important; word-break:break-word !important; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width:5px; }} ::-webkit-scrollbar-thumb {{ background:linear-gradient(#6366f1,#a78bfa); border-radius:10px; }}

/* ── Section headers ── */
.sh {{ color:{MUT} !important; font-size:0.65rem; font-weight:800; letter-spacing:2px; text-transform:uppercase; margin:10px 0 5px; display:block; }}

/* ── Pulse alert ── */
.pulse {{ animation:pulse 2s infinite; background:linear-gradient(135deg,#3b0a0a,#7f1d1d) !important; border:2px solid #ef4444 !important; border-radius:16px; padding:0.9rem 1.1rem; margin-bottom:0.7rem; color:#fecaca !important; word-break:break-word; }}
.pulse * {{ color:#fecaca !important; }}
@keyframes pulse {{ 0%,100% {{ box-shadow:0 4px 24px rgba(239,68,68,0.3); }} 50% {{ box-shadow:0 4px 40px rgba(239,68,68,0.7); }} }}
.clbl {{ text-align:center; font-size:0.75rem; font-weight:700; color:{MUT} !important; padding:5px; background:rgba(255,255,255,0.04); border-radius:8px; margin-bottom:4px; }}
.sp-bad {{ display:inline-block; background:rgba(239,68,68,0.18); color:#fca5a5 !important; padding:2px 8px; border-radius:6px; font-weight:700; margin:2px; border:1px solid rgba(239,68,68,0.3); font-size:0.8rem; }}
.sp-fix {{ color:#86efac !important; font-weight:600; font-size:0.8rem; }}
.footer {{ text-align:center; padding:2.2rem; margin-top:2rem; background:{'linear-gradient(135deg,#0d1b2a,#1b2a4a)' if DK else 'linear-gradient(135deg,#eef2ff,#f5f0ff)'}; border-radius:24px; border:1px solid {BDR}; }}

/* ── Top navbar action buttons (☰ 👤 🌙) ── */
.topbar-btns-row div[data-testid="stHorizontalBlock"] {{ gap:6px!important; margin-bottom:8px!important; }}
/* Make the 3 icon buttons small and pill-shaped */
div[data-testid="stHorizontalBlock"]:first-of-type .stButton>button {{
  background:rgba(99,102,241,0.12) !important;
  border:1px solid rgba(99,102,241,0.3) !important;
  border-radius:10px !important;
  font-size:1rem !important;
  padding:0.25rem 0.5rem !important;
  box-shadow:none !important;
  color:#a78bfa !important;
  min-height:36px !important;
  width:auto !important;
}}
div[data-testid="stHorizontalBlock"]:first-of-type .stButton>button:hover {{
  background:rgba(99,102,241,0.25) !important;
  transform:none !important;
  box-shadow:none !important;
}}
@media (max-width: 768px) {{
  .block-container {{ padding: 0.4rem 0.5rem 1rem !important; max-width: 100% !important; }}

  /* Hero compact */
  .hero {{ padding: 1rem 0.9rem !important; border-radius: 14px !important; margin-bottom: 0.8rem !important; }}
  .app-name {{ font-size: 1.45rem !important; letter-spacing: -0.5px !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; }}
  .app-sub {{ font-size: 0.73rem !important; margin-bottom: 0.6rem !important; }}
  .hero-pills {{ display: flex !important; flex-wrap: wrap !important; gap: 3px !important; justify-content: center !important; }}
  .pill {{ font-size: 0.62rem !important; padding: 2px 7px !important; margin: 1px !important; }}

  /* Step cards — smaller and tighter */
  .step {{ padding: 0.5rem 0.2rem !important; border-radius: 10px !important; }}
  .step-ico {{ font-size: 1rem !important; }}
  .step-n {{ font-size: 0.48rem !important; letter-spacing: 0.3px !important; }}
  .step-l {{ font-size: 0.58rem !important; }}

  /* Tabs — SCROLL horizontally, never wrap */
  .stTabs [data-baseweb="tab-list"] {{
    flex-wrap: nowrap !important;
    overflow-x: auto !important;
    overflow-y: hidden !important;
    -webkit-overflow-scrolling: touch !important;
    scrollbar-width: none !important;
    padding: 3px 4px !important;
    gap: 2px !important;
  }}
  .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {{ display: none !important; }}
  .stTabs [data-baseweb="tab"] {{
    font-size: 0.68rem !important;
    padding: 5px 7px !important;
    white-space: nowrap !important;
    flex-shrink: 0 !important;
  }}

  /* Cards */
  .rc {{ padding: 0.65rem 0.75rem !important; font-size: 0.79rem !important; border-radius: 10px !important; }}
  .mc {{ padding: 0.65rem 0.75rem !important; border-radius: 10px !important; }}
  .mc p {{ font-size: 0.78rem !important; }}
  .vc {{ padding: 0.55rem 0.25rem !important; border-radius: 9px !important; }}
  .vc-ico {{ font-size: 1rem !important; }}
  .vc-lbl {{ font-size: 0.53rem !important; }}
  .vc-val {{ font-size: 0.76rem !important; }}
  .mb {{ padding: 0.8rem 0.45rem !important; border-radius: 11px !important; }}
  .mb-n {{ font-size: 1.4rem !important; }}
  .mb-l {{ font-size: 0.58rem !important; }}

  /* Prevent column overflow */
  [data-testid="column"] {{ min-width: 0 !important; overflow: hidden !important; }}
  .js-plotly-plot, .plotly {{ max-width: 100% !important; }}
  iframe {{ max-width: 100% !important; border-radius: 10px !important; }}
  [data-testid="stDataFrame"] {{ overflow-x: auto !important; max-width: 100% !important; }}
  [data-testid="stFileUploader"] {{ padding: 5px !important; }}
  [data-testid="stFileUploader"] * {{ font-size: 0.73rem !important; }}
  .stButton>button {{ font-size: 0.78rem !important; padding: 0.4rem 0.9rem !important; }}
  section[data-testid="stSidebar"] {{ min-width: 0 !important; }}
  .footer {{ padding: 1rem 0.7rem !important; border-radius: 12px !important; }}
  .pulse {{ padding: 0.65rem 0.75rem !important; font-size: 0.79rem !important; }}
}}

@media (max-width: 420px) {{
  .app-name {{ font-size: 1.2rem !important; }}
  .stTabs [data-baseweb="tab"] {{ font-size: 0.62rem !important; padding: 4px 6px !important; }}
  .step-ico {{ font-size: 0.9rem !important; }}
  .step-l {{ font-size: 0.52rem !important; }}
}}
</style>"""

# ═══════════════════════════════════════════════════════════════════
#
#   LOGIN PAGE
#
# ═══════════════════════════════════════════════════════════════════
def show_login():
    for k,v in [("fp_step",0),("fp_email",""),("fp_otp",""),("fp_username",""),
                ("login_role_sel",""),("reg_role_sel","user")]:
        if k not in st.session_state: st.session_state[k] = v

    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500;600&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body,.stApp{height:100%;overflow:hidden}
.stApp{background:#060918!important;font-family:'DM Sans',sans-serif!important}
section[data-testid="stSidebar"],[data-testid="stDecoration"],#MainMenu,footer,
header[data-testid="stHeader"]{display:none!important}
/* kill all streamlit padding */
.block-container{padding:0!important;max-width:100%!important;margin:0!important}
.element-container{margin-bottom:0!important}
/* animated bg */
.ps-bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.ps-blob{position:absolute;border-radius:50%;filter:blur(90px);opacity:.35;animation:drift ease-in-out infinite alternate}
.ps-blob.a{width:520px;height:520px;background:#6366f1;top:-180px;left:-120px;animation-duration:9s}
.ps-blob.b{width:420px;height:420px;background:#00f5a0;bottom:-130px;right:-100px;animation-duration:12s;animation-delay:3s}
.ps-blob.c{width:300px;height:300px;background:#f472b6;top:40%;left:60%;animation-duration:10s;animation-delay:5s}
@keyframes drift{0%{transform:translate(0,0) scale(1)}100%{transform:translate(40px,35px) scale(1.12)}}
.ps-beam{position:fixed;left:0;top:0;width:100%;height:2px;
  background:linear-gradient(90deg,transparent,rgba(0,245,160,.9),transparent);
  animation:beam 5s ease-in-out infinite;z-index:1}
@keyframes beam{0%{top:-2px;opacity:0}10%{opacity:1}90%{opacity:.5}100%{top:100vh;opacity:0}}
/* ── page wrapper: true full-screen no-scroll ── */
.ps-wrap{position:fixed;inset:0;z-index:10;display:flex;align-items:center;justify-content:center;padding:16px}
/* ── card ── */
.ps-card{
  background:rgba(10,15,35,.92);
  backdrop-filter:blur(28px);-webkit-backdrop-filter:blur(28px);
  border:1px solid rgba(99,102,241,.3);border-radius:24px;
  padding:24px 24px 20px;
  width:100%;max-width:420px;
  box-shadow:0 40px 100px rgba(0,0,0,.8);
  position:relative;z-index:11}
/* ── logo ── */
.ps-logo{display:flex;align-items:center;gap:12px;margin-bottom:20px}
.ps-shield{width:46px;height:46px;border-radius:50%;flex-shrink:0;
  background:linear-gradient(135deg,#6366f1,#a78bfa);
  display:flex;align-items:center;justify-content:center;font-size:1.35rem;
  box-shadow:0 0 24px rgba(99,102,241,.5)}
.ps-brand{font-family:'Syne',sans-serif!important;font-size:1.4rem;font-weight:800;
  background:linear-gradient(90deg,#00f5a0,#00d9f5,#a78bfa);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.ps-sub{font-size:.72rem;color:#64748b;margin-top:2px;font-family:'DM Sans',sans-serif!important}
/* ── role chips ── */
.role-chips{display:flex;gap:8px;margin:8px 0}
.rc-chip{flex:1;padding:8px 10px;border-radius:12px;border:1px solid rgba(255,255,255,.1);
  background:rgba(255,255,255,.04);cursor:pointer;text-align:center;
  font-size:.8rem;font-weight:600;color:#94a3b8;transition:.2s;font-family:'DM Sans',sans-serif!important}
.rc-chip.sel-user{background:rgba(99,102,241,.2);border-color:#6366f1;color:#a5b4fc}
.rc-chip.sel-exp{background:rgba(16,185,129,.2);border-color:#10b981;color:#6ee7b7}
/* ── inputs ── */
.stTextInput label{color:#94a3b8!important;font-size:.78rem!important;
  font-weight:600!important;margin-bottom:3px!important;display:block}
.stTextInput input{
  background:rgba(255,255,255,.06)!important;
  border:1px solid rgba(255,255,255,.12)!important;
  border-radius:12px!important;color:#e2e8f0!important;
  font-size:.9rem!important;padding:10px 14px!important;
  font-family:'DM Sans',sans-serif!important}
.stTextInput input:focus{border-color:#6366f1!important;box-shadow:0 0 0 3px rgba(99,102,241,.25)!important}
/* ── buttons ── */
.stButton>button{
  background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;color:#fff!important;
  border:none!important;border-radius:50px!important;
  padding:.55rem 1.4rem!important;font-weight:700!important;
  font-size:.88rem!important;font-family:'DM Sans',sans-serif!important;
  box-shadow:0 4px 18px rgba(99,102,241,.4)!important;transition:.25s!important;width:100%!important}
.stButton>button:hover{transform:translateY(-2px)!important;box-shadow:0 8px 28px rgba(99,102,241,.6)!important}
/* ── tabs ── */
.stTabs [data-baseweb="tab-list"]{background:rgba(255,255,255,.05)!important;
  border-radius:12px!important;padding:3px!important;gap:2px!important;
  border:1px solid rgba(255,255,255,.08)!important;margin-bottom:8px!important}
.stTabs [data-baseweb="tab"]{color:#64748b!important;font-weight:600!important;
  border-radius:9px!important;font-size:.82rem!important;padding:6px 14px!important;
  font-family:'DM Sans',sans-serif!important}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;
  color:#fff!important;box-shadow:0 4px 14px rgba(99,102,241,.45)!important}
/* ── alert msgs ── */
.ps-err{background:rgba(239,68,68,.15);border:1px solid #ef4444;border-radius:10px;
  padding:8px 12px;font-size:.8rem;color:#fca5a5;margin-bottom:8px;
  font-family:'DM Sans',sans-serif!important}
.ps-ok{background:rgba(16,185,129,.15);border:1px solid #10b981;border-radius:10px;
  padding:8px 12px;font-size:.8rem;color:#6ee7b7;margin-bottom:8px;
  font-family:'DM Sans',sans-serif!important}
.ps-info{background:rgba(99,102,241,.12);border:1px solid #6366f1;border-radius:10px;
  padding:8px 12px;font-size:.8rem;color:#a5b4fc;margin-bottom:8px;
  font-family:'DM Sans',sans-serif!important}
/* ── id upload ── */
[data-testid="stFileUploader"]{background:rgba(99,102,241,.06)!important;
  border:1.5px dashed rgba(99,102,241,.4)!important;border-radius:12px!important;
  padding:8px!important}
[data-testid="stFileUploader"] *{font-size:.8rem!important;color:#94a3b8!important}
/* ── forgot link ── */
.fp-btn button{background:none!important;border:none!important;
  color:#6366f1!important;font-size:.77rem!important;font-weight:600!important;
  text-decoration:underline!important;padding:0!important;
  box-shadow:none!important;width:auto!important;margin:0!important}
.fp-btn button:hover{transform:none!important;box-shadow:none!important}
/* ── security note ── */
.ps-sec{text-align:center;font-size:.68rem;color:#334155;margin-top:6px;
  font-family:'DM Sans',sans-serif!important}
/* ── fp panel ── */
.ps-fp{background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.4);
  border-radius:16px;padding:16px;margin-bottom:8px}
/* MOBILE */
@media(max-width:768px){
  /* Collapse outer spacer cols to zero */
  .login-outer-col{flex:0 0 2px!important;min-width:2px!important;max-width:2px!important;overflow:hidden!important;padding:0!important;visibility:hidden!important}
  .login-center-col{flex:1 1 auto!important;min-width:0!important;max-width:100%!important;padding:0 8px!important}
  /* Card itself */
  .ps-card{padding:20px 16px 16px!important;border-radius:20px!important}
  .ps-brand{font-size:1.2rem!important}
  .ps-shield{width:40px!important;height:40px!important;font-size:1.1rem!important}
  /* Make login/register buttons normal width not full-width */
  .stButton>button{width:auto!important;min-width:120px!important}
  .stTabs [data-baseweb="tab"]{font-size:.78rem!important;padding:6px 12px!important}
  /* Hide Streamlit's deploy/github buttons in header */
  header[data-testid="stHeader"] a,
  header[data-testid="stHeader"] [data-testid="stDecoration"]{ display:none!important }
}
@media(max-width:480px){
  .ps-card{padding:16px 12px 14px!important;border-radius:16px!important}
  .ps-brand{font-size:1.05rem!important}
  .ps-shield{width:36px!important;height:36px!important;font-size:1rem!important}
  .stTabs [data-baseweb="tab"]{font-size:.72rem!important;padding:5px 9px!important}
}
</style>
<div class="ps-bg">
  <div class="ps-blob a"></div>
  <div class="ps-blob b"></div>
  <div class="ps-blob c"></div>
</div>
<div class="ps-beam"></div>
<script>
(function labelLoginCols(){
  function run(){
    var blocks = document.querySelectorAll('[data-testid="stHorizontalBlock"]');
    blocks.forEach(function(block){
      var cols = block.querySelectorAll(':scope > [data-testid="column"]');
      if(cols.length === 3){
        cols[0].classList.add('login-outer-col');
        cols[1].classList.add('login-center-col');
        cols[2].classList.add('login-outer-col');
      }
    });
  }
  run();
  setTimeout(run, 300);
  setTimeout(run, 800);
  setTimeout(run, 1500);
})();
</script>
""", unsafe_allow_html=True)

    # ── centred card: columns on desktop, CSS centering on mobile ──
    _, col, _ = st.columns([1, 2.4, 1])
    with col:
        # Brand header
        st.markdown("""
<div class="ps-logo">
  <div class="ps-shield">🛡️</div>
  <div>
    <div class="ps-brand">PharmaScan AI</div>
    <div class="ps-sub">Vision-Based Fake Medicine Detection</div>
  </div>
</div>""", unsafe_allow_html=True)

        fp_step = st.session_state.get("fp_step", 0)

        # ── FORGOT PASSWORD PANEL ─────────────────────────────────
        if fp_step > 0:
            st.markdown('<div class="ps-fp">', unsafe_allow_html=True)
            st.markdown('<p style="color:#a5b4fc;font-weight:700;font-size:.9rem;margin-bottom:10px">🔑 Reset Password</p>', unsafe_allow_html=True)
            if fp_step == 1:
                st.text_input("Registered Gmail", placeholder="yourname@gmail.com", key="fp_em_in")
                c1,c2 = st.columns(2)
                with c1:
                    if st.button("Send OTP", key="btn_fp1"):
                        em = st.session_state.get("fp_em_in","").strip()
                        if "@" not in em: st.error("Invalid email")
                        else:
                            conn=sqlite3.connect(DB_PATH); row=conn.execute("SELECT username FROM users WHERE email=?",(em,)).fetchone(); conn.close()
                            if row:
                                otp=generate_otp(); ok,_=send_otp_email(em,otp)
                                if ok:
                                    st.session_state.update({"fp_otp":otp,"fp_email":em,"fp_username":row[0],"fp_step":2}); st.rerun()
                                else: st.error("Could not send OTP")
                            else: st.error("No account found")
                with c2:
                    if st.button("Cancel", key="btn_fp1c"): st.session_state["fp_step"]=0; st.rerun()
            elif fp_step == 2:
                st.markdown(f'<div class="ps-ok">OTP sent to <b>{st.session_state["fp_email"]}</b></div>', unsafe_allow_html=True)
                st.text_input("6-digit OTP", max_chars=6, placeholder="483920", key="fp_otp_in")
                c1,c2=st.columns(2)
                with c1:
                    if st.button("Verify OTP", key="btn_fp2"):
                        if st.session_state.get("fp_otp_in","").strip()==st.session_state["fp_otp"]:
                            st.session_state["fp_step"]=3; st.rerun()
                        else: st.error("Wrong OTP")
                with c2:
                    if st.button("Cancel", key="btn_fp2c"): st.session_state["fp_step"]=0; st.rerun()
            elif fp_step == 3:
                st.text_input("New Password", type="password", placeholder="Min 6 chars", key="fp_np")
                st.text_input("Confirm", type="password", placeholder="Re-enter", key="fp_cp")
                c1,c2=st.columns(2)
                with c1:
                    if st.button("Save", key="btn_fp3"):
                        np=st.session_state.get("fp_np",""); cp=st.session_state.get("fp_cp","")
                        if len(np)<6: st.error("Min 6 chars")
                        elif np!=cp: st.error("Passwords don't match")
                        else:
                            ph=hashlib.sha256(np.encode()).hexdigest()
                            conn=sqlite3.connect(DB_PATH); conn.execute("UPDATE users SET password_hash=? WHERE username=?",(ph,st.session_state["fp_username"])); conn.commit(); conn.close()
                            st.session_state["fp_step"]=0; st.rerun()
                with c2:
                    if st.button("Cancel", key="btn_fp3c"): st.session_state["fp_step"]=0; st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            return

        # ── LOGIN / REGISTER TABS ─────────────────────────────────
        login_tab, reg_tab = st.tabs(["🔐 Login", "✨ Register"])

        # ════════ LOGIN ═══════════════════════════════════════════
        with login_tab:
            if st.session_state.get("login_error"):
                st.markdown(f'<div class="ps-err">❌ {st.session_state.login_error}</div>', unsafe_allow_html=True)

            # Role chips
            sel = st.session_state.get("login_role_sel","")
            uc  = "sel-user" if sel=="user"   else ""
            ec  = "sel-exp"  if sel=="expert" else ""
            st.markdown(f"""
<p style="color:#64748b;font-size:.76rem;font-weight:700;margin-bottom:4px;font-family:'DM Sans',sans-serif">I AM:</p>
<div class="role-chips">
  <div class="rc-chip {uc}">👤 Patient / User</div>
  <div class="rc-chip {ec}">👨‍⚕️ Doctor / Pharmacist</div>
</div>""", unsafe_allow_html=True)
            lrole1, lrole2 = st.columns(2)
            with lrole1:
                if st.button("👤 Patient", key="lr1", use_container_width=True):
                    st.session_state["login_role_sel"]="user"; st.rerun()
            with lrole2:
                if st.button("👨‍⚕️ Expert", key="lr2", use_container_width=True):
                    st.session_state["login_role_sel"]="expert"; st.rerun()

            st.text_input("Username", placeholder="admin / doctor / pharmacist", key="l_user")
            st.text_input("Password", type="password", placeholder="Your password", key="l_pass")
            st.text_input("Gmail (optional — for fake alerts)", placeholder="you@gmail.com", key="l_email")

            # Expert info note — no ID needed at login, ID was submitted at registration
            if sel == "expert":
                st.markdown(
                    '<div style="background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.3);'
                    'border-radius:10px;padding:7px 12px;font-size:.75rem;color:#6ee7b7;margin-bottom:4px">'
                    '👨‍⚕️ Expert login — your ID was verified during registration. Just enter your username and password.</div>',
                    unsafe_allow_html=True)

            if st.button("🚀 Login →", key="btn_login"):
                lu=st.session_state.get("l_user","").strip()
                lp=st.session_state.get("l_pass","")
                le=st.session_state.get("l_email","").strip()
                err=""
                if not lu or not lp: err="Please enter username and password."
                elif le and ("@" not in le or "." not in le): err="Invalid email — leave blank if unsure."
                if err: st.session_state.login_error=err; st.rerun()
                else:
                    ok,uname,uemail,urole=db_login(lu,lp)
                    if ok:
                        # Role comes from DB (set during registration) or login_role_sel
                        final_role = urole or "user"
                        if sel == "expert" and final_role != "expert":
                            final_role = "expert"
                        final_email = le if le else (uemail or f"{uname}@pharmascan.demo")
                        st.session_state.update({
                            "logged_in":True,"username":uname,
                            "user_email": final_email,
                            "user_role":final_role,"login_error":"","login_role_sel":""})
                        _save_session(uname, final_role, final_email)
                        st.rerun()
                    else:
                        st.session_state.login_error="Wrong username or password.  Demo: admin / pharmascan123"
                        st.rerun()

            # Forgot password — tiny link
            st.markdown('<div class="fp-btn">', unsafe_allow_html=True)
            if st.button("Forgot Password?", key="btn_fp_open"):
                st.session_state["fp_step"]=1; st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('<div class="ps-sec">🔒 Secured · 256-bit encrypted · HIPAA compliant</div>', unsafe_allow_html=True)

        # ════════ REGISTER ════════════════════════════════════════
        with reg_tab:
            if st.session_state.get("reg_error"):
                cls="ps-ok" if st.session_state.get("reg_ok") else "ps-err"
                ico="✅" if st.session_state.get("reg_ok") else "❌"
                st.markdown(f'<div class="{cls}">{ico} {st.session_state.reg_error}</div>', unsafe_allow_html=True)

            if not st.session_state.get("otp_sent"):
                rrs=st.session_state.get("reg_role_sel","user")
                ruc="sel-user" if rrs=="user" else ""; rec="sel-exp" if rrs=="expert" else ""
                st.markdown(f"""
<p style="color:#64748b;font-size:.76rem;font-weight:700;margin-bottom:4px;font-family:'DM Sans',sans-serif">REGISTER AS:</p>
<div class="role-chips">
  <div class="rc-chip {ruc}">👤 Patient</div>
  <div class="rc-chip {rec}">👨‍⚕️ Expert</div>
</div>""", unsafe_allow_html=True)
                rr1,rr2=st.columns(2)
                with rr1:
                    if st.button("👤 Patient", key="rr1", use_container_width=True):
                        st.session_state["reg_role_sel"]="user"; st.rerun()
                with rr2:
                    if st.button("👨‍⚕️ Expert", key="rr2", use_container_width=True):
                        st.session_state["reg_role_sel"]="expert"; st.rerun()

                st.text_input("Username", placeholder="e.g. dr_priya or nithya_s", key="r_user")
                st.text_input("Gmail — OTP sent here", placeholder="you@gmail.com", key="r_email")
                st.text_input("Password", type="password", placeholder="Min 6 characters", key="r_pass")
                st.text_input("Confirm Password", type="password", placeholder="Re-enter", key="r_pass2")

                # ── Expert ID Proof (only for expert role) ───────────
                reg_id_ok = True
                if rrs == "expert":
                    st.markdown("""
<div style="background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.3);
border-radius:14px;padding:12px 14px;margin:8px 0">
<p style="color:#6ee7b7;font-size:.78rem;font-weight:800;margin-bottom:6px;letter-spacing:.5px">
🪪 PROFESSIONAL IDENTITY PROOF</p>
<p style="color:#64748b;font-size:.71rem;margin-bottom:0;line-height:1.5">
Required to register as Doctor / Pharmacist. Stored securely and never shared.</p>
</div>""", unsafe_allow_html=True)

                    reg_id_types = [
                        "Select ID type...",
                        "🏥 Medical Council Registration Card",
                        "💊 Pharmacy Council Registration",
                        "🎓 Medical Degree Certificate (MBBS/MD/MS)",
                        "🔬 Pharmacy Degree Certificate (B.Pharm/M.Pharm)",
                        "🏛️ Hospital / Clinic Appointment Letter",
                        "🪪 Government Medical ID Card",
                        "📋 Drug Inspector / Regulatory Authority ID",
                        "🔖 Other Professional Proof",
                    ]
                    st.selectbox("ID / Proof Type", reg_id_types, key="r_id_type")
                    st.text_input(
                        "Registration / License Number",
                        placeholder="e.g. TN-MED-2019-12345",
                        key="r_id_number")
                    st.markdown('<p style="color:#94a3b8;font-size:.74rem;font-weight:700;margin-bottom:3px">Upload scanned copy (JPG, PNG or PDF):</p>', unsafe_allow_html=True)
                    r_id_file = st.file_uploader(
                        "Upload ID Proof", type=["jpg","jpeg","png","pdf"],
                        key="r_id_file", label_visibility="collapsed")

                    r_id_type_val = st.session_state.get("r_id_type","")
                    r_id_num_val  = st.session_state.get("r_id_number","").strip()
                    if r_id_type_val == "Select ID type..." or not r_id_type_val:
                        st.markdown('<p style="color:#f59e0b;font-size:.72rem;margin-top:2px">⚠️ Select your ID type</p>', unsafe_allow_html=True)
                        reg_id_ok = False
                    elif not r_id_num_val:
                        st.markdown('<p style="color:#f59e0b;font-size:.72rem;margin-top:2px">⚠️ Enter your registration number</p>', unsafe_allow_html=True)
                        reg_id_ok = False
                    elif r_id_file is None:
                        st.markdown('<p style="color:#f59e0b;font-size:.72rem;margin-top:2px">⚠️ Upload a scanned copy of your ID</p>', unsafe_allow_html=True)
                        reg_id_ok = False
                    else:
                        st.markdown(
                            f'<div style="background:rgba(16,185,129,.12);border:1px solid #10b981;border-radius:10px;'
                            f'padding:7px 12px;margin-top:4px">'
                            f'<p style="color:#6ee7b7;font-size:.75rem;margin:0;font-weight:700">'
                            f'✅ {r_id_type_val.split(" ",1)[-1]} · #{r_id_num_val} · {r_id_file.name}</p>'
                            f'</div>',
                            unsafe_allow_html=True)

                if st.button("📧 Send OTP →", key="btn_send_otp", use_container_width=True):
                    ru=st.session_state.get("r_user","").strip()
                    re_=st.session_state.get("r_email","").strip()
                    rp=st.session_state.get("r_pass","")
                    rp2=st.session_state.get("r_pass2","")
                    err=""
                    if not ru or not re_ or not rp: err="Please fill all fields."
                    elif "@" not in re_ or "." not in re_: err="Enter a valid Gmail."
                    elif rp!=rp2: err="Passwords do not match."
                    elif len(rp)<6: err="Password must be at least 6 characters."
                    elif rrs=="expert" and not reg_id_ok: err="Please complete all ID verification fields."
                    if err: st.session_state.reg_error=err; st.session_state.reg_ok=False; st.rerun()
                    else:
                        otp=generate_otp(); ok_o,omsg=send_otp_email(re_,otp)
                        if ok_o:
                            # Save expert ID details for use after OTP verification
                            id_t = st.session_state.get("r_id_type","") if rrs=="expert" else ""
                            id_n = st.session_state.get("r_id_number","") if rrs=="expert" else ""
                            id_f = st.session_state.get("r_id_file") if rrs=="expert" else None
                            id_fname = id_f.name if id_f else ""
                            st.session_state.update({
                                "otp_code":otp,"otp_email":re_,
                                "otp_pending_user":ru,"otp_pending_pass":rp,
                                "otp_pending_id_type":id_t,
                                "otp_pending_id_number":id_n,
                                "otp_pending_id_file":id_fname,
                                "otp_sent":True,"otp_verified":False,
                                "reg_error":f"OTP sent to {re_}!","reg_ok":True})
                            st.rerun()
                        else:
                            st.session_state.update({"reg_error":f"OTP failed: {omsg}","reg_ok":False}); st.rerun()
            else:
                st.markdown(f'<div class="ps-ok">📧 OTP sent to <b>{st.session_state.otp_email}</b> — check inbox</div>', unsafe_allow_html=True)
                st.text_input("Enter 6-digit OTP", max_chars=6, placeholder="483920", key="entered_otp")
                oc1,oc2=st.columns(2)
                with oc1:
                    if st.button("✅ Verify & Join", key="btn_verify_otp", use_container_width=True):
                        if st.session_state.get("entered_otp","").strip()==st.session_state.otp_code:
                            rr=st.session_state.get("reg_role_sel","user")
                            ok2,msg=db_register(
                                st.session_state.otp_pending_user,
                                st.session_state.otp_email,
                                st.session_state.otp_pending_pass,
                                role=rr,
                                id_type=st.session_state.get("otp_pending_id_type",""),
                                id_number=st.session_state.get("otp_pending_id_number",""),
                                id_filename=st.session_state.get("otp_pending_id_file",""))
                            if ok2:
                                # Send welcome confirmation email
                                try:
                                    send_welcome_email(
                                        st.session_state.otp_email,
                                        st.session_state.otp_pending_user,
                                        rr,
                                        id_type=st.session_state.get("otp_pending_id_type",""),
                                        id_number=st.session_state.get("otp_pending_id_number",""))
                                except Exception:
                                    pass
                                st.session_state.update({
                                    "logged_in":True,"username":st.session_state.otp_pending_user,
                                    "user_email":st.session_state.otp_email,"user_role":rr,
                                    "otp_sent":False,"otp_code":"","otp_verified":True,"reg_error":""})
                                _save_session(st.session_state.otp_pending_user, rr, st.session_state.otp_email)
                                st.rerun()
                            else:
                                st.session_state.update({"reg_error":msg,"reg_ok":False}); st.rerun()
                        else:
                            st.session_state.update({"reg_error":"Wrong OTP.","reg_ok":False}); st.rerun()
                with oc2:
                    if st.button("🔄 Resend", key="btn_resend_otp", use_container_width=True):
                        otp2=generate_otp(); ok2,_=send_otp_email(st.session_state.otp_email,otp2)
                        if ok2: st.session_state.update({"otp_code":otp2,"reg_error":"New OTP sent!","reg_ok":True})
                        else: st.session_state.update({"reg_error":"Resend failed.","reg_ok":False})
                        st.rerun()
                if st.button("← Back", key="btn_back_reg"):
                    st.session_state.update({"otp_sent":False,"otp_code":"","reg_error":""}); st.rerun()
            st.markdown('<div class="ps-sec">🔒 Email verified · Data stored locally</div>', unsafe_allow_html=True)



# ═══════════════════════════════════════════════════════════════════
#   PROFILE PAGE — full screen, mobile-friendly
# ═══════════════════════════════════════════════════════════════════
def show_profile_page():
    DK = st.session_state.get("dark_mode", True)
    BG, SIDE, CARD, TXT, MUT, BDR, CHT, CSS = main_css(DK)
    st.markdown(CSS, unsafe_allow_html=True)

    # Extra profile page CSS
    st.markdown("""<style>
.prof-wrap{max-width:520px;margin:0 auto;padding:16px}
.prof-hero{background:linear-gradient(135deg,#0d1b2a,#1a2744,#0f3460);
  border-radius:24px;padding:28px 20px 20px;text-align:center;
  border:1px solid rgba(99,102,241,.25);margin-bottom:16px}
.prof-avatar{width:72px;height:72px;border-radius:50%;
  background:linear-gradient(135deg,#6366f1,#a78bfa);
  display:flex;align-items:center;justify-content:center;
  font-size:2rem;margin:0 auto 12px;box-shadow:0 0 28px rgba(99,102,241,.5)}
.prof-name{font-family:'Syne',sans-serif!important;font-size:1.4rem;font-weight:800;
  color:#e2e8f0;margin-bottom:4px}
.prof-role{display:inline-block;padding:4px 14px;border-radius:20px;font-size:.78rem;font-weight:700;margin-bottom:12px}
.prof-role.user{background:rgba(99,102,241,.2);color:#a5b4fc;border:1px solid #6366f1}
.prof-role.expert{background:rgba(16,185,129,.2);color:#6ee7b7;border:1px solid #10b981}
.stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:0}
.stat-box{background:rgba(255,255,255,.05);border-radius:14px;padding:12px 8px;text-align:center}
.stat-num{font-family:'Syne',sans-serif!important;font-size:1.4rem;font-weight:800;line-height:1}
.stat-lbl{font-size:.65rem;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-top:3px}
.prof-section{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
  border-radius:18px;padding:16px;margin-bottom:12px}
.prof-section h4{font-size:.72rem;font-weight:800;color:#64748b;letter-spacing:1.5px;
  text-transform:uppercase;margin-bottom:10px}
.prof-row{display:flex;justify-content:space-between;align-items:center;
  padding:7px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.prof-row:last-child{border-bottom:none}
.prof-key{font-size:.82rem;color:#64748b;font-weight:600}
.prof-val{font-size:.84rem;color:#e2e8f0;font-weight:500;text-align:right;word-break:break-all}
.back-btn button{background:rgba(255,255,255,.07)!important;border:1px solid rgba(255,255,255,.12)!important;
  border-radius:50px!important;color:#94a3b8!important;font-size:.84rem!important;
  padding:.4rem 1.2rem!important;box-shadow:none!important;width:auto!important}
.back-btn button:hover{background:rgba(255,255,255,.12)!important;transform:none!important;box-shadow:none!important}
.logout-btn button{background:linear-gradient(135deg,#ef4444,#b91c1c)!important;
  border-radius:50px!important;font-weight:700!important}
@media(max-width:480px){.prof-hero{padding:20px 14px 16px}.prof-name{font-size:1.2rem}}
</style>""", unsafe_allow_html=True)

    username   = st.session_state.get("username","")
    user_email = st.session_state.get("user_email","")
    user_role  = st.session_state.get("user_role","user")

    # Fetch DB info
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT created_at, email, id_type, id_number, id_filename, id_verified FROM users WHERE username=?",
        (username,)).fetchone()
    conn.close()
    joined_date  = row[0] if row else "N/A"
    db_email     = row[1] if row else user_email
    prof_id_type = row[2] if row and row[2] else ""
    prof_id_num  = row[3] if row and row[3] else ""
    prof_id_file = row[4] if row and row[4] else ""
    prof_id_ver  = bool(row[5]) if row else False

    df_prof = db_get_scans(username)
    tot_p   = len(df_prof) if not df_prof.empty else 0
    fk_p    = int((df_prof["authentic"]==0).sum()) if not df_prof.empty else 0
    gn_p    = tot_p - fk_p
    avg_sc  = f"{df_prof['score'].mean():.1f}%" if not df_prof.empty else "—"

    # Streak
    streak = 0
    if not df_prof.empty:
        for val in df_prof["authentic"]:
            if val == 1: streak += 1
            else: break

    role_ico  = "👨‍⚕️" if user_role=="expert" else "👤"
    role_lbl  = "Expert / Pharmacist" if user_role=="expert" else "Patient / User"
    role_cls  = "expert" if user_role=="expert" else "user"

    # Recent scans
    recent_meds = []
    if not df_prof.empty and "medicine" in df_prof.columns:
        recent_meds = df_prof["medicine"].dropna().head(5).tolist()

    _, col, _ = st.columns([0.5, 4, 0.5])
    with col:
        # Back button
        st.markdown('<div class="back-btn">', unsafe_allow_html=True)
        if st.button("← Back", key="btn_prof_back"):
            st.session_state["show_profile"] = False; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        # Hero card
        st.markdown(f"""
<div class="prof-hero">
  <div class="prof-avatar">{role_ico}</div>
  <div class="prof-name">{username}</div>
  <div class="prof-role {role_cls}">{role_lbl}</div>
  <div class="stat-grid">
    <div class="stat-box">
      <div class="stat-num" style="color:#a78bfa">{tot_p}</div>
      <div class="stat-lbl">Total Scans</div>
    </div>
    <div class="stat-box">
      <div class="stat-num" style="color:#10b981">{gn_p}</div>
      <div class="stat-lbl">Genuine</div>
    </div>
    <div class="stat-box">
      <div class="stat-num" style="color:#ef4444">{fk_p}</div>
      <div class="stat-lbl">Fakes Found</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

        # Account info
        st.markdown(f"""
<div class="prof-section">
  <h4>Account Info</h4>
  <div class="prof-row"><span class="prof-key">Username</span><span class="prof-val">{username}</span></div>
  <div class="prof-row"><span class="prof-key">Email</span><span class="prof-val">{db_email}</span></div>
  <div class="prof-row"><span class="prof-key">Role</span><span class="prof-val">{role_lbl}</span></div>
  <div class="prof-row"><span class="prof-key">Joined</span><span class="prof-val">{joined_date}</span></div>
</div>""", unsafe_allow_html=True)

        # Scan stats
        st.markdown(f"""
<div class="prof-section">
  <h4>Scan Statistics</h4>
  <div class="prof-row"><span class="prof-key">Total Scans</span><span class="prof-val">{tot_p}</span></div>
  <div class="prof-row"><span class="prof-key">Genuine Medicines</span><span class="prof-val" style="color:#10b981">{gn_p}</span></div>
  <div class="prof-row"><span class="prof-key">Fakes Detected</span><span class="prof-val" style="color:#ef4444">{fk_p}</span></div>
  <div class="prof-row"><span class="prof-key">Avg. Score</span><span class="prof-val">{avg_sc}</span></div>
  <div class="prof-row"><span class="prof-key">Genuine Streak</span><span class="prof-val" style="color:#00f5a0">{streak} 🔥</span></div>
</div>""", unsafe_allow_html=True)

        # Recent scans
        if recent_meds:
            rows = "".join(f'<div class="prof-row"><span class="prof-key">💊</span><span class="prof-val">{m.title()}</span></div>' for m in recent_meds)
            st.markdown(f'<div class="prof-section"><h4>Recent Scans</h4>{rows}</div>', unsafe_allow_html=True)

        # Alert status
        st.markdown(f"""
<div class="prof-section">
  <h4>Alert Settings</h4>
  <div class="prof-row"><span class="prof-key">Auto Email Alert</span><span class="prof-val" style="color:#10b981">✅ Active</span></div>
  <div class="prof-row"><span class="prof-key">Alert Sent To</span><span class="prof-val">{user_email}</span></div>
</div>""", unsafe_allow_html=True)

        # Expert ID verification section
        if user_role == "expert":
            id_badge = (
                f'<span style="background:rgba(16,185,129,.2);color:#6ee7b7;border:1px solid #10b981;'
                f'border-radius:8px;padding:2px 10px;font-size:.72rem;font-weight:700">✅ Verified</span>'
                if prof_id_ver else
                f'<span style="background:rgba(245,158,11,.2);color:#fde68a;border:1px solid #f59e0b;'
                f'border-radius:8px;padding:2px 10px;font-size:.72rem;font-weight:700">⏳ Pending</span>'
            )
            id_type_clean = prof_id_type.split(" ",1)[-1] if prof_id_type else "Not provided"
            st.markdown(f"""
<div class="prof-section">
  <h4>🪪 Professional ID Verification</h4>
  <div class="prof-row">
    <span class="prof-key">Status</span>
    <span class="prof-val">{id_badge}</span>
  </div>
  <div class="prof-row">
    <span class="prof-key">ID Type</span>
    <span class="prof-val">{id_type_clean}</span>
  </div>
  <div class="prof-row">
    <span class="prof-key">Reg. / License No.</span>
    <span class="prof-val">{prof_id_num if prof_id_num else "Not provided"}</span>
  </div>
  <div class="prof-row">
    <span class="prof-key">Document</span>
    <span class="prof-val">{prof_id_file if prof_id_file else "Not uploaded"}</span>
  </div>
</div>""", unsafe_allow_html=True)

        # Logout + Delete Account
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="logout-btn">', unsafe_allow_html=True)
        if st.button("🚪 Logout", key="btn_prof_logout", use_container_width=True):
            _clear_session()
            for k in list(DEFAULTS.keys()):
                st.session_state[k] = DEFAULTS[k]
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<p style="color:#64748b;font-size:.72rem;font-weight:700;letter-spacing:1px;margin-bottom:6px">⚠️ DANGER ZONE</p>', unsafe_allow_html=True)

        # Delete confirmation
        if not st.session_state.get("confirm_delete"):
            if st.button("🗑️ Delete My Account", key="btn_del_start", use_container_width=True):
                st.session_state["confirm_delete"] = True
                st.rerun()
        else:
            st.markdown(
                '<div style="background:rgba(239,68,68,.12);border:1px solid #ef4444;'
                'border-radius:14px;padding:14px 16px;margin-bottom:8px">'
                '<p style="color:#fca5a5;font-weight:700;font-size:.88rem;margin-bottom:6px">'
                '⚠️ Are you sure you want to delete your account?</p>'
                '<p style="color:#94a3b8;font-size:.78rem;margin:0">'
                'This will permanently delete your account and all scan history. This cannot be undone.</p>'
                '</div>', unsafe_allow_html=True)
            dc1, dc2 = st.columns(2)
            with dc1:
                if st.button("✅ Yes, Delete", key="btn_del_confirm", use_container_width=True):
                    # Send deletion email BEFORE deleting from DB (need email from DB)
                    try:
                        conn_em = sqlite3.connect(DB_PATH)
                        em_row  = conn_em.execute(
                            "SELECT email, role FROM users WHERE username=?", (username,)).fetchone()
                        conn_em.close()
                        if em_row:
                            send_deletion_email(em_row[0], username, em_row[1] or "user")
                    except Exception:
                        pass
                    # Mark account file as deleted (audit trail)
                    _delete_account_file(username)
                    # Now delete all data from DB
                    try:
                        conn_d = sqlite3.connect(DB_PATH)
                        conn_d.execute("DELETE FROM users WHERE username=?", (username,))
                        conn_d.execute("DELETE FROM scans WHERE username=?", (username,))
                        conn_d.execute("DELETE FROM chats WHERE username=?", (username,))
                        conn_d.execute("DELETE FROM qa_questions WHERE username=?", (username,))
                        conn_d.execute("DELETE FROM qa_answers WHERE expert_username=?", (username,))
                        conn_d.commit(); conn_d.close()
                    except Exception: pass
                    # Sync CSV after deletion
                    _csv_append_login(username, "", "", "ACCOUNT_DELETED")
                    _csv_sync_from_db()
                    _clear_session()
                    for k in list(DEFAULTS.keys()):
                        st.session_state[k] = DEFAULTS[k]
                    st.session_state["confirm_delete"] = False
                    st.rerun()
            with dc2:
                if st.button("❌ Cancel", key="btn_del_cancel", use_container_width=True):
                    st.session_state["confirm_delete"] = False
                    st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)


def show_app():
    DK                         = st.session_state.dark_mode
    BG,SIDE,CARD,TXT,MUT,BDR,CHT,CSS = main_css(DK)
    st.markdown(CSS, unsafe_allow_html=True)

    username   = st.session_state.username
    user_email = st.session_state.user_email   # their Gmail = alert receiver
    user_role  = st.session_state.get("user_role", "user")
    is_expert  = (user_role == "expert")

    # ── Session flags ──────────────────────────────────────────────
    if "show_profile" not in st.session_state:
        st.session_state["show_profile"] = False

    # If profile page requested, show it full-screen instead of app
    if st.session_state.get("show_profile"):
        # Hide sidebar on profile page
        st.markdown("""<style>
section[data-testid="stSidebar"]{display:none!important}
.block-container{max-width:600px!important;margin:0 auto!important;padding:1rem 1rem!important}
</style>""", unsafe_allow_html=True)
        show_profile_page()
        return

    with st.sidebar:
        # ── Header row ─────────────────────────────────────────────
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'margin-bottom:4px;padding:4px 0">'
            f'<div style="font-size:.95rem;font-weight:800;color:#a78bfa;'
            f'font-family:Syne,sans-serif;white-space:nowrap">🛡️ PharmaScan</div>'
            f'</div>',
            unsafe_allow_html=True)

        sb1, sb2, sb3 = st.columns([1.2, 1, 1])
        with sb1:
            st.markdown(f'<div style="color:{MUT};font-size:.75rem;padding-top:6px">👤 {username}</div>', unsafe_allow_html=True)
        with sb2:
            if st.button("🌙" if DK else "☀️", key="btn_theme", use_container_width=True):
                st.session_state.dark_mode = not DK
                _save_session(username, user_role, user_email)
                st.rerun()
        with sb3:
            if st.button("👤 Me", key="btn_profile", use_container_width=True):
                st.session_state["show_profile"] = True
                st.rerun()

        st.markdown("---")

        # ── Detection Settings ─────────────────────────────────────
        st.markdown(f'<p style="color:{MUT};font-size:.7rem;font-weight:800;letter-spacing:1px;margin-bottom:6px;margin-top:2px">⚙️ DETECTION SETTINGS</p>', unsafe_allow_html=True)
        conf_thresh = st.slider("Fake Threshold %", 50, 90, 72, key="sl_thresh")
        ocr_langs   = st.multiselect("OCR Languages", ["en","hi","ta","ar","zh","fr"], default=["en"])

        st.markdown("---")
        st.markdown(f'<p style="color:{MUT};font-size:.7rem;font-weight:800;letter-spacing:1px;margin-bottom:6px">📍 LOCATION</p>', unsafe_allow_html=True)
        user_lat  = st.number_input("Latitude",  value=13.0827, format="%.4f")
        user_lon  = st.number_input("Longitude", value=80.2707, format="%.4f")
        user_city = st.text_input("City", value="Chennai")

        st.markdown("---")
        st.markdown(
            f'<div style="background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.4);'
            f'border-radius:10px;padding:7px 10px;font-size:.74rem;color:#6ee7b7;line-height:1.5">'
            f'✅ <b>Auto-alert ON</b><br><span style="word-break:break-all">{user_email}</span></div>',
            unsafe_allow_html=True)

        st.markdown("---")
        st.markdown(f'<p style="color:{MUT};font-size:.7rem;font-weight:800;letter-spacing:1px;margin-bottom:6px">💊 QUICK INTERACTION</p>', unsafe_allow_html=True)
        qa = st.selectbox("Medicine A", [""] + list(MEDS.keys()), key="qa")
        qb = st.selectbox("Medicine B", [""] + list(MEDS.keys()), key="qb")
        if st.button("⚡ Check", key="btn_interact", use_container_width=True) and qa and qb and qa != qb:
            with st.spinner("NIH query..."):
                ints = drug_interactions(qa, qb)
            if ints:
                for i in ints[:2]:
                    sv = i["sev"].lower()
                    ic = "🔴" if "high" in sv else "🟡" if "moderate" in sv else "🟢"
                    st.warning(f"{ic} {i['sev']}: {i['desc'][:80]}")
            else:
                st.success("No known interactions.")

        st.markdown("---")
        df_sb = db_get_scans(username)
        if not df_sb.empty:
            tot_sb = len(df_sb); fk_sb = int((df_sb["authentic"]==0).sum())
            streak = 0
            for val in df_sb["authentic"]:
                if val == 1: streak += 1
                else: break
            st.markdown(f'<p style="color:{MUT};font-size:.7rem;font-weight:800;letter-spacing:1px;margin-bottom:6px">🏆 YOUR STATS</p>', unsafe_allow_html=True)
            if streak >= 3:
                st.markdown(f'<div style="background:linear-gradient(135deg,#064e3b,#065f46);border:1px solid #10b981;border-radius:10px;padding:7px;text-align:center;margin-bottom:6px"><div style="color:#00f5a0;font-size:1.2rem;font-weight:800">{streak}🔥</div><div style="color:#6ee7b7;font-size:.63rem;font-weight:700;letter-spacing:.5px">GENUINE STREAK</div></div>', unsafe_allow_html=True)
            st.markdown(
                f'<div style="color:{MUT};font-size:.72rem;line-height:1.8">'
                f'📊 {tot_sb} scans<br>'
                f'🛡️ {tot_sb-fk_sb} genuine<br>'
                f'🚨 {fk_sb} fakes caught</div>',
                unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🚪 Logout", key="btn_logout_main", use_container_width=True):
            _clear_session()
            for k in list(DEFAULTS.keys()):
                st.session_state[k] = DEFAULTS[k]
            st.rerun()

    # ── TOP NAVBAR — HTML wrapper with Streamlit buttons inside ──
    st.markdown(f"""<style>
/* Sidebar toggle */
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarNavToggleButton"] {{
  position:fixed!important; top:10px!important; left:10px!important;
  z-index:9999!important; width:40px!important; height:40px!important;
  background:rgba(99,102,241,0.2)!important;
  border:1.5px solid rgba(99,102,241,0.45)!important;
  border-radius:10px!important; overflow:hidden!important;
}}
[data-testid="stSidebarCollapsedControl"]*,
[data-testid="stSidebarNavToggleButton"]* {{
  color:transparent!important; font-size:0!important;
}}
[data-testid="stSidebarCollapsedControl"]::after,
[data-testid="stSidebarNavToggleButton"]::after {{
  content:"☰"!important; font-size:1.2rem!important;
  color:#a78bfa!important; position:absolute!important;
  pointer-events:none!important;
}}
/* Navbar wrapper */
div.nav-row [data-testid="stHorizontalBlock"] {{
  background:rgba(15,23,42,0.88)!important;
  border:1px solid rgba(99,102,241,0.2)!important;
  border-radius:14px!important;
  padding:4px 8px 4px 52px!important;
  margin-bottom:12px!important;
  gap:0px!important;
  align-items:center!important;
  flex-wrap:nowrap!important;
}}
div.nav-row [data-testid="column"] {{
  padding:0 2px!important;
  min-width:0!important;
  flex-shrink:1!important;
}}
/* Brand column — shrink text on mobile */
div.nav-row [data-testid="column"]:first-child {{
  flex-shrink:1!important;
  min-width:0!important;
  overflow:hidden!important;
}}
/* Nav buttons */
div.nav-row .stButton>button {{
  background:rgba(99,102,241,0.14)!important;
  border:1px solid rgba(99,102,241,0.3)!important;
  border-radius:20px!important;
  color:#c4b5fd!important;
  font-size:0.72rem!important;
  font-weight:600!important;
  padding:3px 8px!important;
  box-shadow:none!important;
  min-height:26px!important;
  height:26px!important;
  line-height:1!important;
  transform:none!important;
  white-space:nowrap!important;
  width:100%!important;
}}
div.nav-row .stButton>button:hover {{
  background:rgba(99,102,241,0.28)!important;
  transform:none!important; box-shadow:none!important;
}}
div.nav-row [data-testid="column"]:last-child .stButton>button {{
  background:rgba(239,68,68,0.12)!important;
  border-color:rgba(239,68,68,0.28)!important;
  color:#fca5a5!important;
}}
/* Mobile: shrink brand text */
@media(max-width:768px){{
  div.nav-row [data-testid="stHorizontalBlock"] {{
    padding:4px 6px 4px 48px!important;
  }}
  div.nav-row .stButton>button {{
    font-size:0.65rem!important;
    padding:3px 5px!important;
  }}
}}
</style>""", unsafe_allow_html=True)

    st.markdown('<div class="nav-row">', unsafe_allow_html=True)
    nb_brand, nb1, nb2, nb3 = st.columns([7.5, 0.6, 0.6, 0.6])
    with nb_brand:
        st.markdown(
            f'<p style="color:#a78bfa;font-family:Syne,sans-serif;font-weight:800;'
            f'font-size:clamp(0.7rem,2vw,0.92rem);margin:0;padding-top:3px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'🛡️ PharmaScan &nbsp;<span style="color:#475569;font-size:.68rem;font-weight:400">👤 {username}</span></p>',
            unsafe_allow_html=True)
    with nb1:
        if st.button("👤", key="btn_top_profile", use_container_width=True):
            st.session_state["show_profile"] = True
            st.rerun()
    with nb2:
        if st.button("🌙" if DK else "☀️", key="btn_top_theme", use_container_width=True):
            st.session_state.dark_mode = not DK
            _save_session(username, user_role, user_email)
            st.rerun()
    with nb3:
        if st.button("🚪", key="btn_top_logout", use_container_width=True):
            _clear_session()
            for k in list(DEFAULTS.keys()):
                st.session_state[k] = DEFAULTS[k]
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Handle navbar actions via query params (no visible ghost buttons) ──
    qp = st.query_params
    if qp.get("nav") == "profile":
        st.query_params.clear()
        st.session_state["show_profile"] = True
        st.rerun()
    elif qp.get("nav") == "theme":
        st.query_params.clear()
        st.session_state.dark_mode = not DK
        _save_session(username, user_role, user_email)
        st.rerun()
    elif qp.get("nav") == "logout":
        st.query_params.clear()
        _clear_session()
        for k in list(DEFAULTS.keys()):
            st.session_state[k] = DEFAULTS[k]
        st.rerun()

    # ── HERO ─────────────────────────────────────────────────────
    df_c = db_get_scans(username)
    tot_c = len(df_c)
    fk_c  = int((df_c["authentic"]==0).sum()) if not df_c.empty else 0
    gn_c  = tot_c - fk_c

    st.markdown("""
    <div class="hero">
      <div class="app-name">🛡️ PharmaScan AI</div>
      <div class="app-sub">Vision-Based Fake Medicine Detection · Hackathon Edition</div>
      <div class="hero-pills">
        <span class="pill">🧠 Vision</span>
        <span class="pill">📸 Camera</span>
        <span class="pill">🔤 OCR</span>
        <span class="pill">🔡 Spell</span>
        <span class="pill">📄 PDF</span>
        <span class="pill">📧 Alert</span>
        <span class="pill">🗺️ Heatmap</span>
        <span class="pill">🔗 NIH</span>
        <span class="pill">🏥 FDA</span>
        <span class="pill">💊 Compare</span>
        <span class="pill">🔮 Hotspot</span>
        <span class="pill">🏅 Cert</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if tot_c > 0:
        st.markdown(
            f'<div style="display:flex;justify-content:center;gap:40px;margin-bottom:1.2rem">'
            f'<div style="text-align:center"><div style="font-size:1.8rem;font-weight:800;color:#00f5a0;font-family:Syne,sans-serif">{tot_c}</div><div style="font-size:0.67rem;color:{MUT};font-weight:700;letter-spacing:1px">YOUR SCANS</div></div>'
            f'<div style="text-align:center"><div style="font-size:1.8rem;font-weight:800;color:#10b981;font-family:Syne,sans-serif">{gn_c}</div><div style="font-size:0.67rem;color:{MUT};font-weight:700;letter-spacing:1px">GENUINE</div></div>'
            f'<div style="text-align:center"><div style="font-size:1.8rem;font-weight:800;color:#ef4444;font-family:Syne,sans-serif">{fk_c}</div><div style="font-size:0.67rem;color:{MUT};font-weight:700;letter-spacing:1px">FAKES CAUGHT</div></div>'
            f'</div>', unsafe_allow_html=True)

    pc = st.columns(6)
    for col,ico,n,l in [(pc[0],"📷","01","Upload"),(pc[1],"👁️","02","Vision"),
                         (pc[2],"🔤","03","OCR+Spell"),(pc[3],"🕵️","04","Detect"),
                         (pc[4],"📋","05","Report"),(pc[5],"✅","06","Done")]:
        col.markdown(
            f'<div class="step"><div class="step-ico">{ico}</div>'
            f'<div class="step-n">STEP {n}</div><div class="step-l">{l}</div></div>',
            unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── TABS — role-differentiated ────────────────────────────────
    if is_expert:
        T1,T2,T3,T4,T5,T6,T7 = st.tabs([
            "🔬 Vision Scanner","📸 Live Camera",
            "💬 Q&A Forum","📋 Patient Reports",
            "📦 Bulk Scan","🧬 Drug Database","📊 Analytics",
        ])
    else:
        T1,T2,T3,T4,T5,T6,T7 = st.tabs([
            "🔬 Vision Scanner","📸 Live Camera",
            "💬 Q&A Forum","🔗 Interactions",
            "📊 Dashboard","🗺️ Heatmap","💊 Compare Meds",
        ])

    # ══════════════════════════════════════════════
    # TAB 1 — VISION SCANNER
    # ══════════════════════════════════════════════
    with T1:
        L, R = st.columns([1,1], gap="large")
        with L:
            st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">📷 Upload Medicine Image</p>',
                        unsafe_allow_html=True)
            uf = st.file_uploader("Drop image here",
                                   type=["jpg","png","jpeg","webp"],
                                   label_visibility="collapsed")

            if uf:
                img_pil  = Image.open(uf)
                img_arr  = np.array(img_pil.convert("RGB"))
                st.session_state["upload_img_arr"] = img_arr
                proc_g   = preprocess(img_arr)
                proc_rgb = cv2.cvtColor(proc_g, cv2.COLOR_GRAY2RGB)

                st.markdown(f'<p class="sh">Before / After Processing</p>',
                            unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                b1.markdown('<div class="clbl">Original</div>',
                            unsafe_allow_html=True)
                b1.image(img_pil, use_container_width=True)
                b2.markdown('<div class="clbl">Processed</div>',
                            unsafe_allow_html=True)
                b2.image(proc_rgb, use_container_width=True)

                if st.button("🔬 Run Full PharmaScan Analysis",
                              use_container_width=True):
                    with st.spinner("Running vision analysis..."):
                        ocr  = run_ocr(img_arr, ocr_langs)
                        st.session_state.ocr_text = ocr
                        score, checks, sh, co, ed = vision_analyze(img_arr)
                        ok   = score >= conf_thresh
                        em, es, _  = parse_expiry(ocr)
                        med  = detect_med(ocr)
                        st.session_state.current_medicine = med
                        fda  = fda_label(med) if med else None
                        sp   = check_spelling(ocr)
                        st.session_state.scan_result = {
                            "ok":ok,"score":score,"checks":checks,
                            "expiry_msg":em,"es":es,
                            "med":med,"ocr":ocr,"fda":fda,
                            "sh":sh,"co":co,"ed":ed,
                            "bc":[],"spell":sp,
                        }
                        db_save_scan(username, med or "Unknown", ok, score, es,
                                     ocr, sh, co, ed, user_city, user_lat, user_lon,
                                     ",".join([se["word"] for se in sp]))
                        if not ok and user_email:
                            if "@pharmascan.demo" in user_email:
                                st.session_state.alert_sent = False
                                st.session_state.alert_err  = (
                                    "Demo account — enter a real Gmail address at login "
                                    "to receive email alerts.")
                            else:
                                sent, err_msg = send_alert(
                                    user_email, med or "Unknown", score, username)
                                st.session_state.alert_sent = sent
                                st.session_state.alert_err  = "" if sent else err_msg
                    st.success("✅ Done!")

        with R:
            if st.session_state.scan_result:
                r   = st.session_state.scan_result
                med = r["med"]
                st.markdown(
                    f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">Results</p>',
                    unsafe_allow_html=True)

                if r["ok"]:
                    st.markdown(
                        f'<div class="rc rc-ok">✅ <strong>GENUINE MEDICINE</strong><br>'
                        f'<small>Score: {r["score"]:.1f}%</small></div>',
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        f'<div class="pulse">🚨 <strong>FAKE / COUNTERFEIT</strong><br>'
                        f'<small>Score: {r["score"]:.1f}% — DO NOT CONSUME</small></div>',
                        unsafe_allow_html=True)
                    if st.session_state.get("alert_sent"):
                        st.markdown(
                            f'<div class="rc rc-ok" style="padding:0.6rem 1rem;font-size:0.83rem">'
                            f'📧 Alert email sent → {user_email}</div>',
                            unsafe_allow_html=True)
                    elif st.session_state.get("alert_err"):
                        st.markdown(
                            f'<div class="rc rc-warn" style="padding:0.6rem 1rem;font-size:0.83rem">'
                            f'⚠️ Email not sent: {st.session_state.alert_err}</div>',
                            unsafe_allow_html=True)

                # Gauge
                gc  = "#10b981" if r["ok"] else "#ef4444"
                fig = go.Figure(go.Indicator(
                    mode="gauge+number", value=r["score"],
                    domain={"x":[0,1],"y":[0,1]},
                    title={"text":"Detection Score","font":{"size":13,"color":MUT}},
                    number={"suffix":"%","font":{"color":TXT,"size":26}},
                    gauge={
                        "axis":{"range":[0,100],"tickcolor":MUT,
                                "tickfont":{"color":MUT}},
                        "bar":{"color":gc},"bgcolor":CARD,
                        "steps":[
                            {"range":[0,conf_thresh],"color":"rgba(239,68,68,0.1)"},
                            {"range":[conf_thresh,100],"color":"rgba(16,185,129,0.1)"},
                        ],
                        "threshold":{"line":{"color":"white","width":3},
                                     "thickness":0.8,"value":conf_thresh},
                    }))
                fig.update_layout(height=210, margin=dict(t=38,b=5,l=5,r=5),
                                  paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)

                # Vision chips
                st.markdown('<p class="sh">Vision Breakdown</p>',
                            unsafe_allow_html=True)
                vc1,vc2,vc3 = st.columns(3)
                for col,ico,lbl,val,good in [
                    (vc1,"🖼️","Sharpness",f"{r['sh']:.0f}%",r["sh"]>40),
                    (vc2,"🎨","Colour",   f"{r['co']:.0f}%",r["co"]>40),
                    (vc3,"🖨️","Print",    f"{r['ed']:.0f}%",r["ed"]>30),
                ]:
                    val_color = "#10b981" if good else "#ef4444"
                    col.markdown(
                        f'<div class="vc"><div class="vc-ico">{ico}</div>'
                        f'<div class="vc-lbl">{lbl}</div>'
                        f'<div class="vc-val" style="color:{val_color}">{val}</div></div>',
                        unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)

                # Visual checks
                st.markdown('<p class="sh">Visual Inspection</p>',
                            unsafe_allow_html=True)
                for ico,msg,st_ in r["checks"]:
                    cls = {"ok":"rc-ok","bad":"rc-bad","warn":"rc-warn"}[st_]
                    st.markdown(
                        f'<div class="rc {cls}" style="padding:0.55rem 1rem;font-size:0.83rem">'
                        f'{ico} {msg}</div>', unsafe_allow_html=True)

                # Risk card
                st.markdown('<p class="sh">Risk Score Breakdown</p>',
                            unsafe_allow_html=True)
                risks, rtot, (rvd, rclr) = risk_card(r, med)
                lc = {"CRIT":"rc-bad","HIGH":"rc-bad","MED":"rc-warn","LOW":"rc-info"}
                li = {"CRIT":"🔴","HIGH":"🔴","MED":"🟡","LOW":"🟢"}
                st.markdown(
                    f'<div class="rc" style="background:linear-gradient(135deg,#1e293b,#0f172a);'
                    f'border:2px solid {rclr};padding:0.9rem 1.2rem;margin-bottom:0.6rem">'
                    f'<span style="font-weight:800;color:{rclr}">Risk: {rvd}</span>'
                    f'<span style="float:right;font-size:1.2rem;font-weight:800;color:{rclr}">'
                    f'{rtot}%</span></div>', unsafe_allow_html=True)
                for rf in risks:
                    st.markdown(
                        f'<div class="rc {lc.get(rf["l"],"rc-info")}" '
                        f'style="padding:0.5rem 1rem;font-size:0.81rem">'
                        f'{li.get(rf["l"],"🟡")} <strong>{rf["f"]}</strong>'
                        f'<span style="float:right;opacity:0.7;font-size:0.72rem">'
                        f'+{rf["w"]}%</span><br><small>{rf["d"]}</small></div>',
                        unsafe_allow_html=True)

                # Spelling
                st.markdown('<p class="sh">Spelling Detector</p>',
                            unsafe_allow_html=True)
                if r["spell"]:
                    st.markdown(
                        f'<div class="rc rc-bad" style="padding:0.65rem 1rem">'
                        f'⚠️ {len(r["spell"])} spelling error(s) — strong FAKE indicator!</div>',
                        unsafe_allow_html=True)
                    html = "".join(
                        f'<span class="sp-bad">❌ {se["word"]}</span>'
                        f' → <span class="sp-fix">✅ {se["fix"]}</span>&nbsp;&nbsp;'
                        for se in r["spell"])
                    st.markdown(
                        f'<div style="background:{CARD};padding:12px;border-radius:12px;'
                        f'border:1px solid {BDR}">{html}</div>',
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<div class="rc rc-ok" style="padding:0.55rem 1rem;font-size:0.83rem">'
                        '✅ No spelling errors detected</div>', unsafe_allow_html=True)

                # Expiry
                st.markdown('<p class="sh">Expiry Date</p>',
                            unsafe_allow_html=True)
                ecls = {"bad":"rc-bad","warn":"rc-warn","ok":"rc-ok"}.get(r["es"],"rc-info")
                eico = {"bad":"❌","warn":"⚠️","ok":"✅","unknown":"📅"}.get(r["es"],"📅")
                st.markdown(
                    f'<div class="rc {ecls}" style="padding:0.7rem 1rem;font-size:0.9rem">'
                    f'{eico} {r["expiry_msg"]}</div>', unsafe_allow_html=True)

                # Medicine info
                if med:
                    info = MEDS.get(med, {})
                    st.markdown(
                        f'<p class="sh">Detected: <span style="color:#00f5a0">'
                        f'{med.upper()}</span></p>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="mc mc-p"><h4>Pill Matcher</h4>'
                        f'<p>Colour: {info.get("colour","N/A")} · '
                        f'Shape: {info.get("shape","N/A")}<br>'
                        f'Genuine signs: {info.get("genuine","N/A")}</p></div>',
                        unsafe_allow_html=True)
                    m1c, m2c = st.columns(2)
                    with m1c:
                        for cls,h,k in [("mc-b","Category","cat"),
                                         ("mc-g","Use","use"),
                                         ("mc-b","Dosage","dosage")]:
                            st.markdown(
                                f'<div class="mc {cls}"><h4>{h}</h4>'
                                f'<p>{info.get(k,"N/A")}</p></div>',
                                unsafe_allow_html=True)
                    with m2c:
                        st.markdown(
                            f'<div class="mc mc-a"><h4>Side Effects</h4>'
                            f'<p>{info.get("se","N/A")}</p></div>',
                            unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="mc mc-r"><h4>Warning</h4>'
                            f'<p>{info.get("warn","N/A")}</p></div>',
                            unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="mc mc-a"><h4>Interactions</h4>'
                            f'<p>{", ".join(info.get("inter",[])) or "None"}</p></div>',
                            unsafe_allow_html=True)
                    if r["fda"]:
                        with st.expander("📄 FDA Label Data"):
                            for lbl, val in [
                                ("Brand",r["fda"]["brand"]),
                                ("Manufacturer",r["fda"]["mfr"]),
                                ("Purpose",r["fda"]["purpose"]),
                                ("Warnings",r["fda"]["warnings"]),
                            ]:
                                st.markdown(
                                    f'<div class="mc mc-b"><h4>{lbl}</h4>'
                                    f'<p>{val}</p></div>',
                                    unsafe_allow_html=True)

                # PDF
                st.markdown('<p class="sh">Download Report</p>',
                            unsafe_allow_html=True)
                if PDF_OK:
                    pdf = make_pdf(r, med, username, city=user_city, lat=user_lat, lon=user_lon)
                    if pdf:
                        fname = (f"pharmascan_{med or 'report'}_"
                                 f"{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
                        st.download_button("📄 Download PDF Safety Report",
                                           pdf, fname, "application/pdf",
                                           use_container_width=True)
                else:
                    st.info("pip install reportlab  for PDF")

                with st.expander("🔤 OCR Text"):
                    st.code(r["ocr"] or "None", language="text")

                # ── Safety Certificate ──────────────────────────
                st.markdown('<p class="sh">🏅 Safety Certificate</p>',
                            unsafe_allow_html=True)
                cert_html = make_certificate(
                    med or "Unknown", r["score"], username, user_city, r["ok"])
                fname_cert = (f"pharmascan_certificate_{med or 'medicine'}_"
                              f"{datetime.now().strftime('%Y%m%d_%H%M')}.html")
                st.download_button(
                    "🏅 Download Safety Certificate (HTML)",
                    cert_html.encode("utf-8"), fname_cert,
                    "text/html", use_container_width=True)

            else:
                st.markdown(
                    f'<div style="text-align:center;padding:4rem 2rem;'
                    f'background:rgba(255,255,255,0.02);border-radius:22px;'
                    f'border:2px dashed rgba(99,102,241,0.3)">'
                    f'<div style="font-size:4rem">🔬</div>'
                    f'<p style="font-size:1.2rem;font-weight:700;color:{TXT}">Ready to Detect</p>'
                    f'<p style="color:{MUT};font-size:0.9rem">'
                    f'Upload image → Run Full Analysis</p></div>',
                    unsafe_allow_html=True)

    # ══════════════════════════════════════════════
    # TAB 2 — LIVE CAMERA
    # ══════════════════════════════════════════════
    with T2:
        st.markdown(
            f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">'
            '📸 Live Camera Scanner</p>', unsafe_allow_html=True)
        st.markdown(
            '<div class="rc rc-info" style="padding:0.8rem 1.2rem">'
            '📱 Aim camera at medicine → Capture → Instant full analysis</div>',
            unsafe_allow_html=True)

        CL, CR = st.columns([1,1], gap="large")
        with CL:
            cam = st.camera_input("Aim camera at medicine packaging")
            if cam:
                cam_pil = Image.open(cam)
                cam_arr = np.array(cam_pil.convert("RGB"))
                # Persist image bytes so result survives reruns
                st.session_state["cam_bytes"] = cam.getvalue()
                st.session_state["cam_arr"]   = cam_arr

            # Show image from session (persists after button click)
            if st.session_state.get("cam_bytes"):
                st.image(st.session_state["cam_bytes"], use_container_width=True,
                         caption="Captured medicine image")

            if st.session_state.get("cam_arr") is not None:
                if st.button("🔬 Analyse Camera Image", use_container_width=True,
                             key="btn_cam_analyse"):
                    cam_arr = st.session_state["cam_arr"]
                    with st.spinner("Running full PharmaScan analysis..."):
                        ocr  = run_ocr(cam_arr, ocr_langs)
                        st.session_state.ocr_text = ocr
                        score, checks, sh, co, ed = vision_analyze(cam_arr)
                        ok   = score >= conf_thresh
                        em, es, _ = parse_expiry(ocr)
                        med  = detect_med(ocr)
                        st.session_state.current_medicine = med
                        sp   = check_spelling(ocr)
                        fda  = fda_label(med) if med else None
                        cr_new = {
                            "ok":ok,"score":score,"checks":checks,
                            "expiry_msg":em,"es":es,
                            "med":med,"ocr":ocr,"fda":fda,
                            "sh":sh,"co":co,"ed":ed,
                            "bc":[],"spell":sp,
                        }
                        st.session_state.cam_result  = cr_new
                        st.session_state.scan_result = cr_new
                        db_save_scan(username, med or "Unknown", ok, score, es,
                                     ocr, sh, co, ed, user_city, user_lat, user_lon,
                                     ",".join([se["word"] for se in sp]))
                        if not ok and user_email and "@pharmascan.demo" not in user_email:
                            sent, err_msg = send_alert(
                                user_email, med or "Unknown", score, username)
                            st.session_state.alert_sent = sent
                            st.session_state.alert_err  = "" if sent else err_msg
                    st.success("✅ Analysis complete!")

            if st.button("🔄 New Scan", key="btn_cam_reset"):
                st.session_state.cam_result = None
                st.session_state["cam_bytes"] = None
                st.session_state["cam_arr"]   = None
                st.rerun()

        # ── RIGHT COLUMN: full persisted report ─────────────────────
        with CR:
            cr = st.session_state.get("cam_result")
            if cr:
                med = cr["med"]
                st.markdown(
                    f'<p style="color:{TXT};font-size:1.05rem;font-weight:700">📋 Full Camera Report</p>',
                    unsafe_allow_html=True)

                # Verdict banner
                if cr["ok"]:
                    st.markdown(
                        f'<div class="rc rc-ok">✅ <strong>GENUINE MEDICINE</strong>'
                        f'<br><small>Score: {cr["score"]:.1f}%</small></div>',
                        unsafe_allow_html=True)
                else:
                    st.markdown(
                        f'<div class="pulse">🚨 <strong>FAKE / COUNTERFEIT DETECTED</strong>'
                        f'<br><small>Score: {cr["score"]:.1f}% — DO NOT CONSUME</small></div>',
                        unsafe_allow_html=True)
                    if st.session_state.get("alert_sent"):
                        st.markdown(
                            f'<div class="rc rc-ok" style="padding:0.6rem 1rem;font-size:0.83rem">'
                            f'📧 Alert email sent automatically → {user_email}</div>',
                            unsafe_allow_html=True)
                    elif st.session_state.get("alert_err"):
                        st.markdown(
                            f'<div class="rc rc-warn" style="padding:0.6rem 1rem;font-size:0.83rem">'
                            f'⚠️ Email not sent: {st.session_state.alert_err}</div>',
                            unsafe_allow_html=True)

                # Score gauge
                gc = "#10b981" if cr["ok"] else "#ef4444"
                fig_c = go.Figure(go.Indicator(
                    mode="gauge+number", value=cr["score"],
                    domain={"x":[0,1],"y":[0,1]},
                    title={"text":"Detection Score","font":{"size":13,"color":MUT}},
                    number={"suffix":"%","font":{"color":TXT,"size":26}},
                    gauge={
                        "axis":{"range":[0,100],"tickcolor":MUT,"tickfont":{"color":MUT}},
                        "bar":{"color":gc},"bgcolor":CARD,
                        "steps":[
                            {"range":[0,conf_thresh],"color":"rgba(239,68,68,0.1)"},
                            {"range":[conf_thresh,100],"color":"rgba(16,185,129,0.1)"},
                        ],
                        "threshold":{"line":{"color":"white","width":3},
                                     "thickness":0.8,"value":conf_thresh},
                    }))
                fig_c.update_layout(height=200, margin=dict(t=38,b=5,l=5,r=5),
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_c, use_container_width=True)

                # Vision chips
                st.markdown('<p class="sh">Vision Breakdown</p>', unsafe_allow_html=True)
                ccol1,ccol2,ccol3 = st.columns(3)
                for col,ico,lbl,val,good in [
                    (ccol1,"🖼️","Sharpness",f"{cr['sh']:.0f}%",cr["sh"]>40),
                    (ccol2,"🎨","Colour",   f"{cr['co']:.0f}%",cr["co"]>40),
                    (ccol3,"🖨️","Print",    f"{cr['ed']:.0f}%",cr["ed"]>30),
                ]:
                    vc = "#10b981" if good else "#ef4444"
                    col.markdown(
                        f'<div class="vc"><div class="vc-ico">{ico}</div>'
                        f'<div class="vc-lbl">{lbl}</div>'
                        f'<div class="vc-val" style="color:{vc}">{val}</div></div>',
                        unsafe_allow_html=True)

                # Visual checks
                st.markdown('<p class="sh">Visual Inspection</p>', unsafe_allow_html=True)
                for ico, chk_msg, st_ in cr["checks"]:
                    cls = {"ok":"rc-ok","bad":"rc-bad","warn":"rc-warn"}[st_]
                    st.markdown(
                        f'<div class="rc {cls}" style="padding:0.5rem 1rem;font-size:0.82rem">'
                        f'{ico} {chk_msg}</div>', unsafe_allow_html=True)

                # Risk card
                st.markdown('<p class="sh">Risk Score Breakdown</p>', unsafe_allow_html=True)
                risks_c, rtot_c, (rvd_c, rclr_c) = risk_card(cr, med)
                lc = {"CRIT":"rc-bad","HIGH":"rc-bad","MED":"rc-warn","LOW":"rc-info"}
                li_map = {"CRIT":"🔴","HIGH":"🔴","MED":"🟡","LOW":"🟢"}
                st.markdown(
                    f'<div class="rc" style="background:linear-gradient(135deg,#1e293b,#0f172a);'
                    f'border:2px solid {rclr_c};padding:0.9rem 1.2rem;margin-bottom:0.6rem">'
                    f'<span style="font-weight:800;color:{rclr_c}">Risk: {rvd_c}</span>'
                    f'<span style="float:right;font-size:1.2rem;font-weight:800;color:{rclr_c}">'
                    f'{rtot_c}%</span></div>', unsafe_allow_html=True)
                for rf in risks_c:
                    st.markdown(
                        f'<div class="rc {lc.get(rf["l"],"rc-info")}" '
                        f'style="padding:0.5rem 1rem;font-size:0.81rem">'
                        f'{li_map.get(rf["l"],"🟡")} <strong>{rf["f"]}</strong>'
                        f'<span style="float:right;opacity:0.7;font-size:0.72rem">+{rf["w"]}%</span>'
                        f'<br><small>{rf["d"]}</small></div>', unsafe_allow_html=True)

                # Spelling
                st.markdown('<p class="sh">Spelling Detector</p>', unsafe_allow_html=True)
                if cr["spell"]:
                    st.markdown(
                        f'<div class="rc rc-bad" style="padding:0.65rem 1rem">'
                        f'⚠️ {len(cr["spell"])} spelling error(s) — strong FAKE indicator!</div>',
                        unsafe_allow_html=True)
                    html_sp = "".join(
                        f'<span class="sp-bad">❌ {se["word"]}</span>'
                        f' → <span class="sp-fix">✅ {se["fix"]}</span>&nbsp;&nbsp;'
                        for se in cr["spell"])
                    st.markdown(
                        f'<div style="background:{CARD};padding:12px;border-radius:12px;'
                        f'border:1px solid {BDR}">{html_sp}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<div class="rc rc-ok" style="padding:0.55rem 1rem;font-size:0.83rem">'
                        '✅ No spelling errors detected</div>', unsafe_allow_html=True)

                # Expiry
                st.markdown('<p class="sh">Expiry Date</p>', unsafe_allow_html=True)
                ecls = {"bad":"rc-bad","warn":"rc-warn","ok":"rc-ok"}.get(cr["es"],"rc-info")
                eico = {"bad":"❌","warn":"⚠️","ok":"✅","unknown":"📅"}.get(cr["es"],"📅")
                st.markdown(
                    f'<div class="rc {ecls}" style="padding:0.7rem 1rem;font-size:0.9rem">'
                    f'{eico} {cr["expiry_msg"]}</div>', unsafe_allow_html=True)

                # Full medicine info card
                if med:
                    info = MEDS.get(med, {})
                    st.markdown(
                        f'<p class="sh">Detected: <span style="color:#00f5a0">'
                        f'{med.upper()}</span></p>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="mc mc-p"><h4>Pill Matcher</h4>'
                        f'<p>Colour: {info.get("colour","N/A")} · '
                        f'Shape: {info.get("shape","N/A")}<br>'
                        f'Genuine signs: {info.get("genuine","N/A")}</p></div>',
                        unsafe_allow_html=True)
                    cm1, cm2 = st.columns(2)
                    with cm1:
                        for cls_m, h_m, k_m in [("mc-b","Category","cat"),
                                                 ("mc-g","Use","use"),
                                                 ("mc-b","Dosage","dosage")]:
                            st.markdown(
                                f'<div class="mc {cls_m}"><h4>{h_m}</h4>'
                                f'<p>{info.get(k_m,"N/A")}</p></div>',
                                unsafe_allow_html=True)
                    with cm2:
                        st.markdown(
                            f'<div class="mc mc-a"><h4>Side Effects</h4>'
                            f'<p>{info.get("se","N/A")}</p></div>', unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="mc mc-r"><h4>Warning</h4>'
                            f'<p>{info.get("warn","N/A")}</p></div>', unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="mc mc-a"><h4>Interactions</h4>'
                            f'<p>{", ".join(info.get("inter",[])) or "None"}</p></div>',
                            unsafe_allow_html=True)
                    if cr["fda"]:
                        with st.expander("📄 FDA Label Data"):
                            for lbl_f, val_f in [
                                ("Brand",cr["fda"]["brand"]),
                                ("Manufacturer",cr["fda"]["mfr"]),
                                ("Purpose",cr["fda"]["purpose"]),
                                ("Warnings",cr["fda"]["warnings"]),
                            ]:
                                st.markdown(
                                    f'<div class="mc mc-b"><h4>{lbl_f}</h4>'
                                    f'<p>{val_f}</p></div>', unsafe_allow_html=True)

                # PDF download for camera result
                st.markdown('<p class="sh">Download Report</p>', unsafe_allow_html=True)
                if PDF_OK:
                    pdf_c = make_pdf(cr, med, username, city=user_city, lat=user_lat, lon=user_lon)
                    if pdf_c:
                        fname_c = (f"pharmascan_camera_{med or 'report'}_"
                                   f"{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
                        st.download_button("📄 Download PDF Safety Report",
                                           pdf_c, fname_c, "application/pdf",
                                           use_container_width=True)
                with st.expander("🔤 OCR Text"):
                    st.code(cr["ocr"] or "None", language="text")

                # ── Safety Certificate for camera ──────────────
                st.markdown('<p class="sh">🏅 Safety Certificate</p>',
                            unsafe_allow_html=True)
                cert_c_html = make_certificate(
                    med or "Unknown", cr["score"], username, user_city, cr["ok"])
                fname_cert_c = (f"pharmascan_cert_camera_{med or 'medicine'}_"
                                f"{datetime.now().strftime('%Y%m%d_%H%M')}.html")
                st.download_button(
                    "🏅 Download Safety Certificate (HTML)",
                    cert_c_html.encode("utf-8"), fname_cert_c,
                    "text/html", use_container_width=True)
            else:
                st.markdown(
                    f'<div style="text-align:center;padding:4rem 2rem;'
                    f'background:rgba(255,255,255,0.02);border-radius:22px;'
                    f'border:2px dashed rgba(99,102,241,0.3)">'
                    f'<div style="font-size:4rem">📸</div>'
                    f'<p style="font-size:1.1rem;font-weight:700;color:{TXT}">Ready to Scan</p>'
                    f'<p style="color:{MUT};font-size:0.9rem">'
                    f'Capture image → Full report appears here</p></div>',
                    unsafe_allow_html=True)

    # ══════════════════════════════════════════════
    # TAB 3 — Q&A FORUM
    # ══════════════════════════════════════════════
    with T3:
        user_role = st.session_state.get("user_role", "user")
        is_expert = (user_role == "expert")

        # ── Role badge ─────────────────────────────────────────
        if is_expert:
            st.markdown(
                f'<div style="background:rgba(16,185,129,0.15);border:1px solid #10b981;'
                f'border-radius:12px;padding:10px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px">'
                f'<span style="font-size:1.4rem">👨‍⚕️</span>'
                f'<div><span style="color:#10b981;font-weight:800;font-size:0.95rem">Expert Mode</span>'
                f'<span style="color:#6ee7b7;font-size:0.8rem;margin-left:8px">You can answer patient questions below</span></div></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div style="background:rgba(99,102,241,0.12);border:1px solid #6366f1;'
                f'border-radius:12px;padding:10px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px">'
                f'<span style="font-size:1.4rem">👤</span>'
                f'<div><span style="color:#a5b4fc;font-weight:800;font-size:0.95rem">Patient / User Mode</span>'
                f'<span style="color:#94a3b8;font-size:0.8rem;margin-left:8px">Ask questions — doctors & pharmacists will answer</span></div></div>',
                unsafe_allow_html=True)

        QA_CATS = ["General","Side Effects","Dosage","Drug Interactions",
                   "Fake Medicine","Expiry","Storage","Pregnancy Safety","Other"]

        # ════════════════════════════════════════════════
        # USER VIEW — Ask a question
        # ════════════════════════════════════════════════
        if not is_expert:
            st.markdown(f'<p style="color:{TXT};font-size:1.05rem;font-weight:700">💬 Ask a Medicine Question</p>', unsafe_allow_html=True)

            with st.expander("✍️ Post a New Question", expanded=True):
                st.text_area("Your Question",
                             placeholder="e.g. Is it safe to take paracetamol with ibuprofen?",
                             key="qa_q_text", height=100)
                qfc1, qfc2 = st.columns(2)
                with qfc1:
                    st.selectbox("Category", QA_CATS, key="qa_q_cat")
                with qfc2:
                    st.text_input("Medicine (optional)",
                                  placeholder="e.g. paracetamol",
                                  key="qa_q_med")
                if st.button("📨 Post Question", key="btn_post_q", use_container_width=True):
                    qt = st.session_state.get("qa_q_text","").strip()
                    if not qt or len(qt) < 10:
                        st.error("Please write a question (at least 10 characters).")
                    else:
                        qa_post_question(
                            username, user_email,
                            qt,
                            medicine=st.session_state.get("qa_q_med",""),
                            category=st.session_state.get("qa_q_cat","General")
                        )
                        st.success("✅ Question posted! Experts will answer soon.")
                        st.rerun()

        # ════════════════════════════════════════════════
        # EXPERT VIEW — Post a question or answer
        # ════════════════════════════════════════════════
        else:
            with st.expander("✍️ Also post a question (optional)", expanded=False):
                st.text_area("Your Question",
                             placeholder="Experts can also ask questions...",
                             key="qa_q_text", height=80)
                st.selectbox("Category", QA_CATS, key="qa_q_cat")
                st.text_input("Medicine", placeholder="e.g. paracetamol", key="qa_q_med")
                if st.button("📨 Post Question", key="btn_post_q_exp", use_container_width=True):
                    qt = st.session_state.get("qa_q_text","").strip()
                    if qt and len(qt) >= 10:
                        qa_post_question(username, user_email, qt,
                                         medicine=st.session_state.get("qa_q_med",""),
                                         category=st.session_state.get("qa_q_cat","General"))
                        st.success("✅ Question posted!")
                        st.rerun()

        # ════════════════════════════════════════════════
        # QUESTIONS LIST — visible to everyone
        # ════════════════════════════════════════════════
        st.markdown(f'<p style="color:{TXT};font-size:1.05rem;font-weight:700;margin-top:12px">📋 All Questions</p>', unsafe_allow_html=True)

        # Filter bar
        fbc1, fbc2, fbc3 = st.columns([1,1,1])
        with fbc1:
            filt_status = st.selectbox("Filter", ["All","Open","Answered"], key="qa_filt_st")
        with fbc2:
            filt_cat = st.selectbox("Category", ["All"] + QA_CATS, key="qa_filt_cat")
        with fbc3:
            if st.button("🔄 Refresh", key="btn_qa_refresh", use_container_width=True):
                st.rerun()

        status_map = {"All": None, "Open": "open", "Answered": "answered"}
        df_qs = qa_get_questions(
            status=status_map.get(filt_status),
            category=filt_cat if filt_cat != "All" else None
        )

        if df_qs.empty:
            st.markdown(
                f'<div class="rc rc-info" style="padding:1.2rem;text-align:center">'
                f'<div style="font-size:2rem">💬</div>'
                f'<p style="color:{TXT};font-weight:700">No questions yet</p>'
                f'<p style="color:{MUT};font-size:0.85rem">Be the first to ask a medicine question!</p></div>',
                unsafe_allow_html=True)
        else:
            for _, qrow in df_qs.iterrows():
                qid    = int(qrow["id"])
                qtext  = str(qrow.get("question",""))
                quser  = str(qrow.get("username","Unknown"))
                qcat   = str(qrow.get("category","General"))
                qmed   = str(qrow.get("medicine",""))
                qstat  = str(qrow.get("status","open"))
                qdate  = str(qrow.get("asked_at",""))
                qvotes = int(qrow.get("upvotes",0))
                answers_df = qa_get_answers(qid)
                ans_count  = len(answers_df)
                stat_clr   = "#10b981" if qstat=="answered" else "#f59e0b"
                stat_ico   = "✅ Answered" if qstat=="answered" else "⏳ Open"

                med_tag = (f'<span style="background:rgba(16,185,129,.18);color:#6ee7b7;font-size:.7rem;font-weight:700;padding:2px 7px;border-radius:6px;margin-left:4px;white-space:nowrap">{qmed}</span>' if qmed and qmed not in ("None","") else "")
                with st.container():
                    st.markdown(
                        f'<div style="background:{CARD};border:1px solid {BDR};border-radius:16px;'
                        f'padding:14px 16px;margin-bottom:10px;overflow:hidden;">'

                        f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:8px">'
                        f'<span style="background:rgba(99,102,241,.18);color:#a5b4fc;font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:6px;white-space:nowrap">{qcat}</span>'
                        f'{med_tag}'
                        f'<span style="color:{stat_clr};font-size:.7rem;font-weight:700;white-space:nowrap">{stat_ico}</span>'
                        f'<span style="color:{MUT};font-size:.7rem;margin-left:auto;white-space:nowrap;flex-shrink:0">{qdate}</span>'
                        f'</div>'

                        f'<p style="color:{TXT};font-size:.9rem;font-weight:600;margin:0 0 8px;line-height:1.5;word-break:break-word">❓ {qtext}</p>'

                        f'<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center">'
                        f'<span style="color:{MUT};font-size:.76rem">👤 {quser}</span>'
                        f'<span style="color:{MUT};font-size:.76rem">💬 {ans_count} answer{"s" if ans_count!=1 else ""}</span>'
                        f'<span style="color:{MUT};font-size:.76rem">👍 {qvotes}</span>'
                        f'</div></div>',
                        unsafe_allow_html=True)

                    # Show existing answers
                    if ans_count > 0:
                        for _, arow in answers_df.iterrows():
                            aid       = int(arow["id"])
                            atext     = str(arow.get("answer",""))
                            aexpert   = str(arow.get("expert_username",""))
                            arole     = str(arow.get("expert_role","expert"))
                            adate     = str(arow.get("answered_at",""))
                            ahelpful  = int(arow.get("helpful_votes",0))
                            role_ico  = "👨‍⚕️" if "doctor" in arole.lower() or "dr" in aexpert.lower() else "💊" if "pharm" in arole.lower() or arole=="expert" else "🔬"
                            st.markdown(
                                f'<div style="background:rgba(16,185,129,.07);border-left:3px solid #10b981;'
                                f'border-radius:0 12px 12px 0;padding:10px 14px;margin:6px 0 6px 16px;overflow:hidden;">'
                                f'<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:6px">'
                                f'<span style="color:#10b981;font-size:.78rem;font-weight:700;white-space:nowrap">{role_ico} {aexpert}</span>'
                                f'<span style="color:{MUT};font-size:.74rem;font-weight:400">({arole})</span>'
                                f'<span style="color:{MUT};font-size:.7rem;margin-left:auto;flex-shrink:0;white-space:nowrap">{adate}</span>'
                                f'</div>'
                                f'<p style="color:{TXT};font-size:.87rem;margin:0 0 6px;line-height:1.5;word-break:break-word">{atext}</p>'
                                f'<span style="color:{MUT};font-size:.73rem">👍 {ahelpful} found helpful</span>'
                                f'</div>',
                                unsafe_allow_html=True)
                            if st.button(f"👍 Helpful", key=f"helpful_{aid}"):
                                qa_upvote_answer(aid)
                                st.rerun()

                    # Action buttons
                    ab_cols = st.columns([1,1,1,3])
                    with ab_cols[0]:
                        if st.button("👍 Upvote", key=f"upvote_q_{qid}"):
                            qa_upvote_question(qid)
                            st.rerun()
                    with ab_cols[1]:
                        # Delete own question
                        if quser == username:
                            if st.button("🗑️ Delete", key=f"del_q_{qid}"):
                                qa_delete_question(qid, username)
                                st.rerun()

                    # Expert answer box
                    if is_expert:
                        with st.expander(f"✍️ Write Answer for Q#{qid}", expanded=False):
                            st.text_area("Your Answer",
                                         placeholder="Write a detailed, helpful answer...",
                                         key=f"ans_text_{qid}", height=120)
                            expert_role_label = st.selectbox(
                                "Your Role",
                                ["Pharmacist","Doctor","Clinical Expert",
                                 "Medicine Specialist","Admin"],
                                key=f"ans_role_{qid}")
                            if st.button("📤 Post Answer", key=f"btn_ans_{qid}",
                                         use_container_width=True):
                                ans_txt = st.session_state.get(f"ans_text_{qid}","").strip()
                                if not ans_txt or len(ans_txt) < 10:
                                    st.error("Please write a proper answer.")
                                else:
                                    qa_post_answer(qid, username,
                                                   expert_role_label, ans_txt)
                                    st.success("✅ Answer posted!")
                                    st.rerun()

                    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════
    # TAB 4 — ROLE SPLIT: User=Interactions / Expert=Patient Reports
    # ══════════════════════════════════════════════
    with T4:
      if not is_expert:
        # ── USER: Drug Interaction Checker ───────────────────────
        st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">🔗 Drug Interaction Checker</p>', unsafe_allow_html=True)
        di1,di2 = st.columns(2)
        with di1:
            im1 = st.selectbox("Medicine 1",[""] + list(MEDS.keys()),key="im1")
        with di2:
            im2 = st.selectbox("Medicine 2",[""] + list(MEDS.keys()),key="im2")
        cm_inp = st.text_input("Or type any medicine", placeholder="e.g. warfarin")
        if st.button("🔍 Check Interactions", use_container_width=True):
            m1i = cm_inp.strip() if cm_inp.strip() else im1; m2i = im2
            if m1i and m2i and m1i != m2i:
                with st.spinner("NIH query..."):
                    ints = drug_interactions(m1i, m2i)
                st.markdown(f'<p style="color:#00f5a0;font-weight:700">{m1i.title()} + {m2i.title()}</p>', unsafe_allow_html=True)
                if ints:
                    for i in ints:
                        sv=i["sev"].lower(); cls="rc-bad" if "high" in sv else "rc-warn" if "moderate" in sv else "rc-info"; ico="🔴" if "high" in sv else "🟡" if "moderate" in sv else "🟢"
                        st.markdown(f'<div class="rc {cls}"><strong>{ico} {i["sev"]}</strong><br><small>{i["desc"]}</small></div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="rc rc-ok">✅ No known interactions.</div>', unsafe_allow_html=True)
                li_local = MEDS.get(m1i.lower(),{}).get("inter",[])
                if any(m2i.lower()==x.lower() for x in li_local):
                    st.markdown(f'<div class="rc rc-warn">⚠️ Local DB flags: {m1i.title()} + {m2i.title()}</div>', unsafe_allow_html=True)
        st.markdown("---")
        mns = list(MEDS.keys()); mdat = []
        for m_key in mns:
            row_d = {}; li_d = MEDS[m_key].get("inter",[])
            for m2_key in mns:
                row_d[m2_key] = "⚠️" if any(m2_key.lower()==x.lower() for x in li_d) else "✅"
            mdat.append(row_d)
        st.dataframe(pd.DataFrame(mdat,index=mns), use_container_width=True)

      else:
        # ── EXPERT: Patient Reports Centre ────────────────────────
        st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">📋 Patient Scan Reports</p>', unsafe_allow_html=True)
        st.markdown('<div class="rc rc-info" style="padding:.7rem 1rem;font-size:.84rem">Review all patient scans, flag suspicious cases, and export reports for regulatory submission.</div>', unsafe_allow_html=True)

        # Filters
        prf1, prf2, prf3 = st.columns(3)
        with prf1:
            pr_filter = st.selectbox("Show", ["All Scans","Fake Only","Genuine Only"], key="pr_f")
        with prf2:
            pr_med = st.selectbox("Medicine", ["All"] + list(MEDS.keys()), key="pr_m")
        with prf3:
            if st.button("🔄 Refresh", key="btn_pr_ref", use_container_width=True): st.rerun()

        df_all = db_get_scans()  # all users
        if not df_all.empty:
            if pr_filter == "Fake Only":
                df_all = df_all[df_all["authentic"]==0]
            elif pr_filter == "Genuine Only":
                df_all = df_all[df_all["authentic"]==1]
            if pr_med != "All":
                df_all = df_all[df_all["medicine"].str.lower()==pr_med.lower()]

            tot_a=len(df_all); fk_a=int((df_all["authentic"]==0).sum()); gn_a=tot_a-fk_a
            mc=st.columns(4)
            for mcol,num,lbl,clr in [(mc[0],tot_a,"Total Scans","#a78bfa"),(mc[1],fk_a,"Fakes","#ef4444"),(mc[2],gn_a,"Genuine","#10b981"),(mc[3],f"{fk_a/tot_a*100:.1f}%" if tot_a else "0%","Fake Rate","#f59e0b")]:
                mcol.markdown(f'<div class="mb"><div class="mb-n" style="color:{clr}">{num}</div><div class="mb-l">{lbl}</div></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            # Per-patient table
            disp_pr = df_all[["scan_date","username","medicine","authentic","score","expiry_status","city"]].copy()
            disp_pr["authentic"] = disp_pr["authentic"].map({1:"✅ Genuine","0":"🚨 Fake",0:"🚨 Fake"})
            disp_pr["score"]     = disp_pr["score"].apply(lambda x: f"{x:.1f}%")
            disp_pr.columns      = ["Date","Patient","Medicine","Verdict","Score","Expiry","City"]
            st.dataframe(disp_pr, use_container_width=True, height=300)

            # Flag suspicious trend
            if fk_a >= 3:
                st.markdown(f'<div class="pulse">🚨 ALERT: {fk_a} fake medicines detected across patients! Consider reporting to drug regulatory authority.</div>', unsafe_allow_html=True)

            # Export full report
            st.download_button("⬇️ Export All Patient Reports (CSV)", df_all.to_csv(index=False), "patient_reports.csv", "text/csv", use_container_width=True)

            # Medicine risk breakdown chart
            if fk_a > 0:
                st.markdown('<p class="sh">Most Counterfeited Medicines (All Patients)</p>', unsafe_allow_html=True)
                med_fk_cnt = df_all[df_all["authentic"]==0]["medicine"].value_counts().head(6)
                if not med_fk_cnt.empty:
                    fig_pr = px.bar(x=med_fk_cnt.index, y=med_fk_cnt.values,
                                    color=med_fk_cnt.values, color_continuous_scale=["#f59e0b","#ef4444"],
                                    labels={"x":"Medicine","y":"Fake Count"})
                    fig_pr.update_layout(height=240, paper_bgcolor="rgba(0,0,0,0)",
                                         plot_bgcolor="rgba(30,41,59,.3)", font_color=TXT, showlegend=False)
                    st.plotly_chart(fig_pr, use_container_width=True)
        else:
            st.markdown('<div class="rc rc-info">No patient scans found yet.</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════
    # TAB 5 — ROLE SPLIT: User=Dashboard / Expert=Bulk Scan
    # ══════════════════════════════════════════════
    with T5:
      if not is_expert:
        # ── USER: Dashboard ───────────────────────────────────────
        st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">📊 Detection Dashboard</p>', unsafe_allow_html=True)
        if st.button("🔄 Refresh"): st.rerun()
        df = db_get_scans(username)
        if not df.empty:
            tot=len(df); gen=int(df["authentic"].sum()); fk=tot-gen
            avgc=df["score"].mean(); fkp=(fk/tot*100) if tot else 0
            mc2 = st.columns(5)
            for mcol,num,lbl,col in [(mc2[0],tot,"Total Scans","#a78bfa"),(mc2[1],gen,"Genuine","#10b981"),(mc2[2],fk,"Fake","#ef4444"),(mc2[3],f"{avgc:.1f}%","Avg Score","#00f5a0"),(mc2[4],f"{fkp:.1f}%","Fake Rate","#f59e0b")]:
                mcol.markdown(f'<div class="mb"><div class="mb-n" style="color:{col}">{num}</div><div class="mb-l">{lbl}</div></div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            dc1,dc2 = st.columns(2)
            with dc1:
                fp = px.pie(names=["Genuine","Fake"],values=[gen,fk],color_discrete_sequence=["#10b981","#ef4444"],title="Genuine vs Fake",hole=0.5)
                fp.update_layout(height=300,paper_bgcolor="rgba(0,0,0,0)",font_color=TXT)
                st.plotly_chart(fp, use_container_width=True)
            with dc2:
                if "medicine" in df.columns and df["medicine"].notna().any():
                    mc3 = df["medicine"].value_counts().head(8)
                    fb  = px.bar(x=mc3.index,y=mc3.values,title="Most Scanned",color=mc3.values,color_continuous_scale="Plasma")
                    fb.update_layout(height=300,paper_bgcolor="rgba(0,0,0,0)",font_color=TXT,showlegend=False,plot_bgcolor="rgba(255,255,255,0.03)")
                    st.plotly_chart(fb, use_container_width=True)
            if len(df)>1:
                fl = px.line(df.sort_values("id"),x="scan_date",y="score",title="Score Timeline",markers=True,color_discrete_sequence=["#00f5a0"])
                fl.add_hline(y=conf_thresh,line_dash="dash",line_color="#ef4444",annotation_text="Fake Threshold",annotation_font_color="#ef4444")
                fl.update_layout(height=260,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(30,41,59,0.4)",font_color=TXT)
                st.plotly_chart(fl, use_container_width=True)
            if "medicine" in df.columns and fk>0:
                med_fk2 = df[df["authentic"]==0]["medicine"].value_counts().head(6)
                if not med_fk2.empty:
                    fb2 = px.bar(x=med_fk2.index,y=med_fk2.values,title="🚨 Most Counterfeited",color=med_fk2.values,color_continuous_scale=["#f59e0b","#ef4444"])
                    fb2.update_layout(height=240,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(30,41,59,.3)",font_color=TXT,showlegend=False)
                    st.plotly_chart(fb2, use_container_width=True)
            if int((df.head(5)["authentic"]==0).sum())>=3:
                st.markdown(f'<div class="pulse">🚨 TREND ALERT: 3+ fakes in last 5 scans in {user_city}!</div>', unsafe_allow_html=True)
            disp2 = df[["scan_date","medicine","authentic","score","expiry_status","city"]].copy()
            disp2["authentic"] = disp2["authentic"].map({1:"✅ Genuine","0":"🚨 Fake",0:"🚨 Fake"})
            disp2["score"]     = disp2["score"].apply(lambda x: f"{x:.1f}%")
            disp2.columns      = ["Date","Medicine","Verdict","Score","Expiry","City"]
            st.dataframe(disp2, use_container_width=True, height=260)
            st.download_button("⬇️ Export CSV", df.to_csv(index=False), "pharmascan.csv", "text/csv")
        else:
            st.markdown('<div class="rc rc-info">No scans yet. Start scanning!</div>', unsafe_allow_html=True)

      else:
        # ── EXPERT: Bulk Scan Tool ────────────────────────────────
        st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">📦 Bulk Medicine Scan</p>', unsafe_allow_html=True)
        st.markdown('<div class="rc rc-info" style="padding:.7rem 1rem;font-size:.84rem">Upload multiple medicine images at once. Each is analysed instantly. Perfect for pharmacy stock audits or hospital ward rounds.</div>', unsafe_allow_html=True)

        bulk_files = st.file_uploader("Upload multiple medicine images", type=["jpg","jpeg","png","webp"],
                                       accept_multiple_files=True, key="bulk_upload")
        if bulk_files:
            st.markdown(f'<p style="color:{MUT};font-size:.84rem">{len(bulk_files)} image(s) selected. Click Scan All to analyse.</p>', unsafe_allow_html=True)
            if st.button("🔬 Scan All →", key="btn_bulk_scan", use_container_width=True):
                bulk_results = []
                prog = st.progress(0, text="Scanning...")
                for i, bf in enumerate(bulk_files):
                    prog.progress((i+1)/len(bulk_files), text=f"Scanning {bf.name}...")
                    try:
                        img_b = Image.open(bf); arr_b = np.array(img_b.convert("RGB"))
                        ocr_b = run_ocr(arr_b, ocr_langs)
                        sc_b, _, sh_b, co_b, ed_b = vision_analyze(arr_b)
                        ok_b  = sc_b >= conf_thresh
                        med_b = detect_med(ocr_b)
                        em_b, es_b, _ = parse_expiry(ocr_b)
                        sp_b  = check_spelling(ocr_b)
                        db_save_scan(username, med_b or "Unknown", ok_b, sc_b, es_b,
                                     ocr_b, sh_b, co_b, ed_b, user_city, user_lat, user_lon,
                                     ",".join([x["word"] for x in sp_b]))
                        if not ok_b and user_email and "@pharmascan.demo" not in user_email:
                            send_alert(user_email, med_b or "Unknown", sc_b, username)
                        bulk_results.append({
                            "File": bf.name, "Medicine": (med_b or "Unknown").title(),
                            "Verdict": "✅ Genuine" if ok_b else "🚨 Fake",
                            "Score": f"{sc_b:.1f}%",
                            "Expiry": em_b,
                            "Spelling Errors": len(sp_b),

                        })
                    except Exception as ex:
                        bulk_results.append({"File":bf.name,"Medicine":"Error","Verdict":"⚠️ Error","Score":"—","Expiry":"—","Spelling Errors":"—"})
                prog.empty()
                st.session_state["bulk_results"] = bulk_results

        if st.session_state.get("bulk_results"):
            br = st.session_state["bulk_results"]
            fakes_bulk = sum(1 for r in br if "Fake" in r["Verdict"])
            st.markdown(f'<div style="display:flex;gap:16px;margin:12px 0">'
                        f'<div class="mb" style="flex:1"><div class="mb-n" style="color:#a78bfa">{len(br)}</div><div class="mb-l">Scanned</div></div>'
                        f'<div class="mb" style="flex:1"><div class="mb-n" style="color:#ef4444">{fakes_bulk}</div><div class="mb-l">Fakes Found</div></div>'
                        f'<div class="mb" style="flex:1"><div class="mb-n" style="color:#10b981">{len(br)-fakes_bulk}</div><div class="mb-l">Genuine</div></div>'
                        f'</div>', unsafe_allow_html=True)
            df_bulk = pd.DataFrame(br)
            st.dataframe(df_bulk, use_container_width=True)
            st.download_button("⬇️ Download Bulk Scan Report (CSV)", df_bulk.to_csv(index=False),
                               f"bulk_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", "text/csv", use_container_width=True)

    # ══════════════════════════════════════════════
    # TAB 6 — ROLE SPLIT: User=Heatmap / Expert=Drug Database Editor
    # ══════════════════════════════════════════════
    with T6:
      if not is_expert:
        # ── USER: Heatmap ─────────────────────────────────────────
        HT1, HT2, HT3 = st.tabs(["🗺️ Fake Heatmap","🏥 Pharmacy Finder","🔮 Hotspot Predictor"])
        with HT1:
            st.markdown(f'<p style="color:{TXT};font-size:1.05rem;font-weight:700">🗺️ Nationwide Fake Medicine Heatmap</p>', unsafe_allow_html=True)
            df_hm = db_get_scans()
            if df_hm.empty or "lat" not in df_hm.columns or (df_hm["lat"]==0).all():
                st.markdown('<div class="rc rc-info" style="padding:.8rem 1rem;font-size:.84rem">Showing demo data — real scan locations will appear here</div>', unsafe_allow_html=True)
                df_hm = pd.DataFrame({"lat":[13.08,19.07,28.61,22.57,12.97,17.38,23.02,26.91],"lon":[80.27,72.87,77.20,88.36,77.59,78.47,72.57,75.78],"city":["Chennai","Mumbai","Delhi","Kolkata","Bengaluru","Hyderabad","Ahmedabad","Jaipur"],"authentic":[0,1,0,0,1,0,1,0],"medicine":["paracetamol","ibuprofen","amoxicillin","aspirin","cetirizine","metformin","omeprazole","paracetamol"],"score":[45,82,51,48,88,43,91,52]})
            mh = folium.Map(location=[20.5,79.0],zoom_start=5,tiles="cartodbdark_matter")
            for _, row_hm in df_hm.iterrows():
                if pd.notna(row_hm.get("lat")) and float(row_hm.get("lat",0))!=0:
                    fake_hm = row_hm.get("authentic",1)==0
                    popup_hm = f"<b style='color:{'#ef4444' if fake_hm else '#10b981'}'>{'FAKE' if fake_hm else 'GENUINE'}</b><br>{str(row_hm.get('medicine','?'))}<br>{row_hm.get('city','?')}"
                    folium.Marker([float(row_hm["lat"]),float(row_hm["lon"])],popup=folium.Popup(popup_hm,max_width=200),icon=folium.Icon(color="red" if fake_hm else "green",icon="exclamation-sign" if fake_hm else "ok",prefix="glyphicon")).add_to(mh)
            # Full height map
            st.markdown('<style>iframe{min-height:500px!important;height:60vh!important;}</style>', unsafe_allow_html=True)
            st_folium(mh, height=600, use_container_width=True, key="heatmap", returned_objects=[])

        with HT2:
            st.markdown(f'<p style="color:{TXT};font-size:1.05rem;font-weight:700">📍 Find Nearby Pharmacies</p>', unsafe_allow_html=True)

            # ── Location setter directly in this tab ──────────────────
            st.markdown(f'<div style="background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.3);border-radius:14px;padding:14px 16px;margin-bottom:12px">'
                        f'<p style="color:#a5b4fc;font-size:.82rem;font-weight:700;margin-bottom:10px">📍 Set Your Location</p>',
                        unsafe_allow_html=True)
            loc_col1, loc_col2 = st.columns(2)
            with loc_col1:
                user_lat = st.number_input("Latitude", value=user_lat, format="%.4f", key="map_lat")
            with loc_col2:
                user_lon = st.number_input("Longitude", value=user_lon, format="%.4f", key="map_lon")
            user_city = st.text_input("City name", value=user_city, key="map_city")
            st.markdown(
                '<p style="color:#64748b;font-size:.74rem;margin-top:4px">💡 Tip: Google your city name + "coordinates" to find your lat/lon</p>'
                '</div>', unsafe_allow_html=True)

            # Common Indian cities quick-select
            st.markdown(f'<p style="color:{MUT};font-size:.78rem;font-weight:700;margin-bottom:6px">🏙️ Quick select city:</p>', unsafe_allow_html=True)
            cities = {"Chennai":(13.0827,80.2707),"Mumbai":(19.0760,72.8777),"Delhi":(28.6139,77.2090),
                      "Bengaluru":(12.9716,77.5946),"Hyderabad":(17.3850,78.4867),
                      "Kolkata":(22.5726,88.3639),"Pune":(18.5204,73.8567),"Ahmedabad":(23.0225,72.5714)}
            city_cols = st.columns(4)
            for i,(cname,(clat,clon)) in enumerate(cities.items()):
                with city_cols[i%4]:
                    if st.button(cname, key=f"city_{cname}", use_container_width=True):
                        user_lat = clat; user_lon = clon; user_city = cname
                        st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("📍 Find Pharmacies Near Me", use_container_width=True, key="btn_find_pharm"):
                with st.spinner("Searching pharmacies..."):
                    pm = folium.Map(location=[user_lat,user_lon],zoom_start=14,tiles="cartodbdark_matter")
                    ph_count=0
                    try:
                        q_ov=f'[out:json];node["amenity"="pharmacy"](around:2000,{user_lat},{user_lon});out body;'
                        res_ov=requests.get("https://overpass-api.de/api/interpreter",data=q_ov,timeout=8)
                        ph_ov=res_ov.json().get("elements",[])
                        ph_count=len(ph_ov)
                        for p_ov in ph_ov:
                            folium.Marker([p_ov["lat"],p_ov["lon"]],popup=p_ov.get("tags",{}).get("name","Pharmacy"),icon=folium.Icon(color="red",icon="plus-sign")).add_to(pm)
                    except Exception: pass
                    folium.Marker([user_lat,user_lon],popup=f"📍 You ({user_city})",icon=folium.Icon(color="blue",icon="home")).add_to(pm)
                    st.session_state.pharmacy_map=pm; st.session_state.pharmacy_count=ph_count
            if st.session_state.get("pharmacy_map") is not None:
                n_ph=st.session_state.pharmacy_count
                if n_ph>0:
                    st.success(f"✅ Found {n_ph} pharmacies within 2km of {user_city}")
                else:
                    st.info("No pharmacies found nearby — try a different location")
                st_folium(st.session_state.pharmacy_map, height=500, use_container_width=True, key="pharmacy_map", returned_objects=[])
        with HT3:
            st.markdown(f'<p style="color:{TXT};font-size:1.05rem;font-weight:700">🔮 AI Hotspot Predictor</p>', unsafe_allow_html=True)
            st.markdown('<div class="rc rc-info" style="padding:.8rem 1rem;font-size:.84rem">📊 Statistical analysis of your scan data to predict the highest-risk zones</div>', unsafe_allow_html=True)
            if st.button("🔮 Generate AI Risk Prediction", use_container_width=True, key="btn_hotspot"):
                df_hs2=db_get_scans()
                if df_hs2.empty:
                    df_hs2=pd.DataFrame({"city":["Chennai","Mumbai","Delhi","Kolkata","Bengaluru","Hyderabad"],"authentic":[0,1,0,0,1,0],"medicine":["paracetamol","ibuprofen","amoxicillin","aspirin","cetirizine","metformin"],"score":[45,82,51,48,88,43]})
                with st.spinner("Analysing regional patterns..."):
                    prediction=predict_hotspots(df_hs2)
                if prediction: st.session_state["hotspot_prediction"]=prediction
            pred2=st.session_state.get("hotspot_prediction")
            if pred2:
                for line_p in pred2.strip().split("\n"):
                    if not line_p.strip(): continue
                    if line_p.startswith("🔴"): st.markdown(f'<div class="rc rc-bad" style="padding:.7rem 1.1rem;font-size:.9rem">{line_p}</div>', unsafe_allow_html=True)
                    elif line_p.startswith("💊"): st.markdown(f'<div class="rc rc-warn" style="padding:.7rem 1.1rem;font-size:.9rem">{line_p}</div>', unsafe_allow_html=True)
                    elif line_p.startswith("⚠️"): st.markdown(f'<div class="rc rc-warn" style="padding:.7rem 1.1rem;font-size:.9rem">{line_p}</div>', unsafe_allow_html=True)
                    elif line_p.startswith("-"): st.markdown(f'<div class="rc rc-info" style="padding:.55rem 1rem;font-size:.85rem">💡 {line_p[1:].strip()}</div>', unsafe_allow_html=True)

      else:
        # ── EXPERT: Drug Database & Reference ─────────────────────
        st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">🧬 Drug Reference Database</p>', unsafe_allow_html=True)
        st.markdown('<div class="rc rc-info" style="padding:.7rem 1rem;font-size:.84rem">Complete drug reference for all 8 medicines in the system. Search, compare, and lookup FDA / NIH data in real time.</div>', unsafe_allow_html=True)

        # Search
        db_search = st.text_input("🔍 Search medicine", placeholder="e.g. paracetamol", key="db_search_inp")
        meds_to_show = {k:v for k,v in MEDS.items() if not db_search or db_search.lower() in k}

        for med_k, med_v in meds_to_show.items():
            # ── Medicine header card (NO expander = no keyboard collision) ──
            cat_clr = {"Analgesic / Antipyretic":"#10b981","NSAID":"#f59e0b",
                       "Antibiotic (Penicillin)":"#ef4444","Antihistamine":"#60a5fa",
                       "Antidiabetic (Biguanide)":"#a78bfa",
                       "Proton Pump Inhibitor":"#f472b6","NSAID / Antiplatelet":"#fb923c"
                      }.get(med_v.get("cat",""), "#6366f1")

            st.markdown(
                f'<div style="background:linear-gradient(135deg,#1e293b,#0f172a);'
                f'border:1px solid {BDR};border-radius:18px;padding:0;'
                f'margin-bottom:14px;overflow:hidden;">' 

                # Header bar
                f'<div style="background:rgba(255,255,255,.04);padding:12px 18px;'
                f'border-bottom:1px solid {BDR};display:flex;align-items:center;gap:10px;flex-wrap:wrap">' 
                f'<span style="font-size:1.25rem">💊</span>'
                f'<span style="color:#e2e8f0;font-weight:800;font-size:1rem;font-family:Syne,sans-serif">{med_k.title()}</span>'
                f'<span style="background:{cat_clr}22;color:{cat_clr};border:1px solid {cat_clr}55;'
                f'border-radius:20px;padding:2px 10px;font-size:.72rem;font-weight:700;white-space:nowrap">{med_v.get("cat","")}</span>'
                f'</div>'

                # Body grid
                f'<div style="padding:14px 18px;display:grid;grid-template-columns:1fr 1fr;gap:10px;">' 

                f'<div style="background:rgba(99,102,241,.07);border-radius:12px;padding:10px 12px;">' 
                f'<div style="color:#64748b;font-size:.67rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">Use</div>' 
                f'<div style="color:#e2e8f0;font-size:.85rem;line-height:1.5;word-break:break-word">{med_v.get("use","N/A")}</div></div>'

                f'<div style="background:rgba(99,102,241,.07);border-radius:12px;padding:10px 12px;">' 
                f'<div style="color:#64748b;font-size:.67rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">Dosage</div>' 
                f'<div style="color:#e2e8f0;font-size:.85rem;line-height:1.5;word-break:break-word">{med_v.get("dosage","N/A")}</div></div>'

                f'<div style="background:rgba(245,158,11,.07);border-radius:12px;padding:10px 12px;">' 
                f'<div style="color:#64748b;font-size:.67rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">Side Effects</div>' 
                f'<div style="color:#fde68a;font-size:.84rem;line-height:1.5;word-break:break-word">{med_v.get("se","N/A")}</div></div>'

                f'<div style="background:rgba(239,68,68,.07);border-radius:12px;padding:10px 12px;">' 
                f'<div style="color:#64748b;font-size:.67rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">Warning</div>' 
                f'<div style="color:#fca5a5;font-size:.84rem;line-height:1.5;word-break:break-word">{med_v.get("warn","N/A")}</div></div>'

                f'<div style="background:rgba(16,185,129,.07);border-radius:12px;padding:10px 12px;">' 
                f'<div style="color:#64748b;font-size:.67rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">Colour · Shape</div>' 
                f'<div style="color:#e2e8f0;font-size:.84rem;line-height:1.5">{med_v.get("colour","N/A")} · {med_v.get("shape","N/A")}</div></div>'

                f'<div style="background:rgba(167,139,250,.07);border-radius:12px;padding:10px 12px;">' 
                f'<div style="color:#64748b;font-size:.67rem;font-weight:800;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">Interactions</div>' 
                f'<div style="color:#c4b5fd;font-size:.84rem;line-height:1.5;word-break:break-word">{", ".join(med_v.get("inter",[])) or "None listed"}</div></div>'

                f'</div>'  # end grid

                f'<div style="padding:0 18px 14px;display:flex;gap:8px;flex-wrap:wrap">' 
                f'<div style="background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);border-radius:10px;padding:6px 12px;font-size:.76rem;color:#6ee7b7;white-space:nowrap">'
                f'✅ Genuine: {med_v.get("genuine","N/A")}</div></div>'

                f'</div>',
                unsafe_allow_html=True)

            # FDA + NIH buttons below each card
            fa_col, ni_col = st.columns(2)
            with fa_col:
                if st.button(f"🏥 Live FDA — {med_k.title()}", key=f"fda_{med_k}", use_container_width=True):
                    with st.spinner("Fetching from FDA..."):
                        fda_live = fda_label(med_k)
                    if fda_live:
                        st.markdown(
                            f'<div class="rc rc-ok" style="padding:.65rem 1rem;font-size:.83rem;line-height:1.6">'
                            f'✅ <b>{fda_live["brand"]}</b> · {fda_live["mfr"]}<br>'
                            f'<span style="font-size:.78rem;opacity:.85">{fda_live["purpose"][:120]}</span>'
                            f'</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="rc rc-info" style="padding:.55rem 1rem;font-size:.82rem">ℹ️ Not found in FDA NDC database</div>', unsafe_allow_html=True)
            with ni_col:
                if st.button(f"🔗 NIH — {med_k.title()}", key=f"nih_{med_k}", use_container_width=True):
                    ints_k = med_v.get("inter",[])
                    if ints_k:
                        st.markdown(
                            f'<div class="rc rc-warn" style="padding:.65rem 1rem;font-size:.83rem;line-height:1.6">'
                            f'⚠️ Known interactions:<br><b>{", ".join(ints_k)}</b></div>',
                            unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="rc rc-ok" style="padding:.55rem 1rem;font-size:.82rem">✅ No major interactions</div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════
    # TAB 7 — ROLE SPLIT: User=Compare Meds / Expert=Analytics & Alerts
    # ══════════════════════════════════════════════
    with T7:
      if not is_expert:
        # ── USER: Medicine Comparison ─────────────────────────────
        st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">💊 Side-by-Side Medicine Comparison</p>', unsafe_allow_html=True)
        cmp1_c, cmp2_c = st.columns(2)
        with cmp1_c: sel1 = st.selectbox("Medicine 1", list(MEDS.keys()), key="cmp_m1")
        with cmp2_c: sel2 = st.selectbox("Medicine 2", list(MEDS.keys()), index=1, key="cmp_m2")
        if sel1 and sel2:
            d1_c, d2_c = MEDS[sel1], MEDS[sel2]
            rows_c = [("Category","cat"),("Use / Indication","use"),("Dosage","dosage"),("Side Effects","se"),("Warning","warn"),("Typical Colour","colour"),("Shape","shape"),("Genuine Signs","genuine"),("Interactions","inter")]
            for label_c, key_c in rows_c:
                v1_c = d1_c.get(key_c,"N/A"); v2_c = d2_c.get(key_c,"N/A")
                if isinstance(v1_c,list): v1_c=", ".join(v1_c) or "None"
                if isinstance(v2_c,list): v2_c=", ".join(v2_c) or "None"
                shared_c=""
                if key_c=="inter":
                    i1s={x.lower() for x in d1_c.get("inter",[])}; i2s={x.lower() for x in d2_c.get("inter",[])}
                    common_c=i1s&i2s
                    if common_c: shared_c=f'<div class="rc rc-bad" style="padding:4px 10px;font-size:.78rem;margin-top:4px">⚠️ Shared: {", ".join(common_c).title()}</div>'
                r1_c,r2_c,r3_c=st.columns([1,2,2])
                r1_c.markdown(f'<div style="color:{MUT};font-weight:700;font-size:.8rem;padding:8px 0">{label_c}</div>', unsafe_allow_html=True)
                r2_c.markdown(f'<div style="background:{CARD};border:1px solid {BDR};border-radius:10px;padding:8px 12px;font-size:.83rem;color:{TXT}"><strong style="color:#00f5a0">{sel1.title()}</strong><br>{v1_c}</div>', unsafe_allow_html=True)
                r3_c.markdown(f'<div style="background:{CARD};border:1px solid {BDR};border-radius:10px;padding:8px 12px;font-size:.83rem;color:{TXT}"><strong style="color:#a78bfa">{sel2.title()}</strong><br>{v2_c}</div>', unsafe_allow_html=True)
                if shared_c: st.markdown(shared_c, unsafe_allow_html=True)
                st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
            cats_r=["Side Effects","Interactions","Warning","Dosage","Allergy Risk"]
            def med_profile_fn(info):
                return [min(len(info.get("se","").split(","))*20,100),min(len(info.get("inter",[]))*20,100),80 if "do not" in info.get("warn","").lower() else 40,60 if "max" in info.get("dosage","").lower() else 30,80 if "allerg" in info.get("warn","").lower() else 20]
            FILL_MAP2={"#00f5a0":"rgba(0,245,160,0.15)","#a78bfa":"rgba(167,139,250,0.15)"}
            fig_r2=go.Figure()
            for name_r,vals_r,clr_r in [(sel1.title(),med_profile_fn(d1_c),"#00f5a0"),(sel2.title(),med_profile_fn(d2_c),"#a78bfa")]:
                fig_r2.add_trace(go.Scatterpolar(r=vals_r+[vals_r[0]],theta=cats_r+[cats_r[0]],fill="toself",name=name_r,line_color=clr_r,fillcolor=FILL_MAP2.get(clr_r,"rgba(99,102,241,0.15)")))
            fig_r2.update_layout(polar=dict(radialaxis=dict(visible=True,range=[0,100],tickfont=dict(color=MUT),gridcolor=BDR),angularaxis=dict(tickfont=dict(color=TXT,size=11))),showlegend=True,height=340,paper_bgcolor="rgba(0,0,0,0)",font_color=TXT,legend=dict(font=dict(color=TXT)))
            st.plotly_chart(fig_r2, use_container_width=True)

      else:
        # ── EXPERT: Analytics & Alert Centre ──────────────────────
        st.markdown(f'<p style="color:{TXT};font-size:1.1rem;font-weight:700">📊 Expert Analytics & Alert Centre</p>', unsafe_allow_html=True)
        df_exp = db_get_scans()

        # City-level heatmap
        st.markdown('<p class="sh">Regional Risk Dashboard</p>', unsafe_allow_html=True)
        if not df_exp.empty and "city" in df_exp.columns:
            city_grp = df_exp.groupby("city").agg(
                total=("id","count"),
                fakes=("authentic", lambda x: (x==0).sum()),
                avg_score=("score","mean")).reset_index()
            city_grp["fake_rate"] = (city_grp["fakes"]/city_grp["total"]*100).round(1)
            city_grp = city_grp.sort_values("fake_rate",ascending=False)
            fig_city = px.bar(city_grp, x="city", y="fake_rate", color="fake_rate",
                              color_continuous_scale=["#10b981","#f59e0b","#ef4444"],
                              title="Fake Rate % by City", labels={"fake_rate":"Fake Rate %","city":"City"})
            fig_city.update_layout(height=260,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(30,41,59,.3)",font_color=TXT,showlegend=False)
            st.plotly_chart(fig_city, use_container_width=True)
            st.dataframe(city_grp.rename(columns={"city":"City","total":"Total Scans","fakes":"Fakes","fake_rate":"Fake Rate %","avg_score":"Avg Score"}), use_container_width=True)

        st.markdown('<p class="sh">Medicine-Level Counterfeit Trend</p>', unsafe_allow_html=True)
        if not df_exp.empty and "medicine" in df_exp.columns:
            med_grp = df_exp.groupby("medicine").agg(
                total=("id","count"),
                fakes=("authentic", lambda x: (x==0).sum())).reset_index()
            med_grp["fake_pct"]=(med_grp["fakes"]/med_grp["total"]*100).round(1)
            med_grp=med_grp.sort_values("fake_pct",ascending=False)
            fig_med=px.bar(med_grp,x="medicine",y="fake_pct",color="fake_pct",
                           color_continuous_scale=["#10b981","#f59e0b","#ef4444"],
                           title="Counterfeit Rate by Medicine",labels={"fake_pct":"Fake %","medicine":"Medicine"})
            fig_med.update_layout(height=260,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(30,41,59,.3)",font_color=TXT,showlegend=False)
            st.plotly_chart(fig_med, use_container_width=True)

        # Send bulk alert
        st.markdown('<p class="sh">Manual Alert — Notify All Registered Patients</p>', unsafe_allow_html=True)
        st.markdown('<div class="rc rc-warn" style="padding:.7rem 1rem;font-size:.83rem">⚠️ Use only for urgent public health alerts about confirmed counterfeit medicines.</div>', unsafe_allow_html=True)
        alert_med_sel = st.selectbox("Medicine to Alert About", list(MEDS.keys()), key="alert_med_sel")
        alert_msg = st.text_area("Alert Message", placeholder="e.g. Counterfeit paracetamol with blurry label detected in Chennai. Do NOT consume.", key="alert_msg", height=80)
        if st.button("📢 Send Public Alert Email", key="btn_pub_alert", use_container_width=True):
            if not alert_msg.strip():
                st.error("Please write an alert message first.")
            else:
                # Get all unique user emails from DB
                conn_a=sqlite3.connect(DB_PATH)
                emails_a=conn_a.execute("SELECT DISTINCT email FROM users WHERE email NOT LIKE '%@pharmascan.demo'").fetchall()
                conn_a.close()
                sent_c=0
                for em_row in emails_a:
                    if em_row[0] and "@" in em_row[0]:
                        try:
                            send_alert(em_row[0], alert_med_sel, 0.0, f"Expert Alert by {username}")
                            sent_c+=1
                        except Exception: pass
                st.success(f"✅ Alert sent to {sent_c} registered user(s).")

        # WHO / regulatory links
        st.markdown('<p class="sh">Regulatory Quick Links</p>', unsafe_allow_html=True)
        for name_l, url_l, desc_l in [
            ("CDSCO India","https://cdsco.gov.in","Report fake drugs to Central Drugs Standard Control Organisation"),
            ("FDA MedWatch","https://www.fda.gov/safety/medwatch","US FDA adverse event & counterfeit reporting"),
            ("WHO Rapid Alert","https://www.who.int/medicines/publications/drugalerts/en/","WHO global drug alert system"),
            ("PharmaScan PDF Report","#","Download your scan report above in Vision Scanner tab"),
        ]:
            st.markdown(f'<div style="background:{CARD};border:1px solid {BDR};border-radius:12px;padding:10px 14px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center">'
                        f'<div><div style="color:{TXT};font-weight:700;font-size:.88rem">{name_l}</div><div style="color:{MUT};font-size:.76rem;margin-top:2px">{desc_l}</div></div>'
                        f'<a href="{url_l}" target="_blank" style="background:rgba(99,102,241,.2);border:1px solid #6366f1;border-radius:8px;padding:4px 12px;color:#a5b4fc;font-size:.78rem;font-weight:700;text-decoration:none">Open →</a>'
                        f'</div>', unsafe_allow_html=True)


    # Footer
    st.markdown(
        f'<div class="footer">'
        f'<div style="font-size:1.5rem;font-weight:800;font-family:Syne,sans-serif;'
        f'background:linear-gradient(90deg,#00f5a0,#00d9f5,#a78bfa,#f472b6);'
        f'-webkit-background-clip:text;-webkit-text-fill-color:transparent">'
        f'🛡️ PharmaScan AI</div>'
        f'<p style="color:{MUT};font-size:0.78rem;margin:6px 0 0">'
        f'Vision-Based Fake Medicine Detection · Hackathon Edition<br>'
        f'Computer Vision · OCR · Spell Check · PDF · Auto-Email · Heatmap · FDA · NIH · Med Comparison · Safety Certificate · Hotspot Predictor</p>'
        f'<p style="color:#374151;font-size:0.7rem;margin-top:6px">'
        f'For informational purposes only. Always consult a licensed healthcare professional.</p>'
        f'</div>', unsafe_allow_html=True)



# ═══════════════════════════════════════════════════════════════════
#   ADMIN DASHBOARD  — pharmascanai26@gmail.com only
# ═══════════════════════════════════════════════════════════════════
def show_admin_dashboard():
    """Full system dashboard visible ONLY to the superadmin account."""
    DK = st.session_state.get("dark_mode", True)
    BG   = "#0a0f1e" if DK else "#f1f5f9"
    CARD = "#111827" if DK else "#ffffff"
    TXT  = "#e2e8f0" if DK else "#0f172a"
    MUT  = "#64748b"
    BDR  = "#1e293b" if DK else "#e2e8f0"
    ACC  = "#6366f1"

    st.markdown(f"""
    <style>
    .stApp {{background:{BG}!important}}
    .adm-hdr {{
        background:linear-gradient(135deg,#0d1b44,#1a0a2e,#0a1428);
        border-bottom:2px solid rgba(99,102,241,.4);
        padding:20px 28px; margin-bottom:20px;
        display:flex; justify-content:space-between; align-items:center;
    }}
    .adm-title {{
        font-family:'Syne',sans-serif!important;
        font-size:1.6rem; font-weight:800;
        background:linear-gradient(90deg,#00f5a0,#a78bfa,#f472b6);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent;
    }}
    .adm-badge {{
        background:rgba(239,68,68,.2); border:1px solid #ef4444;
        border-radius:20px; padding:4px 14px;
        color:#fca5a5; font-size:.78rem; font-weight:700;
    }}
    .kpi {{
        background:{CARD}; border:1px solid {BDR};
        border-radius:16px; padding:18px 16px; text-align:center;
    }}
    .kpi-n {{font-size:1.8rem; font-weight:800; font-family:'Syne',sans-serif!important}}
    .kpi-l {{font-size:.66rem; color:{MUT}; font-weight:700;
              text-transform:uppercase; letter-spacing:1px; margin-top:4px}}
    .adm-section {{
        background:{CARD}; border:1px solid {BDR};
        border-radius:16px; padding:18px 20px; margin-bottom:16px;
    }}
    .adm-sec-title {{
        font-size:.72rem; font-weight:800; color:{MUT};
        letter-spacing:1.5px; text-transform:uppercase; margin-bottom:12px;
    }}
    .login-row {{
        display:flex; justify-content:space-between; align-items:center;
        padding:8px 0; border-bottom:1px solid rgba(255,255,255,.05);
        font-size:.82rem;
    }}
    .login-row:last-child {{border-bottom:none}}
    .ev-LOGIN    {{color:#00f5a0; font-weight:700}}
    .ev-ADMIN_LOGIN  {{color:#f472b6; font-weight:700}}
    .ev-REGISTERED   {{color:#60a5fa; font-weight:700}}
    .ev-ACCOUNT_DELETED {{color:#ef4444; font-weight:700}}
    </style>
    """, unsafe_allow_html=True)

    # ── Header ───────────────────────────────────────────────────────
    st.markdown(
        '<div class="adm-hdr">'
        '<div class="adm-title">🛡️ PharmaScan AI — Admin Dashboard</div>'
        '<span class="adm-badge">🔐 SUPERADMIN</span>'
        '</div>', unsafe_allow_html=True)

    # ── Logout ───────────────────────────────────────────────────────
    col_lo, _ = st.columns([1, 5])
    with col_lo:
        if st.button("🚪 Logout", key="admin_logout", use_container_width=True):
            _clear_session()
            for k in list(DEFAULTS.keys()):
                st.session_state[k] = DEFAULTS[k]
            st.rerun()

    # ── Load all data ────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    try:
        df_users  = pd.read_sql("SELECT * FROM users ORDER BY id DESC", conn)
        df_scans  = pd.read_sql("SELECT * FROM scans ORDER BY id DESC", conn)
        df_chats  = pd.read_sql("SELECT * FROM chats ORDER BY id DESC", conn)
        df_qa_q   = pd.read_sql("SELECT * FROM qa_questions ORDER BY id DESC", conn)
        df_qa_a   = pd.read_sql("SELECT * FROM qa_answers ORDER BY id DESC", conn)
    except Exception:
        df_users = df_scans = df_chats = df_qa_q = df_qa_a = pd.DataFrame()
    conn.close()

    # Load login activity CSV
    try:
        _ensure_csv(CSV_LOGINS, _CSV_LOGINS_COLS)
        df_logins = pd.read_csv(CSV_LOGINS)
    except Exception:
        df_logins = pd.DataFrame(columns=_CSV_LOGINS_COLS)

    total_users  = len(df_users)
    total_scans  = len(df_scans)
    total_fakes  = int((df_scans["authentic"] == 0).sum()) if not df_scans.empty else 0
    total_logins = len(df_logins[df_logins["event"].isin(["LOGIN","ADMIN_LOGIN"])]) if not df_logins.empty else 0

    # ── KPI row ──────────────────────────────────────────────────────
    k1,k2,k3,k4,k5 = st.columns(5)
    for col, num, lbl, clr in [
        (k1, total_users,               "Registered Users",  "#a78bfa"),
        (k2, total_scans,               "Total Scans",       "#00f5a0"),
        (k3, total_fakes,               "Fakes Detected",    "#ef4444"),
        (k4, total_scans - total_fakes, "Genuine",           "#10b981"),
        (k5, total_logins,              "Login Events",      "#60a5fa"),
    ]:
        col.markdown(
            f'<div class="kpi">'
            f'<div class="kpi-n" style="color:{clr}">{num}</div>'
            f'<div class="kpi-l">{lbl}</div>'
            f'</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────
    A1,A2,A3,A4,A5,A6,A7 = st.tabs([
        "👥 All Users",
        "📋 Login History",
        "🔬 All Scans",
        "💬 Q&A Forum",
        "📊 Analytics",
        "📁 CSV Files",
        "⚙️ System",
    ])

    # ═══ TAB 1 — ALL USERS ══════════════════════════════════════════
    with A1:
        st.markdown('<div class="adm-section">', unsafe_allow_html=True)
        st.markdown('<div class="adm-sec-title">👥 Registered Users</div>', unsafe_allow_html=True)
        if not df_users.empty:
            # Hide password hash for display
            disp_u = df_users.copy()
            disp_u["password_hash"] = "••••••••"
            disp_u["id_verified"]   = disp_u["id_verified"].map({1:"✅ Yes", 0:"⏳ No"})
            st.dataframe(disp_u, use_container_width=True, height=350)
            # Counts
            experts = int((df_users["role"] == "expert").sum())
            users   = int((df_users["role"] != "expert").sum())
            c1,c2,c3 = st.columns(3)
            c1.metric("Total Users", total_users)
            c2.metric("Experts / Pharmacists", experts)
            c3.metric("Patients / Users", users)
            # Download
            dl_u = df_users.copy(); dl_u["password_hash"] = "REDACTED"
            st.download_button(
                "⬇️ Export Users CSV (passwords redacted)",
                dl_u.to_csv(index=False), "admin_users.csv", "text/csv",
                use_container_width=True)
        else:
            st.info("No registered users yet.")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ TAB 2 — LOGIN HISTORY ══════════════════════════════════════
    with A2:
        st.markdown('<div class="adm-section">', unsafe_allow_html=True)
        st.markdown('<div class="adm-sec-title">📋 Complete Login Activity Log</div>', unsafe_allow_html=True)

        if not df_logins.empty:
            # Filter controls
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                ev_opts = ["All"] + sorted(df_logins["event"].dropna().unique().tolist())
                ev_filter = st.selectbox("Filter by Event", ev_opts, key="adm_ev_filter")
            with fc2:
                usr_opts = ["All"] + sorted(df_logins["username"].dropna().unique().tolist())
                usr_filter = st.selectbox("Filter by User", usr_opts, key="adm_usr_filter")
            with fc3:
                role_opts = ["All"] + sorted(df_logins["role"].dropna().unique().tolist())
                role_filter = st.selectbox("Filter by Role", role_opts, key="adm_role_filter")

            df_log_disp = df_logins.copy()
            if ev_filter != "All":
                df_log_disp = df_log_disp[df_log_disp["event"] == ev_filter]
            if usr_filter != "All":
                df_log_disp = df_log_disp[df_log_disp["username"] == usr_filter]
            if role_filter != "All":
                df_log_disp = df_log_disp[df_log_disp["role"] == role_filter]

            df_log_disp = df_log_disp.sort_values("timestamp", ascending=False)

            # Colour-coded cards for latest 50
            st.markdown(f'<p style="color:{MUT};font-size:.76rem;margin-bottom:8px">'
                        f'Showing {min(50, len(df_log_disp))} of {len(df_log_disp)} events</p>',
                        unsafe_allow_html=True)
            for _, row in df_log_disp.head(50).iterrows():
                ev   = str(row.get("event",""))
                ev_cls = {
                    "LOGIN":          "ev-LOGIN",
                    "ADMIN_LOGIN":    "ev-ADMIN_LOGIN",
                    "REGISTERED":     "ev-REGISTERED",
                    "ACCOUNT_DELETED":"ev-ACCOUNT_DELETED",
                }.get(ev, "ev-LOGIN")
                ev_ico = {
                    "LOGIN":           "🟢",
                    "ADMIN_LOGIN":     "🔑",
                    "REGISTERED":      "🆕",
                    "ACCOUNT_DELETED": "🗑️",
                }.get(ev, "⚪")
                st.markdown(
                    f'<div class="login-row">'
                    f'<span style="color:{MUT};font-size:.75rem;width:155px;flex-shrink:0">{row.get("timestamp","")}</span>'
                    f'<span style="color:{TXT};font-weight:600;width:160px">{row.get("username","")}</span>'
                    f'<span style="color:{MUT};width:200px;font-size:.8rem">{row.get("email","")}</span>'
                    f'<span style="color:{MUT};width:80px;font-size:.78rem">{row.get("role","")}</span>'
                    f'<span class="{ev_cls}">{ev_ico} {ev}</span>'
                    f'</div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            # Summary stats
            lc1,lc2,lc3,lc4 = st.columns(4)
            lc1.metric("Total Events",     len(df_logins))
            lc2.metric("Unique Users",     df_logins["username"].nunique())
            lc3.metric("Login Events",     int((df_logins["event"]=="LOGIN").sum()))
            lc4.metric("Registrations",    int((df_logins["event"]=="REGISTERED").sum()))

            st.download_button(
                "⬇️ Export Full Login History CSV",
                df_logins.to_csv(index=False),
                f"login_history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv", use_container_width=True)
        else:
            st.info("No login activity recorded yet.")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ TAB 3 — ALL SCANS ══════════════════════════════════════════
    with A3:
        st.markdown('<div class="adm-section">', unsafe_allow_html=True)
        st.markdown('<div class="adm-sec-title">🔬 All Scan Records</div>', unsafe_allow_html=True)
        if not df_scans.empty:
            # Filters
            sf1, sf2 = st.columns(2)
            with sf1:
                s_usr = st.selectbox("Filter by User", ["All"] + sorted(df_scans["username"].dropna().unique().tolist()), key="adm_scan_usr")
            with sf2:
                s_ver = st.selectbox("Filter by Verdict", ["All", "✅ Genuine", "🚨 Fake"], key="adm_scan_ver")
            df_sc_disp = df_scans.copy()
            if s_usr != "All":
                df_sc_disp = df_sc_disp[df_sc_disp["username"] == s_usr]
            if s_ver == "✅ Genuine":
                df_sc_disp = df_sc_disp[df_sc_disp["authentic"] == 1]
            elif s_ver == "🚨 Fake":
                df_sc_disp = df_sc_disp[df_sc_disp["authentic"] == 0]
            df_sc_disp["authentic"] = df_sc_disp["authentic"].map({1:"✅ Genuine", 0:"🚨 Fake"})
            df_sc_disp["score"] = df_sc_disp["score"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(df_sc_disp[["scan_date","username","medicine","authentic","score",
                                      "expiry_status","city","spell_errors"]],
                         use_container_width=True, height=320)
            st.download_button(
                "⬇️ Export All Scans CSV",
                df_scans.to_csv(index=False),
                f"all_scans_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv", use_container_width=True)
        else:
            st.info("No scans recorded yet.")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ TAB 4 — Q&A FORUM ══════════════════════════════════════════
    with A4:
        st.markdown('<div class="adm-section">', unsafe_allow_html=True)
        st.markdown('<div class="adm-sec-title">💬 Q&A Forum — All Questions & Answers</div>', unsafe_allow_html=True)
        if not df_qa_q.empty:
            st.markdown(f'**{len(df_qa_q)} questions** · **{len(df_qa_a)} answers**')
            st.dataframe(df_qa_q, use_container_width=True, height=260)
            if not df_qa_a.empty:
                st.markdown("**Answers:**")
                st.dataframe(df_qa_a, use_container_width=True, height=200)
            st.download_button("⬇️ Export Q&A CSV",
                               df_qa_q.to_csv(index=False), "admin_qa.csv", "text/csv")
        else:
            st.info("No Q&A posts yet.")
        if not df_chats.empty:
            st.markdown("**Chat History:**")
            st.dataframe(df_chats, use_container_width=True, height=200)
            st.download_button("⬇️ Export Chat History CSV",
                               df_chats.to_csv(index=False), "admin_chats.csv", "text/csv")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ TAB 5 — ANALYTICS ══════════════════════════════════════════
    with A5:
        st.markdown('<div class="adm-sec-title">📊 System-wide Analytics</div>', unsafe_allow_html=True)
        if not df_scans.empty:
            # Fake rate over time
            df_t = df_scans.copy()
            df_t["scan_date"] = pd.to_datetime(df_t["scan_date"], errors="coerce")
            df_t["day"] = df_t["scan_date"].dt.date
            daily = df_t.groupby("day").agg(
                total=("id","count"),
                fakes=("authentic", lambda x: (x==0).sum())
            ).reset_index()
            daily["fake_rate"] = (daily["fakes"]/daily["total"]*100).round(1)

            fig_t = px.line(daily, x="day", y="fake_rate",
                            title="Daily Fake Rate % (All Users)",
                            markers=True, color_discrete_sequence=["#ef4444"])
            fig_t.update_layout(height=240, paper_bgcolor="rgba(0,0,0,0)",
                                plot_bgcolor="rgba(30,41,59,.3)",
                                font_color=TXT)
            st.plotly_chart(fig_t, use_container_width=True)

            # Scans per user
            sc_by_usr = df_scans.groupby("username").agg(
                total=("id","count"),
                fakes=("authentic", lambda x:(x==0).sum())
            ).reset_index().sort_values("total", ascending=False)
            fig_u = px.bar(sc_by_usr, x="username", y="total", color="fakes",
                           color_continuous_scale=["#10b981","#ef4444"],
                           title="Scans per User (coloured by Fakes)",
                           labels={"total":"Scans","username":"User"})
            fig_u.update_layout(height=260, paper_bgcolor="rgba(0,0,0,0)",
                                plot_bgcolor="rgba(30,41,59,.3)",
                                font_color=TXT, showlegend=False)
            st.plotly_chart(fig_u, use_container_width=True)

            # Medicine fake breakdown
            if not df_scans[df_scans["authentic"]==0].empty:
                med_f = df_scans[df_scans["authentic"]==0]["medicine"].value_counts().head(8)
                fig_m = px.pie(names=med_f.index, values=med_f.values,
                               title="Most Counterfeited Medicines",
                               color_discrete_sequence=px.colors.sequential.Reds_r)
                fig_m.update_layout(height=280, paper_bgcolor="rgba(0,0,0,0)",
                                    font_color=TXT)
                st.plotly_chart(fig_m, use_container_width=True)

            # City heatmap
            if "city" in df_scans.columns:
                city_g = df_scans.groupby("city").agg(
                    total=("id","count"),
                    fakes=("authentic", lambda x:(x==0).sum())
                ).reset_index()
                city_g["fake_rate"] = (city_g["fakes"]/city_g["total"]*100).round(1)
                fig_c = px.bar(city_g.sort_values("fake_rate",ascending=False),
                               x="city", y="fake_rate", color="fake_rate",
                               color_continuous_scale=["#10b981","#f59e0b","#ef4444"],
                               title="Fake Rate % by City")
                fig_c.update_layout(height=250, paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(30,41,59,.3)",
                                    font_color=TXT, showlegend=False)
                st.plotly_chart(fig_c, use_container_width=True)
        else:
            st.info("No scan data yet.")

        # Login event breakdown chart
        if not df_logins.empty:
            ev_counts = df_logins["event"].value_counts().reset_index()
            ev_counts.columns = ["Event","Count"]
            fig_ev = px.bar(ev_counts, x="Event", y="Count",
                            color="Count",
                            color_continuous_scale=["#6366f1","#a78bfa"],
                            title="Login Activity Breakdown")
            fig_ev.update_layout(height=220, paper_bgcolor="rgba(0,0,0,0)",
                                 plot_bgcolor="rgba(30,41,59,.3)",
                                 font_color=TXT, showlegend=False)
            st.plotly_chart(fig_ev, use_container_width=True)

    # ═══ TAB 6 — CSV FILES ══════════════════════════════════════════
    with A6:
        st.markdown('<div class="adm-section">', unsafe_allow_html=True)
        st.markdown('<div class="adm-sec-title">📁 Live CSV Data Files</div>', unsafe_allow_html=True)
        st.markdown(f"""
<div style="background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.3);
border-radius:12px;padding:12px 16px;font-size:.82rem;color:#94a3b8;line-height:1.8;margin-bottom:16px">
📂 All data files are stored in the <code style="color:#a5b4fc">pharmascan_data/</code> folder<br>
&nbsp;&nbsp;• <code>users.csv</code> — all registered user accounts<br>
&nbsp;&nbsp;• <code>scans.csv</code> — all scan records<br>
&nbsp;&nbsp;• <code>login_activity.csv</code> — complete login/register/delete log
</div>""", unsafe_allow_html=True)

        if st.button("🔄 Sync all CSVs from DB now", use_container_width=True, key="adm_sync"):
            _csv_sync_from_db()
            st.success("✅ CSVs synced from database.")

        # Download latest versions
        dl1, dl2, dl3 = st.columns(3)
        with dl1:
            if not df_users.empty:
                dl_safe = df_users.copy(); dl_safe["password_hash"] = "REDACTED"
                st.download_button("⬇️ users.csv", dl_safe.to_csv(index=False),
                                   "users.csv", "text/csv", use_container_width=True)
        with dl2:
            if not df_scans.empty:
                st.download_button("⬇️ scans.csv", df_scans.to_csv(index=False),
                                   "scans.csv", "text/csv", use_container_width=True)
        with dl3:
            if not df_logins.empty:
                st.download_button("⬇️ login_activity.csv",
                                   df_logins.to_csv(index=False),
                                   "login_activity.csv", "text/csv",
                                   use_container_width=True)

        # Preview each CSV inline
        for label, df_prev in [("users.csv (passwords redacted)", df_users),
                                ("scans.csv", df_scans),
                                ("login_activity.csv", df_logins)]:
            with st.expander(f"📄 Preview {label}"):
                if not df_prev.empty:
                    if "password_hash" in df_prev.columns:
                        dp = df_prev.copy(); dp["password_hash"] = "••••••"
                    else:
                        dp = df_prev
                    st.dataframe(dp.head(50), use_container_width=True)
                else:
                    st.info("Empty")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ TAB 7 — SYSTEM INFO ════════════════════════════════════════
    with A7:
        st.markdown('<div class="adm-section">', unsafe_allow_html=True)
        st.markdown('<div class="adm-sec-title">⚙️ System Info</div>', unsafe_allow_html=True)
        import os as _sys_os
        db_size = _sys_os.path.getsize(DB_PATH) if _sys_os.path.exists(DB_PATH) else 0
        st.markdown(f"""
<div style="font-size:.85rem;color:{TXT};line-height:2">
<b style="color:{MUT}">Admin Email</b> &nbsp; {ADMIN_EMAIL}<br>
<b style="color:{MUT}">DB Path</b> &nbsp; <code>{_sys_os.path.abspath(DB_PATH)}</code><br>
<b style="color:{MUT}">DB Size</b> &nbsp; {db_size/1024:.1f} KB<br>
<b style="color:{MUT}">Data Dir</b> &nbsp; <code>{_sys_os.path.abspath(DATA_DIR)}</code><br>
<b style="color:{MUT}">Accounts Dir</b> &nbsp; <code>{_sys_os.path.abspath(ACCOUNTS_DIR)}</code><br>
<b style="color:{MUT}">Total Users</b> &nbsp; {total_users}<br>
<b style="color:{MUT}">Total Scans</b> &nbsp; {total_scans}<br>
<b style="color:{MUT}">Total Fakes</b> &nbsp; {total_fakes}<br>
<b style="color:{MUT}">Login Events</b> &nbsp; {len(df_logins)}<br>
<b style="color:{MUT}">Server Time</b> &nbsp; {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
</div>
""", unsafe_allow_html=True)

        # Danger zone — delete a user
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="adm-sec-title" style="color:#ef4444">⚠️ ADMIN DANGER ZONE</div>',
                    unsafe_allow_html=True)
        if not df_users.empty:
            del_usr = st.selectbox("Select user to delete from DB",
                                   ["— select —"] + df_users["username"].tolist(),
                                   key="adm_del_usr")
            if del_usr != "— select —":
                if st.button(f"🗑️ Permanently delete user: {del_usr}",
                             key="adm_del_btn", type="primary"):
                    try:
                        cd = sqlite3.connect(DB_PATH)
                        for tbl, col in [("users","username"),("scans","username"),
                                         ("chats","username"),("qa_questions","username"),
                                         ("qa_answers","expert_username")]:
                            cd.execute(f"DELETE FROM {tbl} WHERE {col}=?", (del_usr,))
                        cd.commit(); cd.close()
                        _csv_sync_from_db()
                        _csv_append_login(del_usr, "", "", "ADMIN_DELETED_USER")
                        st.success(f"✅ User '{del_usr}' and all their data deleted.")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Error: {ex}")
        st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────

# Inject viewport meta tag for proper mobile scaling
st.markdown("""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<style>
/* Global mobile fix: prevent horizontal overflow */
html, body { overflow-x: hidden !important; }
.block-container { overflow-x: hidden !important; }
/* Ensure all images/iframes don't overflow */
img, iframe, video { max-width: 100% !important; height: auto !important; }
/* Streamlit default container max-width on mobile */
@media (max-width: 768px) {
  .block-container { padding-left: 0.75rem !important; padding-right: 0.75rem !important; }
  /* collapse sidebar by default, show as overlay */
  section[data-testid="stSidebar"] { transform: translateX(-100%); transition: transform 0.3s; }
  section[data-testid="stSidebar"][aria-expanded="true"] { transform: translateX(0); }
}
</style>
""", unsafe_allow_html=True)

if not st.session_state.logged_in:
    show_login()
elif st.session_state.get("user_role") == "admin":
    show_admin_dashboard()
else:
    show_app()
