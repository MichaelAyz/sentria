import csv
import os
import random

OUTPUT_FILE = "training/data/train_logs.csv"

# Real-world log templates across categories
SECURITY_TEMPLATES = [
    "Dec 10 06:55:46 LabSZ sshd[{pid}]: reverse mapping checking getaddrinfo for {host} [{ip}] failed - POSSIBLE BREAK-IN ATTEMPT!",
    "Dec 10 06:55:46 LabSZ sshd[{pid}]: Invalid user {user} from {ip}",
    "Dec 10 06:55:46 LabSZ sshd[{pid}]: input_userauth_request: invalid user {user} [preauth]",
    "Dec 10 06:55:46 LabSZ sshd[{pid}]: pam_unix(sshd:auth): check pass; user unknown",
    "Dec 10 06:55:46 LabSZ sshd[{pid}]: pam_unix(sshd:auth): authentication failure; logname= uid=0 euid=0 tty=ssh ruser= rhost={ip}",
    "Dec 10 06:55:48 LabSZ sshd[{pid}]: Failed password for invalid user {user} from {ip} port {port} ssh2",
    "Dec 10 06:55:48 LabSZ sshd[{pid}]: Failed password for root from {ip} port {port} ssh2",
    "Dec 10 06:55:48 LabSZ sshd[{pid}]: Connection closed by {ip} [preauth]",
    "api-gateway WARN: SQL injection payload detected in parameter '{param}' from {ip}",
    "auth-service ERROR: Directory traversal attempt detected for path {path} from {ip}",
    "auth-service ERROR: Cross-site scripting (XSS) probe detected in header {header} from {ip}",
    "firewall-edge ALERT: Brute force signature matched for target service SSH from {ip}"
]

ERROR_TEMPLATES = [
    "postgresql-primary FATAL: remaining connection slots are reserved for non-replication superuser connections",
    "postgresql-primary ERROR: deadlock detected while executing transaction TX_{tx}",
    "kernel: [{uptime}] Out of memory: Kill process {pid} (mysqld) score {score} or sacrifice child",
    "kubelet: Error: Back-off restarting failed container worker-process in pod {pod}",
    "kubelet: OOMKilled container payment-api in pod {pod} memory limit 512Mi exceeded",
    "redis-master ERROR: DiskFullException: No space left on device while persisting RDB snapshot",
    "systemd[1]: Failed to start Docker Application Container Engine: exit-code 1",
    "api-server FATAL: NullPointerException in PaymentProcessor while accessing auth_db",
    "order-service ERROR: DatabaseLockError: lock wait timeout exceeded on table orders"
]

WARNING_TEMPLATES = [
    "task-scheduler WARN: Slow query execution {latency}ms on table {table}",
    "queue-sync WARN: Retry counter reached threshold 3/5 for worker job {job}",
    "cache-node WARN: Connection pool near capacity ({pct}% utilization) for user {user}",
    "ingress-nginx WARN: 429 Too Many Requests rate limit threshold approaching for {ip}",
    "disk-monitor WARN: Filesystem /var/log usage reached {pct}% capacity",
    "kubelet WARN: Node cpu utilization spike detected at {pct}%"
]

ROUTINE_TEMPLATES = [
    "nginx-edge INFO: GET {path} 200 OK {latency}ms for {user} from {ip}",
    "nginx-edge INFO: POST /api/v1/telemetry 201 Created for app_svc from {ip}",
    "health-check INFO: Liveness probe succeeded on /health 200 OK",
    "cron-scheduler INFO: Scheduled job {job} completed successfully in {latency}ms",
    "auth-service INFO: Session token refreshed for {user} from {ip}",
    "cache-layer INFO: Cache hit for key user_profile_{user} latency 1.2ms",
    "db-pool INFO: Connection checkout completed in 0.8ms on connection pool"
]

def generate_dataset(total_count=12000):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    users = ["admin", "root", "webmaster", "test9", "deploy", "guest", "ubuntu", "app_svc"]
    ips = [f"173.234.{random.randint(1,254)}.{random.randint(1,254)}", f"192.168.1.{random.randint(1,254)}", f"10.0.{random.randint(1,254)}.{random.randint(1,254)}"]
    
    rows = []
    # Balance: 25% Security, 25% Critical, 20% Warning, 30% Routine
    distributions = [
        ("security", SECURITY_TEMPLATES, int(total_count * 0.25)),
        ("error", ERROR_TEMPLATES, int(total_count * 0.25)),
        ("warning", WARNING_TEMPLATES, int(total_count * 0.20)),
        ("noise", ROUTINE_TEMPLATES, int(total_count * 0.30))
    ]
    
    for label, templates, count in distributions:
        for _ in range(count):
            tpl = random.choice(templates)
            msg = tpl.format(
                pid=random.randint(1000, 65000),
                port=random.randint(1024, 65535),
                ip=random.choice(ips),
                host="ns.sample-attack-domain.com",
                user=random.choice(users),
                tx=random.randint(1000, 9999),
                uptime=round(random.uniform(1000, 90000), 2),
                score=random.randint(500, 999),
                pod=f"worker-pod-{random.randint(10,99)}",
                latency=random.randint(5, 4500),
                table="orders_v2",
                job=f"sync_{random.randint(1,50)}",
                pct=random.randint(75, 95),
                path="/index.html",
                param="id_search",
                header="X-Forwarded-For"
            )
            rows.append({
                "timestamp": "2026-09-13T00:00:00Z",
                "source": "syslog",
                "level": label.upper(),
                "message": msg,
                "true_label": label
            })
            
    random.shuffle(rows)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "source", "level", "message", "true_label"])
        writer.writeheader()
        writer.writerows(rows)
        
    print(f"Generated {len(rows)} real-world training records to {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_dataset()
