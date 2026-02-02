from flask import Flask, request, jsonify, send_file
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
from deepgram import DeepgramClient, PrerecordedOptions
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
    """Configure Gemini API with your API key"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ GEMINI_API_KEY not found in .env file!")
    genai.configure(api_key=api_key)
    return genai


def initialize_gemini():
    """Initialize Gemini 2.5 Flash model (confirmed working)"""
    gemini = configure_gemini_api()
    try:
        # Use the exact model that works for you
        model = gemini.GenerativeModel('models/gemini-2.5-flash')
        print(f"✅ Successfully initialized: gemini-2.5-flash")
        return model
    except Exception as e:
        print(f"❌ Error initializing gemini-2.5-flash: {e}")
        if "quota" in str(e).lower() or "429" in str(e):
            print("💡 SOLUTION: Get new API key from https://aistudio.google.com/app/apikey")
        raise Exception(f"Could not initialize Gemini model: {e}")

# -------------------- DEEPGRAM --------------------
def initialize_deepgram():
    """Initialize Deepgram for live transcription"""
    try:
        deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
        if not deepgram_api_key:
            print("⚠️  DEEPGRAM_API_KEY not found - using Gemini fallback")
            return None
        
        dg_client = DeepgramClient(deepgram_api_key)
        print("✅ Deepgram initialized - Real-time transcription enabled")
        return dg_client
    except Exception as e:
        print(f"⚠️  Deepgram initialization failed: {e}")
        return None

# -------------------- MONGODB --------------------
try:
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    db_name = os.getenv("DB_NAME", "hospital_voice_db")

    mongo_client = MongoClient(mongo_uri)
    mongo_db = mongo_client[db_name]
    
    # Test connection
    mongo_client.server_info()
    
    patients_col = mongo_db["patients"]
    records_col = mongo_db["records"]
    doctors_col = mongo_db["doctors"]
    
    print("✅ MongoDB connected successfully")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    print("💡 Make sure MongoDB is running: mongod")
    raise

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

# -------------------- AUDIO RECORD --------------------
def record_audio(duration=10, sample_rate=44100):
    """Record audio for fixed duration"""
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    input=True,
                    frames_per_buffer=1024)

    frames = []
    print(f"🎤 Recording for {duration} seconds...")
    
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

    print(f"✅ Recording saved: {filename}")
    return filename

# -------------------- TRANSCRIPTION --------------------
def transcribe_and_translate(model, audio_file, source_language="auto"):
    """Transcribe and translate audio using Gemini 2.5 Flash"""
    try:
        with open(audio_file, "rb") as f:
            audio_data = f.read()

        audio_b64 = base64.b64encode(audio_data).decode()

        prompt_transcribe = """
        Please transcribe this audio file with high accuracy. 
        This is a doctor making clinical notes about a patient.
        Provide only the transcription, no additional commentary.
        """

        print("🔄 Transcribing audio with Gemini 2.5 Flash...")
        response = model.generate_content([
            prompt_transcribe,
            {"mime_type": "audio/wav", "data": audio_b64}
        ])

        transcript = response.text
        print(f"✅ Transcription complete: {len(transcript)} characters")

        # Check if translation needed
        has_non_english = bool(re.search(r'[^\x00-\x7F]', transcript))

        if has_non_english or source_language != 'en-US':
            prompt_translate = f"""
            Translate the following medical transcription to English.
            Provide only the translation, no additional commentary.
            
            Text:
            {transcript}
            """

            print("🔄 Translating to English...")
            translation_response = model.generate_content(prompt_translate)
            translation = translation_response.text
            print("✅ Translation complete")
        else:
            translation = transcript

        return transcript, translation
        
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower() or "429" in error_msg:
            raise Exception("❌ Gemini API quota exceeded! Get new key: https://aistudio.google.com/app/apikey")
        raise Exception(f"Transcription failed: {error_msg}")

# -------------------- SUMMARY --------------------
def generate_structured_medical_summary(model, translation):
    """Generate structured medical summary using Gemini 2.5 Flash"""
    try:
        prompt = f"""
        Create a structured medical summary in JSON format.
        Text: {translation}
        
        Return ONLY valid JSON in this exact format (no markdown, no code blocks):
        {{
          "summary": "brief summary here",
          "medical_condition": "condition here",
          "treatment_plan": "treatment here",
          "followup_date": "date here"
        }}
        """

        print("🔄 Generating medical summary...")
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
            print("✅ Summary generated successfully")
            return summary_data
        except:
            return {
                "summary": response_text,
                "medical_condition": "See summary",
                "treatment_plan": "See summary",
                "followup_date": "Not specified"
            }
            
    except Exception as e:
        if "quota" in str(e).lower() or "429" in str(e):
            raise Exception("❌ Gemini API quota exceeded during summary generation!")
        raise

# -------------------- DEEPGRAM ASYNC HANDLER --------------------
async def process_deepgram_stream(session_id, audio_data):
    """Process audio through Deepgram for live transcription"""
    try:
        session = live_sessions.get(session_id)
        if not session or not session.deepgram_client:
            return
        
        options = PrerecordedOptions(
            model="nova-2-medical",
            language=session.language_code,
            punctuate=True,
            smart_format=True
        )
        
        payload = {"buffer": audio_data}
        
        # SDK v3.2.7+ uses listen.prerecorded instead of listen.rest
        response = session.deepgram_client.listen.prerecorded.v("1").transcribe_file(
            payload, 
            options
        )
        
        if response and hasattr(response, 'results'):
            channels = response.results.channels
            if channels and len(channels) > 0:
                alternatives = channels[0].alternatives
                if alternatives and len(alternatives) > 0:
                    transcript_text = alternatives[0].transcript
                    confidence = alternatives[0].confidence
                    
                    if transcript_text:
                        session.add_transcript(transcript_text, True)
                        
                        socketio.emit('live_transcript', {
                            'transcript': transcript_text,
                            'is_final': True,
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
    """Start live transcription session"""
    try:
        session_id = request.sid
        language_code = data.get('language_code', 'en-US')
        
        session = LiveTranscriptionSession(session_id, language_code)
        session.is_active = True
        live_sessions[session_id] = session
        
        has_deepgram = session.deepgram_client is not None
        
        emit('live_transcription_started', {
            'success': True,
            'message': 'Live transcription started',
            'session_id': session_id,
            'has_deepgram': has_deepgram,
            'engine': 'Deepgram Nova-2 Medical' if has_deepgram else 'Gemini 2.5 Flash'
        })
        
        print(f"🎤 Started live transcription for session: {session_id}")
        
    except Exception as e:
        print(f"❌ Error starting live transcription: {e}")
        emit('live_transcription_error', {'success': False, 'error': str(e)})

@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """Receive and process audio chunks"""
    try:
        session_id = request.sid
        
        if session_id not in live_sessions:
            emit('live_transcription_error', {'error': 'No active session'})
            return
        
        session = live_sessions[session_id]
        
        audio_data = base64.b64decode(data['audio'])
        session.add_audio_chunk(audio_data)
        
        if session.deepgram_client:
            # Use Deepgram for real-time transcription
            def run_async():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(process_deepgram_stream(session_id, audio_data))
                loop.close()
            
            thread = Thread(target=run_async)
            thread.start()
        else:
            # Gemini fallback (slower, processes every 15th chunk)
            if len(session.audio_buffer) % 15 == 0:
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
        
        print(f"✅ Audio saved: {filename}")
        
        # Generate summary with Gemini
        try:
            model = initialize_gemini()
            
            translation = full_transcript
            if session.language_code != 'en-US':
                prompt_translate = f"Translate to English: {full_transcript}"
                translation_response = model.generate_content(prompt_translate)
                translation = translation_response.text
            
            summary_data = generate_structured_medical_summary(model, translation)
        except Exception as e:
            print(f"⚠️ Summary generation error: {e}")
            summary_data = {
                "summary": "Summary generation failed",
                "medical_condition": "See transcript",
                "treatment_plan": "See transcript",
                "followup_date": "Not specified"
            }
        
        emit('live_transcription_complete', {
            'success': True,
            'recording_file': filename,
            'original_transcript': full_transcript,
            'english_transcript': translation,
            'summary_data': summary_data,
            'transcript_buffer': session.transcript_buffer
        })
        
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
    """Record audio for fixed duration and process"""
    try:
        data = request.get_json()
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        duration = int(data.get('duration', 10))
        
        if not patient_id or not doctor_id:
            return jsonify({"success": False, "message": "Patient ID and Doctor ID required"}), 400
        
        print(f"\n{'='*60}")
        print(f"📝 New Recording Request:")
        print(f"   Patient ID: {patient_id}")
        print(f"   Doctor ID: {doctor_id}")
        print(f"   Duration: {duration}s")
        print(f"{'='*60}\n")
        
        model = initialize_gemini()
        recording_file = record_audio(duration=duration)
        transcript, translation = transcribe_and_translate(model, recording_file)
        summary_data = generate_structured_medical_summary(model, translation)
        
        print(f"\n✅ Processing complete!")
        print(f"{'='*60}\n")
        
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
        error_msg = str(e)
        print(f"\n❌ Error: {error_msg}\n")
        return jsonify({"success": False, "message": error_msg}), 500

@app.route('/save', methods=['POST'])
def save():
    """Save recording to database"""
    try:
        data = request.get_json()
        record = {
            "patient_id": data.get('patient_id'),
            "doctor_id": data.get('doctor_id'),
            "recording_file": data.get('recording_file'),
            "transcript": data.get('transcript'),
            "translation": data.get('translation'),
            "summary_data": data.get('summary_data'),
            "timestamp": datetime.utcnow()
        }
        
        result = records_col.insert_one(record)
        print(f"✅ Record saved to database: {result.inserted_id}")
        
        return jsonify({
            "success": True, 
            "message": "Saved successfully", 
            "record_id": str(result.inserted_id)
        }), 200
        
    except Exception as e:
        print(f"❌ Save error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/patients', methods=['GET'])
def api_get_all_patients():
    """Get all patients"""
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
    """Get records for specific patient"""
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
    """Serve audio recording files"""
    file_path = os.path.join('recordings', filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return jsonify({"error": "File not found"}), 404

# -------------------- RUN --------------------
if __name__ == '__main__':
    print("\n" + "="*70)
    print("🏥 Hospital Voice Recording System")
    print("="*70)
    print("✅ Server starting on http://localhost:5000")
    print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")
    
    # Initialize Gemini
    try:
        model = initialize_gemini()
        print("✅ Gemini 2.5 Flash initialized and ready")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        print("\n💡 SOLUTION:")
        print("   1. Get new API key: https://aistudio.google.com/app/apikey")
        print("   2. Add to .env file: GEMINI_API_KEY=your_key_here")
        print("   3. Restart the server\n")
        exit(1)
    
    # Check Deepgram
    dg = initialize_deepgram()
    if dg:
        print("✅ Live transcription: Deepgram Nova-2 Medical (⚡ FASTEST)")
    else:
        print("⚠️  Live transcription: Gemini 2.5 Flash fallback (slower)")
        print("💡 For better live transcription, add DEEPGRAM_API_KEY to .env")
    
    print("\n" + "="*70)
    print("🚀 Server ready! Open http://localhost:5000 in your browser")
    print("="*70 + "\n")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)