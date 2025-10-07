from flask import Flask, request, jsonify
from transformers import pipeline, AutoProcessor, AutoModelForImageTextToText
from PIL import Image
import uuid, os
from flask_cors import CORS
import time
import torch
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, origins=["http://10.102.196.113"], supports_credentials=True) # Allow all origins for API server
# Folders
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load models
skin_cancer_model = pipeline("image-classification", model="Anwarkh1/Skin_Cancer-Image_Classification")
pneumonia_model = pipeline("image-classification", model="lxyuan/vit-xray-pneumonia-classification")
breast_cancer_model = pipeline("image-classification", model="Falah/vit-base-breast-cancer")


# Vision qa models

#terminal auth: hf-auth-login
model_id = "google/medgemma-4b-it"

model = AutoModelForImageTextToText.from_pretrained(
    model_id,
    torch_dtype=torch.bfloat16,
    device_map="auto",
)
processor = AutoProcessor.from_pretrained(model_id)



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

    filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
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
    model_name = request.form.get("model")
    question = request.form.get("question")
    file = request.files.get("file")

    if not file or not model_name or not question:
        return "Invalid", 400

    # Đọc file bằng PIL.Image
    image = Image.open(file.stream)
    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are an expert radiologist."}]
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image", "image": image}
            ]
        }
    ]

    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt"
    ).to(model.device, dtype=torch.bfloat16)

    input_len = inputs["input_ids"].shape[-1]

    with torch.inference_mode():
        generation = model.generate(**inputs, max_new_tokens=500, do_sample=False)
        generation = generation[0][input_len:]

    decoded = processor.decode(generation, skip_special_tokens=True)
    return jsonify({"answer": decoded}),200

    return jsonify({"answer":"Tính năng này tạm thời bị đóng do chưa có GPU =))"}),200


if __name__=="__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
