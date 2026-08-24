# Multi-Halo fleet — the complete guide

> From [Qwen3.8-27B on Strix Halo](../README.md) — running TWO (or more) Strix
> Halo boxes as one fleet: transparent HA, load spreading, cluster experiments,
> and the community knowledge that shaped it.

This chapter family documents everything about multi-box operation of Strix
Halo systems, built and **measured on our two-box fleet** (strixy2 + strixy-9ad3,
both Ryzen AI MAX+ 395 / 8060S / 128 GB) plus research into the wider Halo
ecosystem. Cross-links: the master plan is [FLEET-PLAN.md](FLEET-PLAN.md);
the live status surface is the dashboard at `http://192.168.50.10:8082`.

## Contents

- [FLEET-HA.md](FLEET-HA.md) — **the mirrored-Halo reliability stack (BUILT)**:
  one VIP address, keepalived + haproxy, failover drills, the dashboard, and
  the full-throttle ↔ degraded-serve model. Start here — this is what we run.
- [FLEET-CLUSTER.md](FLEET-CLUSTER.md) — **clustering research (planned)**:
  USB4/TB networking, llama.cpp RPC, ds4 pipeline parallelism, RDMA pointers,
  and the community landscape (strixhalo.wiki, ds4, vllm.cpp, the DSV4-Flash
  quality frontier).
- [FLEET-PLAN.md](FLEET-PLAN.md) — the master plan with phases A–R, decision
  rules, and timeboxes (also the log of what was built when).

## The fleet at a glance (as of 2026-08-24)

```
            clients (pi · Ciao · scripts · WebUI)
              │
              ▼  192.168.50.10:8081  (VIP — one address, forever)
        ┌─ keepalived VRRP + haproxy (both halos) ────┐
        │   leastconn + stick(IP) + /health 2 s       │
        │   model-name ACL → capability lane           │
        ▼                                             ▼
   strixy2 (MASTER)                            strixy-9ad3 (BACKUP)
   · router :8080, 10 recipes                  · identical router
   · preload: balanced (alias default)         · same weights, same recipes
   · GPU canary · boot gate · dream nightly    · GPU canary · boot gate
   · fleet dashboard agent :8082               · fleet dashboard agent :8082
   · RPC/ds4/audio.cpp build-ready             · audio.cpp built (Vulkan)
        │                                             │
        └── USB4 direct link ✅ (10.180.243.1/.2, 9.4 Gbps measured) ──┘
                    │
                    ▼  traddy (capability lane, i7 + GTX1070)
                       · :1234 · Tiel-Coder / Ornith / Gemma4 / LFM
                       · routed by model name via VIP:8081, or :8083 direct
```

**Both up** → requests spread leastconn (two clients = two full-speed
instances; measured in [BENCHMARKS.md](BENCHMARKS.md)). **One down** → the
VIP fails over in <4 s (drill-verified); clients retry once and continue.
**Dashboard** → `http://192.168.50.10:8082` shows both halos, the fleet
doctor, and the live load split — no SSH consoles needed for daily ops.

## Design principles (carried over from the repo)

1. **No SPOF, no shared state**: no shared disk, no primary/replica database —
   just two identical boxes. Any box can serve any client alone.
2. **Failures loud, never silent** (learned from Ciao): degraded paths always
   announce themselves — client fallback banners, journal entries, dashboard
   red pills.
3. **Mirror by construction**: configs live in the repo (`fleet/`,
   `systemd-units/`, `models/models.ini`); a box is rebuilt by cloning + running the
   deploy steps — drift shows up as git diffs, not mysteries.
4. **Measure the reliability, don't assume it**: failover drills, the fleet
   doctor's green/red table, canary probes on both boxes.

## Community resources (the Halo ecosystem)

- **[strixhalo.wiki](https://strixhalo.wiki/)** — the community hub: hardware
  guides (boards, BIOS, eGPU, power modes), AI pages (llama.cpp perf, ROCm
  with rocWMMA + hipBLASlt guidance, vLLM), and a
  [Clustering](https://strixhalo.wiki/AI/Clustering) page that independently
  documents the same USB4→thunderbolt-net→llama.cpp-RPC path we're building
  (their numbers: ~9 Gbps over TB cables; cheap known-good cables listed).
  Their toolbox releases ship llama.cpp with RPC pre-enabled.
- **[ds4 (DwarfStar)](https://github.com/antirez/ds4)** — the DSV4-specialized
  engine (21k★) with a documented two-Strix-Halo layer-split; builds
  first-try on our boxes (verified).
- **[vllm.cpp](https://github.com/mudler/vllm.cpp)** — vLLM's serving core in
  C++; the multi-client frontier; AMD-integrated support still open (watch).
- **r/LocalLLaMA Strix Halo threads** — where the DFlash2/n-gram/MTP
  benchmark culture lives (e.g. the 3-day DFlash2 study our e6 battery
  cross-checked); we now read these headless via Playwright when curl is
  blocked.

*Everything here is reproducible from this repo; numbers are ours unless
labeled otherwise.*
