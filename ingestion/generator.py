import argparse
import csv
import time
import random
import requests
from datetime import datetime, timezone

def get_ip(): return f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
def get_user(): return random.choice(["admin", "user_19", "guest", "system", "app_svc", "db_admin", f"usr_{random.randint(100,999)}"])
def get_resource(): return random.choice(["/index.html", "/api/v1/users", "/admin/settings", "/var/log/syslog", "auth_db", "payment_gateway", f"/static/img_{random.randint(1,50)}.png"])
def get_port(): return random.randint(1024, 65535)

def gen_noise():
    if random.random() < 0.20:
        return f"Connection reset for session on {get_resource()}"
    verbs = ["GET", "POST", "PUT", "Background sync", "Health check", "Session refreshed", "Cache populated"]
    return f"{random.choice(verbs)} {get_resource()} {random.choice([200, 201, 204, 301])} for {get_user()} from {get_ip()}:{get_port()}"

def gen_error():
    if random.random() < 0.20:
        return f"Repeated request pattern detected from {get_ip()}"
    errors = ["ConnectionTimeout", "NullPointerException", "OutOfMemoryError", "DiskFullException", "DatabaseLockError", "TimeoutException", "IOException"]
    components = ["PaymentProcessor", "AuthService", "UserDb", "CacheNode", "MessageQueue", "S3Client"]
    return f"{random.choice(errors)} in {random.choice(components)} while accessing {get_resource()}"

def gen_security():
    if random.random() < 0.20:
        return f"Unexpected parameter format from {get_ip()} on {get_resource()}"
    actions = ["Failed login attempt", "SQL injection payload detected", "Unauthorized access", "Invalid token signature", "Brute force pattern", "Directory traversal attempt"]
    return f"{random.choice(actions)} for {get_user()} from {get_ip()} targeting {get_resource()}"

def gen_warning():
    if random.random() < 0.20:
        return f"Access denied for {get_user()} on {get_resource()}"
    issues = ["Rate limit approaching", "High memory utilization", "Slow query execution", "Retrying failed request", "Connection pool near capacity"]
    return f"{random.choice(issues)} for {get_user()}: {random.randint(1500, 5000)}ms latency on {get_resource()}"

def generate_log():
    category = random.choices(["noise", "error", "security", "warning"], weights=[0.7, 0.15, 0.05, 0.1])[0]
    
    if category == "noise":
        message = gen_noise()
    elif category == "error":
        message = gen_error()
    elif category == "security":
        message = gen_security()
    else:
        message = gen_warning()
        
    log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": random.choice(["api_gateway", "auth_service", "db_primary"]),
        "level": "INFO" if category == "noise" else category.upper(),
        "message": message,
        "true_label": category
    }
    return log

def run_batch(output_file, count):
    logs = [generate_log() for _ in range(count)]
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "source", "level", "message", "true_label"])
        writer.writeheader()
        writer.writerows(logs)
    print(f"Generated {count} logs to {output_file}")

def run_streaming(target_url, batch_size, interval):
    print(f"Streaming {batch_size} logs every {interval}s to {target_url}...")
    while True:
        logs = [generate_log() for _ in range(batch_size)]
        # Strip true_label for realistic production payload
        payload = [{"timestamp": l["timestamp"], "source": l["source"], "level": l["level"], "message": l["message"]} for l in logs]
        
        try:
            resp = requests.post(target_url, json={"logs": payload})
            print(f"Sent {batch_size} logs, status: {resp.status_code}")
            if resp.status_code == 200:
                print(resp.json())
        except Exception as e:
            print(f"Failed to send logs: {e}")
            
        time.sleep(interval)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["batch", "streaming"], required=True)
    parser.add_argument("--output", default="data.csv", help="Output CSV file for batch mode")
    parser.add_argument("--count", type=int, default=1000, help="Number of logs for batch mode")
    parser.add_argument("--url", default="http://localhost:8000/classify", help="Target URL for streaming mode")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for streaming")
    parser.add_argument("--interval", type=float, default=2.0, help="Interval in seconds for streaming")
    args = parser.parse_args()

    if args.mode == "batch":
        run_batch(args.output, args.count)
    else:
        run_streaming(args.url, args.batch_size, args.interval)
