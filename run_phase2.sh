#!/bin/bash
set -e
echo "Installing dependencies..."
pip install --no-cache-dir -r requirements.txt > /dev/null

echo "Generating data..."
python ingestion/generator.py --mode batch --output training/data/train_logs.csv --count 5000 > /dev/null
python ingestion/generator.py --mode batch --output training/data/test_logs.csv --count 1000 > /dev/null

echo "Training model..."
python training/train.py > /dev/null

echo "Evaluating model..."
python training/evaluate.py > eval.log
cat eval.log

# Extract low confidence count
COUNT=$(grep "Predictions below threshold" eval.log | awk -F'[:]' '{print $2}' | awk '{print $1}')
echo "Low confidence count: $COUNT"

if [ "$COUNT" -gt 0 ]; then
  echo "======================================"
  echo "Success! Found $COUNT low-confidence predictions."
  echo "Proceeding to Phase 2 (pytest, FastAPI boot, streaming)..."
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
else
  echo "Failed: No low-confidence predictions found."
fi
