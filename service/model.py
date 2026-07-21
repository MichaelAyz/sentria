import joblib
import os
import logging

logger = logging.getLogger(__name__)

class ModelService:
    def __init__(self, model_path: str = "model.joblib"):
        self.model_path = model_path
        self.model = None
        self.version = "unknown"

    def load(self):
        version_path = os.path.join(os.path.dirname(self.model_path), "version.txt")
        if os.path.exists(version_path):
            with open(version_path, "r") as f:
                self.version = f.read().strip()
        """
        Loads the model from disk.
        If it fails to load, raises an exception to crash the process.
        This provides a clean restart signal for Kubernetes.
        """
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model file not found at {self.model_path}. Crashing process.")
        
        try:
            self.model = joblib.load(self.model_path)
            logger.info("Model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise RuntimeError(f"Startup failure: unable to load model. Crashing process.") from e

    def is_loaded(self) -> bool:
        return self.model is not None

    def predict(self, messages: list[str]) -> list[dict]:
        if not self.is_loaded():
            raise RuntimeError("Model is not loaded.")
            
        categories = self.model.predict(messages)
        probabilities = self.model.predict_proba(messages)
        
        results = []
        for i, category in enumerate(categories):
            class_index = list(self.model.classes_).index(category)
            confidence = probabilities[i][class_index]
            results.append({
                "category": category,
                "confidence": float(confidence)
            })
        return results
