#!/bin/bash
# Qwen3.8-27B UD-Q8_K_XL + DFlash2 spec-decode — RECOMMENDED config from the
# config research (README "Config research"): f16 KV everywhere, n-max 6,
# b/ub 4096. Q8_K_XL streams ~29 GiB of weights per token: decode is lower
# than Q6 at every ctx, prefill is equal (~250-260 t/s pp4k) — choose Q8 when
# quality is the point (the repo motto), Q6 when tokens/s is.
# Context ladder (tg cost of ALLOCATED ctx): 64k ~17.8, 128k ~13.9,
# 192k ~14.3, 256k ~12.2 (works, costs more than Q6). Raise -c only as needed.
# Keep the box quiet: zram-swapped weight pages cost up to ~30% decode.
export AMD_VULKAN_ICD=RADV

./llama.cpp/build-vk/bin/llama-server \
  -m Qwen3.8-27B-UD-Q8_K_XL.gguf \
  -md Qwen3.8-27B-DFlash2-Q8_0.gguf \
  -ngl all -ngld all -fa on \
  -c 65536 -np 1 \
  -b 4096 -ub 4096 \
  -t 16 -tb 32 \
  --spec-type draft-dflash --spec-draft-n-max 6 \
  --chat-template-file sharp.jinja \
  --jinja --host 0.0.0.0 --port 8083 --metrics
