import os
import time
import json
import base64
from datetime import datetime
from flask import Flask, request, render_template, jsonify, send_from_directory
from google.generativeai import GenerativeModel, configure
import wave
import pyaudio
import threading
import queue

# Initialize Flask app
app = Flask(__name__)

# Configure Gemini
configure(api_key="AIzaSyB-RajV0491qW08VDJlQDBRCKmd4UslYYA")
gemini_model = GenerativeModel('gemini-1.5-flash')

# Constants
DATABASE_FILE = "patient_records.json"
RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Audio Configuration
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

# Global state for audio recording
audio_state = {
    'is_recording': False,
    'frames': [],
    'stream': None,
    'p': None,
    'start_time': None,
    'stop_event': threading.Event(),
    'audio_queue': queue.Queue()
}

# --- Database Class (Identical to Streamlit Version) ---
class PatientDatabase:
    def __init__(self):
        self.records = self._load_database()

    def _load_database(self):
        if os.path.exists(DATABASE_FILE):
            with open(DATABASE_FILE, 'r') as f:
                data = json.load(f)
                # Ensure all values are lists
                for patient_id in data:
                    if not isinstance(data[patient_id], list):
                        data[patient_id] = []
                return data
        return {}

    def _save_database(self):
        try:
            # Create backup
            if os.path.exists(DATABASE_FILE):
                backup_file = f"{DATABASE_FILE}.backup"
                os.rename(DATABASE_FILE, backup_file)
            
            # Save new data
            with open(DATABASE_FILE, 'w') as f:
                json.dump(self.records, f, indent=2)
            
            # Remove backup if successful
            if os.path.exists(f"{DATABASE_FILE}.backup"):
                os.remove(f"{DATABASE_FILE}.backup")
            return True
        except Exception as e:
            print(f"Error saving database: {str(e)}")
            # Restore backup if it exists
            if os.path.exists(f"{DATABASE_FILE}.backup"):
                os.rename(f"{DATABASE_FILE}.backup", DATABASE_FILE)
            return False

    def save_recording(self, patient_id, doctor_id, recording_path, original_transcript, english_transcript, summary_data, test_data=None):
        patient_id = str(patient_id)
        
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "doctor_id": str(doctor_id),
            "recording_path": recording_path,
            "original_transcript": original_transcript,
            "english_transcript": english_transcript,
            "summary": summary_data.get("summary", ""),
            "medical_condition": summary_data.get("medical_condition", "Not specified"),
            "treatment_plan": summary_data.get("treatment_plan", "Not specified"),
            "followup_date": summary_data.get("followup_date", "Not specified"),
            "tests": test_data or {}
        }
        
        if patient_id not in self.records:
            self.records[patient_id] = []
        
        self.records[patient_id].append(record)
        return self._save_database()

    def get_patient_records(self, patient_id):
        patient_id = str(patient_id)
        return self.records.get(patient_id, [])

    def get_all_patients(self):
        return list(self.records.keys())

    def get_stats(self):
        total_records = sum(len(records) for records in self.records.values())
        total_patients = len(self.records)
        return {"total_patients": total_patients, "total_records": total_records}

# --- Audio Recorder Class (Identical to Streamlit Version) ---
class AudioRecorder:
    def __init__(self, sample_rate=RATE):
        self.sample_rate = sample_rate
        self.frames = []
        self.stream = None
        self.p = None
        self.is_recording = False
        self.start_time = None
        self.recording_thread = None
        self.stop_event = threading.Event()
        self.audio_queue = queue.Queue()
        self.error_occurred = False

    def _record_audio_thread(self):
        try:
            chunk_count = 0
            while not self.stop_event.is_set():
                if self.stream and self.is_recording:
                    try:
                        data = self.stream.read(CHUNK, exception_on_overflow=False)
                        if data:
                            self.audio_queue.put(data)
                            chunk_count += 1
                    except Exception as e:
                        if self.is_recording:
                            print(f"Audio read error: {str(e)}")
                            self.error_occurred = True
                        break
                time.sleep(0.01)
        except Exception as e:
            print(f"Recording thread error: {str(e)}")
            self.error_occurred = True

    def start_recording(self):
        try:
            # Clean up any previous recording state
            self.stop_recording()
            
            # Initialize PyAudio
            self.p = pyaudio.PyAudio()
            
            # Open stream
            self.stream = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=CHUNK
            )
            
            # Reset recording state
            self.frames = []
            self.is_recording = True
            self.start_time = time.time()
            self.stop_event.clear()
            self.error_occurred = False
            
            # Start recording thread
            self.recording_thread = threading.Thread(target=self._record_audio_thread)
            self.recording_thread.daemon = True
            self.recording_thread.start()
            
            return True
        except Exception as e:
            print(f"Failed to start recording: {str(e)}")
            self.is_recording = False
            return False

    def stop_recording(self):
        try:
            if not self.is_recording:
                return None
            
            # Signal the recording thread to stop
            self.is_recording = False
            self.stop_event.set()
            
            # Wait for thread to finish
            if self.recording_thread and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=2.0)
            
            # Collect all audio data from queue
            self.frames = []
            while not self.audio_queue.empty():
                try:
                    data = self.audio_queue.get_nowait()
                    self.frames.append(data)
                except queue.Empty:
                    break
            
            # Clean up audio stream
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except:
                    pass
                self.stream = None
            
            if self.p:
                try:
                    self.p.terminate()
                except:
                    pass
                self.p = None
            
            if not self.frames:
                print("No audio data recorded")
                return None
            
            # Save file
            filename = f"{RECORDINGS_DIR}/recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            
            wf = wave.open(filename, 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit audio = 2 bytes
            wf.setframerate(self.sample_rate)
            wf.writeframes(b''.join(self.frames))
            wf.close()
            
            duration = time.time() - self.start_time if self.start_time else 0
            print(f"Recording saved: {filename} (Duration: {duration:.1f}s)")
            
            return filename
        except Exception as e:
            print(f"Failed to stop recording: {str(e)}")
            return None

# --- AI Processing Functions ---
def transcribe_audio(audio_file, source_language="auto"):
    try:
        with open(audio_file, "rb") as f:
            audio_data = f.read()
        
        audio_b64 = base64.b64encode(audio_data).decode()
        
        # First, transcribe in original language
        prompt_transcribe = f"""
        Please transcribe this audio file accurately. The speaker is a doctor making notes about a patient.
        The language may be {source_language} or could be any language if auto-detected.
        Provide the transcription in the original language spoken.
        """
        
        response = gemini_model.generate_content([
            prompt_transcribe,
            {"mime_type": "audio/wav", "data": audio_b64}
        ])
        original_transcript = response.text.strip()
        
        # Then, translate to English if not already English
        prompt_translate = f"""
        Translate the following text to English if it's not already in English.
        If it's already in English, just return the same text.
        Make sure the translation is medically accurate and professional.
        
        Text: {original_transcript}
        """
        
        translation_response = gemini_model.generate_content(prompt_translate)
        english_translation = translation_response.text.strip()
        
        return original_transcript, english_translation
    except Exception as e:
        print(f"Transcription error: {str(e)}")
        return f"Transcription failed: {str(e)}", f"Translation failed: {str(e)}"

def generate_medical_summary(text):
    prompt = f"""
    You are a medical assistant. Based on the following doctor's notes, create a structured medical summary.
    
    Return ONLY a valid JSON object with these exact keys:
    - "summary": Brief overview of the patient's condition and visit purpose
    - "medical_condition": Primary issues or diagnoses (or "Not specified" if none)
    - "treatment_plan": Recommended treatments, tests, procedures (or "Not specified" if none)
    - "followup_date": Follow-up actions and dates (or "Not specified" if none)
    
    Doctor's notes: {text}
    """
    
    try:
        response = gemini_model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean up the response to extract JSON
        if '```json' in response_text:
            json_part = response_text.split('```json')[1].split('```')[0]
        elif '```' in response_text:
            json_part = response_text.split('```')[1]
        else:
            json_part = response_text
        
        # Find JSON object boundaries
        start = json_part.find('{')
        end = json_part.rfind('}') + 1
        
        if start != -1 and end > start:
            json_part = json_part[start:end]
            summary_data = json.loads(json_part)
            
            # Validate required keys
            required_keys = ["summary", "medical_condition", "treatment_plan", "followup_date"]
            for key in required_keys:
                if key not in summary_data:
                    summary_data[key] = "Not specified"
            
            return summary_data
        else:
            return {
                "summary": "Medical consultation recorded",
                "medical_condition": "Assessment pending",
                "treatment_plan": "Tests and evaluation required",
                "followup_date": "To be determined"
            }
    except Exception as e:
        print(f"Error generating summary: {str(e)}")
        return {
            "summary": "Medical consultation recorded",
            "medical_condition": "Assessment pending",
            "treatment_plan": "Tests and evaluation required",
            "followup_date": "To be determined"
        }

def extract_tests(text):
    """Extract medical tests from transcript using AI with fallback"""
    try:
        prompt = f"""
        Extract medical tests mentioned in the following doctor's notes.
        Return ONLY a JSON array of test names.
        If no tests are mentioned, return an empty array [].
        
        Doctor's notes: {text}
        """
        response = gemini_model.generate_content(prompt)
        response_text = response.text.strip()

        # Extract JSON array from response
        start = response_text.find('[')
        end = response_text.rfind(']') + 1
        if start != -1 and end > start:
            return list(set(json.loads(response_text[start:end]) + manual_extract_tests(text)))
    except Exception as e:
        print("AI Test extraction failed, using manual fallback:", str(e))
    return manual_extract_tests(text)

def manual_extract_tests(text):
    text = text.lower()
    test_patterns = {
        "blood sugar": ["sugar", "glucose", "blood sugar"],
        "blood test": ["blood test", "blood work"],
        "CT scan": ["ct", "cat scan", "ct scan"],
        "MRI": ["mri"],
        "X-ray": ["x-ray", "xray"],
        "ultrasound": ["ultrasound", "sonogram"],
        "ECG": ["ekg", "ecg"],
        "urine test": ["urine", "urinalysis"]
    }
    found = []
    for test_name, keywords in test_patterns.items():
        if any(k in text for k in keywords):
            found.append(test_name)
    return found


# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start_recording', methods=['POST'])
def api_start_recording():
    global audio_state
    recorder = AudioRecorder()
    if recorder.start_recording():
        audio_state['recorder'] = recorder
        return jsonify({"success": True, "message": "Recording started"})
    else:
        return jsonify({"success": False, "message": "Failed to start recording"}), 500

@app.route('/api/stop_recording', methods=['POST'])
def api_stop_recording():
    global audio_state
    if 'recorder' not in audio_state:
        return jsonify({"success": False, "message": "No active recording"}), 400
    
    recording_file = audio_state['recorder'].stop_recording()
    if recording_file:
        return jsonify({"success": True, "recording_file": recording_file})
    else:
        return jsonify({"success": False, "message": "Failed to save recording"}), 500


@app.route('/api/record_fixed_duration', methods=['POST'])
def api_record_fixed_duration():
    data = request.json
    duration = data.get('duration', 10)
    patient_id = data.get('patient_id')
    doctor_id = data.get('doctor_id')
    source_language = data.get('source_language', 'auto')

    if not all([patient_id, doctor_id]):
        return jsonify({"success": False, "message": "Missing required parameters"}), 400
    
    try:
        # Record audio
        recorder = AudioRecorder()
        if not recorder.start_recording():
            return jsonify({"success": False, "message": "Failed to start recording"}), 500
        
        # Wait for duration
        time.sleep(duration)
        
        # Stop recording
        recording_file = recorder.stop_recording()
        if not recording_file:
            return jsonify({"success": False, "message": "Failed to save recording"}), 500
        
        # Process recording
        original_transcript, english_transcript = transcribe_audio(recording_file, source_language)
        summary_data = generate_medical_summary(english_transcript)
        tests = extract_tests(english_transcript)
        test_status = {test: "Pending" for test in tests}

        # Save to database
        db = PatientDatabase()
        success = db.save_recording(
            patient_id,
            doctor_id,
            recording_file,
            original_transcript,
            english_transcript,
            summary_data,
            test_status
        )
        
        if success:
            return jsonify({
                "success": True,
                "original_transcript": original_transcript,
                "english_transcript": english_transcript,
                "summary_data": summary_data,
                "recording_file": recording_file
            })
        else:
            return jsonify({"success": False, "message": "Failed to save to database"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500




@app.route('/api/process_recording', methods=['POST'])
def api_process_recording():
    data = request.json
    recording_file = data.get('recording_file')
    patient_id = data.get('patient_id')
    doctor_id = data.get('doctor_id')
    source_language = data.get('source_language', 'auto')
    
    if not all([recording_file, patient_id, doctor_id]):
        return jsonify({"success": False, "message": "Missing required parameters"}), 400
    
    # Transcribe and translate
    original_transcript, english_transcript = transcribe_audio(recording_file, source_language)
    
    # Generate medical summary
    summary_data = generate_medical_summary(english_transcript)
    tests = extract_tests(english_transcript)
    test_status = {test: "Pending" for test in tests}
    # Save to database
    db = PatientDatabase()
    success = db.save_recording(
        patient_id,
        doctor_id,
        recording_file,
        original_transcript,
        english_transcript,
        summary_data,
        test_status
    )
    
    if success:
        return jsonify({
            "success": True,
            "original_transcript": original_transcript,
            "english_transcript": english_transcript,
            "summary_data": summary_data,
            "recording_file": recording_file
        })
    else:
        return jsonify({"success": False, "message": "Failed to save to database"}), 500

@app.route('/api/update_test', methods=['POST'])
def update_test():
    data = request.json
    patient_id = data.get("patient_id")
    record_index = int(data.get("record_index", -1))
    test_name = data.get("test_name")
    status = data.get("status")

    if not all([patient_id, test_name, status]) or record_index < 0:
        return jsonify({"success": False, "message": "Invalid parameters"}), 400

    db = PatientDatabase()
    records = db.get_patient_records(patient_id)
    if record_index >= len(records):
        return jsonify({"success": False, "message": "Record index out of range"}), 400

    if "tests" not in records[record_index]:
        records[record_index]["tests"] = {}

    records[record_index]["tests"][test_name] = status
    db.records[patient_id] = records

    if db._save_database():
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Failed to update database"}), 500



@app.route('/api/patients', methods=['GET'])
def api_get_patients():
    db = PatientDatabase()
    patients = db.get_all_patients()
    stats = db.get_stats()
    return jsonify({"patients": patients, "stats": stats})

@app.route('/api/patients/<patient_id>', methods=['GET'])
def api_get_patient_records(patient_id):
    db = PatientDatabase()
    records = db.get_patient_records(patient_id)
    return jsonify({"records": records})

@app.route('/recordings/<filename>')
def serve_recording(filename):
    return send_from_directory(RECORDINGS_DIR, filename)

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=False, port=10000, threaded=True, use_reloader=False)
