#!/usr/bin/env python3
"""
PurriFlow Transcription Server - Audio transcription powered by purrify.ca
Supports local Whisper and Deepgram API
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from faster_whisper import WhisperModel
import threading
import time
import httpx
import subprocess
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='static')

# CORS configuration - restrict to specific origins
# Set CORS_ORIGINS environment variable to comma-separated list of allowed origins
# Default: localhost only for development
ALLOWED_ORIGINS_ENV = os.getenv("CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080")
if ALLOWED_ORIGINS_ENV == "*":
    CORS(app, resources={r"/*": {"origins": "*"}})
else:
    ALLOWED_ORIGINS = ALLOWED_ORIGINS_ENV.split(",")
    CORS(app, origins=ALLOWED_ORIGINS)

# Configuration
MODEL_PATH = "large-v3"
UPLOAD_FOLDER = Path("uploads")
OUTPUT_FOLDER = Path("outputs")
PARTIALS_FOLDER = Path("outputs/partials")
UPLOAD_FOLDER.mkdir(exist_ok=True)
PARTIALS_FOLDER.mkdir(parents=True, exist_ok=True)

# API Keys
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Valid input parameters
VALID_LANGUAGES = {'auto', 'en', 'fr', 'hr', 'es', 'de', 'it', 'pt', 'nl', 'pl', 'ru', 'ja', 'zh'}
VALID_ENGINES = {'whisper', 'deepgram', 'openai'}

# Global model instance (loaded once)
whisper_model = None
model_lock = threading.Lock()

# Job tracking
jobs = {}
job_counter = 0
job_lock = threading.Lock()


def update_job(job_id, **updates):
    """Thread-safe update of job data"""
    with job_lock:
        if job_id in jobs:
            jobs[job_id].update(updates)


def get_job(job_id):
    """Thread-safe retrieval of job data"""
    with job_lock:
        if job_id in jobs:
            return dict(jobs[job_id])
        return None


def get_job_value(job_id, key, default=None):
    """Thread-safe retrieval of a single job value"""
    with job_lock:
        if job_id in jobs:
            return jobs[job_id].get(key, default)
        return default


def load_whisper_model(model_name=None):
    """Load the Whisper model (called once at startup and when model changes)"""
    global whisper_model, MODEL_PATH
    
    with model_lock:
        if model_name is None:
            model_name = "large-v3"
            
        if whisper_model is not None and MODEL_PATH == model_name:
            return  # Model already loaded
            
        if whisper_model is not None:
            logger.info(f"Unloading current model: {MODEL_PATH}")
            del whisper_model
            whisper_model = None
            
        MODEL_PATH = model_name
        logger.info(f"Loading Whisper model: {MODEL_PATH}...")
        logger.info("This may take a moment...")

        # Apple Silicon M1 - use CPU with int8 for best quality and memory
        whisper_model = WhisperModel(
            MODEL_PATH,
            device="cpu",
            compute_type="int8",  # Best memory usage
            download_root="."
        )
        logger.info(f"Model {MODEL_PATH} loaded successfully!")


def update_job_progress(job_id, progress, current_task, audio_processed=None):
    """Update job progress and calculate estimated remaining time based on processing speed"""
    with job_lock:
        if job_id not in jobs:
            return

        jobs[job_id]["progress"] = int(progress)
        jobs[job_id]["current_task"] = current_task

        # Calculate time estimate based on actual processing speed
        audio_duration = jobs[job_id].get("audio_duration", 0)
        first_segment_time = jobs[job_id].get("first_segment_time")

        if audio_processed and audio_processed > 0 and first_segment_time:
            # Calculate how fast we're processing audio
            processing_elapsed = time.time() - first_segment_time
            processing_speed = audio_processed / processing_elapsed  # seconds of audio per second of real time

            if processing_speed > 0:
                # For non-English: transcribe (0-50%) + translate (50-100%)
                # For English: just transcribe (0-100%)
                is_translating = jobs[job_id].get("is_translating", False)
                source_lang = jobs[job_id].get("source_language", "fr")

                if source_lang == "en":
                    # English only: just transcription
                    remaining_audio = audio_duration - audio_processed
                    remaining_seconds = remaining_audio / processing_speed
                else:
                    if not is_translating:
                        # Still transcribing: remaining transcription + full translation pass
                        remaining_transcribe = audio_duration - audio_processed
                        remaining_seconds = (remaining_transcribe / processing_speed) + (audio_duration / processing_speed)
                    else:
                        # Translating: just remaining translation
                        remaining_audio = audio_duration - audio_processed
                        remaining_seconds = remaining_audio / processing_speed

                jobs[job_id]["estimated_remaining"] = max(0, int(remaining_seconds))


def transcribe_with_whisper(job_id, audio_path, filename, source_language, output_name, resume_from_timestamp=0.0, existing_text=None, translate=True, whisper_model_name="large-v3"):
    """Process audio file using local Whisper model"""
    try:
        update_job(job_id, status="processing", progress=2, current_task=f"Initializing Whisper ({whisper_model_name})...")
        
        # Ensure the requested model is loaded
        load_whisper_model(whisper_model_name)

        # Handle auto-detection
        auto_detect = source_language == "auto" or source_language is None
        whisper_lang = None if auto_detect else source_language

        lang_names = {"fr": "French", "en": "English", "hr": "Croatian", "es": "Spanish",
                      "de": "German", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
                      "pl": "Polish", "ru": "Russian", "ja": "Japanese", "zh": "Chinese"}

        if auto_detect:
            update_job(job_id, current_task="Detecting language...")
            lang_name = "Auto-detecting"
        else:
            lang_name = lang_names.get(source_language, source_language.upper())
            update_job(job_id, source_language=source_language)

        update_job(job_id, progress=3, current_task=f"Loading audio ({lang_name})...")
        
        # Build partial filename and path
        base_name = output_name if output_name else Path(filename).stem
        partial_txt_path = PARTIALS_FOLDER / f"{base_name}_{job_id}_transcription.partial.txt"
        partial_json_path = PARTIALS_FOLDER / f"{base_name}_{job_id}.partial.json"
        
        update_job(job_id, partial_file_path=str(partial_txt_path))
        
        # Resume trimming
        processing_audio_path = audio_path
        if resume_from_timestamp > 0:
            trimmed_path = UPLOAD_FOLDER / f"trimmed_{job_id}_{filename}"
            subprocess.run(['ffmpeg', '-i', str(audio_path), '-ss', str(resume_from_timestamp), str(trimmed_path), '-y'], check=True)
            processing_audio_path = str(trimmed_path)
            
        if not existing_text:
            # Initialize partial file and JSON
            with open(partial_txt_path, "w", encoding="utf-8") as f:
                f.write(f"=== {lang_name} Transcription ===\n")
                f.write(f"Model: Whisper\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Status: IN PROGRESS\n\n")
            with open(partial_json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "last_timestamp": 0.0,
                    "base_name": base_name,
                    "language": source_language,
                    "model_tag": "Whisper"
                }, f)
        else:
            # Pre-populate partial file with existing text if provided
            with open(partial_txt_path, "w", encoding="utf-8") as f:
                f.write(f"=== {lang_name} Transcription ===\n")
                f.write(f"Model: Whisper\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Status: IN PROGRESS (Resumed)\n\n")
                for text_line in existing_text:
                    f.write(text_line + "\n")
            with open(partial_json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "last_timestamp": resume_from_timestamp,
                    "base_name": base_name,
                    "language": source_language,
                    "model_tag": "Whisper"
                }, f)

        segments_transcribe, info = whisper_model.transcribe(
            processing_audio_path,
            language=whisper_lang,  # None for auto-detection
            task="transcribe",
            beam_size=5,
            best_of=5,
            temperature=0.0,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            # Anti-hallucination settings
            condition_on_previous_text=False,  # Prevents repetition loops
            compression_ratio_threshold=2.4,   # Detect repetitive segments
            log_prob_threshold=-1.0,           # Filter low-confidence outputs
            no_speech_threshold=0.6            # Better silence detection
        )

        total_duration = info.duration

        # Handle auto-detected language
        detected_lang = info.language
        if auto_detect:
            source_language = detected_lang
            lang_name = lang_names.get(detected_lang, detected_lang.upper())
            update_job(job_id, detected_language=detected_lang, detected_language_name=lang_name,
                      current_task=f"Detected: {lang_name}")

        update_job(job_id, source_language=source_language)

        # Determine progress ranges based on whether we need translation
        needs_translation = (source_language != "en") and translate
        transcribe_start = 5
        transcribe_end = 48 if needs_translation else 95

        update_job(job_id, audio_duration=total_duration, progress=transcribe_start)

        logger.info(f"Processing {filename}. Language: {lang_name}. Duration: {total_duration:.1f}s")

        # Collect transcription
        transcription_text = existing_text[:] if existing_text else []
        first_segment = True
        transcribe_range = transcribe_end - transcribe_start
        actual_total_duration = total_duration + resume_from_timestamp

        for segment in segments_transcribe:
            if first_segment:
                update_job(job_id, first_segment_time=time.time())
                first_segment = False

            transcription_text.append(segment.text)
            
            with open(partial_txt_path, "a", encoding="utf-8") as f:
                f.write(segment.text + "\n")
            
            with open(partial_json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "last_timestamp": resume_from_timestamp + segment.end,
                    "base_name": base_name,
                    "language": source_language,
                    "model_tag": "Whisper"
                }, f)

            if actual_total_duration > 0:
                progress = transcribe_start + ((resume_from_timestamp + segment.end) / actual_total_duration * transcribe_range)
                update_job_progress(
                    job_id, progress,
                    f"Transcribing {lang_name}: {int(resume_from_timestamp + segment.end)}s / {int(actual_total_duration)}s",
                    audio_processed=resume_from_timestamp + segment.end
                )

        transcription = "\n".join(transcription_text)
        update_job(job_id, progress=50 if needs_translation else 97)

        # Translate to English (if not already English and requested)
        translation = ""
        if source_language != "en" and translate:
            update_job(job_id, is_translating=True, first_segment_time=None, progress=52,
                      current_task="Starting translation...")

            segments_translate, _ = whisper_model.transcribe(
                audio_path,
                language=source_language,
                task="translate",
                beam_size=5,
                best_of=5,
                temperature=0.0,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                # Anti-hallucination settings
                condition_on_previous_text=False,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.6
            )

            translation_text = []
            first_segment = True
            translate_start = 55
            translate_end = 95
            translate_range = translate_end - translate_start

            for segment in segments_translate:
                if first_segment:
                    update_job(job_id, first_segment_time=time.time())
                    first_segment = False

                translation_text.append(segment.text)

                if total_duration > 0:
                    progress = translate_start + (segment.end / total_duration * translate_range)
                    update_job_progress(
                        job_id, progress,
                        f"Translating: {int(segment.end)}s / {int(total_duration)}s",
                        audio_processed=segment.end
                    )

            translation = "\n".join(translation_text)
        else:
            translation = transcription

        update_job(job_id, progress=97, current_task="Saving files...")

        # Save outputs with custom name
        base_name = output_name if output_name else Path(filename).stem
        save_outputs(job_id, base_name, source_language, lang_name, transcription, translation)

        if partial_txt_path.exists():
            partial_txt_path.unlink()
        if partial_json_path.exists():
            partial_json_path.unlink()
        if resume_from_timestamp > 0 and 'processing_audio_path' in locals() and processing_audio_path != audio_path:
            Path(processing_audio_path).unlink(missing_ok=True)

    except RuntimeError as e:
        update_job(job_id, status="error", error=f"Whisper model error: {e}")
        logger.error(f"Whisper model error processing {filename}: {e}")
    except OSError as e:
        update_job(job_id, status="error", error=f"File error: {e}")
        logger.error(f"File error processing {filename}: {e}")
    except Exception as e:
        update_job(job_id, status="error", error=str(e))
        logger.error(f"Error processing {filename}: {e}")

def transcribe_with_deepgram(job_id, audio_path, filename, source_language, output_name, translate=True):
    """Process audio file using Deepgram API"""
    try:
        update_job(job_id, status="processing", progress=2, current_task="Preparing upload...",
                  source_language=source_language)

        lang_names = {"fr": "French", "en": "English", "hr": "Croatian"}
        lang_name = lang_names.get(source_language, source_language.upper())

        # Map language codes for Deepgram
        deepgram_langs = {"fr": "fr", "en": "en", "hr": "hr"}
        dg_lang = deepgram_langs.get(source_language, source_language)

        # Read audio file
        update_job(job_id, progress=5, current_task="Reading audio file...")
        with open(audio_path, "rb") as audio_file:
            audio_data = audio_file.read()

        update_job(job_id, progress=15, current_task=f"Uploading to Deepgram ({lang_name})...")

        # Transcription request
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "audio/mpeg"
        }

        # Get transcription in source language
        params = {
            "model": "nova-2",
            "language": dg_lang,
            "punctuate": "true",
            "paragraphs": "true"
        }

        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                "https://api.deepgram.com/v1/listen",
                headers=headers,
                params=params,
                content=audio_data
            )

        update_job(job_id, progress=50, current_task="Processing response...")

        if response.status_code != 200:
            raise httpx.HTTPStatusError(f"Deepgram API error: {response.status_code}",
                                        request=response.request, response=response)

        result = response.json()
        transcription = result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")

        # Get audio duration from response
        duration = result.get("metadata", {}).get("duration", 0)
        update_job(job_id, audio_duration=duration, progress=75)

        # For translation, we need another API call or use a translation service
        # Deepgram doesn't directly translate, so for non-English we'd need another service
        translation = ""
        if source_language != "en":
            update_job(job_id, current_task="Note: Deepgram transcription only...", progress=85)

            # Deepgram doesn't translate - provide the transcription as-is
            translation = f"[Deepgram provides transcription only. Translation not available for {lang_name}.]"
        else:
            translation = transcription

        update_job(job_id, progress=97, current_task="Saving files...")

        # Save outputs
        base_name = output_name if output_name else Path(filename).stem
        save_outputs(job_id, base_name, source_language, lang_name, transcription, translation)

    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError) as e:
        update_job(job_id, status="error", error=str(e))
        logger.error(f"Deepgram API error processing {filename}: {e}")
    except OSError as e:
        update_job(job_id, status="error", error=f"File error: {e}")
        logger.error(f"File error processing {filename}: {e}")
    except Exception as e:
        update_job(job_id, status="error", error=str(e))
        logger.error(f"Error processing {filename}: {e}")

def transcribe_with_openai(job_id, audio_path, filename, source_language, output_name, translate=True):
    """Process audio file using OpenAI Whisper API"""
    try:
        update_job(job_id, status="processing", progress=2, current_task="Preparing for OpenAI...",
                  source_language=source_language)

        lang_names = {"fr": "French", "en": "English", "hr": "Croatian"}
        lang_name = lang_names.get(source_language, source_language.upper())

        update_job(job_id, progress=5, current_task=f"Uploading to OpenAI Whisper ({lang_name})...")

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }

        # Step 1: Transcription in source language
        update_job(job_id, progress=10, current_task=f"Transcribing with OpenAI ({lang_name})...")

        with open(audio_path, "rb") as audio_file:
            files = {
                "file": (filename, audio_file, "audio/mpeg"),
                "model": (None, "whisper-1"),
                "language": (None, source_language),
                "response_format": (None, "text")
            }

            with httpx.Client(timeout=600.0) as client:
                response = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files=files
                )

        if response.status_code != 200:
            raise httpx.HTTPStatusError(f"OpenAI API error: {response.status_code}",
                                        request=response.request, response=response)

        transcription = response.text.strip()
        update_job(job_id, progress=50)

        # Step 2: Translation to English (if not already English)
        translation = ""
        if source_language != "en" and translate:
            update_job(job_id, progress=55, current_task="Translating to English with OpenAI...")

            with open(audio_path, "rb") as audio_file:
                files = {
                    "file": (filename, audio_file, "audio/mpeg"),
                    "model": (None, "whisper-1"),
                    "response_format": (None, "text")
                }

                with httpx.Client(timeout=600.0) as client:
                    response = client.post(
                        "https://api.openai.com/v1/audio/translations",
                        headers=headers,
                        files=files
                    )

            if response.status_code != 200:
                raise httpx.HTTPStatusError(f"OpenAI Translation API error: {response.status_code}",
                                            request=response.request, response=response)

            translation = response.text.strip()
        else:
            translation = transcription

        update_job(job_id, progress=97, current_task="Saving files...")

        # Save outputs
        base_name = output_name if output_name else Path(filename).stem
        save_outputs(job_id, base_name, source_language, lang_name, transcription, translation)

    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError) as e:
        update_job(job_id, status="error", error=str(e))
        logger.error(f"OpenAI API error processing {filename}: {e}")
    except OSError as e:
        update_job(job_id, status="error", error=f"File error: {e}")
        logger.error(f"File error processing {filename}: {e}")
    except Exception as e:
        update_job(job_id, status="error", error=str(e))
        logger.error(f"Error processing {filename}: {e}")


def save_outputs(job_id, base_name, source_language, lang_name, transcription, translation):
    """Save transcription and translation outputs with timestamp and model info"""
    # Get timestamp and model info
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    engine = get_job_value(job_id, "engine", "whisper")
    model_tags = {
        "whisper": "whisper-large-v3",
        "deepgram": "deepgram-nova2",
        "openai": "openai-whisper"
    }
    model_tag = model_tags.get(engine, engine)

    file_prefix = base_name

    # Save transcription
    transcription_path = OUTPUT_FOLDER / "transcriptions" / f"{file_prefix}_{source_language}_transcription.txt"
    transcription_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcription_path, "w", encoding="utf-8") as f:
        f.write(f"=== {lang_name} Transcription ===\n")
        f.write(f"Model: {model_tag}\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(transcription)

    # Save translation
    translation_path = OUTPUT_FOLDER / "translations" / f"{file_prefix}_en_translation.txt"
    translation_path.parent.mkdir(parents=True, exist_ok=True)
    with open(translation_path, "w", encoding="utf-8") as f:
        f.write(f"=== English Translation ===\n")
        f.write(f"Model: {model_tag}\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(translation)

    # Save combined
    combined_path = OUTPUT_FOLDER / "combined" / f"{file_prefix}_combined.txt"
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    with open(combined_path, "w", encoding="utf-8") as f:
        f.write(f"=== {lang_name} Transcription ===\n")
        f.write(f"Model: {model_tag}\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(transcription)
        f.write(f"\n\n{'='*50}\n\n")
        f.write(f"=== English Translation ===\n\n")
        f.write(translation)

    # Update job status
    update_job(job_id,
               status="completed",
               progress=100,
               current_task="Complete!",
               estimated_remaining=0,
               transcription=transcription,
               translation=translation,
               output_folder=str(OUTPUT_FOLDER.resolve()),
               files={
                   "transcription": str(transcription_path),
                   "translation": str(translation_path),
                   "combined": str(combined_path)
               })


@app.route('/')
def index():
    """Serve the main interface"""
    return send_from_directory('static', 'index.html')


@app.route('/transcribe')
def transcribe_page():
    """Alias for purrify.ca/transcribe"""
    return send_from_directory('static', 'index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and start transcription"""
    global job_counter

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Save uploaded file
    filename = file.filename
    filepath = UPLOAD_FOLDER / filename
    file.save(filepath)

    # Get and validate options
    source_language = request.form.get('language', 'fr')
    engine = request.form.get('engine', 'whisper')
    output_name = request.form.get('output_name', '').strip()
    resume_partial_json = request.form.get('resume_partial_json', '').strip()
    whisper_model_name = request.form.get('whisper_model', 'large-v3')

    # Validate language parameter
    if source_language not in VALID_LANGUAGES:
        return jsonify({"error": f"Invalid language: {source_language}. Valid options: {', '.join(sorted(VALID_LANGUAGES))}"}), 400

    # Validate engine parameter
    if engine not in VALID_ENGINES:
        return jsonify({"error": f"Invalid engine: {engine}. Valid options: {', '.join(sorted(VALID_ENGINES))}"}), 400

    # Create job
    with job_lock:
        job_counter += 1
        job_id = job_counter

    jobs[job_id] = {
        "id": job_id,
        "filename": filename,
        "status": "queued",
        "progress": 1,
        "current_task": "Queued...",
        "transcription": None,
        "translation": None,
        "files": {},
        "start_time": time.time(),
        "first_segment_time": None,
        "audio_duration": None,
        "estimated_remaining": None,
        "output_folder": str(OUTPUT_FOLDER.resolve()),
        "engine": engine
    }

    # Handle resume parameters
    resume_from_timestamp = 0.0
    existing_text = None
    
    if resume_partial_json and os.path.exists(resume_partial_json):
        try:
            with open(resume_partial_json) as f:
                meta = json.load(f)
            resume_from_timestamp = float(meta.get("last_timestamp", 0.0))
            
            txt_path = Path(str(resume_partial_json).replace('.partial.json', '.partial.txt'))
            if txt_path.exists():
                text_content = open(txt_path, "r", encoding="utf-8").read()
                marker = "Status: IN PROGRESS"
                if marker in text_content:
                    parts = text_content.split(marker, 1)
                    if len(parts) > 1:
                        after_status = parts[1]
                        nl_pos = after_status.find("\n\n")
                        text_part = after_status[nl_pos+2:] if nl_pos != -1 else after_status.split("\n", 1)[-1]
                        existing_text = [line for line in text_part.split("\n") if line.strip()]
        except Exception as e:
            logger.error(f"Error loading resume file: {e}")

    translate_str = request.form.get('translate', 'true').lower()
    translate_bool = translate_str == 'true'

    # Choose processing function based on engine
    if engine == "deepgram":
        if not DEEPGRAM_API_KEY:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Deepgram API key not configured"
            return jsonify({"job_id": job_id, "filename": filename})
        target_func = transcribe_with_deepgram
        args = (job_id, str(filepath), filename, source_language, output_name, translate_bool)
    elif engine == "openai":
        if not OPENAI_API_KEY:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "OpenAI API key not configured"
            return jsonify({"job_id": job_id, "filename": filename})
        target_func = transcribe_with_openai
        args = (job_id, str(filepath), filename, source_language, output_name, translate_bool)
    else:
        target_func = transcribe_with_whisper
        args = (job_id, str(filepath), filename, source_language, output_name, resume_from_timestamp, existing_text, translate_bool, whisper_model_name)

    # Start processing in background thread
    thread = threading.Thread(
        target=target_func,
        args=args
    )
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id, "filename": filename})


def cleanup_old_jobs():
    cutoff = time.time() - 7200  # 2 hours
    with job_lock:
        old_ids = [jid for jid, j in jobs.items()
                   if j.get('status') in ('completed', 'error')
                   and j.get('start_time', 0) < cutoff]
        for jid in old_ids:
            del jobs[jid]

@app.route('/status/<int:job_id>')
def get_status(job_id):
    """Get job status with thread-safe access"""
    cleanup_old_jobs()
    job_data = get_job(job_id)
    if job_data is None:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(job_data)

@app.route('/partial/<int:job_id>')
def get_partial(job_id):
    partial_path = get_job_value(job_id, 'partial_file_path')
    if not partial_path or not os.path.exists(partial_path):
        return jsonify({"error": "No partial file available"}), 404
    # Security: validate path is within PARTIALS_FOLDER
    if not os.path.abspath(partial_path).startswith(str(PARTIALS_FOLDER.resolve())):
        return jsonify({"error": "Invalid path"}), 403
    directory = os.path.dirname(partial_path)
    filename = os.path.basename(partial_path)
    return send_from_directory(directory, filename, as_attachment=False, mimetype='text/plain')

@app.route('/check_partial')
def check_partial():
    output_name = request.args.get('output_name', '').strip()
    filename = request.args.get('filename', '').strip()
    base_name = output_name if output_name else Path(filename).stem if filename else ''
    if not base_name:
        return jsonify({"found": False})
    
    # Scan for matching .partial.json files
    for json_path in PARTIALS_FOLDER.glob(f"{base_name}_*.partial.json"):
        try:
            with open(json_path) as f:
                meta = json.load(f)
            txt_path = Path(str(json_path).replace('.partial.json', '.partial.txt'))
            if txt_path.exists():
                word_count = len(open(txt_path, "r", encoding="utf-8").read().split())
                return jsonify({
                    "found": True,
                    "last_timestamp": meta.get("last_timestamp", 0),
                    "word_count": word_count,
                    "partial_json_path": str(json_path),
                    "partial_txt_path": str(txt_path),
                    "base_name": base_name
                })
        except Exception as e:
            logger.error(f"Error checking partial file: {e}")
    return jsonify({"found": False})


@app.route('/download/<path:filepath>')
def download_file(filepath):
    """Download output file with path traversal protection"""
    # Validate the path is within allowed output directories
    output_dir = os.path.abspath(str(OUTPUT_FOLDER))
    requested_path = os.path.abspath(filepath)

    if not requested_path.startswith(output_dir + os.sep) and requested_path != output_dir:
        return jsonify({"error": "Invalid file path"}), 403

    directory = os.path.dirname(requested_path)
    filename = os.path.basename(requested_path)
    return send_from_directory(directory, filename, as_attachment=True)


@app.route('/open-folder', methods=['POST'])
def open_folder():
    """Open the file in the local file explorer"""
    data = request.json
    filepath = data.get('filepath', '')
    if not filepath:
        return jsonify({"error": "No filepath provided"}), 400
        
    output_dir = os.path.abspath(str(OUTPUT_FOLDER))
    requested_path = os.path.abspath(filepath)
    
    if not requested_path.startswith(output_dir):
        return jsonify({"error": "Invalid path"}), 403
        
    try:
        import platform
        system = platform.system()
        if system == "Darwin":  # macOS
            subprocess.run(["open", "-R", requested_path])
        elif system == "Windows":
            subprocess.run(["explorer", "/select,", requested_path])
        else:  # Linux
            subprocess.run(["xdg-open", os.path.dirname(requested_path)])
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error opening folder: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "whisper_loaded": whisper_model is not None,
        "deepgram_configured": bool(DEEPGRAM_API_KEY),
        "openai_configured": bool(OPENAI_API_KEY)
    })


@app.route('/config')
def config():
    """Get available engines configuration"""
    return jsonify({
        "engines": {
            "whisper": {
                "available": whisper_model is not None,
                "name": "FREE",
                "description": "Local Whisper large-v3 - Good quality, works offline",
                "features": ["transcription", "translation"],
                "speed": "slower"
            },
            "openai": {
                "available": bool(OPENAI_API_KEY),
                "name": "Fast",
                "description": "OpenAI Whisper API - Quick cloud processing",
                "features": ["transcription", "translation"],
                "speed": "fast"
            },
            "deepgram": {
                "available": bool(DEEPGRAM_API_KEY),
                "name": "Multilingual Quality",
                "description": "Deepgram Nova-2 - Fastest, transcription only",
                "features": ["transcription"],
                "speed": "fastest"
            }
        },
        "default_engine": "whisper"
    })


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("PurriFlow Transcription Server")
    logger.info("Powered by purrify.ca")
    logger.info("=" * 60)

    # Load Whisper model at startup
    load_whisper_model()

    logger.info("=" * 60)
    logger.info("Server ready! Open your browser to:")
    logger.info("http://localhost:8080")
    logger.info("http://localhost:8080/transcribe")
    logger.info("=" * 60)

    # Start Flask server
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
