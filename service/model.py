import joblib
import os
import logging
import numpy as np
from typing import List, Dict, Any, Optional

from .embedder import MiniLMEmbedder
from .features import transform_features

logger = logging.getLogger(__name__)

class ModelService:
    MAX_LOG_LENGTH = 2000

    def __init__(self, linear_head_path: Optional[str] = None, quantized: bool = True):
        if linear_head_path is None:
            linear_head_path = os.path.join(os.path.dirname(__file__), "linear_head.joblib")
        self.linear_head_path = linear_head_path
        self.quantized = quantized
        self.linear_head = None
        self.embedder = None
        self.version = "unknown"
        self._warmed = False

    def load(self):
        """
        Loads the linear classification head and initializes the ONNX MiniLM embedder.
        If loading fails, raises an exception to crash the process (clean restart signal).
        """
        version_path = os.path.join(os.path.dirname(self.linear_head_path), "version.txt")
        if os.path.exists(version_path):
            with open(version_path, "r") as f:
                self.version = f.read().strip()
        
        if not os.path.exists(self.linear_head_path):
            raise FileNotFoundError(f"Linear head not found at {self.linear_head_path}. Crashing process.")
        
        try:
            self.linear_head = joblib.load(self.linear_head_path)
            self.embedder = MiniLMEmbedder(quantized=self.quantized)
            logger.info(f"Model loaded successfully (quantized={self.quantized}, version={self.version}).")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise RuntimeError(f"Startup failure: unable to load model. Crashing process.") from e

    def is_loaded(self) -> bool:
        return self.linear_head is not None and self.embedder is not None

    def warm(self):
        """Pre-warm the ONNX runtime session and linear head to eliminate cold starts."""
        if not self.is_loaded():
            return
        dummy = ["Warmup test log line", "ERROR connection failed to db", "GET /index.html 200 OK"]
        for _ in range(2):
            self.predict(dummy)
        self._warmed = True
        logger.info("Model pre-warmed successfully.")

    def is_warmed(self) -> bool:
        return getattr(self, '_warmed', False)

    def _sanitize(self, message: str) -> str:
        if not message or not message.strip():
            return "[EMPTY_LOG]"
        if len(message) > self.MAX_LOG_LENGTH:
            return message[:self.MAX_LOG_LENGTH]
        return message

    def _keyword_fallback(self, message: str) -> Optional[str]:
        """Fallback classification using keyword rules when ML confidence is low."""
        msg_lower = message.lower()
        
        # Check for security indicators first (most specific attack vectors & auth failures)
        security_keywords = [
            '[security]', 'attack', 'brute force', 'injection', 'traversal',
            'unauthorized', 'access denied', 'permission denied for user', 'xss',
            '/etc/passwd', '/etc/shadow', 'break-in', 'invalid user', 'failed password',
            'jwt', 'cors', 'csrf', 'ssrf', 'wrongpass', 'noauth', 'authenticating user',
            'role "', '.aws/credentials', "admin'--", 'jndi', '169.254.', 'prompt(',
            '<script', 'cmd=id', 'cmd=cat', 'corrupted mac', 'authentication failure'
        ]
        if any(kw in msg_lower for kw in security_keywords):
            return 'security'
        
        # Check for error/critical indicators
        error_keywords = [
            'fatal', 'exception', 'econnrefused', 'division by zero',
            'cannot read', 'oom', '500 ', '502 ', '503 ', 'violates',
            'failed to find server action', 'syntax error', 'panic', 'segfault',
            'databaseerror', 'connection pool exhausted', 'handler not found',
            'open /dev/null failed', 'could not get shadow information',
            'fatal: sshd', 'unhandled promise'
        ]
        if any(kw in msg_lower for kw in error_keywords):
            return 'error'
        
        # Check for warning indicators
        warning_keywords = [
            '[warn]', '[warning]', 'warning:', 'alert', 'slow query', '404 ', '403 ', '400 ', '405 ',
            '413 ', '301 ', 'broken pipe', 'timeout', 'heap memory', 'skipping',
            'slowlog', 'bgsave', 'deprecationwarning', 'is deprecated',
            'enabling "trust"', 'kex_exchange_identification'
        ]
        if any(kw in msg_lower for kw in warning_keywords):
            return 'warning'
        
        # Check for routine/noise indicators
        noise_keywords = [
            '200 ', '204 ', '201 ', '304 ', 'accepted publickey', 'session opened',
            'session closed', 'server listening', 'ready for start up', 'ping',
            'dbsize', 'started session', 'cleanup', 'configuration complete',
            'docker-entrypoint.sh', 'pam_unix(sshd:session)'
        ]
        if any(kw in msg_lower for kw in noise_keywords):
            return 'noise'
        
        return None  # Keep model prediction

    def predict(self, messages: List[str]) -> List[Dict[str, Any]]:
        """
        Classifies batch of messages using MiniLM hybrid embeddings + linear head + safety net.
        """
        if not self.is_loaded():
            raise RuntimeError("Model is not loaded.")
        if not messages:
            return []
        
        sanitized = [self._sanitize(msg) for msg in messages]
        
        # 1. Transform into 388-dim hybrid feature matrix (cleaned embedding + aux structural features)
        features = transform_features(sanitized, self.embedder)
        
        # 2. Linear classification head prediction
        probs = self.linear_head.predict_proba(features)
        best_indices = np.argmax(probs, axis=1)
        confidences = probs[np.arange(len(sanitized)), best_indices]
        categories = self.linear_head.classes_[best_indices]
        
        results = []
        for i in range(len(sanitized)):
            cat = str(categories[i])
            conf = float(confidences[i])
            
            # Heuristic safety net fallback for low-confidence predictions (< 0.60)
            if conf < 0.60:
                heuristic_cat = self._keyword_fallback(sanitized[i])
                if heuristic_cat and heuristic_cat != cat:
                    cat = heuristic_cat
                    conf = 0.55  # Mark as heuristic-derived
            
            results.append({
                "category": cat,
                "confidence": round(conf, 4)
            })
            
        return results
