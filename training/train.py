import os
import subprocess
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import Pipeline
import joblib

TRAIN_FILE = "training/data/train_logs.csv"
MODEL_OUTPUT = "service/model.joblib"

def train_model():
    if not os.path.exists(TRAIN_FILE):
        raise FileNotFoundError(f"Training data {TRAIN_FILE} not found. Run generator in batch mode first.")
        
    df = pd.read_csv(TRAIN_FILE)
    X = df["message"]
    y = df["true_label"]
    
    print(f"Training on {len(df)} records...")
    
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(max_features=5000, ngram_range=(1, 2))),
        ('clf', SGDClassifier(loss='log_loss', max_iter=1000, random_state=42, class_weight='balanced', alpha=0.0005))
    ])
    
    pipeline.fit(X, y)
    
    os.makedirs(os.path.dirname(MODEL_OUTPUT), exist_ok=True)
    joblib.dump(pipeline, MODEL_OUTPUT)
    print(f"Model saved to {MODEL_OUTPUT}")
    
    try:
        git_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    except Exception:
        git_sha = "unknown"
    
    version_file = os.path.join(os.path.dirname(MODEL_OUTPUT), "version.txt")
    with open(version_file, "w") as f:
        f.write(git_sha)
    print(f"Model version {git_sha} saved to {version_file}")

if __name__ == "__main__":
    train_model()
