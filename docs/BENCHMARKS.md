# Benchmarks — sweet spots, threads & the sweep method

> From [Qwen3.8-27B on Strix Halo](../README.md) — the config sweet spots, the threads-vs-concurrency study, and how the sweep found them.

## Sweep findings at a glance

How these were measured: [config research](#the-sweep-harness--how-the-sweet-spots-were-found).

| Axis | Winner | Evidence |
|---|---|---|
| KV type (target & draft) | **f16 / f16** | f16 is faster than q8_0 on both models (Q6 20.8 vs 19.2, Q8 16.6 vs 15.6 t/s) and higher fidelity — 128 GB unified makes it free |
| KV quantization for long windows | **f16 default; q8_0 when the window is the point** | NIAH battery 2026-08-21 (two random codes at 25%/75% depth, 8k/32k/64k/96k ctx, f16→q4_0): **40/40 retrieved** — positional retrieval survives q4_0 even at 96k. Decode flat across types (26.6–29.6 t/s); only memory drops (~3.3 GiB GTT per 110k ctx f16→q8_0, ~5.0 f16→q4_0, ×~9.5 at 1M) |
| `--spec-draft-n-max` | **6** | 6–7 plateau, 4 clearly worse (DFlash2 `block_size=8, n_extract=5`); committed Q5 single runs (`results/s1-Q5-n*.log`) show n3–n6 within noise (22.5–23.2 t/s) on that probe shape — the n4-worse gap shows on Q6 with the standard probe |
| `-c` allocated ctx | **65536 default; allocation is free up to 256k** | decode flat 64k–256k (Q6 20.2 ±0.2 t/s, Q8 ~17.6); the ≥128k crash is deep-prefill-only, not an allocation limit |
| `-b/-ub` | **4096** | tg flat ±2% across 2048/4096/8192; 4096 = +6% deep prefill over 2048; 8192 doubles compute buffers for nothing |
| `-tb` | **32** | tb16 within ~1% — GPU-bound |
| Model choice | **Q6 speed / Q8 quality** | decode favors Q6 at every ctx; Q8 prefill edges Q6 (pp512 366 vs 346 — Q8_0's symmetric blocks ride the fast kernel path). Q4 was evaluated and dropped — acceptance collapse, see Models |
| Host state | **`-lm mmap+mlock`** | zram-swapped weight pages cost up to ~30% decode; mlock makes weights unswappable |
| dflash fine-tuning | **inert beyond n-max** | `spec-draft-n-min` 2/3 and `spec-draft-p-min` 0.3/0.9 change nothing (bit-identical decodes, acceptance 0.647; independently confirmed upstream — the DFlash2 selector path never reads p-min). Single-shot `ngram-map-k` on dflash *hurts* (29.0 → 27.4 t/s). Draft quality sets acceptance — `n_max` is the only working knob |
| **n-gram lookup stacked on DFlash (replay workloads)** | **opt-in, replay-shaped** | e6 battery (9-turn cumulative file-build + regen, [`results/e6-ngram.csv`](../results/e6-ngram.csv)): `ngram-map-k4v` on dflash6 is flat while the file evolves (−1…+7%/turn), **+69% on the late re-emit turn and 91 t/s (2.3×) on pure regen** — but build mean only +12.2% (below our 15% adopt bar) and **n-max 5 *lost* 6%** here (bandwidth-bound APU: their dGPU "5 beats 7" doesn't transfer). Regime data points: ours (8060S iGPU) vs the [RTX PRO 6000 study](https://github.com/lukaLLM/DFlash2_Qwen3.8_3.6_27B_LlamaCPP) (4.68× multi-turn). Use: operators with replay-heavy agent sessions (file re-emission, quote-back) may stack `ngram-map-k4v` on the spec line; keep it off for one-shot and prose (their prose: −30%) |
| `--kv-unified` | **no effect at `-np 1`** | measured 2026-08-21 on Q6@64k and Q8@192k (journal-confirmed `kv_unified='true'`): tg and RAM identical within noise. Its purpose is sharing one KV buffer across parallel slots; with a single slot (and the hybrid SSM's tiny KV) there is nothing to unify. It flips on by itself if slots ever go auto |


## Threads (`-t`), batch threads (`-tb`) and two concurrent clients — measured

Production pins `-t 16 -tb 32` (the box has 16C/32T), but with **full GPU
offload** (`-ngl all`) CPU threads only orchestrate — so how little can you
run with, and does it matter when two clients are hitting the server at once?
Measured 2026-08-23 (`e5_threads_battery.py`, evidence
[`results/e5-threads.csv`](../results/e5-threads.csv)): standalone server in the
balanced shape (Q6 + DFlash2 draft, f16 KV, `-c 131072 -np 2` → two 64k
slots, fa on), **2 concurrent client threads** × 4 requests each; every
request re-prefills 4,927 tokens (`cache_prompt=false`) then decodes 128
(`ignore_eos`). n=8 per config.

| Config | prefill per client (t/s) | decode per client (t/s) | vs baseline |
|---|---:|---:|---|
| `-t 16 -tb 32` (production) | 192 | 18.8 | — |
| `-t 1 -tb 1` | 191 | 18.8 | **−0.4% / −0.1%** |
| `-t 1 -tb 2` | 191 | 18.7 | −0.5% / −0.5% |
| `-t 2 -tb 1` | 161–174 (2 runs) | 19.6–22.3 | **−9…−16% prefill** / decode: noise |
| `-t 2 -tb 2` | 191 | 18.7 | −0.6% / −0.7% |

Read it straight:

- **One thread costs nothing.** With everything on the GPU, `-t 1 -tb 1`
  serves two concurrent clients at baseline speed — CPU threads are pure
  orchestration here. Practical use: if you co-locate CPU-heavy work with
  the server (agent processes, builds), dropping to `-t 1 -tb 1` gifts ~15
  cores to it with **zero measured serving cost** under this workload.
- **The one bad shape is `-t 2 -tb 1`**: a reproducible 9–16% prefill loss
  (both runs), while its decode moved within noise. Mechanism unproven —
  avoid the combination; every other tested shape ties the baseline.
- **Concurrency itself is nearly free in aggregate**: two clients each decode
  at ~18.8 t/s *while both are running* — aggregate ~37.6 t/s vs ~19–20
  single-stream (the batched 2-slot path packs both streams into one GPU
  submission; the hybrid-SSM's tiny per-layer state makes this cheap).
  Prefill is the shared resource: ~192 t/s per client concurrent vs ~300+
  solo. If you need two consumers on one box, decode is the wrong thing to
  worry about — long *prefills* queueing each other are.

Caveats: n=8 per config, single box, decode scatter ±15% across configs
(DFlash2 acceptance is content-dependent); thread findings apply to
fully-offloaded serving — CPU-layer runs are a different regime. The
`--models-max 1` router serializes *model* loading, not slots; to get two
concurrent clients on one model you need `-np 2` (as here) — the recipe
default stays `-np 1`.


## The sweep harness — how the sweet spots were found

`sweep_llama_configs.sh`: staged config search (interleaved pairs, order-bias controls).

A staged, one-axis-at-a-time search for the optimal server config per target quant
(winners carried forward; every result appended to `results/sweep.csv`, one log per
config under `results/`). Results: [findings at a glance](#sweep-findings-at-a-glance).

```bash
./scripts/sweep_llama_configs.sh 0                                # capacity probe
./scripts/sweep_llama_configs.sh 1                                # --spec-draft-n-max 3-9, both models
./scripts/sweep_llama_configs.sh 2 <best-n6> <best-n8>            # KV types 2x2 (target x draft)
./scripts/sweep_llama_configs.sh 3 "Q6 - - 6" "Q8 - - 6"   # ctx ladder 64k(control)→128k→192k→256k
#  (`-` = default f16 KV; SWEEP_TAG_PREFIX=r2- tags repeat passes; optional 6th+
#   fields override the ctx list/order — use to break run-order confounds)
./scripts/sweep_llama_configs.sh 4 "Q6 q8_0 q8_0 <n6> <ctx>" ... # -b/-ub 2048/4096/8192
./scripts/sweep_llama_configs.sh 5 ...                            # -tb 16 vs 32
```

Guards built in: per-server wait ceiling, fail-fast on dead loads, process-group
cleanup (no orphans), crash-tolerant CSV (status column).

**Methodology:** absolute t/s drifts up to ±25% across a day on this box (zram under
memory churn — lessons #1–2), so every ranking comes from back-to-back runs inside
tight windows, with reversed-order passes to break run-order confounds. Trust only
interleaved comparisons, never numbers from different sessions.

