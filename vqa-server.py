from flask import Flask, request, jsonify
from huggingface_hub import login
from transformers import pipeline, AutoProcessor, AutoModelForImageTextToText
from PIL import Image
import torch
import base64
import io

# =========================
# Hugging Face login
# =========================
login("")

device = "cuda" if torch.cuda.is_available() else "cpu"

app = Flask(__name__)

# =========================
# Utils
# =========================
def image_from_base64(b64_string: str) -> Image.Image:
    if "," in b64_string:  # data:image/png;base64,...
        b64_string = b64_string.split(",")[1]
    image_bytes = base64.b64decode(b64_string)
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")

# =========================
# 1️⃣ MedGemma
# =========================
medgemma_pipe = pipeline(
    "image-text-to-text",
    model="google/medgemma-4b-it",
    dtype=torch.bfloat16 if device == "cuda" else torch.float32,
    device=device
)

@app.route("/medgemma", methods=["POST"])
def medgemma_api():
    data = request.get_json()

    image = image_from_base64(data["image_base64"])
    prompt = data.get("question", "Describe this X-ray")

    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are an expert radiologist."}]
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "image": image}
            ]
        }
    ]

    output = medgemma_pipe(
        text=messages,
        max_new_tokens=300
    )

    result = output[0]["generated_text"][-1]["content"]
    return jsonify({"result": result})

# =========================
# 2️⃣ IDEFICS Medical VQA
# =========================
idefics_processor = AutoProcessor.from_pretrained("HuggingFaceM4/idefics-9b")
idefics_model = AutoModelForImageTextToText.from_pretrained(
    "Shashwath01/Idefic_medical_VQA_merged_4bit",
    device_map=device
)

@app.route("/idefics", methods=["POST"])
def idefics_api():
    data = request.get_json()

    image = image_from_base64(data["image_base64"])
    question = data["question"]

    tokenizer = idefics_processor.tokenizer
    bad_words_ids = tokenizer(
        ["<image>", "<fake_token_around_image>"],
        add_special_tokens=False
    ).input_ids

    inputs = idefics_processor(
        images=image,
        text=f"Question: {question}\nAnswer:",
        return_tensors="pt"
    ).to(device)

    generated_ids = idefics_model.generate(
        **inputs,
        max_new_tokens=200,
        bad_words_ids=bad_words_ids,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id
    )

    answer = idefics_processor.batch_decode(
        generated_ids,
        skip_special_tokens=True
    )[0]

    return jsonify({"result": answer})

# =========================
# Health check
# =========================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# =========================
# Run
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)