# Audio Transcription & Translation Interface

Easy-to-use web interface for transcribing French audio files and translating them to English using OpenAI's Whisper large-v3 model.

## Features

- 🎙️ **Transcribe** French audio to text
- 🌍 **Translate** French audio to English
- 📁 **Drag & Drop** support for easy file upload
- 📊 **Real-time Progress** tracking
- 💾 **Download** transcriptions and translations
- 🎨 **Beautiful UI** with dark mode and glassmorphism
- 🔄 **Batch Processing** for multiple files

## Supported Audio Formats

M4A, MP3, WAV, FLAC, OGG, and more

## Quick Start

1. **Start the server:**
   ```bash
   ./start_server.sh
   ```

2. **Open your browser:**
   Navigate to `http://localhost:8080`

3. **Upload audio files:**
   - Drag and drop files onto the upload area, or
   - Click to browse and select files

4. **Wait for processing:**
   - Watch real-time progress
   - View transcription and translation results
   - Download output files

## Output Files

All processed files are saved in the `outputs/` directory:
- `outputs/transcriptions/` - French transcriptions
- `outputs/translations/` - English translations
- `outputs/combined/` - Both in one file

## Requirements

- Python 3.13+
- FFmpeg (installed via Homebrew)
- Virtual environment with faster-whisper and Flask

## Technical Details

- **Model:** [Whisper large-v3 (Systran faster-whisper)](https://huggingface.co/Systran/faster-whisper-large-v3)
- **Backend:** Flask + faster-whisper
- **Frontend:** Vanilla HTML/CSS/JavaScript
- **Processing:** Background threads with real-time status updates

## Notes

- First run may take longer as the model downloads
- Processing time depends on audio length and quality
- For poor audio quality, the large-v3 model provides best results
