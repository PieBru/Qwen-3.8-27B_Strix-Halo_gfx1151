#!/usr/bin/env python3
"""fleet_dashboard — minimalist HTMX dashboard for the two-Halo fleet.

One stdlib-only agent per halo (no deps, no build). Serves:
  /            the page (HTMX polls /fragment every 5 s)
  /fragment    dashboard HTML fragment (aggregates BOTH halos)
  /.metrics    this halo's local stats as JSON (peer fetches it)
  /htmx.min.js vendored htmx (no CDN, air-gap safe)

Exposed via haproxy on the VIP (:8082) — inherits the fleet's HA. Each
agent binds 0.0.0.0:8082 (LAN-only surface, like the routers); when an
agent renders the dashboard it pulls its peer's /.metrics directly over
the LAN, so the view is complete from whichever halo answers.

Data sources (all read-only, no root): router /health + /v1/models,
/proc (mem/load/uptime), shutil disk, systemctl is-active (user+system
units), journalctl -k ring events (24 h), gpu-canary log tail, git HEAD,
haproxy stats CSV (127.0.0.1:8404), ip addr (VIP ownership).

Deploy: see fleet/fleet-dashboard.service (systemd user unit; linger on).
"""
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8082
VIP = "192.168.50.10"
HALO = socket.gethostname()
if HALO == "strixy2":
    OWN_IP, PEER_IP, PEER_NAME = "192.168.50.184", "192.168.50.15", "strixy-9ad3"
else:
    OWN_IP, PEER_IP, PEER_NAME = "192.168.50.15", "192.168.50.184", "strixy2"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANARY_LOG = os.path.join(REPO, "results", "gpu-canary.log")
ROUTER = "http://127.0.0.1:8080"

def sh(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None

def fetch_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None

def local_metrics():
    m = {}
    m["halo"] = HALO
    m["ts"] = time.time()
    m["uptime_s"] = int(float(open("/proc/uptime").read().split()[0]))
    la = open("/proc/loadavg").read().split()
    m["load1"] = float(la[0]); m["load5"] = float(la[1])
    mi = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if ":" in l}
    m["mem_avail_gb"] = round(mi.get("MemAvailable", 0) / 1e6, 1)
    m["mem_total_gb"] = round(mi.get("MemTotal", 0) / 1e6, 1)
    m["cached_gb"] = round(mi.get("Cached", 0) / 1e6, 1)
    m["swap_used_gb"] = round((mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)) / 1e6, 1)
    du = shutil.disk_usage("/")
    m["disk_free_gb"] = round(du.free / 1e9, 0)
    # router
    h = fetch_json(f"{ROUTER}/health", 2)
    m["router_health"] = bool(h and h.get("status") == "ok")
    models = fetch_json(f"{ROUTER}/v1/models", 2)
    m["recipes"] = len(models["data"]) if models else 0
    # units
    m["router_unit"] = sh("systemctl --user is-active llama-router.service") == "active"
    m["keepalived"] = sh("systemctl is-active keepalived") == "active"
    m["haproxy"] = sh("systemctl is-active haproxy") == "active"
    m["canary_timer"] = sh("systemctl --user is-active gpu-canary.timer") == "active"
    m["dream_timer"] = sh("systemctl --user is-active pi-dream.timer") == "active"
    # VIP
    m["vip_owner"] = bool(sh(f"ip -4 addr show | grep -c '{VIP}/'"))
    # git
    m["git"] = sh(f"cd {REPO} && git rev-parse --short HEAD") or "?"
    # canary log
    try:
        tail = open(CANARY_LOG).read().strip().splitlines()[-1]
        m["canary_last"] = tail[:120]
        m["canary_age_min"] = round((time.time() - os.path.getmtime(CANARY_LOG)) / 60, 1)
    except Exception:
        m["canary_last"] = None; m["canary_age_min"] = None
    # kernel ring events last 24h
    rings = sh("journalctl -k --since '24 hours ago' --no-pager 2>/dev/null | grep -c 'ring .* timeout'") or "0"
    m["ring_events_24h"] = int(rings) if rings.isdigit() else 0
    # haproxy backend stats (request totals per backend)
    m["haproxy_stats"] = haproxy_csv()
    return m

def haproxy_csv():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8404/;csv", timeout=3) as r:
            lines = r.read().decode().splitlines()
    except Exception:
        return None
    if not lines:
        return {}
    hdr = lines[0].lstrip("# ").split(",")
    ix = {n: i for i, n in enumerate(hdr)}
    out = {}
    for l in lines[1:]:
        f = l.split(",")
        if len(f) < len(hdr) or f[ix["svname"]] not in ("halo1", "halo2"):
            continue
        g = lambda n: f[ix[n]] if n in ix else "0"
        try:
            out[f[ix["svname"]]] = {"status": g("status"),
                                     "stot": int(float(g("stot") or 0)),
                                     "hrsp_2xx": int(float(g("hrsp_2xx") or 0))}
        except ValueError:
            continue
    return out

PILL = '<span class="p {}">{}</span>'

def pill(ok, label_ok, label_bad="DOWN"):
    return PILL.format("ok" if ok else "bad", label_ok if ok else label_bad)

def halo_card(m):
    if m is None or m.get("unreachable"):
        name = (m or {}).get("halo", PEER_NAME)
        return f'<div class="card"><h3>{name}</h3>{PILL.format("bad","UNREACHABLE")}</div>'
    up_h, up_m = divmod(m["uptime_s"], 3600)
    rows = [
        ("router", pill(m["router_health"], f'OK · {m["recipes"]} recipes')),
        ("units", pill(m["router_unit"] and m["keepalived"] and m["haproxy"], "router·vrrp·lb")),
        ("vip", PILL.format("ok", "OWNS VIP") if m["vip_owner"] else '<span class="p dim">standby</span>'),
        ("RAM", f'{m["mem_avail_gb"]} GB avail / {m["mem_total_gb"]} · cache {m["cached_gb"]} · swap {m["swap_used_gb"]}'),
        ("load", f'{m["load1"]} / {m["load5"]} · up {up_h}h{up_m:02d}m'),
        ("disk", f'{m["disk_free_gb"]:.0f} GB free'),
        ("canary", pill(bool(m["canary_last"]), (m["canary_last"] or "")[:44] + f' ({m["canary_age_min"]}m ago)') if m["canary_last"] else PILL.format("bad", "no log")),
        ("kernel", pill(m["ring_events_24h"] == 0, "0 ring events 24h", f'{m["ring_events_24h"]} RING TIMEOUTS')),
        ("git", m["git"]),
    ]
    trs = "".join(f'<tr><td class="k">{k}</td><td>{v}</td></tr>' for k, v in rows)
    return f'<div class="card"><h3>{m["halo"]}</h3><table>{trs}</table></div>'

def doctor(local, peer):
    checks = []
    def add(name, ok, note=""):
        checks.append((name, ok, note))
    both = [m for m in (local, peer) if m]
    add("both halos reachable", len(both) == 2)
    if both:
        add("git parity", all(m["git"] == both[0]["git"] for m in both), both[0]["git"])
        add("exactly one VIP owner", sum(bool(m["vip_owner"]) for m in both) == 1)
        add("all core units up", all(m["router_unit"] and m["keepalived"] and m["haproxy"] for m in both))
        add("routers healthy", all(m["router_health"] for m in both))
        add("canary timers armed", all(m["canary_timer"] for m in both))
        add("no kernel ring events 24h", all(m["ring_events_24h"] == 0 for m in both))
        add("swap low (<8 GB)", all(m["swap_used_gb"] < 8 for m in both))
        add("disk >100 GB free", all(m["disk_free_gb"] > 100 for m in both))
    trs = ""
    for name, ok, note in checks:
        trs += (f'<tr><td>{PILL.format("ok","OK") if ok else PILL.format("bad","FAIL")}</td>'
                f'<td>{name}</td><td class="dim">{note}</td></tr>')
    return f'<div class="card wide"><h3>fleet doctor</h3><table>{trs}</table></div>'

def load_split(local):
    st = (local or {}).get("haproxy_stats") or {}
    t = sum(v["stot"] for v in st.values())
    rows = ""
    # haproxy server names -> real hostnames so the operator can correlate
    DISPLAY = {"halo1": "strixy2", "halo2": "strixy-9ad3"}
    for b in ("halo1", "halo2"):
        s = st.get(b)
        disp = DISPLAY.get(b, b)
        if s:
            share = 100 * s["stot"] / t if t else 0
            rows += (f'<tr><td class="k">{disp}</td><td>{PILL.format("ok", s["status"]) if s["status"]=="UP" else PILL.format("bad", s["status"])}</td>'
                     f'<td>{s["stot"]} req</td><td>{share:.0f}%</td></tr>')
        else:
            rows += f'<tr><td class="k">{disp}</td><td>{PILL.format("bad","no stats")}</td><td>—</td><td>—</td></tr>'
    return f'<div class="card"><h3>load split (haproxy)</h3><table>{rows}</table></div>'

def fragment():
    local = local_metrics()
    peer = fetch_json(f"http://{PEER_IP}:{PORT}/.metrics", 3)
    # STABLE card order: sort by halo hostname so the cards never swap
    # sides when the dashboard-serving halo changes (operator request).
    cards = sorted([m for m in (local, peer) if m], key=lambda m: m["halo"])
    names = [c["halo"] for c in cards]
    # peer placeholder card keeps the slot when unreachable
    if len(cards) < 2:
        missing = PEER_NAME if (local and len(cards) == 1) else "peer"
        from html import escape as esc
        cards.append({"halo": missing, "unreachable": True})
    vip_owner = next((c["halo"] for c in cards if c.get("vip_owner")), "?")
    hdr = (f'fleet · VIP {VIP}:8081 · dashboard served by <b>{HALO}</b> · '
           f'VIP owner <b>{vip_owner}</b> · {time.strftime("%H:%M:%S")}')
    h = (f'<div class="hdr">{hdr}</div>'
         f'<div class="grid">{halo_card(cards[0])}{halo_card(cards[1])}</div>'
         f'<div class="grid">{doctor(local, peer)}{load_split(local)}</div>')
    return h

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Halo Fleet</title><script src="/htmx.min.js"></script><style>
:root{color-scheme:dark}
body{font:14px/1.45 ui-monospace,monospace;background:#0e1116;color:#cdd6e1;margin:0;padding:16px}
.hdr{color:#7aa2f7;margin-bottom:12px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px;margin-bottom:12px}
.card{background:#151a22;border:1px solid #232b38;border-radius:8px;padding:12px}
.card h3{margin:0 0 8px;color:#9ece6a;font-size:13px;text-transform:lowercase}
table{border-collapse:collapse;width:100%}td{padding:2px 8px 2px 0;vertical-align:top}
td.k{color:#565f89;white-space:nowrap}
.p{padding:0 8px;border-radius:10px;font-size:12px}
.p.ok{background:#1b2b1f;color:#9ece6a}.p.bad{background:#2f1b1b;color:#f7768e}
.p.dim{background:#1d222c;color:#565f89}
.dim{color:#565f89}
</style></head><body>
<div id="dash" hx-get="/fragment" hx-trigger="load, every 5s">loading fleet…</div>
</body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/fragment":
            self._send(200, fragment())
        elif self.path == "/.metrics":
            self._send(200, json.dumps(local_metrics()), "application/json")
        elif self.path == "/htmx.min.js":
            js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_htmx.min.js"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(js)))
            self.end_headers()
            self.wfile.write(js)
        elif self.path == "/":
            self._send(200, PAGE)
        else:
            self._send(404, "nope")

if __name__ == "__main__":
    print(f"fleet_dashboard on {OWN_IP}:{PORT} ({HALO}, peer {PEER_NAME})", flush=True)
    ThreadingHTTPServer((OWN_IP, PORT), H).serve_forever()
