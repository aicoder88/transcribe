import os
import sys
import httpx
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load env vars
load_dotenv()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
OUTPUT_FOLDER = Path("outputs")

def transcribe_deepgram(audio_path, output_name=None):
    if not DEEPGRAM_API_KEY:
        print("Error: DEEPGRAM_API_KEY not found in .env")
        return

    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"Error: {audio_path} not found")
        return

    print(f"Reading {audio_path}...")
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    print("Uploading to Deepgram (nova-2, auto-detect language)...")
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/mpeg" 
    }
    
    # Try with auto-detection
    params = {
        "model": "nova-2",
        "punctuate": "true",
        "paragraphs": "true",
        "detect_language": "true"
    }

    try:
        with httpx.Client(timeout=600.0) as client:
            response = client.post(
                "https://api.deepgram.com/v1/listen",
                headers=headers,
                params=params,
                content=audio_data
            )
        
        if response.status_code != 200:
            print(f"Deepgram Error {response.status_code}: {response.text}")
            return

        result = response.json()
        transcription = result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")
        detected_lang = result.get("metadata", {}).get("detected_language", "en")
        
        # RESTRICTION: Block English results from Deepgram
        if detected_lang == "en":
            print("\n!!! RESTRICTED !!!")
            print("Deepgram has detected English ('en'). This engine is restricted for English.")
            print("Please run this again utilizing the Whisper engine for English content.")
            return

        print(f"Transcription complete. Detected language: {detected_lang}")
        
        # Save results
        base_name = output_name if output_name else audio_path.stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Transcription path
        trans_dir = OUTPUT_FOLDER / "transcriptions"
        trans_dir.mkdir(parents=True, exist_ok=True)
        trans_path = trans_dir / f"{base_name}_{detected_lang}_transcription.txt"
        
        with open(trans_path, "w", encoding="utf-8") as f:
            f.write(f"=== {detected_lang} Transcription ===\n")
            f.write(f"Source: {audio_path.name}\n")
            f.write(f"Model: Deepgram Nova-2\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(transcription)
            
        print(f"Saved transcription to {trans_path}")
        
        # Also save combined if it's English
        if detected_lang == "en":
            comb_dir = OUTPUT_FOLDER / "combined"
            comb_dir.mkdir(parents=True, exist_ok=True)
            comb_path = comb_dir / f"{base_name}_combined.txt"
            with open(comb_path, "w", encoding="utf-8") as f:
                f.write(f"=== English Transcription ===\n")
                f.write(f"Source: {audio_path.name}\n\n")
                f.write(transcription)
            print(f"Saved combined output to {comb_path}")
            
        return trans_path

    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python it_transcriber.py <audio_path> [output_name]")
    else:
        path = sys.argv[1]
        out = sys.argv[2] if len(sys.argv) > 2 else None
        transcribe_deepgram(path, out)
