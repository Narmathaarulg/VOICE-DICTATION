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
from deepgram import Deepgram
import asyncio
from threading import Thread

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
    # Try multiple models
    model_names = [
        'gemini-1.5-flash-latest',
        'gemini-1.5-flash',
        'gemini-1.5-pro-latest',
        'gemini-pro'
    ]
    
    for model_name in model_names:
        try:
            model = gemini.GenerativeModel(model_name)
            test_response = model.generate_content("test")
            print(f"✅ Successfully initialized Gemini model: {model_name}")
            return model
        except Exception as e:
            print(f"⚠️ Model {model_name} not available: {e}")
            continue
    
    raise Exception("Could not initialize any Gemini model")

# -------------------- DEEPGRAM --------------------
def initialize_deepgram():
    """Initialize Deepgram client"""
    try:
        deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
        if not deepgram_api_key:
            print("⚠️ DEEPGRAM_API_KEY not found in .env")
            return None
        
        dg_client = Deepgram(deepgram_api_key)
        print("✅ Deepgram initialized successfully")
        return dg_client
    except Exception as e:
        print(f"⚠️ Deepgram initialization failed: {e}")
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
live_sessions = {}

class LiveTranscriptionSession:
    def __init__(self, session_id, language_code='en-US'):
        self.session_id = session_id
        self.language_code = language_code
        self.transcript_buffer = []
        self.full_transcript = ""
        self.audio_buffer = []
        self.is_active = False
        self.deepgram_client = initialize_deepgram()
        self.deepgram_connection = None
        
    def add_transcript(self, text, is_final=False):
        """Add transcribed text to buffer"""
        self.transcript_buffer.append({
            'text': text,
            'is_final': is_final,
            'timestamp': datetime.utcnow().isoformat()
        })
        
        if is_final:
            self.full_transcript += " " + text
    
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
        self.full_transcript = ""

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
    Create a structured medical summary in JSON format.
    Text: {translation}
    
    Return ONLY valid JSON in this exact format:
    {{
      "summary": "brief summary here",
      "medical_condition": "condition here",
      "treatment_plan": "treatment here",
      "followup_date": "date here"
    }}
    """

    response = model.generate_content(prompt)
    response_text = response.text.strip()

    # Remove markdown code blocks if present
    response_text = response_text.replace('```json', '').replace('```', '').strip()

    json_start = response_text.find('{')
    json_end = response_text.rfind('}')

    if json_start == -1 or json_end == -1:
        return {
            "summary": response_text,
            "medical_condition": "See summary",
            "treatment_plan": "See summary",
            "followup_date": "Not specified"
        }

    json_str = response_text[json_start:json_end+1]
    try:
        summary_data = json.loads(json_str)
    except:
        return {
            "summary": response_text,
            "medical_condition": "See summary",
            "treatment_plan": "See summary",
            "followup_date": "Not specified"
        }

    return summary_data

# -------------------- DEEPGRAM ASYNC HANDLER --------------------
async def process_deepgram_stream(session_id, audio_data):
    """Process audio through Deepgram (runs in async thread)"""
    try:
        session = live_sessions.get(session_id)
        if not session or not session.deepgram_client:
            return
        
        # Deepgram live streaming options
        options = {
            'punctuate': True,
            'interim_results': True,
            'language': session.language_code,
            'model': 'nova-2-medical',  # Medical model for better accuracy
            'smart_format': True
        }
        
        # Create live transcription source
        source = {'buffer': audio_data, 'mimetype': 'audio/wav'}
        
        # Get transcription
        response = await session.deepgram_client.transcription.live(source, options)
        
        # Process response
        if response and 'channel' in response:
            transcript_data = response['channel']['alternatives'][0]
            transcript_text = transcript_data.get('transcript', '')
            is_final = response.get('is_final', False)
            confidence = transcript_data.get('confidence', 0)
            
            if transcript_text:
                # Add to session
                session.add_transcript(transcript_text, is_final)
                
                # Emit to client via SocketIO
                socketio.emit('live_transcript', {
                    'transcript': transcript_text,
                    'is_final': is_final,
                    'confidence': confidence
                }, room=session_id)
                
    except Exception as e:
        print(f"⚠️ Deepgram processing error: {e}")

# -------------------- SOCKETIO EVENTS --------------------

@socketio.on('connect')
def handle_connect():
    print(f"✅ Client connected: {request.sid}")
    emit('connection_response', {'status': 'connected', 'sid': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"❌ Client disconnected: {request.sid}")
    if request.sid in live_sessions:
        live_sessions[request.sid].is_active = False
        del live_sessions[request.sid]

@socketio.on('start_live_transcription')
def handle_start_live_transcription(data):
    """Start live transcription with Deepgram"""
    try:
        session_id = request.sid
        language_code = data.get('language_code', 'en-US')
        
        # Create new session
        session = LiveTranscriptionSession(session_id, language_code)
        session.is_active = True
        live_sessions[session_id] = session
        
        has_deepgram = session.deepgram_client is not None
        
        emit('live_transcription_started', {
            'success': True,
            'message': 'Live transcription started',
            'session_id': session_id,
            'has_deepgram': has_deepgram,
            'engine': 'Deepgram Nova-2 Medical' if has_deepgram else 'Fallback mode'
        })
        
        print(f"🎤 Started live transcription for session: {session_id}")
        
    except Exception as e:
        print(f"❌ Error starting live transcription: {e}")
        emit('live_transcription_error', {'success': False, 'error': str(e)})

@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Receive and process audio chunks with Deepgram"""
    try:
        session_id = request.sid
        
        if session_id not in live_sessions:
            emit('live_transcription_error', {'error': 'No active session'})
            return
        
        session = live_sessions[session_id]
        
        # Get audio data (base64 encoded)
        audio_data = base64.b64decode(data['audio'])
        session.add_audio_chunk(audio_data)
        
        # Process with Deepgram if available
        if session.deepgram_client:
            # Run Deepgram processing in background thread
            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(process_deepgram_stream(session_id, audio_data))
                loop.close()
            
            thread = Thread(target=run_async)
            thread.start()
        else:
            # Fallback: Use Gemini (slower, for demo only)
            if len(session.audio_buffer) % 15 == 0:  # Process every 15th chunk
                try:
                    temp_filename = f"recordings/temp_live_{session_id}.wav"
                    os.makedirs(os.path.dirname(temp_filename), exist_ok=True)
                    
                    with wave.open(temp_filename, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(session.get_full_audio())
                    
                    model = initialize_gemini()
                    with open(temp_filename, "rb") as f:
                        audio_b64 = base64.b64encode(f.read()).decode()
                    
                    response = model.generate_content([
                        "Transcribe this medical audio briefly:",
                        {"mime_type": "audio/wav", "data": audio_b64}
                    ])
                    
                    transcript = response.text
                    
                    if transcript:
                        session.add_transcript(transcript, True)
                        emit('live_transcript', {
                            'transcript': transcript,
                            'is_final': True,
                            'confidence': 0.85
                        })
                    
                    if os.path.exists(temp_filename):
                        os.remove(temp_filename)
                        
                except Exception as e:
                    print(f"⚠️ Gemini fallback error: {e}")
                    
    except Exception as e:
        print(f"❌ Error processing audio chunk: {e}")
        emit('live_transcription_error', {'error': str(e)})

@socketio.on('stop_live_transcription')
def handle_stop_live_transcription(data):
    """Stop live transcription and generate summary"""
    try:
        session_id = request.sid
        
        if session_id not in live_sessions:
            emit('live_transcription_error', {'error': 'No active session'})
            return
        
        session = live_sessions[session_id]
        session.is_active = False
        
        # Get full transcript
        full_transcript = session.full_transcript.strip()
        
        if not full_transcript:
            full_transcript = "No audio detected"
        
        # Save audio file
        audio_bytes = session.get_full_audio()
        filename = f"recordings/live_recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_bytes)
        
        # Generate summary with Gemini
        model = initialize_gemini()
        
        translation = full_transcript
        if session.language_code != 'en-US':
            prompt_translate = f"Translate to English: {full_transcript}"
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
        
        # Clean up
        session.clear_buffers()
        del live_sessions[session_id]
        
        print(f"✅ Stopped live transcription for session: {session_id}")
        
    except Exception as e:
        print(f"❌ Error stopping live transcription: {e}")
        emit('live_transcription_error', {'error': str(e)})

# -------------------- REST API ROUTES --------------------

@app.route('/')
def serve_index():
    return app.send_static_file('index.html')

@app.route('/api/record_fixed_duration', methods=['POST'])
def api_record_fixed_duration():
    """Record for fixed duration"""
    try:
        data = request.get_json()
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        duration = int(data.get('duration', 10))
        
        if not patient_id or not doctor_id:
            return jsonify({"success": False, "message": "Patient ID and Doctor ID required"}), 400
        
        model = initialize_gemini()
        recording_file = record_audio(duration=duration)
        transcript, translation = transcribe_and_translate(model, recording_file)
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
        return jsonify({"success": True, "message": "Saved successfully", "record_id": str(result.inserted_id)}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/patients', methods=['GET'])
def api_get_all_patients():
    try:
        patient_ids = records_col.distinct("patient_id")
        total_records = records_col.count_documents({})
        return jsonify({"success": True, "patients": patient_ids, "stats": {"total_patients": len(patient_ids), "total_records": total_records}})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/patients/<patient_id>', methods=['GET'])
def api_get_patient_records(patient_id):
    try:
        records = list(records_col.find({"patient_id": patient_id}, {"_id": 0}).sort("timestamp", -1))
        for record in records:
            if 'timestamp' in record:
                record['timestamp'] = record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            if 'summary_data' in record:
                record['medical_condition'] = record['summary_data'].get('medical_condition', 'N/A')
                record['treatment_plan'] = record['summary_data'].get('treatment_plan', 'N/A')
                record['followup_date'] = record['summary_data'].get('followup_date', 'N/A')
        return jsonify({"success": True, "patient_id": patient_id, "records": records})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/recordings/<path:filename>', methods=['GET'])
def serve_recording(filename):
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return jsonify({"error": "File not found"}), 404

# -------------------- RUN --------------------
if __name__ == '__main__':
    print("\n" + "="*70)
    print("🏥 Hospital Voice Recording System - Deepgram Live Transcription")
    print("="*70)
    print("✅ Server starting on http://localhost:5000")
    
    # Initialize Gemini
    try:
        model = initialize_gemini()
        print("✅ Gemini API initialized successfully")
    except Exception as e:
        print(f"❌ CRITICAL: Could not initialize Gemini: {e}")
        exit(1)
    
    # Check Deepgram
    dg = initialize_deepgram()
    if dg:
        print("✅ Live transcription: Deepgram Nova-2 Medical (REAL-TIME ⚡)")
    else:
        print("⚠️  Live transcription: Gemini fallback (SLOWER)")
        print("💡 Add DEEPGRAM_API_KEY to .env for real-time transcription")
    
    print("="*70 + "\n")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)