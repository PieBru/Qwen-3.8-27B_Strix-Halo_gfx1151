# Qwen3.8-27B on Strix Halo (Radeon 8060S / gfx1151)

> *Speed is useful, but quality is fundamental — one subtle bug fewer or a better
> codebase always pays for itself in wall-time gained.*

Run Qwen3.8-27B with the [strix-halo llama.cpp](https://github.com/Nathanw1014/strix-halo-llamacpp)
fork on a Ryzen AI MAX+ 395, with DFlash2 speculative decoding.

## TL;DR — reproduce on any gfx1151 (Strix Halo) box

Five steps, ~30 min, no desktop environment needed (Arch minimal headless verified;
Ubuntu may work, untested):

```bash
# 1. deps (Arch; versions OBSERVED working: shaderc 2026.3, libdrm 2.4.134)
sudo pacman -S --needed base-devel cmake ninja git shaderc vulkan-headers \
  spirv-headers vulkan-icd-loader vulkan-radeon vulkan-tools libdrm
# 2. build the fork (or skip: prebuilt v0.6.6 tarball — same commit, see Quick Start)
git clone https://github.com/Nathanw1014/llama.cpp && cd llama.cpp && git checkout strix-halo-vulkan
cmake -B build-vk -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DLLAMA_CURL=OFF
cmake --build build-vk --target llama-server llama-cli llama-bench -j
# 3. models: UD K_XL quants from the unsloth repo tip (fingerprints in Models)
#    https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/main
#    plus a Qwen3.8-27B-DFlash2 draft GGUF
# 4. verify backend + bare perf (expect: Vulkan0 AMD 8060S; quiet box, f16 KV:
#    Q6 pp512 ~346 / tg32 ~8.6; Q8 pp512 ~366 / tg32 ~7.3 — zram churn can halve tg)
./build-vk/bin/llama-cli --list-devices
./build-vk/bin/llama-bench -m MODEL-UD-Q6_K_XL.gguf -ngl 99 -fa on -t 16 -b 4096 -ub 4096 -p 512 -n 32 -d 0,8192 -r 2
# 5. serve a preset (balanced-speed = Q6 daily driver, ~29 t/s on a quiet box)
./run_llama-server.sh --goal balanced-speed
curl -s localhost:8081/completion -H 'Content-Type: application/json' \
     -d '{"prompt":"Explain briefly why the sky is blue at sunset.","n_predict":64}'
```

Numbers are for an 85 W sustained PPT box; expect ±10% run-to-run. Deep prefill
**crashes ≥128k ctx** (`vk::DeviceLostError`) on this stack — 64k is the ceiling.
Once verified, pick your workload recipe from the
[**Recommended configs (per goal)**](#recommended-configs-per-goal) table.

## Quick start: run the prebuilt release (time-saving)

Skip the build entirely — the toolbox releases ship a portable, self-contained stack
(latest `v0.6.6`, `strix-halo-llamacpp-vulkan-portable.tar.gz`) that bundles its own
RADV + libdrm, so it won't touch the system driver and needs no compile toolchain:

```bash
curl -L https://github.com/Nathanw1014/strix-halo-llamacpp/releases/download/v0.6.6/strix-halo-llamacpp-vulkan-portable.tar.gz | tar xz
# the tarball's launcher self-sets the perf env; run its server directly with the
# preset flags (the repo's run_llama-server.sh hardcodes the local build path):
#   ./vulkan/llama-server -m <UD-Q6_K_XL.gguf> -md <DFlash2-Q8_0.gguf> -ngl all -fa on \
#       -c 65536 -b 4096 -ub 4096 --spec-type draft-dflash --spec-draft-n-max 6 --host 0.0.0.0
```

Verified on this box: the tarball pins commit `7b6c613`; the fork tip is
perf-identical within 1% (chat-parser-only delta since). Read on only if you want
to build from source.

## What's in this repo

Model weights (`.gguf`) and the `llama.cpp/` clone are local-only; this repo holds
the serving setup and notes:

- `run_llama-server.sh` — **unified launcher**: `--goal max-quality|balanced-quality|balanced-speed|max-speed`
  single-model presets, or `--router` to serve every recipe; every field overridable
  (`--model`, `--ctx`, `--nmax`, `--kv`, `--port`, `--draft`, `--no-mlock`, `--dry-run`;
  `--help` explains each)
- `models.ini` — the router recipes (the names in the table below)
- `llama-router.service` — systemd user unit (installs to `~/.config/systemd/user/`)
- `sharp.jinja` — fixed chat template for this model family (see Thanks)
- `update_strix-halo-llamacpp_vulkan.sh` — pull/rebuild the fork + backend check
- `sweep_llama_configs.sh` — staged config search ([config research](#config-research-sweep_llama_configssh))

## Recommended configs (per goal)

| Goal | Router recipe (`models.ini`) | Command (`run_llama-server.sh …`) | `-c` | RAM | left | tg (served) | pp4k | PPL / KLD↑ | When to pick |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| **Max quality** | `Qwen38-27B-Q8-192K-quality` | `--goal max-quality` (Q8) | 196608 (sane ceiling) | ~54 GiB | ~68 GiB | ~25 | ~330 | 4.692 / ref | final answers, code, synthesis — quality over everything |
| **Balanced → quality** | `Qwen38-27B-Q8-65K-balanced-quality` | `--goal balanced-quality` (Q8) | 65536 (default) | ~45 GiB | ~78 GiB | ~25 | ~331 | 4.692 / ref | default when correctness matters more than latency |
| **Balanced → speed** ✅ default | `Qwen38-27B-Q6-65K-balanced-speed` | `run_llama-server.sh` (Q6) | 65536 | ~40 GiB | ~83 GiB | **~29** | ~306 | 4.706 / 0.0073 | daily driver — Q6 quality is good anyway; best quality/speed balance |
| **Max speed** | `Qwen38-27B-Q6-65K-fast` | `--goal max-speed` (Q6) | 65536 (trim to the task if you like) | ~40 GiB | ~83 GiB | **~29** | ~306 | 4.706 / 0.0073 | interactive churn |
| **Fast churn** | `Qwen38-27B-Q5-65K-turbo` | `--model q5` (Q5) | 65536 | ~35 GiB | ~88 GiB | **~32** | ~297 | 4.722 / 0.0137 | fastest decoder on the box (n-max 5); lightest spec footprint |
| **Vision** | `Qwen38-27B-Q6-65K-vision` | router-only (mmproj, no spec) | 65536 | ~32 GiB | ~91 GiB | ~8.4 | — | 4.706 / 0.0073 | the only image-capable recipe — runs `spec-type = none` (see lessons #7); lightest resident footprint (no draft model) |

Notes on the columns:

All presets: DFlash2-Q8_0 draft, f16 KV, n-max 6 (turbo: 5), `-b/-ub 4096`, `-t 16 -tb 32`,
`-lm mmap+mlock`, sharp.jinja template, metrics on. tg = sustained decode on a quiet
box; fresh-load peaks run higher. **RAM** = resident footprint vs idle router
(weights + draft + KV + compute buffers; mlock'd, never swapped), **left** = `free`
"available" with that recipe live — headroom for concurrent models/activities.
Measured 2026-08-21 on a 124 GiB box via the router; variance ±1–2 GiB.

tg was measured fresh-slot (first task after load), temp-0, at each row's own `-c`:
same-quant rows tie because ctx allocation is free (see
[findings](#sweep-findings-at-a-glance)). Served defaults are sampling-penalty-free.
⚠️ Opting into `repeat_penalty 1.05` costs **23–28% decode on every spec recipe**
(it collapses DFlash2 acceptance 0.647 → 0.450); prefill and vision are immune.
Use it per-request, only when repetition actually bites — lessons #9.

PPL / KLD↑ (`llama-perplexity`, 200×512-token chunks of a local docs corpus; use for
internal ranking only — absolute values are corpus-specific). KLD = KL divergence of
the token distribution vs the `UD-Q8_K_XL` reference logits; top-p agreement with the
reference: Q8 100% (is the reference), Q6 96.5%, Q5 95.5%. PPL depends only on the
weights — recipes sharing a quant share these values; spec decode, mmproj, ctx and
penalties don't enter.

Heads-up for concurrency: `--models-max 1` is policy, not a hard memory limit —
two small recipes would *fit* (e.g. turbo + fast ≈ 75 GiB), but three resident
models exhausted memory and hard-hung the box, so 1 stays the default; raise only
with verified headroom. Nothing loads at boot: each recipe's **first request pays a
one-time load** (~6 s warm, up to ~13 s from cold page cache), and switching recipe
names under `--models-max 1` unloads the previous one first, paying the same load
again — steady-state serving after that is instant.

Decision rule: **Q8 when quality is the point, Q6 when tokens/s is** — prefill is
equal (~250–330 pp4k), decode favors Q5-turbo > Q6 > Q8 at every context size.

## Running it

Single model with a preset (any field overridable, `--help` for all):

```bash
./run_llama-server.sh --goal balanced-speed            # Q6 @ 64k — daily driver
./run_llama-server.sh --goal max-quality               # Q8 @ 192k — final answers
./run_llama-server.sh --goal max-speed --ctx 32768     # trimmed ctx for pure t/s
./run_llama-server.sh --model q8 --kv q8_0 --nmax 4   # fully custom
```

### Serving all recipes (the router)

One port, every recipe from the table, loaded on demand:

```bash
./run_llama-server.sh --router --port 8080              # foreground
# or as a boot-persistent user service:
cp llama-router.service ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user enable --now llama-router

curl -s localhost:8080/v1/chat/completions -H 'Content-Type: application/json' \
     -d '{"model":"Qwen38-27B-Q6-65K-balanced-speed","max_tokens":64,
          "messages":[{"role":"user","content":"hi"}]}'
```

Recipe names are `Qwen38-27B-<QUANT>-<CTX>-<ROLE>`; the short names
(`Qwen38-27B-turbo`, `-fast`, …) still work as aliases. Recipe-specific keys
(weights, ctx, spec config, mmproj) live in `models.ini` sections — see the header
of that file for the key reference and the CLI-vs-section precedence rule (lessons #8).

## Test — verify GPU, not silent CPU fallback

The headline failure mode in BUILD.md: a Vulkan ICD manifest without `api_version`
gets skipped by the loader and llama.cpp **silently falls back to CPU** (~7x slower).
Not an issue with the system RADV, but always confirm the backend:

```bash
# backend must read GPU/Vulkan (AMD Radeon 8060S), not CPU
./build-vk/bin/llama-cli --list-devices
./build-vk/bin/llama-bench -m <model.gguf> -ngl 99 -fa on -t 16 -b 4096 -ub 4096 -p 512 -n 32 -d 0,8192 -r 2
```

Quiet-box reference for that bench command (f16 KV): Q6 pp512 **~346** / tg32
**~8.6**; Q8 pp512 **~366** / tg32 **~7.3**; shallow pp512 varies ±10% run-to-run at
85 W. Note `llama-bench` measures bare decode only — it takes most server flags but
not `-md`/`--spec-*` (no draft support), so spec-decode gains don't show here.

## Sweep findings at a glance

How these were measured: [config research](#config-research-sweep_llama_configssh).

| Axis | Winner | Evidence |
|---|---|---|
| KV type (target & draft) | **f16 / f16** | f16 is faster than q8_0 on both models (Q6 20.8 vs 19.2, Q8 16.6 vs 15.6 t/s) and higher fidelity — 128 GB unified makes it free |
| `--spec-draft-n-max` | **6** | 6–7 plateau, 4 clearly worse (DFlash2 `block_size=8, n_extract=5`); Q6: n6 28.6 > n5 27.4 > n4 24.8 |
| `-c` allocated ctx | **65536 default; allocation is free up to 256k** | decode flat 64k–256k (Q6 20.2 ±0.2 t/s, Q8 ~17.6); the ≥128k crash is deep-prefill-only, not an allocation limit |
| `-b/-ub` | **4096** | tg flat ±2% across 2048/4096/8192; 4096 = +6% deep prefill over 2048; 8192 doubles compute buffers for nothing |
| `-tb` | **32** | tb16 within ~1% — GPU-bound |
| Model choice | **Q6 speed / Q8 quality** | decode favors Q6 at every ctx; Q8 prefill edges Q6 (pp512 366 vs 346 — Q8_0's symmetric blocks ride the fast kernel path). Q4 was evaluated and dropped — acceptance collapse, see Models |
| Host state | **`-lm mmap+mlock`** | zram-swapped weight pages cost up to ~30% decode; mlock makes weights unswappable |
| dflash fine-tuning | **inert beyond n-max** | `spec-draft-n-min` 2/3 and `spec-draft-p-min` 0.3/0.9 change nothing (bit-identical decodes, acceptance 0.647); stacking `ngram-map-k` on dflash *hurts* (29.0 → 27.4 t/s). Draft quality sets acceptance — `n_max` is the only working knob |
| `--kv-unified` | **no effect at `-np 1`** | measured 2026-08-21 on Q6@64k and Q8@192k (journal-confirmed `kv_unified='true'`): tg and RAM identical within noise. Its purpose is sharing one KV buffer across parallel slots; with a single slot (and the hybrid SSM's tiny KV) there is nothing to unify. It flips on by itself if slots ever go auto |

## Models — Unsloth Dynamic GGUFs, aligned with the repo tip

The target GGUFs are the Unsloth Dynamic **K_XL** quants, aligned with the
unsloth repo **tip** (v3.0 re-quant run) as of 2026-08-21. A full tie-battery
(fresh-slot decode, prefill, perplexity, KL-vs-Q8) showed the tip K_XL files
tie the previous pinned v2 set within noise on every axis, so we track the tip;
the v2 files were verified equivalent and then removed locally (their
fingerprints remain in git history for refetching). `Q8_K_XL` was byte-identical
between the two revisions.

**<https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/main>**

| File | Role | Exact size (bytes) | sha256 starts with |
|---|---|---:|---|
| `Qwen3.8-27B-UD-Q8_K_XL.gguf` | quality recipes | 31,457,991,680 | `af36ecb6b5db` |
| `Qwen3.8-27B-UD-Q6_K_XL.gguf` | speed recipes + vision | 25,299,061,664 | `701d8fa9ed21` |
| `Qwen3.8-27B-UD-Q5_K_XL.gguf` | turbo recipe | 20,876,938,144 | `8601193d3d57` |

`UD-Q4_K_XL` is deliberately absent: evaluated and dropped — the measured case
against it is below.

Verify a download against the table (`ls -l` size, or `sha256sum` prefix).

The `DFlash2-*` draft GGUFs come from elsewhere (not in that repo) and only load
via `-md` next to a target — run standalone they fail with
`dflash requires ctx_other to be set`. `mmproj-F16.gguf` is the vision projector,
wired per-recipe via the `mmproj` key in `models.ini`.

### Context beyond 192k: the 1M question (researched, not servable yet)

The model card declares 262,144 native context, "extensible up to 1,000,000
tokens" via YaRN (factor 4.0 from the 262,144 training ctx), and budgets
262k reasoning + 131k output for long-horizon agentic work inside that window.
We built and load-tested a `Q6-1M-yarn` recipe (`rope-scaling = yarn`,
`rope-scale = 4`, `yarn-orig-ctx = 262144`, `c = 1048576`):

- **The allocation fits this box**: 100.9 of 122.1 GiB GTT with f16 KV (RAM
  avail 14.3 G — tight; q8_0 KV would land ~75 G, comfortable).
- **But it can't serve**: the fork caps every slot to the model's training ctx
  (262,144) with no YaRN exemption (server-context.cpp) — the KV is allocated,
  then unusable beyond 262k.
- **And prompts beyond ~128k hit the Vulkan deep-prefill crash** regardless
  (the known `vk::DeviceLostError` ceiling).

So `Q8-192K-quality` remains the practical maximum served recipe, and a ready-
to-enable 1M recipe is kept commented at the bottom of `models.ini` for when
the fork lifts both blockers. No quality claim is made either way: positions
beyond 262k are extrapolated (YaRN-interpolated RoPE), not trained.

### Dynamic Quant v3.0 — `UD-Q6_K_M`: compatible alternative, not the default

Unsloth's v3.0 `Qwen3.8-27B-UD-Q6_K_M.gguf` (23,088,409,504 bytes, sha256
`493301830a59…`) loads cleanly on this stack (same tensor warnings as v2, identical
arch/vocab/params) and serves with DFlash2:

| | Q6_K_XL (v2.0, default) | Q6_K_M (v3.0) |
|---|---:|---:|
| file size | 24.1 GiB | 21.5 GiB |
| decode tg / prefill pp4k | 29.0 t/s / 306 | 30.8 t/s / 293 |
| DFlash2 acceptance | 0.64744 | 0.64744 |
| GTT resident | 37.7 G | 35.0 G |
| perplexity (local corpus) | 4.7062 | 4.7051 (tied) |
| KL div vs Q8 ref / top-p agreement | 0.00734 / 96.5% | 0.00984 / 96.1% |

Quality-first verdict: the v2 XL stays the default — v3.0's token distribution sits
measurably further from the Q8 reference, and it loses at prefill. Pick v3.0 when
2.8 GiB of RAM or decode t/s matter more; to adopt it, add a `models.ini` section
pointing `model =` at the _M_ file (copy any Q6 section and edit).

### `UD-Q4_K_XL`: evaluated and dropped (2026-08-21) — GGUF deleted locally

The natural "warp speed" candidate (16.7 GiB weights, lightest possible target)
loses in practice: DFlash2 acceptance collapses with the extra quant noise
(0.41–0.59 vs 0.647 on Q5/Q6), so best-case decode is **28.2 t/s (n-max 4)** vs
Q5-turbo's **32.3** — the bandwidth advantage is eaten by rejected drafts. Quality
is the set's floor (KLD 0.0266 vs Q8 ref — 2× Q5's 0.0137; top-p agreement
94.7%). It also can't unlock 1M context: that's blocked by the slot cap and
prefill ceiling (see above), both quant-independent, and KV dominates the
memory budget anyway. All Q4 references are removed from the recipes/launcher;
the quant remains fetchable from the unsloth repo history if ever re-needed.

## Environment

Everything below was verified on **Arch Linux installed as a minimal headless
server** — no desktop environment, GPU used purely as a compute device — and that
is what we **use and recommend for serving LLM inference**: latest compilers and
Mesa/RADV with zero desktop drag, and nothing competing with the GPU for memory
bandwidth. **Ubuntu may work but we didn't test it**; the package names in the
dependencies section are Arch's, so translate them (`apt`/universe, possibly newer
upstream packages for shaderc/RADV) before assuming parity.

Adapted from [BUILD.md](https://github.com/Nathanw1014/strix-halo-llamacpp/blob/master/BUILD.md)
for a box where **ROCm and Vulkan (system RADV) are already installed and proven working**.

Verified on this machine (Arch Linux, Ryzen AI MAX+ 395 / Radeon 8060S, gfx1151):

- `rocminfo` → gfx1151 ✔
- `vulkaninfo` → RADV, ICD `radeon_icd.json` ✔
- `glslc 2026.3` — meets the "current shaderc" requirement ✔
- Vulkan + SPIRV headers present in `/usr/include` ✔

## Dependencies (Arch Linux — pacman / paru)

Everything is in the official repos; no AUR needed (`paru -S` works identically if
that's your habit). Package set verified against this working box (`pacman -Qo`):

```bash
# Vulkan build (required) — versions OBSERVED working:
#   shaderc 2026.3-1 (glslc)  vulkan/spirv-headers 1.4.357  libdrm 2.4.134
sudo pacman -S --needed base-devel cmake ninja git \
  shaderc vulkan-headers spirv-headers vulkan-icd-loader vulkan-radeon \
  vulkan-tools libdrm

# ROCm / HIP (optional, for the decode-fix build) — OBSERVED set is 7.2.4:
#   rocm-hip-sdk pulls hipcc + runtime, comgr, rocblas, rocm-llvm
sudo pacman -S --needed rocm-hip-sdk rocm-cmake
```

`vulkan-radeon` (system RADV) is the driver llama.cpp actually runs on — no bundled
Mesa needed on this box. `vulkan-tools` provides `vulkaninfo` for the checks above.

## Build from source — for testing improvements

```bash
git clone https://github.com/Nathanw1014/llama.cpp && cd llama.cpp
git checkout strix-halo-vulkan
cmake -B build-vk -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON -DLLAMA_CURL=OFF
cmake --build build-vk --target llama-server llama-cli llama-bench -j
```

No `-DVulkan_*` overrides needed: the system glslc (2026.3) and headers already meet
the toolchain requirements. `GGML_NATIVE=ON` is correct here because this CPU *is*
Strix Halo (CI replaces it with explicit Zen 5 toggles only because GitHub runners
aren't).

## The toolbox behind it (BUILD.md)

The upstream repo assembles a portable *toolbox* from 3 (4 with HIP) build outputs
via `build-from-source.sh`:

1. **libdrm ≥ 2.4.133** — meson build, `--prefix=/usr` (the `amdgpu.ids` path is baked
   in at build time), staged with `DESTDIR`.
2. **Mesa RADV (compute-only)** — from Mesa main, `-Dvulkan-drivers=amd`, no
   gallium/llvm. Exists so the tarball ships its own known-good driver.
3. **llama.cpp Vulkan (the actual fixes)** — fork branch **`strix-halo-vulkan`**
   (dequant-once + all-quant transpose + full mmid stack).
4. **llama.cpp HIP (optional decode fix)** — branch `fa-tile-dequant-on-load`,
   built in a ROCm 7.2.4 container targeting gfx1151.

Steps 1–2 only matter for *portability to other machines*. On this box, with working
system RADV, you only need **step 3**.

**Why the fork, measured** (back-to-back `llama-bench` vs mainline, quiet box):

| Metric | fork | stock mainline | fork Δ |
|---|---:|---:|---:|
| Q6 pp512 / @d8192 | 355.8 / 314.8 | 301.0 / 263.7 | **+18% / +19%** |
| Q8 pp512 / @d8192 | 371.6 / 326.1 | 302.9 / 267.0 | **+23% / +22%** |
| tg32 (Q6 / Q8) | 8.60 / 7.30 | 8.55 / 7.27 | parity |

Stock also has no DFlash2 spec-decode at all — the 20→29 t/s layer. **The fork stays
mandatory** until the prefill PRs land upstream
([ggml-org/llama.cpp#25494](https://github.com/ggml-org/llama.cpp/pull/25494) and
follow-ups); when they do, stock inherits the wins and the fork becomes redundant.

## Optional: HIP variant (decode fix)

Branch `fa-tile-dequant-on-load`, built natively since local ROCm works — the ROCm
container in BUILD.md is only for reproducible CI-style builds:

```bash
git clone https://github.com/Nathanw1014/llama.cpp && cd llama.cpp
git checkout fa-tile-dequant-on-load
cmake -B build-hip -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151 \
  -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF
cmake --build build-hip --target llama-server llama-cli llama-bench -j
```

## Config research (`sweep_llama_configs.sh`)

A staged, one-axis-at-a-time search for the optimal server config per target quant
(winners carried forward; every result appended to `results/sweep.csv`, one log per
config under `results/`). Results: [findings at a glance](#sweep-findings-at-a-glance).

```bash
./sweep_llama_configs.sh 0                                # capacity probe
./sweep_llama_configs.sh 1                                # --spec-draft-n-max 3-9, both models
./sweep_llama_configs.sh 2 <best-n6> <best-n8>            # KV types 2x2 (target x draft)
./sweep_llama_configs.sh 3 "Q6 - - 6" "Q8 - - 6"   # ctx ladder 64k(control)→128k→192k→256k
#  (`-` = default f16 KV; SWEEP_TAG_PREFIX=r2- tags repeat passes; optional 6th+
#   fields override the ctx list/order — use to break run-order confounds)
./sweep_llama_configs.sh 4 "Q6 q8_0 q8_0 <n6> <ctx>" ... # -b/-ub 2048/4096/8192
./sweep_llama_configs.sh 5 ...                            # -tb 16 vs 32
```

Guards built in: per-server wait ceiling, fail-fast on dead loads, process-group
cleanup (no orphans), crash-tolerant CSV (status column).

**Methodology:** absolute t/s drifts up to ±25% across a day on this box (zram under
memory churn — lessons #1–2), so every ranking comes from back-to-back runs inside
tight windows, with reversed-order passes to break run-order confounds. Trust only
interleaved comparisons, never numbers from different sessions.

## Lessons learned

1. **Measure back-to-back or not at all.** Absolute t/s drifts with box state; only
   interleaved pairs give trustworthy rankings. Mind **run order** too: the first
   server after a cold start pays page-cache warm-up, so sequential ladders lean
   toward whatever ran last. Reversed-order passes are how you catch both biases.
2. **zram eats inference.** GTT weight pages are shmem-backed → swappable → they
   compress into zram under load churn, and decode then pays per-token
   decompression (up to ~30%). Fixes, best first: (a) `-lm mmap+mlock` so the
   weights can never be swapped (needs `memlock` unlimited — see next);
   (b) tune the pressure that triggers swapping instead of disabling it:
   `vm.swappiness` (default 60 biases toward swapping anon pages; 1–10 makes zram
   a last resort) and `vm.watermark_scale_factor` (how early kswapd wakes);
   (c) `sudo swapoff -a` disables zram entirely until reboot — safe on 128 GB with
   the box otherwise quiet, but it removes the safety net and makes the kernel's
   precautional OOM killer trigger earlier under pressure. We prefer (a)+(b).
3. **mlock needs a limit raise — and fails SILENTLY without it.** Default
   `ulimit -l` here was 8192 KB (8 MB-class) and multi-GB buffers then fail with
   `Cannot allocate memory`. One-time, then re-login:
   `echo -e 'piero soft memlock unlimited\npiero hard memlock unlimited' | sudo tee /etc/security/limits.d/99-llama-mlock.conf`
   ⚠️ The server only *warns* on mlock ENOMEM and keeps serving **unprotected** —
   it does not abort. After re-login verify: `ulimit -l` must print `unlimited`.
4. **Power is a throttling detector, not a cost metric.** We log PPT only to
   confirm the box holds a flat 85 W (no throttle). A Strix Halo's max draw is more
   than an order of magnitude below a pre-Blackwell NVIDIA desktop part — the
   interesting wattage story is elsewhere.
5. **A clean box is part of the benchmark.** You don't need to dedicate the machine
   to inference — but if you want SOTA-at-home, privilege inference quality over
   co-located niceties (a SQL server, several heavy LLMs on the same box). One
   model, mlocked, on quiet unified memory.
6. **Trust but verify the fork's failure modes.** The `vk::DeviceLostError` ceiling
   (deep prefill ≥128k) and the one-off KV core dump were found by sweeping —
   neither appears in casual use. Allocation ≠ prefill: 256k ctx loads in 20 s.
7. **Vision is cheap — until an image actually arrives.** Attaching `mmproj-F16`
   to a spec recipe costs almost nothing statically (+~1.2 GB GTT, +~0.6 s load;
   text decode neutral) and the recipe serves text at full speed — but the first
   real image request dies with `decode() failed: failed to process speculative
   batch`: image embeddings are incompatible with the DFlash2 spec path in this
   fork. Hence vision is its own `Q6-65K-vision` recipe with `spec-type = none` —
   it pays the no-spec decode tax (8.4 t/s vs 21–29 for the same weights with
   spec; image encode itself is fast, <0.5 s warm for 512 px) so every text recipe
   keeps its speed, and it's the lightest resident recipe (~32 GiB, no draft
   model). **"It loads" ≠ "it works"** — a vision setup that was never probed with
   a real image is unverified. (`--mmproj` is a per-section ini key by design; the
   router strips it from the shared CLI.)
8. **Router CLI args silently override per-recipe ini keys.** The router overlays
   its own command line onto every `models.ini` section: a key present in both is
   always won by the CLI and the section key is dead — no warning is logged. The
   per-child `n_max=` journal line is the ground truth. Rule: shared flags ride the
   router CLI, divergent keys (`spec-type`, `spec-draft-n-max`, `model-draft`,
   `mmproj`) live *only* in the sections.
9. **Sampling penalties are poison for speculative decode.** `repeat_penalty 1.05`
   collapses DFlash2 draft acceptance from 0.647 to 0.450 (mean accepted run
   4.8 → 3.4 tokens) — the penalized logits stop agreeing with the draft's
   continuations, so most drafted tokens get rejected and decode reverts toward
   no-spec speed. Measured cost (same loaded model, temp 0): Q6 29.0 → 21.0 (−28%),
   Q5-turbo 32.3 → 24.2 (−25%), Q8 24.7 → 19.1 (−23%). Prefill is immune (no
   sampling) and no-spec recipes (vision) are unaffected. Per-request only, when
   repetition actually bites.
10. **Re-sending an identical prompt after a long-prompt task serves garbage
    (slot-KV contamination).** Repro (any quant, single-slot router): send prompt
    A (short) → send prompt B (~5k tokens) → send A again. The third request's
    prefix-match trusts a KV that no longer holds A, evaluates only ~3–4 of A's
    12 tokens, and decodes from a corrupted context: one quant degenerates to
    garbage (acceptance 0.02), another echoes prior content deterministically
    (acceptance 0.95 — fast *and* wrong). A different prompt recovers immediately.
    **Workaround (verified): per-request `"cache_prompt": false` on re-sent
    identical prompts.** Benchmarking corollary: only fresh-slot (first task after
    load) numbers are honest.

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
