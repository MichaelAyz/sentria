"""
Zero-Leakage Stratified Dataset Splitter
Guarantees NO duplicate or near-duplicate leakage between Train, Validation, and Blind Test.
Normalizes logs to template signatures, groups by signature, and performs stratified splitting.
Asserts that Train, Val, and Blind Test share ZERO signature overlap.
Locks blind_test_logs.jsonl with SHA256.
"""
import json
import os
import re
import random
import hashlib
from collections import defaultdict

BASE_DIR = os.path.dirname(__file__)
RAW_DIR = os.path.join(BASE_DIR, "raw_captured")
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

CAPTURED_FILES = [
    "nginx_logs.json",
    "postgres_logs.json",
    "redis_logs.json",
    "nextjs_node_logs.json",
    "kubernetes_logs.json",
    "auth_ssh_logs.json"
]

def normalize_signature(text: str) -> str:
    """
    Normalizes log message to a template signature by stripping
    timestamps, dynamic PIDs, IP addresses, ports, and hex pointers.
    """
    s = text.strip()
    # Strip ISO and syslog timestamps
    s = re.sub(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?', '<TS>', s)
    s = re.sub(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}', '<TS>', s)
    s = re.sub(r'\[\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}\s+[+-]\d{4}\]', '<TS>', s)
    # Strip IPv4
    s = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '<IP>', s)
    # Strip ports and PIDs
    s = re.sub(r'port \d+', 'port <PORT>', s)
    s = re.sub(r'\[\d+\]', '[<PID>]', s)
    # Strip hex addresses
    s = re.sub(r'0x[0-9a-fA-F]+', '<HEX>', s)
    # Strip specific numbers
    s = re.sub(r'\b\d{4,}\b', '<NUM>', s)
    # Strip whitespace variations
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()

def load_and_split():
    random.seed(42)  # Deterministic seed for reproducible split
    
    all_items = []
    for fname in CAPTURED_FILES:
        fpath = os.path.join(RAW_DIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r") as f:
            items = json.load(f)
            for it in items:
                it["signature"] = normalize_signature(it["raw_log"])
            all_items.extend(items)
            
    # Group unique items by category and signature
    cat_sig_items = defaultdict(dict)
    for it in all_items:
        sig = it["signature"]
        cat = it["category"]
        if sig not in cat_sig_items[cat]:
            cat_sig_items[cat][sig] = it
            
    total_distinct = sum(len(sigs) for sigs in cat_sig_items.values())
    print(f"Total raw items: {len(all_items)} across {total_distinct} distinct template signatures.")
    
    TARGET_TEST = 20  # Exactly 20 distinct signatures in blind test per category
    TARGET_VAL = 5    # Exactly 5 distinct signatures in val per category
    
    train_records = []
    val_records = []
    blind_test_records = []
    
    train_sigs = set()
    val_sigs = set()
    test_sigs = set()
    
    system_stats = defaultdict(lambda: {"total": 0, "train": 0, "val": 0, "test": 0})
    category_stats = defaultdict(lambda: {"total": 0, "train": 0, "val": 0, "test": 0})
    
    for cat in sorted(cat_sig_items.keys()):
        sig_dict = cat_sig_items[cat]
        
        # Partition signatures by system for multi-system representation
        by_sys = defaultdict(list)
        for sig, item in sig_dict.items():
            by_sys[item["system"]].append(item)
            
        # Deterministically shuffle within each system
        for sys_name in by_sys:
            random.shuffle(by_sys[sys_name])
            
        systems = sorted(by_sys.keys())
        
        # 1. Round-robin multi-system selection for Blind Test (exactly TARGET_TEST signatures)
        cat_test = []
        while len(cat_test) < TARGET_TEST:
            progress = False
            for s in systems:
                if len(by_sys[s]) > 0 and len(cat_test) < TARGET_TEST:
                    item = by_sys[s].pop(0)
                    cat_test.append(item)
                    progress = True
            if not progress:
                break
                
        # 2. Round-robin multi-system selection for Val (exactly TARGET_VAL signatures)
        cat_val = []
        while len(cat_val) < TARGET_VAL:
            progress = False
            for s in systems:
                if len(by_sys[s]) > 0 and len(cat_val) < TARGET_VAL:
                    item = by_sys[s].pop(0)
                    cat_val.append(item)
                    progress = True
            if not progress:
                break
                
        # 3. Remaining signatures go to Train
        cat_train = []
        for s in systems:
            cat_train.extend(by_sys[s])
            
        # Cap noise in training pool to prevent extreme class skew (balanced linear head)
        if cat == "noise" and len(cat_train) > 50:
            random.shuffle(cat_train)
            cat_train = cat_train[:50]
            
        # Record into splits
        for it in cat_test:
            test_sigs.add(it["signature"])
            blind_test_records.append(it)
            system_stats[it["system"]]["test"] += 1
            category_stats[cat]["test"] += 1
            
        for it in cat_val:
            val_sigs.add(it["signature"])
            val_records.append(it)
            system_stats[it["system"]]["val"] += 1
            category_stats[cat]["val"] += 1
            
        for it in cat_train:
            train_sigs.add(it["signature"])
            train_records.append(it)
            system_stats[it["system"]]["train"] += 1
            category_stats[cat]["train"] += 1
            
        tot = len(cat_test) + len(cat_val) + len(cat_train)
        category_stats[cat]["total"] = tot
        
    for sys_name in system_stats:
        system_stats[sys_name]["total"] = (
            system_stats[sys_name]["train"] + 
            system_stats[sys_name]["val"] + 
            system_stats[sys_name]["test"]
        )
        
    # STRICT ASSERTIONS: ZERO SIGNATURE LEAKAGE
    overlap_train_test = train_sigs & test_sigs
    overlap_train_val = train_sigs & val_sigs
    overlap_val_test = val_sigs & test_sigs
    
    assert len(overlap_train_test) == 0, f"LEAKAGE DETECTED between Train and Test: {overlap_train_test}"
    assert len(overlap_train_val) == 0, f"LEAKAGE DETECTED between Train and Val: {overlap_train_val}"
    assert len(overlap_val_test) == 0, f"LEAKAGE DETECTED between Val and Test: {overlap_val_test}"
    assert all(category_stats[c]["test"] == TARGET_TEST for c in ["error", "noise", "security", "warning"]), (
        f"Blind test target not met: {dict(category_stats)}"
    )
    print("[OK] ZERO-LEAKAGE ASSERTION PASSED: Exact and normalized signature overlap = 0.")
    print(f"[OK] TARGET MET: Exactly {TARGET_TEST} distinct signatures per category in Blind Test set.")
    
    # Deterministically shuffle splits
    random.shuffle(train_records)
    random.shuffle(val_records)
    random.shuffle(blind_test_records)
    
    # Save files
    train_file = os.path.join(DATA_DIR, "train_logs.jsonl")
    val_file = os.path.join(DATA_DIR, "val_logs.jsonl")
    blind_test_file = os.path.join(DATA_DIR, "blind_test_logs.jsonl")
    
    with open(train_file, "w") as f:
        for r in train_records:
            clean_r = {k: v for k, v in r.items() if k != "signature"}
            f.write(json.dumps(clean_r) + "\n")
            
    with open(val_file, "w") as f:
        for r in val_records:
            clean_r = {k: v for k, v in r.items() if k != "signature"}
            f.write(json.dumps(clean_r) + "\n")
            
    with open(blind_test_file, "w") as f:
        for r in blind_test_records:
            clean_r = {k: v for k, v in r.items() if k != "signature"}
            f.write(json.dumps(clean_r) + "\n")
            
    # Calculate checksum of the locked blind test set
    with open(blind_test_file, "rb") as f:
        test_sha = hashlib.sha256(f.read()).hexdigest()
        
    lock_file = os.path.join(DATA_DIR, "blind_test_logs.lock")
    with open(lock_file, "w") as f:
        f.write(f"SHA256: {test_sha}\nCOUNT: {len(blind_test_records)}\nSTATUS: LOCKED\nLEAKAGE_CHECK: PASSED (0 signature overlap)\n")
        
    print("\n==========================================================")
    print("STRATIFIED FIXED-N HOLDOUT SPLIT COMPLETED (ZERO LEAKAGE)")
    print("==========================================================")
    print(f"Total Selected Signatures: {len(train_records) + len(val_records) + len(blind_test_records)}")
    print(f"Training Set:            {len(train_records)} records -> {train_file}")
    print(f"Validation Set:          {len(val_records)} records -> {val_file}")
    print(f"Blind Test Set:          {len(blind_test_records)} records -> {blind_test_file}")
    print(f"Blind Test SHA256:       {test_sha} [LOCKED]")
    print("\nPer-Category Breakdown (Support Counts):")
    for cat, stats in sorted(category_stats.items()):
        print(f"  {cat.upper():10}: Total={stats['total']:3} | Train={stats['train']:3} | Val={stats['val']:3} | BlindTest={stats['test']:3} [N >= 20 OK]")
    print("\nPer-System Breakdown (Support Counts):")
    for sys_name, stats in sorted(system_stats.items()):
        print(f"  {sys_name:15}: Total={stats['total']:3} | Train={stats['train']:3} | Val={stats['val']:3} | BlindTest={stats['test']:3}")
    print("==========================================================")

if __name__ == "__main__":
    load_and_split()

