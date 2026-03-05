# Audio Transcription & Translation Interface

Easy-to-use web interface for transcribing English, French, Croatian, or other language audio files and then translating them to English using OpenAI's Whisper large-v3 model.

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

## 🚀 How to Install and Run Locally

**No manual model downloads required!** The server will automatically download the Whisper AI models (roughly 3GB) directly to your computer the very first time you process a file. 

### Prerequisites
1. **Python 3.13+** installed on your computer.
2. **FFmpeg** installed (Mac: `brew install ffmpeg`, Windows: `winget install ffmpeg`).

### Installation
1. **Clone this repository:**
   ```bash
   git clone https://github.com/aicoder88/transcribe.git
   cd transcribe
   ```

2. **Set up the Python Environment:**
   Run these commands to create an isolated environment and install the required packages:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # (On Windows, use: venv\Scripts\activate)
   pip install -r requirements.txt
   ```

3. **Start the server:**
   ```bash
   ./start_server.sh
   # Note: On Windows, use `python transcribe_server.py` instead.
   ```

4. **Open your browser:**
   Navigate to [http://localhost:8080](http://localhost:8080)

5. **Upload audio files:**
   - The first time you process a file, the server will briefly pause to download the Whisper AI model to your computer automatically.
   - Simply drag and drop files onto the upload area.
   - Watch real-time progress and download output files!

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
