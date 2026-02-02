# KMCH Hospital AI Backend
# Flask + Browser Audio Upload + Gemini + MongoDB

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient
from dotenv import load_dotenv
import google.generativeai as genai
import os
from datetime import datetime
import uuid

# ------------------ CONFIG ------------------
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

UPLOAD_FOLDER = "recordings"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ------------------ DB ------------------
client = MongoClient(MONGO_URI)
db = client["kmch_hospital"]
patients_col = db["patients"]
records_col = db["records"]

# ------------------ GEMINI ------------------
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-1.5-flash")

# ------------------ HELPERS ------------------
def ai_transcribe_and_summary(text):
    prompt = f"""
You are a medical AI assistant.
Convert this raw transcription into:
1. Clean medical transcription
2. Clinical summary
3. Diagnosis suggestion
4. Treatment plan
5. Follow-up

Raw text:\n{text}
"""
    response = model.generate_content(prompt)
    return response.text

# ------------------ ROUTES ------------------

# Upload audio from browser
@app.route("/api/upload_audio", methods=["POST"])
def upload_audio():
    file = request.files.get("audio")
    patient_id = request.form.get("patient_id")
    doctor_id = request.form.get("doctor_id")

    if not file:
        return jsonify({"error": "No audio file"}), 400

    filename = f"{uuid.uuid4()}.wav"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    record = {
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "audio_file": filename,
        "created_at": datetime.utcnow(),
        "status": "uploaded"
    }

    records_col.insert_one(record)

    return jsonify({"message": "Audio uploaded", "filename": filename})

# Process audio (Gemini)
@app.route("/api/process_recording", methods=["POST"])
def process_recording():
    data = request.json
    filename = data.get("filename")
    patient_id = data.get("patient_id")

    # In real system: speech-to-text engine (Deepgram / Whisper)
    # Demo transcription placeholder
    fake_transcription = "Patient has fever and throat pain for 3 days"

    ai_result = ai_transcribe_and_summary(fake_transcription)

    result_data = {
        "patient_id": patient_id,
        "filename": filename,
        "transcription": fake_transcription,
        "ai_report": ai_result,
        "processed_at": datetime.utcnow()
    }

    records_col.update_one({"audio_file": filename}, {"$set": result_data})

    return jsonify({"message": "Processed", "report": ai_result})

# Create patient
@app.route("/api/patients", methods=["POST"])
def create_patient():
    data = request.json
    data["created_at"] = datetime.utcnow()
    patients_col.insert_one(data)
    return jsonify({"message": "Patient created"})

# Get all patients
@app.route("/api/patients", methods=["GET"])
def get_patients():
    patients = list(patients_col.find({}, {"_id": 0}))
    return jsonify(patients)

# Get patient records
@app.route("/api/patients/<patient_id>", methods=["GET"])
def get_patient_records(patient_id):
    records = list(records_col.find({"patient_id": patient_id}, {"_id": 0}))
    return jsonify(records)

# Update test results
@app.route("/api/update_test", methods=["POST"])
def update_test():
    data = request.json
    records_col.update_one(
        {"patient_id": data.get("patient_id")},
        {"$set": {"test_results": data.get("test_results")}}
    )
    return jsonify({"message": "Test updated"})

# Serve audio
@app.route("/recordings/<filename>")
def get_audio(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# ------------------ MAIN ------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
