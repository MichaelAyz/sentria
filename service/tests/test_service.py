import pytest
from fastapi.testclient import TestClient
from service.main import app, THRESHOLD_NEEDS_REVIEW

client = TestClient(app)

class MockModelService:
    version = "test-sha-1234"

    def is_loaded(self):
        return True
        
    def load(self):
        pass

    def warm(self):
        pass
    
    def predict(self, messages):
        results = []
        for msg in messages:
            if "boundary_exact" in msg:
                results.append({"category": "noise", "confidence": THRESHOLD_NEEDS_REVIEW})
            elif "boundary_below" in msg:
                results.append({"category": "error", "confidence": THRESHOLD_NEEDS_REVIEW - 0.01})
            elif "boundary_above" in msg:
                results.append({"category": "security", "confidence": THRESHOLD_NEEDS_REVIEW + 0.01})
            else:
                results.append({"category": "noise", "confidence": 0.99})
        return results

@pytest.fixture(autouse=True)
def override_model_service(monkeypatch):
    monkeypatch.setattr("service.main.model_service", MockModelService())

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_loaded": True, "model_version": "test-sha-1234"}

def test_health_check_not_loaded(monkeypatch):
    class UnloadedMock:
        def is_loaded(self): return False
        def load(self): pass
        version = "unknown"
    monkeypatch.setattr("service.main.model_service", UnloadedMock())
    response = client.get("/health")
    assert response.status_code == 503

def test_classify_and_feedback():
    with TestClient(app) as client:
        payload = {
            "logs": [
                {"timestamp": "2026-07-18T10:00:00Z", "source": "test", "level": "INFO", "message": "hello world"}
            ]
        }
        response = client.post("/classify", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        result = data["results"][0]
        
        assert "log_id" in result
        assert result["category"] == "noise"
        assert result["confidence"] == 0.99
        assert result["needs_review"] is False
        
        feedback_payload = {
            "log_id": result["log_id"],
            "message": "hello world",
            "predicted_category": "noise",
            "true_category": "noise"
        }
        fb_response = client.post("/feedback", json=feedback_payload)
        assert fb_response.status_code == 200

def test_needs_review_boundaries():
    payload = {
        "logs": [
            {"timestamp": "t", "source": "s", "level": "I", "message": "boundary_exact"},
            {"timestamp": "t", "source": "s", "level": "I", "message": "boundary_below"},
            {"timestamp": "t", "source": "s", "level": "I", "message": "boundary_above"}
        ]
    }
    response = client.post("/classify", json=payload)
    results = response.json()["results"]
    
    assert results[0]["confidence"] == THRESHOLD_NEEDS_REVIEW
    assert results[0]["needs_review"] is False
    
    assert results[1]["confidence"] < THRESHOLD_NEEDS_REVIEW
    assert results[1]["needs_review"] is True
    
    assert results[2]["confidence"] > THRESHOLD_NEEDS_REVIEW
    assert results[2]["needs_review"] is False

def test_ui_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "Sentria" in response.text

def test_stats_endpoint():
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "OPERATIONAL"
    assert "feedbacks_collected" in data
    assert "model_version" in data

def test_classify_empty_logs():
    response = client.post("/classify", json={"logs": []})
    assert response.status_code == 200
    assert response.json()["results"] == []

def test_reload_endpoint():
    response = client.get("/reload")
    assert response.status_code == 200
    assert response.json()["status"] == "reloaded"

def test_classify_triage_summary():
    payload = {
        "logs": [
            {"timestamp": "2026-09-14T00:00:01Z", "source": "ssh", "level": "WARN", "message": "Failed password for root from 192.168.1.50"},
            {"timestamp": "2026-09-14T00:00:02Z", "source": "ssh", "level": "WARN", "message": "Failed password for admin from 192.168.1.50"}
        ]
    }
    response = client.post("/classify", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "triage_summary" in data
    summary = data["triage_summary"]
    assert summary["total_logs"] == 2
    assert "counts" in summary
    assert "diagnostic" in summary
    assert "severity" in summary

def test_real_model_inference_accuracy():
    import os
    from service.model import ModelService
    
    model_path = os.path.join(os.path.dirname(__file__), "..", "linear_head.joblib")
    if not os.path.exists(model_path):
        pytest.skip("Linear head artifact not found for real-model test")
        
    real_service = ModelService(linear_head_path=model_path)
    real_service.load()
    
    samples = [
        ("Failed password for root from 10.0.0.1 port 22 ssh2", "security"),
        ("Invalid user admin from 10.0.0.2", "security"),
        ("FATAL: remaining connection slots are reserved", "error"),
        ("OutOfMemoryError in PaymentProcessor", "error"),
        ("DiskFullException: No space left on device", "error"),
        ("Slow query execution 3200ms on orders", "warning"),
        ("Connection pool near capacity (92% utilization)", "warning"),
        ("GET /index.html 200 OK 12ms", "noise"),
        ("Health check passed on /health 200 OK", "noise"),
        ("Started Session 1234 of user root.", "noise")
    ]
    
    messages = [s[0] for s in samples]
    expected = [s[1] for s in samples]
    
    predictions = real_service.predict(messages)
    correct = sum(1 for pred, exp in zip(predictions, expected) if pred["category"] == exp)
    accuracy = correct / len(samples)
    
    assert accuracy >= 0.80, f"Model accuracy {accuracy:.1%} below 80% threshold"


def test_ingest_raw_text_plain():
    raw_text = "GET /index.html 200 OK 12ms\nGET /health 200 OK"
    response = client.post(
        "/ingest/raw",
        content=raw_text,
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 2
    assert data["results"][0]["source"] == "raw"
    assert data["triage_summary"] is not None


def test_ingest_raw_json():
    payload = {
        "raw": "FATAL: database connection failed\n502 Bad Gateway",
        "source": "auth-service"
    }
    response = client.post(
        "/ingest/raw",
        json=payload
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 2
    assert data["results"][0]["source"] == "auth-service"


def test_ingest_raw_empty():
    response = client.post(
        "/ingest/raw",
        content="   \n\n   ",
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 400
    assert "No log content provided" in response.json()["detail"]


def test_ingest_raw_multiline_stitching():
    traceback_log = (
        "Traceback (most recent call last):\n"
        "  File \"app.py\", line 42, in handle_request\n"
        "    raise DatabaseError('connection timed out')\n"
        "DatabaseError: connection timed out\n"
        "GET /index.html 200 OK"
    )
    response = client.post(
        "/ingest/raw",
        content=traceback_log,
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 200
    data = response.json()
    # The traceback should be stitched into 1 entry, plus the 200 OK -> 2 total
    assert len(data["results"]) == 2
    assert "Traceback" in data["results"][0]["message"]
    assert "DatabaseError" in data["results"][0]["message"]


def test_ingest_raw_source_query_param():
    raw_text = "GET /api/v1/users 200 OK 45ms"
    response = client.post(
        "/ingest/raw?source=k8s-ingress",
        content=raw_text,
        headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["source"] == "k8s-ingress"
