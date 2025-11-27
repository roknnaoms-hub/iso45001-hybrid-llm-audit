
# utils/audit_logger.py — v0.7.3 (JSONL audit log)
import os, json, datetime, pathlib, hashlib

def _sha1(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()

def _today_file(log_dir: str|os.PathLike) -> pathlib.Path:
    d = datetime.datetime.utcnow().strftime("%Y%m%d")
    logdir = pathlib.Path(log_dir)
    logdir.mkdir(parents=True, exist_ok=True)
    return logdir / f"audit_{d}.jsonl"

def write_audit_log(log_dir, audit_id, backend, model, clause_hint, evidence_digest, csv_bytes, findings_count, version, elapsed_sec):
    rec = {
        "audit_id": audit_id,
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backend": backend,
        "model": model,
        "clause_hint": clause_hint,
        "hash_evidence": _sha1(evidence_digest)[:8],
        "hash_csv": hashlib.sha1(csv_bytes or b"").hexdigest()[:8] if csv_bytes else "",
        "findings_count": findings_count,
        "version": version,
        "elapsed_time": round(float(elapsed_sec or 0), 3)
    }
    fp = _today_file(log_dir)
    with open(fp, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return str(fp)
