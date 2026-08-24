# Qwen3.8-27B on Strix Halo (Radeon 8060S / gfx1151)

> *Speed is useful, but quality is fundamental — one subtle bug fewer or a better
> codebase always pays for itself in wall-time gained.*

Run Qwen3.8-27B with the [strix-halo llama.cpp](https://github.com/Nathanw1014/strix-halo-llamacpp)
fork on a Ryzen AI MAX+ 395, with DFlash2 speculative decoding.
## Why this exists: cloud-free intelligence on a desk

A **less-than-€2,000 mini-PC** (AMD Strix Halo, 128 GB) now serves a
27B reasoning model entirely from your desk — no API keys, no quotas, no
meters, no telemetry. Your agent runs 24/7 on hardware you own outright:

- **~17–21 tokens/s** sustained decode of the Q6_K_XL quant (Q8: ~15–18;
  Q5: ~23 — spec decode makes the *quant choice* the speed dial), ~330 t/s
  prefill
- **~85 W** at full tilt — idle draws ~10–15 W, about half the cost
  of leaving an LED lightbulb on
- **Private by physics** — prompts never leave the machine

**How we know:** every number in this repo traces to committed evidence
under `results/`, runs under pre-registered decision rules, with
OBSERVED/INFERRED/REPORTED labels — and when our own audit caught
evidence-less numbers, we corrected the docs, not the evidence.
The full pitch — hardware, power math, privacy, and the measurement
method: **[docs/WHY.md](docs/WHY.md)** — including
[*What's the price of absolute privacy?*](docs/WHY.md#whats-the-price-of-absolute-privacy):
€/Mtok all-in (€2.4 flat-out, €9 agent-realistic), break-evens vs cloud
priced honestly, and why privacy ends up being a discount, not a premium.

## Provenance note

> *Humans architected, verified, sealed. AI assistants built and wrote all the
delivered stuff.*

The architecture decisions, every acceptance of a
measurement, and the seal of each release were human; the builds, probes,
batteries, tables, and most of this documentation were produced by AI
assistants under that supervision — including this sentence. Every number in
this README traces to a command you can re-run.
## TL;DR — reproduce on any gfx1151 (Strix Halo) box

Clone, install deps, build the fork, download the models (~73 GiB), verify
the GPU, serve — six steps, ~45 min, headless-friendly:

```bash
git clone https://github.com/PieBru/Qwen-3.8-27B_Strix-Halo_gfx1151 && cd Qwen-3.8-27B_Strix-Halo_gfx1151
./scripts/download_models.sh          # after deps + fork build (see full steps)
./scripts/run_llama-server.sh --goal balanced
```

Expected on a quiet box (f16 KV): Q6_K_XL prefill ~346 t/s, decode
~17–21 t/s served. **One caveat**: on a *default kernel*, deep Vulkan fills die at
~137k positions — that wall is the amdgpu watchdog, not Vulkan, and one
kernel parameter removes it entirely (full story linked in the guide).

The complete six-step bring-up with expected numbers, bench commands, and
the watchdog caveat: **[docs/TLDR.md](docs/TLDR.md)** · zero-build
alternative: [Quick start](docs/QUICKSTART.md).

## Quick start: run the prebuilt release (time-saving)

No build, no toolchain: the toolbox tarball bundles its own RADV + libdrm
and is verified perf-identical to the fork tip —
**[docs/QUICKSTART.md](docs/QUICKSTART.md)**, or build from source in the
[TL;DR](#tldr--reproduce-on-any-gfx1151-strix-halo-box).

## Headline findings (the counterintuitive ones)

Our setup keeps surprising us — every one of these inverts something most
LLM users take for granted, and every one is measured, not vibes:

- **The window is free; *filling* it isn't** — allocate 32k or 256k, decode
  speed doesn't care. Only how deep you *fill* it costs.
- **A smaller quant is *slower* here** — quant noise breaks the speculative
  drafter's guesses; the bandwidth you save gets eaten by rejected drafts.
- **Sampling penalties poison speculative decode** — 1.05 repeat penalty
  costs a quarter of your speed.
- **f16 KV beats quantized KV on *both* speed and quality** — 128 GB of
  unified memory inverts the usual trade.
- **Two recipes = two full weight copies in GPU memory**, even for the same
  file on disk.
- **Vision is free… until the first image arrives** — then spec decode dies.
- **Thinking is not the expensive part — running *out* of it is.**

The measured version of each claim, with numbers and evidence links:
**[docs/FINDINGS.md](docs/FINDINGS.md)**.

## Recommended configs (per goal)

Five roles, one menu: **quality** (Q8, correctness-first) · **balanced**
(Q6 @ 128k, the daily driver, ~17–21 t/s) · **coding** (balanced + a
measured reasoning-budget guard) · **speed** (Q5, fastest decode) ·
**vision** (images, no spec decode by design) — plus the **context dial**
(`quality@NNk`, the window per request, allocation is free). The full
table with RAM/throughput/quality columns, when-to-pick notes, and the
dial explained: **[docs/RECIPES.md](docs/RECIPES.md)**.

## Running it

Operations — serving all recipes via the router, the movable `Qwen38-27B`
default alias, pairing with the [pi coding agent](docs/RUNNING.md#pair-it-with-pi-the-coding-agent),
the 24/7 agent margin rule, one operator's profile, and GPU verification:
**[docs/RUNNING.md](docs/RUNNING.md)** (the recipe deep-dive — fill-decay
table, when-to-pick notes, relative costs — lives there too).

## Test — verify GPU, not silent CPU fallback

[`llama-cli --list-devices` and the quiet-box reference bench](docs/RUNNING.md#test--verify-gpu-not-silent-cpu-fallback).

## Sweep findings at a glance

The full config-research table — KV types, n-max, batch sizes, host state,
n-gram replay findings: **[docs/BENCHMARKS.md](docs/BENCHMARKS.md#sweep-findings-at-a-glance)**.

## Threads (`-t`), batch threads (`-tb`) and two concurrent clients — measured

`-t 1 -tb 1` is free under full GPU offload; `-t 2 -tb 1` is the one bad
shape; two clients nearly double aggregate decode:
**[docs/BENCHMARKS.md](docs/BENCHMARKS.md#threads--t-batch-threads--tb-and-two-concurrent-clients--measured)**.

## The 1M-token context: what works, what doesn't, and what it costs

The 262k servable ceiling, the YaRN cap, what 1M costs in memory, and the
three routes to a real 1M window: **[docs/DEEP-CONTEXT.md](docs/DEEP-CONTEXT.md)**.

### Deep positions: the amdgpu watchdog wall — and how to remove it

The 136,965 "Vulkan wall" was the kernel lockup watchdog — forensics and the
`lockup_timeout=-1` intervention (full window, 254,356, verified):
**[docs/DEEP-CONTEXT.md](docs/DEEP-CONTEXT.md#deep-positions-the-amdgpu-watchdog-wall--and-how-to-remove-it)**.

## Vulkan vs ROCm, which and why?

The measured A/B, speed/stability pictures, and the practical ranking — in
one chart, incremental prefill while the context fills, our two GPU
backends head-to-head:

```mermaid
xychart-beta
    title "Incremental prefill t/s vs FILLED context — Vulkan (lockup_timeout=-1) vs ROCm"
    x-axis "positions filled" ["19.5k","39k","58.7k","78k","97.8k","117k","137k","156k","176k","196k","215k","235k","254k"]
    y-axis "prefill tok/s" 0 --> 350
    line [328, 266, 218, 177, 144, 118, 100, 86, 75, 67, 60, 54, 49]
    line [262, 165, 102, 71, 55, 44, 37, 32, 28, 25, 22]
```

Vulkan leads at every depth (2.7× by 117k) and, with the amdgpu watchdog
out of the way, fills the **entire 262k window** — the old "Vulkan dies at
137k" was the kernel killing slow-but-legal dispatches, not a driver bug
(forensics + intervention in the page below). The full story — bare-bench
parity, DFlash2-on-ROCm, the sibling-project comparisons, the HIP build recipe:
**[docs/BACKENDS.md](docs/BACKENDS.md)**.

### How this compares with sibling projects

halofpx (measured, pinned), ds4 (builds on our Halos — bake-off
candidate), vllm.cpp (right engine, AMD support pending), FreeToken
(edge-native MoE serving — big ideas, NVIDIA-first for now), Lemonade
(AMD-backed server layer, explicit gfx1151 support):
**[docs/BACKENDS.md](docs/BACKENDS.md#how-this-compares-with-sibling-projects)**.

## Stability without the kernel GPU watchdog (lockup_timeout=-1 playbook)

Three-layer unattended stability — hardware TCO, the GPU canary, the scoped
reboot grant: **[docs/DEEP-CONTEXT.md](docs/DEEP-CONTEXT.md#stability-without-the-kernel-gpu-watchdog-lockup_timeout-1-playbook)**.

## Reasoning levels: cost and quality — measured

Levels are style, not cost; only `reasoning_budget_tokens` is a real cap;
thinking inside a bounded budget can starve the answer — and what we run
because of it: **[docs/REASONING.md](docs/REASONING.md)**.

## Models — Unsloth Dynamic GGUFs, aligned with the repo tip

Which GGUFs we run and why, the v3.0 tie-battery, the Q4 drop:
**[docs/BUILDING.md](docs/BUILDING.md#models--unsloth-dynamic-ggufs-aligned-with-the-repo-tip)**.

The official Qwen benchmark card, charted and commented — what the vendor
measured on BF16 (≈ our Q8, per the tie-battery):
**[docs/QWEN-CARD.md](docs/QWEN-CARD.md)**.

Every weight's full sha256 sits in the comment above its `model =` line in
[`models/models.ini`](models/models.ini) — **always verify before first use**
(`sha256sum models/<file>.gguf`), or run `scripts/download_models.sh --check`
to verify all at once.

## Environment · Dependencies · Build from source · The toolbox

Environment notes, the OBSERVED dependency set, building the fork, the
prebuilt toolbox: **[docs/BUILDING.md](docs/BUILDING.md#environment)**.

## Optional: HIP variant (ROCm build)

The no-root TheRock build recipe: **[docs/BACKENDS.md](docs/BACKENDS.md#optional-hip-variant-rocm-build)**.

## Finding the sweet spots — the config sweep

Every flag in our recipes earned its place: we swept KV types, draft
widths, batch sizes, thread counts, host state — dozens of back-to-back
duels — and kept only what measured faster *without* a quality cost.
The surprising wins live here too: why f16 KV beats quantized KV on
speed AND quality, the exact draft width where DFlash2 peaks, and which
"obvious" tuning knobs turned out to be inert.
**[docs/BENCHMARKS.md](docs/BENCHMARKS.md#sweep-findings-at-a-glance)**.
## Lessons learned

Ten hard-won rules — measure back-to-back, zram eats inference, mlock fails
silently, penalties poison speculative decode, the KV-contamination trap,
and the "it loads ≠ it works" vision lesson:
**[docs/LESSONS.md](docs/LESSONS.md)**.

<a id="ideas-parked-help-wanted"></a>

## Ideas, parked

Our open threads — the research menu for anyone (including future us) who
wants to pick one up:

- **Two-Halo fleet**: USB4 direct link (cable inbound, runbook ready),
  llama.cpp RPC "virtual halo", DeepSeek V4 Flash as the quality frontier.
- **Engine bake-off**: ds4, vllm.cpp, audio.cpp — all three *build* on our
  Halos today (verified).
- **Quality & reasoning**: what's left of the measurement program.
- **Fleet growth**: enrolling the LAN's beefy boxes (i9/RTX, i7/8GB) as
  heterogeneous backends.
- **The scout**: nightly research dream → the auto-healing, auto-evolutive
  ladder (observe → propose → heal → evolve; operator seals every rung).
- **Upstream karma**: our filed issues and the PRs we owe the community.

Full detail, statuses, and the design thinking:
**[docs/IDEAS.md](docs/IDEAS.md)** · the fleet's own docs:
[MULTI-HALO](docs/MULTI-HALO.md).

Something catch your eye? Open an issue — measured numbers welcome, vibes
politely declined.

## 🙏 Thanks to the authors of this software stack

This experiment stands entirely on other people's work:

- **[Nathanw1014](https://github.com/Nathanw1014)** — the
  [strix-halo llama.cpp toolbox](https://github.com/Nathanw1014/strix-halo-llamacpp)
  and fork branches: the FA dequant-once / transpose prefill fixes, the mmid MoE
  work, the evidence-driven benchmark methodology, and the prebuilt payloads this
  repo leans on. Also the author of the r/LocalLLaMA benchmarks this README
  reality-checks against.
- **[aic0d3r](https://github.com/aic0d3r)** — the independent port/validation of the
  prefill stack onto current main
  ([ROCmFPX#86](https://github.com/charlie12345/ROCmFPX/issues/86)), which confirmed
  the fixes and documented the silent-CPU-fallback trap.
- **Gaetan Puleo** — the DeepSeek V4 lightning-indexer Vulkan kernels contributed to
  the fork.
- **The r/LocalLLaMA community behind the
  [“Qwen3.8-27B Q5_K_XL on Strix Halo at 31 t/s decode” thread](https://www.reddit.com/r/LocalLLaMA/comments/1vsw6nz/qwen3827b_q5_k_xl_on_strix_halo_at_31_ts_decode/)**
  — the post that inspired these tests, and specifically
  [the comment](https://www.reddit.com/r/LocalLLaMA/comments/1vsw6nz/comment/p4tku1z/?context=3)
  whose config (Q8 target, DFlash2 draft 4, u/ub 2048) seeded our sweep starting point.
- **[llama.cpp](https://github.com/ggml-org/llama.cpp) / ggml** — the whole enterprise:
  the upstream project and its maintainer team and community.
- **[Mesa / RADV](https://www.mesa3d.org/) and the [AMD ROCm](https://rocm.docs.amd.com/)
  teams** — the open Vulkan and compute stacks that make gfx1151 a first-class
  citizen, and the driver-level compute work this fork's kernels assume.
- **[Unsloth](https://unsloth.ai/)** — the UD (Unsloth Dynamic 1.2 2-quant v2)
  Q5–Q8_K_XL quantizations used as targets across these experiments
  ([repo](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF)),
  and the community's quant tooling.
- **The Qwen team (Alibaba)** — the Qwen 3.8 model family these configs run.
- **[u/froggeric](https://www.reddit.com/user/froggeric)** — author of
  [*Fixed jinja chat template for Qwen 3.5/3.6 and the Qwen3.8 family*
  (r/LocalLLaMA)](https://www.reddit.com/r/LocalLLaMA/comments/1vnm7le/fixed_jinja_chat_template_for_qwen_35_36_and_the/).
  The `models/sharp.jinja` template shipped here is that work
  (`qwen3.8-froggeric-v22.1.1`) — it fixed the broken tool-call/thinking formatting
  that stock templates produce for this model family. Without it the server output
  would be garbage with tools enabled.
## License

[MIT](LICENSE) © 2026 PieBru. The configs and notes here are MIT; the
[strix-halo llama.cpp fork](https://github.com/Nathanw1014/llama.cpp) and llama.cpp
itself remain under their own MIT license, and the model weights (not in this repo)
belong to their respective publishers.
