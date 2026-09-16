import re
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

ISO_PATTERN = re.compile(
    r'(?P<iso>\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)'
)
SYSLOG_PATTERN = re.compile(
    r'(?P<syslog>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})'
)
APACHE_PATTERN = re.compile(
    r'\[?(?P<apache>\d{2}/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/\d{4}:\d{2}:\d{2}:\d{2}(?:\s*[+-]\d{4})?)\]?'
)
REDIS_PATTERN = re.compile(
    r'(?P<redis>\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)'
)
EPOCH_PATTERN = re.compile(
    r'(?:^|[^\d])(?P<epoch>\d{10}(?:\.\d{1,6})?)(?:[^\d]|$)'
)

IP_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
KV_SERVICE_PATTERN = re.compile(r'\b(?:service|container|app)=([a-zA-Z0-9_\-\.]+)\b', re.IGNORECASE)
SYSLOG_SERVICE_PATTERN = re.compile(r'(?:[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}\s+[\w\-\.]+\s+)([a-zA-Z0-9_\-\.]+)(?:\[\d+\])?:')
KNOWN_SERVICES = ['postgresql', 'postgres', 'redis', 'nginx', 'apache', 'nextjs', 'node', 'mysql', 'sshd', 'dockerd', 'docker', 'systemd', 'kernel']

INFRA_KEYWORDS = [
    'fatal', 'oom', 'out of memory', 'panic', 'segfault', 'database', 'deadlock',
    'connection pool', 'connection limit', 'no space left', 'disk full',
    'killed process', 'core dump', 'failed password', 'unauthorized', 'break-in',
    'injection', 'attack', 'too many clients'
]
SYMPTOM_KEYWORDS = [
    '502 bad gateway', '504 gateway timeout', '500 internal server error',
    'upstream timed out', 'connection refused', 'broken pipe', 'retry'
]


class IncidentEvent(BaseModel):
    timestamp: str
    epoch_ts: float
    source: str
    category: str
    confidence: float
    message: str


class RootCause(BaseModel):
    event: IncidentEvent
    reason: str


class Incident(BaseModel):
    incident_id: str
    title: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    category: str  # "error", "security", "warning"
    start_time: str
    end_time: str
    duration_seconds: float
    root_cause: RootCause
    affected_services: List[str]
    event_count: int
    timeline: List[IncidentEvent]
    remediation: str
    entities: Dict[str, Any]


class TimestampParser:
    @staticmethod
    def parse(text: str, fallback_ts: Optional[str] = None, default_year: int = 2026) -> float:
        for candidate in [text, fallback_ts]:
            if not candidate:
                continue
            # 1. ISO-8601
            m = ISO_PATTERN.search(candidate)
            if m:
                val = m.group('iso').replace('Z', '+00:00').replace(' ', 'T')
                try:
                    dt = datetime.fromisoformat(val)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except Exception:
                    pass
            # 2. Redis
            m = REDIS_PATTERN.search(candidate)
            if m:
                try:
                    dt = datetime.strptime(m.group('redis'), "%d %b %Y %H:%M:%S.%f").replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except Exception:
                    pass
            # 3. Apache/Nginx
            m = APACHE_PATTERN.search(candidate)
            if m:
                try:
                    parts = m.group('apache').strip().split()
                    dt = datetime.strptime(parts[0], "%d/%b/%Y:%H:%M:%S").replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except Exception:
                    pass
            # 4. Syslog
            m = SYSLOG_PATTERN.search(candidate)
            if m:
                try:
                    parts = m.group('syslog').split()
                    norm = f"{default_year} {parts[0]} {int(parts[1]):02d} {parts[2]}"
                    dt = datetime.strptime(norm, "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except Exception:
                    pass
            # 5. Epoch timestamp
            m = EPOCH_PATTERN.search(candidate)
            if m:
                try:
                    return float(m.group('epoch'))
                except Exception:
                    pass
        return 0.0


class EntityExtractor:
    @staticmethod
    def extract(message: str, source: Optional[str] = None) -> Dict[str, Any]:
        ips = set()
        for ip in IP_PATTERN.findall(message):
            if not (ip.startswith("0.") or ip == "0.0.0.0" or ip == "127.0.0.1"):
                ips.add(ip)
                
        service = None
        if source and source.lower() not in ("default-source", "unknown", "test", "s"):
            service = source.lower()
            
        if not service:
            m = KV_SERVICE_PATTERN.search(message)
            if m:
                service = m.group(1).lower()
                
        if not service:
            m = SYSLOG_SERVICE_PATTERN.search(message)
            if m:
                service = m.group(1).lower()
                
        if not service:
            msg_lower = message.lower()
            for s in KNOWN_SERVICES:
                if s in msg_lower:
                    service = "postgresql" if s == "postgres" else s
                    break
                    
        if not service:
            service = (source if source and source != "default-source" else "system").lower()
            
        return {
            "ips": sorted(list(ips)),
            "service": service
        }


def get_remediation_advice(root_cause_msg: str) -> str:
    msg = root_cause_msg.lower()
    if any(k in msg for k in ['connection limit', 'pool exhausted', 'too many clients']):
        return "Increase database max_connections or pool size, implement connection pooling (e.g. PgBouncer), and investigate potential connection leaks."
    if any(k in msg for k in ['out of memory', 'oom', 'cannot allocate', 'killed process']):
        return "Increase memory allocation for the container/process, audit memory leak profiles, and review memory-intensive queries or cache allocations."
    if any(k in msg for k in ['no space left', 'disk full', 'disk space']):
        return "Expand storage volume immediately, purge rotated/debug logs, and configure automated log pruning policies."
    if any(k in msg for k in ['failed password', 'invalid user', 'brute force']):
        return "Rate-limit or block offending IP at edge firewall/WAF, enable fail2ban, and enforce mandatory MFA."
    if any(k in msg for k in ['injection', 'xss', 'traversal', 'attack']):
        return "Block malicious source IP at WAF, sanitize and parameterize all input queries, and review target endpoint access control."
    if any(k in msg for k in ['502', 'connection refused', 'upstream timed out']):
        return "Verify upstream backend health, restart failed upstream service instances, and verify ingress/proxy configuration."
    return "Inspect service logs and system metrics around the root cause timestamp to identify resource constraints or unhandled exceptions."


class IncidentGrouper:
    def __init__(self, window_seconds: float = 120.0):
        self.window_seconds = window_seconds

    def analyze(self, results: List[Any], fallback_timestamps: Optional[List[str]] = None) -> List[Incident]:
        """
        Groups anomalous log events within a temporal window and returns structured Incidents.
        """
        # 1. Filter anomalous events (noise routine traffic is excluded from incidents)
        anomalous_items = []
        for idx, r in enumerate(results):
            cat = getattr(r, 'category', r.get('category') if isinstance(r, dict) else None)
            if cat not in ('error', 'warning', 'security'):
                continue
            
            msg = getattr(r, 'message', r.get('message') if isinstance(r, dict) else "") or ""
            src = getattr(r, 'source', r.get('source') if isinstance(r, dict) else None)
            conf = float(getattr(r, 'confidence', r.get('confidence') if isinstance(r, dict) else 1.0))
            log_id = getattr(r, 'log_id', r.get('log_id') if isinstance(r, dict) else str(uuid.uuid4()))
            fb_ts = fallback_timestamps[idx] if fallback_timestamps and idx < len(fallback_timestamps) else getattr(r, 'timestamp', None)
            
            ts = TimestampParser.parse(msg, fallback_ts=fb_ts)
            entities = EntityExtractor.extract(msg, src)
            
            anomalous_items.append({
                "log_id": log_id,
                "epoch_ts": ts,
                "orig_index": idx,
                "category": cat,
                "confidence": conf,
                "message": msg,
                "source": entities["service"],
                "ips": entities["ips"]
            })
            
        if len(anomalous_items) < 2:
            return []

        # 2. Assign synthetic timestamps if all timestamps were 0 (i.e. no timestamp in logs)
        has_any_real_ts = any(item["epoch_ts"] > 0 for item in anomalous_items)
        if not has_any_real_ts:
            base_now = 1789466400.0
            for i, item in enumerate(anomalous_items):
                item["epoch_ts"] = base_now + (i * 0.5)

        # 3. Sort chronologically
        anomalous_items.sort(key=lambda x: (x["epoch_ts"], x["orig_index"]))

        # 4. Sliding-window clustering with entity bridging
        clusters: List[List[Dict[str, Any]]] = []
        current_cluster: List[Dict[str, Any]] = []
        cluster_ips = set()
        last_ts = 0.0

        for item in anomalous_items:
            if not current_cluster:
                current_cluster.append(item)
                last_ts = item["epoch_ts"]
                cluster_ips.update(item["ips"])
                continue

            dt = item["epoch_ts"] - last_ts
            shares_ip = bool(set(item["ips"]) & cluster_ips)

            within_window = dt <= self.window_seconds
            within_bridge_window = dt <= (self.window_seconds * 2.5) and shares_ip

            if within_window or within_bridge_window:
                current_cluster.append(item)
                last_ts = max(last_ts, item["epoch_ts"])
                cluster_ips.update(item["ips"])
            else:
                if len(current_cluster) >= 2:
                    clusters.append(current_cluster)
                current_cluster = [item]
                last_ts = item["epoch_ts"]
                cluster_ips = set(item["ips"])

        if len(current_cluster) >= 2:
            clusters.append(current_cluster)

        # 5. Build Incident objects
        incidents: List[Incident] = []
        for cluster in clusters:
            incidents.append(self._build_incident(cluster))

        return incidents

    def _build_incident(self, events: List[Dict[str, Any]]) -> Incident:
        error_or_sec = [e for e in events if e["category"] in ("error", "security")]
        candidates = error_or_sec if error_or_sec else events

        earliest = candidates[0]
        root_cause_event = earliest
        reason = "Initial anomalous event observed in incident timeline."

        # Infrastructure tiebreaker: if symptoms occur near core failure, prefer core failure
        earliest_window_events = [e for e in candidates if (e["epoch_ts"] - earliest["epoch_ts"]) <= 5.0]
        for e in earliest_window_events:
            msg_lower = e["message"].lower()
            if any(k in msg_lower for k in INFRA_KEYWORDS):
                if not any(k in root_cause_event["message"].lower() for k in INFRA_KEYWORDS):
                    root_cause_event = e
                    reason = "Primary infrastructure/resource trigger identified prior to downstream symptoms."
                    break

        affected_services = sorted(list(set(e["source"] for e in events)))
        all_ips = sorted(list(set(ip for e in events for ip in e["ips"])))
        has_error = any(e["category"] == "error" for e in events)
        has_sec = any(e["category"] == "security" for e in events)

        if len(affected_services) >= 3 or (has_error and has_sec):
            severity = "CRITICAL"
        elif has_error or has_sec:
            severity = "HIGH"
        else:
            severity = "MEDIUM"

        rc_msg = root_cause_event["message"]
        clean_rc = re.sub(r'^\s*(?:\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[^\s]*|[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})\s*', '', rc_msg)
        clean_rc = clean_rc.strip()
        if len(clean_rc) > 65:
            clean_rc = clean_rc[:62] + "..."
            
        if len(affected_services) > 1:
            title = f"{clean_rc} -> Cascading failure across {len(affected_services)} services"
        elif all_ips and has_sec:
            title = f"Security probe / repeated attack from {all_ips[0]} ({len(events)} events)"
        else:
            title = f"{clean_rc} ({len(events)} correlated events)"

        start_epoch = events[0]["epoch_ts"]
        end_epoch = events[-1]["epoch_ts"]
        duration = round(end_epoch - start_epoch, 2)

        start_iso = datetime.fromtimestamp(start_epoch, tz=timezone.utc).isoformat()
        end_iso = datetime.fromtimestamp(end_epoch, tz=timezone.utc).isoformat()

        timeline: List[IncidentEvent] = []
        for e in events:
            timeline.append(IncidentEvent(
                timestamp=datetime.fromtimestamp(e["epoch_ts"], tz=timezone.utc).isoformat(),
                epoch_ts=e["epoch_ts"],
                source=e["source"],
                category=e["category"],
                confidence=e["confidence"],
                message=e["message"]
            ))

        remediation = get_remediation_advice(root_cause_event["message"])

        rc_model = RootCause(
            event=IncidentEvent(
                timestamp=datetime.fromtimestamp(root_cause_event["epoch_ts"], tz=timezone.utc).isoformat(),
                epoch_ts=root_cause_event["epoch_ts"],
                source=root_cause_event["source"],
                category=root_cause_event["category"],
                confidence=root_cause_event["confidence"],
                message=root_cause_event["message"]
            ),
            reason=reason
        )

        return Incident(
            incident_id=f"inc-{uuid.uuid4().hex[:8]}",
            title=title,
            severity=severity,
            category="security" if has_sec and not has_error else "error" if has_error else "warning",
            start_time=start_iso,
            end_time=end_iso,
            duration_seconds=duration,
            root_cause=rc_model,
            affected_services=affected_services,
            event_count=len(events),
            timeline=timeline,
            remediation=remediation,
            entities={
                "ips": all_ips,
                "services": affected_services
            }
        )
