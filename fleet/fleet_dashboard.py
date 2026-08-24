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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

PORT = 8082
VIP = "192.168.50.10"
HALO = socket.gethostname()
if HALO == "strixy2":
    OWN_IP, PEER_IP, PEER_NAME = "192.168.50.184", "192.168.50.15", "strixy-9ad3"
else:
    OWN_IP, PEER_IP, PEER_NAME = "192.168.50.15", "192.168.50.184", "strixy2"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_HOST_IP = OWN_IP if HALO == "strixy2" else PEER_IP  # strixy2 = reports host
CANARY_LOG = os.path.join(REPO, "results", "gpu-canary.log")
HASHCHECK_STATE = os.path.join(REPO, "results", "fleet-hashcheck.json")
BOOTGATE_STATE = os.path.join(REPO, "results", "boot-gate.json")
# nightly reports (produced on the pi main box — strixy2; dim note on halo2)
REPORTS = {"dream": os.path.expanduser("~/Piero/Work/pi-dream/DREAM_REPORT_latest.md"),
           "scout": os.path.expanduser("~/Piero/Work/pi-scout/SCOUT_REPORT_latest.md")}
REPORTS_HOST = "strixy2"  # the pi main box produces both; others render its state
ROUTER = "http://127.0.0.1:8080"
LOCAL_TZ = ZoneInfo("Europe/Rome")  # DST-tracked; hosts may differ (UTC vs Rome)

def clock():
    return datetime.now(LOCAL_TZ).strftime("%H:%M:%S")

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
    m["git_dirty"] = bool(sh(f"cd {REPO} && git status --porcelain 2>/dev/null | head -1"))
    # canary log
    try:
        tail = open(CANARY_LOG).read().strip().splitlines()[-1]
        m["canary_last"] = tail[:120]
        m["canary_age_min"] = round((time.time() - os.path.getmtime(CANARY_LOG)) / 60, 1)
    except Exception:
        m["canary_last"] = None; m["canary_age_min"] = None
    # boot insurance state (fleet-boot-gate: app weights + system level)
    try:
        bg = json.load(open(BOOTGATE_STATE))
        m["boot_gate_ok"] = bool(bg.get("app", {}).get("ok"))
        m["boot_gate_app"] = bg.get("app", {}).get("summary", "?")
        m["boot_gate_prev_clean"] = bg.get("sys", {}).get("prev_boot_clean")
        m["boot_gate_fs_errs"] = bg.get("sys", {}).get("fs_error_lines")
        m["boot_gate_errs"] = bg.get("sys", {}).get("err_count")
        # did the gate run THIS boot? (state ts must postdate boot start)
        m["boot_gate_this_boot"] = bool(bg.get("ts", 0) >= time.time() - m["uptime_s"] - 60)
    except Exception:
        m["boot_gate_ok"] = None; m["boot_gate_app"] = None
        m["boot_gate_prev_clean"] = None; m["boot_gate_fs_errs"] = None
        m["boot_gate_errs"] = None; m["boot_gate_this_boot"] = False
    # nightly reports state (produced on the reports host; exchanged via
    # /.metrics so ANY renderer shows the same card — no VIP bounce)
    m["reports"] = {}
    if HALO == REPORTS_HOST:
        for kind, p in REPORTS.items():
            try:
                age_h = (time.time() - os.path.getmtime(p)) / 3600
                head = [l for l in open(p, encoding="utf-8").read().splitlines() if l.strip()][:8]
                teaser = next((l for l in head if l.startswith("**Verdict:**") or l.startswith("- **Generated:**")), head[0] if head else "")
                teaser = re.sub(r"^[#*-]+\s*|\*\*", "", teaser)[:88]
                m["reports"][kind] = {"age_h": round(age_h, 1), "teaser": teaser}
            except Exception:
                pass
    # nightly GGUF hash verification state (fleet-hashcheck)
    try:
        hc = json.load(open(HASHCHECK_STATE))
        m["weights_ok"] = bool(hc.get("ok"))
        m["weights_summary"] = hc.get("summary", "?")
        m["weights_age_h"] = round((time.time() - hc.get("ts", 0)) / 3600, 1)
    except Exception:
        m["weights_ok"] = None; m["weights_summary"] = None; m["weights_age_h"] = None
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

# numeric health thresholds (bad => bold red; good => quiet green note)
THR = {
    "mem_avail_gb": (20, "RAM LOW"),        # < 20 GB free is fleet-unhealthy
    "swap_used_gb": (8, "SWAPPING"),        # zram churn tax (lesson #2)
    "load1": (24, "CPU SAT"),               # > 1.5x cores sustained
    "disk_free_gb": (100, "DISK LOW"),      # GB free on /
}

# direction per metric: UPPER = "bad when ABOVE limit"; LOWER = "bad when BELOW"
DIRECTION = {"mem_avail_gb": "LOWER", "disk_free_gb": "LOWER",
             "swap_used_gb": "UPPER", "load1": "UPPER"}

def num_pill(m, key, text):
    """Render a numeric metric: red+bold pill if past threshold, green note otherwise."""
    limit, label = THR[key]
    val = m.get(key)
    if val is None:
        return PILL.format("bad", "n/a")
    bad = (val > limit) if DIRECTION[key] == "UPPER" else (val < limit)
    if bad:
        return PILL.format("bad", f'{label}: {text}')
    return f'<span class="p ok">{text}</span>'

def halo_card(m):
    if m is None or m.get("unreachable"):
        name = (m or {}).get("halo", PEER_NAME)
        return f'<div class="card"><h3>{name}</h3>{PILL.format("bad","UNREACHABLE")}</div>'
    up_d, up_rem = divmod(m["uptime_s"], 86400)
    up_h, up_m = divmod(up_rem, 3600)
    up_s = f"{up_d}d{up_h}h" if up_d else f"{up_h}h{up_m:02d}m"
    rows = [
        ("router", pill(m["router_health"], f'OK · {m["recipes"]} recipes')),
        ("units", pill(m["router_unit"] and m["keepalived"] and m["haproxy"], "router·vrrp·lb")),
        ("RAM", num_pill(m, "mem_avail_gb", f'{m["mem_avail_gb"]} GB avail / {m["mem_total_gb"]} · cache {m["cached_gb"]} GB')),
        ("swap", num_pill(m, "swap_used_gb", f'{m["swap_used_gb"]} GB in zram')),
        ("load", num_pill(m, "load1", f'{m["load1"]} / {m["load5"]} · up {up_s}')),
        ("disk", num_pill(m, "disk_free_gb", f'{m["disk_free_gb"]:.0f} GB free')),
        ("canary", pill(bool(m["canary_last"]), (m["canary_last"] or "")[:44] + f' ({m["canary_age_min"]}m ago)') if m["canary_last"] else PILL.format("bad", "no log")),
        ("weights", (pill(m.get("weights_ok"), f'{m.get("weights_summary")} GGUF OK · {m.get("weights_age_h")}h ago') if m.get("weights_age_h") is not None else PILL.format("bad", "not verified"))
                   if m.get("weights_ok") is not None else '<span class="p dim">no state yet</span>'),
        ("boot", (pill(m.get("boot_gate_ok") and m.get("boot_gate_this_boot"),
                      f'{m.get("boot_gate_app")} · prev-boot {"clean" if m.get("boot_gate_prev_clean") else "UNCLEAN"} · fs {m.get("boot_gate_fs_errs")} · err {m.get("boot_gate_errs")}')
                  if m.get("boot_gate_ok") is not None else '<span class="p dim">no gate</span>')),
        ("kernel", pill(m["ring_events_24h"] == 0, "0 ring events 24h", f'{m["ring_events_24h"]} RING TIMEOUTS')),
        ("git", (PILL.format("bad", f'{m["git"]}*dirty') if m.get("git_dirty")
                 else (f'<span class="p ok">{m["git"]}</span>' if m.get("git") not in (None, "?") else PILL.format("bad", "?")))),
    ]
    trs = "".join(f'<tr><td class="k">{k}</td><td>{v}</td></tr>' for k, v in rows)
    return f'<div class="card"><h3>{m["halo"]}</h3><table>{trs}</table></div>'

def md_html(text):
    """stdlib markdown-subset renderer for the night reports (headings, hr,
    bold/italic, inline code, links, bullet/numbered lists, pipe tables,
    code fences). Escapes HTML FIRST — report text is never raw HTML."""
    import html as _h
    def inline(t):
        # stash code spans FIRST: their content may contain * [ ] that must
        # not be interpreted as markdown (found the hard way: `results/*.log`
        # inside a **bold** span broke bold rendering)
        t = _h.escape(t, quote=False)
        codes = []
        def _stash(m):
            codes.append(m.group(1)); return f"\x00{len(codes)-1}\x00"
        t = re.sub(r"`([^`]+)`", _stash, t)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", t)
    out, i, in_code, lst = [], 0, False, None
    para = []
    def close():
        nonlocal lst
        if lst: out.append(f"</{lst}>"); lst = None
    def flush_para():
        # join wrapped lines into one paragraph — **bold**/[links] may span them
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
    lines = text.splitlines()
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            flush_para(); close()
            out.append("</pre>" if in_code else "<pre>"); in_code = not in_code; i += 1; continue
        if in_code: out.append(_h.escape(ln)); i += 1; continue
        if not ln.strip(): flush_para(); close(); i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m: flush_para(); close(); n = len(m.group(1)) + 1; out.append(f"<h{n}>{inline(m.group(2))}</h{n}>"); i += 1; continue
        if re.match(r"^[-*_]{3,}\s*$", ln): flush_para(); close(); out.append("<hr>"); i += 1; continue
        m = re.match(r"^\s*[-*]\s+(.*)", ln)
        if m:
            if lst != "ul": flush_para(); close(); out.append("<ul>"); lst = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>"); i += 1; continue
        m = re.match(r"^\s*\d+\.\s+(.*)", ln)
        if m:
            if lst != "ol": flush_para(); close(); out.append("<ol>"); lst = "ol"
            out.append(f"<li>{inline(m.group(1))}</li>"); i += 1; continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush_para(); close()
            hdr = [c.strip() for c in ln.strip().strip("|").split("|")]
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in hdr) + "</tr>")
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in lines[j].strip().strip("|").split("|")) + "</tr>"); j += 1
            out.append("</table>"); i = j; continue
        para.append(ln); i += 1
    flush_para(); close()
    if in_code: out.append("</pre>")
    return "".join(out)

def reports_card(local, peer):
    # state always comes from strixy2 (local or via peer metrics) so the card
    # never bounces between renderers; buttons route to the reports host.
    src = next((m for m in (local, peer) if m and m.get("halo") == REPORTS_HOST), None)
    rows = ""
    for kind in ("dream", "scout"):
        r = (src or {}).get("reports", {}).get(kind)
        if r:
            base = "" if HALO == REPORTS_HOST else f"http://{REPORTS_HOST_IP}:{PORT}"
            rows += (f'<tr><td class="k">{kind}</td>'
                     f'<td><button class="p ok" hx-get="{base}/report/{kind}" hx-target="#modal" '
                     f'hx-swap="innerHTML">{r["age_h"]:.0f}h · open</button></td>'
                     f'<td class="dim">{r["teaser"]}</td></tr>')
        else:
            rows += (f'<tr><td class="k">{kind}</td><td colspan="2">'
                     f'<span class="p bad">reports host unreachable</span></td></tr>')
    return f'<div class="card"><h3>nightly reports</h3><table>{rows}</table></div>'
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
        add("boot insurance ran this boot", all(m.get("boot_gate_ok") is True and m.get("boot_gate_this_boot") for m in both),
            ", ".join(f'{m["halo"]}: {m.get("boot_gate_app")} ({"clean" if m.get("boot_gate_prev_clean") else "UNCLEAN prev"})' for m in both))
        add("weights verified nightly", all(m.get("weights_ok") is True and m.get("weights_age_h", 99) < 26 for m in both),
            ", ".join(f'{m["halo"]}: {m.get("weights_summary", "?")} ({m.get("weights_age_h", "?")}h)' for m in both))
        add("no kernel ring events 24h", all(m["ring_events_24h"] == 0 for m in both))
        add("swap low (<8 GB)", all(m["swap_used_gb"] < 8 for m in both))
        add("disk >100 GB free", all(m["disk_free_gb"] > 100 for m in both))
    trs = ""
    for name, ok, note in checks:
        # dimmed test description (standby style) so a FAIL pill is the only
        # saturated element in the card — operator's eye goes straight to red
        trs += (f'<tr><td>{PILL.format("ok","OK") if ok else PILL.format("bad","FAIL")}</td>'
                f'<td><span class="p dim">{name}</span></td><td class="dim">{note}</td></tr>')
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
            pill_cls = "ok" if s["status"] == "UP" else "bad"
            rows += (f'<tr><td class="k">{disp}</td><td>{PILL.format("ok", s["status"]) if s["status"]=="UP" else PILL.format("bad", s["status"])}</td>'
                     f'<td><span class="p {pill_cls}">{s["stot"]} req</span></td>'
                     f'<td><span class="p {pill_cls}">{share:.0f}%</span></td></tr>')
        else:
            rows += (f'<tr><td class="k">{disp}</td><td>{PILL.format("bad","no stats")}</td>'
                     f'<td>{PILL.format("bad","—")}</td><td>{PILL.format("bad","—")}</td></tr>')
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
    def role_chip(m):
        # one chip per halo: crown for the current VIP owner, sleep otherwise
        if m is None or m.get("unreachable"):
            return f'{PILL.format("bad", "unreachable")}'
        if m.get("vip_owner"):
            return f'👑 <span class="p ok">{m["halo"]} · OWNS VIP</span>'
        return f'💤 <span class="p dim">{m["halo"]} · standby</span>'
    # static title (no bouncing owner text): logo, the common VIP, the clock
    hdr = (f'<span class="logo">Halo Fleet</span> · '
           f'<span class="dim">VIP {VIP}:8081</span> · '
           f'<span class="clock">{clock()}</span>')
    chips = f'<div class="chips">{role_chip(cards[0])}{role_chip(cards[1])}</div>'
    h = (f'<div class="hdr">{hdr}</div>{chips}'
         f'<div class="grid">{halo_card(cards[0])}{halo_card(cards[1])}</div>'
         f'<div class="grid">{doctor(local, peer)}{load_split(local)}</div>'
         f'<div class="grid">{reports_card(local, peer)}</div>')
    return h

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Halo Fleet</title><script src="/htmx.min.js"></script><style>
:root{color-scheme:dark}
body{font:14px/1.45 ui-monospace,monospace;background:#0e1116;color:#cdd6e1;margin:0;padding:16px}
.hdr{color:#7aa2f7;margin-bottom:8px;font-size:14px}
.logo{color:#9ece6a;font-weight:700}
.clock{color:#cdd6e1}
.chips{display:flex;gap:8px;margin-bottom:12px;font-size:13px}
.chips .p{font-size:12px}
#modal{display:none;position:fixed;inset:0;background:#000c;z-index:10;overflow:auto;padding:24px}
#modal:not(:empty){display:flex}
.modalbox{background:#151a22;border:1px solid #232b38;border-radius:8px;max-width:880px;width:100%;height:fit-content;padding:16px;margin:auto}
.md h2{color:#9ece6a;font-size:15px;margin:12px 0 4px}
.md h3,.md h4{color:#7aa2f7;font-size:13px;margin:10px 0 4px}
.md p{margin:4px 0}
.md li{margin:2px 0 0}
.md pre{background:#0e1116;border:1px solid #232b38;border-radius:6px;padding:8px;overflow:auto;font-size:12px;white-space:pre-wrap}
.md code{color:#e0af68}
.md table{border-collapse:collapse;margin:6px 0}
.md th,.md td{border:1px solid #232b38;padding:2px 8px;font-size:12px;text-align:left}
.md a{color:#7aa2f7}
.md hr{border:0;border-top:1px solid #232b38;margin:8px 0}
button.p{cursor:pointer;font-family:inherit}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px;margin-bottom:12px}
.card{background:#151a22;border:1px solid #232b38;border-radius:8px;padding:12px}
.card h3{margin:0 0 8px;color:#9ece6a;font-size:13px;text-transform:lowercase}
table{border-collapse:collapse;width:100%}td{padding:2px 8px 2px 0;vertical-align:top}
td.k{color:#565f89;white-space:nowrap}
.p{padding:0 8px;border-radius:10px;font-size:12px}
.p.ok{background:#1b2b1f;color:#9ece6a}.p.bad{background:#3a1418;color:#ff6b7d;font-weight:700;border:1px solid #f7768e66}
.p.dim{background:#1d222c;color:#565f89}
.dim{color:#565f89}
.g{color:#9ece6a}
</style></head><body>
<div id="dash" hx-get="/fragment" hx-trigger="load, every 5s">loading fleet…</div>
<div id="modal" onclick="this.innerHTML=''"></div>
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
        elif self.path in ("/report/dream", "/report/scout"):
            kind = self.path.rsplit("/", 1)[-1]
            body = None
            if HALO == REPORTS_HOST:
                try:
                    md = open(REPORTS[kind], encoding="utf-8").read()
                    body = md_html(md)
                except Exception:
                    pass
            else:
                # proxy to the reports host so this URL works everywhere
                # simple text proxy: fetch rendered HTML from the reports host
                try:
                    with urllib.request.urlopen(f"http://{REPORTS_HOST_IP}:{PORT}/report/{kind}", timeout=4) as r:
                        body = r.read().decode()
                    # strip the reports host's modalbox wrapper, keep inner .md
                    m = re.search(r'<div class="md">.*</div>', body, re.S)
                    if m: body = m.group(0)
                except Exception:
                    body = None
            if body is not None:
                out = (f'<div class="modalbox" onclick="event.stopPropagation()">'
                       f'<button class="p dim" style="float:right" onclick="document.getElementById(\'modal\').innerHTML=\'\'">close ✕</button>'
                       f'{body if body.startswith("<div class=\"md\"") else f"<div class=\"md\">{body}</div>"}'
                       f'</div>')
                self._send(200, out)
            else:
                self._send(200, '<div class="modalbox"><p>report unavailable (reports host '
                                'down or file missing)</p></div>')
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
