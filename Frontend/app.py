from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime
import uuid

api_host = 'http://10.102.196.113:8080'
app = Flask(__name__)

# Ensure uploads directory exists
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

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

@app.route('/')
def index():
    return render_template('index.html', api_host=api_host)

@app.route('/vision-qa')
def vision_qa():
    return render_template('vision_qa.html', api_host=api_host)

@app.route('/history')
def history():
    conn = sqlite3.connect('history.db')
    c = conn.cursor()
    
    # Fetch diagnoses
    c.execute("SELECT model, image_filename, prediction, probability, timestamp FROM diagnoses ORDER BY timestamp DESC")
    diagnoses = [{"model": row[0], "image_filename": row[1], "prediction": row[2], 
                  "probability": row[3], "timestamp": row[4]} for row in c.fetchall()][:10]
    
    # Fetch Q&A interactions
    c.execute("SELECT image_filename, question, answer, timestamp FROM qa_interactions ORDER BY timestamp DESC")
    qa_interactions = [{"image_filename": row[0], "question": row[1], "answer": row[2], 
                        "timestamp": row[3]} for row in c.fetchall()][:10]
    
    # Calculate statistics
    c.execute("SELECT COUNT(*) FROM diagnoses")
    total_diagnoses = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM diagnoses WHERE model = 'skin_cancer'")
    skin_cancer = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM diagnoses WHERE model = 'pneumonia'")
    pneumonia = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM diagnoses WHERE model = 'breast_cancer'")
    breast_cancer = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM qa_interactions")
    total_qa = c.fetchone()[0]
    
    stats = {
        "total_diagnoses": total_diagnoses,
        "skin_cancer": skin_cancer,
        "pneumonia": pneumonia,
        "breast_cancer": breast_cancer,
        "total_qa": total_qa
    }
    
    conn.close()
    return render_template('history.html', diagnoses=diagnoses, qa_interactions=qa_interactions, stats=stats)


if __name__ == '__main__':
    app.run(debug=True, port=5000)