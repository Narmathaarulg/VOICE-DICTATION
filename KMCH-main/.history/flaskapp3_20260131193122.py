from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import os
import base64
import json
import re
import logging
from datetime import datetime, timedelta
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configuration
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///medical_records.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-key-change-in-production'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY') or Fernet.generate_key()
    MAX_RECORDING_DURATION = 300  # 5 minutes
    UPLOAD_FOLDER = 'recordings'
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size

app.config.from_object(Config)

# Initialize extensions
db = SQLAlchemy(app)
jwt = JWTManager(app)
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:3000", "http://localhost:5000"],
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('medical_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize encryption
cipher_suite = Fernet(app.config['ENCRYPTION_KEY'])

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============================================================================
# DATABASE MODELS
# ============================================================================

class User(db.Model):
    """User model for doctors and administrators"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='doctor')  # doctor, admin
    license_number = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    records = db.relationship('MedicalRecord', backref='doctor', lazy=True)
    audit_logs = db.relationship('AuditLog', backref='user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'role': self.role,
            'license_number': self.license_number
        }


class Patient(db.Model):
    """Patient model"""
    __tablename__ = 'patients'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address_encrypted = db.Column(db.Text)  # Encrypted
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    records = db.relationship('MedicalRecord', backref='patient', lazy=True)
    
    def set_address(self, address):
        """Encrypt and store address"""
        if address:
            self.address_encrypted = cipher_suite.encrypt(address.encode()).decode()
    
    def get_address(self):
        """Decrypt and return address"""
        if self.address_encrypted:
            return cipher_suite.decrypt(self.address_encrypted.encode()).decode()
        return None
    
    def to_dict(self, include_sensitive=False):
        data = {
            'id': self.id,
            'patient_id': self.patient_id,
            'full_name': self.full_name,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'gender': self.gender,
            'created_at': self.created_at.isoformat()
        }
        if include_sensitive:
            data.update({
                'phone': self.phone,
                'email': self.email,
                'address': self.get_address()
            })
        return data


class MedicalRecord(db.Model):
    """Medical record model"""
    __tablename__ = 'medical_records'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    recording_filename = db.Column(db.String(255))
    transcript_encrypted = db.Column(db.Text)  # Encrypted
    translation_encrypted = db.Column(db.Text)  # Encrypted
    summary_encrypted = db.Column(db.Text)  # Encrypted (JSON)
    source_language = db.Column(db.String(20))
    recording_duration = db.Column(db.Integer)  # in seconds
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def set_transcript(self, transcript):
        """Encrypt and store transcript"""
        if transcript:
            self.transcript_encrypted = cipher_suite.encrypt(transcript.encode()).decode()
    
    def get_transcript(self):
        """Decrypt and return transcript"""
        if self.transcript_encrypted:
            return cipher_suite.decrypt(self.transcript_encrypted.encode()).decode()
        return None
    
    def set_translation(self, translation):
        """Encrypt and store translation"""
        if translation:
            self.translation_encrypted = cipher_suite.encrypt(translation.encode()).decode()
    
    def get_translation(self):
        """Decrypt and return translation"""
        if self.translation_encrypted:
            return cipher_suite.decrypt(self.translation_encrypted.encode()).decode()
        return None
    
    def set_summary(self, summary_dict):
        """Encrypt and store summary"""
        if summary_dict:
            summary_json = json.dumps(summary_dict)
            self.summary_encrypted = cipher_suite.encrypt(summary_json.encode()).decode()
    
    def get_summary(self):
        """Decrypt and return summary"""
        if self.summary_encrypted:
            summary_json = cipher_suite.decrypt(self.summary_encrypted.encode()).decode()
            return json.loads(summary_json)
        return {}
    
    def to_dict(self, include_sensitive=True):
        data = {
            'id': self.id,
            'patient_id': self.patient_id,
            'doctor_id': self.doctor_id,
            'doctor_name': self.doctor.full_name if self.doctor else None,
            'recording_filename': self.recording_filename,
            'source_language': self.source_language,
            'recording_duration': self.recording_duration,
            'created_at': self.created_at.isoformat()
        }
        if include_sensitive:
            data.update({
                'transcript': self.get_transcript(),
                'translation': self.get_translation(),
                'summary': self.get_summary()
            })
        return data


class AuditLog(db.Model):
    """Audit log for tracking all access to patient data"""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)  # VIEW, CREATE, UPDATE, DELETE
    resource_type = db.Column(db.String(50), nullable=False)  # PATIENT, RECORD, USER
    resource_id = db.Column(db.Integer)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(255))
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp.isoformat()
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def log_audit(user_id, action, resource_type, resource_id=None, details=None):
    """Log an audit entry"""
    try:
        audit = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:255],
            details=details
        )
        db.session.add(audit)
        db.session.commit()
        logger.info(f"Audit log: User {user_id} performed {action} on {resource_type} {resource_id}")
    except Exception as e:
        logger.error(f"Failed to log audit: {str(e)}")


def success_response(data=None, message="Success", status=200):
    """Standardized success response"""
    response = {
        "success": True,
        "message": message
    }
    if data is not None:
        response["data"] = data
    return jsonify(response), status


def error_response(message, status=400, details=None):
    """Standardized error response"""
    response = {
        "success": False,
        "error": message
    }
    if details:
        response["details"] = details
    return jsonify(response), status


def validate_patient_id(patient_id):
    """Validate patient ID format"""
    if not patient_id or not isinstance(patient_id, str):
        return False
    # Patient ID should be alphanumeric, 6-20 characters
    return bool(re.match(r'^[A-Z0-9]{6,20}$', patient_id.upper()))


def initialize_gemini():
    """Initialize Gemini AI model"""
    try:
        genai.configure(api_key=app.config['GEMINI_API_KEY'])
        model = genai.GenerativeModel('gemini-1.5-pro')
        return model
    except Exception as e:
        logger.error(f"Failed to initialize Gemini: {str(e)}")
        raise


def transcribe_audio(model, audio_data, source_language="auto"):
    """Transcribe audio using Gemini"""
    try:
        audio_b64 = base64.b64encode(audio_data).decode()
        
        prompt = f"""
        Please transcribe this audio file with high accuracy. This is a doctor making clinical notes about a patient.
        
        Important guidelines for medical transcription:
        - Pay special attention to medical terminology, drug names, and dosages
        - Maintain exact numbers for vital signs, test results, and medication dosages
        - Indicate any parts that are unclear with [unclear]
        - Preserve all medical abbreviations as spoken
        
        The language may be {source_language} or could be any language if auto-detected.
        """
        
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": audio_b64}
        ])
        
        transcript = response.text
        return transcript
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        raise


def translate_text(model, text):
    """Translate text to English using Gemini"""
    try:
        # Check if text contains non-English characters
        has_non_english = bool(re.search(r'[^\x00-\x7F]', text))
        
        if not has_non_english:
            return text
        
        prompt = f"""
        Translate the following medical transcription to English.
        
        IMPORTANT:
        - This text may contain a mix of English and non-English languages
        - Translate ALL non-English parts to English
        - Preserve all medical terminology exactly as stated
        - Maintain numerical values and units precisely
        - If you're unsure about any term, indicate with [uncertain: original_term]
        
        Text to translate:
        {text}
        """
        
        response = model.generate_content(prompt)
        translation = response.text
        return translation
    except Exception as e:
        logger.error(f"Translation failed: {str(e)}")
        return text


def generate_medical_summary(model, translation):
    """Generate structured medical summary using Gemini"""
    try:
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
        
        Doctor's notes:
        {translation}
        
        Format your response as a valid JSON object with these keys:
        - "summary": A concise overview of the patient's condition
        - "medical_condition": Primary diagnoses or issues identified
        - "treatment_plan": Specific treatments, medications, or procedures recommended
        - "followup_date": Any follow-up dates mentioned (format as MM/DD/YYYY if possible)
        - "vital_signs": Any vital signs mentioned (blood pressure, temperature, heart rate, etc.)
        - "medications": List of medications prescribed or discussed
        """
        
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Extract JSON from response
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')
        
        if json_start >= 0 and json_end >= 0:
            json_str = response_text[json_start:json_end+1]
            summary_data = json.loads(json_str)
        else:
            summary_data = json.loads(response_text)
        
        # Ensure all required keys exist
        required_keys = ["summary", "medical_condition", "treatment_plan", "followup_date"]
        for key in required_keys:
            if key not in summary_data:
                summary_data[key] = "Not specified"
        
        return summary_data
    except Exception as e:
        logger.error(f"Summary generation failed: {str(e)}")
        return {
            "summary": "Error generating summary.",
            "medical_condition": "Not extracted",
            "treatment_plan": "Not extracted",
            "followup_date": "Not extracted"
        }


# ============================================================================
# API ENDPOINTS - AUTHENTICATION
# ============================================================================

@app.route('/api/auth/register', methods=['POST'])
@limiter.limit("5 per hour")
def register():
    """Register a new user (doctor)"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'email', 'password', 'full_name']
        for field in required_fields:
            if field not in data:
                return error_response(f"Missing required field: {field}", 400)
        
        # Check if user already exists
        if User.query.filter_by(username=data['username']).first():
            return error_response("Username already exists", 400)
        
        if User.query.filter_by(email=data['email']).first():
            return error_response("Email already exists", 400)
        
        # Create new user
        user = User(
            username=data['username'],
            email=data['email'],
            full_name=data['full_name'],
            role=data.get('role', 'doctor'),
            license_number=data.get('license_number')
        )
        user.set_password(data['password'])
        
        db.session.add(user)
        db.session.commit()
        
        logger.info(f"New user registered: {user.username}")
        
        return success_response(
            data=user.to_dict(),
            message="User registered successfully",
            status=201
        )
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        db.session.rollback()
        return error_response("Registration failed", 500)


@app.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    """Login and receive JWT token"""
    try:
        data = request.get_json()
        
        if not data or 'username' not in data or 'password' not in data:
            return error_response("Missing username or password", 400)
        
        user = User.query.filter_by(username=data['username']).first()
        
        if not user or not user.check_password(data['password']):
            return error_response("Invalid username or password", 401)
        
        if not user.is_active:
            return error_response("Account is disabled", 403)
        
        # Create access token
        access_token = create_access_token(
            identity=user.id,
            additional_claims={'role': user.role}
        )
        
        log_audit(user.id, 'LOGIN', 'USER', user.id)
        
        logger.info(f"User logged in: {user.username}")
        
        return success_response(data={
            'access_token': access_token,
            'user': user.to_dict()
        })
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return error_response("Login failed", 500)


# ============================================================================
# API ENDPOINTS - PATIENTS
# ============================================================================

@app.route('/api/patients', methods=['POST'])
@jwt_required()
@limiter.limit("20 per hour")
def create_patient():
    """Create a new patient"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate required fields
        if 'patient_id' not in data or 'full_name' not in data:
            return error_response("Missing required fields: patient_id, full_name", 400)
        
        # Validate patient ID format
        if not validate_patient_id(data['patient_id']):
            return error_response("Invalid patient ID format. Must be 6-20 alphanumeric characters", 400)
        
        # Check if patient already exists
        if Patient.query.filter_by(patient_id=data['patient_id'].upper()).first():
            return error_response("Patient ID already exists", 400)
        
        # Create new patient
        patient = Patient(
            patient_id=data['patient_id'].upper(),
            full_name=data['full_name'],
            date_of_birth=datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date() if 'date_of_birth' in data else None,
            gender=data.get('gender'),
            phone=data.get('phone'),
            email=data.get('email')
        )
        
        if 'address' in data:
            patient.set_address(data['address'])
        
        db.session.add(patient)
        db.session.commit()
        
        log_audit(current_user_id, 'CREATE', 'PATIENT', patient.id)
        logger.info(f"New patient created: {patient.patient_id}")
        
        return success_response(
            data=patient.to_dict(include_sensitive=True),
            message="Patient created successfully",
            status=201
        )
    except Exception as e:
        logger.error(f"Patient creation error: {str(e)}")
        db.session.rollback()
        return error_response("Failed to create patient", 500)


@app.route('/api/patients/<patient_id>', methods=['GET'])
@jwt_required()
def get_patient(patient_id):
    """Get patient details"""
    try:
        current_user_id = get_jwt_identity()
        
        patient = Patient.query.filter_by(patient_id=patient_id.upper()).first()
        
        if not patient:
            return error_response("Patient not found", 404)
        
        log_audit(current_user_id, 'VIEW', 'PATIENT', patient.id)
        
        return success_response(data=patient.to_dict(include_sensitive=True))
    except Exception as e:
        logger.error(f"Error retrieving patient: {str(e)}")
        return error_response("Failed to retrieve patient", 500)


@app.route('/api/patients', methods=['GET'])
@jwt_required()
def list_patients():
    """List all patients (with pagination)"""
    try:
        current_user_id = get_jwt_identity()
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '')
        
        query = Patient.query
        
        if search:
            query = query.filter(
                db.or_(
                    Patient.patient_id.ilike(f'%{search}%'),
                    Patient.full_name.ilike(f'%{search}%')
                )
            )
        
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        return success_response(data={
            'patients': [p.to_dict(include_sensitive=False) for p in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        })
    except Exception as e:
        logger.error(f"Error listing patients: {str(e)}")
        return error_response("Failed to list patients", 500)


# ============================================================================
# API ENDPOINTS - MEDICAL RECORDS
# ============================================================================

@app.route('/api/records/transcribe', methods=['POST'])
@jwt_required()
@limiter.limit("30 per hour")
def transcribe_recording():
    """Transcribe and process an audio recording"""
    try:
        current_user_id = get_jwt_identity()
        
        # Check if audio file is present
        if 'audio' not in request.files:
            return error_response("No audio file provided", 400)
        
        audio_file = request.files['audio']
        
        if audio_file.filename == '':
            return error_response("No audio file selected", 400)
        
        # Get additional parameters
        patient_id = request.form.get('patient_id')
        source_language = request.form.get('source_language', 'auto')
        
        if not patient_id:
            return error_response("Patient ID is required", 400)
        
        # Validate patient exists
        patient = Patient.query.filter_by(patient_id=patient_id.upper()).first()
        if not patient:
            return error_response("Patient not found", 404)
        
        # Read audio data
        audio_data = audio_file.read()
        
        # Save audio file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"recording_{patient_id}_{timestamp}.wav"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(filepath, 'wb') as f:
            f.write(audio_data)
        
        # Initialize Gemini
        model = initialize_gemini()
        
        # Transcribe
        logger.info(f"Transcribing audio for patient {patient_id}")
        transcript = transcribe_audio(model, audio_data, source_language)
        
        # Translate if needed
        logger.info(f"Translating transcript for patient {patient_id}")
        translation = translate_text(model, transcript)
        
        # Generate summary
        logger.info(f"Generating medical summary for patient {patient_id}")
        summary = generate_medical_summary(model, translation)
        
        # Create medical record
        record = MedicalRecord(
            patient_id=patient.id,
            doctor_id=current_user_id,
            recording_filename=filename,
            source_language=source_language,
            recording_duration=request.form.get('duration', type=int)
        )
        
        record.set_transcript(transcript)
        record.set_translation(translation)
        record.set_summary(summary)
        
        db.session.add(record)
        db.session.commit()
        
        log_audit(current_user_id, 'CREATE', 'RECORD', record.id, 
                 f"Created record for patient {patient_id}")
        
        logger.info(f"Medical record created: ID {record.id} for patient {patient_id}")
        
        return success_response(
            data=record.to_dict(include_sensitive=True),
            message="Recording processed successfully",
            status=201
        )
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        db.session.rollback()
        return error_response("Failed to process recording", 500)


@app.route('/api/records/patient/<patient_id>', methods=['GET'])
@jwt_required()
def get_patient_records(patient_id):
    """Get all records for a specific patient"""
    try:
        current_user_id = get_jwt_identity()
        
        # Find patient
        patient = Patient.query.filter_by(patient_id=patient_id.upper()).first()
        if not patient:
            return error_response("Patient not found", 404)
        
        # Get records
        records = MedicalRecord.query.filter_by(patient_id=patient.id)\
            .order_by(MedicalRecord.created_at.desc())\
            .all()
        
        log_audit(current_user_id, 'VIEW', 'RECORD', None, 
                 f"Viewed records for patient {patient_id}")
        
        return success_response(data={
            'patient': patient.to_dict(include_sensitive=False),
            'records': [r.to_dict(include_sensitive=True) for r in records]
        })
    except Exception as e:
        logger.error(f"Error retrieving patient records: {str(e)}")
        return error_response("Failed to retrieve records", 500)


@app.route('/api/records/<int:record_id>', methods=['GET'])
@jwt_required()
def get_record(record_id):
    """Get a specific medical record"""
    try:
        current_user_id = get_jwt_identity()
        
        record = MedicalRecord.query.get(record_id)
        if not record:
            return error_response("Record not found", 404)
        
        log_audit(current_user_id, 'VIEW', 'RECORD', record_id)
        
        return success_response(data=record.to_dict(include_sensitive=True))
    except Exception as e:
        logger.error(f"Error retrieving record: {str(e)}")
        return error_response("Failed to retrieve record", 500)


@app.route('/api/records/<int:record_id>/audio', methods=['GET'])
@jwt_required()
def get_recording_file(record_id):
    """Download the audio recording file"""
    try:
        current_user_id = get_jwt_identity()
        
        record = MedicalRecord.query.get(record_id)
        if not record:
            return error_response("Record not found", 404)
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], record.recording_filename)
        
        if not os.path.exists(filepath):
            return error_response("Recording file not found", 404)
        
        log_audit(current_user_id, 'DOWNLOAD', 'RECORD', record_id, 
                 "Downloaded audio file")
        
        return send_file(filepath, mimetype='audio/wav', as_attachment=True)
    except Exception as e:
        logger.error(f"Error serving recording: {str(e)}")
        return error_response("Failed to retrieve recording", 500)


# ============================================================================
# API ENDPOINTS - AUDIT LOGS
# ============================================================================

@app.route('/api/audit/logs', methods=['GET'])
@jwt_required()
def get_audit_logs():
    """Get audit logs (admin only or own logs)"""
    try:
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        
        query = AuditLog.query
        
        # Non-admin users can only see their own logs
        if current_user.role != 'admin':
            query = query.filter_by(user_id=current_user_id)
        
        pagination = query.order_by(AuditLog.timestamp.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)
        
        return success_response(data={
            'logs': [log.to_dict() for log in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        })
    except Exception as e:
        logger.error(f"Error retrieving audit logs: {str(e)}")
        return error_response("Failed to retrieve audit logs", 500)


# ============================================================================
# HEALTH CHECK & INFO
# ============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return success_response(data={
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '2.0.0'
    })


@app.route('/api/info', methods=['GET'])
def app_info():
    """Application information"""
    return success_response(data={
        'name': 'Medical Transcription System',
        'version': '2.0.0',
        'max_recording_duration': app.config['MAX_RECORDING_DURATION'],
        'max_file_size': app.config['MAX_CONTENT_LENGTH']
    })


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return error_response("Resource not found", 404)


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    db.session.rollback()
    return error_response("Internal server error", 500)


@app.errorhandler(413)
def request_entity_too_large(error):
    return error_response("File too large", 413)


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_database():
    """Initialize the database"""
    with app.app_context():
        db.create_all()
        logger.info("Database tables created successfully")
        
        # Create default admin user if it doesn't exist
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@medical.com',
                full_name='System Administrator',
                role='admin'
            )
            admin.set_password('admin123')  # Change this in production!
            db.session.add(admin)
            db.session.commit()
            logger.info("Default admin user created")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_database()
    app.run(debug=True, host='0.0.0.0', port=5000)