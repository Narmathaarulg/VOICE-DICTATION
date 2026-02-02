from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import os
import time
import numpy as np
from scipy.io.wavfile import write
from datetime import datetime
import pandas as pda
import google.generativeai as genai
import base64
import pyaudio
import wave
import json
import re
load_dotenv()

app = Flask(__name__, static_folder='temp', static_url_path='')

CORS(app)

# Configure API key
def configure_gemini_api():
    api_key = os.environ.get("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    return genai

# Initialize Gemini model
def initialize_gemini():
    gemini = configure_gemini_api()
    model = gemini.GenerativeModel('gemini-1.5-pro')
    return model

# System database simulation
class PatientDatabase:
    def __init__(self):
        self.db_file = "patient_records.json"
        if os.path.exists(self.db_file):
            with open(self.db_file, 'r') as f:
                self.records = json.load(f)
        else:
            self.records = {}

    def save_recording(self, patient_id, doctor_id, recording_path, transcript, translation, summary_data):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if patient_id not in self.records:
            self.records[patient_id] = []
            
        clean_summary = {k: v for k, v in summary_data.items() 
                        if k not in ["confidence_level", "verification_note"]}
        
        record = {
            "timestamp": timestamp,
            "doctor_id": doctor_id,
            "recording_path": recording_path,
            "original_transcript": transcript,  # Changed key name
            "english_transcript": translation,  # Changed key name
            "transcript": transcript,
            "translation": translation,
            "summary": clean_summary.get("summary", ""),
            "medical_condition": clean_summary.get("medical_condition", "Not specified"),
            "treatment_plan": clean_summary.get("treatment_plan", "Not specified"),
            "followup_date": clean_summary.get("followup_date", "Not specified"),
            "tests": {}  # Add tests field
        }
        
        self.records[patient_id].append(record)
        
        with open(self.db_file, 'w') as f:
            json.dump(self.records, f)

    def get_patient_records(self, patient_id):
        if patient_id in self.records:
            return self.records[patient_id]
        return []
    
    def get_all_patient_ids(self):
        return list(self.records.keys())
    
    def get_stats(self):
        total_patients = len(self.records)
        total_records = sum(len(records) for records in self.records.values())
        return {
            "total_patients": total_patients,
            "total_records": total_records
        }
    
    def update_test(self, patient_id, record_index, test_name, status):
        if patient_id in self.records and record_index < len(self.records[patient_id]):
            if "tests" not in self.records[patient_id][record_index]:
                self.records[patient_id][record_index]["tests"] = {}
            
            self.records[patient_id][record_index]["tests"][test_name] = status
            
            with open(self.db_file, 'w') as f:
                json.dump(self.records, f)
            return True
        return False

# Recording state
recording_state = {
    "is_recording": False,
    "audio_chunks": [],
    "stream": None,
    "pyaudio_instance": None
}

# Record audio
def record_audio(duration=10, sample_rate=44100):
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    input=True,
                    frames_per_buffer=1024)
    
    frames = []
    for i in range(0, int(sample_rate / 1024 * duration)):
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

# Transcription and translation function
def transcribe_and_translate(model, audio_file, source_language="auto"):
    with open(audio_file, "rb") as f:
        audio_data = f.read()
    
    audio_b64 = base64.b64encode(audio_data).decode()
    
    prompt_transcribe = f"""
    Please transcribe this audio file with high accuracy. This is a doctor making clinical notes about a patient.
    
    Important guidelines for medical transcription:
    - Pay special attention to medical terminology, drug names, and dosages
    - Maintain exact numbers for vital signs, test results, and medication dosages
    - Indicate any parts that are unclear with [unclear]
    - Preserve all medical abbreviations as spoken
    
    The language may be {source_language} or could be any language if auto-detected.
    """
    
    try:
        response = model.generate_content([
            prompt_transcribe,
            {"mime_type": "audio/wav", "data": audio_b64}
        ])
        transcript = response.text
        transcript = f"{transcript}\n\nTranscription confidence: High"
    except Exception as e:
        return f"Transcription failed. Error: {str(e)}", None
    
    has_non_english = bool(re.search(r'[^\x00-\x7F]', transcript))
    
    prompt_translate = f"""
    Translate the following medical transcription to English.
    
    IMPORTANT: 
    - This text may contain a mix of English and non-English languages
    - Translate ALL non-English parts to English
    - Preserve all medical terminology exactly as stated
    - Maintain numerical values and units precisely
    - If you're unsure about any term, indicate with [uncertain: original_term]
    
    Text to translate:
    {transcript}
    """
    
    try:
        translation_response = model.generate_content(prompt_translate)
        translation = translation_response.text
        if has_non_english and translation == transcript:
            retry_prompt = f"""
            The previous text contains non-English characters but wasn't translated.
            Please translate all non-English text to English.
            Original text: {transcript}
            """
            retry_response = model.generate_content(retry_prompt)
            translation = retry_response.text
            translation += "\n\n[Note: This text required additional translation processing]"
    except Exception as e:
        if has_non_english:
            translation = f"[Translation Error: The transcript contains non-English text that could not be translated.]\n\n{transcript}"
        else:
            translation = transcript
    
    return transcript, translation

# Summary generation function
def generate_structured_medical_summary(model, translation):
    prompt = f"""
    You are a specialized medical AI assistant with extensive knowledge of clinical terminology. 
    Based on the following doctor's notes, create a structured medical summary.
    
    IMPORTANT GUIDELINES:
    - Be precise and medically accurate in your interpretations
    - Only include information that is explicitly stated in the notes
    - Do not invent medical conditions or treatments that weren't mentioned
    - If something is unclear or not specified, state "Not specified" for that section
    - If medical terminology is used, maintain the proper medical terms
    - Look for specific diagnoses, medications, dosages, and follow-up instructions
    
    Doctor's notes: {translation}
    
    Format your response as a valid JSON object with these keys:
    - "summary": A concise overview of the patient's condition
    - "medical_condition": Primary diagnoses or issues identified
    - "treatment_plan": Specific treatments, medications, or procedures recommended
    - "followup_date": Any follow-up dates mentioned (format as MM/DD/YYYY if possible)
    """
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')
        
        if json_start >= 0 and json_end >= 0:
            json_str = response_text[json_start:json_end+1]
            summary_data = json.loads(json_str)
        else:
            summary_data = json.loads(response_text)
            
        required_keys = ["summary", "medical_condition", "treatment_plan", "followup_date"]
        for key in required_keys:
            if key not in summary_data:
                summary_data[key] = "Not specified"
                
        return summary_data
    except Exception as e:
        return {
            "summary": "Error generating summary.",
            "medical_condition": "Not extracted",
            "treatment_plan": "Not extracted",
            "followup_date": "Not extracted"
        }

# Serve the React front-end
@app.route('/')
def serve_index():
    return app.send_static_file('index.html')

# Serve favicon
@app.route('/favicon.ico')
def serve_favicon():
    # Return empty response for favicon to avoid 404
    return '', 204

# ============ NEW API ENDPOINTS ============

# Get all patients
@app.route('/api/patients', methods=['GET'])
def get_all_patients():
    db = PatientDatabase()
    stats = db.get_stats()
    patient_ids = db.get_all_patient_ids()
    return jsonify({
        "patients": patient_ids,
        "stats": stats
    })

# Get specific patient records
@app.route('/api/patients/<patient_id>', methods=['GET'])
def get_patient_records_api(patient_id):
    db = PatientDatabase()
    records = db.get_patient_records(patient_id)
    return jsonify({"records": records})

# Start recording (control mode)
@app.route('/api/start_recording', methods=['POST'])
def start_recording():
    try:
        global recording_state
        
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
        recording_state["pyaudio_instance"] = p
        
        return jsonify({"success": True, "message": "Recording started"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# Stop recording (control mode)
@app.route('/api/stop_recording', methods=['POST'])
def stop_recording():
    try:
        global recording_state
        
        if not recording_state["is_recording"]:
            return jsonify({"success": False, "message": "Not currently recording"}), 400
        
        # Stop the stream
        stream = recording_state["stream"]
        p = recording_state["pyaudio_instance"]
        
        # Read any remaining data
        while recording_state["is_recording"]:
            try:
                data = stream.read(1024, exception_on_overflow=False)
                recording_state["audio_chunks"].append(data)
            except:
                break
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        # Save the recording
        filename = f"recordings/recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        wf = wave.open(filename, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b''.join(recording_state["audio_chunks"]))
        wf.close()
        
        recording_state["is_recording"] = False
        recording_state["audio_chunks"] = []
        recording_state["stream"] = None
        recording_state["pyaudio_instance"] = None
        
        return jsonify({"success": True, "recording_file": filename})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# Record with fixed duration
@app.route('/api/record_fixed_duration', methods=['POST'])
def record_fixed_duration():
    data = request.get_json()
    patient_id = data.get('patient_id')
    doctor_id = data.get('doctor_id')
    duration = int(data.get('duration', 10))
    source_language = data.get('source_language', 'auto')
    
    if not patient_id or not doctor_id:
        return jsonify({"success": False, "message": "Patient ID and Doctor ID are required"}), 400
    
    try:
        model = initialize_gemini()
        recording_file = record_audio(duration=duration)
        transcript, translation = transcribe_and_translate(model, recording_file, source_language)
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

# Process recording
@app.route('/api/process_recording', methods=['POST'])
def process_recording():
    data = request.get_json()
    recording_file = data.get('recording_file')
    patient_id = data.get('patient_id')
    doctor_id = data.get('doctor_id')
    source_language = data.get('source_language', 'auto')
    
    try:
        model = initialize_gemini()
        transcript, translation = transcribe_and_translate(model, recording_file, source_language)
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

# Update test status
@app.route('/api/update_test', methods=['POST'])
def update_test():
    data = request.get_json()
    patient_id = data.get('patient_id')
    record_index = data.get('record_index')
    test_name = data.get('test_name')
    status = data.get('status')
    
    db = PatientDatabase()
    success = db.update_test(patient_id, record_index, test_name, status)
    
    if success:
        return jsonify({"success": True, "message": "Test updated successfully"})
    else:
        return jsonify({"success": False, "message": "Failed to update test"}), 400

# Original endpoints (kept for compatibility)
@app.route('/record', methods=['POST'])
def record():
    data = request.get_json()
    patient_id = data.get('patientId')
    doctor_id = data.get('doctorId')
    duration = int(data.get('duration', 10))
    source_language = data.get('sourceLanguage', 'auto')
    quality = data.get('quality', 'Standard')
    
    if not patient_id or not doctor_id:
        return jsonify({"error": "Patient ID and Doctor ID are required"}), 400
    
    try:
        model = initialize_gemini()
        recording_file = record_audio(duration=duration)
        transcript, translation = transcribe_and_translate(model, recording_file, source_language)
        summary_data = generate_structured_medical_summary(model, translation)
        
        return jsonify({
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "recording_file": recording_file,
            "transcript": transcript,
            "translation": translation,
            "summary_data": summary_data
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/save', methods=['POST'])
def save():
    data = request.get_json()
    db = PatientDatabase()
    try:
        db.save_recording(
            data['patient_id'],
            data['doctor_id'],
            data['recording_file'],
            data['transcript'],
            data['translation'],
            data['summary_data']
        )
        return jsonify({"message": "Record saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/records/<patient_id>', methods=['GET'])
def get_records(patient_id):
    db = PatientDatabase()
    records = db.get_patient_records(patient_id)
    return jsonify(records)

@app.route('/recordings/<path:filename>', methods=['GET'])
def serve_recording(filename):
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return jsonify({"error": "File not found"}), 404

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('recordings', exist_ok=True)
    os.makedirs('temp', exist_ok=True)
    
    app.run(debug=True, port=5000)