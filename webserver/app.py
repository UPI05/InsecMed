from flask import g, Flask, render_template, render_template_string, request, jsonify, redirect, url_for, flash, session
import sqlite3, os, secrets, requests
from datetime import datetime
from celery import Celery
import uuid
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from flask_talisman import Talisman
from flask_bcrypt import Bcrypt
from flasgger import Swagger
import yaml

app = Flask(__name__)
app.secret_key = "inseclab"

# --- Đọc file OpenAPI YAML ---
with open("api-docs-flasgger.yaml", "r", encoding="utf-8") as f:
    openapi_spec = yaml.safe_load(f)

# --- Gắn Swagger UI với file YAML ---
swagger = Swagger(app, template=openapi_spec)

talisman = Talisman(
    app,
    session_cookie_secure=False,         # Không bật Secure cookie (dev)
    session_cookie_samesite='Strict',    # SameSite Strict để chống CSRF
    force_https=False,                   # Không redirect HTTP -> HTTPS (dev)
    frame_options='DENY',                # X-Frame-Options: DENY (chống clickjacking)
    content_security_policy={            # CSP: hạn chế nhúng iframe
        "frame-ancestors": "'self'"
    }
)

# limit upload size
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'nrrd', 'hdr', 'img', 'nii', 'gz', 'dcm'}

# server host
WEB_SERVER_HOST = 'http://10.102.196.113'
AI_SERVER_HOST = 'http://10.102.196.113:8080'
IMG_SERVER_HOST = 'http://10.102.196.113:8000'
EXPLAIN_SERVER_HOST = "http://10.102.196.101:8000/explain"

# Rate limiter
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["100 per hour"])

# Cấu hình Celery dùng Redis làm broker
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'   # broker
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'  # lưu kết quả

celery = Celery(app.name,
                broker=app.config['CELERY_BROKER_URL'],
                backend=app.config['CELERY_RESULT_BACKEND'])
celery.conf.update(app.config)

# Folders
PROFILE_PIC_FOLDER = 'static/profile_pics'
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database
DB_FILE = 'insecmed.db'

def allowed_ext(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

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

if not os.path.exists(DB_FILE):
    init_db()

def get_db_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

@app.before_request
def load_notifications():
    # Không load nếu không login 
    if request.endpoint in ('static',) or 'user_id' not in session:
        return

    conn = get_db_conn()

    # Lấy users map (id -> full_name)
    users = conn.execute("SELECT id, full_name FROM users").fetchall()
    users_map = {row["id"]: row["full_name"] for row in users}

    user_row = conn.execute("SELECT email FROM users WHERE id = ?", (session['user_id'],)).fetchone()

    if user_row:
        user_email = user_row["email"]
    else:
        flash("Không tìm thấy người dùng với id này!", "danger")
        return redirect(request.referrer)

    # Lấy notifications
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
        creator_id = n["user_id"]
        n["user_id"] = users_map.get(creator_id)
    g.notifications = notifications

# -----------------Celery ----------------
@celery.task(bind=True, queue='pipeline_a')
def call_diagnosis_from_ai_server(self, filename, patient_id, model_name, user_id):
    input_file = open(os.path.join(UPLOAD_FOLDER, filename), 'rb')
    # Gọi API server để inference
    files = {'file': input_file}
    data = {'model': model_name}
    resp = requests.post(f"{AI_SERVER_HOST}/diagnose", data=data, files=files)
    results = resp.json()

    labels = ""
    for i in range(len(model_name.split(','))):
        labels += results['results'][i]['top_label'] + "/"

    explain_filenames = ""

    for idx, m in enumerate(model_name.split(',')):
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
            "prediction": (None, "Value"),
            "image": (filename, input_file, "image/png")
        }

        explain_filenames += "explain_"+str(idx)+"_"+filename + ","

        response = requests.post(EXPLAIN_SERVER_HOST, files=files)
        if response.content:
            with open(os.path.join(UPLOAD_FOLDER, "explain_"+str(idx)+"_"+filename), "wb") as f:
                f.write(response.content)

    # Lưu vào database
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
    # Gọi API server để inference
    files = {'file': open(os.path.join(UPLOAD_FOLDER, filename), 'rb')}
    data = {'question': question, 'model': model_name}
    resp = requests.post(f"{AI_SERVER_HOST}/vqa-diagnose", data=data, files=files)
    results = resp.json()
    # Lưu vào database
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


@app.route('/diagnoseStatus/<task_id>')
@limiter.limit("60 per second")
def task_diagnosis_status(task_id):
    task = call_diagnosis_from_ai_server.AsyncResult(task_id)
    if task.state == 'PENDING':
        return jsonify({"status": "queued"})
    elif task.state == 'SUCCESS':
        return jsonify({"status": "finished", "result": task.result})
    elif task.state == 'FAILURE':
        return jsonify({"status": "failed", "error": "private"}) #str(task.info)
    else:
        return jsonify({"status": task.state})

@app.route('/vqaStatus/<task_id>')
@limiter.limit("60 per second")
def task_visionqa_status(task_id):
    task = call_vision_qa_from_ai_server.AsyncResult(task_id)
    if task.state == 'PENDING':
        return jsonify({"status": "queued"})
    elif task.state == 'SUCCESS':
        return jsonify({"status": "finished", "result": task.result})
    elif task.state == 'FAILURE':
        return jsonify({"status": "failed", "error": str(task.info)})
    else:
        return jsonify({"status": task.state})

# ---------------- Routes ----------------
@app.route("/ping", methods=["GET"])
@limiter.limit("5 per minute")
def ping():
    return jsonify({"msg": "pong"})

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('diagnose'))
    return render_template('login.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("4 per minute")
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone')
        role = request.form.get('role')
        profile_pic = request.files.get('profile_pic')

        if not full_name or not email or not password:
            flash("Họ tên, email, mật khẩu bắt buộc.", "danger")
            return redirect(url_for('register'))

        if not role:
            flash("Vui lòng chọn vai trò (Bệnh nhân hoặc Bác sĩ).", "danger")
            return redirect(url_for('register'))

        conn = get_db_conn()
        c = conn.cursor()

        # kiểm tra email đã tồn tại
        c.execute("SELECT id FROM users WHERE email=?", (email,))
        if c.fetchone():
            flash("Email đã đăng ký.", "danger")
            conn.close()
            return redirect(url_for('register'))

        bcrypt = Bcrypt(app)
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

        filename = None
        if profile_pic and profile_pic.filename:
            filename = f"{uuid.uuid4()}_{secure_filename(profile_pic.filename)}"
            if not allowed_ext(filename):
                return jsonify({"error": "Invalid format"})
            profile_pic.save(os.path.join(PROFILE_PIC_FOLDER, filename))

        # thêm role vào insert
        c.execute("""
            INSERT INTO users (full_name, email, phone, profile_pic, password_hash, role)
            VALUES (?,?,?,?,?,?)
        """, (full_name, email, phone, filename, password_hash, role))

        conn.commit()
        conn.close()
        flash("Đăng ký thành công!", "success")
        return redirect(url_for('index'))

    return render_template('register.html')


@app.route('/login', methods=['GET','POST'])
@limiter.limit("3 per minute")
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if not email or not password:
            flash("Email và mật khẩu bắt buộc.", "danger")
            return redirect(url_for('index'))

        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT id,password_hash,role FROM users WHERE email=?", (email,))
        user = c.fetchone()
        conn.close()

        from flask_bcrypt import Bcrypt
        bcrypt = Bcrypt(app)

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            flash("Đăng nhập thành công!", "success")
            return render_template_string("""
            <script>
            localStorage.removeItem('taskList');
            window.location.href = "/";
            </script>
            """)
        else:
            flash("Email hoặc mật khẩu không đúng.", "danger")
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_role', None)
    flash("Đã đăng xuất.", "success")
    return render_template_string("""
    <script>
    localStorage.removeItem('taskList');
    window.location.href = "/";
    </script>
    """)

@app.route('/profile', methods=['GET','POST'])
def profile():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    show_patient_management = False
    isDoctor = False
    if (session['user_role'] == 'doctor'):
        show_patient_management = True
        isDoctor = True

    conn = get_db_conn()
    c = conn.cursor()

    if request.method=='POST':
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        password = request.form.get('password')
        profile_pic = request.files.get('profile_pic')

        c.execute("SELECT profile_pic FROM users WHERE id=?", (session['user_id'],))
        old_pic = c.fetchone()['profile_pic']
        filename = old_pic

        if profile_pic and profile_pic.filename:
            filename = f"{uuid.uuid4()}_{secure_filename(profile_pic.filename)}"
            if not allowed_ext(filename):
                return jsonify({"error": "Invalid format"})
            profile_pic.save(os.path.join(PROFILE_PIC_FOLDER, filename))
            if old_pic and os.path.exists(os.path.join(PROFILE_PIC_FOLDER, old_pic)):
                os.remove(os.path.join(PROFILE_PIC_FOLDER, old_pic))

        from flask_bcrypt import Bcrypt
        bcrypt = Bcrypt(app)

        if password:
            phash = bcrypt.generate_password_hash(password).decode('utf-8')
            c.execute("UPDATE users SET full_name=?, phone=?, profile_pic=?, password_hash=? WHERE id=?",
                      (full_name, phone, filename, phash, session['user_id']))
        else:
            c.execute("UPDATE users SET full_name=?, phone=?, profile_pic=? WHERE id=?",
                      (full_name, phone, filename, session['user_id']))
        conn.commit()
        conn.close()
        flash("Cập nhật thành công", "success")
        return redirect(url_for('profile'))

    c.execute("SELECT full_name,email,phone,profile_pic FROM users WHERE id=?", (session['user_id'],))
    user = c.fetchone()
    conn.close()
    return render_template('profile.html', notifications=g.notifications, isDoctor=isDoctor, user=user, show_patient_management=show_patient_management)


@app.route('/shared-to-me')
def shared_to_me():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    show_patient_management = False
    isDoctor = False
    if (session['user_role'] == 'doctor'):
        show_patient_management = True
        isDoctor = True

    conn = get_db_conn()
    c = conn.cursor()

    user_row = c.execute("SELECT email FROM users WHERE id = ?", (session['user_id'],)).fetchone()

    if user_row:
        user_email = user_row["email"]
    else:
        flash("Không tìm thấy người dùng với id này!", "danger")
        return redirect(request.referrer)

    # Diagnoses
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
        creator = d["user_id"]
        sharer = d["sharer"]
        d["user_id"] = users.get(creator, None)
        d["sharer"] = users.get(sharer, None)
        d["model"] = ", ".join(model_map.get(m.strip(), m.strip()) for m in d["model"].split(","))

    # QA interactions
    c.execute("SELECT id, user_id, patient_id,model,image_filename,question,answer,timestamp,sharer FROM qa_interactions WHERE share_to=? AND accept_share=1 ORDER BY timestamp DESC", (user_email,))
    qa_interactions = [dict(row) for row in c.fetchall()]
    for d in qa_interactions:
        creator = d["user_id"]
        sharer = d["sharer"]
        d["user_id"] = users.get(creator, None)
        d["sharer"] = users.get(sharer, None)
        d["model"] = ", ".join(model_map.get(m.strip(), m.strip()) for m in d["model"].split(","))

    conn.close()

    return render_template('shared_to_me.html', notifications=g.notifications, isDoctor=isDoctor, show_patient_management=show_patient_management, diagnoses=diagnoses[:20], qa_interactions=qa_interactions[:20])

@app.route('/history')
def history():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    show_patient_management = False
    isDoctor = False
    if (session['user_role'] == 'doctor'):
        show_patient_management = True
        isDoctor = True

    conn = get_db_conn()
    c = conn.cursor()

    # Diagnoses
    c.execute("SELECT id, patient_id, model,image_filename,prediction,probability,timestamp FROM diagnoses WHERE user_id=? ORDER BY timestamp DESC", (session['user_id'],))
    diagnoses = [dict(row) for row in c.fetchall()]

    # QA interactions
    c.execute("SELECT id, patient_id,model,image_filename,question,answer,timestamp FROM qa_interactions WHERE user_id=? ORDER BY timestamp DESC", (session['user_id'],))
    qa_interactions = [dict(row) for row in c.fetchall()]

    # Stats
    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=?", (session['user_id'],))
    total_diagnoses = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='skin_cancer_vit'", (session['user_id'],))
    skin_cancer = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='pneumonia_vit'", (session['user_id'],))
    pneumonia = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='breast_cancer_vit'", (session['user_id'],))
    breast_cancer = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='covid19_vit'", (session['user_id'],))
    covid_19 = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND (model='brain_tumor_vit' OR model='brain_tumor_resnet')", (session['user_id'],))
    brain_tumor = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM qa_interactions WHERE user_id=?", (session['user_id'],))
    total_qa = c.fetchone()[0]

    conn.close()
    
    return render_template('history.html', notifications=g.notifications, isDoctor=isDoctor, show_patient_management=show_patient_management, diagnoses=diagnoses[:20], qa_interactions=qa_interactions[:20],
                           stats={"total_diagnoses":total_diagnoses,"skin_cancer":skin_cancer,
                                  "pneumonia":pneumonia,"breast_cancer":breast_cancer,"covid_19":covid_19,
                                  "brain_tumor":brain_tumor,"total_qa":total_qa})

@app.route('/pending-cases')
def pending_cases():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    show_patient_management = False
    isDoctor = False
    if (session['user_role'] == 'doctor'):
        show_patient_management = True
        isDoctor = True
    else:
        return redirect(url_for('index'))
    return render_template('pending_cases.html', notifications=g.notifications, isDoctor=isDoctor, api_host=WEB_SERVER_HOST, show_patient_management=show_patient_management)

# ---------------- Patient Management ----------------
@app.route("/patient-management")
def patient_management():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    
    if (session['user_role'] != 'doctor'):
        flash("Role khong hop le", "danger")
        return redirect(url_for('index'))

    user_id = session['user_id']
    conn = get_db_conn()
    patients = conn.execute(
        "SELECT * FROM patients WHERE creator_id = ?",
        (user_id,)
    ).fetchall()
    conn.close()
    return render_template("patient_management.html", notifications=g.notifications, isDoctor=True, show_patient_management=True, patients=patients)


@app.route("/patients/add", methods=["POST"])
@limiter.limit("3 per minute")
def add_patient():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    if (session['user_role'] != 'doctor'):
        flash("Role khong hop le", "danger")
        return redirect(url_for('index'))

    data = request.form
    user_id = session['user_id']

    conn = get_db_conn()
    conn.execute(
        "INSERT INTO patients (name, age, gender, phone, email, address, creator_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data["name"], data.get("age"), data.get("gender"), data.get("phone"), data.get("email"), data.get("address"), user_id)
    )
    conn.commit()
    conn.close()
    flash("Thêm bệnh nhân thành công", "success")
    return redirect(url_for("patient_management"))


@app.route("/patients/update/<int:id>", methods=["POST"])
@limiter.limit("3 per minute")
def update_patient(id):
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    if (session['user_role'] != 'doctor'):
        flash("Role khong hop le", "danger")
        return redirect(url_for('index'))

    user_id = session['user_id']
    data = request.form

    conn = get_db_conn()
    # Kiểm tra quyền
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ? AND creator_id = ?",
        (id, user_id)
    ).fetchone()

    if not patient:
        conn.close()
        flash("Bạn không có quyền sửa bệnh nhân này", "danger")
        return redirect(url_for("patient_management"))

    conn.execute(
        "UPDATE patients SET name=?, age=?, gender=?, phone=?, email=?, address=? WHERE id=?",
        (data["name"], data.get("age"), data.get("gender"), data.get("phone"), data.get("email"), data.get("address"), id)
    )
    conn.commit()
    conn.close()
    flash("Cập nhật bệnh nhân thành công", "success")
    return redirect(url_for("patient_management"))


@app.route("/patients/delete/<int:id>", methods=["POST"])
@limiter.limit("3 per minute")
def delete_patient(id):
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    if (session['user_role'] != 'doctor'):
        flash("Role khong hop le", "danger")
        return redirect(url_for('index'))

    user_id = session['user_id']
    conn = get_db_conn()
    # Kiểm tra quyền
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ? AND creator_id = ?",
        (id, user_id)
    ).fetchone()

    if not patient:
        conn.close()
        flash("Bạn không có quyền xóa bệnh nhân này", "danger")
        return redirect(url_for("patient_management"))

    conn.execute("DELETE FROM patients WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash("Xóa bệnh nhân thành công", "success")
    return redirect(url_for("patient_management"))

@app.route("/respond_share", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"]) 
def respond_share():
    if 'user_id' not in session:
        return {"status": "unauthorized"}, 403

    diag_id = request.form.get("id")
    table = request.form.get("table")
    decision = request.form.get("decision")  # 1 = accept, 0 = reject

    if table == '1':
        conn = get_db_conn()
        conn.execute("UPDATE qa_interactions SET accept_share=? WHERE id=?", (decision, diag_id))
        conn.commit()
        conn.close()
    elif table == '0':
        conn = get_db_conn()
        conn.execute("UPDATE diagnoses SET accept_share=? WHERE id=?", (decision, diag_id))
        conn.commit()
        conn.close()

    return {"status": "success"}



# ---------------- Diagnosis ----------------
@app.route("/diagnosis_detail")
@limiter.limit("10 per minute") 
def diagnosis_detail():
    diag_id = request.args.get("id")
    tag = request.args.get("tag")
    if not diag_id or not tag:
        return "Missing id or tag", 400
    
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    
    if tag == 'diag':

        conn = get_db_conn()
        row = conn.execute("SELECT id, user_id, patient_id, model, image_filename, prediction, probability, timestamp, share_to, sharer, explain_image_filename FROM diagnoses WHERE id = ?", (diag_id,)).fetchone()
        user_row = conn.execute("SELECT email FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        conn.close()

        if not row:
            return "Diagnosis not found", 404
        
        if user_row:
            user_email = user_row["email"]
        else:
            flash("Không tìm thấy người dùng với id này!", "danger")
            return redirect(request.referrer)
        
        if row[1] != session['user_id'] and row[8] != user_email:
            return redirect(url_for('shared_to_me'))
            #return "Permission denied", 403
        
        showUpdate = False
        if row[1] == session['user_id']:
            showUpdate = True

        conn = get_db_conn()
        creator = conn.execute("SELECT full_name from users WHERE id = ?", (row[1],)).fetchone()
        sharer = conn.execute("SELECT full_name from users WHERE id = ?", (row[9],)).fetchone()
        patient = conn.execute("SELECT name from patients WHERE id = ?", (row[2],)).fetchone()
        conn.close()

        if not creator:
            creator = ["N/A"]
        
        if not sharer:
            sharer = ["N/A"]

        if not patient:
            patient = ["N/A"]

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
            "creator": creator[0],
            "patient_id": row[2],
            "model": model,
            "image_filename": row[4],
            "prediction": row[5],
            "probability": row[6],
            "timestamp": row[7],
            "share_to": row[8],
            "sharer": sharer[0],
            "patient": patient[0],
            "explain_image_filename": row[10]
        }

    else:
        conn = get_db_conn()
        row = conn.execute("SELECT id, user_id, patient_id, model, image_filename, question, answer, timestamp, share_to, sharer FROM qa_interactions WHERE id = ?", (diag_id,)).fetchone()
        user_row = conn.execute("SELECT email FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        conn.close()

        if not row:
            return "Diagnosis not found", 404
        
        if user_row:
            user_email = user_row["email"]
        else:
            flash("Không tìm thấy người dùng với id này!", "danger")
            return redirect(request.referrer)
        
        if row[1] != session['user_id'] and row[8] != user_email:
            return redirect(url_for('shared_to_me'))
            #return "Permission denied", 403
        
        showUpdate = False
        if row[1] == session['user_id']:
            showUpdate = True

        conn = get_db_conn()
        creator = conn.execute("SELECT full_name from users WHERE id = ?", (row[1],)).fetchone()
        sharer = conn.execute("SELECT full_name from users WHERE id = ?", (row[9],)).fetchone()
        patient = conn.execute("SELECT name from patients WHERE id = ?", (row[2],)).fetchone()
        conn.close()

        if not creator:
            creator = ["N/A"]
        
        if not sharer:
            sharer = ["N/A"]

        if not patient:
            patient = ["N/A"]

        model_map = {
            "general": "Chẩn đoán tổng quát"
        }
        model = ", ".join(model_map.get(m.strip(), m.strip()) for m in row[3].split(","))

        diagnosis = {
            "id": row[0],
            "creator": creator[0],
            "patient_id": row[2],
            "model": model,
            "image_filename": row[4],
            "question": row[5],
            "answer": row[6],
            "timestamp": row[7],
            "share_to": row[8],
            "sharer": sharer[0],
            "patient": patient[0]
        }

    return render_template("diagnosis_detail.html", tag=tag, notifications=g.notifications, showUpdate=showUpdate, isDoctor=True, show_patient_management=True, diagnosis=diagnosis)

@app.route("/update_patient_diagnosis", methods=["POST"])
@limiter.limit("3 per minute", methods=["POST"]) 
def update_patient_diagnosis():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    diag_id = request.form.get("id")
    tag = request.form.get("tag")
    new_patient = request.form.get("patient_id")

    # Chọn bảng dựa vào tag
    table = "diagnoses" if tag == "diag" else "qa_interactions"

    conn = get_db_conn()
    row = conn.execute(f"SELECT user_id FROM {table} WHERE id = ?", (diag_id,)).fetchone()
    conn.close()

    if row[0] != session['user_id']:
        flash("⛔ You do not have permission to update this diagnosis!", "danger")
        return redirect(f"/diagnosis_detail?id={diag_id}")

    conn = get_db_conn()
    conn.execute(f"UPDATE {table} SET patient_id = ? WHERE id = ?", (new_patient, diag_id))
    conn.commit()
    conn.close()
    flash("Update complete.", "success")
    return redirect(f"/diagnosis_detail?tag={tag}&id={diag_id}")

@app.route("/share_diagnosis", methods=["POST"])
@limiter.limit("3 per minute", methods=["POST"]) 
def share_diagnosis():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    diag_id = request.form.get("id")
    tag = request.form.get("tag")
    share_to_user = request.form.get("user_id")

    # Chọn bảng dựa vào tag
    table = "diagnoses" if tag == "diag" else "qa_interactions"

    conn = get_db_conn()
    row = conn.execute(f"SELECT user_id, share_to FROM {table} WHERE id = ?", (diag_id,)).fetchone()
    user_email = conn.execute("SELECT email FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    conn.close()

    if row[0] != session['user_id'] and row[1] != user_email[0]:
        flash("⛔ You do not have permission to share this diagnosis!", "danger")
        return redirect(f"/diagnosis_detail?id={diag_id}")
    
    conn = get_db_conn()
    conn.execute(f"UPDATE {table} SET share_to = ?, sharer = ?, accept_share = 0 WHERE id = ?", (share_to_user, session['user_id'], diag_id))
    conn.commit()
    conn.close()
    flash("Share complete.", "success")
    return redirect(f"/diagnosis_detail?tag={tag}&id={diag_id}")

@app.route('/diagnose', methods=['GET','POST'])
@limiter.limit("3 per minute", methods=["POST"]) 
def diagnose():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    show_patient_management = False
    isDoctor = False
    if (session['user_role'] == 'doctor'):
        isDoctor = True
        show_patient_management = True

    if request.method == 'GET':
        conn = get_db_conn()
        patients = conn.execute("SELECT id, name FROM patients WHERE creator_ID = ?", (session['user_id'],)).fetchall()

        return render_template('diagnosis.html', notifications=g.notifications, patient_id=session['user_id'], isDoctor=isDoctor, patients=patients, show_patient_management=show_patient_management, api_host=WEB_SERVER_HOST, img_host=IMG_SERVER_HOST)

    # POST: lưu file và request vào DB
    file = request.files.get('file')
    model_name = request.form.get('model')
    patient_id = request.form.get('patient_id')

    if not file or not model_name or not patient_id:
        return jsonify({"error": "Thiếu file, model hoặc mã bệnh nhân"}), 400

    conn = get_db_conn()
    if str(patient_id).startswith("BN_"):
        user_patient_id = str(patient_id)[3:]
        patient = conn.execute(
            "SELECT id, full_name FROM users WHERE id = ?",
            (user_patient_id,)
        ).fetchone()
        if int(user_patient_id) != int(session['user_id']):
            patient = False
    else:
        patient = conn.execute(
            "SELECT * FROM patients WHERE id = ? AND creator_id = ?",
            (patient_id, session['user_id'])
        ).fetchone()

    conn.close()

    if not patient and str(patient_id) != "0":
        return jsonify({"error": "Mã bệnh nhân không tồn tại hoặc bạn không có quyền"}), 400

    filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
    if not allowed_ext(filename):
                return jsonify({"error": "Invalid format"})
    
    file.save(os.path.join(UPLOAD_FOLDER, filename))

    try:
        # Gửi task vào Celery
        task = call_diagnosis_from_ai_server.apply_async(args=[filename, patient_id, model_name, session['user_id']])
    except requests.RequestException as e:
        return jsonify({"error": "Lỗi kết nối API"}), 500
    finally:
        pass

    return jsonify({"task_id": task.id, "status": "queued"}), 200


# ---------------- Vision QA ----------------
@app.route('/vision-qa', methods=['GET','POST'])
@limiter.limit("2 per 10 minutes", methods=["POST"]) 
def vision_qa():
    if ('user_id' not in session) or ('user_role' not in session):
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))
    show_patient_management = False
    isDoctor = False
    if (session['user_role'] == 'doctor'):
        show_patient_management = True
        isDoctor = True

    if request.method == 'GET':
        conn = get_db_conn()
        patients = conn.execute("SELECT id, name FROM patients WHERE creator_ID = ?", (session['user_id'],)).fetchall()
        conn.close()
        return render_template('vision_qa.html', notifications=g.notifications, isDoctor=isDoctor, patient_id=session['user_id'], patients=patients, show_patient_management=show_patient_management, api_host=WEB_SERVER_HOST, img_host=IMG_SERVER_HOST)

    file = request.files.get('file')
    question = request.form.get('question')
    model_name = request.form.get('model')
    patient_id = request.form.get('patient_id')

    if not file or not question:
        return jsonify({"error": "Thiếu file hoặc câu hỏi"}), 400

    conn = get_db_conn()
    if str(patient_id).startswith("BN_"):
        user_patient_id = str(patient_id)[3:]
        patient = conn.execute(
            "SELECT id, full_name FROM users WHERE id = ?",
            (user_patient_id,)
        ).fetchone()
        if int(user_patient_id) != int(session['user_id']):
            patient = False
    else:
        patient = conn.execute(
            "SELECT * FROM patients WHERE id = ? AND creator_id = ?",
            (patient_id, session['user_id'])
        ).fetchone()

    conn.close()

    if not patient and str(patient_id) != "0":
        return jsonify({"error": "Mã bệnh nhân không tồn tại hoặc bạn không có quyền"}), 400

    filename = f"vqa_{uuid.uuid4()}_{secure_filename(file.filename)}"
    if not allowed_ext(filename):
                return jsonify({"error": "Invalid format"})
    file.save(os.path.join(UPLOAD_FOLDER, filename))

    try:
        # Gửi task vào Celery
        task = call_vision_qa_from_ai_server.apply_async(args=[filename, question, patient_id, model_name, session['user_id']])
    except requests.RequestException as e:
        return jsonify({"error": "Lỗi kết nối API"}), 500
    finally:
        pass

    return jsonify({"task_id": task.id, "status": "queued"})


# ---------------- Main ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
