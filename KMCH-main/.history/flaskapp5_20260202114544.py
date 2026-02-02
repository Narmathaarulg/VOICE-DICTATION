from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
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
import asyncio
from threading import Thread

# -------------------- EVENTLET MONKEY PATCH (CRITICAL FIX!) --------------------
# This MUST be done BEFORE importing pymongo
import eventlet
eventlet.monkey_patch()

# NOW import pymongo after eventlet is patched
from pymongo import MongoClient
from deepgram_service import DeepgramService

# -------------------- ENV --------------------
load_dotenv()

# -------------------- APP --------------------
app = Flask(__name__, static_folder='temp', static_url_path='')
CORS(app, resources={r"/*": {"origins": "*"}})

# -------------------- SOCKETIO --------------------
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# -------------------- GEMINI --------------------
def configure_gemini_api():
    api_key = os.environ.get("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    return genai


def initialize_gemini():
    gemini = configure_gemini_api()
    model = gemini.GenerativeModel('models/gemini-2.0-flash-exp')
    return model

# -------------------- MONGODB (FIXED!) --------------------
# Use direct IP or localhost instead of hostname to avoid DNS issues
mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
db_name = os.getenv("DB_NAME", "hospital_voice_db")

print(f"📡 Connecting to MongoDB: {mongo_uri}")

try:
    # Add timeout and direct connection options
    mongo_client = MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=5000,
        directConnection=True,
        connect=False  # Don't connect immediately, connect on first use
    )
    
    mongo_db = mongo_client[db_name]
    patients_col = mongo_db["patients"]
    records_col = mongo_db["records"]
    doctors_col = mongo_db["doctors"]
    
    print("✅ MongoDB client initialized")
except Exception as e:
    print(f"⚠️ MongoDB initialization warning: {e}")
    print("💡 The app will try to connect when needed")

# -------------------- AUDIO STREAMING STATE --------------------
recording_state = {
    "is_recording": False,
    "audio_chunks": [],
    "stream": None,
    "p": None
}

# -------------------- LIVE TRANSCRIPTION STATE --------------------
active_transcriptions = {}

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

    if json_start != -1 and json_end != -1:
        json_str = response_text[json_start:json_end+1]
        summary_data = json.loads(json_str)
        return summary_data
    else:
        return {
            "summary": translation[:200],
            "medical_condition": "Not extracted",
            "treatment_plan": "Not extracted",
            "followup_date": "Not specified"
        }

# ==================== SOCKETIO EVENTS ====================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f'✅ Client connected: {request.sid}')
    emit('connection_status', {'status': 'connected', 'message': 'Connected to server'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f'❌ Client disconnected: {request.sid}')
    
    if request.sid in active_transcriptions:
        transcription_data = active_transcriptions[request.sid]
        if 'service' in transcription_data:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(transcription_data['service'].finish())
            loop.close()
        
        del active_transcriptions[request.sid]


@socketio.on('start_live_transcription')
def handle_start_live_transcription(data):
    """Start live transcription session"""
    try:
        print(f'🎤 Starting live transcription for client: {request.sid}')
        language_code = data.get('language_code', 'en-US')
        
        deepgram_service = DeepgramService()
        
        active_transcriptions[request.sid] = {
            'service': deepgram_service,
            'language_code': language_code,
            'transcript_parts': [],
            'interim_transcript': '',
            'start_time': datetime.utcnow()
        }
        
        async def send_transcript_to_client(transcript, is_final):
            session_data = active_transcriptions.get(request.sid)
            if not session_data:
                return
            
            if is_final:
                session_data['transcript_parts'].append(transcript)
                session_data['interim_transcript'] = ''
            else:
                session_data['interim_transcript'] = transcript
            
            socketio.emit('live_transcript', {
                'transcript': transcript,
                'is_final': is_final,
                'confidence': 0.9
            }, room=request.sid)
        
        def start_deepgram():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                deepgram_service.start_transcription(send_transcript_to_client)
            )
            loop.close()
        
        thread = Thread(target=start_deepgram)
        thread.daemon = True
        thread.start()
        
        time.sleep(0.5)
        
        emit('transcription_started', {
            'status': 'success',
            'message': 'Live transcription started'
        })
        
    except Exception as e:
        print(f'❌ Error starting transcription: {e}')
        import traceback
        traceback.print_exc()
        emit('live_transcription_error', {
            'error': str(e)
        })


@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Receive and process audio chunks"""
    try:
        if request.sid not in active_transcriptions:
            return
        
        session_data = active_transcriptions[request.sid]
        deepgram_service = session_data['service']
        
        audio_base64 = data.get('audio', '')
        audio_bytes = base64.b64decode(audio_base64)
        
        def send_audio():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(deepgram_service.send_audio(audio_bytes))
            loop.close()
        
        thread = Thread(target=send_audio)
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        print(f'❌ Error processing audio chunk: {e}')


@socketio.on('stop_live_transcription')
def handle_stop_live_transcription(data):
    """Stop live transcription and process final results"""
    try:
        print(f'🛑 Stopping live transcription for client: {request.sid}')
        
        if request.sid not in active_transcriptions:
            emit('live_transcription_error', {
                'error': 'No active transcription session'
            })
            return
        
        session_data = active_transcriptions[request.sid]
        deepgram_service = session_data['service']
        
        def finalize_transcription():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            final_transcript = loop.run_until_complete(deepgram_service.finish())
            loop.close()
            
            try:
                model = initialize_gemini()
                english_transcript = final_transcript
                summary_data = generate_structured_medical_summary(model, english_transcript)
                
                recording_file = f"recordings/live_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                os.makedirs(os.path.dirname(recording_file), exist_ok=True)
                
                with open(recording_file, 'w') as f:
                    f.write(final_transcript)
                
                socketio.emit('live_transcription_complete', {
                    'success': True,
                    'original_transcript': final_transcript,
                    'english_transcript': english_transcript,
                    'summary_data': summary_data,
                    'recording_file': recording_file
                }, room=request.sid)
                
            except Exception as e:
                print(f'❌ Error processing final transcript: {e}')
                socketio.emit('live_transcription_error', {
                    'error': f'Failed to process transcript: {str(e)}'
                }, room=request.sid)
            
            if request.sid in active_transcriptions:
                del active_transcriptions[request.sid]
        
        thread = Thread(target=finalize_transcription)
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        print(f'❌ Error stopping transcription: {e}')
        emit('live_transcription_error', {
            'error': str(e)
        })

# ==================== ROUTES ====================

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
    try:
        data = request.get_json()

        record = {
            "patient_id": data.get('patient_id'),
            "doctor_id": data.get('doctor_id'),
            "recording_file": data.get('recording_file'),
            "transcript": data.get('transcript'),
            "translation": data.get('translation'),
            "summary_data": data.get('summary_data'),
            "timestamp": datetime.utcnow(),
            "tests": {}
        }

        result = records_col.insert_one(record)
        
        return jsonify({
            "success": True, 
            "message": "Saved to MongoDB successfully",
            "record_id": str(result.inserted_id)
        }), 200
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/records/<patient_id>', methods=['GET'])
def get_records(patient_id):
    try:
        records = list(records_col.find({"patient_id": patient_id}, {"_id": 0}))
        return jsonify(records)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/recordings/<path:filename>', methods=['GET'])
def serve_recording(filename):
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return jsonify({"error": "File not found"}), 404


@app.route('/api/start_recording', methods=['POST'])
def api_start_recording():
    """Start recording in control mode"""
    try:
        if recording_state["is_recording"]:
            return jsonify({"success": False, "message": "Already recording"}), 400
        
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
        
        stream = recording_state["stream"]
        p = recording_state["p"]
        
        while stream.is_active():
            data = stream.read(1024, exception_on_overflow=False)
            recording_state["audio_chunks"].append(data)
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
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


@app.route('/api/process_recording', methods=['POST'])
def api_process_recording():
    """Process an existing recording"""
    try:
        data = request.get_json()
        recording_file = data.get('recording_file')
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        source_language = data.get('source_language', 'auto')
        
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


@app.route('/api/patients', methods=['GET'])
def api_get_all_patients():
    """Get all patients summary"""
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
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/patients/<patient_id>', methods=['GET'])
def api_get_patient_records(patient_id):
    """Get records for a specific patient"""
    try:
        records = list(records_col.find(
            {"patient_id": patient_id},
            {"_id": 0}
        ).sort("timestamp", -1))
        
        for record in records:
            if 'timestamp' in record:
                record['timestamp'] = record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            
            if 'summary_data' in record:
                record['medical_condition'] = record['summary_data'].get('medical_condition', 'N/A')
                record['treatment_plan'] = record['summary_data'].get('treatment_plan', 'N/A')
                record['followup_date'] = record['summary_data'].get('followup_date', 'N/A')
            
            if 'recording_file' in record:
                record['recording_path'] = record['recording_file']
            
            if 'transcript' in record:
                record['original_transcript'] = record['transcript']
            if 'translation' in record:
                record['english_transcript'] = record['translation']
        
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
        
        records = list(records_col.find(
            {"patient_id": patient_id}
        ).sort("timestamp", -1))
        
        if record_index >= len(records):
            return jsonify({"success": False, "message": "Invalid record index"}), 400
        
        record = records[record_index]
        
        if 'tests' not in record:
            record['tests'] = {}
        
        record['tests'][test_name] = status
        
        records_col.update_one(
            {"_id": record["_id"]},
            {"$set": {"tests": record['tests']}}
        )
        
        return jsonify({"success": True, "message": "Test updated successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -------------------- RUN --------------------
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 Hospital Voice Recording System - Starting...")
    print("="*60)
    print("📡 Live Transcription: ENABLED")
    print("🎤 Deepgram Integration: ACTIVE")
    print("💾 MongoDB: Lazy connection (connects on first use)")
    print("🌐 Server: http://localhost:5000")
    print("="*60 + "\n")
    
    # Use eventlet with socketio
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)