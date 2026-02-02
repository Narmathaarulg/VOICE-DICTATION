from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
import os
import time
from datetime import datetime
import google.generativeai as genai
import base64
import json
import re
import asyncio
from threading import Thread
from pymongo import MongoClient

# Import the Deepgram service
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

# -------------------- MONGODB --------------------
mongo_uri = os.getenv("MONGO_URI")
db_name = os.getenv("DB_NAME")

mongo_client = MongoClient(mongo_uri)
mongo_db = mongo_client[db_name]

patients_col = mongo_db["patients"]
records_col = mongo_db["records"]
doctors_col = mongo_db["doctors"]

# -------------------- GLOBAL STATE --------------------
active_transcriptions = {}

# -------------------- TRANSCRIPTION FUNCTIONS --------------------
def generate_structured_medical_summary(model, translation):
    """Generate medical summary using Gemini"""
    prompt = f"""
    Create a structured medical summary in JSON format from the following medical transcription.
    
    Text: {translation}
    
    Return ONLY valid JSON in this exact format:
    {{
      "summary": "Brief overview of the consultation",
      "medical_condition": "Patient's condition/diagnosis",
      "treatment_plan": "Recommended treatment",
      "followup_date": "Follow-up date if mentioned, otherwise 'Not specified'"
    }}
    """

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()

        # Extract JSON from response
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')

        if json_start != -1 and json_end != -1:
            json_str = response_text[json_start:json_end+1]
            summary_data = json.loads(json_str)
            return summary_data
        else:
            # Return default structure if JSON not found
            return {
                "summary": translation[:200],
                "medical_condition": "Not extracted",
                "treatment_plan": "Not extracted",
                "followup_date": "Not specified"
            }
    except Exception as e:
        print(f"❌ Error generating summary: {e}")
        return {
            "summary": translation[:200],
            "medical_condition": "Error extracting",
            "treatment_plan": "Error extracting",
            "followup_date": "Not specified"
        }

# -------------------- SOCKETIO EVENT HANDLERS --------------------

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f'✅ Client connected: {request.sid}')
    emit('connection_status', {'status': 'connected', 'message': 'Connected to server'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f'❌ Client disconnected: {request.sid}')
    
    # Clean up any active transcription for this client
    if request.sid in active_transcriptions:
        transcription_data = active_transcriptions[request.sid]
        if 'service' in transcription_data:
            # Stop the Deepgram service
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
        
        # Create Deepgram service instance
        deepgram_service = DeepgramService()
        
        # Store session data
        active_transcriptions[request.sid] = {
            'service': deepgram_service,
            'language_code': language_code,
            'transcript_parts': [],
            'interim_transcript': '',
            'start_time': datetime.utcnow()
        }
        
        # Callback function to send transcripts to client
        async def send_transcript_to_client(transcript, is_final):
            session_data = active_transcriptions.get(request.sid)
            if not session_data:
                return
            
            if is_final:
                # Store final transcript parts
                session_data['transcript_parts'].append(transcript)
                session_data['interim_transcript'] = ''
            else:
                # Update interim transcript
                session_data['interim_transcript'] = transcript
            
            # Emit to client
            socketio.emit('live_transcript', {
                'transcript': transcript,
                'is_final': is_final,
                'confidence': 0.9
            }, room=request.sid)
        
        # Start Deepgram transcription in background
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
        
        # Wait a bit for connection to establish
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
            print(f'⚠️ No active transcription for client: {request.sid}')
            return
        
        session_data = active_transcriptions[request.sid]
        deepgram_service = session_data['service']
        
        # Decode base64 audio
        audio_base64 = data.get('audio', '')
        audio_bytes = base64.b64decode(audio_base64)
        
        # Send to Deepgram asynchronously
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
        
        # Stop Deepgram and get final transcript
        def finalize_transcription():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            final_transcript = loop.run_until_complete(deepgram_service.finish())
            loop.close()
            
            # Process with Gemini
            try:
                model = initialize_gemini()
                
                # For now, assume English (you can add translation later)
                english_transcript = final_transcript
                
                # Generate summary
                summary_data = generate_structured_medical_summary(model, english_transcript)
                
                # Generate a temporary recording filename
                recording_file = f"recordings/live_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                os.makedirs(os.path.dirname(recording_file), exist_ok=True)
                
                # Save transcript to file
                with open(recording_file, 'w') as f:
                    f.write(final_transcript)
                
                # Send complete results to client
                socketio.emit('live_transcription_complete', {
                    'success': True,
                    'original_transcript': final_transcript,
                    'english_transcript': english_transcript,
                    'summary_data': summary_data,
                    'recording_file': recording_file
                }, room=request.sid)
                
            except Exception as e:
                print(f'❌ Error processing final transcript: {e}')
                import traceback
                traceback.print_exc()
                
                socketio.emit('live_transcription_error', {
                    'error': f'Failed to process transcript: {str(e)}'
                }, room=request.sid)
            
            # Clean up
            if request.sid in active_transcriptions:
                del active_transcriptions[request.sid]
        
        thread = Thread(target=finalize_transcription)
        thread.daemon = True
        thread.start()
        
    except Exception as e:
        print(f'❌ Error stopping transcription: {e}')
        import traceback
        traceback.print_exc()
        emit('live_transcription_error', {
            'error': str(e)
        })


# -------------------- EXISTING ROUTES --------------------

@app.route('/')
def serve_index():
    return app.send_static_file('index.html')


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
    print("🚀 Starting Flask-SocketIO server...")
    print("📡 WebSocket support enabled for live transcription")
    print("🎤 Deepgram integration active")
    
    # Use eventlet for better async support
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)