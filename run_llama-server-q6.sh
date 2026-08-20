#!/bin/bash
# Qwen3.8-27B UD-Q6_K_XL + DFlash2 spec-decode — RECOMMENDED config from the
# config research (README "Config research"): f16 KV everywhere (RAM is not
# scarce on 128GB unified; f16 beat q8_0 KV by 6-8% on decode), n-max 6
# (6-7 plateau, 4 clearly worse), b/ub 4096 (deep-prefill sweet spot).
# Context ladder (tg cost of ALLOCATED ctx, idle prompts): 64k ~20 t/s,
# 128k ~16.7, 192k ~15.6, 256k ~16.8 — all load fine (SSM state is tiny);
# raise -c only when you need it. Weights are mlocked (`-lm mmap+mlock`) so zram
# can never swap them out — better than disabling swap system-wide (see README
# lessons).
ulimit -l unlimited 2>/dev/null || true  # enables multi-GB mlock once limits.d allows (README lessons)
export AMD_VULKAN_ICD=RADV

./llama.cpp/build-vk/bin/llama-server \
  -m Qwen3.8-27B-UD-Q6_K_XL.gguf \
  -md Qwen3.8-27B-DFlash2-Q8_0.gguf \
  -ngl all -ngld all -fa on -lm mmap+mlock \
  -c 65536 -np 1 \
  -b 4096 -ub 4096 \
  -t 16 -tb 32 \
  --spec-type draft-dflash --spec-draft-n-max 6 \
  --chat-template-file sharp.jinja \
  --jinja --host 0.0.0.0 --port 8082 --metrics
