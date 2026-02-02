

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os
from datetime import datetime
import google.generativeai as genai
import base64
import json
import re
from pymongo import MongoClient

load_dotenv()

app = Flask(__name__)
CORS(app)

# ---------------- GEMINI ----------------
def initialize_gemini():
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    return genai.GenerativeModel('gemini-1.5-pro')

# ---------------- MONGO ----------------
mongo_client = MongoClient(os.getenv("MONGO_URI"))
mongo_db = mongo_client[os.getenv("DB_NAME")]
records_col = mongo_db["records"]

# ---------------- API ----------------
@app.route('/upload-audio', methods=['POST'])
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file'}), 400

    audio_file = request.files['audio']
    patient_id = request.form.get('patient_id')
    doctor_id = request.form.get('doctor_id')

    os.makedirs('uploads', exist_ok=True)
    file_path = f"uploads/{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    audio_file.save(file_path)

    model = initialize_gemini()

    # Gemini transcription
    with open(file_path, "rb") as f:
        audio_data = f.read()

    audio_b64 = base64.b64encode(audio_data).decode()

    response = model.generate_content([
        "Transcribe this medical audio clearly.",
        {"mime_type": "audio/wav", "data": audio_b64}
    ])

    transcript = response.text

    # Summary
    summary_prompt = f"""
    Create medical summary JSON:
    {{
      "summary":"",
      "medical_condition":"",
      "treatment_plan":"",
      "followup_date":""
    }}
    Text: {transcript}
    """

    summary_res = model.generate_content(summary_prompt)
    txt = summary_res.text
    js = txt[txt.find('{'):txt.rfind('}')+1]
    summary = json.loads(js)

    record = {
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "audio": file_path,
        "transcript": transcript,
        "summary": summary,
        "timestamp": datetime.utcnow()
    }

    records_col.insert_one(record)

    return jsonify(record)


@app.route('/records/<patient_id>')
def get_records(patient_id):
    data = list(records_col.find({"patient_id": patient_id}, {"_id": 0}))
    return jsonify(data)


if __name__ == '__main__':
    app.run(debug=True)
