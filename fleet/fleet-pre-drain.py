#!/usr/bin/env python3
"""fleet-pre-drain — automatic zero-loss drain at shutdown.

Runs from fleet-pre-drain.service (SYSTEM unit, Before=shutdown.target,
User=piero — see that file for why system-level: user units cannot order
against system shutdown targets). Steps:

1. Which halo am I? (halo1=strixy2, halo2=strixy-9ad3 — same mapping the
   dashboard uses.)
2. Who owns the VIP? (ip addr on self → I own; else the peer does.)
3. Disable MY server on the OWNER's haproxy:
   - I own    -> sudo python3 <repo>/fleet/haproxy-drain.py disable halos/<me>
   - peer owns-> ssh piero@<peer> sudo python3 <repo>/fleet/haproxy-drain.py ...
   (works for both roles: each haproxy defines BOTH backends, so the owner
   keeps serving VIP traffic through the survivor while I drain)
4. Wait for my in-flight sessions to finish: poll the owner's haproxy CSV
   (127.0.0.1:8404 loopback; peer's via ssh) until MY server's scur == 0,
   capped at FLEET_DRAIN_WAIT (default 120 s). Shutdown then proceeds.

Notes:
- system findings are logged to results/fleet-pre-drain.log + the journal.
- If shutdown is CANCELLED after this ran (rare), my server stays in MAINT:
  re-enable with haproxy-drain.py enable halos/<me> (dashboard shows MAINT).
- A hard mains cut / long-press bypasses all of this by definition — the
  boot gate (fleet-boot-gate) is the insurance there.
stdlib-only.
"""
import os
import re
import subprocess
import sys
import time
import urllib.request

VIP = "192.168.50.10"
HALOS = {"strixy2": ("halo1", "192.168.50.184", "192.168.50.15"),
         "strixy-9ad3": ("halo2", "192.168.50.15", "192.168.50.184")}
ME, OWN_IP, PEER_IP = HALOS[os.uname().nodename]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAIN_WAIT = int(os.environ.get("FLEET_DRAIN_WAIT", "120"))
LOG = os.path.join(REPO, "results", "fleet-pre-drain.log")


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{ME}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        open(LOG, "a").write(line + "\n")
    except Exception:
        pass


def sh(cmd, timeout=10):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def i_own_vip():
    rc, out, _ = sh(f"ip -4 addr show | grep -c '{VIP}/'")
    return rc == 0 and out.strip() == "1"


def haproxy_cmd(action, remote=None):
    """disable/enable my server on the VIP owner's haproxy socket."""
    arg = f"{action} halos/{ME}"
    script = f"{REPO}/fleet/haproxy-drain.py"
    if remote is None:
        return sh(f"sudo -n /usr/bin/python3 {script} {arg}", timeout=15)
    return sh(f"ssh -o ConnectTimeout=8 -o BatchMode=yes piero@{remote} "
              f"'sudo -n /usr/bin/python3 {script} {arg}'", timeout=25)


def my_scur(remote=None):
    """current sessions on MY backend server, from the owner's haproxy CSV."""
    if remote is None:
        try:
            csv = urllib.request.urlopen("http://127.0.0.1:8404/;csv", timeout=4).read().decode()
        except Exception:
            return None
    else:
        rc, out, _ = sh(f"ssh -o ConnectTimeout=8 -o BatchMode=yes piero@{remote} "
                        f"'curl -s --max-time 4 http://127.0.0.1:8404/;csv'", timeout=15)
        if rc != 0:
            return None
        csv = out
    for line in csv.splitlines():
        f = line.lstrip("# ").split(",")
        if len(f) > 5 and f[0] == "halos" and f[1] == ME:
            try:
                return int(f[4])  # scur: current sessions
            except ValueError:
                return None
    return None


def main():
    owner = "self" if i_own_vip() else "peer"
    log(f"shutdown drain starting: I am {ME}, VIP owner={owner}, wait-cap={DRAIN_WAIT}s")
    rc, out, err = haproxy_cmd("disable", remote=None if owner == "self" else PEER_IP)
    log(f"disable halos/{ME} on {owner}: rc={rc} {out or err}")
    if rc != 0:
        log("drain FAILED to disable — proceeding with shutdown (failover covers new requests)")
        return 0  # never block shutdown on drain failure; health checks cover us
    waited = 0.0
    while waited < DRAIN_WAIT:
        n = my_scur(remote=None if owner == "self" else PEER_IP)
        if n is None:
            log(f"scur unavailable at {waited:.0f}s — continuing")
            break
        if n == 0:
            log(f"drained clean at {waited:.0f}s (scur=0) — safe to power off")
            return 0
        time.sleep(2)
        waited += 2
    log(f"wait-cap reached ({DRAIN_WAIT}s) or sessions stuck — proceeding (in-flight sessions may see 502)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
