import requests

url = "http://127.0.0.1:5000/predict"
files = {"file": open("/home/d1l1th1um/Desktop/demo/Frontend/static/sample.jpg", "rb")}
data = {"model": "pneumonia"}

response = requests.post(url, files=files, data=data)
print(response.json())
