#!/usr/bin/env python3
"""gpu_canary — unattended GPU-liveness watchdog for the lockup_timeout=-1 setup.

WHY IT EXISTS: with amdgpu.lockup_timeout=-1 the kernel will never again
declare a ring timeout — the price of the 256k-window Vulkan fix. The
hardware watchdog (SP5100 TCO, petted by systemd at RuntimeWatchdogSec=20s)
only catches FULL system hangs. The gap is "kernel alive, GPU ring wedged":
HTTP health stays green while every inference hangs forever. This canary
closes that gap.

Probe signature (matches the observed 2026-08-22 wedges):
  /health OK  AND  a 1-token completion dead/timing out  =>  GPU path wedged.

Behavior (timer fires every 10 min):
  router not active            -> skip (planned offline: batteries etc.)
  /health not ok                -> restart router once, log, reset counter
  health ok + completion ok     -> reset fail counter
  health ok + completion dead   -> count; 2 consecutive => journal + reboot
                                    (via sudoers NOPASSWD systemctl reboot)

State: ~/.local/state/gpu_canary/  Logs: results/gpu-canary.log
Undo: systemctl --user disable --now gpu-canary.timer; remove sudoers file.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

HOST = "localhost:8080"
MODEL = "Qwen38-27B-balanced"   # always-loaded default; probe is tiny
COMPLETION_TIMEOUT = 240        # s; normal is <10 s even under load
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root (script lives in scripts/)
STATE_DIR = os.path.expanduser("~/.local/state/gpu_canary")
FAILS_FILE = os.path.join(STATE_DIR, "consecutive_fails")
LOG = os.path.join(REPO, "results", "gpu-canary.log")


def log(msg):
    line = f"{time.strftime('%F %T')} {msg}"
    with open(LOG, "a") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def unit_active(name):
    r = subprocess.run(["systemctl", "--user", "is-active", name],
                       capture_output=True, text=True)
    return r.stdout.strip() == "active"


def http(url, body=None, timeout=30):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def read_fails():
    try:
        return int(open(FAILS_FILE).read())
    except (OSError, ValueError):
        return 0


def write_fails(n):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FAILS_FILE, "w") as fh:
        fh.write(str(n))


def any_model_loading_or_probe_model_not_loaded():
    """2026-08-26 incident grace: distinguish an in-flight model LOAD from a
    GPU wedge. The catalog (/v1/models) reports per-model status:
    'loading' (weights streaming) or 'unloaded' (probe model evicted by a
    scheduled job's pinned model — will reload on demand). Both mean the
    completion path is legitimately blocked, NOT wedged. Catalog failure ->
    False (can't prove a load; fall through to the wedge verdict)."""
    try:
        d = http(f"http://{HOST}/v1/models", timeout=15)
        for m in d.get("data", []):
            st = (m.get("status") or {}).get("value")
            if st == "loading":
                return True
            if m.get("id") == MODEL and st in ("unloaded", "unknown"):
                return True
    except Exception:
        return False
    return False


def main():
    if not unit_active("llama-router.service"):
        log("router inactive — planned offline, skipping probe")
        write_fails(0)
        return 0

    # 1) service-level health
    try:
        http(f"http://{HOST}/health", timeout=15)
    except Exception as e:
        log(f"health DOWN ({e}) — restarting router (service-level), not GPU verdict")
        subprocess.run(["systemctl", "--user", "restart", "llama-router.service"])
        write_fails(0)
        return 0

    # 2) end-to-end GPU probe: health-green + inference-dead = wedge signature
    body = json.dumps({"model": MODEL, "max_tokens": 1, "temperature": 0,
                       "messages": [{"role": "user", "content": "1"}]}).encode()
    try:
        t0 = time.time()
        d = http(f"http://{HOST}/v1/chat/completions", body, timeout=COMPLETION_TIMEOUT)
        _ = d["choices"][0]
        log(f"probe ok ({time.time()-t0:.1f}s)")
        write_fails(0)
        return 0
    except Exception as e:
        # Model-load grace (2026-08-26 incident): a scheduled job's pinned
        # model (e.g. gefc-dream's quality@128k) evicts the resident one;
        # /health stays green while the completion path is dead — the SAME
        # signature as a wedge. Before counting a fail, check the catalog:
        # any model loading (or the probe model not yet loaded) = in-flight
        # LOAD, not a GPU wedge — reset the counter and skip this cycle.
        if any_model_loading_or_probe_model_not_loaded():
            log(f"probe DEAD ({e}) BUT a model load is in flight "
                f"(catalog says loading/not-loaded) — load contention, not a "
                f"GPU wedge; counter reset, next cycle re-probes")
            write_fails(0)
            return 0
        fails = read_fails() + 1
        write_fails(fails)
        log(f"probe DEAD ({e}) — health was green: GPU-wedge signature, "
            f"consecutive fails={fails}")
        if fails >= 2:
            log("GPU WEDGE CONFIRMED (2 consecutive dead probes with green "
                "health) — REBOOTING box via hardware path (lockup_timeout=-1 "
                "means the kernel cannot recover itself)")
            subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "reboot"])
            return 2
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
