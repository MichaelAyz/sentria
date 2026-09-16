import os
import re
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional

import time
from .model import ModelService
from .stitcher import stitch_multiline_logs
from .metrics import MetricsMiddleware, MODEL_LOADED, INFERENCE_REQUESTS, INFERENCE_CONFIDENCE
from .feedback import setup_database, save_feedback
from .incidents import Incident, IncidentGrouper

THRESHOLD_NEEDS_REVIEW = 0.75
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(os.path.dirname(__file__), "linear_head.joblib"))
QUANTIZED = os.getenv("QUANTIZED", "true").lower() in ("true", "1", "yes")

model_service = ModelService(linear_head_path=MODEL_PATH, quantized=QUANTIZED)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Process will crash if this fails
    model_service.load()
    if hasattr(model_service, "warm"):
        model_service.warm()
    MODEL_LOADED.labels(version=model_service.version).set(1)
    setup_database()
    yield
    MODEL_LOADED.labels(version=model_service.version).set(0)

app = FastAPI(lifespan=lifespan)
app.add_middleware(MetricsMiddleware)

class LogLine(BaseModel):
    timestamp: str
    source: str
    level: str
    message: str

class ClassifyRequest(BaseModel):
    logs: List[LogLine]

class ClassificationResult(BaseModel):
    log_id: str
    category: str
    confidence: float
    needs_review: bool
    source: Optional[str] = None
    message: Optional[str] = None
    timestamp: Optional[str] = None

class TriageSummary(BaseModel):
    total_logs: int
    latency_ms: Optional[float] = None
    counts: dict  # {"critical": N, "security": N, "warning": N, "routine": N, "uncertain": N}
    top_ips: List[dict]  # [{"ip": "x.x.x.x", "count": N, "categories": ["security"]}]
    diagnostic: str  # Human-readable diagnostic paragraph
    severity: str  # "critical", "warning", "healthy"

class ClassifyResponse(BaseModel):
    results: List[ClassificationResult]
    triage_summary: Optional[TriageSummary] = None
    incidents: Optional[List[Incident]] = None

class FeedbackRequest(BaseModel):
    log_id: str
    message: str
    predicted_category: str
    true_category: str

@app.get("/", include_in_schema=False)
def get_ui():
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Sentria UI not found</h1>", status_code=404)

@app.get("/health")
def health_check():
    if not model_service.is_loaded():
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ok", "model_loaded": True, "model_version": model_service.version}

@app.api_route("/reload", methods=["GET", "POST"])
def reload_model():
    model_service.load()
    MODEL_LOADED.labels(version=model_service.version).set(1)
    return {"status": "reloaded", "model_version": model_service.version}

@app.get("/api/stats")
def get_stats():
    from .feedback import get_feedback_count
    return {
        "status": "OPERATIONAL",
        "model_loaded": model_service.is_loaded(),
        "model_version": model_service.version,
        "quantized": getattr(model_service, "quantized", False),
        "feedbacks_collected": get_feedback_count()
    }

def _classify_from_logs(logs: List[LogLine]) -> ClassifyResponse:
    if not logs:
        return ClassifyResponse(results=[])
        
    start_time = time.time()
    
    # Extract raw messages and stitch multi-line stack traces (e.g. Next.js, Node, Python)
    raw_messages = [log.message for log in logs]
    stitched_messages = stitch_multiline_logs(raw_messages)
    
    # Maintain source reference (use first log's source or per-line source)
    default_source = logs[0].source if logs else None
    
    try:
        predictions = model_service.predict(stitched_messages)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
        
    results = []
    for i, pred in enumerate(predictions):
        log_id = str(uuid.uuid4())
        needs_review = pred["confidence"] < THRESHOLD_NEEDS_REVIEW
        
        INFERENCE_REQUESTS.labels(category=pred["category"], status_code="200").inc()
        INFERENCE_CONFIDENCE.observe(pred["confidence"])
        
        msg = stitched_messages[i] if i < len(stitched_messages) else None
        orig_log = logs[i] if i < len(logs) else None
        log_source = orig_log.source if orig_log and orig_log.source else default_source
        log_timestamp = orig_log.timestamp if orig_log and orig_log.timestamp else None

        results.append(ClassificationResult(
            log_id=log_id,
            category=pred["category"],
            confidence=pred["confidence"],
            needs_review=needs_review,
            source=log_source,
            message=msg,
            timestamp=log_timestamp
        ))
    
    elapsed_ms = round((time.time() - start_time) * 1000, 1)
    triage = _generate_triage_summary(results, elapsed_ms=elapsed_ms)

    # Incident grouping & root cause analysis across anomalous log events
    anomalous = [r for r in results if r.category in ("error", "warning", "security")]
    incidents = None
    if len(anomalous) >= 2:
        grouper = IncidentGrouper(window_seconds=120)
        found_incidents = grouper.analyze(anomalous)
        if found_incidents:
            incidents = found_incidents

    return ClassifyResponse(results=results, triage_summary=triage, incidents=incidents)

@app.post("/classify", response_model=ClassifyResponse)
def classify_logs(request: ClassifyRequest):
    return _classify_from_logs(request.logs)

@app.post("/ingest/raw", response_model=ClassifyResponse)
async def ingest_raw(request: Request, source: Optional[str] = "raw"):
    content_type = request.headers.get("content-type", "").lower()
    raw_text = ""
    effective_source = source or "raw"

    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                raw_text = body.get("raw", "")
                if body.get("source"):
                    effective_source = body["source"]
            elif isinstance(body, str):
                raw_text = body
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
    else:
        body_bytes = await request.body()
        raw_text = body_bytes.decode("utf-8", errors="replace")

    if not raw_text or not raw_text.strip():
        raise HTTPException(status_code=400, detail="No log content provided")

    stitched_lines = stitch_multiline_logs(raw_text.splitlines())
    if not stitched_lines:
        raise HTTPException(status_code=400, detail="No log content provided")

    now_iso = datetime.now(timezone.utc).isoformat()

    logs = [
        LogLine(
            timestamp=now_iso,
            source=effective_source,
            level="INFO",
            message=line
        )
        for line in stitched_lines
    ]

    return _classify_from_logs(logs)


IP_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

def _generate_triage_summary(results: List[ClassificationResult], elapsed_ms: float = 0.0) -> TriageSummary:
    """Generate a clean triage summary with category breakdown and IP correlation."""
    counts = {"critical": 0, "security": 0, "warning": 0, "routine": 0, "uncertain": 0}
    ip_data = {}
    
    for r in results:
        if r.category == "error":
            counts["critical"] += 1
        elif r.category == "security":
            counts["security"] += 1
        elif r.category == "warning":
            counts["warning"] += 1
        else:
            counts["routine"] += 1
        
        if r.needs_review:
            counts["uncertain"] += 1
        
        # Extract IPs
        if r.message:
            ips_found = IP_PATTERN.findall(r.message)
            for ip in ips_found:
                if ip.startswith("0.") or ip == "0.0.0.0" or ip == "127.0.0.1":
                    continue
                if ip not in ip_data:
                    ip_data[ip] = {"count": 0, "categories": set()}
                ip_data[ip]["count"] += 1
                ip_data[ip]["categories"].add(r.category)
    
    # Top IPs
    top_ips = []
    for ip, data in sorted(ip_data.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
        if data["count"] >= 2 or data["categories"] & {"security", "error"}:
            top_ips.append({
                "ip": ip,
                "count": data["count"],
                "categories": sorted(data["categories"])
            })
    
    # Build clean diagnostic
    diagnostic_parts = []
    total = len(results)
    
    if counts["security"] > 0:
        diagnostic_parts.append(f"{counts['security']} security event(s) detected.")
    if counts["critical"] > 0:
        diagnostic_parts.append(f"{counts['critical']} critical failure(s) require immediate attention.")
    if counts["warning"] > 0:
        diagnostic_parts.append(f"{counts['warning']} operational warning(s) flagged.")
    if counts["uncertain"] > 0:
        diagnostic_parts.append(f"{counts['uncertain']} log event(s) classified with low confidence (<0.75).")
        
    if counts["security"] > 0 and top_ips:
        sec_ips = [ip for ip in top_ips if "security" in ip["categories"]]
        if sec_ips:
            top_ip = sec_ips[0]
            if top_ip["count"] >= 3:
                diagnostic_parts.append(
                    f"Repeated security activity: {top_ip['count']} events originating from {top_ip['ip']}."
                )
            else:
                diagnostic_parts.append(
                    f"Security activity detected from {top_ip['ip']} ({top_ip['count']} events)."
                )
    
    if counts["security"] == 0 and counts["critical"] == 0 and counts["warning"] == 0:
        diagnostic_parts.append(f"All {total} analyzed logs are routine background operational events. Zero anomalies detected.")
    elif counts["routine"] > 0:
        diagnostic_parts.append(f"{counts['routine']} routine background event(s) suppressed from default attention view.")
        
    diagnostic = " ".join(diagnostic_parts) if diagnostic_parts else "Analysis complete."
    
    if counts["security"] > 0 or counts["critical"] > 0:
        severity = "critical"
    elif counts["warning"] > 0 or counts["uncertain"] > 0:
        severity = "warning"
    else:
        severity = "healthy"
        
    return TriageSummary(
        total_logs=total,
        latency_ms=elapsed_ms,
        counts=counts,
        top_ips=top_ips,
        diagnostic=diagnostic,
        severity=severity
    )

@app.post("/feedback")
def submit_feedback(request: FeedbackRequest):
    save_feedback(request.log_id, request.message, request.predicted_category, request.true_category)
    return {"status": "feedback_saved"}

