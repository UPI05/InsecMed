from flask import Flask, request, jsonify
from transformers import pipeline, AutoModel, AutoTokenizer, AutoProcessor
import torch
from PIL import Image
import io
from flask_cors import CORS
import sqlite3
import uuid
import os
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# Khởi tạo các pipeline
skin_cancer_model = pipeline("image-classification", model="Anwarkh1/Skin_Cancer-Image_Classification")
pneumonia_model = pipeline("image-classification", model="lxyuan/vit-xray-pneumonia-classification")
breast_cancer_model = pipeline("image-classification", model="Falah/vit-base-breast-cancer")
# -------------VQA----------------
# # 1️⃣ Đường dẫn local model
# # -----------------------------
# model_path = "./bio-medical-multimodal-llama"

# # -----------------------------
# # 2️⃣ Load model và tokenizer
# # -----------------------------
# model_vqa = AutoModel.from_pretrained(
#     model_path,
#     device_map="cpu",           # chạy trên CPU
#     torch_dtype=torch.float32,  # CPU FP32
#     attn_implementation="eager",
#     trust_remote_code=True,
#     local_files_only=True       # chỉ dùng file local
# )

# tokenizer = AutoTokenizer.from_pretrained(
#     model_path,
#     trust_remote_code=True,
#     local_files_only=True
# )
# # -----------------------------
# # 3️⃣ Load processor (xử lý ảnh + text)
# # -----------------------------
# processor = AutoProcessor.from_pretrained(
#     model_path,
#     trust_remote_code=True,
#     local_files_only=True
# )


# Tạo Flask app
app = Flask(__name__)
CORS(app, resources={r"*": {"origins": "*"}})


# Kết nối limiter với Redis để chia sẻ state giữa nhiều worker/instance
limiter = Limiter(
    key_func=get_remote_address,                # Lấy IP client làm khóa
    storage_uri="redis://localhost:6379",       # Redis backend
    default_limits=["15 per hour"]             # Giới hạn mặc định cho toàn app
)
limiter.init_app(app)

# Ensure uploads directory exists
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def call_vision_qa(image_path, question):
    # Load image and prepare inputs
    image = Image.open(image_path).convert("RGB")
    msgs = [{'role': 'user', 'content': [image, question]}]
    res = model_vqa.chat( image=image, msgs=msgs, tokenizer=tokenizer, sampling=False, stream=False )

    return {"answer": f"{res}"}

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS diagnoses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  model TEXT,
                  image_filename TEXT,
                  prediction TEXT,
                  probability REAL,
                  timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS qa_interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  image_filename TEXT,
                  question TEXT,
                  answer TEXT,
                  timestamp DATETIME)''')
    conn.commit()
    conn.close()

init_db()

###
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"msg": "pong"})

@app.route("/diagnose", methods=["POST"])
def diagnose():
    """
    Form-data:
        model: "skin_cancer" | "pneumonia" | "breast_cancer"
        file: <ảnh upload>
    """
    model_name = request.form.get("model")
    file = request.files.get("file")

    if not model_name or not file:
        return jsonify({"error": "Thiếu model hoặc file ảnh"}), 400

    # Đọc ảnh bằng Pillow
    try:
        image = Image.open(io.BytesIO(file.read()))
    except Exception as e:
        return jsonify({"error": f"Lỗi đọc ảnh: {str(e)}"}), 400
    
    # Save image
    filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)
    
    # Chọn model phù hợp
    if model_name == "skin_cancer":
        results = skin_cancer_model(image)
    elif model_name == "pneumonia":
        results = pneumonia_model(image)
    elif model_name == "breast_cancer":
        results = breast_cancer_model(image)
    else:
        return jsonify({"error": "Model không hợp lệ"}), 400
    
    # Save to database
    conn = sqlite3.connect('history.db')
    c = conn.cursor()
    max_result = max(results, key=lambda x: x['score'])
    c.execute("INSERT INTO diagnoses (model, image_filename, prediction, probability, timestamp) VALUES (?, ?, ?, ?, ?)",
              (model_name, filename, max_result['label'], max_result['score'], datetime.now()))
    conn.commit()
    conn.close()

    return jsonify(results)


@app.route('/vqa-diagnose', methods=['POST'])
#@limiter.limit("10 per minute")
def vqaDiagnose():
    return jsonify({"answer": "Temporarily closed!"})
    file = request.files['file']
    question = request.form['question']
    
    # Save image
    filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)
    
    result = call_vision_qa(file_path, question)
    
    # Save to database
    conn = sqlite3.connect('history.db')
    c = conn.cursor()
    c.execute("INSERT INTO qa_interactions (image_filename, question, answer, timestamp) VALUES (?, ?, ?, ?)",
              (filename, question, result['answer'], datetime.now()))
    conn.commit()
    conn.close()
    
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
