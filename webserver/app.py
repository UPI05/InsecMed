from flask import Flask, render_template, render_template_string, request, jsonify, redirect, url_for, flash, session
import sqlite3, os, secrets, requests
from datetime import datetime
from celery import Celery
import uuid
from PIL import Image
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# server host
WEB_SERVER_HOST = 'http://10.102.196.113'
AI_SERVER_HOST = 'http://10.102.196.113:8080'

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
                  prediction TEXT,
                  probability REAL,
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

init_db()

def get_db_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn
# -----------------Celery ----------------
@celery.task(bind=True)
def call_diagnosis_from_ai_server(self, filename, patient_id, model_name, user_id):
    # Gọi API server để inference
    files = {'file': open(os.path.join(UPLOAD_FOLDER, filename), 'rb')}
    data = {'model': model_name}
    resp = requests.post(f"{AI_SERVER_HOST}/diagnose", data=data, files=files)
    results = resp.json()

    # Lưu vào database
    max_result = max(results, key=lambda x: x['score'])
    conn = get_db_conn()
    conn.execute(
        "INSERT INTO diagnoses (user_id, patient_id, model, image_filename, prediction, probability, timestamp) VALUES (?,?,?,?,?,?,?)",
        (user_id, patient_id, model_name, filename, max_result['label'], max_result['score'], datetime.now())
    )
    conn.commit()
    conn.close()

    return results

@celery.task(bind=True)
def call_vision_qa_from_ai_server(self, filename, question, patient_id, model_name, user_id):
    # Gọi API server để inference
    files = {'file': open(os.path.join(UPLOAD_FOLDER, filename), 'rb')}
    data = {'question': question, 'model': model_name}
    resp = requests.post(f"{AI_SERVER_HOST}/vqa-diagnose", data=data, files=files)
    results = resp.json()
    # Lưu vào database
    conn = get_db_conn()
    conn.execute(
        "INSERT INTO qa_interactions (user_id, patient_id, model, image_filename, question, answer, timestamp) VALUES (?,?,?,?,?,?,?)",
        (user_id, patient_id, model_name, filename, question, results['answer'], datetime.now())
    )
    conn.commit()
    conn.close()

    return results


@app.route('/diagnoseStatus/<task_id>')
@limiter.limit("120 per minute")
def task_diagnosis_status(task_id):
    task = call_diagnosis_from_ai_server.AsyncResult(task_id)
    if task.state == 'PENDING':
        return jsonify({"status": "queued"})
    elif task.state == 'SUCCESS':
        return jsonify({"status": "finished", "result": task.result})
    elif task.state == 'FAILURE':
        return jsonify({"status": "failed", "error": str(task.info)})
    else:
        return jsonify({"status": task.state})

@app.route('/vqaStatus/<task_id>')
@limiter.limit("60 per minute")
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

        from flask_bcrypt import Bcrypt
        bcrypt = Bcrypt(app)
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

        filename = None
        if profile_pic and profile_pic.filename:
            filename = f"{uuid.uuid4()}_{profile_pic.filename}"
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
            filename = f"{uuid.uuid4()}_{profile_pic.filename}"
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
    return render_template('profile.html', isDoctor=isDoctor, user=user, show_patient_management=show_patient_management)

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
    c.execute("SELECT patient_id, model,image_filename,prediction,probability,timestamp FROM diagnoses WHERE user_id=? ORDER BY timestamp DESC", (session['user_id'],))
    diagnoses = [dict(row) for row in c.fetchall()]

    # QA interactions
    c.execute("SELECT patient_id,model,image_filename,question,answer,timestamp FROM qa_interactions WHERE user_id=? ORDER BY timestamp DESC", (session['user_id'],))
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

    c.execute("SELECT COUNT(*) FROM qa_interactions WHERE user_id=?", (session['user_id'],))
    total_qa = c.fetchone()[0]

    conn.close()
    
    return render_template('history.html', isDoctor=isDoctor, show_patient_management=show_patient_management, diagnoses=diagnoses[:20], qa_interactions=qa_interactions[:20],
                           stats={"total_diagnoses":total_diagnoses,"skin_cancer":skin_cancer,
                                  "pneumonia":pneumonia,"breast_cancer":breast_cancer,"total_qa":total_qa})

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
    return render_template('pending_cases.html', isDoctor=isDoctor, api_host=WEB_SERVER_HOST, show_patient_management=show_patient_management)

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
    return render_template("patient_management.html", isDoctor=True, show_patient_management=True, patients=patients)


@app.route("/patients/add", methods=["POST"])
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


# ---------------- Diagnosis ----------------
@app.route('/diagnose', methods=['GET','POST'])
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
        conn.close()
        return render_template('diagnosis.html', patient_id=session['user_id'], isDoctor=isDoctor, patients=patients, show_patient_management=show_patient_management, api_host=WEB_SERVER_HOST)

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

    if not patient:
        return jsonify({"error": "Mã bệnh nhân không tồn tại hoặc bạn không có quyền"}), 400

    try:
        image = Image.open(file)
    except Exception as e:
        return jsonify({"error": f"Lỗi đọc ảnh: {e}"}), 400

    filename = f"{uuid.uuid4()}_{file.filename}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))

    try:
        # Gửi task vào Celery
        task = call_diagnosis_from_ai_server.apply_async(args=[filename, patient_id, model_name, session['user_id']])
    except requests.RequestException as e:
        return jsonify({"error": f"Lỗi kết nối API: {e}"}), 500
    finally:
        pass

    return jsonify({"task_id": task.id, "status": "queued"})


# ---------------- Vision QA ----------------
@app.route('/vision-qa', methods=['GET','POST'])
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
        return render_template('vision_qa.html', isDoctor=isDoctor, patient_id=session['user_id'], patients=patients, show_patient_management=show_patient_management, api_host=WEB_SERVER_HOST)

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

    if not patient:
        return jsonify({"error": "Mã bệnh nhân không tồn tại hoặc bạn không có quyền"}), 400

    try:
        image = Image.open(file)
    except Exception as e:
        return jsonify({"error": f"Lỗi đọc ảnh: {e}"}), 400

    filename = f"vqa_{uuid.uuid4()}_{file.filename}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))

    try:
        # Gửi task vào Celery
        task = call_vision_qa_from_ai_server.apply_async(args=[filename, question, patient_id, model_name, session['user_id']])
    except requests.RequestException as e:
        return jsonify({"error": f"Lỗi kết nối API: {e}"}), 500
    finally:
        pass

    return jsonify({"task_id": task.id, "status": "queued"})


# ---------------- Main ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
