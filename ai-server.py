from flask import Flask, request, jsonify
from transformers import pipeline
from PIL import Image
import uuid, os, io
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=["http://10.102.196.113"], supports_credentials=True) # Allow all origins for API server
# Folders
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load models
skin_cancer_model = pipeline("image-classification", model="Anwarkh1/Skin_Cancer-Image_Classification")
pneumonia_model = pipeline("image-classification", model="lxyuan/vit-xray-pneumonia-classification")
breast_cancer_model = pipeline("image-classification", model="Falah/vit-base-breast-cancer")

# ----- Diagnosis -----
@app.route("/diagnose", methods=["POST"])
def diagnose():
    model_name = request.form.get("model")
    file = request.files.get("file")

    if not model_name or not file:
        return jsonify({"error":"Thiếu model hoặc file ảnh"}),400

    try:
        image = Image.open(file)
    except Exception as e:
        return jsonify({"error":f"Lỗi đọc ảnh: {e}"}),400

    filename = f"{uuid.uuid4()}_{file.filename}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))

    if model_name=="skin_cancer_vit":
        results = skin_cancer_model(image)
    elif model_name=="pneumonia_vit":
        results = pneumonia_model(image)
    elif model_name=="breast_cancer_vit":
        results = breast_cancer_model(image)
    else:
        return jsonify({"error":"Model không hợp lệ"}),400

    return jsonify(results)

@app.route("/vqa-diagnose", methods=["POST"])
def vqa_diagnose():
    return jsonify({"answer":"Temporarily closed"}),503


if __name__=="__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
