import requests
import os

EXPLAIN_SERVER_HOST = "http://10.102.196.101:8000/explain"
UPLOAD_FOLDER = 'static/test'
filename = "image.jpg"

model_name='skin,breast,pneu,brain,covid'

# File ảnh cần upload
image_path = "image.jpg"   # đổi thành ảnh của bạn

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

        print(explain_model_name)
        files = {
            "model_kind": (None, explain_model_name),
            "prediction": (None, "Value"),
            "image": (filename, input_file, "image/png")
        }

        response = requests.post(EXPLAIN_SERVER_HOST, files=files)
        if response.content:
            with open(os.path.join(UPLOAD_FOLDER, "explain_"+str(idx)+"_"+filename), "wb") as f:
                f.write(response.content)