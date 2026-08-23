# Fleet HA — the mirrored-Halo reliability stack (as built)

> From [Multi-Halo fleet](MULTI-HALO.md) · master plan: [FLEET-PLAN.md](FLEET-PLAN.md)

**Status: BUILT & DRILL-VERIFIED 2026-08-24.** Everything in this page is
running in production on both halos right now.

## The one-address model

Clients point at **`192.168.50.10:8081`** (the VIP) and nothing else. That
address is owned by exactly one halo at a time (VRRP); a haproxy on the VIP
owner spreads requests across both routers. Direct per-box access
(`:8080`) stays available for debugging.

## Components (all configs committed under `fleet/`)

| Piece | What | Where |
|---|---|---|
| keepalived | VRRP instance `LLAMAS` (id 51): halo1 MASTER prio 150 (preemptive), halo2 BACKUP prio 100; advert 1 s; auth PASS | `/etc/keepalived/keepalived.conf` (from `fleet/keepalived-halo{1,2}.conf`) |
| haproxy | frontend `llamas` on VIP:8081 → backend `halos` (leastconn, `httpchk GET /health`, inter 2s); dashboard frontend on VIP:8082; loopback stats on 127.0.0.1:8404 | `/etc/haproxy/haproxy.cfg` (from `fleet/haproxy.cfg`) |
| sysctl | `net.ipv4.ip_nonlocal_bind=1` — lets the BACKUP's haproxy bind the VIP before owning it | `/etc/sysctl.d/91-haproxy-vip.conf` |
| fleet-dashboard | stdlib-only HTMX agent per halo (LAN IP :8082): per-halo cards, fleet doctor, load split; 5 s auto-refresh | `fleet/fleet_dashboard.py` + `fleet/fleet-dashboard.service` (user unit) |
| GPU canary | per-halo probe (health green + 1-token completion dead ×2 → reboot via scoped sudoers) | `gpu_canary.py` + `systemd-units/gpu-canary.{service,timer}` |

## As-built lessons (why :8081 and other details)

1. **The routers bind `0.0.0.0:8080`**, which shadows any VIP on :8080 —
   the VIP frontend therefore listens on **:8081**. Same for the dashboard:
   agents bind their **per-box LAN IP** (:8082), not 0.0.0.0.
2. **`ip_nonlocal_bind`** is required on BOTH boxes or the BACKUP's haproxy
   crash-loops while it doesn't own the VIP.
3. **Repo units must be path-agnostic**: the fleet's repo layouts differ
   (`~/Piero/Work/<repo>` on dev, `~/<repo>` on halo2) — units resolve both.
4. haproxy CSV stats are parsed **header-based** (field order is not stable
   across versions).

## Verified behavior (2026-08-24 drills, all OBSERVED)

- VIP serving + alias completion through :8081 (`VIP-OK`, served by
  `Qwen38-27B-balanced`).
- **Failover**: stop halo1's keepalived+haproxy → VIP moved to halo2 in
  **<4 s** → completion served transparently (`FAILOVER-OK`).
- **Restore**: MASTER preempted, VIP reclaimed, halo2 released it, health
  green. No split-brain observed (exactly-one-VIP check is a doctor rule).
- Dashboard via VIP:8082 during all of the above: kept rendering from the
  surviving halo, showing the current server and VIP owner.

## Deploy discipline (the rule the doctor enforces)

Fleet deploys are **git push on the dev box → `git pull --ff-only` on the
peer** — never scp'd file copies. Hot-scping a script to one halo works
until the next parity check catches the drift (this happened once, 2026-08-24:
the dashboard's git-parity FAIL flagged an scp-hot-deployed agent; fixed by
checkout + ff-pull). The doctor's parity row exists precisely to catch this.

## Known limits (documented, not hidden)

- **In-flight requests die on failover.** Stateless HTTP + client retry
  recovers in one request. No proxy can do better without state migration.
- **KV cache does not migrate.** The survivor re-prefills the conversation
  (seconds shallow; ~a minute at 100k+ filled — priced in the e4 decay
  table).
- **VRRP needs protocol 112** on the LAN switch (ubiquitous) and root for
  keepalived (system units, enabled).
- Preemptive failback causes one blip when the MASTER returns — acceptable
  here; switch to `nopreempt` if a halo flaps.

## Client wiring

| Client | Recommendation |
|---|---|
| scripts / curl / cron | `http://192.168.50.10:8081` |
| WebUI presets | same |
| **pi** | keep direct `localhost`/LAN providers (the pi-llama-cpp extension lists both routers — richer than the VIP for model load/unload management) |
| **Ciao** | primary → VIP; keep its loud `fallback_base_url` as belt-and-suspenders |
| dashboard | `http://192.168.50.10:8082` (bookmarks retire the SSH consoles) |

## Growth path (not needed for 2 backends)

External HA proxy pairs (e.g. 2× Raspberry Pi) only earn their keep at
3+ backends, TLS termination, or mixed services — documented in
[FLEET-PLAN.md](FLEET-PLAN.md) Phase R2.5 as the upgrade path, deliberately
not built for the pair.
