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
- **Halo-death drill (2026-08-24)**: with halo2's keepalived+haproxy+
  dashboard-agent stopped, the VIP dashboard kept rendering from strixy2 —
  halo2's card held its slot as red `UNREACHABLE`, doctor row
  `FAIL: both halos reachable`, load split showed it `DOWN`, and inference
  through VIP:8081 continued (`HALO2-DOWN-OK`). On restore: all pills green,
  both cards live, `both-reachable OK`. The dashboard is exactly as
  available as the fleet (shares its fate by design); per-box agents also
  listen on their real IPs (`:8082`) so any breathing box can show the
  fleet state directly.

## Planned maintenance — the AUTOMATIC pre-drain (2026-08-24, verified)

An **unplanned** halo death costs the in-flight session (one 502, observed
2026-08-24: `Server halos/halo2 is DOWN … 1 sessions active`). A shutdown
that goes through systemd — **CLI (`poweroff`/`reboot`/`halt`) AND the
short-press ACPI power button** (observed: the button runs the systemd
shutdown sequence) — now drains automatically:

- **`fleet/fleet-pre-drain.service`** (SYSTEM unit — user units cannot
  order against system shutdown targets; `Before=shutdown.target`,
  `WantedBy=shutdown.target`, `User=piero`, enabled on both boxes) runs
  `fleet/fleet-pre-drain.py` at shutdown: identifies the VIP owner,
  disables **my** server on the OWNER's haproxy (local socket via the
  scoped sudoers grant if I own it; the peer's socket over SSH otherwise —
  works for both roles since every haproxy defines both backends), then
  waits for my `scur == 0` from the owner's `8404/;csv` (in-flight
  generations finish), capped at 120 s (`FLEET_DRAIN_WAIT`). Never blocks
  shutdown on its own failure — failover covers.
- **`fleet/haproxy-drain.py`** — the whitelisted root helper behind the
  scoped `fleet-haproxy-drain` sudoers grant (gpu-canary-reboot pattern).
  Dry-test-verified gotchas baked in: the runtime API needs the literal
  `server` word; `/var/run/haproxy-master.sock` is the MASTER socket so
  commands route via the `@1` worker prefix; empty reply = success.
  Manual form: `sudo python3 fleet/haproxy-drain.py disable halos/halo2`.
- **Verified 2026-08-24 (dry, both ownership paths)**: owner=self
  (strixy2): disable → CSV `MAINT` → `drained clean (scur=0)` → enable →
  `UP`. owner=peer (from strixy-9ad3 over SSH): peer-path drain incl.
  remote CSV poll → `MAINT` → restore → `UP`. The under-fire path (a real
  button/CLI shutdown with the hook armed) is checked at the next real
  move. A hard long-press or mains cut bypasses all of this by definition
  — that's what the boot insurance below is for.
- If a shutdown is CANCELLED after the drain ran, my server stays MAINT:
  re-enable by hand (`haproxy-drain.py enable halos/<me>`; the dashboard
  load-split shows MAINT).

## Boot insurance — two levels at every boot (2026-08-24, verified)

"**Cheap insurance**" for what no shutdown hook can cover (mains cut,
long-press hard off) plus a fast always-on gate for every boot:

- **`fleet/fleet-boot-gate.service`** (user unit, `WantedBy=default.target`,
  both boxes) runs `fleet/fleet-boot-gate.py` at boot BEFORE the router
  (`llama-router.service` carries `Requires=` + `After=`):
  - **L1 app**: size + first/last 1 MiB sha256 of all 5 weights vs
    `fleet/boot-gate-baseline.json` (pinned beside the full sha256s in
    models.ini) — ~0.2 s; catches gross corruption before the router
    EVER serves. **A failed gate leaves the router DOWN** (sabotage-
    guarded: broken baseline → gate rc=1 → router start REFUSED).
  - **L2 system**: prev-boot clean-shutdown classifier (journal markers),
    kernel fs/IO error lines this boot, err-priority count — REPORTED,
    never blocking (an UNCLEAN prev boot is the insurance *kicking in*,
    not a failure). Surfaced on each halo card's `boot` row and the
    doctor's `boot insurance ran this boot` check.
- The full 45 s hashcheck remains nightly (02:30 Europe/Rome,
  `fleet-hashcheck.timer`); after ANY physical power cycle, run it by hand
  too (`python3 fleet/fleet-hashcheck.py` — verified 5/5 after the
  2026-08-24 move).

## Deploy discipline (the rule the doctor enforces)

Fleet deploys are **git push on the dev box → `git pull --ff-only` on the
peer** — never scp'd file copies. Hot-scping a script to one halo works
until the next parity check catches the drift (this happened once, 2026-08-24:
the dashboard's git-parity FAIL flagged an scp-hot-deployed agent; fixed by
checkout + ff-pull). The doctor's parity row exists precisely to catch this.

## Session affinity (sticky by client IP) — as built

Steady-state bouncing — a reconnecting client ping-ponging between halos and
thrashing both KV caches every request — is eliminated: the backend carries

    stick-table type ip size 100k expire 24h
    stick on src

Semantics (verified live 2026-08-24): a **fresh** client is assigned by
leastconn (the *less-busy* halo — demonstrated with a held generation on one
halo routing the new client to the other); from then on the client IP sticks
to that halo (warm prefix cache; `X-Served-By` response header names the
server for debugging). Different clients → different halos → **parallel
full-speed serving** (two agents = one per box, better than 2-on-1: e5).
Failover: stuck clients move to the survivor — each pays exactly **one**
re-prefill (the acceptable, one-time cost — not to be confused with the
per-request thrash affinity kills). Known nuances: (a) two agents behind one
IP pin together (np=1 keeps their keep-alive connections independent — they
queue per halo; if that pattern ever hurts, the knob is `-np 2` on the
routers or per-path hashing); (b) the stick table is per-haproxy-instance —
on VIP failover the new owner's table is empty and reassigns once (peers
table-sync is the documented upgrade if that one bounce ever matters);
(c) `timeout server 30m` on the halos backend so long silent non-streaming
generations (16k-token thinking bursts ≈ 13 min at ~20 t/s) survive the
proxy.

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
