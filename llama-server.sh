#!/bin/bash
# Qwen3.8-27B UD-Q5_K_XL + DFlash2 spec-decode server (strix-halo-vulkan fork, commit 7b6c613).
# Measured on this box (85 W PPT, RADV): ~15.4 t/s gen with this draft config,
# ~6.7 t/s without spec decode. Reddit "31 t/s" is the burst/best-case number;
# the thread's own steady-state reports are 16-23 t/s (Q8 target) and ~21.6 at Q5.
export AMD_VULKAN_ICD=RADV

./llama.cpp/build-vk/bin/llama-server \
  -m Qwen3.8-27B-UD-Q5_K_XL.gguf \
  -md Qwen3.8-27B-DFlash2-Q4_K_M.gguf \
  -ngl all -ngld all -fa on \
  -ctk q8_0 -ctv q8_0 -ctkd q8_0 -ctvd q8_0 \
  -c 65536 -np 1 \
  -b 4096 -ub 4096 \
  -t 16 -tb 32 \
  --spec-type draft-dflash --spec-draft-n-max 4 \
  --chat-template-file sharp.jinja \
  --jinja --host 0.0.0.0 --port 8081 --metrics
