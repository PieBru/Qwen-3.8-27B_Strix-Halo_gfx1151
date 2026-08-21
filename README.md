# Qwen3.8-27B on Strix Halo (Radeon 8060S / gfx1151)

> *Speed is useful, but quality is fundamental — one subtle bug fewer or a better
> codebase always pays for itself in wall-time gained.*

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
# 3. models: UD quants from the PINNED commit (tip files differ! fingerprints in Models)
#    https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/408fcc1807ab
#    plus a Qwen3.8-27B-DFlash2 draft GGUF
# 4. verify backend + bare perf (expect: Vulkan0 AMD 8060S; quiet box, f16 KV:
#    Q6 pp512 ~346 / tg32 ~8.6; Q8 pp512 ~366 / tg32 ~7.3 — zram churn can halve tg)
./build-vk/bin/llama-cli --list-devices
./build-vk/bin/llama-bench -m MODEL-UD-Q6_K_XL.gguf -ngl 99 -fa on -t 16 -b 4096 -ub 4096 -p 512 -n 32 -d 0,8192 -r 2
# 5. verify spec-decode with a preset (balanced-speed = Q6 daily driver;
#    quiet box peaks Q6 ~28 / Q8 ~25 t/s; typical 15-20)
./run_llama-server.sh --goal balanced-speed   # then: curl localhost:8081/completion ..."n_predict":256
```

Numbers are for an 85 W sustained PPT box; expect ±10% run-to-run. Deep prefill
**crashes ≥128k ctx** (`vk::DeviceLostError`) on this stack — 64k is the ceiling.
Once verified, pick your workload preset from the
[**Recommended configs (per goal)**](#recommended-configs-per-goal) table —
max quality / balanced → quality / balanced → speed / max speed, each with its
launcher script and expected numbers.

## Sweep findings at a glance

Full data + methodology in [Config research](#config-research-sweep_llama_configssh);
goal-oriented presets in its [recommendations table](#recommended-configs-per-goal).

| Axis | Finding | Winner |
|---|---|---|
| KV type (target & draft) | f16 **faster** than q8_0 on both models (Q6 20.8 vs 19.2, Q8 16.6 vs 15.6) and higher fidelity — 128 GB unified makes it free | **f16 / f16** |
| `--spec-draft-n-max` | 6–7 plateau, 4 clearly worse (DFlash2 `block_size=8, n_extract=5`) | **6** |
| `-c` allocated ctx | **flat 64k–256k on a quiet box** (Q6 ~20.2 ±0.2 t/s, Q8 ~17.6 at ≥128k; two passes + order-controlled); the drift-era "128k+ decay" was zram, not ctx; ≥128k crash is deep-prefill-only | **65536 default; raise to 192k/256k freely** |
| `-b/-ub` | tg flat ±2%; 4096 = +6% deep prefill over 2048; 8192 buys nothing | **4096** |
| `-tb` | parity (GPU-bound) | **32** |
| Model choice | decode favors Q6 at every ctx; **Q8 prefill edges Q6** (pp512 366 vs 346 — Q8_0's symmetric blocks ride the fast kernel path) | Q6 speed / Q8 quality |
| Host state | zram-swapped weight pages cost up to ~30% decode — mlock the weights | `-lm mmap+mlock` |

Run Qwen3.8-27B with the [strix-halo llama.cpp](https://github.com/Nathanw1014/strix-halo-llamacpp)
fork on a Ryzen AI MAX+ 395, with DFlash2 speculative decoding. This repo holds the
launchers and notes; model weights (`.gguf`) and the `llama.cpp/` clone are local-only.

- `run_llama-server.sh` — **unified launcher**: `--goal max-quality|balanced-quality|balanced-speed|max-speed`
  presets from the config research, every field overridable (`--model`, `--ctx`, `--nmax`,
  `--kv`, `--port`, `--draft`, `--no-mlock`, `--dry-run`; `--help` explains each)
- `update_strix-halo-llamacpp_vulkan.sh` — pull/rebuild the fork + backend check
- `sweep_llama_configs.sh` — staged config search ([config research](#config-research-sweep_llama_configssh))
- Benchmarks and the Reddit-"31 t/s" reality check below

## Environment (read this first)

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
- `glslc 2026.3` — meets the "current shaderc" requirement (the warned-about distro
  2023.8 does not apply) ✔
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

## Models — Unsloth Dynamic 1.2 2-quant **v2**, pinned revision

The target GGUFs benchmarked here are **Unsloth Dynamic 1.2 2-quant v2** — the
**config-research models are `UD-Q6_K_XL` and `UD-Q8_K_XL`** (recommended
launchers); the earlier perf tables also used `UD-Q5_K_XL` (and Q4 before it).
⚠️ The unsloth repo tip now carries **different files under the same names**
(re-quantized — different sizes and LFS hashes), so download the v2 set from
the pinned commit, not `main`:

**<https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/408fcc1807ab>**

| File | Exact size (bytes) | sha256 starts with |
|---|---:|---|
| `Qwen3.8-27B-UD-Q8_K_XL.gguf` — **max quality** | 31,457,991,680 | `af36ecb6b5db` (identical at `main`) |
| `Qwen3.8-27B-UD-Q6_K_XL.gguf` — **max speed preset** | 25,924,152,384 | `739202186fd9` (tip differs!) |
| `Qwen3.8-27B-UD-Q5_K_XL.gguf` — legacy perf tables | 20,218,178,624 | `176a6a3f034e` (tip differs!) |
| `Qwen3.8-27B-UD-Q4_K_XL.gguf` — legacy (still on disk, unused by presets) | 17,923,394,624 | `bee238bbeb3d` (tip differs!) |

Verify a download against the table (`ls -l` size, or `sha256sum` prefix) — a
same-named file of a different size is the newer revision, not the one measured here.
The `DFlash2-*` draft GGUFs come from elsewhere (not in that repo) and are loaded via
`-md`, never standalone.

Local set at the time of the config research: `UD-Q4/Q5/Q6/Q8_K_XL` targets,
`DFlash2-Q8_0` draft (the slightly faster `DFlash2-Q4_K_M` was removed to make
room; it remains fetchable from the pinned commit above).
A stray `mmproj-F16.gguf` (vision projector) is unused by these configs.

## Quick Start: just run the prebuilt release (time-saving)

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

**Verified on this box**: the tarball pins commit `7b6c613`; the local build now
tracks the fork tip (`9b9ac3e38` at last sync — chat-parser-only delta, perf
identical within 1%), Vulkan backend confirmed, tg8 = 7.55 t/s on Q5_K_XL. Read on
only if you want to build from source to test improvements.

## What BUILD.md actually describes (full toolbox)

For context — the upstream repo assembles a portable *toolbox* from 3 (4 with HIP) build outputs via
`build-from-source.sh`:

1. **libdrm ≥ 2.4.133** — meson build, `--prefix=/usr` (the `amdgpu.ids` path is baked
   in at build time), staged with `DESTDIR`.
2. **Mesa RADV (compute-only)** — from Mesa main, `-Dvulkan-drivers=amd`, no
   gallium/llvm. Exists so the tarball ships its own known-good driver.
3. **llama.cpp Vulkan (the actual fixes)** — fork branch **`strix-halo-vulkan`**
   (dequant-once + all-quant transpose + full mmid stack).
4. **llama.cpp HIP (optional decode fix)** — branch `fa-tile-dequant-on-load`,
   built in a ROCm 7.2.4 container targeting gfx1151.
5–7. Package / publish / CI — portable tarball, Docker images, ghcr push, 2-hourly
   dev-build watcher.

Steps 1–2 only matter for *portability to other machines*. On this box, with working
system RADV, you only need **step 3**.

> **Upstreaming outlook.** The fixes measured here are riding llama.cpp PRs
> (e.g. [ggml-org/llama.cpp#25494](https://github.com/ggml-org/llama.cpp/pull/25494),
> the FA dequant-once work). Hopefully they land in mainline — unless surpassed by
> an even better method — at which point stock llama.cpp inherits these wins and
> the fork becomes redundant. Until then: pin the fork (`strix-halo-vulkan`).
>
> **Stock-vs-fork, measured 2026-08-21** (mainline tip `cd26896` with #25494 already
> merged; same-day back-to-back `llama-bench`, quiet box, f16 KV, `-r 1`):
>
> | Metric | fork `7b6c61330` | stock `cd26896` | fork Δ |
> |---|---:|---:|---:|
> | Q6 pp512 / @d8192 | 355.8 / 314.8 | 301.0 / 263.7 | **+18% / +19%** |
> | Q8 pp512 / @d8192 | 371.6 / 326.1 | 302.9 / 267.0 | **+23% / +22%** |
> | tg32 (Q6 / Q8) | 8.60 / 7.30 | 8.55 / 7.27 | parity |
>
> Stock also has no DFlash2 spec-decode at all (the 20→28 t/s layer). **Fork stays
> mandatory** until the remaining prefill PRs land.

## Full local build — for testing improvements

Build the fork yourself when you want to try new commits, patches or flag tweaks
(the update script automates this). Straight from BUILD.md, simplified for this box:

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

## Test — verify GPU, not silent CPU fallback

The headline failure mode in BUILD.md: a Vulkan ICD manifest without `api_version`
gets skipped by the loader and llama.cpp **silently falls back to CPU** (~7x slower).
Not an issue with the system RADV, but always confirm the backend:

```bash
# backend must read GPU/Vulkan (AMD Radeon 8060S), not CPU
./build-vk/bin/llama-bench -m <model.gguf>

# or serve it:
./build-vk/bin/llama-server --host 127.0.0.1 --port 8080 -m <model.gguf> -ngl 99
```

## Baseline performance (Q5-era measurements — superseded by the config research)

> **Read the numbers below as a floor, not a ceiling.** They were taken on 2026-08-20
> with the box under day-long load churn (zram-swapped weight pages — see
> [Lessons learned](#lessons-learned)). On a quiet box the same stack reaches
> **~223 GB/s effective** (Q6: pp512 **345.8**, tg32 **8.58**; Q8: pp512 **365.7**,
> tg32 **7.28**, f16 KV) — i.e. the Q5-era tg32 of 6.7 was ~60% of achievable.
> Current recommended configs: [per-goal table](#recommended-configs-per-goal).

Qwen3.8-27B-UD-Q5_K_XL (18.8 GiB), Vulkan backend confirmed, `AMD_VULKAN_ICD=RADV`:

| Workload | t/s | Notes |
|---|---:|---|
| pp512 prefill | **249.8** | `-fa on -ctk/ctv q8_0 -ub 2048`; healthy — beats issue #86's ported 215 t/s @d32k (70 W box) |
| pp512 @ d8192 | 228.6 | depth costs ~8% — normal head-dim effect |
| pp512 @ d32k | 190.8 | deep prefill, q8_0 KV, `-ub 4096` |
| pp512 @ d64k | 146.0 | deep prefill, q8_0 KV, `-ub 4096` |
| pp512 @ ≥128k | **crash** | `vk::DeviceLostError` at d131072 — same crash class issue #86 hit on stock builds (there f16 KV @64k); 64k is the measured working ceiling for prefill on this Vulkan stack |
| tg32 decode, no draft | **6.7** | bandwidth-bound (drift-era floor; quiet-box Q6 reaches 8.6, Q8 7.3); even at ~223 GB/s effective, ~31 t/s *without* a draft remains impossible for a 27B dense-weight stream |
| tg with DFlash2 draft (n-max 4) | 14.5–15.5 | Q4_K_M draft ≥ Q8_0 draft (15.4 vs 14.55); n-max 16 ≈ n-max 4 (block_size 8 caps it) |
| tg, full server config (Q5-era settings) | **16.8** | adds `-ub 4096` — the +5% the author measured on Q4/Q5 targets |

**The Reddit "31 t/s" headline is a burst/best-case number, not steady state.** The
thread itself reports 16–23 t/s interactive (Q8 target, draft 4) and describes
21.6→30 t/s as the *burst* of the MTP→DFlash2 bump at Q5. This box at 16.8 t/s is
in-band, not at 50% — the remaining gap is measurement methodology plus the author's
sustained power envelope (this one holds a flat 85 W).

### llama-bench with the server's flags (reproducible verification)

`llama-bench` takes most of `run_llama-server.sh`'s tunables — but **not** `-md`/
`--spec-*` (no draft support: it measures bare decode only), nor `-ctkd/-ctvd`,
`-tb`, `-c`/`-np`. The transferable set, with the `-ub` A/B folded in:

```bash
./build-vk/bin/llama-bench -m ../Qwen3.8-27B-UD-Q6_K_XL.gguf \
  -ngl 99 -fa on -t 16 -b 4096 -ub 4096 -p 512 -n 32 -d 0,8192 -r 1
```

OBSERVED quiet-box, f16 KV, build `7b6c61330`: Q6 pp512 **345.8** / pp512@d8192
**315.2** / tg32 **8.58**; Q8 pp512 **365.7** / d8192 **327.7** / tg32 **7.28**.
(Earlier Q5-era runs at q8_0 KV measured 220–250 pp / 6.7 tg under load churn — the
difference is box state, not KV type.) Shallow pp512 still varies ±10% run-to-run
at 85 W.

> The `DFlash2` GGUFs are **draft models** (1.9B, `dflash` arch): running one standalone
> fails with `dflash requires ctx_other to be set` — they only load via `-md` next to a
> target model.

## Running it: speculative decoding

Use the unified launcher — presets from the [per-goal table](#recommended-configs-per-goal),
any field overridable:

```bash
./run_llama-server.sh --goal balanced-speed            # Q6 @ 64k — daily driver
./run_llama-server.sh --goal max-quality               # Q8 @ 192k — final answers
./run_llama-server.sh --goal max-speed --ctx 32768     # trimmed ctx for pure t/s
./run_llama-server.sh --model q8 --kv q8_0 --nmax 4   # fully custom
```

All presets: DFlash2-Q8_0 draft, **f16 KV**, n-max 6, `-b/-ub 4096`, `-t 16 -tb 32`,
`-lm mmap+mlock` (zram-immune weights; needs the memlock limit raised — see
[Lessons learned](#lessons-learned)), sharp.jinja template, metrics on.
Live-verified: bare `balanced-speed` on a quiet box → **27.7 t/s**.

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
config under `results/`):

```bash
./sweep_llama_configs.sh 0                                # capacity probe (done, below)
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

### Findings on this gfx1151 (full sweep, 2026-08-20)

**Methodology lesson first:** absolute t/s drifts ±25% across the day — GTT weight
pages are shmem-backed and land in **zram** under memory churn, and decode then pays
per-token decompression. All rankings below come from back-to-back (interleaved)
runs inside tight windows; fresh-load peaks: **Q6 28.6 / Q8 24.7 t/s**. For an
inference box: keep it quiet, or disable swap (`swapoff -a` / mask the zram unit).

| Axis | Winner | Evidence (back-to-back pairs) |
|---|---|---|
| KV types (target × draft) | **f16 / f16, both models** | Q6: 20.8 vs 19.2 (q8/q8); Q8: 16.6 vs 15.6 — with 128 GB unified, quality KV is also the faster choice here |
| `--spec-draft-n-max` | **6** (6–7 plateau; 4 clearly worse) | Q6: n6 28.6 > n5 27.4 > n4 24.8 (fresh window); n7 ≈ n6 elsewhere |
| `-c` (allocated ctx) | **65536 default; allocation is free up to 256k** | Quiet-box re-measure (2026-08-21, fresh boot, zram 0 B used, two passes + an order-controlled third): **flat** — Q6 20.2 ±0.2 t/s and Q8 ~17.6 t/s from 64k straight through 256k. The earlier "ALLOCATED ctx costs decode" decay (Q6 19.8→16.7, Q8 17.8→13.9) was drift-era zram noise and does **not** reproduce. Only real quirk: Q8 dips ~1.4 t/s at 64k vs ≥128k (confirmed not a run-order artifact; mechanism unknown). The ≥128k crash is deep-prefill-specific (bench filling the ctx), not an allocation limit |
| `-b/-ub` | **4096** | tg flat (±2%, 2048/4096/8192); llama-bench already showed 4096 = +6% deep prefill over 2048; 8192 doubles compute buffers for nothing |
| `-tb` | **32** (parity) | tb16 within ~1% of tb32 — GPU-bound, as expected |

### Recommended configs (per goal)

All presets: DFlash2-Q8_0 draft, f16 KV, n-max 6, `-b/-ub 4096`, `-t 16 -tb 32`,
`-lm mmap+mlock`. tg = typical sustained; **fresh quiet box peaks ≈ +50%**.
RAM columns (measured 2026-08-21, 124 GiB box, recipe resident via the router,
sequentially, `--models-max 1`): **RAM** = resident footprint vs idle router
(weights + draft + KV + compute buffers; mlock'd, so it never swaps out),
**left** = `free` "available" with that recipe live — headroom for concurrent
models/activities. Run-to-run variance ±1–2 GiB.

| Goal | Router recipe (`models.ini`) | Command (`run_llama-server.sh …`) | `-c` | RAM | left | sustained tg (quiet box) | pp4k | When to pick |
|---|---|---|---|---:|---:|---:|---:|---|
| **Max quality** | `Qwen38-27B-Q8-192K-quality` | `--goal max-quality` (Q8) | 196608 (sane ceiling) | ~54 GiB | ~68 GiB | ~25 | ~365 | final answers, code, synthesis — quality over everything |
| **Balanced → quality** | `Qwen38-27B-Q8-65K-balanced-quality` | `--goal balanced-quality` (Q8) | 65536 (default) | ~45 GiB | ~78 GiB | ~25 | ~365 | default when correctness matters more than latency |
| **Balanced → speed** ✅ default | `Qwen38-27B-Q6-65K-balanced-speed` | `run_llama-server.sh` (Q6) | 65536 | ~40 GiB | ~83 GiB | **~28** | ~346 | daily driver — Q6 quality is good anyway; best sustained t/s measured |
| **Max speed** | `Qwen38-27B-Q6-65K-fast` | `--goal max-speed` (Q6) | 65536 (16k–256k flat on a quiet box; trim to the task) | ~40 GiB | ~83 GiB | **~28** | ~346 | interactive churn |
| **Fast churn** | `Qwen38-27B-Q5-65K-turbo` | `--model q5` (Q5) | 65536 | ~35 GiB | ~88 GiB | ~23 | — | fast throwaway prototyping |
| **Vision** | `Qwen38-27B-Q6-65K-vision` | router-only (mmproj, no spec) | 65536 | ~32 GiB | ~91 GiB | ~8.6 (no spec) | — | the only image-capable recipe — image tokens crash the dflash spec batch, so it runs `spec-type = none` (2026-08-21); lightest resident footprint (no draft model) |

Heads-up for concurrency: `--models-max 1` is policy, not a hard memory limit —
two small recipes would *fit* (e.g. turbo + fast ≈ 75 GiB), but three resident
models exhausted memory and hard-hung the box (2026-08-21), so 1 stays the
default; raise only with verified headroom.

Decision rule between them: **Q8 when quality is the point, Q6 when tokens/s is** —
prefill is equal (~250–260 pp4k), decode favors Q6 at every context size.

## Lessons learned

1. **Measure back-to-back or not at all.** Absolute t/s drifted ±25% during a day of
   stage sweeps; only interleaved pairs gave trustworthy rankings. The first
   stage-2 block was drift-corrupted and was re-run. Mind **run order** too: the
   first server after a cold start pays page-cache warm-up, so sequential ladders
   lean toward whatever ran last (a 16k/32k/64k ctx ladder inverted until we saw
   the bias). The 2026-08-21 ctx re-measure took it further: two full passes
   (identical results) plus one reversed-order pass to prove the lone anomaly
   (Q8's 64k dip) was real, not a first-in-sequence artifact.
2. **zram eats inference.** GTT weight pages are shmem-backed → swappable → they
   compress into zram under load churn, and decode then pays per-token
   decompression (up to ~30%). Fixes, best first: (a) `-lm mmap+mlock` so the
   weights can never be swapped (needs `memlock` unlimited — see below);
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
   ⚠️ **Observed 2026-08-21:** the server only *warns* on mlock ENOMEM and keeps
   serving **unprotected** — it does not abort. `/etc/security/limits.d/` didn't
   even exist on this box (the step above had never been applied), so every
   "mlock'd" run until then ran without actual protection. After re-login verify:
   `ulimit -l` must print `unlimited`.
4. **Power is a throttling detector, not a cost metric.** We logged PPT only to
   confirm the box held a flat 85 W (no throttle). A Strix Halo's max draw is more
   than an order of magnitude below a pre-Blackwell NVIDIA desktop part — the
   interesting wattage story is elsewhere.
5. **A clean box is part of the benchmark.** All tests ran on a "clean" Strix Halo
   with no other heavy processes sharing RAM/GTT/bandwidth. You don't need to
   dedicate the machine to inference — but if you want SOTA-at-home, privilege
   inference quality over co-located niceties (a SQL server, several heavy LLMs
   on the same box). One model, mlocked, on quiet unified memory.
6. **Trust but verify the fork's failure modes.** The `vk::DeviceLostError` ceiling
   (deep prefill ≥128k) and the one-off KV core dump were found by sweeping —
   neither appears in casual use. Allocation ≠ prefill: 256k ctx loads in 20 s.

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
  Q4–Q8_K_XL quantizations used as targets across these experiments
  ([pinned revision](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/408fcc1807ab)),
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
