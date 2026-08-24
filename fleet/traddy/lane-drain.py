#!/usr/bin/env python3
"""lane-drain (traddy) — drain the capability lane before this box shuts down.

traddy is NOT a VIP member, so "drain" = disable server traddy/traddy on
BOTH halos' haproxy (whichever owns the VIP serves traffic; disabling on
both is idempotent and covers a failover mid-shutdown), then wait until
the lane's scur == 0 on both (in-flight generations finish), capped.

Run from fleet-pre-drain.service (system unit, User=admin,
Before=shutdown.target). Never blocks shutdown on failure — the halos'
health checks pull the lane DOWN anyway; this only saves the in-flight
requests. Re-enable at boot: lane-enable.py.
stdlib-only.
"""
import os
import subprocess
import time

HALOS = [("192.168.50.184", "/home/piero/Piero/Work/Qwen-3.8-27B_Strix-Halo_gfx1151"),
         ("192.168.50.15", "/home/piero/Qwen-3.8-27B_Strix-Halo_gfx1151")]
WAIT_CAP = int(os.environ.get("FLEET_DRAIN_WAIT", "120"))
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "results", "lane-drain.log")


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [traddy] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        open(LOG, "a").write(line + "\n")
    except Exception:
        pass


def sh(cmd, timeout=20):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip()


def drain(action):
    """disable|enable traddy/traddy on both halos via their scoped sudoers."""
    for ip, repo in HALOS:
        rc, out = sh(f"ssh -o ConnectTimeout=8 -o BatchMode=yes piero@{ip} "
                     f"'sudo -n /usr/bin/python3 {repo}/fleet/haproxy-drain.py {action} traddy/traddy'")
        log(f"{action} traddy/traddy on {ip}: rc={rc} {out or ''}")


def scur(ip):
    rc, out = sh(f"ssh -o ConnectTimeout=8 -o BatchMode=yes piero@{ip} "
                 "\"curl -s --max-time 4 'http://127.0.0.1:8404/;csv'\"", timeout=15)
    if rc != 0:
        return None
    for line in out.splitlines():
        f = line.lstrip("# ").split(",")
        if len(f) > 5 and f[0] == "traddy" and f[1] == "traddy":
            try:
                return int(f[4])
            except ValueError:
                return None
    return None


def main():
    log(f"lane drain starting (cap {WAIT_CAP}s)")
    drain("disable")
    waited = 0
    while waited < WAIT_CAP:
        counts = [scur(ip) for ip, _ in HALOS]
        if all(c == 0 for c in counts):
            log(f"lane drained clean at {waited:.0f}s (scur=0 on both halos)")
            return 0
        time.sleep(2)
        waited += 2
    log("wait-cap reached — proceeding (in-flight lane requests may 502)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
