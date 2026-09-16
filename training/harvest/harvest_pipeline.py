"""
Automated Log Harvesting & Drain3 Mining Pipeline
Streams raw production logs across 16+ real systems (Loghub, live containers, security archives),
mines structural templates via Drain3, and extracts strictly 1 representative log per template cluster.
Enforces zero leakage against the locked blind test set.
"""
import os
import re
import csv
import io
import json
import random
import urllib.request
from collections import defaultdict
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
RAW_CAPTURED = os.path.join(BASE_DIR, "..", "capture", "raw_captured", "all_captured_logs.json")
BLIND_TEST_FILE = os.path.join(DATA_DIR, "blind_test_logs.jsonl")
VAL_FILE = os.path.join(DATA_DIR, "val_logs.jsonl")
OUTPUT_TRAIN_FILE = os.path.join(DATA_DIR, "train_logs.jsonl")

def normalize_signature(text: str) -> str:
    s = text.strip()
    s = re.sub(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?', '<TS>', s)
    s = re.sub(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}', '<TS>', s)
    s = re.sub(r'\[\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\]', '<TS>', s)
    s = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '<IP>', s)
    s = re.sub(r'port \d+', 'port <PORT>', s)
    s = re.sub(r'\[\d+\]', '[<PID>]', s)
    s = re.sub(r'0x[0-9a-fA-F]+', '<HEX>', s)
    s = re.sub(r'\b\d{4,}\b', '<NUM>', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()

def load_locked_signatures():
    test_sigs = set()
    val_sigs = set()
    if os.path.exists(BLIND_TEST_FILE):
        with open(BLIND_TEST_FILE, "r") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    test_sigs.add(normalize_signature(item["raw_log"]))
    if os.path.exists(VAL_FILE):
        with open(VAL_FILE, "r") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    val_sigs.add(normalize_signature(item["raw_log"]))
    return test_sigs, val_sigs

def fetch_loghub_datasets():
    """
    Downloads real production log subsets from the Loghub repository across 16 systems.
    """
    systems = [
        'Linux', 'Apache', 'Hadoop', 'OpenStack', 'Spark', 'Zookeeper',
        'BGL', 'HPC', 'Mac', 'Windows', 'Thunderbird', 'OpenSSH', 'HDFS', 'Android', 'HealthApp', 'Proxifier'
    ]
    candidates = []
    print("\n[1/4] Fetching real production logs from Loghub across 16 systems...")
    for s in systems:
        url = f"https://raw.githubusercontent.com/logpai/loghub/master/{s}/{s}_2k.log_structured.csv"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=12) as resp:
                text = resp.read().decode('utf-8', errors='ignore')
            reader = csv.DictReader(io.StringIO(text))
            count = 0
            for row in reader:
                content = row.get("Content", "").strip()
                if not content:
                    continue
                level = row.get("Level", "").upper().strip()
                
                raw_log = f"{s}: [{level or 'INFO'}] {content}" if level else f"{s}: {content}"
                c_lower = content.lower()
                
                # Check security indicators
                if any(k in c_lower for k in [
                    'authentication failure', 'failed password', 'invalid user',
                    'possible break-in', 'unauthorized', 'access denied',
                    'reverse mapping checking', 'check pass; user unknown',
                    'too many authentication failures', 'change of username disallowed',
                    'error: kex_exchange_identification'
                ]):
                    cat = "security"
                elif level in ["ERROR", "FATAL", "CRITICAL", "SEVERE", "FAILURE"] or any(k in c_lower for k in [
                    'exception', 'fatal', 'failed to', 'syntax error', 'connection refused',
                    'nullpointerexception', 'ioexception', 'panic', 'core dump', 'segfault'
                ]):
                    cat = "error"
                elif level in ["WARN", "WARNING"] or any(k in c_lower for k in [
                    'warning', 'alert', 'slow', 'retry', 'timeout', 'deprecated', 'saturation',
                    'temperature exceeds', 'worker_connections are not enough'
                ]):
                    cat = "warning"
                else:
                    cat = "noise"
                    
                candidates.append({
                    "system": s.lower(),
                    "raw_log": raw_log,
                    "category": cat
                })
                count += 1
            print(f"  -> Fetched {count} rows from Loghub {s}")
        except Exception as e:
            print(f"  -> Warning fetching {s}: {e}")
            
    return candidates

def fetch_web_attack_datasets():
    """
    Downloads real web attack traces (Acunetix & Netsparker vulnerability scans) from apache-http-logs.
    """
    import urllib.parse
    candidates = []
    print("\n[2/4] Fetching real web attack logs (Acunetix & Netsparker)...")
    for tool, fn in [('acunetix', 'acunetix.txt'), ('netsparker', 'netsparker.txt')]:
        url = f'https://raw.githubusercontent.com/ocatak/apache-http-logs/master/{fn}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                for i, line in enumerate(resp):
                    if i >= 3000:
                        break
                    s = line.decode('utf-8', errors='ignore').strip()
                    m = re.search(r'"([A-Z]+)\s+([^\s"]+)\s+HTTP/[0-9.]+"\s+(\d{3})', s)
                    if not m:
                        continue
                    method, path, status_code = m.group(1), m.group(2), int(m.group(3))
                    path_unquoted = urllib.parse.unquote(path)
                    p_lower = path_unquoted.lower()
                    
                    is_attack = any(k in p_lower for k in [
                        'select', 'union', 'waitfor delay', 'sleep(', 'benchmark(',
                        '<script', 'alert(', 'onerror=', 'onload=', '../', 'etc/passwd',
                        'etc/shadow', 'cmd=', 'exec', 'eval(', 'base64', 'wp-config',
                        'phpinfo', '.env', '.git', 'bin/sh', 'bin/bash', 'win.ini'
                    ])
                    
                    spaced = path_unquoted.replace('?', ' ? ').replace('&', ' & ').replace('=', ' = ')
                    clean_req = re.sub(r'\s+', ' ', f'{method} {spaced}').strip()
                    raw_log = f'192.168.1.100 - - [14/Sep/2026:12:00:00 +0000] "{method} {path_unquoted} HTTP/1.1" {status_code} 1024'
                    
                    if is_attack:
                        cat = 'security'
                    elif status_code >= 500:
                        cat = 'error'
                    elif status_code >= 400:
                        cat = 'warning'
                    else:
                        cat = 'noise'
                        
                    candidates.append({
                        'system': 'apache',
                        'raw_log': raw_log,
                        'category': cat,
                        'drain_input': f'apache: {clean_req} {status_code}'
                    })
            print(f"  -> Fetched real attack logs from {tool}")
        except Exception as e:
            print(f"  -> Warning fetching {tool}: {e}")
            
    return candidates

def load_live_captured_candidates():
    """
    Loads self-run live service captured logs (Postgres, Redis, Nginx, Node/Next.js, K8s, SSH)
    with clean labels.
    """
    candidates = []
    if os.path.exists(RAW_CAPTURED):
        with open(RAW_CAPTURED, "r") as f:
            items = json.load(f)
            for it in items:
                raw_log = it["raw_log"]
                cat = it["category"]
                
                # Correct inadvertent false positives from initial pattern matches
                if "/docker-entrypoint.sh:" in raw_log:
                    cat = "noise"
                elif "pam_unix(sshd:session): session closed" in raw_log or "pam_unix(sshd:session): session opened" in raw_log:
                    cat = "noise"
                elif "<search> gc: ON" in raw_log or "RedisBloom version" in raw_log or "Module 'bf' loaded" in raw_log:
                    cat = "noise"
                elif "locale: not found" in raw_log:
                    cat = "warning"
                    
                candidates.append({
                    "system": it["system"],
                    "raw_log": raw_log,
                    "category": cat
                })
        print(f"\n[3/4] Loaded and cleaned {len(candidates)} live captured logs across self-run services")
    return candidates

def main():
    print("==========================================================")
    print("STARTING AUTOMATED LOG HARVESTING & DRAIN3 TEMPLATE MINING")
    print("==========================================================")
    
    test_sigs, val_sigs = load_locked_signatures()
    print(f"Loaded {len(test_sigs)} locked test signatures and {len(val_sigs)} val signatures.")
    
    # 1. Collect all candidates
    all_candidates = []
    loghub_candidates = fetch_loghub_datasets()
    web_attack_candidates = fetch_web_attack_datasets()
    live_candidates = load_live_captured_candidates()
    
    all_candidates.extend(live_candidates)
    all_candidates.extend(loghub_candidates)
    all_candidates.extend(web_attack_candidates)
    print(f"\nTotal aggregated candidate logs: {len(all_candidates)}")
    
    # 2. Configure Drain3 TemplateMiner
    config = TemplateMinerConfig()
    config.drain_sim_th = 0.55
    miner = TemplateMiner(config=config)
    
    # 3. Mine templates and guarantee strictly 1 representative log per template cluster
    seen_clusters = set()
    harvested_by_cat = defaultdict(list)
    skipped_leakage = 0
    duplicate_clusters = 0
    
    random.seed(42)
    random.shuffle(all_candidates)
    
    for item in all_candidates:
        raw_log = item["raw_log"]
        sig = normalize_signature(raw_log)
        
        # STRICT LEAKAGE PREVENTION: Drop any candidate that matches a locked test/val signature
        if sig in test_sigs or sig in val_sigs:
            skipped_leakage += 1
            continue
            
        drain_input = item.get("drain_input", raw_log)
        result = miner.add_log_message(drain_input)
        cluster_id = result["cluster_id"]
        
        if cluster_id in seen_clusters:
            duplicate_clusters += 1
            continue
            
        seen_clusters.add(cluster_id)
        harvested_by_cat[item["category"]].append({
            "system": item["system"],
            "raw_log": raw_log,
            "category": item["category"],
            "cluster_id": cluster_id,
            "signature": sig
        })
        
    total_mined = sum(len(items) for items in harvested_by_cat.values())
    print(f"\n[4/4] Drain3 Mining Completed:")
    print(f"  -> Total distinct template clusters mined: {total_mined}")
    print(f"  -> Discarded duplicate logs in existing clusters: {duplicate_clusters}")
    print(f"  -> Dropped to prevent test/val leakage: {skipped_leakage}")
    print(f"  -> Category breakdown before balancing:")
    for c, items in sorted(harvested_by_cat.items()):
        print(f"     {c.upper():10}: {len(items)} distinct templates")
        
    # 4. Stratified Multi-System Balancing
    # Balance so every system gets representation and no single system or class dominates
    final_train_records = []
    caps = {"noise": 250, "error": 200, "warning": 150, "security": 150}
    
    for c, items in harvested_by_cat.items():
        by_sys = defaultdict(list)
        for it in items:
            by_sys[it["system"]].append(it)
        for s in by_sys:
            random.shuffle(by_sys[s])
            
        selected = []
        systems = sorted(by_sys.keys())
        max_cap = caps.get(c, 150)
        
        # Round-robin selection across all systems for this category
        while len(selected) < max_cap:
            progress = False
            for s in systems:
                if by_sys[s] and len(selected) < max_cap:
                    selected.append(by_sys[s].pop(0))
                    progress = True
            if not progress:
                break
                
        final_train_records.extend(selected)
        print(f"  -> Selected for training [{c.upper()}]: {len(selected)} distinct templates across {len(systems)} systems")
        
    random.shuffle(final_train_records)
    
    # 5. Strict Zero-Leakage Assertion
    final_train_sigs = {r["signature"] for r in final_train_records}
    assert len(final_train_sigs & test_sigs) == 0, "LEAKAGE DETECTED between Harvested Train and Locked Blind Test!"
    assert len(final_train_sigs & val_sigs) == 0, "LEAKAGE DETECTED between Harvested Train and Val!"
    print("\n[OK] ZERO-LEAKAGE ASSERTION PASSED: Exact and normalized signature overlap with Blind Test = 0.")
    
    # 6. Save expanded training dataset
    with open(OUTPUT_TRAIN_FILE, "w") as f:
        for r in final_train_records:
            clean_r = {
                "system": r["system"],
                "raw_log": r["raw_log"],
                "category": r["category"]
            }
            f.write(json.dumps(clean_r) + "\n")
            
    print(f"\nSuccessfully written {len(final_train_records)} distinct template records to {OUTPUT_TRAIN_FILE}")
    print("==========================================================")

if __name__ == "__main__":
    main()
