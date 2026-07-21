import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

from .model import ModelService
from .metrics import MetricsMiddleware, MODEL_LOADED, INFERENCE_REQUESTS, INFERENCE_CONFIDENCE
from .feedback import setup_database, save_feedback

THRESHOLD_NEEDS_REVIEW = 0.75
MODEL_PATH = "service/model.joblib"

model_service = ModelService(model_path=MODEL_PATH)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Process will crash if this fails
    model_service.load()
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

class ClassifyResponse(BaseModel):
    results: List[ClassificationResult]

class FeedbackRequest(BaseModel):
    log_id: str
    message: str
    predicted_category: str
    true_category: str

@app.get("/health")
def health_check():
    if not model_service.is_loaded():
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ok", "model_loaded": True, "model_version": model_service.version}

@app.post("/classify", response_model=ClassifyResponse)
def classify_logs(request: ClassifyRequest):
    messages = [log.message for log in request.logs]
    
    try:
        predictions = model_service.predict(messages)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
        
    results = []
    for pred in predictions:
        log_id = str(uuid.uuid4())
        needs_review = pred["confidence"] < THRESHOLD_NEEDS_REVIEW
        
        INFERENCE_REQUESTS.labels(category=pred["category"], status_code="200").inc()
        INFERENCE_CONFIDENCE.observe(pred["confidence"])
        
        results.append(ClassificationResult(
            log_id=log_id,
            category=pred["category"],
            confidence=pred["confidence"],
            needs_review=needs_review
        ))
        
    return ClassifyResponse(results=results)

@app.post("/feedback")
def submit_feedback(request: FeedbackRequest):
    save_feedback(request.log_id, request.message, request.predicted_category, request.true_category)
    return {"status": "feedback_saved"}
