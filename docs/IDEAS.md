# Ideas, parked — the full menu

> From [Qwen3.8-27B on Strix Halo](../README.md) — everything researched,
> started, or parked, in detail. The front page carries the summary.

Things we researched, started, or parked — each is a standing invitation for a
fellow Haloer to pick up. The fleet has its own documentation set: **[docs/MULTI-HALO.md](MULTI-HALO.md)**
(the guide: [HA stack as built](FLEET-HA.md) — one VIP address,
failover-drilled, dashboard — plus [clustering research](FLEET-CLUSTER.md)
and the [master plan](FLEET-PLAN.md) with phases, bake-offs, and
decision rules); this chapter is the menu.

**Two-Halo fleet** (two 128 GB Strix boxes, one flock):

- **USB4 direct link** — a 0.8 m certified cable turns two Halos into a
  ~10–20 Gbps pair (vs 1 GbE); thunderbolt-net staging is ready on both
  boxes (`tb0`, static /30, module persisted). *Status: cable in transit —
  bring-up runbook ready.*
- **llama.cpp RPC virtual-Halo** — `ggml-rpc-server` + `--rpc` splits
  weights/KV across both boxes; the decoder needs only ~300 KB/s cross-
  traffic (1 GbE suffices!), prefill pays ~10–15%. Open upstream bugs to
  dodge: #26685 (Vulkan garble), #26746 (gfx1151 TOP_K crash), #26128.
- **DeepSeek V4 Flash on two Halos** — the quality frontier: ~685B MoE,
  Unsloth UD-IQ3_S lands at 116 GB (perfect two-Halo split) or their Q2
  imatrix quants fit one Halo. The fork already ships DSV4 Vulkan kernels
  + dspark spec decode. Bonus insight: MoE + mmap = demand-paged experts
  (hot experts in RAM, cold ones on the 7.9 GB/s NVMe) — single-Halo
  DSV4 might just work.

**Engine bake-off** (all three build on gfx1151 today — verified):

- **ds4 (DwarfStar)** — antirez's DSV4-specialized engine, 21k★,
  Strix-Halo ROCm target builds first-try against TheRock 7.15; ships
  two-Halo layer-split pipeline + SSD expert streaming. Next: the ~100 GB
  quant download and a first t/s number.
- **vllm.cpp** — vLLM's serving core (continuous batching, RadixAttention)
  in one C++ binary; multi-client serving frontier — currently broken on
  AMD iGPU (their #125/#41/#937) → watch, then a one-evening smoke.
- **audio.cpp** — 50 families of ASR/TTS/VAD/diar on ggml, builds on the
  Halos (Vulkan, verified): the natural audio-server side for our sister
  project [Ciao](https://github.com/PieBru/Ciao) (Wyoming bridge = the fun
  part).

**Quality & reasoning**:

- **passkey at depth** — we filled 254k positions and measured speed at
  every depth; nobody has measured *recall* there. `llama-passkey` is
  built and waiting for a GPU evening.
- **e3 agent battery tail** — 10 of 30 tool-loop episodes unbanked
  (`e3_agent_battery.py`, resume-safe).
- **froggeric template watch** — v22.3 current; upgrades are a ~30-min
  adopt-track (their suite + our E0 matrix).

**Fleet growth — heterogeneous backends** (researched 2026-08-24):

- The fleet's HA spine (VIP + haproxy) is backend-agnostic: enrolling a
  box = two haproxy `server` lines + a llama-server that answers `/health`.
- **Beefy i9 + RTX 4090 Ti + 128 GB DDR5** → third *27B-class* backend
  (CUDA speed likely beats the halos; 128 GB RAM opens `-cmoe` MoE shapes).
  Pilot candidate: weight-80 backend behind the existing VIP.
- **i7 + 8 GB VRAM + 64 GB** → wrong box for the 27B, right box for the
  small-model speed lane, embeddings, or **audio.cpp for Ciao** (Phase E
  lands naturally on exactly this class of hardware).
- Heterogeneity caveats researched: per-server `weight` (leastconn doesn't
  know "fast"), KV re-prefill on cross-hardware failover (same one-time
  cost, more frequent), dashboard doctor needs a generalized "backends"
  card (halo-specific checks don't map), capacity-sharing vs dedicated
  (boxes already running llama-server for others = *federation*, not
  takeover), LAN trust surface.
- Suggested pilot: enroll the i9 alone (evening, zero fleet risk), live
  with three-way spreading for a week, then decide the i7's lane.

**Nightly research dream — the "scout"** (researched 2026-08-24):

- Unattended ~07:00 pi run (same systemd pattern as the nightly memory
  dream; [pi-dream](https://github.com/PieBru/pi-dream) is the chassis)
  that scans the monitored sources — llama.cpp/fork commits + merged PRs,
  r/LocalLLaMA + r/StrixHalo (+ this repo's watch ledger triggers), HF
  quant repos (Unsloth/froggeric), the engine newborns (ds4, vllm.cpp,
  audio.cpp) — and writes a **morning report**: what's new AND *worth
  evaluating* for our fully-local, lightweight LAN-inference goals.
- Infrastructure ~90% standing: pi + headless-Chromium Reddit browsing
  (proven), GitHub API, the watch ledger's named triggers, report
  conventions. Missing piece: a `scout` skill (focused prompt + source
  list + worth-evaluating filter) on the pi-dream chassis.
- Filter is the design core: the report earns its 07:00 slot only by
  surfacing *decision-relevant* changes (perf/quality deltas on our
  model/hardware class, bug fixes touching our open issues, new quant
  revisions) — not a firehose. Each finding links evidence + names the
  repo experiment that would evaluate it (e.g. "DFlash2 upstreamed →
  re-run stock-vs-fork spec battery").
- Quality gate: report-only by default (pi-dream's Dream Gate pattern);
  nothing auto-applies to recipes or memory without a human pass.
- **The philosophy behind it — auto-healing, auto-evolutive system**: the
  scout is phase 1 of a ladder, not a newsfeed:
  1. **Observe** (day 1): morning report, operator reads.
  2. **Propose** (stable weeks): report + drafted experiment/patch per
     finding, operator approves each.
  3. **Auto-heal** (trust earned): autonomous *revertible* actions only —
     restart a wedged service (the canary already does this pattern),
     re-pin a flaky recipe, re-run a battery and file the result; every
     action journaled + one-command rollback.
  4. **Auto-evolve** (highest bar, always operator-sealed): adopting
     measured improvements (new quants, flags, recipes) — proposal +
     evidence lands as a PR/draft; **the operator keeps the seal** (the
     agent's own constitution: never self-ratify hard changes).
  Rollback is a first-class citizen at every rung — nothing evolves
  without a tested way back (git discipline + .bak conventions + the
  fleet doctor's drift detection are the existing rails this climbs).

**Sibling evaluation queue** (from the
[comparisons chapter](BACKENDS.md#how-this-compares-with-sibling-projects) —
pre-registered experiments per project, trigger → run → verdict):

- **ds4 vs llama.cpp fork on the same box** — trigger: quant download
  evening. Run: ds4f-q2 (their imatrix asymmetric quant) under ds4 vs
  Unsloth UD-IQ3_S under our fork, same Halo; judge = E2 tier-1 battery +
  t/s pair. Rule: ds4 wins the lane iff quality ≥ our-Q8 − 1 pt AND t/s
  ≥ 1.5× ours (their whole thesis is specialization).
- **Lemonade `vllm`+`rocm` vs our router** — trigger: an evening when
  Lemonade's model manager carries our GGUF. Run: same weights, same
  prompts, decode/prefill + a 2-client e5-style arm (their continuous
  batching is the claim). Rule: adopt as on-ramp lane iff parity t/s and
  the UX wins; our router stays the fleet core regardless.
- **vllm.cpp on AMD integrated** — trigger: their #125/#41/#937 close.
  Run: e5 two-client battery as judge vs the router's `-np 2` numbers.
- **FreeToken** — trigger: ROCm PRs land gfx1151 (or the i9 joins the
  fleet: trialable immediately on RTX). Run: their CPU–GPU co-execution
  on DSV4-Flash vs our `-cmoe` mmap paging; judge = t/s at equal quality
  tier (E2 battery), plus watch whether semantic-anchor KV edits port
  the idea to our agent loops.
- **halofpx** — already measured (pinned 2026-08-22); re-run only if
  they publish KLD/quality numbers for their defaults.

**Upstream karma** (pick one, file a PR, cite our evidence):

- llama.cpp **#27588** (ours): trailing `assistant(tool_calls)` dropped in
  auto-prefill — PR offer stands (serialize vs reject).
- Watchdog forensics worth posting on **#27076/#27458**: our kernel-log
  1:1 + `lockup_timeout=-1` intervention is the only published causal
  proof we know of.
- **#27210** (adaptive MTP) / **#27342** (DFlash2 upstreaming): both open,
  both shape our spec-decode future; our spec-battery is ready to be the
  first gfx1151 datapoint when they merge.

Something catch your eye? Open an issue — measured numbers welcome, vibes
politely declined.
