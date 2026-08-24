# PROPOSAL (DRAFT) — Two Halos, One Flock: RPC / USB4 research & phased test plan
Date: 2026-08-24 · Status: PROPOSAL — nothing executed yet · Repo: Qwen-3.8-27B_Strix-Halo_gfx1151

---

## 0. What we have today (the baseline we must beat)

| | strixy2 (dev) | strixy-9ad3 (.15) |
|---|---|---|
| APU | Ryzen AI MAX+ 395 (8060S, gfx1151, 128 GB) | identical |
| Backend | fork Vulkan build (DFlash2) | identical |
| Serving | router :8080, 10 recipes, models-max 1, balanced preloaded | identical (idle otherwise) |
| Link | — both on switched 1 GbE (eno1, 1000 Mb/s measured up) — | |

**Already working fleet behavior:** pi's `llamaServerUrl` registers BOTH
routers (10 recipes × 2 boxes = 20 models). Pointing a second client at
`.15` today gives true parallel serving — two full-speed Q6 instances,
zero new technology. **This covers two of the three stated goals already**
(more than one GGUF resident, more than one client served).

The third goal — one *virtual* halo, ~256 GB pool, one model bigger than
any single box — is what llama.cpp RPC exists for. That's the research
subject below.

## 1. Research findings (primary sources, read today)

### 1.1 How llama.cpp RPC works
- `ggml-rpc-server` on each remote host exposes its **accelerator devices**
  (Vulkan included); the main host's llama-server/client adds `--rpc ip:port`
  per server. (fork tree: `tools/rpc/`, `ggml/src/ggml-rpc/`.)
- Weights AND KV are split across devices **in proportion to free memory**
  (overridable with `--tensor-split`). It is a *pipeline/proportional* split
  — not tensor-parallel — so per-token cross-traffic is the hidden state
  (~12–16 KB/token for a 27B), not weights.
- RPC server supports a **local tensor cache** (`-c`) so repeat model loads
  don't re-transfer weights (mmap of transferred buffers).
- Upstream's own README labels the RPC backend **proof-of-concept,
  fragile, insecure — never on an open network** (fine for us: LAN/TB link).

### 1.2 Known bugs that touch OUR exact stack (all OPEN, read today)
| Issue | Report | Relevance |
|---|---|---|
| [#26685](https://github.com/ggml-org/llama.cpp/issues/26685) | **garbled output with RPC + Vulkan** (DeepSeek V4) | our backend |
| [#26746](https://github.com/ggml-org/llama.cpp/issues/26746) | **ROCm gfx1151 RPC worker crashes in TOP_K during prefill after 4096 tokens** | our exact APU (ROCm path) |
| [#26128](https://github.com/ggml-org/llama.cpp/issues/26128) | server prompt cache incompatible with RPC (`-np > 1`) | multi-slot |
| [#26143](https://github.com/ggml-org/llama.cpp/issues/26143) | RPC node cache grows without bound | long runs |

→ Expect breakage; treat any experiment as upstream-karma data, not a
production migration. Both of our backends have open eval bugs.

### 1.3 Bandwidth math (why 1 GbE might actually be enough for decode)
- Decode: hidden state per token ≈ 12–16 KB; at 20 t/s ≈ **300 KB/s**
  cross-traffic → 1 GbE (~110 MB/s) has ~300× headroom.
- Spec decode (DFlash2, n-max 6): ~6× the crossings ≈ 2 MB/s. Still trivial.
- Prefill: 4096-token microbatch ⇒ ~50 MB per boundary crossing ⇒ ~0.45 s
  on 1 GbE per chunk, on top of ~3–5 s compute — **~10–15% prefill tax**.
- Model load: Q6 ≈ 17 GB ⇒ ~2.5 min over 1 GbE first time (local cache
  `-c` makes repeat loads disk-fast).
- **USB4 networking** would erase the prefill tax and the load time
  (thunderbolt-net typically reaches ~10–20 Gbps practical).

### 1.4 USB4 status on our pair (measured today)
- Both boxes: Strix Halo **USB4 routers present** (2 domains each),
  `thunderbolt_net` module available (kernel 7.1.8).
- **No cable connected yet** — no remote devices enumerate; there is no
  `tb<0..n>` network interface on either side.
- Bring-up when the cable arrives: plug → authorize (boltd) →
  `thunderbolt-net` creates `tb0` on both ends → static IPs → iperf3.

### 1.5 The uncomfortable finding (be honest in the proposal)
The unique thing RPC buys — *one model bigger than 124 GB* — is
**currently blocked upstream by the 262,144 slot cap** (same finding as
the parked 1M recipe): llama-server caps any slot to n_ctx_train, YaRN or
not. So today RPC cannot give us a >262k window even with 2× memory.
Largest single-model config we can legally serve:
- Q8 + 262k window, f16 KV ≈ 61 GB — **fits ONE box**.
- Q6 + 262k + **2 slots × 262k KV** ≈ 90 GB KV + 17 GB weights ≈ 107 GB —
  fits one box, barely.
So RPC's production value TODAY ≈ 0 for our recipes; its value is
(a) the experiment/upstream data, (b) readiness for the day the cap lifts
(one-box 1M f16 needs ~121 GB — RPC would make it comfortable).

## 2. Proposed phases (each gated, each timeboxed)

### The engine bake-off context (2026-08-24 research)

The two-halo goal attracted a four-way engine contest; the proposal tracks
all of them, one judge (our E2 deterministic battery + our bench harnesses):

| Path | Two-halo mechanism | DSV4-Flash | On our gfx1151 today | First-number cost |
|---|---|---|---|---|
| llama.cpp fork (status quo) | RPC tensor split (PoC; #26685/#26746/#26128/#26143 open) | deep fork support (Vulkan DSV4 kernels, dsv4 KV, dspark) + 6 open model bugs | ✅ production | Phase B smoke → IQ3_S via RPC |
| **ds4 (DwarfStar)** ★21.7k | **layer-split pipeline, documented 2× Strix split** (`--layers 0:21/22:output`), SSD expert streaming, imatrix asymmetric quants | *the* specialty engine; MTP/dspark spec decode | ROCm target exists (`make strix-halo`) but rough (#552/#626 build, #577, #829) | dry-build running; ds4f-q2-q4 ~100 GB |
| vllm.cpp ★329 (7wk) | ❌ none (single-node) | runs it — parity with ds4 + **+14% `VT_V4_RESIDENT_W`** (GB10, byte-exact); independently documented the MoE residency physics | ❌ Vulkan broken (#125), ROCm skeleton, temp>0 crash (#937) | watch only |
| fleet status quo | two independent routers | ❌ (27B only) | ✅ | zero |

Bake-off notes: ds4 is the cheapest path to a big-model number on the pair
(named Strix target, layer-split already two-halo); llama.cpp RPC is the
integration-clean path (same recipes/servers) gated on its bug board;
vllm.cpp is the **multi-client serving frontier** (continuous batching,
RadixAttention) — the *right* answer to the original 2-client question —
but AMD integrated is its open edge. Their GB10 DSV4 numbers (16.3–18.7 t/s
IQ2-mix) are the halo ballpark target.

### Phase A — USB4 link bring-up — ✅ COMPLETE (2026-08-24, measured)

Cable: PremiumCord EJ903C (0.8 m, e-marker). Plug-in was fully
automatic on both halos — no bolt authorization needed (AMD USB4
auto-authorized; security level "user" did not block TB-net).
As-built (differs from the sketch in useful ways):

- Interface name is **`thunderbolt0`** (kernel default), not `tb0` —
  the staged 90-tb0.network never matched; renamed to
  **05-thunderbolt0.network** (must sort before 20-ethernet.network,
  which steals the interface via its `enx…` ALTNAME matching `en*`).
- Addressing as staged: 10.180.243.1/.2 /30, **MTU 9000** (+2-3%),
  declarative networkd (survives reboots; eno1 untouched as fallback).
- **Measured: 9.43/8.96 Gbps (MTU 1500), 9.48/9.21 (MTU 9000), 9.10
  aggregate @ 4 streams, RTT 0.28-1.5 ms** — the ~9.1-9.4 Gbps
  platform ceiling, ~1.9× the 5 Gbps gate. (USB4 40G signalling but
  TB-net software path tops out here; parallel streams add no headroom
  — relevant for RPC batch sizing.)
- SSH over the link works both ways (aliases halo1-usb4/halo2-usb4,
  known_hosts pinned); dashboard doctor row `usb4 interconnect up`.
- Next: Phase B (RPC smoke) may proceed on this fabric.

### Phase B — RPC smoke test — ✅ COMPLETE (2026-08-24, verdict: TECHNICALLY SOUND, not adopted)

Setup: `build-rpc` (Vulkan+RPC, fork pin 9b9ac3e38) on both halos;
`ggml-rpc-server` on .15 over the USB4 link (10.180.243.2:50052);
llama-server on strixy2 with `--rpc`. **Measured (OBSERVED):**
- **Correctness**: 10 fixed prompts temp-0 vs local single-box: 9/10
  bit-exact (content AND reasoning); 1 coherent divergence in a long
  reasoning chain (anthem line variant — FP-ordering class, NOT the
  #26685 garbling class; no gibberish anywhere).
- **Decode**: 95 → 104 ms/token = **92% of single-box** (gate was ≥50%).
  Prefill 62 → 32 t/s (52%) — the split pays a real prefill tax.
- **Stability**: 15.2k/30.3k/56.9k-token fills clean, zero RPC errors,
  both processes alive after. (A 70k-token request was cleanly rejected
  at 64k ctx — my probe sizing error, documented, not a crash.)
- Verdict: RPC works, is bit-sane, and the fabric supports it — but with
  BOTH halos alive there is no *serving* case where 92%-decode beats
  running a full copy per box (HA + 2 clients at full speed). The
  unique value — one model >124 GB or >262k window — remains blocked
  upstream by the 262k slot cap. **Chapter closed until that cap lifts
  or a >124GB model appears; builds kept in build-rpc/ (revertible).**
- Test-harness lessons (all mine, not the link's): word-lists compress
  ~11.6 tokens/block (not 74); thinking eats small max_tokens — use
  reasoning_effort low + budget; `off` is not a valid effort value
  (template raise); block-counting is beyond Q5's arithmetic (the '100'
  answer was model error, caught as such).
On `.15`: stop the router's preload (idle box), run
`ggml-rpc-server --host <tb-ip> -p 50052 -c` (Vulkan build with
`-DGGML_RPC=ON` — needs a build config there; fork already carries it).
On dev box: `llama-server --rpc <tb-ip>:50052 -ngl 99` with the **speed
weights (Q5)** first, then Q6. Tests, in order:
1. Correctness: 5 fixed prompts, outputs diffed vs local single-box run
   (temp 0). **Garbled output = instant stop, file upstream data on #26685.**
2. Decode t/s + prefill t/s vs single-box (llama-bench + fill chunks).
3. Stability: 16k-chunk incremental fill to 64k+ (watch #26746-class
   crashes; note: that report is ROCm — Vulkan path may differ).
**Success = bit-sane outputs + decode ≥ 50% of single-box + no crash in a
30-min soak.** Anything less = document, revert, close the chapter until
upstream fixes land.

### Phase C — (only if B passes) pick the production shape

**C′ (primary candidate since 2026-08-24): DeepSeek-V4-Flash 0731 quality rig.**
A ~685B MoE (~6 active experts/token) whose Unsloth UD quants land exactly
in the two-halo envelope — and the fork already ships first-class DSV4
support (Vulkan gather/dequant kernels, dsv4 KV cache, `draft-dspark`
spec decode with a 10.9 GB Q8_0 sidecar in the same repo).

The MoE insight that makes it viable (measured 2026-08-24):

- NVMe measured at **7.9 GB/s** (direct 2 GB write test, dev box);
- with default `-lm mmap`, only touched expert pages live in RAM and the
  kernel page cache keeps hot experts resident — cold expert ≈ 100–200 ms
  NVMe fetch, once;
- a task's routed-expert hot-set is far smaller than the 116 GB pool, so
  single-halo serving (~75 GB free cache) likely runs with only a
  spill-fraction on disk;
- **two halos via RPC split the tensor map ~58 GB per side — each page
  cache swallows its half whole** → the first configuration where
  IQ3_S (116 GB) runs fully RAM-resident. Cross-link carries activations
  (~MBs/token), not experts;
- `--cpu-moe`/`--n-cpu-moe` are the explicit knobs (also the upstream fix
  for #25582's CUDA expert garbling — unified memory makes 'CPU' experts
  GPU-accessible here).

Target quant ladder: UD-IQ3_S 116 GB (primary), IQ3_XXS 104 GB, Q3_K_M 128 GB
(fallbacks if pressure/leaks bite). Watch-board: #27155 (dspark draft KV
leak — the speed path), #25171/#25259 (long-context forgetting,
cache-shaped), #26694 (long agentic repetition), #25796/#26965 (tool-call
edge cases).

C′ sub-phases:
1. **C′.1 single-halo paging probe** (~1 h, no RPC): IQ3_S mmap on .15,
   `-cmoe`; measure cold ramp, steady t/s, major-fault rate, cache
   residency — isolates the MoE-cache question from RPC.
2. **C′.2 two-halo RPC split** (after Phase B green): same quant, both
   ends; expect ~zero steady-state disk traffic; compare t/s + faults.
3. **C′.3 quality verdict**: run the repo's E2 tier-1 deterministic
   battery vs the 27B Q8 — our own number for 'close to SOTA'.

Previous candidates, now secondary:
1. **1M-window readiness rig** (blocked by the upstream 262,144 slot cap;
  parked recipe runs the moment upstream exempts YaRN).
2. **Dual-slot 262k interactive** (only if single-box 107 GB proves too
  tight under real load).
3. Not pursued: using RPC to co-locate multiple different models — the
  two-router fleet already does that better.

### Phase D (watch) — vllm.cpp: the multi-client serving candidate

Not runnable on gfx1151 today (Vulkan #125, ROCm skeleton #41, temp>0 AMD
iGPU crash #937) — but it is the engine built for exactly our other open
question: many concurrent clients, continuous batching, prefix caching.
Triggers to act: #125/#41/#937 close or an AMD-integrated release note →
then a one-evening smoke (build Vulkan/HIP, run our e5 two-client battery
as the judge vs the router's -np 2 result). Meanwhile: watch, star, and
keep the e5 battery ready.

### Phase S — Scout: the nightly research watch (BUILT & FIRST-RUN 2026-08-23)

Rung 1 of the auto-healing/auto-evolutive ladder (see README Ideas):
observe-only. `fleet/scout/` carries the skill + systemd units (timer
07:00 local, runs pi with the scout skill pinned to quality@128k;
reports land in ~/Piero/Work/pi-scout/ as versioned SCOUT_REPORT_*.md).
First run (manual, 44 min): 2 evening-grade findings (fork 5 commits
past pin incl. an MTP-checkpoint revert→reapply pair — sync candidate;
community 1.8× gfx1151 prefill claim #27553), 6 watch items, correct
report-only gating with a proposed ledger diff. Dream Gate applies:
nothing is applied without the operator.

### Phase R — Reliability: the mirrored-Halo fleet (full throttle ↔ degraded serve)

Two identical computers are a reliability asset independent of the two-Halo
performance story — and largely already staged. The concept: **mirror everything
that matters; serve full-throttle when both are up; degrade gracefully with one.**

R0 — What is already mirrored (verified 2026-08-24):

| Layer | Mechanism | Status |
|---|---|---|
| Repo + recipes + docs | `git pull --ff-only` discipline, same commit on both boxes | ✅ running |
| Router service (10 recipes, same models/models.ini) | systemd user unit + linger on both | ✅ running |
| Model weights | same GGUFs on both (download_models.sh sha256-verified) | ✅ |
| pi clients | `lan`/`local` providers + pi-llama-cpp extension registers BOTH routers | ✅ running |
| Ciao-style fallback seam | Ciao already implements `[llm].fallback_base_url` (second llama-server retry, LOUD never-silent) — the pattern to copy | ✅ pattern exists |

R1 — Mirror the non-repo state (the actual gaps):

1. **OS/runtime knobs**: TheRock 7.15 tarball (userspace, no root) is on
   strixy2 only → replicate to .15 (`~/opt/rocm-7.15`, needed by ds4 and any
   HIP work). One-time ~8.6 GB copy (USB4 link will make this trivial).
2. **Boot config**: strixy2 runs `amdgpu.lockup_timeout=-1` + the GPU canary
   + sudoers reboot grant; .15 runs the default kernel. Decide per role:
   if .15 ever serves deep-context, mirror the playbook
   (staged files exist in-repo: systemd-units/, runbook in DEEP-CONTEXT docs).
3. **sysctl/limits** (swappiness=10, watermark_scale_factor=125, memlock
   unlimited, zram posture): currently box-specific knowledge → move the
   exact files into the repo (`sysctl/99-llama-inference.conf` +
   `security-limits.d/99-llama-mlock.conf` templates) so any Haloer can
   replicate the pair in minutes. Then apply on .15 (some already match).
4. **pi agent state**: ~/.pi/agent/{models.json,settings.json} and user
   units (pi-dream.timer, gpu-canary.timer) → a tiny `fleet-sync.sh`
   (rsync whitelist + systemd user-unit copy + `daemon-reload`) committed
   to the repo; cron/timer-driven, diff-visible.
5. **Dream/report outputs and results/ evidence**: one-way sync back to the
   primary (or a shared backup target) — cheap insurance.

R2 — Degraded-serve behavior (the payoff):

- **Both up (full throttle)**: pi/clients balance per-request across both
  routers (extension lists both); heavy jobs (fill batteries, RPC workers,
  ds4 builds) coexist with interactive serving on the idle box.
- **One down (degraded, zero config)**: every client keeps working — the
  pi-llama-cpp palette still lists the live router; Ciao-style fallbacks
  retry the survivor loudly. Preload (balanced) means instant service on
  whichever box is up. No SPOF in the serving path: no shared disk, no
  primary/replica database — just two identical boxes.
- **Nightly unattended**: dream/batch jobs pinned per-box; if the pinned box
  is down, a simple health-check wrapper starts the job on the survivor
  (one systemd `OnFailure`/ ExecCondition line, to be written when needed).

R2.5 — Transparent HA, one address (BUILT & TESTED 2026-08-24)

keepalived + haproxy run ON both halos (no extra hardware — a proxy pair
of Raspberry PIs would add boxes to maintain without adding availability
for a 2-backend fleet; revisit PIs only at 3+ backends / TLS / mixed
services). Configs are the repo's source of truth under `fleet/`.

    clients ──► 192.168.50.10:8081 (VIP, VRRP failover < 4 s)
                  └─ haproxy on the VIP owner, leastconn + /health checks
                       ├─ halo1 127.0.0.1:8080
                       └─ halo2 192.168.50.15:8080

As-built details: VIP port 8081 (the routers' 0.0.0.0:8080 shadows a VIP
:8080 — direct per-box access stays :8080 for debug); `ip_nonlocal_bind=1`
sysctl (`/etc/sysctl.d/91-haproxy-vip.conf`) so the BACKUP's haproxy binds
the VIP before owning it; VRRP id 51, priority 150/100, preemptive MASTER.

Verified (2026-08-24): VIP serving + alias completion; **failover drill** —
halt halo1's keepalived+haproxy → VIP moved to .15 in <4 s → completion
served transparently (`FAILOVER-OK`); restore → MASTER preempted, .15
released, health green.

Client guidance: point anything that wants transparent HA at
`192.168.50.10:8081` (scripts, WebUI presets, Ciao primary). pi keeps its
direct localhost/LAN providers (the pi-llama-cpp extension already lists
both routers — richer than the VIP for model management); Ciao's existing
fallback stays as belt-and-suspenders. In-flight requests die on failover
(clients retry once — stateless HTTP recovers); KV does not migrate (the
survivor re-prefills; the e4 decay table prices it).

R3 — Verification (measure the reliability, don't assume it):

- A `fleet-doctor.sh` (repo tool): on either box, verify git commit parity,
  GGUF hashes vs results/gguf-baseline, router health, units enabled,
  sysctl/limits values, tb0 config presence — one green/red table.
- Chaos drill (quarterly, 10 min): halt one box mid-battery; confirm zero
  client errors via the survivor; confirm recovery on boot.

Design principle (learned from Ciao): **failures must be loud, never silent**
— the degraded path always announces itself (client fallback banners,
journal entries), and the fleet-doctor reports drift before it bites.

### Phase E — Ciao audio serving on halo #2 (audio.cpp)

Ciao (PieBru/Ciao) today runs faster-whisper + Piper/Kokoro in-process
(Python) beside llama-server; the goal is inference/client separation:

```
Ciao (client + Wyoming seam)
 ├─ LLM   → llama.cpp router (halo fleet — already separated)
 └─ Audio → audio.cpp server (halo #2 spare capacity): ASR + TTS + VAD
```

audio.cpp (0xShug0, ★1.9k, 9 weeks old, 50 families/70+ variants, ggml,
CUDA-optimized with HIP/ROCm since 0.5, Vulkan/Metal/CPU same surface):
one engine for the whole audio side, GGUF-packaged (Q8 up to 1.53×/−37%
VRAM), parity tooling vs Python references — same evidence culture as this
repo/ds4/vllm.cpp.

Known frictions: (1) their **server/API + pipelines are the explicitly
immature subsystem** (own contribution-focus note) — the exact seam Ciao
needs; Wyoming is NOT implemented there → a thin Wyoming↔audio.cpp bridge
or wait for API stabilization; (2) whisper.cpp/faster-whisper GGUFs are not
drop-in (per-family tensor mapping — migration = re-picking models:
Parakeet-TDT / SenseVoice / Voxtral-Realtime ASR candidates); (3) ROCm is
3 weeks old there — gfx1151 unverified; (4) license NOASSERTION — check
before any bundling.

Sub-phases:
1. **E1 (running): dry-build on .15** — clone + `-DGGML_HIP=ON` (TheRock
   7.15 userspace already resident on dev; replicate or Vulkan-first on
   .15) + one ASR family + one TTS family → RTF/latency vs Ciao's current
   faster-whisper/Piper numbers. Evening-sized.
2. **E2 (on E1 green): Wyoming bridge prototype** — thin adapter on the
   audio.cpp server API (or local-protocol plugin) exposing the Wyoming
   events Ciao already speaks.
3. **E3: Ciao config surface** — `[audio] base_url` mirroring the existing
   `[llm].fallback_base_url` pattern; keep in-process Python as fallback.

Note the hardware story: audio models are small/latency-shaped — this is
NOT a two-halo capacity problem; it is the "what else does halo #2 do
while idling" question, and it composes with any Phase C outcome.

### Explicitly NOT proposed
- Rewiring the production routers around RPC (bugs §1.2; fleet already
  serves the multi-model/multi-client goals).
- Any exposure of rpc-server beyond the direct TB link (PoC security).

## 3. Time & cost summary

| Phase | Time | GPU | Risk |
|---|---|---|---|
| A USB4 | 45–90 min | 0 | low (recoverable config) |
| B RPC smoke | ~2 h | 2 h | medium (known bugs; revertible) |
| C′ bake-off | ds4: build ✅ done | ds4f-q2-q4 download + bench evenings | medium |
| D vllm.cpp | watch-only | 0 | n/a |
| E audio.cpp | E1 build ✅ done on .15 (Vulkan) | ASR+TTS family bench evening | low |

### Dry-build results (2026-08-24, both GREEN)

- **ds4 on dev box**: `make strix-halo` against TheRock 7.15 userspace —
  **first-try success, zero patches** (upstream #552/#626 build fixes evidently
  landed); all five binaries built with `--offload-arch=gfx1151` (ds4,
  ds4-server, ds4-bench, ds4-eval, ds4-agent). Runtime smoke: `--rocm`
  initializes, sets oom_score_adj, and correctly REFUSES a Qwen GGUF
  (engine is DSV4/GLM-5.2-only by design — needs its own quants to go
  further). Next: `./download_model.sh ds4f-q2-q4` (~100 GB) on a free slot.
- **audio.cpp on .15**: cmake `-DGGML_VULKAN=ON` build **green**;
  `audiocpp_cli` + `audiocpp_server` run and advertise `--backend
  vulkan/rocm` with VAD/ASR/TTS/diar task surface + embedded WebUI.
  gfx1151 risk (E-friction #3) retired at the build level; next: one ASR +
  one TTS GGUF family, RTF/latency vs Ciao's faster-whisper/Piper.

## 4. What we tell the README later
Whichever way B lands, the two-halo chapter writes itself: either "RPC
works on gfx1151 Vulkan pairs, here's the split math" or "we measured the
open bugs on our APUs and stayed with the fleet architecture" — both are
useful upstream contributions.

---
*Sources read: fork `tools/rpc/README.md` + `ggml-rpc.cpp` (interface,
cache, PoC warning), issues #26685/#26746/#26128/#26143 (open), local
USB4/thunderbolt enumeration on both boxes, eno1 link state. Estimates in
§1.3 derive from hidden-dim arithmetic (12–16 KB/token) + measured e4
prefill rates — mark as INFERRED until Phase B measures them.*
