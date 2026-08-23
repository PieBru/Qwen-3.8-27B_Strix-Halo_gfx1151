# Fleet clustering — joining the Halos into one bigger machine

> From [Multi-Halo fleet](MULTI-HALO.md) · master plan: [FLEET-PLAN.md](FLEET-PLAN.md)
>
> **Status: RESEARCHED & PARTIALLY STAGED (2026-08-24).** The HA stack
> ([FLEET-HA.md](FLEET-HA.md)) is built; everything here is the *next*
> frontier — using both halos as ONE inference machine.

## Why cluster at all

The HA fleet already gives 2× serving capacity and zero-downtime. Clustering
adds what one box can never have: **~250 GB of usable memory for a single
model** — the DeepSeek V4 Flash class (~685B MoE) — and a path beyond the
262k context ceiling. The full proposal (with bandwidth math, bug boards,
and phase gates) is [FLEET-PLAN.md](FLEET-PLAN.md); this page is the
orientation view.

## The three roads to a "virtual halo"

| Road | Mechanism | State for us | Community signal |
|---|---|---|---|
| **A. llama.cpp RPC** | `ggml-rpc-server` on each halo; master splits weights+KV proportionally; per-token cross-traffic is only the hidden state (~300 KB/s at 20 t/s — 1 GbE suffices for decode; prefill pays ~10–15%) | fork has full RPC support; smoke test pending (Phase B); open upstream bugs #26685 (Vulkan garble) / #26746 (gfx1151 TOP_K crash) / #26128 / #26143 | [strixhalo.wiki Clustering](https://strixhalo.wiki/AI/Clustering) documents exactly this path with TB networking (~9 Gbps) — community-validated |
| **B. ds4 (DwarfStar)** | layer-split pipeline parallelism (`--layers 0:21` / `22:output`), worker-to-worker TCP; **a two-Strix-Halo split is documented and tested upstream** | **built first-try** on our dev box (`make strix-halo`, TheRock 7.15); needs its ~100 GB quant | the engine's reference distributed numbers are 2× MacBook TB5; Strix ROCm is a named target with active fixes landing |
| **C. RDMA / soft-RDMA** | tensor parallelism over USB4 "soft-RDMA" (µs-class latency); Infiniband via M.2 for the serious version | not started | [wiki page](https://strixhalo.wiki/AI/Clustering_with_RDMA) links a repo running **DeepSeek V4 Flash this way** — proof it works on our hardware class |

Plus the two *adjacent* engines researched: **vllm.cpp** (multi-client
serving frontier — continuous batching, RadixAttention; AMD-integrated
support still open, watch) and **audio.cpp** (built on halo2; the Ciao
audio-serving path). See FLEET-PLAN Phases D/E.

## The link layer: USB4 / Thunderbolt networking

- Both Strix Halo boxes expose **2× USB4 v1 (40G, TB3-compatible)** ports;
  a TB cable brings up `thunderbolt-net` immediately (~9 Gbps measured by
  the community; ~10–20 Gbps class).
- **Our staging (done, dormant)**: `thunderbolt-net` module loaded +
  persisted on both boxes; systemd-networkd `.network` files written for the
  future `tb0` interface (random-migration-safe /30: 10.180.243.1/.2);
  bring-up runbook in FLEET-PLAN Phase A. Plug in the cable → ~10 min to
  measured iperf3 numbers.
- **Cable folklore** (wiki + our research): passive 40G only holds ≤1 m;
  80G/TB5-class claims on passive cables are only credible at ≤0.8 m — the
  e-marker (not the listing) tells the truth; `boltctl`/`dmesg` verify in
  seconds. Cheap known-good option per the wiki: UGOURD TB 40G ~$5/0.3 m.
- The wiki notes thunderbolt-net has **no routing** — fine for our 2-box
  direct pair; three+ boxes want the switch or per-pair links.

## The payload that justifies it: DeepSeek V4 Flash

- ~685B MoE, ~6 active experts/token — quality frontier, "close to SOTA
  closed" per community benchmarks (our own E2 battery will put OUR number
  on it when we run it).
- **Unsloth UD quants land exactly in our envelope**: IQ3_S 116 GB (perfect
  2-halo split), IQ3_XXS 104 GB, Q3_K_M 128 GB; ds4's own asymmetric
  imatrix quants (experts IQ2_XXS/Q2_K, everything else untouched) fit ONE
  halo at ~96–110 GB.
- **MoE demand-paging** (the insight that makes single-halo plausible):
  with `-lm mmap` only touched expert pages live in RAM; hot experts stay
  in page cache; cold ones fault from our 7.9 GB/s NVMe (~100–200 ms once).
  `--cpu-moe`/`--n-cpu-moe` are the explicit knobs (also the upstream fix
  for the CUDA expert-garbling bug #25582 — on unified memory, "CPU"
  experts are GPU-accessible).
- Open bug board to watch before trusting it: #25171/#25259 (long-context
  forgetting), #26694 (long agentic repetition), #27155 (dspark draft KV
  leak), #25796/#26965 (tool-call edges).

## Roadmap recap (gated, from FLEET-PLAN)

1. **Phase A** — cable in → USB4 link + iperf3 gate (≥5 Gbps).
2. **Phase B** — RPC smoke on the pair (Q5/Q6 weights; instant-stop on
   garbled output; report to upstream if it bites).
3. **Phase C′ bake-off** — ds4 two-halo split vs llama.cpp RPC vs
   single-halo mmap paging; judge = our E2 deterministic battery vs the
   27B Q8. ds4 and audio.cpp already build on the halos; vllm.cpp watched.
4. **Phase D/E** — vllm.cpp multi-client serving (on AMD-integrated
   support); Ciao audio via audio.cpp on halo2.

*Numbers above are ours where measured (7.9 GB/s NVMe, bandwidth math);
INFERRED where derived; community data labeled. The plan doc tracks
provenance per claim.*
