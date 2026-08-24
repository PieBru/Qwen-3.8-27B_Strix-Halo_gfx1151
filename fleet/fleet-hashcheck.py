#!/usr/bin/env python3
"""fleet-hashcheck — nightly GGUF integrity verification for the fleet.

Reads the full sha256 hashes from models/models.ini (the comment directly
above each model=/model-draft=/mmproj= line — single source of truth, the
same hashes the router config carries), sha256s every weight file on THIS
box (~80 GiB, ~30-60 s on NVMe), and writes results/fleet-hashcheck.json
for the fleet dashboard's doctor. Also appends a line to
results/fleet-hashcheck.log.

Exit code: 0 = every file verified, 1 = any mismatch/missing.

stdlib-only (like the canary and dashboard) — safe from a systemd timer
with no venv/uv dependency.

Deploy: cp fleet/fleet-hashcheck.{service,timer} to ~/.config/systemd/user/
        && systemctl --user daemon-reload && systemctl --user enable --now fleet-hashcheck.timer
Run once: uv run python3 fleet/fleet-hashcheck.py   (or plain python3)
"""
import hashlib
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INI = os.path.join(REPO, "models", "models.ini")
STATE = os.path.join(REPO, "results", "fleet-hashcheck.json")
LOG = os.path.join(REPO, "results", "fleet-hashcheck.log")


def parse_ini_hashes(path):
    """Map weight-path -> full sha256 from the models.ini comments.

    Format (written 2026-08-24): a `; sha256 = <hash> ...` comment sits
    directly above the `model = <path>` / `model-draft =` / `mmproj =` line.
    Dedupes repeated paths (Q8 appears in 5 recipes, Q6 in 4).
    """
    want = {}
    prev_sha = None
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if s.startswith("; sha256 = "):
            prev_sha = s.split("=", 1)[1].strip().split()[0]
        elif s.startswith(("model =", "model-draft =", "mmproj =")) and prev_sha:
            want[s.split("=", 1)[1].strip()] = prev_sha
            prev_sha = None
    return want


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    t0 = time.time()
    want = parse_ini_hashes(INI)
    if not want:
        print("FATAL: no hashes parsed from models.ini", flush=True)
        return 2
    files = {}
    ok = True
    for rel, exp in sorted(want.items()):
        full = os.path.join(REPO, rel)
        if not os.path.exists(full):
            files[rel] = {"ok": False, "want": exp, "got": None, "note": "MISSING"}
            ok = False
            print(f"MISSING  {rel} (want {exp[:12]}…)", flush=True)
            continue
        got = sha256_file(full)
        good = got == exp
        files[rel] = {"ok": good, "want": exp, "got": got}
        ok = ok and good
        print(f"{'OK       ' if good else 'MISMATCH '} {rel}  {got[:12]}…", flush=True)
    n_ok = sum(1 for v in files.values() if v["ok"])
    secs = round(time.time() - t0, 1)
    state = {
        "ts": time.time(),
        "ok": ok,
        "summary": f"{n_ok}/{len(files)}",
        "files": files,
        "seconds": secs,
    }
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)  # atomic — the dashboard never reads a half-written state
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {state['summary']} OK" if ok else \
           f"{time.strftime('%Y-%m-%d %H:%M:%S')} {state['summary']} FAIL"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"state -> {STATE}  ({state['summary']} verified in {secs}s)", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
