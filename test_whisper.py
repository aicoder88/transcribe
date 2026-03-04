from faster_whisper import WhisperModel
import time
import os

model_path = "large-v3"
audio_file = "test_audio_2.m4a"

print("Loading model...")
start = time.time()
model = WhisperModel(model_path, device="cpu", compute_type="int8", download_root=".")
print(f"Model loaded in {time.time() - start:.2f}s")

print("Starting transcription with VAD...")
start = time.time()
segments, info = model.transcribe(
    audio_file,
    language="fr",
    beam_size=5,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500)
)
print(f"Call returned in {time.time() - start:.2f}s")

print(f"Audio duration: {info.duration}")

print("Iterating segments...")
count = 0
for segment in segments:
    count += 1
    print(f"Segment {count}: {segment.end}s")
    if count >= 3:
        break
