#!/bin/bash
set -e

echo "======================================"
echo "Phase 2 (pytest, FastAPI boot, streaming)..."
echo "======================================"

echo "Running pytest..."
pytest service/tests/

echo "Booting FastAPI locally in background..."
uvicorn service.main:app --host 127.0.0.1 --port 8000 &
UVICORN_PID=$!
sleep 5

echo "Running streaming generator against live FastAPI endpoint..."
python ingestion/generator.py --mode streaming --url http://127.0.0.1:8000/classify --batch-size 10 --interval 2.0 > stream.log 2>&1 &
STREAM_PID=$!

sleep 10
kill $STREAM_PID || true
kill $UVICORN_PID || true

echo "======================================"
echo "Streaming Logs showing needs_review matches:"
grep -A 2 -i "'needs_review': True" stream.log | head -n 15 || echo "No needs_review logs found in the stream."
echo "======================================"
