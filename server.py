from flask import Flask, request, jsonify, session
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from transformers import pipeline
import sqlite3
import uuid, os, io, re
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from PIL import Image

app = Flask(__name__)
app.secret_key = ''
bcrypt = Bcrypt(app)
CORS(app, origins=["http://10.102.196.113"], supports_credentials=True)  # Allow all origins for API server

# Rate limiter
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["100 per hour"])

# Models
skin_cancer_model = pipeline("image-classification", model="Anwarkh1/Skin_Cancer-Image_Classification")
pneumonia_model = pipeline("image-classification", model="lxyuan/vit-xray-pneumonia-classification")
breast_cancer_model = pipeline("image-classification", model="Falah/vit-base-breast-cancer")

# Folders
UPLOAD_FOLDER = 'static/uploads'
PROFILE_PIC_FOLDER = 'static/profile_pics'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)

# ---------------- Database ----------------
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
                  password_hash TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS diagnoses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  model TEXT,
                  image_filename TEXT,
                  prediction TEXT,
                  probability REAL,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS qa_interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  image_filename TEXT,
                  question TEXT,
                  answer TEXT,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()

init_db()

# ---------------- Routes ----------------

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"msg": "pong"})

# ----- User Auth -----
@app.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    phone = request.form.get('phone')
    profile_pic = request.files.get('profile_pic')

    if not full_name or not email or not password:
        return jsonify({"error": "Họ tên, email, mật khẩu bắt buộc."}), 400
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Email không hợp lệ."}), 400
    if phone and not re.match(r"^\+?\d{10,15}$", phone):
        return jsonify({"error": "Số điện thoại không hợp lệ."}), 400

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email=?", (email,))
    if c.fetchone():
        conn.close()
        return jsonify({"error": "Email đã đăng ký."}), 400

    password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    filename = None
    if profile_pic and profile_pic.filename:
        filename = f"{uuid.uuid4()}_{profile_pic.filename}"
        profile_pic.save(os.path.join(PROFILE_PIC_FOLDER, filename))

    c.execute("INSERT INTO users (full_name,email,phone,profile_pic,password_hash) VALUES (?,?,?,?,?)",
              (full_name,email,phone,filename,password_hash))
    conn.commit()
    conn.close()
    return jsonify({"message": "Đăng ký thành công!"}), 201

@app.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    if not email or not password:
        return jsonify({"error": "Email và mật khẩu bắt buộc."}), 400

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id,password_hash FROM users WHERE email=?", (email,))
    user = c.fetchone()
    conn.close()

    if user and bcrypt.check_password_hash(user[1], password):
        session['user_id'] = user[0]
        return jsonify({"message": "Đăng nhập thành công!"}), 200
    return jsonify({"error": "Email hoặc mật khẩu không đúng."}), 401

@app.route("/profile", methods=["GET","POST"])
@limiter.limit("10 per minute")
def profile():
    if 'user_id' not in session:
        return jsonify({"error":"Vui lòng đăng nhập"}),401
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if request.method=="GET":
        c.execute("SELECT full_name,email,phone,profile_pic FROM users WHERE id=?",(session['user_id'],))
        u = c.fetchone()
        conn.close()
        return jsonify({"full_name":u[0],"email":u[1],"phone":u[2],"profile_pic":u[3]}),200
    # POST update
    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    password = request.form.get('password')
    profile_pic = request.files.get('profile_pic')
    c.execute("SELECT profile_pic FROM users WHERE id=?",(session['user_id'],))
    old_pic = c.fetchone()[0]
    filename = old_pic
    if profile_pic and profile_pic.filename:
        filename = f"{uuid.uuid4()}_{profile_pic.filename}"
        profile_pic.save(os.path.join(PROFILE_PIC_FOLDER, filename))
        if old_pic and os.path.exists(os.path.join(PROFILE_PIC_FOLDER, old_pic)):
            os.remove(os.path.join(PROFILE_PIC_FOLDER, old_pic))
    if password:
        phash = bcrypt.generate_password_hash(password).decode('utf-8')
        c.execute("UPDATE users SET full_name=?, phone=?, profile_pic=?, password_hash=? WHERE id=?",
                  (full_name,phone,filename,phash,session['user_id']))
    else:
        c.execute("UPDATE users SET full_name=?, phone=?, profile_pic=? WHERE id=?",
                  (full_name,phone,filename,session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({"message":"Cập nhật thành công"}),200

@app.route("/logout", methods=["POST"])
def logout():
    session.pop('user_id',None)
    return jsonify({"message":"Đăng xuất thành công"}),200

# ----- Diagnosis -----
@app.route("/diagnose", methods=["POST"])
@limiter.limit("10 per minute")
def diagnose():
    if 'user_id' not in session:
        return jsonify({"error":"Vui lòng đăng nhập"}),401

    model_name = request.form.get("model")
    file = request.files.get("file")
    if not model_name or not file:
        return jsonify({"error":"Thiếu model hoặc file ảnh"}),400

    try:
        image = Image.open(io.BytesIO(file.read()))
    except Exception as e:
        return jsonify({"error":f"Lỗi đọc ảnh: {e}"}),400

    filename = f"{uuid.uuid4()}_{file.filename}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))

    if model_name=="skin_cancer":
        results = skin_cancer_model(image)
    elif model_name=="pneumonia":
        results = pneumonia_model(image)
    elif model_name=="breast_cancer":
        results = breast_cancer_model(image)
    else:
        return jsonify({"error":"Model không hợp lệ"}),400

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    max_result = max(results,key=lambda x:x['score'])
    c.execute("INSERT INTO diagnoses (user_id,model,image_filename,prediction,probability,timestamp) VALUES (?,?,?,?,?,?)",
              (session['user_id'],model_name,filename,max_result['label'],max_result['score'],datetime.now()))
    conn.commit()
    conn.close()

    return jsonify(results)

@app.route('/vqa-diagnose', methods=['POST'])
@limiter.limit("10 per minute")
def vqa_diagnose():
    return jsonify({"answer":"Temporarily closed"}),503

if __name__=="__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
