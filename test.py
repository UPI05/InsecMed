# Use a pipeline as a high-level helper
from transformers import pipeline

pipe = pipeline("image-classification", model="DunnBC22/vit-base-patch16-224-in21k_covid_19_ct_scans")
results=pipe("https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/hub/parrots.png")
# In kết quả
for r in results:
    print(f"Label: {r['label']}, Score: {r['score']:.4f}")