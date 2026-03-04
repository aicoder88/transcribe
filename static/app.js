// Global state
const jobs = new Map();
let pollInterval = null;
let appConfig = null;

// Configuration for memory management
const MAX_COMPLETED_JOBS = 50;  // Maximum number of completed jobs to keep in memory
const JOB_RETENTION_MS = 3600000;  // 1 hour - time to keep completed jobs in memory

// DOM Elements
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const jobsSection = document.getElementById('jobsSection');
const jobsContainer = document.getElementById('jobsContainer');
const modeCards = document.querySelectorAll('.mode-card');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    setupEventListeners();
});

async function loadConfig() {
    try {
        const response = await fetch('/config');
        if (response.ok) {
            appConfig = await response.json();
            updateModeCardsAvailability();
        }
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

function updateModeCardsAvailability() {
    if (!appConfig) return;

    modeCards.forEach(card => {
        const engine = card.dataset.engine;
        const engineConfig = appConfig.engines[engine];
        const badge = card.querySelector('.mode-badge');
        const radio = card.querySelector('input[type="radio"]');

        if (engineConfig) {
            if (engineConfig.available) {
                card.classList.remove('unavailable');
                radio.disabled = false;
                badge.textContent = 'Ready';
                badge.className = 'mode-badge badge-available';
            } else {
                card.classList.add('unavailable');
                radio.disabled = true;
                badge.textContent = 'API Key Required';
                badge.className = 'mode-badge badge-unavailable';

                // If this was selected, switch to whisper
                if (card.classList.contains('selected')) {
                    card.classList.remove('selected');
                    const whisperCard = document.querySelector('.mode-card[data-engine="whisper"]');
                    if (whisperCard) {
                        whisperCard.classList.add('selected');
                        whisperCard.querySelector('input[type="radio"]').checked = true;
                    }
                }
            }
        }
    });
}

function setupEventListeners() {
    // Click to upload
    uploadArea.addEventListener('click', () => {
        fileInput.click();
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });

    // Mode card selection
    modeCards.forEach(card => {
        card.addEventListener('click', (e) => {
            if (card.classList.contains('unavailable')) {
                e.preventDefault();
                return;
            }

            modeCards.forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            card.querySelector('input[type="radio"]').checked = true;
        });
    });
}

async function handleFiles(files) {
    if (files.length === 0) return;

    // Show jobs section
    jobsSection.style.display = 'block';

    // Upload each file
    for (const file of files) {
        await uploadFile(file);
    }

    // Start polling for updates
    startPolling();
}

async function uploadFile(file) {
    const languageSelect = document.getElementById('languageSelect');
    const selectedEngine = document.querySelector('input[name="engine"]:checked');
    const outputName = document.getElementById('outputName');

    // Check for partials first
    try {
        const checkRes = await fetch(`/check_partial?output_name=${encodeURIComponent(outputName.value.trim())}&filename=${encodeURIComponent(file.name)}`);
        if (checkRes.ok) {
            const checkData = await checkRes.json();
            if (checkData.found) {
                // Show inline prompt
                const tempId = 'temp-' + Date.now();
                createJobCard(tempId, file.name, languageSelect.value);
                const card = document.getElementById(`job-${tempId}`);
                card.innerHTML = `
                    <div style="padding: 1rem;">
                        <span class="job-title">${file.name}</span>
                        <div style="margin-top: 1rem; padding: 1rem; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px;">
                            <p style="margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.5rem;">
                                <span>⚡</span> Found previous partial work: ~${checkData.word_count} words.
                            </p>
                            <p style="margin-bottom: 1rem; font-size: 0.9em; color: var(--text-muted);">
                                Resume from ${Math.round(checkData.last_timestamp)}s or start fresh?
                            </p>
                            <div style="display: flex; gap: 1rem;">
                                <button id="btn-resume-${tempId}" class="btn btn-primary" style="flex: 1;">Resume</button>
                                <button id="btn-fresh-${tempId}" class="btn btn-secondary" style="flex: 1;">Start Fresh</button>
                            </div>
                        </div>
                    </div>
                `;
                await new Promise((resolve) => {
                    document.getElementById(`btn-resume-${tempId}`).addEventListener('click', () => {
                        card.remove();
                        const translateCheckbox = document.getElementById('translateCheckbox');
                        doUpload(file, languageSelect.value, selectedEngine ? selectedEngine.value : 'whisper', outputName.value.trim(), checkData.partial_json_path, translateCheckbox ? translateCheckbox.checked : true);
                        resolve();
                    });
                    document.getElementById(`btn-fresh-${tempId}`).addEventListener('click', () => {
                        card.remove();
                        const translateCheckbox = document.getElementById('translateCheckbox');
                        doUpload(file, languageSelect.value, selectedEngine ? selectedEngine.value : 'whisper', outputName.value.trim(), null, translateCheckbox ? translateCheckbox.checked : true);
                        resolve();
                    });
                });
                return; // actual upload is handled
            }
        }
    } catch (e) {
        console.error("Partial check failed", e);
    }

    const translateCheckbox = document.getElementById('translateCheckbox');
    await doUpload(file, languageSelect.value, selectedEngine ? selectedEngine.value : 'whisper', outputName.value.trim(), null, translateCheckbox ? translateCheckbox.checked : true);
}

async function doUpload(file, language, engine, outputName, resumePartialJson, translate) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('language', language);
    formData.append('engine', engine);
    formData.append('output_name', outputName);
    formData.append('translate', translate ? 'true' : 'false');
    if (resumePartialJson) {
        formData.append('resume_partial_json', resumePartialJson);
    }

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('Upload failed');
        }

        const data = await response.json();
        const jobId = data.job_id;

        // Create job card
        createJobCard(jobId, file.name, language);

        // Store job
        jobs.set(jobId, {
            filename: file.name,
            status: 'queued',
            autoDetect: language === 'auto'
        });

    } catch (error) {
        console.error('Upload error:', error);
        alert(`Failed to upload ${file.name}: ${error.message}`);
    }
}


function createJobCard(jobId, filename, language) {
    const card = document.createElement('div');
    card.className = 'glass-panel job-card';
    card.id = `job-${jobId}`;

    const isAutoDetect = language === 'auto';

    card.innerHTML = `
        <div class="job-header">
            <span class="job-title">${filename}</span>
            <div class="job-meta">
                ${isAutoDetect ? '<span class="detected-lang" id="lang-' + jobId + '">Detecting...</span>' : ''}
                <span class="status-badge status-queued">QUEUED</span>
            </div>
        </div>

        <div class="progress-wrapper">
            <div class="progress-fill"></div>
        </div>

        <div class="progress-detail">
            <span class="job-task">Waiting to start...</span>
            <span class="progress-percentage">1%</span>
        </div>

        <div class="output-path-info" style="display: none; margin-top: 0.75rem; padding: 0.5rem; background: rgba(255,255,255,0.03); border-radius: 6px; font-size: 0.8rem; color: var(--text-muted);">
            <strong>Output:</strong> <code class="output-path" style="user-select: all; color: var(--accent);"></code>
        </div>

        <div class="job-results" style="display: none;"></div>
        <div class="live-transcript" style="display: none; margin-top: 0.5rem; text-align: right;">
            <a href="#" target="_blank" class="live-link" style="color: var(--accent); text-decoration: none; font-size: 0.85rem;">📄 View live transcript →</a>
        </div>
    `;

    jobsContainer.insertBefore(card, jobsContainer.firstChild);
}

function updateJobCard(jobId, jobData) {
    const card = document.getElementById(`job-${jobId}`);
    if (!card) return;

    const statusEl = card.querySelector('.status-badge');
    const taskEl = card.querySelector('.job-task');
    const progressFill = card.querySelector('.progress-fill');
    const progressText = card.querySelector('.progress-percentage');
    const resultsEl = card.querySelector('.job-results');
    const outputPathInfo = card.querySelector('.output-path-info');
    const outputPath = card.querySelector('.output-path');
    const detectedLangEl = card.querySelector(`#lang-${jobId}`);

    // Update detected language if available
    if (detectedLangEl && jobData.detected_language_name) {
        detectedLangEl.textContent = jobData.detected_language_name;
        detectedLangEl.style.background = 'rgba(16, 185, 129, 0.15)';
        detectedLangEl.style.color = 'var(--success)';
    }

    // Show output path as soon as available (even during processing)
    if (jobData.output_folder && outputPathInfo && outputPath) {
        outputPathInfo.style.display = 'block';
        outputPath.textContent = jobData.output_folder;
    }

    // Update status
    statusEl.className = `status-badge status-${jobData.status}`;
    statusEl.textContent = jobData.status.toUpperCase();

    // Live transcript link
    const liveLinkContainer = card.querySelector('.live-transcript');
    const liveLink = card.querySelector('.live-link');
    if (jobData.status === 'processing' && jobData.partial_file_path) {
        liveLinkContainer.style.display = 'block';
        liveLink.href = `/partial/${jobId}`;
    } else {
        if (liveLinkContainer) liveLinkContainer.style.display = 'none';
    }

    // Update task
    taskEl.textContent = jobData.current_task || 'Processing...';

    // Update progress
    const progress = jobData.progress || 0;
    progressFill.style.width = `${progress}%`;

    // Show time estimate if available
    const timeEstimate = formatTime(jobData.estimated_remaining);
    if (timeEstimate && jobData.status === 'processing') {
        progressText.textContent = `${progress}% - ${timeEstimate}`;
    } else {
        progressText.textContent = `${progress}%`;
    }

    // Show results if completed
    if (jobData.status === 'completed' && jobData.transcription && jobData.translation) {
        resultsEl.style.display = 'block';
        resultsEl.className = 'results-container';

        const langInfo = jobData.detected_language_name
            ? ` (${jobData.detected_language_name})`
            : '';

        const showTranslation = jobData.translation && jobData.translation !== jobData.transcription && !jobData.translation.startsWith('[Deepgram');

        resultsEl.innerHTML = `
            <div class="result-block">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <h4 style="margin: 0;">Transcription${langInfo}</h4>
                    <button onclick="copyJobText(${jobData.id}, 'transcription', this)" class="btn btn-secondary" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;">📋 Copy</button>
                </div>
                <div class="result-content">${escapeHtml(jobData.transcription)}</div>
            </div>

            ${showTranslation ? `
            <div class="result-block">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <h4 style="margin: 0;">English Translation</h4>
                    <button onclick="copyJobText(${jobData.id}, 'translation', this)" class="btn btn-secondary" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;">📋 Copy</button>
                </div>
                <div class="result-content">${escapeHtml(jobData.translation)}</div>
            </div>
            ` : ''}

            <div class="action-bar" style="grid-column: span 2;">
                <div style="width: 100%; margin-bottom: 1rem; padding: 0.5rem; background: rgba(255,255,255,0.05); border-radius: 4px; font-size: 0.85rem; color: var(--text-muted); display: flex; justify-content: space-between; align-items: center;">
                    <div><strong>Saved locally to:</strong> <code style="user-select: all;">${escapeHtml(jobData.output_folder || 'outputs/')}</code></div>
                    <button onclick="openLocalFolder('${(jobData.files.transcription || '').replace(/'/g, "\\'")}')" class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; background: rgba(255,255,255,0.1);">
                        📁 Reveal in Finder
                    </button>
                </div>
                <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                    <a href="/download/${jobData.files.transcription}" class="btn btn-secondary" download>
                        Download Transcript
                    </a>
                    <a href="/download/${jobData.files.translation}" class="btn btn-secondary" download>
                        Download Translation
                    </a>
                    <a href="/download/${jobData.files.combined}" class="btn btn-primary" download>
                        Download All Combined
                    </a>
                </div>
            </div>
        `;
    }

    // Show error if failed
    if (jobData.status === 'error') {
        resultsEl.style.display = 'block';
        resultsEl.innerHTML = `
            <div class="glass-panel" style="padding: 1rem; border-color: var(--error); background: rgba(239, 68, 68, 0.1);">
                <h4 style="color: var(--error); margin-bottom: 0.5rem;">Processing Error</h4>
                <p style="color: #fca5a5;">${escapeHtml(jobData.error || 'Unknown error occurred')}</p>
            </div>
        `;
    }
}


function startPolling() {
    if (pollInterval) return;

    pollInterval = setInterval(async () => {
        let allComplete = true;

        for (const [jobId, job] of jobs.entries()) {
            if (job.status === 'completed' || job.status === 'error') {
                continue;
            }

            allComplete = false;

            try {
                const response = await fetch(`/status/${jobId}`);
                if (response.ok) {
                    const data = await response.json();
                    // Track completion time for cleanup
                    if ((data.status === 'completed' || data.status === 'error') && !job.completedAt) {
                        data.completedAt = Date.now();
                    }
                    jobs.set(jobId, { ...jobs.get(jobId), ...data });
                    updateJobCard(jobId, data);
                }
            } catch (error) {
                console.error(`Error polling job ${jobId}:`, error);
            }
        }

        // Clean up old completed jobs to prevent memory leak
        cleanupOldJobs();

        // Stop polling if all jobs are complete
        if (allComplete && jobs.size > 0) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }, 1000); // Poll every second
}

function cleanupOldJobs() {
    const now = Date.now();
    const completedJobs = [];

    // Collect completed/errored jobs with their completion times
    for (const [jobId, job] of jobs.entries()) {
        if ((job.status === 'completed' || job.status === 'error') && job.completedAt) {
            completedJobs.push({ jobId, completedAt: job.completedAt });
        }
    }

    // Sort by completion time (oldest first)
    completedJobs.sort((a, b) => a.completedAt - b.completedAt);

    // Remove jobs that are too old
    for (const { jobId, completedAt } of completedJobs) {
        if (now - completedAt > JOB_RETENTION_MS) {
            removeJob(jobId);
        }
    }

    // If we still have too many completed jobs, remove the oldest ones
    const remainingCompleted = completedJobs.filter(j => jobs.has(j.jobId));
    if (remainingCompleted.length > MAX_COMPLETED_JOBS) {
        const toRemove = remainingCompleted.slice(0, remainingCompleted.length - MAX_COMPLETED_JOBS);
        for (const { jobId } of toRemove) {
            removeJob(jobId);
        }
    }
}

function removeJob(jobId) {
    // Remove from Map
    jobs.delete(jobId);

    // Remove DOM element
    const card = document.getElementById(`job-${jobId}`);
    if (card) {
        card.remove();
    }

    // Hide jobs section if empty
    if (jobs.size === 0) {
        jobsSection.style.display = 'none';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(seconds) {
    if (!seconds || seconds <= 0) return '';
    if (seconds < 60) return `~${Math.ceil(seconds)}s remaining`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.ceil(seconds % 60);
    return `~${mins}m ${secs}s remaining`;
}

async function openLocalFolder(filepath) {
    if (!filepath) return;
    try {
        const response = await fetch('/open-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filepath })
        });
        if (!response.ok) {
            throw new Error('Failed to open folder');
        }
    } catch (e) {
        console.error(e);
        alert('Could not open folder on the server. Ensure the server has permission.');
    }
}

function copyJobText(jobId, type, btnEl) {
    const job = jobs.get(jobId);
    if (!job) return;
    const text = job[type];
    if (!text) return;

    navigator.clipboard.writeText(text).then(() => {
        const originalText = btnEl.innerHTML;
        btnEl.innerHTML = '✅ Copied!';
        setTimeout(() => { btnEl.innerHTML = originalText; }, 2000);
    }).catch(err => {
        console.error('Failed to copy', err);
        alert('Failed to copy to clipboard.');
    });
}
