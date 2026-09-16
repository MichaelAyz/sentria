"""
Training script for the Linear Classification Head on top of frozen MiniLM embeddings.
Reads training/data/train_logs.jsonl, embeds via ONNX MiniLM, trains LogisticRegression,
validates on training/data/val_logs.jsonl, and saves service/linear_head.joblib.
"""
import json
import os
import subprocess
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from service.embedder import MiniLMEmbedder
from service.features import transform_features

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRAIN_FILE = os.path.join(DATA_DIR, "train_logs.jsonl")
VAL_FILE = os.path.join(DATA_DIR, "val_logs.jsonl")
OUTPUT_MODEL = os.path.join(os.path.dirname(__file__), "..", "service", "linear_head.joblib")

def load_jsonl(filepath):
    texts, labels, systems = [], [], []
    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            texts.append(item["raw_log"])
            labels.append(item["category"])
            systems.append(item.get("system", "unknown"))
    return texts, labels, systems

def train():
    print("==========================================================")
    print("TRAINING LINEAR CLASSIFIER HEAD ON FROZEN MiniLM EMBEDDINGS")
    print("==========================================================")
    
    print(f"Loading training data from {TRAIN_FILE}...")
    train_texts, train_labels, _ = load_jsonl(TRAIN_FILE)
    print(f"Loaded {len(train_texts)} training records.")
    
    print("Initializing MiniLM ONNX Embedder (FP32)...")
    embedder = MiniLMEmbedder(quantized=False)
    
    print("Extracting 384-dimensional pure MiniLM features for training set...")
    X_train = transform_features(train_texts, embedder)
    y_train = np.array(train_labels)
    print(f"X_train shape: {X_train.shape}")
    
    # Train calibrated LogisticRegression head
    print("Fitting LogisticRegression(class_weight='balanced', C=1.0)...")
    clf = LogisticRegression(
        class_weight="balanced", 
        max_iter=1000, 
        random_state=42, 
        C=1.0,
        solver="lbfgs"
    )
    clf.fit(X_train, y_train)
    print(f"Classes learned: {list(clf.classes_)}")
    
    # Save the linear head
    os.makedirs(os.path.dirname(OUTPUT_MODEL), exist_ok=True)
    joblib.dump(clf, OUTPUT_MODEL)
    print(f"Saved linear head to {OUTPUT_MODEL} ({os.path.getsize(OUTPUT_MODEL) / 1024:.1f} KB)")
    
    # Evaluate on Validation Set (for calibration and sanity check)
    if os.path.exists(VAL_FILE):
        print("\n--- Validation Set Evaluation (Calibration Gate) ---")
        val_texts, val_labels, _ = load_jsonl(VAL_FILE)
        X_val = transform_features(val_texts, embedder)
        y_val = np.array(val_labels)
        
        y_pred = clf.predict(X_val)
        probs = clf.predict_proba(X_val)
        
        print(classification_report(y_val, y_pred, digits=4))
        
        # Check confidence distributions
        confidences = np.max(probs, axis=1)
        print(f"Mean Confidence on Validation Set: {np.mean(confidences):.4f}")
        print(f"P25 Confidence: {np.percentile(confidences, 25):.4f}")
        print(f"P50 (Median) Confidence: {np.median(confidences):.4f}")
        print(f"P75 Confidence: {np.percentile(confidences, 75):.4f}")
        
    # Write model version
    try:
        git_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    except Exception:
        git_sha = "unknown"
        
    version_file = os.path.join(os.path.dirname(OUTPUT_MODEL), "version.txt")
    with open(version_file, "w") as f:
        f.write(f"minilm-onnx-{git_sha[:8]}")
    print(f"Model version saved to {version_file}")
    print("==========================================================")

if __name__ == "__main__":
    train()
