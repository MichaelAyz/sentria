import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from service.main import app
from service.incidents import (
    TimestampParser,
    EntityExtractor,
    IncidentGrouper,
    get_remediation_advice
)

class MockIncidentModelService:
    version = "test-inc-1234"

    def is_loaded(self):
        return True

    def load(self):
        pass

    def warm(self):
        pass

    def predict(self, messages):
        results = []
        for msg in messages:
            m = msg.lower()
            if any(k in m for k in ['fatal', 'error', '502', 'exception', 'exhausted', 'databaseerror']):
                results.append({"category": "error", "confidence": 0.95})
            elif any(k in m for k in ['failed password', 'unauthorized', 'attack']):
                results.append({"category": "security", "confidence": 0.95})
            elif any(k in m for k in ['warn', 'health check failed']):
                results.append({"category": "warning", "confidence": 0.90})
            else:
                results.append({"category": "noise", "confidence": 0.99})
        return results

@pytest.fixture(autouse=True)
def override_model_service(monkeypatch):
    monkeypatch.setattr("service.main.model_service", MockIncidentModelService())

client = TestClient(app)

def test_timestamp_parser_all_formats():
    # 1. ISO-8601
    ts_iso = TimestampParser.parse("2026-09-15T10:00:00Z FATAL error occurred")
    assert ts_iso > 0
    dt_iso = datetime.fromtimestamp(ts_iso, tz=timezone.utc)
    assert dt_iso.year == 2026 and dt_iso.month == 9 and dt_iso.day == 15 and dt_iso.hour == 10

    # 2. Syslog RFC 3164
    ts_syslog = TimestampParser.parse("Sep 15 07:32:10 LabSZ sshd[24206]: Failed password")
    assert ts_syslog > 0
    dt_syslog = datetime.fromtimestamp(ts_syslog, tz=timezone.utc)
    assert dt_syslog.month == 9 and dt_syslog.day == 15 and dt_syslog.hour == 7 and dt_syslog.minute == 32

    # 3. Apache/Nginx combined
    ts_apache = TimestampParser.parse('192.168.1.1 - - [15/Sep/2026:07:32:10 +0000] "GET /admin HTTP/1.1" 500')
    assert ts_apache > 0
    dt_apache = datetime.fromtimestamp(ts_apache, tz=timezone.utc)
    assert dt_apache.year == 2026 and dt_apache.month == 9 and dt_apache.day == 15

    # 4. Redis log
    ts_redis = TimestampParser.parse("15 Sep 2026 07:32:31.457 # Warning: no config file specified")
    assert ts_redis > 0
    dt_redis = datetime.fromtimestamp(ts_redis, tz=timezone.utc)
    assert dt_redis.year == 2026 and dt_redis.second == 31

    # 5. Unix epoch
    ts_epoch = TimestampParser.parse("1726385530.123 event happened")
    assert abs(ts_epoch - 1726385530.123) < 0.001

    # 6. Fallback timestamp
    ts_fallback = TimestampParser.parse("Message with no time", fallback_ts="2026-09-15T12:00:00Z")
    assert ts_fallback > 0
    dt_fb = datetime.fromtimestamp(ts_fallback, tz=timezone.utc)
    assert dt_fb.hour == 12

    # 7. No timestamp anywhere
    ts_none = TimestampParser.parse("Just a message without any timestamp")
    assert ts_none == 0.0


def test_entity_extractor():
    # Extracts IP and excludes localhost
    res1 = EntityExtractor.extract("Attack from 192.168.1.99 and 127.0.0.1", source="firewall")
    assert res1["ips"] == ["192.168.1.99"]
    assert res1["service"] == "firewall"

    # Extracts service from key-value pair
    res2 = EntityExtractor.extract('level=error container=payment-api msg="db error"')
    assert res2["service"] == "payment-api"

    # Extracts service from syslog tag
    res3 = EntityExtractor.extract("Sep 15 07:32:10 LabSZ sshd[24206]: Failed password for root")
    assert res3["service"] == "sshd"

    # Identifies postgres keyword
    res4 = EntityExtractor.extract("FATAL: terminating postgres connection due to administrator command")
    assert res4["service"] == "postgresql"


def test_cascading_failure_clustering_and_rca():
    grouper = IncidentGrouper(window_seconds=120)

    payload = [
        {"category": "error", "source": "postgresql", "message": "2026-09-15T10:00:00Z FATAL: sorry, too many clients already", "confidence": 0.98},
        {"category": "error", "source": "nextjs", "message": "2026-09-15T10:00:05Z DatabaseError: connection pool exhausted after 30000ms", "confidence": 0.95},
        {"category": "error", "source": "nginx", "message": "2026-09-15T10:00:06Z 502 Bad Gateway while connecting to upstream", "confidence": 0.92},
        {"category": "noise", "source": "nginx", "message": "2026-09-15T10:00:15Z GET /health 200 0.001", "confidence": 0.99},
        {"category": "warning", "source": "monitor", "message": "2026-09-15T10:00:20Z Health check failed for service nextjs: connection refused", "confidence": 0.88}
    ]

    incidents = grouper.analyze(payload)
    assert len(incidents) == 1

    inc = incidents[0]
    assert "cascading" in inc.title.lower() or "clients" in inc.title.lower()
    assert inc.severity == "CRITICAL"  # >= 3 services
    assert set(inc.affected_services) == {"postgresql", "nextjs", "nginx", "monitor"}
    assert inc.event_count == 4  # Noise log was properly excluded
    assert len(inc.timeline) == 4
    assert inc.duration_seconds == 20.0

    # Verify root cause
    assert inc.root_cause.event.source == "postgresql"
    assert "too many clients" in inc.root_cause.event.message
    assert "pool" in inc.remediation.lower() or "connection" in inc.remediation.lower()


def test_time_window_separation():
    grouper = IncidentGrouper(window_seconds=120)

    # Cluster 1 at 10:00:00, Cluster 2 at 10:30:00 (30 minutes later)
    payload = [
        {"category": "error", "source": "db", "message": "2026-09-15T10:00:00Z OutOfMemoryError in buffer pool", "confidence": 0.99},
        {"category": "error", "source": "app", "message": "2026-09-15T10:00:10Z connection refused", "confidence": 0.95},
        {"category": "security", "source": "sshd", "message": "2026-09-15T10:30:00Z Failed password for root from 10.10.10.5", "confidence": 0.99},
        {"category": "security", "source": "sshd", "message": "2026-09-15T10:30:04Z Failed password for admin from 10.10.10.5", "confidence": 0.99}
    ]

    incidents = grouper.analyze(payload)
    assert len(incidents) == 2
    assert incidents[0].category == "error"
    assert incidents[1].category == "security"


def test_entity_bridging():
    grouper = IncidentGrouper(window_seconds=120)

    # Events separated by 180s (>120s default), but from the same attacker IP
    payload = [
        {"category": "security", "source": "auth", "message": "2026-09-15T10:00:00Z Failed password from 198.51.100.44", "confidence": 0.95},
        {"category": "security", "source": "nginx", "message": "2026-09-15T10:03:00Z 401 Unauthorized for /api/admin from 198.51.100.44", "confidence": 0.92}
    ]

    incidents = grouper.analyze(payload)
    assert len(incidents) == 1
    assert "198.51.100.44" in incidents[0].entities["ips"]


def test_edge_cases():
    grouper = IncidentGrouper(window_seconds=120)

    # 1. Single anomalous event does not constitute a cascading cluster
    single = [{"category": "error", "source": "app", "message": "Single crash", "confidence": 0.9}]
    assert len(grouper.analyze(single)) == 0

    # 2. All noise produces 0 incidents
    noise = [
        {"category": "noise", "source": "app", "message": "200 OK", "confidence": 0.99},
        {"category": "noise", "source": "app", "message": "health check passed", "confidence": 0.99}
    ]
    assert len(grouper.analyze(noise)) == 0

    # 3. Empty list produces 0 incidents
    assert len(grouper.analyze([])) == 0


def test_classify_endpoint_with_incidents():
    # Multi-event cascading error payload
    payload = {
        "logs": [
            {"timestamp": "2026-09-15T10:00:00Z", "source": "postgresql", "level": "FATAL", "message": "FATAL: connection limit exceeded for non-superusers"},
            {"timestamp": "2026-09-15T10:00:02Z", "source": "app-api", "level": "ERROR", "message": "DatabaseError: connection pool exhausted"},
            {"timestamp": "2026-09-15T10:00:05Z", "source": "nginx", "level": "ERROR", "message": "502 Bad Gateway upstream server unavailable"},
            {"timestamp": "2026-09-15T10:00:10Z", "source": "nginx", "level": "INFO", "message": "GET /health 200 0.002"}
        ]
    }

    response = client.post("/classify", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "results" in data
    assert "triage_summary" in data
    assert "incidents" in data
    assert data["incidents"] is not None
    assert len(data["incidents"]) == 1

    incident = data["incidents"][0]
    assert incident["severity"] in ("CRITICAL", "HIGH")
    assert incident["event_count"] == 3  # The 200 log is noise
    assert "root_cause" in incident
    assert incident["root_cause"]["event"]["source"] == "postgresql"
    assert "affected_services" in incident
    assert "remediation" in incident


def test_classify_endpoint_routine_has_no_incidents():
    payload = {
        "logs": [
            {"timestamp": "2026-09-15T10:00:00Z", "source": "nginx", "level": "INFO", "message": "GET /api/v1/status 200 0.012"},
            {"timestamp": "2026-09-15T10:00:01Z", "source": "nginx", "level": "INFO", "message": "GET /health 200 0.001"}
        ]
    }

    response = client.post("/classify", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data.get("incidents") is None
