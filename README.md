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
# 4. verify backend + bare perf (expect: Vulkan0 AMD 8060S; pp512 220-256; tg32 ~6.7)
./build-vk/bin/llama-cli --list-devices
./build-vk/bin/llama-bench -m MODEL-UD-Q5_K_XL.gguf -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -t 16 -b 4096 -ub 4096 -p 512 -n 32 -d 0,8192 -r 2
# 5. verify spec-decode (expect ~15 t/s Q5 / ~20 t/s Q6 with the DFlash2 draft)
./run_llama-server.sh   # then: curl localhost:8081/completion ..."n_predict":256
```

Numbers are for an 85 W sustained PPT box; expect ±10% run-to-run. Deep prefill
**crashes ≥128k ctx** (`vk::DeviceLostError`) on this stack — 64k is the ceiling.

Run Qwen3.8-27B with the [strix-halo llama.cpp](https://github.com/Nathanw1014/strix-halo-llamacpp)
fork on a Ryzen AI MAX+ 395, with DFlash2 speculative decoding. This repo holds the
launchers and notes; model weights (`.gguf`) and the `llama.cpp/` clone are local-only.

- `run_llama-server.sh` — verified server config (Q5 target, DFlash2-Q8_0 draft, ~15 t/s gen)
- `update_strix-halo-llamacpp_vulkan.sh` — pull/rebuild the fork + backend check
- `sweep_llama_configs.sh` — staged config search for the sweet spots ([config research](#config-research-sweep_llama_configssh))
- Benchmarks and the Reddit-"31 t/s" reality check below

## Environment (read this first)

Everything below was verified on **Arch Linux installed as a minimal headless
server** — no desktop environment, GPU used purely as a compute device.
**Ubuntu may work but we didn't test it**; the package names in the dependencies
section are Arch's, so translate them (`apt`/universe, possibly newer upstream
packages for shaderc/RADV) before assuming parity.

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

The target GGUFs benchmarked here are **Unsloth Dynamic 1.2 2-quant v2** (`UD-Q4_K_XL`,
`UD-Q5_K_XL`). ⚠️ The unsloth repo tip now carries **different files under the same
names** (re-quantized — different sizes and LFS hashes), so download the v2 set from
the pinned commit, not `main`:

**<https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/408fcc1807ab>**

| File (this repo's benchmarks) | Exact size (bytes) | sha256 starts with |
|---|---:|---|
| `Qwen3.8-27B-UD-Q5_K_XL.gguf` | 20,218,178,624 | `176a6a3f034e` |
| `Qwen3.8-27B-UD-Q4_K_XL.gguf` | 17,923,394,624 | `bee238bbeb3d` |

Verify a download against the table (`ls -l` size, or `sha256sum` prefix) — a
same-named file of a different size is the newer revision, not the one measured here.
The `DFlash2-*` draft GGUFs come from elsewhere (not in that repo) and are loaded via
`-md`, never standalone.

Local set at the time of the config research: `UD-Q5/Q6/Q8_K_XL` targets,
`DFlash2-Q8_0` draft (the slightly faster `DFlash2-Q4_K_M` and the `UD-Q4_K_XL`
were removed to make room; all remain fetchable from the pinned commit above).
A stray `mmproj-F16.gguf` (vision projector) is unused by these configs.

## Quick Start: just run the prebuilt release (time-saving)

Skip the build entirely — the toolbox releases ship a portable, self-contained stack
(latest `v0.6.6`, `strix-halo-llamacpp-vulkan-portable.tar.gz`) that bundles its own
RADV + libdrm, so it won't touch the system driver and needs no compile toolchain:

```bash
curl -L https://github.com/Nathanw1014/strix-halo-llamacpp/releases/download/v0.6.6/strix-halo-llamacpp-vulkan-portable.tar.gz | tar xz
# point run_llama-server.sh at the extracted binary instead of the local build:
#   ./vulkan/llama-server -m <MODEL.gguf> -ngl 99 -fa 1 --host 0.0.0.0
```

**Verified on this box**: same llama.cpp commit as the local build (`7b6c613`),
Vulkan backend confirmed, tg8 = 7.55 t/s on Q5_K_XL. Read on only if you want to
build from source to test improvements.

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

## Realistic performance on this box (measured 2026-08-20, flat 85 W PPT)

Qwen3.8-27B-UD-Q5_K_XL (18.8 GiB), Vulkan backend confirmed, `AMD_VULKAN_ICD=RADV`:

| Workload | t/s | Notes |
|---|---:|---|
| pp512 prefill | **249.8** | `-fa on -ctk/ctv q8_0 -ub 2048`; healthy — beats issue #86's ported 215 t/s @d32k (70 W box) |
| pp512 @ d8192 | 228.6 | depth costs ~8% — normal head-dim effect |
| pp512 @ d32k | 190.8 | deep prefill, q8_0 KV, `-ub 4096` |
| pp512 @ d64k | 146.0 | deep prefill, q8_0 KV, `-ub 4096` |
| pp512 @ ≥128k | **crash** | `vk::DeviceLostError` at d131072 — same crash class issue #86 hit on stock builds (there f16 KV @64k); 64k is the measured working ceiling for prefill on this Vulkan stack |
| tg32 decode, no draft | **6.7** | bandwidth-bound: 18.8 GiB of weights per token ≈ 130 GB/s effective; ~31 t/s *without* a draft is physically impossible on Strix Halo |
| tg with DFlash2 draft (n-max 4) | 14.5–15.5 | Q4_K_M draft ≥ Q8_0 draft (15.4 vs 14.55); n-max 16 ≈ n-max 4 (block_size 8 caps it) |
| tg, full `run_llama-server.sh` config | **16.8** | adds `-ub 4096` — the +5% the author measured on Q4/Q5 targets |

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
./build-vk/bin/llama-bench -m ../Qwen3.8-27B-UD-Q5_K_XL.gguf \
  -ngl 99 -fa on -ctk q8_0 -ctv q8_0 -t 16 -b 4096 -ub 2048,4096 \
  -p 512 -n 32 -d 0,8192 -r 2
```

OBSERVED (build `7b6c61330`): pp512 220.9→225.3 and pp512@d8192 203.9→**216.2**
going ub 2048→4096 (**+6% deep prefill** — matches the author's ~5%-on-Q4/Q5 claim);
tg32 6.68/6.69 and tg32@d8192 6.36/6.35 (flat — decode is bandwidth-bound, only the
draft moves it). Shallow pp512 varies 220–250 across sessions; treat ~±10% as run-to-run
noise at 85 W.

> The `DFlash2` GGUFs are **draft models** (1.9B, `dflash` arch): running one standalone
> fails with `dflash requires ctx_other to be set` — they only load via `-md` next to a
> target model.

## Running it: speculative decoding

Use `run_llama-server.sh` in this directory — Q5_K_XL target + DFlash2 Q4_K_M draft,
q8_0 KV, 64k context, `--spec-type draft-dflash --spec-draft-n-max 4`, sharp.jinja
template, metrics on. Verified end-to-end: 16.8 t/s generation.

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
./sweep_llama_configs.sh 3 "Q6 q8_0 q8_0 <n6>" "Q8 q8_0 q8_0 <n8>"   # ctx 128k/192k/256k
./sweep_llama_configs.sh 4 "Q6 q8_0 q8_0 <n6> <ctx>" ... # -b/-ub 2048/4096/8192
./sweep_llama_configs.sh 5 ...                            # -tb 16 vs 32
```

Guards built in: per-server wait ceiling, fail-fast on dead loads, process-group
cleanup (no orphans), crash-tolerant CSV (status column).

### Findings so far on this gfx1151 (Stage 0, 2026-08-20)

| Finding | Evidence |
|---|---|
| **Qwen3.8 is a hybrid SSM — context is nearly free** | `qwen35.ssm.*` in the GGUF; RSS-delta 8k→64k ctx ≈ **48 B/token** (Q6): 256k ctx would add ~0.01–0.3 GiB. Pick `-c` for the 64k crash ceiling, not memory |
| **Q6 / Q8 targets reach 19.7 / 16.7 t/s with the Q8_0 draft** (baseline config: q8_0 KV, c=8192, ub 4096, n-max 4) | no draft A/B was run on these targets — on Q5 the deleted `DFlash2-Q4_K_M` draft measured ~+5% *faster* (15.4 vs 14.55), so draft choice is target-dependent |
| **Warm server loads are 6–12 s** — the earlier "dozen seconds vs minutes" gap was cold page cache + the orphaned-server memory pressure, not the build | timing column in `results/sweep.csv` |
| Draft-model KV is ~free (1.9B SSM) | `Vulkan0 model buffer size = 1950.71 MiB` (draft) vs 23328.84 MiB (Q6 target) |

Stages 1–5 not yet run on this box; the harness is ready and the commands above
are the exact next steps.

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
- **[llama.cpp](https://github.com/ggml-org/llama.cpp) / ggml** — the whole enterprise:
  the upstream project and its maintainer team and community.
- **[Mesa / RADV](https://www.mesa3d.org/) and the [AMD ROCm](https://rocm.docs.amd.com/)
  teams** — the open Vulkan and compute stacks that make gfx1151 a first-class
  citizen, and the driver-level compute work this fork's kernels assume.
- **[Unsloth](https://unsloth.ai/)** — the UD (Unsloth Dynamic 1.2 2-quant v2)
  Q4/Q5_K_XL quantizations used as targets here ([pinned revision](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/408fcc1807ab)),
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
