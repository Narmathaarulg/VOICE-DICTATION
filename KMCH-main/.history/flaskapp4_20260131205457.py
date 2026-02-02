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
    model = gemini.GenerativeModel('models/gemini-2.5-flash')  # ✅ Updated model
    return model

# -------------------- MONGODB --------------------
mongo_uri = os.getenv("MONGO_URI")
db_name = os.getenv("DB_NAME")

mongo_client = MongoClient(mongo_uri)
mongo_db = mongo_client[db_name]

patients_col = mongo_db["patients"]
records_col = mongo_db["records"]
doctors_col = mongo_db["doctors"]

# -------------------- AUDIO STREAMING STATE --------------------
recording_state = {
    "is_recording": False,
    "audio_chunks": [],
    "stream": None,
    "p": None
}

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

# -------------------- OLD ROUTES --------------------
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


# -------------------- NEW API ROUTES --------------------

@app.route('/api/start_recording', methods=['POST'])
def api_start_recording():
    """Start recording in control mode"""
    try:
        if recording_state["is_recording"]:
            return jsonify({"success": False, "message": "Already recording"}), 400
        
        # Initialize PyAudio
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=44100,
            input=True,
            frames_per_buffer=1024
        )
        
        recording_state["is_recording"] = True
        recording_state["audio_chunks"] = []
        recording_state["stream"] = stream
        recording_state["p"] = p
        
        return jsonify({"success": True, "message": "Recording started"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/stop_recording', methods=['POST'])
def api_stop_recording():
    """Stop recording and save file"""
    try:
        if not recording_state["is_recording"]:
            return jsonify({"success": False, "message": "Not recording"}), 400
        
        # Stop stream
        stream = recording_state["stream"]
        p = recording_state["p"]
        
        # Read remaining data
        while stream.is_active():
            data = stream.read(1024, exception_on_overflow=False)
            recording_state["audio_chunks"].append(data)
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        # Save to file
        filename = f"recordings/recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        wf = wave.open(filename, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b''.join(recording_state["audio_chunks"]))
        wf.close()
        
        # Reset state
        recording_state["is_recording"] = False
        recording_state["audio_chunks"] = []
        recording_state["stream"] = None
        recording_state["p"] = None
        
        return jsonify({"success": True, "recording_file": filename})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/record_fixed_duration', methods=['POST'])
def api_record_fixed_duration():
    """Record for a fixed duration"""
    try:
        data = request.get_json()
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        duration = int(data.get('duration', 10))
        source_language = data.get('source_language', 'auto')
        
        if not patient_id or not doctor_id:
            return jsonify({"success": False, "message": "Patient ID and Doctor ID required"}), 400
        
        # Initialize model
        model = initialize_gemini()
        
        # Record audio
        recording_file = record_audio(duration=duration)
        
        # Transcribe and translate
        transcript, translation = transcribe_and_translate(model, recording_file, source_language)
        
        # Generate summary
        summary_data = generate_structured_medical_summary(model, translation)
        
        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "recording_file": recording_file,
            "original_transcript": transcript,
            "english_transcript": translation,
            "summary_data": summary_data
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/process_recording', methods=['POST'])
def api_process_recording():
    """Process an existing recording"""
    try:
        data = request.get_json()
        recording_file = data.get('recording_file')
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        source_language = data.get('source_language', 'auto')
        
        # Initialize model
        model = initialize_gemini()
        
        # Transcribe and translate
        transcript, translation = transcribe_and_translate(model, recording_file, source_language)
        
        # Generate summary
        summary_data = generate_structured_medical_summary(model, translation)
        
        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "recording_file": recording_file,
            "original_transcript": transcript,
            "english_transcript": translation,
            "summary_data": summary_data
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/patients', methods=['GET'])
def api_get_all_patients():
    """Get all patients summary"""
    try:
        # Get unique patient IDs
        patient_ids = records_col.distinct("patient_id")
        total_records = records_col.count_documents({})
        
        return jsonify({
            "success": True,
            "patients": patient_ids,
            "stats": {
                "total_patients": len(patient_ids),
                "total_records": total_records
            }
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/patients/<patient_id>', methods=['GET'])
def api_get_patient_records(patient_id):
    """Get records for a specific patient"""
    try:
        records = list(records_col.find(
            {"patient_id": patient_id},
            {"_id": 0}
        ).sort("timestamp", -1))
        
        # Format timestamps
        for record in records:
            if 'timestamp' in record:
                record['timestamp'] = record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            
            # Extract summary fields
            if 'summary_data' in record:
                record['medical_condition'] = record['summary_data'].get('medical_condition', 'N/A')
                record['treatment_plan'] = record['summary_data'].get('treatment_plan', 'N/A')
                record['followup_date'] = record['summary_data'].get('followup_date', 'N/A')
            
            # Add recording path for audio playback
            if 'recording_file' in record:
                record['recording_path'] = record['recording_file']
        
        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "records": records
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/update_test', methods=['POST'])
def api_update_test():
    """Update test status for a patient record"""
    try:
        data = request.get_json()
        patient_id = data.get('patient_id')
        record_index = data.get('record_index')
        test_name = data.get('test_name')
        status = data.get('status')
        
        # Find the specific record
        records = list(records_col.find(
            {"patient_id": patient_id}
        ).sort("timestamp", -1))
        
        if record_index >= len(records):
            return jsonify({"success": False, "message": "Invalid record index"}), 400
        
        record = records[record_index]
        
        # Update tests
        if 'tests' not in record:
            record['tests'] = {}
        
        record['tests'][test_name] = status
        
        # Update in database
        records_col.update_one(
            {"_id": record["_id"]},
            {"$set": {"tests": record['tests']}}
        )
        
        return jsonify({"success": True, "message": "Test updated successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------- RUN --------------------
if __name__ == '__main__':
    app.run(debug=True)