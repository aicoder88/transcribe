#!/bin/bash

# Transcription Server Startup Script

echo "=================================="
echo "Starting Transcription Server"
echo "=================================="
echo ""

# Activate virtual environment
source venv/bin/activate

# Start the server
python3 transcribe_server.py
