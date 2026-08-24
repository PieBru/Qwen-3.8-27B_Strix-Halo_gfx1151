# Qwen3.8-27B on Strix Halo (Radeon 8060S / gfx1151)

> *Speed is useful, but quality is fundamental — one subtle bug fewer or a better
> codebase always pays for itself in wall-time gained.*

Run Qwen3.8-27B with the [strix-halo llama.cpp](https://github.com/Nathanw1014/strix-halo-llamacpp)
fork on a Ryzen AI MAX+ 395, with DFlash2 speculative decoding.
## Why this exists: cloud-free intelligence on a desk

If you are a solo developer with an AI agent working around the clock, a
privacy-sensitive operator, or any other entity that wants to be free from
cloud chains — read on. An all-purpose computer that cost **less than €2,000**
(launch offer) now serves a 27-billion-parameter reasoning model, entirely
from your own desk. Which machine? We tested on a **GMKtec EVO-X2** (Ryzen
AI MAX+ 395, 128 GiB) — [amazon.it/dp/B0F6X332N6](https://www.amazon.it/dp/B0F6X332N6/) —
any mini-PC or desktop with the same AMD Strix Halo APU works the same. **Not
affiliated**: no sponsorship, no free hardware, no affiliate links (the
shopping link above is a plain product URL, no referral tag); we paid for
ours. External links in this README point only to the open-source projects,
model publishers, hardware references, and community threads this work builds
on or measures — see
[Acknowledgements](#-thanks-to-the-authors-of-this-software-stack) — never to
sponsored placements.

- **No API keys, no quotas, no meters.** The model lives in your RAM
  (~122 GiB of it, mlock'd — the box's whole personality is inference).
- **Real speeds, measured**: 16–21 tokens/s typical sustained decode with
  DFlash2 speculative decoding (content-dependent: acceptance spans
  0.28–0.91, so the same model spans ~15–35 t/s; peaks near the top on
  narrative-style output), ~330 t/s prefill; a five-recipe menu (quality /
  balanced / speed / vision / a context dial to a 256k-token window) you
  switch per request, like a reasoning level.
- **Sips power**: ~85 W sustained at full tilt — order of magnitude under a
  multi-GPU rig; idle cost roughly a lightbulb (~€0.04/night at €0.12/kWh,
  computed from the 85 W figure — verify against your tariff).
- **Private by physics**: prompts never leave the machine. No telemetry to
  disable, no retention policy to trust — unplugged is unambiguous.
- **Yours**: no deprecations, no price changes, no terms-of-service updates
  that quietly reshape your workflow. The stack is open source end to end.

The recipes, the numbers, and every trap we hit (there were many) are
documented below — so your agent can run 24/7 on hardware you own outright.

**How we know (the method behind every number):** all benchmarks are
back-to-back interleaved pairs (lesson #1); every battery's raw evidence is
committed under `results/` — CSVs, server logs, kernel journal excerpts;
experiments run under pre-registered decision rules (`docs/PLAN-INDEX.md (landed — archived locally)`)
and the reasoning batteries' answer keys are computed by the graders
themselves; claims carry OBSERVED / INFERRED / REPORTED labels; and when our
own adversarial README audit caught numbers without committed evidence, we
corrected the README rather than the evidence (2026-08-23). If a number here
can't be re-run from this repo, it doesn't belong here.

## Provenance note

> *Humans architected, verified, sealed. AI assistants built and wrote all the
delivered stuff.*

The architecture decisions, every acceptance of a
measurement, and the seal of each release were human; the builds, probes,
batteries, tables, and most of this documentation were produced by AI
assistants under that supervision — including this sentence. Every number in
this README traces to a command you can re-run.
## TL;DR — reproduce on any gfx1151 (Strix Halo) box

Six steps, ~45 min, no desktop environment needed (Arch minimal headless verified
end-to-end on a second box, 2026-08-21; Ubuntu may work, untested):

```bash
# 0. this repo (launchers, recipes, systemd unit, model downloader)
git clone https://github.com/PieBru/Qwen-3.8-27B_Strix-Halo_gfx1151 && cd Qwen-3.8-27B_Strix-Halo_gfx1151
# 1. deps (Arch; versions OBSERVED working: shaderc 2026.3, libdrm 2.4.134)
sudo pacman -S --needed base-devel cmake ninja git shaderc vulkan-headers \
  spirv-headers vulkan-icd-loader vulkan-radeon vulkan-tools libdrm
# 2. build the fork INSIDE the repo (llama.cpp/ is gitignored; or skip the
#    build: prebuilt v0.6.6 tarball — same commit, see Quick Start)
git clone https://github.com/Nathanw1014/llama.cpp && cd llama.cpp && git checkout strix-halo-vulkan
cmake -B build-vk -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DLLAMA_CURL=OFF
cmake --build build-vk --target llama-server llama-cli llama-bench -j && cd ..
# 3. models — everything (targets + DFlash2 draft + vision mmproj), verified:
./download_models.sh            # ~73 GiB total; or pick: q6 q8 q5 draft mmproj
# 4. verify backend + bare perf (expect: Vulkan0 AMD 8060S; quiet box, f16 KV:
#    Q6 pp512 ~346 / tg32 ~8.6; Q8 pp512 ~366 / tg32 ~7.3 — zram churn can halve tg)
./build-vk/bin/llama-cli --list-devices
./build-vk/bin/llama-bench -m MODEL-UD-Q6_K_XL.gguf -ngl 99 -fa on -t 16 -b 4096 -ub 4096 -p 512 -n 32 -d 0,8192 -r 2
# 5. serve a preset (balanced = Q6 daily driver, ~17-21 t/s on a quiet box)
./run_llama-server.sh --goal balanced
curl -s localhost:8081/completion -H 'Content-Type: application/json' \
     -d '{"prompt":"Explain briefly why the sky is blue at sunset.","n_predict":64}'
```

Numbers are for an 85 W sustained PPT box; expect ±10% run-to-run. On a
**default kernel**, deep Vulkan fills die at ~137k positions — but that wall
is the **amdgpu lockup watchdog**, not Vulkan (kernel forensics 2026-08-23:
every "device lost" was a ring timeout + reset on our own submission). With
`amdgpu.lockup_timeout=-1` on the cmdline, the same battery filled the
**entire 262k window** (254,356 positions, zero errors) — see
[Vulkan vs ROCm](#vulkan-vs-rocm-which-and-why),
[the deep-positions A/B](#deep-positions-the-amdgpu-watchdog-wall--and-how-to-remove-it),
and the [stability playbook](#stability-without-the-kernel-gpu-watchdog-lockup_timeout-1-playbook).
(ROCm/TheRock 7.15 needs no kernel change and survived 215,228 on the same
battery — the fallback when boot params are off-limits.)
Once verified, pick your workload recipe from the
[**recipe menu**](docs/RECIPES.md) table.
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

## Quick start: run the prebuilt release (time-saving)

No build, no toolchain: the toolbox tarball bundles its own RADV + libdrm
and is verified perf-identical to the fork tip —
**[docs/QUICKSTART.md](docs/QUICKSTART.md)**, or build from source in the
[TL;DR](#tldr--reproduce-on-any-gfx1151-strix-halo-box).

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
parity, DFlash2-on-ROCm, the halofpx comparison, the HIP build recipe:
**[docs/BACKENDS.md](docs/BACKENDS.md)**.

### How this compares with halofpx as of 2026-08-22

The measured-quality-first comparison with the speed-first cousin:
**[docs/BACKENDS.md](docs/BACKENDS.md#how-this-compares-with-halofpx-as-of-2026-08-22)**.

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

## Environment · Dependencies · Build from source · The toolbox

Environment notes, the OBSERVED dependency set, building the fork, the
prebuilt toolbox: **[docs/BUILDING.md](docs/BUILDING.md#environment)**.

## Optional: HIP variant (ROCm build)

The no-root TheRock build recipe: **[docs/BACKENDS.md](docs/BACKENDS.md#optional-hip-variant-rocm-build)**.

## Config research (`sweep_llama_configs.sh`)

The staged sweep harness and how every table number was produced:
**[docs/BENCHMARKS.md](docs/BENCHMARKS.md#config-research-sweep_llama_configssh)**.
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
  The `sharp.jinja` template shipped here is that work
  (`qwen3.8-froggeric-v22.1.1`) — it fixed the broken tool-call/thinking formatting
  that stock templates produce for this model family. Without it the server output
  would be garbage with tools enabled.
## License

[MIT](LICENSE) © 2026 PieBru. The configs and notes here are MIT; the
[strix-halo llama.cpp fork](https://github.com/Nathanw1014/llama.cpp) and llama.cpp
itself remain under their own MIT license, and the model weights (not in this repo)
belong to their respective publishers.
