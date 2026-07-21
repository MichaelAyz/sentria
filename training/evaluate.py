import os
import pandas as pd
import joblib
from sklearn.metrics import classification_report

TEST_FILE = "training/data/test_logs.csv"
MODEL_FILE = "service/model.joblib"
THRESHOLD_NEEDS_REVIEW = 0.75

def evaluate_model():
    if not os.path.exists(TEST_FILE):
        raise FileNotFoundError(f"Test data {TEST_FILE} not found. Run generator in batch mode first to create a test set.")
    if not os.path.exists(MODEL_FILE):
        raise FileNotFoundError(f"Model {MODEL_FILE} not found. Run train.py first.")
        
    df = pd.read_csv(TEST_FILE)
    X = df["message"]
    y_true = df["true_label"]
    
    model = joblib.load(MODEL_FILE)
    y_pred = model.predict(X)
    y_proba = model.predict_proba(X)
    
    print("--- Evaluation Report ---")
    print(classification_report(y_true, y_pred))
    
    low_confidence_count = 0
    for i, pred_class in enumerate(y_pred):
        class_idx = list(model.classes_).index(pred_class)
        confidence = y_proba[i][class_idx]
        if confidence < THRESHOLD_NEEDS_REVIEW:
            low_confidence_count += 1
            
    print(f"\n--- Confidence Review ---")
    print(f"Predictions below threshold (< {THRESHOLD_NEEDS_REVIEW}): {low_confidence_count} out of {len(y_pred)}")

if __name__ == "__main__":
    evaluate_model()
