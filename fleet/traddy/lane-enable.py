#!/usr/bin/env python3
"""lane-enable (traddy) — bring the capability lane back after boot.

Order: ff-pull the clone (deploy discipline), wait for the local router
to be healthy (lazy builds can be slow), re-enable traddy/traddy on both
halos (undo a shutdown drain — haproxy MAINT survives traddy reboots),
then fire a warm-up completion so the first real request skips the
~165 s cold load. stdlib-only.
"""
import json
import subprocess
import time
import urllib.request

import os
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HALOS = [("192.168.50.184", "/home/piero/Piero/Work/Qwen-3.8-27B_Strix-Halo_gfx1151"),
         ("192.168.50.15", "/home/piero/Qwen-3.8-27B_Strix-Halo_gfx1151")]
WARM_MODEL = "Qwen-35B-coding"  # the flagship lane model


def sh(cmd, timeout=20):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip()


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} [lane-enable] {msg}", flush=True)


def main():
    sh(f"git -C {REPO} pull --ff-only -q || true")
    # wait for the local router (max 240 s)
    for _ in range(48):
        try:
            with urllib.request.urlopen("http://127.0.0.1:1234/health", timeout=3) as r:
                if json.loads(r.read()).get("status") == "ok":
                    break
        except Exception:
            pass
        time.sleep(5)
    else:
        log("router never became healthy — skipping enable")
        return 1
    for ip, repo in HALOS:
        rc, out = sh(f"ssh -o ConnectTimeout=8 -o BatchMode=yes piero@{ip} "
                     f"'sudo -n /usr/bin/python3 {repo}/fleet/haproxy-drain.py enable traddy/traddy'")
        log(f"enable on {ip}: rc={rc} {out or ''}")
    # warm-up in background: preload the flagship so first requests skip the cold load
    subprocess.Popen(["bash", "-c",
        f"curl -s --max-time 600 -o /dev/null http://127.0.0.1:1234/v1/chat/completions "
        f"-H 'Content-Type: application/json' -d '{{\"model\":\"{WARM_MODEL}\","
        f"\"messages\":[{{\"role\":\"user\",\"content\":\"ping\"}}],\"max_tokens\":1}}' &"])
    log(f"lane enabled; warm-up fired for {WARM_MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
