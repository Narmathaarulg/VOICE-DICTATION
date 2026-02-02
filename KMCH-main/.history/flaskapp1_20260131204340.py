from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import os
import time
from datetime import datetime
import google.generativeai as genai
import base64
import pyaudio
import wave
import json
import re
from pymongo import MongoClient

# -------------------- ENV --------------------
load_dotenv()

# -------------------- APP --------------------
app = Flask(__name__, static_folder='temp', static_url_path='')
CORS(app)

# -------------------- GEMINI --------------------
def configure_gemini_api():
    api_key = os.environ.get("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    return genai


def initialize_gemini():
    gemini = configure_gemini_api()
    model = gemini.GenerativeModel('')
    return model

# -------------------- MONGODB --------------------
mongo_uri = os.getenv("MONGO_URI")
db_name = os.getenv("DB_NAME")

mongo_client = MongoClient(mongo_uri)
mongo_db = mongo_client[db_name]

patients_col = mongo_db["patients"]
records_col = mongo_db["records"]
doctors_col = mongo_db["doctors"]

# -------------------- AUDIO RECORD --------------------
def record_audio(duration=10, sample_rate=44100):
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    input=True,
                    frames_per_buffer=1024)

    frames = []
    for _ in range(0, int(sample_rate / 1024 * duration)):
        data = stream.read(1024)
        frames.append(data)
        time.sleep(0.001)

    stream.stop_stream()
    stream.close()
    p.terminate()

    filename = f"recordings/recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    wf = wave.open(filename, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(sample_rate)
    wf.writeframes(b''.join(frames))
    wf.close()

    return filename

# -------------------- TRANSCRIPTION --------------------
def transcribe_and_translate(model, audio_file, source_language="auto"):
    with open(audio_file, "rb") as f:
        audio_data = f.read()

    audio_b64 = base64.b64encode(audio_data).decode()

    prompt_transcribe = f"""
    Please transcribe this audio file with high accuracy. This is a doctor making clinical notes about a patient.
    """

    response = model.generate_content([
        prompt_transcribe,
        {"mime_type": "audio/wav", "data": audio_b64}
    ])

    transcript = response.text

    has_non_english = bool(re.search(r'[^\x00-\x7F]', transcript))

    prompt_translate = f"""
    Translate the following medical transcription to English.
    Text:
    {transcript}
    """

    translation_response = model.generate_content(prompt_translate)
    translation = translation_response.text

    return transcript, translation

# -------------------- SUMMARY --------------------
def generate_structured_medical_summary(model, translation):
    prompt = f"""
    Create a structured medical summary in JSON.
    Text: {translation}
    
    Format:
    {{
      "summary": "",
      "medical_condition": "",
      "treatment_plan": "",
      "followup_date": ""
    }}
    """

    response = model.generate_content(prompt)
    response_text = response.text.strip()

    json_start = response_text.find('{')
    json_end = response_text.rfind('}')

    json_str = response_text[json_start:json_end+1]
    summary_data = json.loads(json_str)

    return summary_data

# -------------------- ROUTES --------------------
@app.route('/')
def serve_index():
    return app.send_static_file('index.html')


@app.route('/record', methods=['POST'])
def record():
    data = request.get_json()

    patient_id = data.get('patientId')
    doctor_id = data.get('doctorId')
    duration = int(data.get('duration', 10))

    if not patient_id or not doctor_id:
        return jsonify({"error": "Patient ID and Doctor ID required"}), 400

    model = initialize_gemini()

    recording_file = record_audio(duration=duration)
    transcript, translation = transcribe_and_translate(model, recording_file)
    summary_data = generate_structured_medical_summary(model, translation)

    return jsonify({
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "recording_file": recording_file,
        "transcript": transcript,
        "translation": translation,
        "summary_data": summary_data
    })


@app.route('/save', methods=['POST'])
def save():
    data = request.get_json()

    record = {
        "patient_id": data['patient_id'],
        "doctor_id": data['doctor_id'],
        "recording_file": data['recording_file'],
        "transcript": data['transcript'],
        "translation": data['translation'],
        "summary_data": data['summary_data'],
        "timestamp": datetime.utcnow()
    }

    records_col.insert_one(record)

    return jsonify({"message": "Saved to MongoDB successfully"}), 200


@app.route('/records/<patient_id>', methods=['GET'])
def get_records(patient_id):
    records = list(records_col.find({"patient_id": patient_id}, {"_id": 0}))
    return jsonify(records)


@app.route('/recordings/<path:filename>', methods=['GET'])
def serve_recording(filename):
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return jsonify({"error": "File not found"}), 404


# -------------------- RUN --------------------
if __name__ == '__main__':
    app.run(debug=True)
