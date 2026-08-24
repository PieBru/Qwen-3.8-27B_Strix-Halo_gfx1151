# Models, environment & builds

> From [Qwen3.8-27B on Strix Halo](../README.md) — which GGUFs and why, quant evaluations, dependencies, building the fork and toolbox.

## Models — Unsloth Dynamic GGUFs, aligned with the repo tip

The target GGUFs are the Unsloth Dynamic **K_XL** quants, aligned with the
unsloth repo **tip** (v3.0 re-quant run) as of 2026-08-21. A full tie-battery
(fresh-slot decode, prefill, perplexity, KL-vs-Q8) showed the tip K_XL files
tie the previous pinned v2 set within noise on every axis, so we track the tip;
the v2 files were verified equivalent and then removed locally (their
fingerprints remain in git history for refetching). `Q8_K_XL` was byte-identical
between the two revisions.

**<https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/main>**

First-timers: `./scripts/download_models.sh` fetches all three (or pass `q5 q6 q8`),
verifies each sha256, and warns if the repo tip has drifted from the
fingerprints below; `./scripts/download_models.sh --check` re-verifies what's on disk.

| File | Role | Exact size (bytes) | sha256 starts with |
|---|---|---:|---|
| `models/Qwen3.8-27B-UD-Q8_K_XL.gguf` | quality recipes | 31,457,991,680 | `af36ecb6b5db` |
| `models/Qwen3.8-27B-UD-Q6_K_XL.gguf` | speed recipes + vision | 25,299,061,664 | `701d8fa9ed21` |
| `models/Qwen3.8-27B-UD-Q5_K_XL.gguf` | turbo recipe | 20,876,938,144 | `8601193d3d57` |

`UD-Q4_K_XL` is deliberately absent: evaluated and dropped — the measured case
against it is below.

Verify a download against the table (`ls -l` size, or `sha256sum` prefix).

The `DFlash2-*` draft GGUFs live in
[z-lab/Qwen3.8-27B-DFlash2-GGUF](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2-GGUF)
(the `Q4_K_M` variant there measured ~+5% acceptance but needs re-fetching) and
only load via `-md` next to a target — run standalone they fail with
`dflash requires ctx_other to be set`. `models/mmproj-F16.gguf` is the vision projector
(unsloth repo, sha `cbb841a9ee06…`), wired per-recipe via the `mmproj` key in
`models/models.ini`. `download_models.sh` fetches and verifies all five files —
targets, draft, mmproj — against the fingerprints above.

### Context beyond 192k?

Everything 1M — the cap (mainline-inherited), the measured RAM budget, the
NIAH-validated quantized KV, the 512K verdict, and the vLLM/local-patch/
upstream routes to a real 1M window — lives in
[The 1M-token context](DEEP-CONTEXT.md#the-1m-token-context-what-works-what-doesnt-and-what-it-costs).

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
2.8 GiB of RAM or decode t/s matter more; to adopt it, add a `models/models.ini` section
pointing `model =` at the _M_ file (copy any Q6 section and edit).

### `UD-Q4_K_XL`: evaluated and dropped (2026-08-21) — GGUF deleted locally

The natural "warp speed" candidate (16.7 GiB weights, lightest possible target)
loses in practice: DFlash2 acceptance collapses with the extra quant noise
(0.41–0.59 vs 0.647 on Q5/Q6), so best-case decode is **28.2 t/s (n-max 4)** vs
Q5-turbo's **~23** — the bandwidth advantage is eaten by rejected drafts. Quality
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

