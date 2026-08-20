#!/bin/bash
# Qwen3.8-27B UD-Q5_K_XL + DFlash2 spec-decode server (strix-halo-vulkan fork, commit 7b6c613).
# Measured on this box (85 W PPT, RADV): ~14.5-15 t/s gen with the Q8_0 draft
# (the slightly faster Q4_K_M draft was deleted to make room for Q6/Q8 targets;
# Q6/Q8 targets reach 19.7/16.7 t/s with this same draft — see README config research).
# ~6.7 t/s without spec decode. Reddit "31 t/s" is the burst/best-case number.
export AMD_VULKAN_ICD=RADV

./llama.cpp/build-vk/bin/llama-server \
  -m Qwen3.8-27B-UD-Q5_K_XL.gguf \
  -md Qwen3.8-27B-DFlash2-Q8_0.gguf \
  -ngl all -ngld all -fa on \
  -ctk q8_0 -ctv q8_0 -ctkd q8_0 -ctvd q8_0 \
  -c 65536 -np 1 \
  -b 4096 -ub 4096 \
  -t 16 -tb 32 \
  --spec-type draft-dflash --spec-draft-n-max 4 \
  --chat-template-file sharp.jinja \
  --jinja --host 0.0.0.0 --port 8081 --metrics
