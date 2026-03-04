# TRANSCRIBE Improvements

**Type:** Python Flask - Audio Transcription Service
**Production Ready:** No (60%)

## Summary
Clean audio transcription app using Whisper, but critical security gaps exist.

## Critical Fixes

| Priority | Issue | File | Fix |
|----------|-------|------|-----|
| CRITICAL | Path traversal | `transcribe_server.py:570-572` | Validate filepath against output dir only |
| HIGH | No input validation | `transcribe_server.py:505-507` | Validate language/engine parameters |
| HIGH | Race conditions | `transcribe_server.py:40-42` | Add proper locking for jobs dict |
| HIGH | Broad exception handling | Lines 241, 326, 409 | Catch specific exceptions |
| MEDIUM | CORS allows all origins | Line 23 | Restrict to specific domains |
| MEDIUM | No logging framework | Throughout | Replace print() with logging module |
| MEDIUM | Memory leak in JS | `static/app.js:299-326` | Clear old jobs from memory |

## Specific Tasks

### 1. Fix Path Traversal (2 hours)
```python
# In transcribe_server.py, validate paths:
def validate_output_path(filepath):
    output_dir = os.path.abspath(OUTPUT_DIR)
    requested = os.path.abspath(filepath)
    if not requested.startswith(output_dir):
        raise ValueError("Invalid path")
```

### 2. Add Input Validation (3 hours)
```python
VALID_LANGUAGES = ['en', 'fr', 'es', ...]
VALID_ENGINES = ['local', 'openai', 'deepgram']

def validate_request(source_language, engine):
    if source_language not in VALID_LANGUAGES:
        raise ValueError(f"Invalid language: {source_language}")
```

## Recommended Tooling

```bash
# Testing
pip install pytest pytest-cov

# Type checking
pip install mypy

# Linting
pip install pylint flake8
```
