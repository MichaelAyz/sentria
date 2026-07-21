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
