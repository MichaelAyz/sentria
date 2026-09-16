# Sentria Log Ingestion Recipes

Sentria provides a raw ingestion endpoint at `POST /ingest/raw` that accepts multi-line log streams, automatic stack trace stitching, and dynamic incident clustering without requiring pre-formatted JSON structures.

---

## 1. Quick Ingestion with cURL

### Plaintext Streaming
```bash
curl -X POST "http://localhost:8000/ingest/raw?source=production-api" \
  -H "Content-Type: text/plain" \
  --data-binary @/var/log/nginx/error.log
```

### Direct String Ingestion
```bash
curl -X POST "http://localhost:8000/ingest/raw?source=auth-service" \
  -H "Content-Type: text/plain" \
  -d $'FATAL: database connection pool exhausted\n502 Bad Gateway while connecting to upstream'
```

### JSON Raw Payload
```bash
curl -X POST "http://localhost:8000/ingest/raw" \
  -H "Content-Type: application/json" \
  -d '{
    "raw": "FATAL: terminating connection\n502 Bad Gateway",
    "source": "payment-service"
  }'
```

---

## 2. Fluent Bit Recipe

Copy `fluent-bit.conf` into your Fluent Bit configuration directory (e.g., `/etc/fluent-bit/fluent-bit.conf`):

```ini
[SERVICE]
    Flush        1
    Daemon       Off
    Log_Level    info

[INPUT]
    Name         tail
    Path         /var/log/syslog,/var/log/nginx/*.log
    Tag          production.logs
    Refresh_Interval 2

[OUTPUT]
    Name         http
    Match        *
    Host         127.0.0.1
    Port         8000
    URI          /ingest/raw?source=fluentbit
    Format       raw
    Header       Content-Type text/plain
```

---

## 3. Vector Recipe

Add to your `vector.toml`:

```toml
[sources.system_logs]
type = "file"
include = ["/var/log/*.log", "/var/log/syslog"]
read_from = "beginning"

[sinks.sentria]
type = "http"
inputs = ["system_logs"]
uri = "http://127.0.0.1:8000/ingest/raw?source=vector"
method = "post"

[sinks.sentria.encoding]
codec = "raw_message"

[sinks.sentria.request.headers]
"Content-Type" = "text/plain"

[sinks.sentria.batch]
max_events = 50
timeout_secs = 2
```

---

## 4. Logstash Recipe

Add to your Logstash pipeline (`logstash.conf`):

```ruby
input {
  file {
    path => [ "/var/log/syslog", "/var/log/**/*.log" ]
    start_position => "beginning"
  }
}

output {
  http {
    url => "http://127.0.0.1:8000/ingest/raw?source=logstash"
    http_method => "post"
    content_type => "text/plain"
    format => "message"
  }
}
```

---

## Response Structure

The endpoint returns the standard `ClassifyResponse` containing:
- `results`: Individual classified log records with confidence and flags.
- `triage_summary`: Aggregated diagnostics, IP telemetry, and category counts.
- `incidents`: Correlated temporal clusters and root cause diagnosis when $\ge 2$ anomalous events occur within the temporal window ($\Delta T = 120s$).
