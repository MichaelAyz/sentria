from starlette.middleware.base import BaseHTTPMiddleware
import time
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Request, Response

INFERENCE_REQUESTS = Counter(
    "inference_requests_total",
    "Total inference requests",
    ["category", "status_code"]
)

INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds",
    "Inference latency in seconds",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

INFERENCE_CONFIDENCE = Histogram(
    "inference_confidence_score",
    "Confidence score of predictions",
    buckets=[0.1, 0.3, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 0.95, 1.0]
)

MODEL_LOADED = Gauge(
    "model_loaded",
    "1 if model is loaded, 0 otherwise",
    ["version"]
)

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            data = generate_latest()
            return Response(content=data, media_type=CONTENT_TYPE_LATEST)
            
        if request.url.path == "/classify" and request.method == "POST":
            start_time = time.time()
            response = await call_next(request)
            latency = time.time() - start_time
            INFERENCE_LATENCY.observe(latency)
            return response
            
        return await call_next(request)
