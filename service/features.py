"""
Feature Engineering for Log Classification
Provides log prefix cleaning (signal extraction) and structural indicator feature extraction.
Combines 384-dimensional MiniLM embeddings with normalized structural markers into
an enriched 388-dimensional hybrid feature vector.
"""
import re
from typing import List
import numpy as np

# Compiled regular expressions for fast syslog / ISO-8601 / container prefix removal
PREFIX_PATTERNS = [
    # ISO-8601 / standard UTC timestamps with optional PID brackets
    re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\s*(?:UTC\s*)?(?:\[\d+\]\s*)?'),
    # Syslog traditional format: "Dec 10 07:11:00 hostname daemon[123]: "
    re.compile(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+[\w\.\-]+(?:\s+[\w\.\-]+\[\d+\])?:?\s*'),
    # Redis log prefix: "1:M 15 Sep 2026 07:32:39.319 * "
    re.compile(r'^\d+:[M|C|S]\s+\d{2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+\s*'),
    # Nginx error log timestamp: "2026/09/15 07:32:10 "
    re.compile(r'^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\s*'),
    # Common Apache / Nginx access log prefix: "172.17.0.1 - - [15/Sep/2026:07:32:10 +0000] "
    re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}\s+-\s+-\s+\[[^\]]+\]\s*'),
    # Kubernetes event prefix: "k8s event: [Warning] " or "k8s event: [Normal] "
    re.compile(r'^k8s event:\s*\[\w+\]\s*')
]

def clean_log_prefix(text: str) -> str:
    """
    Strips dynamic date, timestamp, and daemon metadata from the start of a log line,
    leaving the actual semantic payload for the embedding tokenizer.
    """
    s = text.strip()
    for pat in PREFIX_PATTERNS:
        s = pat.sub('', s).strip()
    return s

def transform_features(texts: List[str], embedder) -> np.ndarray:
    """
    Transforms raw log texts into pure 384-dimensional MiniLM embeddings
    after stripping dynamic date and syslog metadata prefixes.
    No auxiliary label-proxy features are injected.
    """
    cleaned_texts = [clean_log_prefix(t) for t in texts]
    return embedder.embed(cleaned_texts, batch_size=64)

