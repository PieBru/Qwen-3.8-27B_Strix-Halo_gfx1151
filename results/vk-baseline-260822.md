ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = AMD Radeon 8060S Graphics (RADV STRIX_HALO) (radv) | uma: 1 | fp16: dot2 | bf16: 0 | fp4: 0 | warp size: 64 | shared memory: 65536 | int dot: 1 | matrix cores: KHR_coopmat
| model                          |       size |     params | backend    | ngl | n_batch | n_ubatch |  fa |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | ------: | -------: | --: | --------------: | -------------------: |
| qwen35 27B Q6_K                |  23.55 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |           pp512 |        360.59 ± 0.23 |
| qwen35 27B Q6_K                |  23.55 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |            tg32 |          8.78 ± 0.01 |
| qwen35 27B Q6_K                |  23.55 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |   pp512 @ d8192 |        316.58 ± 0.00 |
| qwen35 27B Q6_K                |  23.55 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |    tg32 @ d8192 |          8.59 ± 0.00 |

build: 9b9ac3e38 (10570)
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = AMD Radeon 8060S Graphics (RADV STRIX_HALO) (radv) | uma: 1 | fp16: dot2 | bf16: 0 | fp4: 0 | warp size: 64 | shared memory: 65536 | int dot: 1 | matrix cores: KHR_coopmat
| model                          |       size |     params | backend    | ngl | n_batch | n_ubatch |  fa |            test |                  t/s |
| ------------------------------ | ---------: | ---------: | ---------- | --: | ------: | -------: | --: | --------------: | -------------------: |
| qwen35 27B Q4_K - Medium       |  29.29 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |           pp512 |        365.04 ± 9.82 |
| qwen35 27B Q4_K - Medium       |  29.29 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |            tg32 |          7.27 ± 0.00 |
| qwen35 27B Q4_K - Medium       |  29.29 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |   pp512 @ d8192 |        326.92 ± 0.14 |
| qwen35 27B Q4_K - Medium       |  29.29 GiB |    27.32 B | Vulkan     |  99 |    4096 |     4096 |   1 |    tg32 @ d8192 |          7.14 ± 0.00 |

build: 9b9ac3e38 (10570)
