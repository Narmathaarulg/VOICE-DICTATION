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
from pymongo import MongoClient
import io
import threading

# -------------------- ENV --------------------
load_dotenv()

# -------------------- APP --------------------
app = Flask(__name__, static_folder='temp', static_url_path='')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# -------------------- GEMINI --------------------
def configure_gemini_api():
    api_key = os.environ.get("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    return genai


def initialize_gemini():
    gemini = configure_gemini_api()
    # ✅ FIXED: Use correct model name
    model = gemini.GenerativeModel('models/gemini-1.5-flash')  # Changed from gemini-2.0-flash-exp
    return model

# -------------------- GOOGLE SPEECH CLIENT --------------------
def initialize_speech_client():
    """Initialize Google Speech-to-Text client"""
    try:
        from google.cloud import speech_v1p1beta1 as speech
        client = speech.SpeechClient()
        print("✅ Google Speech-to-Text initialized successfully")
        return client
    except Exception as e:
        print(f"⚠️ Google Speech-to-Text not available: {e}")
        print("💡 Live transcription will use Gemini API fallback (slower)")
        return None

# -------------------- MONGODB --------------------
mongo_uri = os.getenv("MONGO_URI")
db_name = os.getenv("DB_NAME")

mongo_client = MongoClient(mongo_uri)
mongo_db = mongo_client[db_name]

patients_col = mongo_db["patients"]
records_col = mongo_db["records"]
doctors_col = mongo_db["doctors"]

# -------------------- LIVE TRANSCRIPTION STATE --------------------
live_sessions = {}  # Store active live transcription sessions

class LiveTranscriptionSession:
    def __init__(self, session_id, language_code='en-US'):
        self.session_id = session_id
        self.language_code = language_code
        self.transcript_buffer = []
        self.audio_buffer = []
        self.is_active = False
        self.speech_client = initialize_speech_client()
        self.last_transcript = ""
        
    def add_audio_chunk(self, audio_data):
        """Add audio chunk to buffer"""
        self.audio_buffer.append(audio_data)
        
    def get_full_audio(self):
        """Get complete audio as bytes"""
        return b''.join(self.audio_buffer)
    
    def clear_buffers(self):
        """Clear all buffers"""
        self.transcript_buffer = []
        self.audio_buffer = []

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

# -------------------- SOCKETIO EVENTS FOR LIVE TRANSCRIPTION --------------------

@socketio.on('connect')
def handle_connect():
    print(f"✅ Client connected: {request.sid}")
    emit('connection_response', {'status': 'connected', 'sid': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"❌ Client disconnected: {request.sid}")
    # Clean up session if exists
    if request.sid in live_sessions:
        live_sessions[request.sid].is_active = False
        del live_sessions[request.sid]

@socketio.on('start_live_transcription')
def handle_start_live_transcription(data):
    """Start a new live transcription session"""
    try:
        session_id = request.sid
        language_code = data.get('language_code', 'en-US')
        
        # Create new session
        session = LiveTranscriptionSession(session_id, language_code)
        session.is_active = True
        live_sessions[session_id] = session
        
        emit('live_transcription_started', {
            'success': True,
            'message': 'Live transcription started',
            'session_id': session_id,
            'has_google_speech': session.speech_client is not None
        })
        
        print(f"🎤 Started live transcription for session: {session_id}")
        
    except Exception as e:
        print(f"❌ Error starting live transcription: {e}")
        emit('live_transcription_error', {
            'success': False,
            'error': str(e)
        })

@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Receive and process audio chunks in real-time"""
    try:
        session_id = request.sid
        
        if session_id not in live_sessions:
            emit('live_transcription_error', {'error': 'No active session'})
            return
        
        session = live_sessions[session_id]
        
        # Get audio data (base64 encoded)
        audio_data = base64.b64decode(data['audio'])
        session.add_audio_chunk(audio_data)
        
        # Use Google Speech-to-Text if available
        if session.speech_client:
            try:
                from google.cloud import speech_v1p1beta1 as speech
                
                # Configure recognition
                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=16000,
                    language_code=session.language_code,
                    enable_automatic_punctuation=True,
                    model='medical_conversation'
                )
                
                audio = speech.RecognitionAudio(content=audio_data)
                
                # Perform transcription
                response = session.speech_client.recognize(config=config, audio=audio)
                
                # Process results
                for result in response.results:
                    transcript = result.alternatives[0].transcript
                    confidence = result.alternatives[0].confidence
                    
                    # Add to session buffer
                    session.transcript_buffer.append({
                        'text': transcript,
                        'confidence': confidence,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                    # Emit live transcript to client
                    emit('live_transcript', {
                        'transcript': transcript,
                        'confidence': confidence,
                        'is_final': result.is_final
                    })
                    
            except Exception as e:
                print(f"⚠️ Speech recognition error: {e}")
                # Don't show error to user, just skip this chunk
                
        else:
            # Fallback: Use Gemini for transcription (accumulate chunks first)
            # Only process every 10th chunk to avoid rate limits
            if len(session.audio_buffer) % 10 == 0 and len(session.audio_buffer) > 0:
                try:
                    # Create temporary wav file
                    temp_filename = f"recordings/temp_live_{session_id}.wav"
                    os.makedirs(os.path.dirname(temp_filename), exist_ok=True)
                    
                    with wave.open(temp_filename, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(session.get_full_audio())
                    
                    # Use Gemini to transcribe
                    model = initialize_gemini()
                    with open(temp_filename, "rb") as f:
                        audio_b64 = base64.b64encode(f.read()).decode()
                    
                    response = model.generate_content([
                        "Transcribe this audio briefly:",
                        {"mime_type": "audio/wav", "data": audio_b64}
                    ])
                    
                    transcript = response.text
                    
                    # Only emit if we got new content
                    if transcript and transcript != session.last_transcript:
                        session.last_transcript = transcript
                        emit('live_transcript', {
                            'transcript': transcript,
                            'confidence': 0.9,
                            'is_final': False
                        })
                    
                    # Clean up temp file
                    os.remove(temp_filename)
                    
                except Exception as e:
                    print(f"⚠️ Gemini transcription error: {e}")
            
    except Exception as e:
        print(f"❌ Error processing audio chunk: {e}")
        emit('live_transcription_error', {'error': str(e)})

@socketio.on('stop_live_transcription')
def handle_stop_live_transcription(data):
    """Stop live transcription and process final result"""
    try:
        session_id = request.sid
        
        if session_id not in live_sessions:
            emit('live_transcription_error', {'error': 'No active session'})
            return
        
        session = live_sessions[session_id]
        session.is_active = False
        
        # Get full transcript
        full_transcript = ' '.join([t['text'] for t in session.transcript_buffer])
        
        # If no transcript from Google Speech, use Gemini as fallback
        if not full_transcript or full_transcript.strip() == '':
            full_transcript = session.last_transcript or "No audio detected"
        
        # Save audio file
        audio_bytes = session.get_full_audio()
        filename = f"recordings/live_recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Write WAV file
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_bytes)
        
        # Generate summary using Gemini
        model = initialize_gemini()
        
        # If transcript is not in English, translate it
        translation = full_transcript
        if session.language_code != 'en-US':
            prompt_translate = f"""
            Translate the following medical transcription to English.
            Text: {full_transcript}
            """
            translation_response = model.generate_content(prompt_translate)
            translation = translation_response.text
        
        # Generate medical summary
        summary_data = generate_structured_medical_summary(model, translation)
        
        # Send final results
        emit('live_transcription_complete', {
            'success': True,
            'recording_file': filename,
            'original_transcript': full_transcript,
            'english_transcript': translation,
            'summary_data': summary_data,
            'transcript_buffer': session.transcript_buffer
        })
        
        # Clean up session
        session.clear_buffers()
        del live_sessions[session_id]
        
        print(f"✅ Stopped live transcription for session: {session_id}")
        
    except Exception as e:
        print(f"❌ Error stopping live transcription: {e}")
        emit('live_transcription_error', {'error': str(e)})

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
    records = list(records_col.find({"patient_id": patient_id}, {"_id": 0}))
    return jsonify(records)


@app.route('/recordings/<path:filename>', methods=['GET'])
def serve_recording(filename):
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return jsonify({"error": "File not found"}), 404


# -------------------- API ROUTES --------------------

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
    print("🏥 Hospital Voice Recording System - Live Transcription")
    print("="*60)
    print("✅ Server starting on http://localhost:5000")
    print("📝 Using Gemini model: gemini-1.5-flash")
    
    # Check Google Speech availability
    speech_client = initialize_speech_client()
    if speech_client:
        print("✅ Live transcription: Google Speech-to-Text (FAST)")
    else:
        print("⚠️  Live transcription: Gemini fallback (SLOWER)")
        print("💡 To enable fast live transcription, set up Google Cloud Speech-to-Text")
    
    print("="*60 + "\n")
    
    # Use socketio.run instead of app.run for WebSocket support
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)