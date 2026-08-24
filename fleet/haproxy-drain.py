#!/usr/bin/env python3
"""haproxy-drain — whitelisted haproxy runtime-socket commands (run via sudo).

The stats socket /var/run/haproxy-master.sock is root-owned. This helper
accepts EXACTLY two command shapes (anything else exits 2, no shell, no
arbitrary passthrough):

    sudo python3 haproxy-drain.py disable halos/halo2
    sudo python3 haproxy-drain.py enable  halos/halo2

Scope-limited by the sudoers grant (pattern: gpu-canary-reboot). Used by
fleet-pre-drain.py (automatic, at shutdown) and by hand for planned moves
(see docs/FLEET-HA.md — pre-drain procedure).
"""
import re
import socket
import sys

SOCK = "/var/run/haproxy-master.sock"
# backend/server: halos/halo1, halos/halo2, dashb/halo1, dashb/halo2
VALID = re.compile(r"^(disable|enable) (halos|dashb)/halo[12]$")

def main():
    if len(sys.argv) != 3:
        print("usage: haproxy-drain.py disable|enable backend/server", file=sys.stderr)
        return 2
    cmd = f"{sys.argv[1]} {sys.argv[2]}"
    if not VALID.match(cmd):
        print(f"refused (not whitelisted): {cmd!r}", file=sys.stderr)
        return 2
    s = socket.socket(socket.AF_UNIX)
    s.connect(SOCK)
    s.sendall(cmd.encode() + b"\n")
    s.shutdown(socket.SHUT_WR)
    out = b""
    while True:
        b = s.recv(65536)
        if not b:
            break
        out += b
    s.close()
    # empty reply = accepted; haproxy only answers errors
    print((out.decode(errors="replace").strip() or "ok")[:200])
    return 0

if __name__ == "__main__":
    sys.exit(main())
