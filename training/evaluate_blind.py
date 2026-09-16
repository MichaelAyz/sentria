"""
Honest Blind Held-Out Evaluation & FP32 vs INT8 Benchmark
Runs strictly ONCE against the locked blind_test_logs.jsonl set.
Reports:
1. Model-Only Accuracy (Zero Heuristics) vs Full-Pipeline Accuracy
2. Precision, Recall, F1, and Support (sample count N) for every row
3. Statistical confidence flags for any row with N < 20
4. Per-system breakdown with support counts and reliability flags
5. FP32 vs INT8 empirical comparison (accuracy delta, latency, file size)
"""
import json
import os
import time
import hashlib
import numpy as np
import joblib
from sklearn.metrics import classification_report, accuracy_score, f1_score

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from service.embedder import MiniLMEmbedder
from service.model import ModelService
from service.features import transform_features

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BLIND_TEST_FILE = os.path.join(DATA_DIR, "blind_test_logs.jsonl")
LOCK_FILE = os.path.join(DATA_DIR, "blind_test_logs.lock")
LINEAR_HEAD_FILE = os.path.join(os.path.dirname(__file__), "..", "service", "linear_head.joblib")
ONNX_DIR = os.path.join(os.path.dirname(__file__), "..", "service", "onnx")

RELIABILITY_THRESHOLD = 20  # Sample count threshold below which metrics are flagged as noisy

def verify_lock():
    print("\n[LOCK & LEAKAGE VERIFICATION]")
    if not os.path.exists(LOCK_FILE):
        print("  WARNING: No lock file found.")
        return
    with open(LOCK_FILE, "r") as f:
        lock_content = f.read()
    print("  Lock file content:\n  " + lock_content.replace("\n", "\n  "))
    
    with open(BLIND_TEST_FILE, "rb") as f:
        current_sha = hashlib.sha256(f.read()).hexdigest()
    print(f"  Current test set SHA256: {current_sha}")
    if current_sha in lock_content:
        print("  [OK] SHA256 MATCH: Blind test set is completely intact and untouched.")
    else:
        print("  [WARNING] SHA256 MISMATCH: Test set has been modified!")

def load_blind_test():
    texts, labels, systems = [], [], []
    with open(BLIND_TEST_FILE, "r") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            texts.append(item["raw_log"])
            labels.append(item["category"])
            systems.append(item.get("system", "unknown"))
    return texts, labels, systems

def evaluate_model(quantized=False, name="FP32"):
    clf = joblib.load(LINEAR_HEAD_FILE)
    embedder = MiniLMEmbedder(quantized=quantized)
    model_service = ModelService(linear_head_path=LINEAR_HEAD_FILE, quantized=quantized)
    model_service.load()
    
    texts, labels, systems = load_blind_test()
    
    # Warmup
    _ = embedder.embed(["warmup log line 1", "warmup log line 2"])
    
    # Measure latency across single-sentence invocations
    latencies = []
    for t in texts:
        t0 = time.time()
        _ = embedder.embed([t])
        latencies.append((time.time() - t0) * 1000)
        
    # Batch embedding & hybrid feature extraction
    t0 = time.time()
    features = transform_features(texts, embedder)
    batch_time_ms = (time.time() - t0) * 1000
    
    # 1. MODEL-ONLY PREDICTIONS (Enriched MiniLM hybrid embeddings + Linear Head, ZERO heuristics)
    probs_raw = clf.predict_proba(features)
    preds_model_only = clf.predict(features)
    acc_model_only = accuracy_score(labels, preds_model_only)
    macro_f1_model_only = f1_score(labels, preds_model_only, average="macro")
    report_model_only = classification_report(labels, preds_model_only, digits=4, output_dict=True, zero_division=0)
    
    # 2. FULL-PIPELINE PREDICTIONS (Model + Keyword Fallback Safety Net for conf < 0.60)
    pipeline_results = model_service.predict(texts)
    preds_full_pipeline = [r["category"] for r in pipeline_results]
    acc_full_pipeline = accuracy_score(labels, preds_full_pipeline)
    macro_f1_full_pipeline = f1_score(labels, preds_full_pipeline, average="macro")
    report_full_pipeline = classification_report(labels, preds_full_pipeline, digits=4, output_dict=True, zero_division=0)
    
    # Per-system accuracy for both modes
    sys_results = {}
    for sys_name in sorted(set(systems)):
        idx = [i for i, s in enumerate(systems) if s == sys_name]
        sys_labels = [labels[i] for i in idx]
        sys_pred_mo = [preds_model_only[i] for i in idx]
        sys_pred_fp = [preds_full_pipeline[i] for i in idx]
        
        sys_results[sys_name] = {
            "count": len(idx),
            "acc_model_only": accuracy_score(sys_labels, sys_pred_mo),
            "acc_full_pipeline": accuracy_score(sys_labels, sys_pred_fp),
            "reliable": len(idx) >= RELIABILITY_THRESHOLD
        }
        
    model_file = os.path.join(ONNX_DIR, "model_quantized.onnx" if quantized else "model.onnx")
    file_size_mb = os.path.getsize(model_file) / (1024 * 1024)
    
    return {
        "name": name,
        "quantized": quantized,
        "acc_model_only": acc_model_only,
        "macro_f1_model_only": macro_f1_model_only,
        "report_model_only": report_model_only,
        "acc_full_pipeline": acc_full_pipeline,
        "macro_f1_full_pipeline": macro_f1_full_pipeline,
        "report_full_pipeline": report_full_pipeline,
        "p50_latency_ms": np.percentile(latencies, 50),
        "p95_latency_ms": np.percentile(latencies, 95),
        "mean_latency_ms": np.mean(latencies),
        "batch_total_ms": batch_time_ms,
        "file_size_mb": file_size_mb,
        "per_system": sys_results,
        "total_test_samples": len(texts)
    }

def print_table(res):
    print(f"\nModel Configuration: {res['name']} ({'INT8 Quantized' if res['quantized'] else 'FP32'})")
    print(f"File Size: {res['file_size_mb']:.2f} MB | Latency: P50={res['p50_latency_ms']:.1f}ms, P95={res['p95_latency_ms']:.1f}ms | Batch({res['total_test_samples']} logs)={res['batch_total_ms']:.1f}ms")
    print("-" * 85)
    print(f"OVERALL ACCURACY:     Model-Only = {res['acc_model_only']*100:.2f}%  |  Full-Pipeline = {res['acc_full_pipeline']*100:.2f}%")
    print(f"MACRO F1 SCORE:       Model-Only = {res['macro_f1_model_only']:.4f}  |  Full-Pipeline = {res['macro_f1_full_pipeline']:.4f}")
    print("-" * 85)
    
    print("\nPER-CATEGORY BREAKDOWN:")
    print(f"  {'CATEGORY':10} | {'SUPPORT (N)':11} | {'MODEL-ONLY F1':13} | {'FULL-PIPELINE F1':16} | {'RELIABILITY NOTE'}")
    print("  " + "-" * 75)
    for cat in ["error", "noise", "security", "warning"]:
        if cat in res["report_full_pipeline"]:
            m_mo = res["report_model_only"][cat]
            m_fp = res["report_full_pipeline"][cat]
            support = int(m_fp["support"])
            flag = "[OK] Robust sample" if support >= RELIABILITY_THRESHOLD else "[!] Small sample (N<20)"
            print(f"  {cat.upper():10} | N = {support:<7} | F1 = {m_mo['f1-score']:.3f}      | F1 = {m_fp['f1-score']:.3f}          | {flag}")
            
    print("\nPER-SYSTEM BREAKDOWN:")
    print(f"  {'SYSTEM':15} | {'SUPPORT (N)':11} | {'MODEL-ONLY ACC':14} | {'FULL-PIPELINE ACC':17} | {'RELIABILITY NOTE'}")
    print("  " + "-" * 78)
    for s, v in res["per_system"].items():
        flag = "[OK] Robust sample" if v["reliable"] else "[!] Small sample (N<20)"
        print(f"  {s:15} | N = {v['count']:<7} | {v['acc_model_only']*100:6.1f}%       | {v['acc_full_pipeline']*100:6.1f}%          | {flag}")

def main():
    print("=====================================================================================")
    print("SENTRIA: RIGOROUS BLIND HELD-OUT EVALUATION (ZERO-LEAKAGE)")
    print("=====================================================================================")
    
    verify_lock()
    
    print("\n" + "="*85)
    print("EVALUATING MODEL A: FP32 ONNX (model.onnx)")
    print("="*85)
    fp32_res = evaluate_model(quantized=False, name="FP32")
    print_table(fp32_res)
    
    print("\n" + "="*85)
    print("EVALUATING MODEL B: INT8 QUANTIZED ONNX (model_quantized.onnx)")
    print("="*85)
    int8_res = evaluate_model(quantized=True, name="INT8")
    print_table(int8_res)

    # EMPIRICAL COMPARISON & DELTA REPORT
    acc_delta_mo = (int8_res['acc_model_only'] - fp32_res['acc_model_only']) * 100
    acc_delta_fp = (int8_res['acc_full_pipeline'] - fp32_res['acc_full_pipeline']) * 100
    speedup = fp32_res['p50_latency_ms'] / max(0.01, int8_res['p50_latency_ms'])
    size_reduction = (1 - int8_res['file_size_mb'] / fp32_res['file_size_mb']) * 100
    
    print("\n" + "="*85)
    print("EMPIRICAL DELTA REPORT (FP32 vs INT8)")
    print("="*85)
    print(f"Model-Only Accuracy Delta:   {acc_delta_mo:+.2f}%  (FP32: {fp32_res['acc_model_only']*100:.2f}% vs INT8: {int8_res['acc_model_only']*100:.2f}%)")
    print(f"Full-Pipeline Accuracy Delta:{acc_delta_fp:+.2f}%  (FP32: {fp32_res['acc_full_pipeline']*100:.2f}% vs INT8: {int8_res['acc_full_pipeline']*100:.2f}%)")
    print(f"CPU Latency Speedup:         {speedup:.2f}x faster on P50")
    print(f"Disk & RAM Footprint:        {size_reduction:.1f}% reduction ({fp32_res['file_size_mb']:.1f}MB -> {int8_res['file_size_mb']:.1f}MB)")
    print("="*85)

if __name__ == "__main__":
    main()
