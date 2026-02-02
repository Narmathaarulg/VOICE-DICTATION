<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hospital Voice Recording System</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --primary: #1a73e8;
            --primary-light: #4285f4;
            --primary-dark: #0d47a1;
            --secondary: #34a853;
            --accent: #fbbc05;
            --danger: #ea4335;
            --dark: #202124;
            --light: #f8f9fa;
            --gray: #5f6368;
            --light-gray: #e8eaed;
            --card-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
            --transition: all 0.3s ease;
        }

        body {
            background-color: #f5f7fa;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: var(--dark);
            padding: 20px;
        }

        .app-container {
            max-width: 1400px;
            margin: 0 auto;
        }

        .app-header {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%);
            color: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 30px;
            box-shadow: var(--card-shadow);
        }

        .app-header h1 {
            font-weight: 700;
            margin-bottom: 5px;
        }

        .app-header p {
            opacity: 0.9;
            margin-bottom: 0;
        }

        .card {
            border-radius: 12px;
            border: none;
            box-shadow: var(--card-shadow);
            margin-bottom: 25px;
            transition: var(--transition);
        }

        .card:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.1);
        }

        .card-header {
            background: linear-gradient(to right, var(--primary), var(--primary-light));
            color: white;
            border-radius: 12px 12px 0 0 !important;
            padding: 15px 20px;
            border-bottom: none;
            font-weight: 600;
        }

        .card-body {
            padding: 20px;
        }

        .form-control, .form-select {
            border-radius: 8px;
            padding: 10px 15px;
            border: 2px solid var(--light-gray);
            transition: var(--transition);
        }

        .form-control:focus, .form-select:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 0.2rem rgba(26, 115, 232, 0.15);
        }

        .form-label {
            font-weight: 600;
            color: var(--gray);
            margin-bottom: 8px;
        }

        .btn {
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 600;
            transition: var(--transition);
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }

        .btn i {
            margin-right: 8px;
        }

        .btn-primary {
            background-color: var(--primary);
            border: none;
        }

        .btn-primary:hover {
            background-color: var(--primary-dark);
            transform: translateY(-2px);
        }

        .btn-danger {
            background-color: var(--danger);
            border: none;
        }

        .btn-success {
            background-color: var(--secondary);
            border: none;
        }

        .btn-warning {
            background-color: var(--accent);
            border: none;
        }

        .recording-btn {
            margin-right: 10px;
            min-width: 160px;
        }

        .transcript-box {
            background-color: #f8fafc;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            min-height: 150px;
            max-height: 400px;
            overflow-y: auto;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            white-space: pre-wrap;
            line-height: 1.5;
        }

        .recording-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background-color: var(--danger);
            animation: pulse 1.5s infinite;
            margin-right: 8px;
        }

        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.7; }
            50% { transform: scale(1.1); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.7; }
        }

        .nav-tabs {
            border-bottom: none;
        }

        .nav-tabs .nav-link {
            border-radius: 8px 8px 0 0;
            padding: 12px 20px;
            font-weight: 600;
            color: var(--gray);
            border: none;
            transition: var(--transition);
        }

        .nav-tabs .nav-link.active {
            background: linear-gradient(to bottom, var(--primary), var(--primary-light));
            color: white;
            border: none;
        }

        .tab-content {
            background-color: white;
            border-radius: 0 0 8px 8px;
            padding: 20px;
            border: 1px solid #e2e8f0;
            border-top: none;
        }

        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }

        .status-pending {
            background-color: #fef3c7;
            color: #d97706;
        }

        .status-in-progress {
            background-color: #dbeafe;
            color: #3b82f6;
        }

        .status-completed {
            background-color: #dcfce7;
            color: #16a34a;
        }

        .status-cancelled {
            background-color: #fee2e2;
            color: #dc2626;
        }

        .section-title {
            border-left: 4px solid var(--primary);
            padding-left: 12px;
            margin: 20px 0 15px;
            font-weight: 600;
        }

        .floating-alert {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1050;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            border-radius: 8px;
            opacity: 0;
            transform: translateY(-20px);
            transition: all 0.4s ease;
        }

        .floating-alert.show {
            opacity: 1;
            transform: translateY(0);
        }

        @media (max-width: 768px) {
            .recording-btn {
                width: 100%;
                margin-bottom: 10px;
            }
            
            .btn-group {
                flex-direction: column;
            }
        }
    </style>
</head>

<body>
    <div class="app-container">
        <div class="app-header">
            <div class="d-flex align-items-center">
                <i class="fas fa-hospital me-3" style="font-size: 2rem;"></i>
                <div>
                    <h1>Hospital Voice Recording System</h1>
                    <p>Secure medical documentation through voice recording and transcription</p>
                </div>
            </div>
        </div>

        <ul class="nav nav-tabs mb-4" id="mainTabs">
            <li class="nav-item">
                <a class="nav-link active" id="recording-tab" data-bs-toggle="tab" href="#recording">
                    <i class="fas fa-microphone-alt me-2"></i>Recording
                </a>
            </li>
            <li class="nav-item">
                <a class="nav-link" id="records-tab" data-bs-toggle="tab" href="#records">
                    <i class="fas fa-notes-medical me-2"></i>Patient Records
                </a>
            </li>
        </ul>

        <div class="tab-content">
            <!-- Recording Tab -->
            <div class="tab-pane fade show active" id="recording">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-microphone-alt me-2"></i>Record Doctor's Notes
                    </div>
                    <div class="card-body">
                        <div class="row mb-3">
                            <div class="col-md-6 mb-3">
                                <label class="form-label"><i class="fas fa-user-injured me-2"></i>Patient ID</label>
                                <input type="text" class="form-control" id="patient-id" placeholder="Enter patient ID">
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label"><i class="fas fa-user-md me-2"></i>Doctor ID</label>
                                <input type="text" class="form-control" id="doctor-id" placeholder="Enter doctor ID">
                            </div>
                        </div>

                        <div class="row mb-3">
                            <div class="col-md-6 mb-3">
                                <label class="form-label"><i class="fas fa-language me-2"></i>Source Language</label>
                                <select class="form-select" id="source-language">
                                    <option value="auto">Auto Detect</option>
                                    <option value="English">English</option>
                                    <option value="Spanish">Spanish</option>
                                    <option value="French">French</option>
                                    <option value="Chinese">Chinese</option>
                                    <option value="Arabic">Arabic</option>
                                    <option value="Hindi">Hindi</option>
                                    <option value="Japanese">Japanese</option>
                                    <option value="German">German</option>
                                    <option value="Portuguese">Portuguese</option>
                                    <option value="Russian">Russian</option>
                                </select>
                            </div>
                            <div class="col-md-6 mb-3">
                                <label class="form-label"><i class="fas fa-sliders-h me-2"></i>Recording Mode</label>
                                <div class="d-flex gap-3">
                                    <div class="form-check border rounded p-3 flex-grow-1">
                                        <input class="form-check-input" type="radio" name="recording-mode" id="mode-control"
                                            value="control" checked>
                                        <label class="form-check-label fw-medium" for="mode-control">
                                            <i class="fas fa-play-pause me-2"></i>Start/Stop Control
                                        </label>
                                    </div>
                                    <div class="form-check border rounded p-3 flex-grow-1">
                                        <input class="form-check-input" type="radio" name="recording-mode" id="mode-fixed"
                                            value="fixed">
                                        <label class="form-check-label fw-medium" for="mode-fixed">
                                            <i class="fas fa-hourglass-half me-2"></i>Fixed Duration
                                        </label>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div id="fixed-duration-controls" style="display: none;">
                            <div class="mb-3">
                                <label class="form-label"><i class="fas fa-clock me-2"></i>Recording Duration (seconds)</label>
                                <input type="range" class="form-range" id="duration" min="5" max="60" value="10">
                                <div class="d-flex justify-content-between mt-1">
                                    <small>5s</small>
                                    <strong>Selected: <span id="duration-value">10</span> seconds</strong>
                                    <small>60s</small>
                                </div>
                            </div>
                            <button id="record-fixed" class="btn btn-primary recording-btn">
                                <i class="fas fa-microphone me-2"></i>Record (Fixed Duration)
                            </button>
                        </div>

                        <div id="control-mode-controls">
                            <div class="d-flex flex-wrap align-items-center mb-3">
                                <button id="start-recording" class="btn btn-danger recording-btn">
                                    <i class="fas fa-circle me-2"></i>Start Recording
                                </button>
                                <button id="stop-recording" class="btn btn-secondary recording-btn" disabled>
                                    <i class="fas fa-stop me-2"></i>Stop Recording
                                </button>
                                <div id="recording-feedback" class="ms-3 p-2 bg-light rounded">
                                    <i class="fas fa-check-circle text-success me-2"></i>Ready to record
                                </div>
                            </div>
                        </div>

                        <div id="recording-results" style="display: none;">
                            <hr class="my-3">
                            <h3 class="section-title"><i class="fas fa-file-medical me-2"></i>Recording Results</h3>

                            <div class="d-flex flex-wrap justify-content-between gap-2 mb-3">
                                <button id="cancel-recording" class="btn btn-warning">
                                    <i class="fas fa-times me-2"></i>Cancel Recording
                                </button>
                                <button id="save-recording" class="btn btn-success">
                                    <i class="fas fa-save me-2"></i>Save to Patient Records
                                </button>
                            </div>

                            <ul class="nav nav-tabs" id="results-tabs">
                                <li class="nav-item">
                                    <a class="nav-link active" data-bs-toggle="tab" href="#original-tab">
                                        <i class="fas fa-comment-medical me-2"></i>Original
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#english-tab">
                                        <i class="fas fa-globe me-2"></i>English
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#summary-tab">
                                        <i class="fas fa-file-medical me-2"></i>Summary
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#audio-tab">
                                        <i class="fas fa-music me-2"></i>Audio
                                    </a>
                                </li>
                            </ul>

                            <div class="tab-content p-3 border border-top-0 rounded-bottom">
                                <div class="tab-pane fade show active" id="original-tab">
                                    <h4 class="d-flex align-items-center gap-2 mb-2">
                                        <i class="fas fa-language text-primary"></i>Original Language Transcript
                                    </h4>
                                    <div class="transcript-box" id="original-transcript"></div>
                                </div>
                                <div class="tab-pane fade" id="english-tab">
                                    <h4 class="d-flex align-items-center gap-2 mb-2">
                                        <i class="fas fa-globe-americas text-primary"></i>English Translation
                                    </h4>
                                    <div class="transcript-box" id="english-transcript"></div>
                                </div>
                                <div class="tab-pane fade" id="summary-tab">
                                    <div class="row">
                                        <div class="col-md-6 mb-3">
                                            <label class="form-label"><i class="fas fa-stethoscope me-2"></i>Medical Condition</label>
                                            <textarea class="form-control" id="medical-condition" rows="4"></textarea>
                                        </div>
                                        <div class="col-md-6 mb-3">
                                            <label class="form-label"><i class="fas fa-prescription-bottle-medical me-2"></i>Treatment Plan</label>
                                            <textarea class="form-control" id="treatment-plan" rows="4"></textarea>
                                        </div>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label"><i class="fas fa-calendar-check me-2"></i>Follow-up Date</label>
                                        <input type="text" class="form-control" id="followup-date">
                                    </div>
                                </div>
                                <div class="tab-pane fade" id="audio-tab">
                                    <h4 class="d-flex align-items-center gap-2 mb-2">
                                        <i class="fas fa-wave-square text-primary"></i>Audio Recording
                                    </h4>
                                    <audio controls class="w-100" id="audio-player"></audio>
                                    <div class="mt-2 text-muted small" id="audio-file-info"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Patient Records Tab -->
            <div class="tab-pane fade" id="records">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-notes-medical me-2"></i>Patient Records
                    </div>
                    <div class="card-body">
                        <div class="row mb-3">
                            <div class="col-md-9 mb-3">
                                <label class="form-label"><i class="fas fa-search me-2"></i>Enter Patient ID</label>
                                <input type="text" class="form-control" id="patient-search" placeholder="Search by patient ID">
                            </div>
                            <div class="col-md-3 d-flex align-items-end">
                                <button id="search-patient" class="btn btn-primary w-100">
                                    <i class="fas fa-search me-2"></i>Search
                                </button>
                            </div>
                        </div>

                        <div id="patient-details" style="display: none;">
                            <div class="alert alert-success d-flex align-items-center" id="patient-found-message">
                                <i class="fas fa-check-circle me-2"></i>
                                <span></span>
                            </div>

                            <h3 class="section-title"><i class="fas fa-user-injured me-2"></i>Patient Records</h3>
                            <div class="table-responsive mb-3">
                                <table class="table table-striped">
                                    <thead>
                                        <tr>
                                            <th>Record #</th>
                                            <th>Date/Time</th>
                                            <th>Doctor ID</th>
                                            <th>Medical Condition</th>
                                            <th>Follow-up</th>
                                        </tr>
                                    </thead>
                                    <tbody id="records-table"></tbody>
                                </table>
                            </div>

                            <div class="mb-3">
                                <label class="form-label"><i class="fas fa-file-medical me-2"></i>Select record to view details:</label>
                                <select class="form-select" id="record-select">
                                    <option value="">Select a record</option>
                                </select>
                            </div>

                            <div id="record-details" style="display: none;">
                                <h3 class="section-title"><i class="fas fa-file-medical-alt me-2"></i>Record Details</h3>

                                <ul class="nav nav-tabs" id="record-tabs">
                                    <li class="nav-item">
                                        <a class="nav-link active" data-bs-toggle="tab" href="#record-overview">
                                            <i class="fas fa-file-alt me-2"></i>Overview
                                        </a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" data-bs-toggle="tab" href="#record-tests">
                                            <i class="fas fa-vial me-2"></i>Tests
                                        </a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" data-bs-toggle="tab" href="#record-audio">
                                            <i class="fas fa-headphones me-2"></i>Audio
                                        </a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" data-bs-toggle="tab" href="#record-raw">
                                            <i class="fas fa-code me-2"></i>Raw Data
                                        </a>
                                    </li>
                                </ul>

                                <div class="tab-content p-3 border border-top-0 rounded-bottom">
                                    <div class="tab-pane fade show active" id="record-overview">
                                        <div class="row">
                                            <div class="col-md-6">
                                                <div class="mb-3">
                                                    <label class="form-label"><i class="fas fa-user-md me-2"></i>Doctor ID</label>
                                                    <div class="form-control-plaintext" id="record-doctor-id"></div>
                                                </div>
                                                <div class="mb-3">
                                                    <label class="form-label"><i class="fas fa-calendar-alt me-2"></i>Date/Time</label>
                                                    <div class="form-control-plaintext" id="record-timestamp"></div>
                                                </div>
                                                <div class="mb-3">
                                                    <label class="form-label"><i class="fas fa-stethoscope me-2"></i>Medical Condition</label>
                                                    <div class="form-control-plaintext" id="record-condition"></div>
                                                </div>
                                            </div>
                                            <div class="col-md-6">
                                                <div class="mb-3">
                                                    <label class="form-label"><i class="fas fa-prescription-bottle-alt me-2"></i>Treatment Plan</label>
                                                    <div class="form-control-plaintext" id="record-treatment"></div>
                                                </div>
                                                <div class="mb-3">
                                                    <label class="form-label"><i class="fas fa-calendar-check me-2"></i>Follow-up Date</label>
                                                    <div class="form-control-plaintext" id="record-followup"></div>
                                                </div>
                                            </div>
                                        </div>

                                        <div class="row mt-3">
                                            <div class="col-md-6">
                                                <h4 class="d-flex align-items-center gap-2 mb-2">
                                                    <i class="fas fa-language text-primary"></i>Original Language
                                                </h4>
                                                <div class="transcript-box" id="record-original-transcript"></div>
                                            </div>
                                            <div class="col-md-6">
                                                <h4 class="d-flex align-items-center gap-2 mb-2">
                                                    <i class="fas fa-globe-americas text-primary"></i>English Translation
                                                </h4>
                                                <div class="transcript-box" id="record-english-transcript"></div>
                                            </div>
                                        </div>
                                    </div>

                                    <div class="tab-pane fade" id="record-tests">
                                        <h4 class="d-flex align-items-center gap-2 mb-2">
                                            <i class="fas fa-vial text-primary"></i>Current Tests
                                        </h4>
                                        <div id="record-tests-list" class="mb-3"></div>

                                        <h4 class="d-flex align-items-center gap-2 mb-2">
                                            <i class="fas fa-tasks text-primary"></i>Manage Tests
                                        </h4>
                                        <div class="row">
                                            <div class="col-md-5">
                                                <label class="form-label"><i class="fas fa-vial me-2"></i>Select Test</label>
                                                <select class="form-select" id="record-test-select">
                                                    <option value="add-new">Add new test</option>
                                                </select>
                                                <input type="text" class="form-control mt-2" id="record-new-test"
                                                    style="display: none;" placeholder="Enter new test name">
                                            </div>
                                            <div class="col-md-5">
                                                <label class="form-label"><i class="fas fa-tasks me-2"></i>Status</label>
                                                <select class="form-select" id="record-test-status">
                                                    <option value="Pending">Pending</option>
                                                    <option value="In Progress">In Progress</option>
                                                    <option value="Completed">Completed</option>
                                                    <option value="Cancelled">Cancelled</option>
                                                </select>
                                            </div>
                                            <div class="col-md-2 d-flex align-items-end">
                                                <button id="record-update-test" class="btn btn-primary w-100">
                                                    <i class="fas fa-sync me-2"></i>Update
                                                </button>
                                            </div>
                                        </div>
                                    </div>

                                    <div class="tab-pane fade" id="record-audio">
                                        <h4 class="d-flex align-items-center gap-2 mb-2">
                                            <i class="fas fa-wave-square text-primary"></i>Audio Recording
                                        </h4>
                                        <audio controls class="w-100" id="record-audio-player"></audio>
                                        <div class="mt-2 text-muted small" id="record-audio-file-info"></div>
                                    </div>

                                    <div class="tab-pane fade" id="record-raw">
                                        <h4 class="d-flex align-items-center gap-2 mb-2">
                                            <i class="fas fa-database text-primary"></i>Raw Record Data
                                        </h4>
                                        <div class="transcript-box" id="record-raw-data"></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <h3 class="section-title"><i class="fas fa-database me-2"></i>Database Summary</h3>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <div class="card text-center h-100">
                                    <div class="card-body">
                                        <h5 class="card-title"><i class="fas fa-users me-2"></i>Total Patients</h5>
                                        <p class="card-text fs-3" id="total-patients">0</p>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="card text-center h-100">
                                    <div class="card-body">
                                        <h5 class="card-title"><i class="fas fa-file-medical me-2"></i>Total Records</h5>
                                        <p class="card-text fs-3" id="total-records">0</p>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="card h-100">
                                    <div class="card-body">
                                        <h5 class="card-title text-center"><i class="fas fa-history me-2"></i>Quick Patient Select</h5>
                                        <select class="form-select mt-3" id="quick-patient-select">
                                            <option value="">Select a patient</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Floating Alert -->
        <div class="floating-alert alert alert-success" role="alert" id="save-alert">
            <i class="fas fa-check-circle me-2"></i>
            <span>Recording saved successfully!</span>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Global state
        let mediaRecorder;
        let audioChunks = [];
        let currentRecording = null;
        let currentPatientRecords = [];

        // DOM elements
        const startBtn = document.getElementById('start-recording');
        const stopBtn = document.getElementById('stop-recording');
        const recordFixedBtn = document.getElementById('record-fixed');
        const recordingFeedback = document.getElementById('recording-feedback');
        const recordingResults = document.getElementById('recording-results');
        const cancelRecordingBtn = document.getElementById('cancel-recording');
        const saveRecordingBtn = document.getElementById('save-recording');
        const saveAlert = document.getElementById('save-alert');

        // Initialize
        document.addEventListener('DOMContentLoaded', function () {
            // Load database stats
            updateDatabaseStats();

            // Setup recording mode toggle
            document.querySelectorAll('input[name="recording-mode"]').forEach(radio => {
                radio.addEventListener('change', function () {
                    if (this.value === 'fixed') {
                        document.getElementById('fixed-duration-controls').style.display = 'block';
                        document.getElementById('control-mode-controls').style.display = 'none';
                    } else {
                        document.getElementById('fixed-duration-controls').style.display = 'none';
                        document.getElementById('control-mode-controls').style.display = 'block';
                    }
                });
            });

            // Duration slider
            const durationSlider = document.getElementById('duration');
            const durationValue = document.getElementById('duration-value');
            durationSlider.addEventListener('input', function () {
                durationValue.textContent = this.value;
            });

            // Start recording (control mode)
            startBtn.addEventListener('click', async function () {
                const patientId = document.getElementById('patient-id').value;
                const doctorId = document.getElementById('doctor-id').value;

                if (!patientId || !doctorId) {
                    showAlert('Please enter both Patient ID and Doctor ID', 'danger');
                    return;
                }

                try {
                    const response = await fetch('/api/start_recording', {
                        method: 'POST'
                    });

                    const data = await response.json();
                    if (data.success) {
                        startBtn.disabled = true;
                        stopBtn.disabled = false;
                        recordingFeedback.innerHTML = `
                            <span class="recording-indicator"></span> Recording...
                        `;
                    } else {
                        alert('Failed to start recording: ' + data.message);
                    }
                } catch (error) {
                    console.error('Error starting recording:', error);
                    alert('Failed to start recording');
                }
            });

            // Stop recording (control mode)
            stopBtn.addEventListener('click', async function () {
                try {
                    const response = await fetch('/api/stop_recording', {
                        method: 'POST'
                    });

                    const data = await response.json();
                    if (data.success) {
                        startBtn.disabled = false;
                        stopBtn.disabled = true;
                        recordingFeedback.innerHTML = '<i class="fas fa-check-circle text-success me-2"></i> Ready to record';

                        // Process the recording
                        currentRecording = {recording_file: data.recording_file};
                        await processRecording(data.recording_file);
                    } else {
                        alert('Failed to stop recording: ' + data.message);
                    }
                } catch (error) {
                    console.error('Error stopping recording:', error);
                    alert('Failed to stop recording');
                }
            });

            // Record fixed duration
            recordFixedBtn.addEventListener('click', async function () {
                const patientId = document.getElementById('patient-id').value;
                const doctorId = document.getElementById('doctor-id').value;
                const duration = parseInt(document.getElementById('duration').value);

                if (!patientId || !doctorId) {
                    showAlert('Please enter both Patient ID and Doctor ID', 'danger');
                    return;
                }

                try {
                    const originalText = recordFixedBtn.innerHTML;
                    recordFixedBtn.disabled = true;
                    recordFixedBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>Recording (${duration}s)...`;

                    const response = await fetch('/api/record_fixed_duration', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            patient_id: patientId,
                            doctor_id: doctorId,
                            duration: duration,
                            source_language: document.getElementById('source-language').value
                        })
                    });

                    const data = await response.json();

                    if (data.success) {
                        displayRecordingResults(data);
                        recordingResults.style.display = 'block';
                    } else {
                        alert('Failed to process recording: ' + data.message);
                    }

                    recordFixedBtn.disabled = false;
                    recordFixedBtn.innerHTML = originalText;
                } catch (error) {
                    console.error('Error recording:', error);
                    alert('Failed to start recording');
                    recordFixedBtn.disabled = false;
                    recordFixedBtn.innerHTML = '<i class="fas fa-microphone me-2"></i>Record (Fixed Duration)';
                }
            });

            // Cancel recording
            cancelRecordingBtn.addEventListener('click', function () {
                if (confirm('Are you sure you want to cancel this recording?')) {
                    recordingResults.style.display = 'none';
                    startBtn.disabled = false;
                    stopBtn.disabled = true;
                    recordingFeedback.innerHTML = '<i class="fas fa-check-circle text-success me-2"></i> Ready to record';
                    currentRecording = null;
                }
            });

            // Save recording - UPDATED
            saveRecordingBtn.addEventListener('click', async function () {
                const patientId = document.getElementById('patient-id').value;
                const doctorId = document.getElementById('doctor-id').value;
                
                if (!patientId || !doctorId) {
                    showAlert('Patient ID and Doctor ID required!', 'danger');
                    return;
                }
                
                if (!currentRecording) {
                    showAlert('No recording data available!', 'danger');
                    return;
                }
                
                const recordData = {
                    patient_id: patientId,
                    doctor_id: doctorId,
                    recording_file: currentRecording.recording_file || '',
                    transcript: document.getElementById('original-transcript').textContent,
                    translation: document.getElementById('english-transcript').textContent,
                    summary_data: {
                        medical_condition: document.getElementById('medical-condition').value,
                        treatment_plan: document.getElementById('treatment-plan').value,
                        followup_date: document.getElementById('followup-date').value
                    }
                };
                
                try {
                    saveRecordingBtn.disabled = true;
                    saveRecordingBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Saving...';
                    
                    const response = await fetch('/save', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(recordData)
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        showAlert('Recording saved successfully to patient records!', 'success');
                        recordingResults.style.display = 'none';
                        currentRecording = null;
                        
                        // Clear input fields
                        document.getElementById('patient-id').value = '';
                        document.getElementById('doctor-id').value = '';
                        
                        // Update database stats
                        updateDatabaseStats();
                    } else {
                        showAlert('Failed to save: ' + (data.error || 'Unknown error'), 'danger');
                    }
                } catch (error) {
                    console.error('Error saving record:', error);
                    showAlert('Failed to save recording. Please try again.', 'danger');
                } finally {
                    saveRecordingBtn.disabled = false;
                    saveRecordingBtn.innerHTML = '<i class="fas fa-save me-2"></i>Save to Patient Records';
                }
            });

            // Patient search
            document.getElementById('search-patient').addEventListener('click', searchPatient);
            document.getElementById('quick-patient-select').addEventListener('change', function () {
                if (this.value) {
                    document.getElementById('patient-search').value = this.value;
                    searchPatient();
                }
            });
        });

        async function processRecording(recordingFile) {
            const patientId = document.getElementById('patient-id').value;
            const doctorId = document.getElementById('doctor-id').value;
            const language = document.getElementById('source-language').value;

            const response = await fetch('/api/process_recording', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    recording_file: recordingFile,
                    patient_id: patientId,
                    doctor_id: doctorId,
                    source_language: language
                })
            });

            const data = await response.json();

            if (data.success) {
                displayRecordingResults(data);
                recordingResults.style.display = 'block';
            } else {
                alert('Failed to process recording: ' + data.message);
            }
        }

        function displayRecordingResults(data) {
            // Store current recording data globally
            currentRecording = data;
            
            document.getElementById('original-transcript').textContent = data.original_transcript || 'No transcript available';
            document.getElementById('english-transcript').textContent = data.english_transcript || 'No translation available';

            document.getElementById('medical-condition').value = data.summary_data?.medical_condition || '';
            document.getElementById('treatment-plan').value = data.summary_data?.treatment_plan || '';
            document.getElementById('followup-date').value = data.summary_data?.followup_date || '';

            const audioPlayer = document.getElementById('audio-player');
            const audioFileName = data.recording_file.split('/').pop();
            audioPlayer.src = `/recordings/${audioFileName}`;
            document.getElementById('audio-file-info').textContent = `File: ${audioFileName}`;
            
            // Show results section
            recordingResults.style.display = 'block';
        }

        async function searchPatient() {
            const patientId = document.getElementById('patient-search').value;
            if (!patientId) return;

            try {
                const response = await fetch(`/api/patients/${patientId}`);
                const data = await response.json();

                if (data.success && data.records && data.records.length > 0) {
                    currentPatientRecords = data.records;
                    document.getElementById('patient-details').style.display = 'block';
                    document.getElementById('patient-found-message').innerHTML = `
                        <i class="fas fa-check-circle me-2"></i>
                        <div>Found ${data.records.length} records for Patient ID: ${patientId}</div>
                    `;

                    // Populate records table
                    const tableBody = document.getElementById('records-table');
                    tableBody.innerHTML = '';

                    data.records.forEach((record, index) => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${index + 1}</td>
                            <td>${record.timestamp}</td>
                            <td>${record.doctor_id}</td>
                            <td>${record.medical_condition}</td>
                            <td>${record.followup_date}</td>
                        `;
                        tableBody.appendChild(row);
                    });

                    // Populate record select dropdown
                    const recordSelect = document.getElementById('record-select');
                    recordSelect.innerHTML = '<option value="">Select a record</option>';

                    data.records.forEach((record, index) => {
                        const option = document.createElement('option');
                        option.value = index;
                        option.textContent = `Record ${index + 1} - ${record.timestamp}`;
                        recordSelect.appendChild(option);
                    });

                    updateQuickPatientSelect();
                } else {
                    alert(`No records found for Patient ID: ${patientId}`);
                }
            } catch (error) {
                console.error('Error searching patient:', error);
                alert('Failed to search patient records');
            }
        }

        function updateQuickPatientSelect() {
            const quickSelect = document.getElementById('quick-patient-select');
            
            fetch('/api/patients')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        quickSelect.innerHTML = '<option value="">Select a patient</option>';
                        data.patients.forEach(patientId => {
                            const option = document.createElement('option');
                            option.value = patientId;
                            option.textContent = patientId;
                            quickSelect.appendChild(option);
                        });
                    }
                })
                .catch(error => console.error('Error loading patients:', error));
        }

        function updateDatabaseStats() {
            fetch('/api/patients')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('total-patients').textContent = data.stats.total_patients;
                        document.getElementById('total-records').textContent = data.stats.total_records;
                        updateQuickPatientSelect();
                    }
                })
                .catch(error => console.error('Error loading stats:', error));
        }

        // Record selection
        document.getElementById('record-select').addEventListener('change', function () {
            const index = parseInt(this.value);
            if (isNaN(index)) return;

            const record = currentPatientRecords[index];
            document.getElementById('record-details').style.display = 'block';

            // Update record details
            document.getElementById('record-doctor-id').textContent = record.doctor_id;
            document.getElementById('record-timestamp').textContent = record.timestamp;
            document.getElementById('record-condition').textContent = record.medical_condition;
            document.getElementById('record-treatment').textContent = record.treatment_plan;
            document.getElementById('record-followup').textContent = record.followup_date;

            document.getElementById('record-original-transcript').textContent = record.original_transcript || 'N/A';
            document.getElementById('record-english-transcript').textContent = record.english_transcript || 'N/A';

            // Update audio player
            const audioPlayer = document.getElementById('record-audio-player');
            if (record.recording_path) {
                audioPlayer.src = `/recordings/${record.recording_path.split('/').pop()}`;
                document.getElementById('record-audio-file-info').textContent = `File: ${record.recording_path.split('/').pop()}`;
            }

            // Update tests list
            const testsList = document.getElementById('record-tests-list');
            testsList.innerHTML = '';

            if (record.tests && Object.keys(record.tests).length > 0) {
                for (const [test, status] of Object.entries(record.tests)) {
                    const testItem = document.createElement('div');
                    testItem.className = 'mb-2 p-2 border rounded';
                    testItem.innerHTML = `<strong>${test}</strong>: <span class="status-badge ${getStatusClass(status)}">${status}</span>`;
                    testsList.appendChild(testItem);
                }
            } else {
                testsList.innerHTML = '<div class="text-muted">No tests recorded</div>';
            }

            // Update test dropdown
            const newTestInput = document.getElementById('record-new-test');
            const testUpdateBtn = document.getElementById('record-update-test');
            const oldTestSelect = document.getElementById('record-test-select');
            const newTestSelect = oldTestSelect.cloneNode(true);
            oldTestSelect.parentNode.replaceChild(newTestSelect, oldTestSelect);

            newTestSelect.innerHTML = '<option value="add-new">Add new test</option>';
            if (record.tests) {
                Object.keys(record.tests).forEach(test => {
                    const option = document.createElement('option');
                    option.value = test;
                    option.textContent = test;
                    newTestSelect.appendChild(option);
                });
            }
            newTestInput.style.display = 'none';

            newTestSelect.addEventListener('change', function () {
                if (this.value === 'add-new') {
                    newTestInput.style.display = 'block';
                } else {
                    newTestInput.style.display = 'none';
                }
            });

            // Replace update button to avoid duplicate handlers
            const newUpdateBtn = testUpdateBtn.cloneNode(true);
            testUpdateBtn.parentNode.replaceChild(newUpdateBtn, testUpdateBtn);

            newUpdateBtn.addEventListener('click', async function () {
                const patientId = document.getElementById('patient-search').value;
                const index = parseInt(document.getElementById('record-select').value);
                const testSelect = document.getElementById('record-test-select');
                const status = document.getElementById('record-test-status').value;

                let testName = testSelect.value;
                if (testName === 'add-new') {
                    testName = document.getElementById('record-new-test').value.trim();
                    if (!testName) return alert('Enter a test name');
                }

                try {
                    const response = await fetch('/api/update_test', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            patient_id: patientId,
                            record_index: index,
                            test_name: testName,
                            status: status
                        })
                    });

                    const data = await response.json();
                    if (data.success) {
                        showAlert('Test updated successfully!', 'success');
                        searchPatient(); // Refresh UI
                    } else {
                        alert('Failed to update: ' + data.message);
                    }
                } catch (err) {
                    console.error('Update error', err);
                    alert('Error updating test');
                }
            });

            // Update raw data
            document.getElementById('record-raw-data').textContent = JSON.stringify(record, null, 2);
        });

        function getStatusClass(status) {
            switch(status) {
                case 'Pending': return 'status-pending';
                case 'In Progress': return 'status-in-progress';
                case 'Completed': return 'status-completed';
                case 'Cancelled': return 'status-cancelled';
                default: return '';
            }
        }

        function showAlert(message, type) {
            const alert = document.getElementById('save-alert');
            alert.className = `floating-alert alert alert-${type} show`;
            alert.querySelector('span').textContent = message;
            
            setTimeout(() => {
                alert.classList.remove('show');
            }, 3000);
        }
    </script>
</body>
</html>