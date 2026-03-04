# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Audio transcription and translation web application supporting multiple engines: local Whisper (faster-whisper), OpenAI Whisper API, and Deepgram API. Transcribes audio in French, English, or Croatian and translates to English.

## Commands

```bash
# Start the server (activates venv and runs Flask on port 8080)
./start_server.sh

# Or manually:
source venv/bin/activate
python3 transcribe_server.py

# Install dependencies
pip install -r requirements.txt
```

Access the UI at http://localhost:8080

## Environment Variables

Create a `.env` file for API-based engines:
```
DEEPGRAM_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```
Local Whisper works without any API keys.

## Architecture

### Backend (`transcribe_server.py`)
- Flask server serving static files and REST API
- Three transcription engines: `transcribe_with_whisper`, `transcribe_with_deepgram`, `transcribe_with_openai`
- WhisperModel loaded once at startup (large-v3, CPU, float32)
- Background threading for transcription jobs
- Job tracking via global `jobs` dict with status polling

### API Endpoints
- `POST /upload` - Upload audio file with `language`, `engine`, `output_name` params; returns job_id
- `GET /status/<job_id>` - Poll job progress (0-100%), status, current_task, estimated_remaining, detected_language
- `GET /download/<path>` - Download output files
- `GET /config` - Returns available engines and their status (for frontend mode cards)
- `GET /health` - Returns model/API status

### Frontend (`static/`)
- `index.html` - Single page with drag-drop upload, mode card selector, language dropdown with auto-detect
- `app.js` - Config fetching, mode card availability, file upload, job card management, polling (1s interval)
- `style.css` - Dark glassmorphism theme with animated background orbs, mode cards, micro-animations

### Processing Flow
1. File uploaded to `uploads/`
2. Transcription: 5-48% progress (5-95% for English-only)
3. Translation to English: 52-95% progress (skipped for English)
4. Output saved to `outputs/{transcriptions,translations,combined}/`
5. Job marked complete at 100%

Output filenames include timestamp and model tag: `{name}_{timestamp}_{model}_transcription.txt`

## Key Implementation Details

- Model downloads to current directory on first run
- VAD filter enabled with 500ms silence threshold
- Anti-hallucination: `condition_on_previous_text=False`, compression ratio threshold, log probability filtering
- Language auto-detection: Pass `language=auto` to let Whisper detect the source language
- Progress includes real-time ETA based on audio processing speed
- Job status: queued → processing → completed/error
- Mode cards dynamically enable/disable based on API key availability (fetched from `/config`)
- Deepgram provides transcription only (no translation)
