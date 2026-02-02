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
from bson import ObjectId

# -------------------- ENV --------------------
load_dotenv()

# -------------------- APP --------------------
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# -------------------- GEMINI --------------------
def configure_gemini_api():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables")
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
    
    # Collections
    patients_col = mongo_db["patients"]
    records_col = mongo_db["records"]
    doctors_col = mongo_db["doctors"]
    
    # Test connection
    mongo_client.server_info()
    print(f"✅ MongoDB connected successfully to database: {db_name}")
except Exception as e:
    print(f"❌ MongoDB connection failed: {str(e)}")
    mongo_client = None
    mongo_db = None

# -------------------- AUDIO RECORD --------------------
# Global variable to store active recording
active_recording = {
    'stream': None,
    'frames': [],
    'is_recording': False
}

def record_audio(duration=10, sample_rate=44100):
    """Record audio for a fixed duration"""
    p = pyaudio.PyAudio()
    
    # Find default input device
    try:
        default_input = p.get_default_input_device_info()
        print(f"Using input device: {default_input['name']}")
    except Exception as e:
        print(f"Error getting default input device: {str(e)}")
    
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    input=True,
                    frames_per_buffer=1024)

    print(f"🎤 Recording started for {duration} seconds...")
    frames = []
    
    for i in range(0, int(sample_rate / 1024 * duration)):
        try:
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(data)
        except Exception as e:
            print(f"Error reading audio: {str(e)}")
            break

    stream.stop_stream()
    stream.close()
    p.terminate()
    
    print("🎤 Recording stopped")

    # Save to file
    filename = f"recordings/recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    wf = wave.open(filename, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(sample_rate)
    wf.writeframes(b''.join(frames))
    wf.close()
    
    print(f"✅ Audio saved to: {filename}")

    return filename

# -------------------- TRANSCRIPTION --------------------
def transcribe_and_translate(model, audio_file, source_language="auto"):
    """Transcribe and translate audio file"""
    try:
        with open(audio_file, "rb") as f:
            audio_data = f.read()

        audio_b64 = base64.b64encode(audio_data).decode()

        prompt_transcribe = f"""
        Please transcribe this audio file with high accuracy. This is a doctor making clinical notes about a patient.
        
        Important guidelines:
        - Pay attention to medical terminology, drug names, and dosages
        - Maintain exact numbers for vital signs and test results
        - Indicate unclear parts with [unclear]
        - The language may be {source_language} or auto-detected.
        """

        print("🔄 Transcribing audio...")
        response = model.generate_content([
            prompt_transcribe,
            {"mime_type": "audio/wav", "data": audio_b64}
        ])

        transcript = response.text
        print(f"✅ Transcription complete: {len(transcript)} characters")

        # Check for non-English characters
        has_non_english = bool(re.search(r'[^\x00-\x7F]', transcript))

        if has_non_english or source_language.lower() != 'english':
            prompt_translate = f"""
            Translate the following medical transcription to English.
            Preserve all medical terminology and numerical values.
            
            Text:
            {transcript}
            """

            print("🔄 Translating to English...")
            translation_response = model.generate_content(prompt_translate)
            translation = translation_response.text
            print(f"✅ Translation complete")
        else:
            translation = transcript

        return transcript, translation
    
    except Exception as e:
        print(f"❌ Error in transcription: {str(e)}")
        return f"Error: {str(e)}", None

# -------------------- SUMMARY --------------------
def generate_structured_medical_summary(model, translation):
    """Generate structured medical summary from translation"""
    try:
        prompt = f"""
        Create a structured medical summary in JSON format.
        
        Doctor's notes: {translation}
        
        Format your response as valid JSON:
        {{
          "summary": "Brief overview",
          "medical_condition": "Primary diagnosis",
          "treatment_plan": "Treatment details",
          "followup_date": "Follow-up date (MM/DD/YYYY or 'Not specified')"
        }}
        """

        print("🔄 Generating medical summary...")
        response = model.generate_content(prompt)
        response_text = response.text.strip()

        # Extract JSON from response
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')

        if json_start >= 0 and json_end >= 0:
            json_str = response_text[json_start:json_end+1]
            summary_data = json.loads(json_str)
            print("✅ Summary generated successfully")
            return summary_data
        else:
            raise ValueError("No JSON found in response")
    
    except Exception as e:
        print(f"❌ Error generating summary: {str(e)}")
        return {
            "summary": "Error generating summary",
            "medical_condition": "Not extracted",
            "treatment_plan": "Not extracted",
            "followup_date": "Not specified"
        }

# -------------------- ROUTES --------------------
@app.route('/')
def serve_index():
    """Serve the main HTML page"""
    return send_from_directory('static', 'index.html')

@app.route('/api/test', methods=['GET'])
def test_api():
    """Test API endpoint"""
    return jsonify({
        "success": True,
        "message": "API is working",
        "mongodb_connected": mongo_client is not None,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/start_recording', methods=['POST'])
def start_recording():
    """Start recording in control mode"""
    global active_recording
    
    try:
        if active_recording['is_recording']:
            return jsonify({
                "success": False,
                "message": "Recording already in progress"
            }), 400
        
        # Initialize PyAudio
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16,
                       channels=1,
                       rate=44100,
                       input=True,
                       frames_per_buffer=1024)
        
        active_recording['stream'] = stream
        active_recording['frames'] = []
        active_recording['is_recording'] = True
        active_recording['pyaudio'] = p
        
        print("🎤 Recording started (control mode)")
        
        return jsonify({
            "success": True,
            "message": "Recording started"
        })
    
    except Exception as e:
        print(f"❌ Error starting recording: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/stop_recording', methods=['POST'])
def stop_recording():
    """Stop recording in control mode"""
    global active_recording
    
    try:
        if not active_recording['is_recording']:
            return jsonify({
                "success": False,
                "message": "No active recording"
            }), 400
        
        # Stop stream
        stream = active_recording['stream']
        stream.stop_stream()
        stream.close()
        
        p = active_recording['pyaudio']
        p.terminate()
        
        # Save to file
        filename = f"recordings/recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        wf = wave.open(filename, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b''.join(active_recording['frames']))
        wf.close()
        
        # Reset recording state
        active_recording['stream'] = None
        active_recording['frames'] = []
        active_recording['is_recording'] = False
        
        print(f"✅ Recording saved: {filename}")
        
        return jsonify({
            "success": True,
            "recording_file": filename,
            "message": "Recording stopped"
        })
    
    except Exception as e:
        print(f"❌ Error stopping recording: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/record_fixed_duration', methods=['POST'])
def record_fixed_duration():
    """Record audio with fixed duration and process it"""
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
    
    try:
        # Record audio
        recording_file = record_audio(duration=duration)
        
        # Initialize Gemini
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
        print(f"❌ Error in record_fixed_duration: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/process_recording', methods=['POST'])
def process_recording():
    """Process a recording (for control mode)"""
    data = request.get_json()
    
    recording_file = data.get('recording_file')
    patient_id = data.get('patient_id')
    doctor_id = data.get('doctor_id')
    source_language = data.get('source_language', 'auto')
    
    if not all([recording_file, patient_id, doctor_id]):
        return jsonify({
            "success": False,
            "message": "Missing required parameters"
        }), 400
    
    try:
        # Initialize Gemini
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
        print(f"❌ Error processing recording: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/save_record', methods=['POST'])
def save_record():
    """Save recording to MongoDB"""
    data = request.get_json()
    
    if not mongo_client:
        return jsonify({
            "success": False,
            "message": "MongoDB not connected"
        }), 500
    
    try:
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
        
        print(f"✅ Record saved to MongoDB with ID: {result.inserted_id}")
        
        return jsonify({
            "success": True,
            "message": "Record saved successfully",
            "record_id": str(result.inserted_id)
        })
    
    except Exception as e:
        print(f"❌ Error saving record: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/patients/<patient_id>', methods=['GET'])
def get_patient_records(patient_id):
    """Get all records for a patient"""
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
        
        # Convert datetime to string
        for record in records:
            if 'timestamp' in record:
                record['timestamp'] = record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            "success": True,
            "records": records
        })
    
    except Exception as e:
        print(f"❌ Error fetching patient records: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/patients', methods=['GET'])
def get_all_patients():
    """Get list of all patients and stats"""
    if not mongo_client:
        return jsonify({
            "success": False,
            "message": "MongoDB not connected"
        }), 500
    
    try:
        # Get distinct patient IDs
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
        print(f"❌ Error fetching patients: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/api/update_test', methods=['POST'])
def update_test():
    """Update test status for a record"""
    data = request.get_json()
    
    if not mongo_client:
        return jsonify({
            "success": False,
            "message": "MongoDB not connected"
        }), 500
    
    try:
        patient_id = data.get('patient_id')
        record_index = data.get('record_index')
        test_name = data.get('test_name')
        status = data.get('status')
        
        # Get all records for patient
        records = list(records_col.find(
            {"patient_id": patient_id}
        ).sort("timestamp", -1))
        
        if record_index >= len(records):
            return jsonify({
                "success": False,
                "message": "Invalid record index"
            }), 400
        
        # Update the specific record
        record_id = records[record_index]['_id']
        
        records_col.update_one(
            {"_id": record_id},
            {"$set": {f"tests.{test_name}": status}}
        )
        
        return jsonify({
            "success": True,
            "message": "Test status updated"
        })
    
    except Exception as e:
        print(f"❌ Error updating test: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route('/recordings/<path:filename>', methods=['GET'])
def serve_recording(filename):
    """Serve audio recording files"""
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype='audio/wav')
    return jsonify({"error": "File not found"}), 404

# -------------------- RUN --------------------
if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('recordings', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    print("\n" + "="*50)
    print("🏥 Hospital Voice Recording System")
    print("="*50)
    print(f"MongoDB: {'✅ Connected' if mongo_client else '❌ Not Connected'}")
    print(f"Database: {db_name}")
    print("="*50 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)