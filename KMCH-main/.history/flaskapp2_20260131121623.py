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
import threading

# -------------------- ENV --------------------
load_dotenv()

# -------------------- APP --------------------
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# -------------------- GEMINI --------------------
def configure_gemini_api():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found!")
    genai.configure(api_key=api_key)
    return genai

def initialize_gemini():
    gemini = configure_gemini_api()
    model = gemini.GenerativeModel('gemini-1.5-pro')
    return model

# -------------------- MONGODB --------------------
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
db_name = os.getenv("DB_NAME", "hospital_db")

try:
    mongo_client = MongoClient(mongo_uri)
    mongo_db = mongo_client[db_name]
    
    patients_col = mongo_db["patients"]
    records_col = mongo_db["records"]
    doctors_col = mongo_db["doctors"]
    
    mongo_client.server_info()
    print(f"✅ MongoDB Connected: {db_name}")
except Exception as e:
    print(f"❌ MongoDB Error: {e}")
    mongo_client = None

# -------------------- GLOBAL RECORDING STATE --------------------
recording_state = {
    'is_recording': False,
    'stream': None,
    'frames': [],
    'pyaudio': None,
    'start_time': None
}

# -------------------- AUDIO FUNCTIONS --------------------
def record_audio_fixed(duration=10, sample_rate=44100):
    """Record audio for fixed duration"""
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    input=True,
                    
                    frames_per_buffer=1024)

    print(f"🎤 Recording {duration}s...")
    frames = []
    
    for _ in range(0, int(sample_rate / 1024 * duration)):
        try:
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(data)
        except Exception as e:
            print(f"Read error: {e}")

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
    
    print(f"✅ Saved: {filename}")
    return filename

# -------------------- TRANSCRIPTION --------------------
def transcribe_and_translate(model, audio_file, source_language="auto"):
    """Transcribe and translate audio"""
    try:
        with open(audio_file, "rb") as f:
            audio_data = f.read()

        audio_b64 = base64.b64encode(audio_data).decode()

        prompt = f"""
        Transcribe this medical audio with high accuracy.
        Language: {source_language}
        Pay attention to medical terms, drug names, dosages.
        """

        print("🔄 Transcribing...")
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": audio_b64}
        ])

        transcript = response.text
        print(f"✅ Transcript: {len(transcript)} chars")

        # Check if translation needed
        has_non_english = bool(re.search(r'[^\x00-\x7F]', transcript))

        if has_non_english or source_language.lower() != 'english':
            translate_prompt = f"Translate to English, preserve medical terms:\n{transcript}"
            print("🔄 Translating...")
            translation_response = model.generate_content(translate_prompt)
            translation = translation_response.text
            print("✅ Translation complete")
        else:
            translation = transcript

        return transcript, translation
    
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        return f"Error: {str(e)}", None

# -------------------- SUMMARY --------------------
def generate_structured_medical_summary(model, translation):
    """Generate medical summary"""
    try:
        prompt = f"""
        Create medical summary in JSON format.
        Notes: {translation}
        
        Return ONLY valid JSON:
        {{
          "summary": "brief overview",
          "medical_condition": "diagnosis",
          "treatment_plan": "treatment",
          "followup_date": "date or Not specified"
        }}
        """

        print("🔄 Generating summary...")
        response = model.generate_content(prompt)
        response_text = response.text.strip()

        # Extract JSON
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')

        if json_start >= 0 and json_end >= 0:
            json_str = response_text[json_start:json_end+1]
            summary_data = json.loads(json_str)
            print("✅ Summary generated")
            return summary_data
        else:
            raise ValueError("No JSON found")
    
    except Exception as e:
        print(f"❌ Summary error: {e}")
        return {
            "summary": "Error generating summary",
            "medical_condition": "Not extracted",
            "treatment_plan": "Not extracted",
            "followup_date": "Not specified"
        }

# -------------------- API ROUTES --------------------

@app.route('/')
def serve_index():
    """Serve main HTML"""
    return send_from_directory('static', 'index.html')

@app.route('/api/test', methods=['GET'])
def test_api():
    """Test endpoint"""
    return jsonify({
        "success": True,
        "message": "API Working!",
        "mongodb": mongo_client is not None,
        "timestamp": datetime.now().isoformat()
    })

# ========== START/STOP RECORDING ==========

@app.route('/api/start_recording', methods=['POST', 'OPTIONS'])
def start_recording():
    """Start recording (control mode)"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    global recording_state
    
    try:
        if recording_state['is_recording']:
            return jsonify({
                "success": False,
                "message": "Already recording"
            }), 400
        
        # Initialize PyAudio
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=44100,
            input=True,
            frames_per_buffer=1024
        )
        
        recording_state['stream'] = stream
        recording_state['frames'] = []
        recording_state['pyaudio'] = p
        recording_state['is_recording'] = True
        recording_state['start_time'] = time.time()
        
        # Start recording thread
        def record_chunks():
            while recording_state['is_recording']:
                try:
                    data = recording_state['stream'].read(1024, exception_on_overflow=False)
                    recording_state['frames'].append(data)
                except Exception as e:
                    print(f"Recording error: {e}")
                    break
        
        thread = threading.Thread(target=record_chunks, daemon=True)
        thread.start()
        
        print("🎤 Recording STARTED")
        
        return jsonify({
            "success": True,
            "message": "Recording started"
        })
    
    except Exception as e:
        print(f"❌ Start error: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/stop_recording', methods=['POST', 'OPTIONS'])
def stop_recording():
    """Stop recording (control mode)"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    global recording_state
    
    try:
        if not recording_state['is_recording']:
            return jsonify({
                "success": False,
                "message": "No active recording"
            }), 400
        
        # Stop recording
        recording_state['is_recording'] = False
        time.sleep(0.2)  # Wait for thread to finish
        
        stream = recording_state['stream']
        p = recording_state['pyaudio']
        frames = recording_state['frames']
        
        if stream:
            stream.stop_stream()
            stream.close()
        
        # Save to file
        filename = f"recordings/recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        wf = wave.open(filename, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        p.terminate()
        
        # Reset state
        recording_state = {
            'is_recording': False,
            'stream': None,
            'frames': [],
            'pyaudio': None,
            'start_time': None
        }
        
        duration = time.time() - recording_state.get('start_time', 0)
        print(f"🎤 Recording STOPPED ({duration:.1f}s)")
        print(f"✅ Saved: {filename}")
        
        return jsonify({
            "success": True,
            "recording_file": filename,
            "duration": duration,
            "message": "Recording stopped"
        })
    
    except Exception as e:
        print(f"❌ Stop error: {e}")
        recording_state['is_recording'] = False
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/recording_status', methods=['GET'])
def recording_status():
    """Get recording status"""
    return jsonify({
        "is_recording": recording_state['is_recording'],
        "duration": time.time() - recording_state.get('start_time', time.time()) if recording_state['is_recording'] else 0
    })

# ========== FIXED DURATION RECORDING ==========

@app.route('/api/record_fixed_duration', methods=['POST', 'OPTIONS'])
def record_fixed_duration():
    """Record with fixed duration"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    try:
        data = request.get_json()
        
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        duration = int(data.get('duration', 10))
        source_language = data.get('source_language', 'auto')
        
        if not patient_id or not doctor_id:
            return jsonify({
                "success": False,
                "message": "Patient ID and Doctor ID required"
            }), 400
        
        print(f"\n{'='*50}")
        print(f"📝 Patient: {patient_id} | Doctor: {doctor_id} | Duration: {duration}s")
        print(f"{'='*50}\n")
        
        # Record audio
        recording_file = record_audio_fixed(duration=duration)
        
        # Initialize Gemini
        model = initialize_gemini()
        
        # Transcribe
        transcript, translation = transcribe_and_translate(model, recording_file, source_language)
        
        # Generate summary
        summary_data = generate_structured_medical_summary(model, translation)
        
        print(f"\n{'='*50}")
        print("✅ PROCESSING COMPLETE")
        print(f"{'='*50}\n")
        
        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "recording_file": recording_file,
            "original_transcript": transcript,
            "english_transcript": translation,
            "summary_data": summary_data
        }), 200
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/process_recording', methods=['POST', 'OPTIONS'])
def process_recording():
    """Process existing recording"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    try:
        data = request.get_json()
        
        recording_file = data.get('recording_file')
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        source_language = data.get('source_language', 'auto')
        
        print(f"\n📝 Processing: {recording_file}")
        
        # Initialize Gemini
        model = initialize_gemini()
        
        # Transcribe
        transcript, translation = transcribe_and_translate(model, recording_file, source_language)
        
        # Generate summary
        summary_data = generate_structured_medical_summary(model, translation)
        
        print("✅ Processing complete\n")
        
        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "recording_file": recording_file,
            "original_transcript": transcript,
            "english_transcript": translation,
            "summary_data": summary_data
        }), 200
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

# ========== MONGODB OPERATIONS ==========

@app.route('/api/save_record', methods=['POST', 'OPTIONS'])
def save_record():
    """Save to MongoDB"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    if not mongo_client:
        return jsonify({
            "success": False,
            "message": "MongoDB not connected"
        }), 500
    
    try:
        data = request.get_json()
        
        record = {
            "patient_id": data.get('patient_id'),
            "doctor_id": data.get('doctor_id'),
            "recording_path": data.get('recording_file'),
            "original_transcript": data.get('original_transcript'),
            "english_transcript": data.get('english_transcript'),
            "medical_condition": data.get('summary_data', {}).get('medical_condition', 'Not specified'),
            "treatment_plan": data.get('summary_data', {}).get('treatment_plan', 'Not specified'),
            "followup_date": data.get('summary_data', {}).get('followup_date', 'Not specified'),
            "summary": data.get('summary_data', {}).get('summary', ''),
            "tests": {},
            "timestamp": datetime.utcnow()
        }
        
        result = records_col.insert_one(record)
        
        print(f"✅ Saved to MongoDB: {result.inserted_id}")
        
        return jsonify({
            "success": True,
            "message": "Saved successfully",
            "record_id": str(result.inserted_id)
        }), 200
    
    except Exception as e:
        print(f"❌ Save error: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/patients/<patient_id>', methods=['GET'])
def get_patient_records(patient_id):
    """Get patient records"""
    if not mongo_client:
        return jsonify({
            "success": False,
            "message": "MongoDB not connected"
        }), 500
    
    try:
        records = list(records_col.find(
            {"patient_id": patient_id},
            {"_id": 0}
        ).sort("timestamp", -1))
        
        # Format timestamps
        for record in records:
            if 'timestamp' in record:
                record['timestamp'] = record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            "success": True,
            "records": records
        })
    
    except Exception as e:
        print(f"❌ Fetch error: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/patients', methods=['GET'])
def get_all_patients():
    """Get all patients stats"""
    if not mongo_client:
        return jsonify({
            "success": False,
            "message": "MongoDB not connected"
        }), 500
    
    try:
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
        print(f"❌ Stats error: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/update_test', methods=['POST', 'OPTIONS'])
def update_test():
    """Update test status"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    if not mongo_client:
        return jsonify({
            "success": False,
            "message": "MongoDB not connected"
        }), 500
    
    try:
        data = request.get_json()
        
        patient_id = data.get('patient_id')
        record_index = data.get('record_index')
        test_name = data.get('test_name')
        status = data.get('status')
        
        records = list(records_col.find({"patient_id": patient_id}).sort("timestamp", -1))
        
        if record_index >= len(records):
            return jsonify({
                "success": False,
                "message": "Invalid record index"
            }), 400
        
        record_id = records[record_index]['_id']
        
        records_col.update_one(
            {"_id": record_id},
            {"$set": {f"tests.{test_name}": status}}
        )
        
        print(f"✅ Updated test: {test_name} = {status}")
        
        return jsonify({
            "success": True,
            "message": "Test updated"
        })
    
    except Exception as e:
        print(f"❌ Update error: {e}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

# ========== FILE SERVING ==========

@app.route('/recordings/<path:filename>', methods=['GET'])
def serve_recording(filename):
    """Serve audio files"""
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype='audio/wav')
    return jsonify({"error": "File not found"}), 404

# -------------------- RUN --------------------
if __name__ == '__main__':
    os.makedirs('recordings', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    print("\n" + "="*60)
    print("🏥 HOSPITAL VOICE RECORDING SYSTEM")
    print("="*60)
    print(f"MongoDB: {'✅ Connected' if mongo_client else '❌ Not Connected'}")
    print(f"Database: {db_name}")
    print(f"Server: http://localhost:5000")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)