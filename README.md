# Qwen3.8-27B on Strix Halo (Radeon 8060S / gfx1151)

Run Qwen3.8-27B with the [strix-halo llama.cpp](https://github.com/Nathanw1014/strix-halo-llamacpp)
fork on a Ryzen AI MAX+ 395, with DFlash2 speculative decoding. This repo holds the
launchers and notes; model weights (`.gguf`) and the `llama.cpp/` clone are local-only.

- `run_llama-server.sh` — verified server config (16.8 t/s gen with the DFlash2 draft)
- `update_strix-halo-llamacpp_vulkan.sh` — pull/rebuild the fork + backend check
- Benchmarks and the Reddit-"31 t/s" reality check below

> ## 🙏 Big thanks
>
> **[u/froggeric](https://www.reddit.com/user/froggeric)** — author of
> [*Fixed jinja chat template for Qwen 3.5/3.6 and the Qwen3.8 family*
> (r/LocalLLaMA)](https://www.reddit.com/r/LocalLLaMA/comments/1vnm7le/fixed_jinja_chat_template_for_qwen_35_36_and_the/).
> The `sharp.jinja` template shipped here is that work
> (`qwen3.8-froggeric-v22.1.1`) — it fixed the broken tool-call/thinking formatting
> that stock templates produce for this model family. Without it the server output
> above would be garbage with tools enabled.

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
| pp512 @ d32k | 190.82 | deep-context prefill, q8_0 KV, -ub 4096 |
| pp512 @ d64k | 146.02 | deep-context prefill, q8_0 KV, -ub 4096 |
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
- **[Unsloth](https://unsloth.ai/)** — the UD (Unsloth Dynamic) Q4/Q5_K_XL quantizations
  used as targets here, and the community's quant tooling.
- **The Qwen team (Alibaba)** — the Qwen 3.8 model family these configs run.
- **[u/froggeric](https://www.reddit.com/user/froggeric)** — again, for the chat
  template (see the top of this README).

## License

[MIT](LICENSE) © 2026 PieBru. The configs and notes here are MIT; the
[strix-halo llama.cpp fork](https://github.com/Nathanw1014/llama.cpp) and llama.cpp
itself remain under their own MIT license, and the model weights (not in this repo)
belong to their respective publishers.
