#!/usr/bin/env python3
"""fleet-boot-gate — two-level "cheap insurance" at boot.

Level 1 (APPLICATION): fast weight integrity — size + first/last 1 MiB
sha256 of every GGUF against fleet/boot-gate-baseline.json (pinned in the
repo next to the full sha256s in models/models.ini). ~2 s for all 5 files
vs ~45 s for the full nightly fleet-hashcheck.py — this gate catches gross
corruption (torn writes, bit rot, truncated files) before the router EVER
serves a request; the nightly full check remains the deep guarantee.

Level 2 (SYSTEM): how did the previous boot end + what did the kernel find?
- prev-boot clean shutdown?  (journalctl -b -1 tail: systemd-shutdown /
  "Journal stopped" markers = clean; abrupt end = unclean — crash/mains cut)
- kernel fs/IO error lines this boot (not-properly-unmounted, ext4-fs
  error, I/O error, corrupt)
- err-priority journal count this boot (informational; high counts hint
  at deeper problems worth a look)

Exit code: 0 = weights OK (system findings are REPORTED, never blocking);
1 = any weight anomaly -> with Requires=/After= on llama-router.service,
the router refuses to start (a corrupted weight is never served; fail
loud). State -> results/boot-gate.json for the dashboard/doctor.

stdlib-only. Deploy: user unit (linger), WantedBy=default.target.
"""
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(REPO, "fleet", "boot-gate-baseline.json")
STATE = os.path.join(REPO, "results", "boot-gate.json")
CHUNK = 1 << 20


def sha_range(f, start, n):
    h = __import__("hashlib").sha256()
    with open(f, "rb") as fh:
        fh.seek(start)
        h.update(fh.read(n))
    return h.hexdigest()


def level1_weights():
    base = json.load(open(BASELINE))
    files, ok = {}, True
    for rel, want in sorted(base.items()):
        p = os.path.join(REPO, rel)
        f = {"want_size": want["size"]}
        if not os.path.exists(p):
            f.update(ok=False, note="MISSING"); ok = False
        else:
            sz = os.path.getsize(p)
            f["size_ok"] = sz == want["size"]
            f["head_ok"] = sha_range(p, 0, CHUNK) == want["head_1m"]
            f["tail_ok"] = sha_range(p, max(0, sz - CHUNK), CHUNK) == want["tail_1m"]
            f["ok"] = f["size_ok"] and f["head_ok"] and f["tail_ok"]
            ok = ok and f["ok"]
        files[rel] = f
    return ok, files


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return r.stdout
    except Exception:
        return ""


def level2_system():
    out = {}
    # prev boot ended with a clean shutdown sequence?
    tail = sh("journalctl -b -1 -n 30 --no-pager 2>/dev/null")
    clean = bool(re.search(r"systemd-shutdown\[1\]|Journal stopped|Reached target.*(Power|Shutdown|Reboot)", tail))
    out["prev_boot_clean"] = clean
    # kernel fs/io errors this boot
    k = sh("journalctl -b -k --no-pager 2>/dev/null")
    kerrs = re.findall(r".*(not properly unmounted|ext4-fs error|i/o error|corrupt).*", k, re.I)
    out["fs_error_lines"] = len(kerrs)
    out["fs_error_samples"] = kerrs[:3]
    # err-priority count this boot (informational)
    n = sh("journalctl -b -p err --no-pager 2>/dev/null | wc -l").strip()
    out["err_count"] = int(n) if n.isdigit() else None
    return out


def main():
    t0 = time.time()
    app_ok, files = level1_weights()
    sysinfo = level2_system()
    state = {
        "ts": time.time(),
        "app": {"ok": app_ok, "summary": f"{sum(1 for v in files.values() if v.get('ok'))}/{len(files)}", "files": files},
        "sys": sysinfo,
        "ok": app_ok,  # system findings reported, not blocking
        "seconds": round(time.time() - t0, 1),
    }
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)  # atomic — dashboard never reads half-written
    print(f"boot-gate: weights {state['app']['summary']} ok={app_ok} · "
          f"prev-boot {'clean' if sysinfo['prev_boot_clean'] else 'UNCLEAN'} · "
          f"fs-errors {sysinfo['fs_error_lines']} · err-count {sysinfo['err_count']} "
          f"({state['seconds']}s)", flush=True)
    return 0 if app_ok else 1


if __name__ == "__main__":
    sys.exit(main())
