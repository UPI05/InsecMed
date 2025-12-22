import os
import time
import uuid
import sqlite3
from datetime import datetime
from typing import Optional
from passlib.context import CryptContext
from fastapi import (
    FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, status
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from celery import Celery
import requests
import logging

# --- CONFIG ---

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "inseclab"
DB_FILE = "insecmed.db"
UPLOAD_FOLDER = "static/uploads"
PROFILE_PIC_FOLDER = "static/profile_pics"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'nrrd', 'hdr', 'img', 'nii', 'gz', 'dcm'}

WEB_SERVER_HOST = 'http://10.102.196.113'
AI_SERVER_HOST = 'http://10.102.196.113:8080'
IMG_SERVER_HOST = 'http://10.102.196.113:8000'
EXPLAIN_SERVER_HOST = "http://10.102.196.101:8000/explain"

# --- App & templates ---
app = FastAPI(title="InsecMed (FastAPI port)", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Simple security headers middleware (mimic Talisman basics)
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # Not forcing HTTPS for dev; set HSTS only if desired
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # basic CSP example - allow same origin frames blocked
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return response
    
#app.add_middleware(SecurityHeadersMiddleware)

# --- Celery config ---
celery = Celery(
    "insecmed",
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

# --- DB helpers ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  full_name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  phone TEXT,
                  profile_pic TEXT,
                  role TEXT,
                  password_hash TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS diagnoses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  patient_id INTEGER,
                  model TEXT,
                  image_filename TEXT,
                  explain_image_filename TEXT,
                  prediction TEXT,
                  probability REAL,
                  share_to TEXT,
                  accept_share INTEGER,
                  sharer INTEGER,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS qa_interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  model TEXT,
                  patient_id INTEGER,
                  image_filename TEXT,
                  question TEXT,
                  answer TEXT,
                  share_to TEXT,
                  accept_share INTEGER,
                  sharer INTEGER,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            creator_id INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def get_db_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_notifications(request: Request):
    session_data = request.session
    if not session_data or "user_id" not in session_data:
        return []

    conn = get_db_conn()
    users = conn.execute("SELECT id, full_name FROM users").fetchall()
    users_map = {row["id"]: row["full_name"] for row in users}
    user_row = conn.execute(
        "SELECT email FROM users WHERE id = ?",
        (session_data.get("user_id"),)
    ).fetchone()
    if not user_row:
        conn.close()
        return []

    user_email = user_row["email"]
    rows = conn.execute("""
        SELECT id, user_id, timestamp, 0 AS type
        FROM diagnoses
        WHERE share_to=? AND (accept_share IS NULL OR accept_share = 0)
        UNION ALL
        SELECT id, user_id, timestamp, 1 AS type
        FROM qa_interactions
        WHERE share_to=? AND (accept_share IS NULL OR accept_share = 0)
        ORDER BY timestamp DESC
    """, (user_email, user_email)).fetchall()
    conn.close()

    notifications = [dict(row) for row in rows]
    for n in notifications:
        n["user_id"] = users_map.get(n["user_id"], "Unknown")
    return notifications

init_db()

# --- Utilities ---
def allowed_ext(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def get_client_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# --- Rate limit placeholder decorator (no-op) ---
def rate_limit(limit_str: str):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# --- Celery tasks ---
@celery.task(bind=True, queue='pipeline_a')
def call_diagnosis_from_ai_server(self, filename, patient_id, model_name, user_id):
    files = {'file': open(os.path.join(UPLOAD_FOLDER, filename), 'rb')}
    data = {'model': model_name}
    resp = requests.post(f"{AI_SERVER_HOST}/diagnose", data=data, files=files)
    results = resp.json()

    labels = ""
    for i in range(len(model_name.split(','))):
        labels += results['results'][i]['top_label'] + "/"


    explain_filenames = ""

    for idx, m in enumerate(model_name.split(',')):
        input_file = open(os.path.join(UPLOAD_FOLDER, filename), 'rb')
        # Explain Multipart form-data
        explain_model_name = ""

        if 'skin' in m:
            explain_model_name = "Anwarkh1/Skin_Cancer-Image_Classification"

        elif 'breast' in m:
            explain_model_name = "Falah/vit-base-breast-cancer"

        elif 'brain' in m:
            explain_model_name = "DunnBC22/vit-base-patch16-224-in21k_brain_tumor_diagnosis"

        elif 'pneu' in m:
            explain_model_name = "xyuan/vit-xray-pneumonia-classification"

        else:
            explain_model_name = "DunnBC22/vit-base-patch16-224-in21k_covid_19_ct_scans"

        files = {
            "model_kind": (None, explain_model_name),
            "prediction": (None, results["results"][idx]["top_label_origin"]),
            "image": (filename, input_file, "image/png")
        }
        explain_filenames += "explain_"+str(idx)+"_"+filename + ","

        # response = requests.post(EXPLAIN_SERVER_HOST, files=files)
        # if response.content:
        #     with open(os.path.join(UPLOAD_FOLDER, "explain_"+str(idx)+"_"+filename), "wb") as f:
        #         f.write(response.content)

    conn = get_db_conn()
    cur = conn.execute(
        "INSERT INTO diagnoses (user_id, patient_id, model, image_filename, explain_image_filename, prediction, probability, timestamp) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, patient_id, model_name, filename, explain_filenames, labels, results['results'][0]['top_score'], datetime.now())
    )
    diag_id = cur.lastrowid
    results["diagnosis_id"] = diag_id
    results["explain_image_filenames"] = explain_filenames
    conn.commit()
    conn.close()

    return results

@celery.task(bind=True, queue='pipeline_b')
def call_vision_qa_from_ai_server(self, filename, question, patient_id, model_name, user_id):
    files = {'file': open(os.path.join(UPLOAD_FOLDER, filename), 'rb')}
    data = {'question': question, 'model': model_name}
    resp = requests.post(f"{AI_SERVER_HOST}/vqa-diagnose", data=data, files=files)
    results = resp.json()

    conn = get_db_conn()
    cur = conn.execute(
        "INSERT INTO qa_interactions (user_id, patient_id, model, image_filename, question, answer, timestamp) VALUES (?,?,?,?,?,?,?)",
        (user_id, patient_id, model_name, filename, question, results['answer'], datetime.now())
    )
    diag_id = cur.lastrowid
    results["diagnosis_id"] = diag_id
    conn.commit()
    conn.close()

    return results

# Helper to include notifications easily
def template_context(request: Request, notifications=None, **kwargs):
    ctx = {
        "request": request,
        "notifications": notifications or []  # lấy từ dependency
    }
    ctx.update(kwargs)
    return ctx

# --- Authentication helpers ---
def require_login(request: Request):
    if 'user_id' not in request.session:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return request.session['user_id']

# flash message helpers (store in session)
def flash(request: Request, message: str, category: str = "info"):
    flashes = request.session.get("_flashes", [])
    flashes.append({"msg": message, "cat": category})
    request.session["_flashes"] = flashes

def get_flashes(request: Request):
    flashes = request.session.pop("_flashes", [])
    return flashes

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if 'user_id' in request.session:
        return RedirectResponse(url="/diagnose")
    return templates.TemplateResponse("login.html", template_context(request, flashes=get_flashes(request)))

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("terms.html", template_context(request))

@app.get("/ping")
#@rate_limit("5/minute")
async def ping():
    return {"msg": "pong"}

# ---------------- Register / Login / Logout ----------------
@app.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse("register.html", template_context(request, flashes=get_flashes(request)))

@app.post("/register")
#@rate_limit("4/minute")
async def register_post(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    phone: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    profile_pic: Optional[UploadFile] = File(None)
):
    if not full_name or not email or not password:
        flash(request, "Họ tên, email, mật khẩu bắt buộc.", "danger")
        return RedirectResponse(url="/register", status_code=303)
    if not role:
        flash(request, "Vui lòng chọn vai trò (Bệnh nhân hoặc Bác sĩ).", "danger")
        return RedirectResponse(url="/register", status_code=303)

    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email=?", (email,))
    if c.fetchone():
        conn.close()
        flash(request, "Email đã đăng ký.", "danger")
        return RedirectResponse(url="/register", status_code=303)

    password_hash = pwd_context.hash(password)

    filename = None
    if profile_pic and profile_pic.filename:
        filename = f"{uuid.uuid4()}_{profile_pic.filename}"
        if not allowed_ext(filename):
            conn.close()
            return JSONResponse({"error": "Invalid format"})
        file_path = os.path.join(PROFILE_PIC_FOLDER, filename)
        with open(file_path, "wb") as f:
            f.write(await profile_pic.read())

    c.execute("""
        INSERT INTO users (full_name, email, phone, profile_pic, password_hash, role)
        VALUES (?,?,?,?,?,?)
    """, (full_name, email, phone, filename, password_hash, role))
    conn.commit()
    conn.close()
    flash(request, "Đăng ký thành công!", "success")
    return RedirectResponse(url="/", status_code=303)

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", template_context(request, flashes=get_flashes(request)))

@app.post("/login")
#@rate_limit("3/minute")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    if not email or not password:
        flash(request, "Email và mật khẩu bắt buộc.", "danger")
        return RedirectResponse(url="/", status_code=303)

    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT id,password_hash,role FROM users WHERE email=?", (email,))
    user = c.fetchone()
    conn.close()

    if user and pwd_context.verify(password, user["password_hash"]):
        request.session['user_id'] = user["id"]
        request.session['user_role'] = user["role"]
        flash(request, "Đăng nhập thành công!", "success")
        # simulate JS localStorage removal by redirect
        return templates.TemplateResponse("redirect_js.html", {"request": request, "target": "/"})
    else:
        flash(request, "Email hoặc mật khẩu không đúng.", "danger")
        return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.pop('user_id', None)
    request.session.pop('user_role', None)
    flash(request, "Đã đăng xuất.", "success")
    return templates.TemplateResponse("redirect_js.html", {"request": request, "target": "/"})

# ---------------- Profile ----------------
@app.get("/profile", response_class=HTMLResponse)
async def profile_get(request: Request, notifications=Depends(get_notifications)):
    if 'user_id' not in request.session:
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)

    isDoctor = (request.session.get('user_role') == 'doctor')
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT full_name,email,phone,profile_pic FROM users WHERE id=?", (request.session['user_id'],))
    user = c.fetchone()
    conn.close()
    return templates.TemplateResponse("profile.html", template_context(request, notifications=notifications, isDoctor=isDoctor, show_patient_management=isDoctor, user=user, flashes=get_flashes(request)))

@app.post("/profile")
async def profile_post(
    request: Request,
    full_name: str = Form(...),
    phone: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    profile_pic: Optional[UploadFile] = File(None)
):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)

    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT profile_pic FROM users WHERE id=?", (request.session['user_id'],))
    old = c.fetchone()
    old_pic = old['profile_pic'] if old else None
    filename = old_pic

    if profile_pic and profile_pic.filename:
        filename = f"{uuid.uuid4()}_{profile_pic.filename}"
        if not allowed_ext(filename):
            conn.close()
            return JSONResponse({"error": "Invalid format"})
        with open(os.path.join(PROFILE_PIC_FOLDER, filename), "wb") as f:
            f.write(await profile_pic.read())
        if old_pic:
            try:
                os.remove(os.path.join(PROFILE_PIC_FOLDER, old_pic))
            except Exception:
                pass

    if password:
        phash = pwd_context.hash(password)
        c.execute("UPDATE users SET full_name=?, phone=?, profile_pic=?, password_hash=? WHERE id=?",
                  (full_name, phone, filename, phash, request.session['user_id']))
    else:
        c.execute("UPDATE users SET full_name=?, phone=?, profile_pic=? WHERE id=?",
                  (full_name, phone, filename, request.session['user_id']))
    conn.commit()
    conn.close()
    flash(request, "Cập nhật thành công", "success")
    return RedirectResponse(url="/profile", status_code=303)

# ---------------- Shared to me, History, Pending cases ----------------
@app.get("/shared-to-me", response_class=HTMLResponse)
async def shared_to_me(request: Request, notifications=Depends(get_notifications)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)

    isDoctor = (request.session['user_role'] == 'doctor')

    conn = get_db_conn()
    c = conn.cursor()
    user_row = c.execute("SELECT email FROM users WHERE id = ?", (request.session['user_id'],)).fetchone()
    if user_row:
        user_email = user_row["email"]
    else:
        conn.close()
        flash(request, "Không tìm thấy người dùng với id này!", "danger")
        return RedirectResponse(url="/", status_code=303)

    c.execute("SELECT id, full_name FROM users")
    users = {row["id"]: row["full_name"] for row in c.fetchall()}

    model_map = {
        "skin_cancer_vit": "Ung thư da",
        "pneumonia_vit": "Viêm phổi",
        "covid19_vit": "Covid-19",
        "breast_cancer_vit": "Ung thư vú",
        "brain_tumor_vit": "U não - A",
        "brain_tumor_resnet": "U não - B"
    }

    c.execute("SELECT id, user_id, patient_id, model,image_filename,prediction,probability,timestamp,sharer FROM diagnoses WHERE share_to=? AND accept_share=1 ORDER BY timestamp DESC", (user_email,))
    diagnoses = [dict(row) for row in c.fetchall()]
    for d in diagnoses:
        d["user_id"] = users.get(d["user_id"], None)
        d["sharer"] = users.get(d["sharer"], None)
        d["model"] = ", ".join(model_map.get(m.strip(), m.strip()) for m in d["model"].split(","))

    c.execute("SELECT id, user_id, patient_id,model,image_filename,question,answer,timestamp,sharer FROM qa_interactions WHERE share_to=? AND accept_share=1 ORDER BY timestamp DESC", (user_email,))
    qa_interactions = [dict(row) for row in c.fetchall()]
    for d in qa_interactions:
        d["user_id"] = users.get(d["user_id"], None)
        d["sharer"] = users.get(d["sharer"], None)
        d["model"] = ", ".join(model_map.get(m.strip(), m.strip()) for m in d["model"].split(","))

    conn.close()
    return templates.TemplateResponse("shared_to_me.html", template_context(request, notifications=notifications, isDoctor=isDoctor, show_patient_management=isDoctor, diagnoses=diagnoses[:20], qa_interactions=qa_interactions[:20], flashes=get_flashes(request)))

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request, notifications=Depends(get_notifications)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)

    isDoctor = (request.session['user_role'] == 'doctor')
    conn = get_db_conn()
    c = conn.cursor()

    c.execute("SELECT id, patient_id, model,image_filename,prediction,probability,timestamp FROM diagnoses WHERE user_id=? ORDER BY timestamp DESC", (request.session['user_id'],))
    diagnoses = [dict(row) for row in c.fetchall()]

    c.execute("SELECT id, patient_id,model,image_filename,question,answer,timestamp FROM qa_interactions WHERE user_id=? ORDER BY timestamp DESC", (request.session['user_id'],))
    qa_interactions = [dict(row) for row in c.fetchall()]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=?", (request.session['user_id'],))
    total_diagnoses = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='skin_cancer_vit'", (request.session['user_id'],))
    skin_cancer = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='pneumonia_vit'", (request.session['user_id'],))
    pneumonia = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='breast_cancer_vit'", (request.session['user_id'],))
    breast_cancer = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='covid19_vit'", (request.session['user_id'],))
    covid_19 = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND (model='brain_tumor_vit' OR model='brain_tumor_resnet')", (request.session['user_id'],))
    brain_tumor = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM qa_interactions WHERE user_id=?", (request.session['user_id'],))
    total_qa = c.fetchone()[0]

    conn.close()
    return templates.TemplateResponse("history.html", template_context(request, notifications=notifications, isDoctor=isDoctor, show_patient_management=isDoctor, diagnoses=diagnoses[:20], qa_interactions=qa_interactions[:20], stats={
        "total_diagnoses": total_diagnoses,
        "skin_cancer": skin_cancer,
        "pneumonia": pneumonia,
        "breast_cancer": breast_cancer,
        "covid_19": covid_19,
        "brain_tumor": brain_tumor,
        "total_qa": total_qa
    }, flashes=get_flashes(request)))

@app.get("/pending-cases", response_class=HTMLResponse)
async def pending_cases(request: Request, notifications=Depends(get_notifications)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    if (request.session['user_role'] != 'doctor'):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("pending_cases.html", template_context(request, notifications=notifications, user_id=request.session['user_id'], isDoctor=True, api_host=WEB_SERVER_HOST, show_patient_management=True))

# ---------------- Patient Management ----------------
@app.get("/patient-management", response_class=HTMLResponse)
async def patient_management(request: Request, notifications=Depends(get_notifications)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    if (request.session['user_role'] != 'doctor'):
        flash(request, "Role khong hop le", "danger")
        return RedirectResponse(url="/", status_code=303)

    conn = get_db_conn()
    patients = conn.execute("SELECT * FROM patients WHERE creator_id = ?", (request.session['user_id'],)).fetchall()
    conn.close()
    return templates.TemplateResponse("patient_management.html", template_context(request, notifications=notifications, isDoctor=True, show_patient_management=True, patients=patients, flashes=get_flashes(request)))

@app.post("/patients/add")
#@rate_limit("3/minute")
async def add_patient(request: Request, name: str = Form(...), age: Optional[int] = Form(None), gender: Optional[str] = Form(None), phone: Optional[str] = Form(None), email: Optional[str] = Form(None), address: Optional[str] = Form(None)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    if (request.session['user_role'] != 'doctor'):
        flash(request, "Role khong hop le", "danger")
        return RedirectResponse(url="/", status_code=303)
    user_id = request.session['user_id']
    conn = get_db_conn()
    conn.execute("INSERT INTO patients (name, age, gender, phone, email, address, creator_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (name, age, gender, phone, email, address, user_id))
    conn.commit()
    conn.close()
    flash(request, "Thêm bệnh nhân thành công", "success")
    return RedirectResponse(url="/patient-management", status_code=303)

@app.post("/patients/update/{id}")
#@rate_limit("3/minute")
async def update_patient(request: Request, id: int, name: str = Form(...), age: Optional[int] = Form(None), gender: Optional[str] = Form(None), phone: Optional[str] = Form(None), email: Optional[str] = Form(None), address: Optional[str] = Form(None)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    if (request.session['user_role'] != 'doctor'):
        flash(request, "Role khong hop le", "danger")
        return RedirectResponse(url="/", status_code=303)
    user_id = request.session['user_id']
    conn = get_db_conn()
    patient = conn.execute("SELECT * FROM patients WHERE id = ? AND creator_id = ?", (id, user_id)).fetchone()
    if not patient:
        conn.close()
        flash(request, "Bạn không có quyền sửa bệnh nhân này", "danger")
        return RedirectResponse(url="/patient-management", status_code=303)
    conn.execute("UPDATE patients SET name=?, age=?, gender=?, phone=?, email=?, address=? WHERE id=?",
                 (name, age, gender, phone, email, address, id))
    conn.commit()
    conn.close()
    flash(request, "Cập nhật bệnh nhân thành công", "success")
    return RedirectResponse(url="/patient-management", status_code=303)

@app.post("/patients/delete/{id}")
#@rate_limit("3/minute")
async def delete_patient(request: Request, id: int):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    if (request.session['user_role'] != 'doctor'):
        flash(request, "Role khong hop le", "danger")
        return RedirectResponse(url="/", status_code=303)
    user_id = request.session['user_id']
    conn = get_db_conn()
    patient = conn.execute("SELECT * FROM patients WHERE id = ? AND creator_id = ?", (id, user_id)).fetchone()
    if not patient:
        conn.close()
        flash(request, "Bạn không có quyền xóa bệnh nhân này", "danger")
        return RedirectResponse(url="/patient-management", status_code=303)
    conn.execute("DELETE FROM patients WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash(request, "Xóa bệnh nhân thành công", "success")
    return RedirectResponse(url="/patient-management", status_code=303)

# ---------------- Respond share ----------------
@app.post("/respond_share")
#@rate_limit("10/minute")
async def respond_share(request: Request, id: str = Form(...), table: str = Form(...), decision: str = Form(...)):
    if 'user_id' not in request.session:
        return JSONResponse({"status": "unauthorized"}, status_code=403)
    if table == '1':
        conn = get_db_conn()
        conn.execute("UPDATE qa_interactions SET accept_share=? WHERE id=?", (decision, id))
        conn.commit()
        conn.close()
    elif table == '0':
        conn = get_db_conn()
        conn.execute("UPDATE diagnoses SET accept_share=? WHERE id=?", (decision, id))
        conn.commit()
        conn.close()
    return {"status": "success"}

# ---------------- Diagnosis detail ----------------
@app.get("/diagnosis_detail", response_class=HTMLResponse)
async def diagnosis_detail(request: Request, notifications=Depends(get_notifications), id: Optional[int] = None, tag: Optional[str] = None):
    if not id or not tag:
        return JSONResponse({"error": "Missing id or tag"}, status_code=400)
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)

    conn = get_db_conn()
    if tag == 'diag':
        row = conn.execute("SELECT id, user_id, patient_id, model, image_filename, prediction, probability, timestamp, share_to, sharer, explain_image_filename FROM diagnoses WHERE id = ?", (id,)).fetchone()
        user_row = conn.execute("SELECT email FROM users WHERE id = ?", (request.session['user_id'],)).fetchone()
        conn.close()
        if not row:
            return JSONResponse({"error": "Diagnosis not found"}, status_code=404)
        if user_row:
            user_email = user_row["email"]
        else:
            flash(request, "Không tìm thấy người dùng với id này!", "danger")
            return RedirectResponse(request.headers.get("referer", "/"), status_code=303)
        if row[1] != request.session['user_id'] and row[8] != user_email:
            return RedirectResponse(url="/shared-to-me", status_code=303)
        showUpdate = (row[1] == request.session['user_id'])

        conn = get_db_conn()
        creator = conn.execute("SELECT full_name from users WHERE id = ?", (row[1],)).fetchone()
        sharer = conn.execute("SELECT full_name from users WHERE id = ?", (row[9],)).fetchone()
        patient = conn.execute("SELECT name from patients WHERE id = ?", (row[2],)).fetchone()
        conn.close()

        model_map = {
            "skin_cancer_vit": "Ung thư da",
            "pneumonia_vit": "Viêm phổi",
            "covid19_vit": "Covid-19",
            "breast_cancer_vit": "Ung thư vú",
            "brain_tumor_vit": "U não - A",
            "brain_tumor_resnet": "U não - B"
        }
        model = ", ".join(model_map.get(m.strip(), m.strip()) for m in row[3].split(","))

        diagnosis = {
            "id": row[0],
            "creator": (creator[0] if creator else "N/A"),
            "patient_id": row[2],
            "model": model,
            "image_filename": row[4],
            "prediction": row[5],
            "probability": row[6],
            "timestamp": row[7],
            "share_to": row[8],
            "sharer": (sharer[0] if sharer else "N/A"),
            "patient": (patient[0] if patient else "N/A"),
            "explain_image_filenames": row[10]
        }

    else:
        row = conn.execute("SELECT id, user_id, patient_id, model, image_filename, question, answer, timestamp, share_to, sharer FROM qa_interactions WHERE id = ?", (id,)).fetchone()
        user_row = conn.execute("SELECT email FROM users WHERE id = ?", (request.session['user_id'],)).fetchone()
        conn.close()
        if not row:
            return JSONResponse({"error": "Diagnosis not found"}, status_code=404)
        if user_row:
            user_email = user_row["email"]
        else:
            flash(request, "Không tìm thấy người dùng với id này!", "danger")
            return RedirectResponse(request.headers.get("referer", "/"), status_code=303)
        if row[1] != request.session['user_id'] and row[8] != user_email:
            return RedirectResponse(url="/shared-to-me", status_code=303)
        showUpdate = (row[1] == request.session['user_id'])

        conn = get_db_conn()
        creator = conn.execute("SELECT full_name from users WHERE id = ?", (row[1],)).fetchone()
        sharer = conn.execute("SELECT full_name from users WHERE id = ?", (row[9],)).fetchone()
        patient = conn.execute("SELECT name from patients WHERE id = ?", (row[2],)).fetchone()
        conn.close()

        model_map = {"general": "Chẩn đoán tổng quát"}
        model = ", ".join(model_map.get(m.strip(), m.strip()) for m in row[3].split(","))

        diagnosis = {
            "id": row[0],
            "creator": (creator[0] if creator else "N/A"),
            "patient_id": row[2],
            "model": model,
            "image_filename": row[4],
            "question": row[5],
            "answer": row[6],
            "timestamp": row[7],
            "share_to": row[8],
            "sharer": (sharer[0] if sharer else "N/A"),
            "patient": (patient[0] if patient else "N/A")
        }

    return templates.TemplateResponse("diagnosis_detail.html", template_context(request, notifications=notifications, tag=tag, showUpdate=showUpdate, isDoctor=True, show_patient_management=True, diagnosis=diagnosis, flashes=get_flashes(request)))

# ---------------- Update patient diagnosis ----------------
@app.post("/update_patient_diagnosis")
#@rate_limit("3/minute")
async def update_patient_diagnosis(request: Request, id: str = Form(...), tag: str = Form(...), patient_id: str = Form(...)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    table = "diagnoses" if tag == "diag" else "qa_interactions"
    conn = get_db_conn()
    row = conn.execute(f"SELECT user_id FROM {table} WHERE id = ?", (id,)).fetchone()
    conn.close()
    if row[0] != request.session['user_id']:
        flash(request, "⛔ You do not have permission to update this diagnosis!", "danger")
        return RedirectResponse(url=f"/diagnosis_detail?id={id}", status_code=303)
    conn = get_db_conn()
    conn.execute(f"UPDATE {table} SET patient_id = ? WHERE id = ?", (patient_id, id))
    conn.commit()
    conn.close()
    flash(request, "Update complete.", "success")
    return RedirectResponse(url=f"/diagnosis_detail?tag={tag}&id={id}", status_code=303)

# ---------------- Share diagnosis ----------------
@app.post("/share_diagnosis")
#@rate_limit("3/minute")
async def share_diagnosis(request: Request, id: str = Form(...), tag: str = Form(...), user_id: str = Form(...)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    table = "diagnoses" if tag == "diag" else "qa_interactions"
    conn = get_db_conn()
    row = conn.execute(f"SELECT user_id, share_to FROM {table} WHERE id = ?", (id,)).fetchone()
    user_email = conn.execute("SELECT email FROM users WHERE id = ?", (request.session['user_id'],)).fetchone()
    conn.close()
    if row[0] != request.session['user_id'] and row[1] != user_email[0]:
        flash(request, "⛔ You do not have permission to share this diagnosis!", "danger")
        return RedirectResponse(url=f"/diagnosis_detail?id={id}", status_code=303)
    conn = get_db_conn()
    conn.execute(f"UPDATE {table} SET share_to = ?, sharer = ?, accept_share = 0 WHERE id = ?", (user_id, request.session['user_id'], id))
    conn.commit()
    conn.close()
    flash(request, "Share complete.", "success")
    return RedirectResponse(url=f"/diagnosis_detail?tag={tag}&id={id}", status_code=303)

# ---------------- Diagnose (upload + enque) ----------------
@app.get("/diagnose", response_class=HTMLResponse)
async def diagnose_get(request: Request, notifications=Depends(get_notifications)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    isDoctor = (request.session['user_role'] == 'doctor')
    conn = get_db_conn()
    patients = conn.execute("SELECT id, name FROM patients WHERE creator_id = ?", (request.session['user_id'],)).fetchall()
    conn.close()
    return templates.TemplateResponse("diagnosis.html", template_context(request, notifications=notifications, user_id=request.session['user_id'], patient_id=request.session['user_id'], isDoctor=isDoctor, patients=patients, show_patient_management=isDoctor, api_host=WEB_SERVER_HOST, img_host=IMG_SERVER_HOST, flashes=get_flashes(request)))

@app.post("/diagnose")
#@rate_limit("3/minute")
async def diagnose_post(request: Request, file: UploadFile = File(...), model: str = Form(...), patient_id: str = Form(...)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    if not file or not model or not patient_id:
        return JSONResponse({"error": "Thiếu file, model hoặc mã bệnh nhân"}, status_code=400)

    conn = get_db_conn()
    # patient check
    if str(patient_id).startswith("BN_"):
        user_patient_id = str(patient_id)[3:]
        patient = conn.execute("SELECT id, full_name FROM users WHERE id = ?", (user_patient_id,)).fetchone()
        if int(user_patient_id) != int(request.session['user_id']):
            patient = False
    else:
        patient = conn.execute("SELECT * FROM patients WHERE id = ? AND creator_id = ?", (patient_id, request.session['user_id'])).fetchone()
    conn.close()

    if not patient and str(patient_id) != "0":
        return JSONResponse({"error": "Mã bệnh nhân không tồn tại hoặc bạn không có quyền"}, status_code=400)

    filename = f"{uuid.uuid4()}_{file.filename}"
    if not allowed_ext(filename):
        return JSONResponse({"error": "Invalid format"}, status_code=400)

    with open(os.path.join(UPLOAD_FOLDER, filename), "wb") as f:
        f.write(await file.read())

    try:
        task = call_diagnosis_from_ai_server.apply_async(args=[filename, patient_id, model, request.session['user_id']])
    except requests.RequestException:
        return JSONResponse({"error": "Lỗi kết nối API"}, status_code=500)

    return {"task_id": task.id, "status": "queued"}

# ---------------- Task status endpoints ----------------
@app.get("/diagnoseStatus/{task_id}")
#@rate_limit("60/second")
async def task_diagnosis_status(task_id: str):
    task = call_diagnosis_from_ai_server.AsyncResult(task_id)
    if task.state == 'PENDING':
        return {"status": "queued"}
    elif task.state == 'SUCCESS':
        return {"status": "finished", "result": task.result}
    elif task.state == 'FAILURE':
        return {"status": "failed", "error": "private"}
    else:
        return {"status": task.state}

@app.get("/vqaStatus/{task_id}")
#@rate_limit("60/second")
async def task_visionqa_status(task_id: str):
    task = call_vision_qa_from_ai_server.AsyncResult(task_id)
    if task.state == 'PENDING':
        return {"status": "queued"}
    elif task.state == 'SUCCESS':
        return {"status": "finished", "result": task.result}
    elif task.state == 'FAILURE':
        return {"status": "failed", "error": str(task.info)}
    else:
        return {"status": task.state}

# ---------------- Vision QA ----------------
@app.get("/vision-qa", response_class=HTMLResponse)
async def vision_qa_get(request: Request, notifications=Depends(get_notifications)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        flash(request, "Vui lòng đăng nhập", "danger")
        return RedirectResponse(url="/", status_code=303)
    isDoctor = (request.session['user_role'] == 'doctor')
    conn = get_db_conn()
    patients = conn.execute("SELECT id, name FROM patients WHERE creator_id = ?", (request.session['user_id'],)).fetchall()
    conn.close()
    return templates.TemplateResponse("vision_qa.html", template_context(request, notifications=notifications, user_id=request.session['user_id'], isDoctor=isDoctor, patient_id=request.session['user_id'], patients=patients, show_patient_management=isDoctor, api_host=WEB_SERVER_HOST, img_host=IMG_SERVER_HOST, flashes=get_flashes(request)))

@app.post("/vision-qa")
#@rate_limit("2/10minutes")
async def vision_qa_post(request: Request, file: UploadFile = File(...), question: str = Form(...), model: str = Form(...), patient_id: str = Form(...)):
    if ('user_id' not in request.session) or ('user_role' not in request.session):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    if not file or not question:
        return JSONResponse({"error": "Thiếu file hoặc câu hỏi"}, status_code=400)

    conn = get_db_conn()
    if str(patient_id).startswith("BN_"):
        user_patient_id = str(patient_id)[3:]
        patient = conn.execute("SELECT id, full_name FROM users WHERE id = ?", (user_patient_id,)).fetchone()
        if int(user_patient_id) != int(request.session['user_id']):
            patient = False
    else:
        patient = conn.execute("SELECT * FROM patients WHERE id = ? AND creator_id = ?", (patient_id, request.session['user_id'])).fetchone()
    conn.close()

    if not patient and str(patient_id) != "0":
        return JSONResponse({"error": "Mã bệnh nhân không tồn tại hoặc bạn không có quyền"}, status_code=400)

    filename = f"vqa_{uuid.uuid4()}_{file.filename}"
    if not allowed_ext(filename):
        return JSONResponse({"error": "Invalid format"}, status_code=400)
    with open(os.path.join(UPLOAD_FOLDER, filename), "wb") as f:
        f.write(await file.read())

    try:
        task = call_vision_qa_from_ai_server.apply_async(args=[filename, question, patient_id, model, request.session['user_id']])
    except requests.RequestException:
        return JSONResponse({"error": "Lỗi kết nối API"}, status_code=500)

    return {"task_id": task.id, "status": "queued"}

# ---------------- Main entry ----------------
# For dev run: uvicorn fast_app:app --host 0.0.0.0 --port 5000
