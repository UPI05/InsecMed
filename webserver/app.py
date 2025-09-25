from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
import sqlite3, os, secrets, requests
from datetime import datetime
import uuid
from PIL import Image

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# server host
WEB_SERVER_HOST = 'http://10.102.196.113'
AI_SERVER_HOST = 'http://10.102.196.113:8080'

# Folders
PROFILE_PIC_FOLDER = 'static/profile_pics'
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database
DB_FILE = 'insecmed.db'

def get_db_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------- Routes ----------------

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone')
        profile_pic = request.files.get('profile_pic')

        if not full_name or not email or not password:
            flash("Họ tên, email, mật khẩu bắt buộc.", "danger")
            return redirect(url_for('register'))

        conn = get_db_conn()
        c = conn.cursor()
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

        c.execute("INSERT INTO users (full_name,email,phone,profile_pic,password_hash) VALUES (?,?,?,?,?)",
                  (full_name,email,phone,filename,password_hash))
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
        c.execute("SELECT id,password_hash FROM users WHERE email=?", (email,))
        user = c.fetchone()
        conn.close()

        from flask_bcrypt import Bcrypt
        bcrypt = Bcrypt(app)

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            flash("Đăng nhập thành công!", "success")
            return redirect(url_for('pending_cases'))
        else:
            flash("Email hoặc mật khẩu không đúng.", "danger")
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("Đã đăng xuất.", "success")
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET','POST'])
def profile():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))

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
    return render_template('profile.html', user=user)

@app.route('/history')
def history():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))

    conn = get_db_conn()
    c = conn.cursor()

    # Diagnoses
    c.execute("SELECT model,image_filename,prediction,probability,timestamp FROM diagnoses WHERE user_id=? ORDER BY timestamp DESC", (session['user_id'],))
    diagnoses = [dict(row) for row in c.fetchall()]

    # QA interactions
    c.execute("SELECT image_filename,question,answer,timestamp FROM qa_interactions WHERE user_id=? ORDER BY timestamp DESC", (session['user_id'],))
    qa_interactions = [dict(row) for row in c.fetchall()]

    # Stats
    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=?", (session['user_id'],))
    total_diagnoses = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='skin_cancer'", (session['user_id'],))
    skin_cancer = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='pneumonia'", (session['user_id'],))
    pneumonia = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM diagnoses WHERE user_id=? AND model='breast_cancer'", (session['user_id'],))
    breast_cancer = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM qa_interactions WHERE user_id=?", (session['user_id'],))
    total_qa = c.fetchone()[0]

    conn.close()
    print(diagnoses)
    return render_template('history.html', diagnoses=diagnoses, qa_interactions=qa_interactions,
                           stats={"total_diagnoses":total_diagnoses,"skin_cancer":skin_cancer,
                                  "pneumonia":pneumonia,"breast_cancer":breast_cancer,"total_qa":total_qa})

@app.route('/pending-cases')
def pending_cases():
    return render_template('pending_cases.html', api_host=WEB_SERVER_HOST)

@app.route('/api/pending_cases')
def api_pending_cases():
    # Dữ liệu mẫu
    CASES = [
        {"id": 1, "patient_name": "Nguyen Van A", "disease": "Ung thư da", "uploaded_at": "2025-09-25 10:20", "prediction": None},
        {"id": 2, "patient_name": "Tran Thi B", "disease": "Ung thư phổi", "uploaded_at": "2025-09-24 15:45", "prediction": "Không có vấn đề"},
        {"id": 3, "patient_name": "Le Van C", "disease": "Ung thư vú", "uploaded_at": "2025-09-23 09:10", "prediction": None}
    ]

    # Chỉ trả những case chưa có prediction
    pending_cases = [c for c in CASES if c['prediction'] is None]
    return jsonify(pending_cases)

# ---------------- Diagnosis ----------------
@app.route('/diagnose', methods=['GET','POST'])
def diagnose():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))

    if request.method == 'GET':
        return render_template('diagnosis.html', api_host=WEB_SERVER_HOST)

    
    # POST: lưu file và request vào DB
    file = request.files.get('file')
    model_name = request.form.get('model')

    if not file or not model_name:
        return jsonify({"error": "Thiếu file hoặc model"}), 400

    try:
        image = Image.open(file)
    except Exception as e:
        return jsonify({"error": f"Lỗi đọc ảnh: {e}"}), 400

    filename = f"{uuid.uuid4()}_{file.filename}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))

    # Gọi API server để inference
    files = {'file': open(os.path.join(UPLOAD_FOLDER, filename), 'rb')}
    data = {'model': model_name}
    try:
        resp = requests.post(f"{AI_SERVER_HOST}/diagnose", data=data, files=files)
        results = resp.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Lỗi kết nối API: {e}"}), 500
    finally:
        files['file'].close()

    # Lưu vào database
    max_result = max(results, key=lambda x: x['score'])
    conn = get_db_conn()
    conn.execute(
        "INSERT INTO diagnoses (user_id,model,image_filename,prediction,probability,timestamp) VALUES (?,?,?,?,?,?)",
        (session['user_id'], model_name, filename, max_result['label'], max_result['score'], datetime.now())
    )
    conn.commit()
    conn.close()

    return jsonify(results)

# ---------------- Vision QA ----------------
@app.route('/vision-qa', methods=['GET','POST'])
def vision_qa():
    if 'user_id' not in session:
        flash("Vui lòng đăng nhập", "danger")
        return redirect(url_for('index'))

    if request.method == 'GET':
        return render_template('vision_qa.html', api_host=WEB_SERVER_HOST)

    file = request.files.get('file')
    question = request.form.get('question')

    if not file or not question:
        return jsonify({"error": "Thiếu file hoặc câu hỏi"}), 400

    try:
        image = Image.open(file)
    except Exception as e:
        return jsonify({"error": f"Lỗi đọc ảnh: {e}"}), 400

    filename = f"{uuid.uuid4()}_{file.filename}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))

    # Gọi API server để trả lời (hiện tại tạm thời đóng)
    files = {'file': open(os.path.join(UPLOAD_FOLDER, filename), 'rb')}
    data = {'question': question}
    try:
        resp = requests.post(f"{AI_SERVER_HOST}/vqa-diagnose", data=data, files=files)
        results = resp.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Lỗi kết nối API: {e}"}), 500
    finally:
        files['file'].close()

    # Lưu vào database
    conn = get_db_conn()
    conn.execute(
        "INSERT INTO qa_interactions (user_id,image_filename,question,answer,timestamp) VALUES (?,?,?,?,?)",
        (session['user_id'], filename, question, results.get('answer','Temporarily closed'), datetime.now())
    )
    conn.commit()
    conn.close()

    return jsonify(results)


# ---------------- Main ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
