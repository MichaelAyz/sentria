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
