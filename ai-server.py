from flask import Flask, request, jsonify
from transformers import pipeline, AutoProcessor, AutoModelForImageTextToText
from PIL import Image
import uuid, os
from flask_cors import CORS
import time
import torch
from werkzeug.utils import secure_filename
import paramiko
import json
import getpass
import markdown
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIG =====
KEY_PATH = "/home/d1l1th1um/Desktop/id_rsa"
CMS_HOST = "cms-ssh.sc.imr.tohoku.ac.jp"
GPU_HOST = "gpu.sc.imr.tohoku.ac.jp"
USER = "inomar01"
REMOTE_DIR = "/home/inomar01/Hieu"
REMOTE_IMAGE = f"{REMOTE_DIR}/upload"
LOCAL_IMAGE = "/home/d1l1th1um/Desktop/demo/vqa-image"

PASS_PHRASE = os.getenv("PASS_PHRASE")
GPU_PASSWD = os.getenv("GPU_PASSWD")

app = Flask(__name__)
CORS(app, origins=["http://10.102.196.113"], supports_credentials=True) # Allow all origins for API server
# Folders
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load models
skin_cancer_model = pipeline("image-classification", model="Anwarkh1/Skin_Cancer-Image_Classification")
pneumonia_model = pipeline("image-classification", model="lxyuan/vit-xray-pneumonia-classification")
breast_cancer_model = pipeline("image-classification", model="Falah/vit-base-breast-cancer")
covid19_model = pipeline("image-classification", model="DunnBC22/vit-base-patch16-224-in21k_covid_19_ct_scans")
brain_tumor_model_vit = pipeline("image-classification", model="DunnBC22/vit-base-patch16-224-in21k_brain_tumor_diagnosis")
brain_tumor_model_resnet50 = pipeline("image-classification", model="Alia-Mohammed/resnet-50-finetuned-brain-tumor")
# Vision qa models

#terminal auth: hf-auth-login
#model_id = "google/medgemma-4b-it"
#
#model = AutoModelForImageTextToText.from_pretrained(
#    model_id,
#    torch_dtype=torch.bfloat16,
#    device_map="auto",
#)
#processor = AutoProcessor.from_pretrained(model_id)

def normalize_results(results):
    # Nếu là dict duy nhất → bọc vào list
    if isinstance(results, dict):
        return [results]
    return results


def parse_model_names(model_name_str):
    if not model_name_str:
        return []

    # Tách theo dấu phẩy và làm sạch
    models = [m.strip() for m in model_name_str.split(",")]

    # Loại bỏ chuỗi rỗng + loại trùng nhau, giữ đúng thứ tự xuất hiện
    unique_models = []
    seen = set()

    for m in models:
        if m and m not in seen:
            unique_models.append(m)
            seen.add(m)

    return unique_models


# ----- Diagnosis -----
@app.route("/diagnose", methods=["POST"])
def diagnose():
    model_names = request.form.get("model")
    file = request.files.get("file")

    print(file.filename)

    if not model_names or not file:
        return jsonify({"error":"Thiếu model hoặc file ảnh"}),400

    try:
        image = Image.open(file)
    except Exception as e:
        return jsonify({"error":f"Lỗi đọc ảnh: {e}"}),400

    filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
    image.save(os.path.join(UPLOAD_FOLDER, filename))

    models = parse_model_names(model_names)

    final_results = []

    model_map = {
        "skin_cancer_vit": "Ung thư da",
        "pneumonia_vit": "Viêm phổi",
        "covid19_vit": "Covid-19",
        "breast_cancer_vit": "Ung thư vú",
        "brain_tumor_vit": "U não - A",
        "brain_tumor_resnet": "U não - B"
    }

    for model_name in models:
        if model_name=="skin_cancer_vit":
            results = normalize_results(skin_cancer_model(image))
            label_map = {
                "melanocytic_Nevi": "Nốt ruồi lành tính",
                "benign_keratosis-like_lesions": "Tổn thương sừng lành tính",
                "melanoma": "U ác tính",
                "actinic_keratoses": "Dày sừng ánh sáng",
                "basal_cell_carcinoma": "Ung thư biểu mô tế bào đáy"
            }

        elif model_name=="pneumonia_vit":
            results = normalize_results(pneumonia_model(image))
            label_map = {
                "NORMAL": "Phổi bình thường",
                "PNEUMONIA": "Viêm phổi"
            }

        elif model_name=="covid19_vit":
            results = normalize_results(covid19_model(image))
            label_map = {
                "CT_COVID": "Hình ảnh CT có dấu hiệu COVID-19",
                "CT_NonCOVID": "Hình ảnh CT không có dấu hiệu COVID-19"
            }

        elif model_name=="breast_cancer_vit":
            results = normalize_results(breast_cancer_model(image))
            label_map = {
                "class0": "Không bị ung thư vú",
                "class1": "Bị ung thư vú"
            }
        elif model_name=='brain_tumor_vit':
            results = normalize_results(brain_tumor_model_vit(image))
            label_map = {
                "yes": "Bị u não",
                "no": "Không bị u não"
            }
        elif model_name=='brain_tumor_resnet':
            results = normalize_results(brain_tumor_model_resnet50(image))
            label_map = {
                "meningioma": "U màng não",
                "pituitary": "U tuyến yên",
                "glioma": "U tế bào thần kinh đệm",
                "notumor": "Không có khối u"
            }
        else:
            return jsonify({"error":"Model không hợp lệ"}),400

        # Áp dụng filter mapping
        filtered_results = []
        for r in results:
            new_label = label_map.get(r["label"], r["label"])
            filtered_results.append({
                "originLabel": r["label"],
                "label": new_label,
                "score": round(r["score"], 4)
            })
        best = max(filtered_results, key=lambda x: x["score"])
        new_model_name = model_map.get(model_name, model_name)
        final_results.append({
            "model": new_model_name,
            "top_label": best["label"],
            "top_label_origin": best["originLabel"],
            "top_score": best["score"],
            "details": filtered_results
        })

    return jsonify({
        "status": "finished",
        "results": final_results
    })

@app.route("/vqa-diagnose", methods=["POST"])
def vqa_diagnose():
    model_name = request.form.get("model")
    question = request.form.get("question")
    file = request.files.get("file")

    print("model: ", model_name)

    if not file or not model_name or not question:
        return "Invalid", 400
    
    ext = os.path.splitext(file.filename)[1].lower()
    
    file.save(LOCAL_IMAGE + ext)

    # ===== COMMAND =====
    curl_cmd = f"""
    cd {REMOTE_DIR} && curl -X POST http://10.200.1.3:5000/{model_name} -F "image=@upload{ext}" -F "question={question}"
    """

    # ===== INPUT SECRETS =====
    key_passphrase = PASS_PHRASE
    gpu_password = GPU_PASSWD

    # ===== SSH TO CMS =====
    print("[*] Connecting to CMS...")
    pkey = paramiko.RSAKey.from_private_key_file(
        KEY_PATH, password=key_passphrase
    )

    cms = paramiko.SSHClient()
    cms.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cms.connect(CMS_HOST, username=USER, pkey=pkey)

    # ===== TUNNEL TO GPU =====
    transport = cms.get_transport()
    dest_addr = (GPU_HOST, 22)
    local_addr = ("127.0.0.1", 0)

    channel = transport.open_channel(
        "direct-tcpip", dest_addr, local_addr
    )

    gpu = paramiko.SSHClient()
    gpu.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    gpu.connect(
        GPU_HOST,
        username=USER,
        password=gpu_password,
        sock=channel
    )

    # ===== UPLOAD IMAGE =====
    print("[*] Uploading image to GPU node...")
    sftp = gpu.open_sftp()

    try:
        sftp.chdir(REMOTE_DIR)
    except IOError:
        sftp.mkdir(REMOTE_DIR)
        sftp.chdir(REMOTE_DIR)

    sftp.put(LOCAL_IMAGE + ext, REMOTE_IMAGE + ext)
    sftp.close()

    # ===== EXEC CURL =====
    print("[*] Running MedGemma request...")
    stdin, stdout, stderr = gpu.exec_command(curl_cmd)

    #gpu.close()
    #cms.close()
    return jsonify({"answer": markdown.markdown(json.loads(stdout.read().decode())['result'])}),200

    # messages = [
    #     {
    #         "role": "system",
    #         "content": [{"type": "text", "text": "You are an expert radiologist."}]
    #     },
    #     {
    #         "role": "user",
    #         "content": [
    #             {"type": "text", "text": question},
    #             {"type": "image", "image": image}
    #         ]
    #     }
    # ]

    # inputs = processor.apply_chat_template(
    #     messages, add_generation_prompt=True, tokenize=True,
    #     return_dict=True, return_tensors="pt"
    # ).to(model.device, dtype=torch.bfloat16)

    # input_len = inputs["input_ids"].shape[-1]

    # with torch.inference_mode():
    #     generation = model.generate(**inputs, max_new_tokens=500, do_sample=False)
    #     generation = generation[0][input_len:]

    # decoded = processor.decode(generation, skip_special_tokens=True)
    # return jsonify({"answer": decoded}),200

    return jsonify({"answer":"Tính năng này tạm thời bị đóng do chưa có GPU =))"}),200


if __name__=="__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
