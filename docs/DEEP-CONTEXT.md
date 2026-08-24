# Deep context & unattended stability

> From [Qwen3.8-27B on Strix Halo](../README.md) — the 256k/1M window story, the amdgpu watchdog wall, and the lockup_timeout=-1 playbook.

## The 1M-token context: what works, what doesn't, and what it costs

Qwen3.8-27B's 1M-token window is a headline feature — here is everything this
repo measured about it on a Strix Halo (gfx1151) box, in one place.

**The promise.** The model card declares 262,144 native context, "extensible
up to 1,000,000 tokens" via YaRN (factor 4.0 from the 262,144 training ctx),
and the publisher's long-horizon guidance budgets 262k reasoning + 131k output
*inside* the 1M window. Important framing: positions beyond 262k are
YaRN-extrapolated, not trained — endorsed by the publisher, but expect gradual
quality decay as you climb past 256k, on every server.

**What this stack serves today: `quality@256k` at 262,144.** That number is the
model's `n_ctx_train`, and llama-server caps every slot to it — a cap inherited
from **mainline llama.cpp itself** (identical code verified in a stock clone),
with no YaRN exemption. We load-tested a full 1M recipe
(`rope-scaling = yarn`, `rope-scale = 4`, `yarn-orig-ctx = 262144`,
`c = 1048576`): the KV allocated fine, then the journal printed the cap warning
and the usable slot came back at 262,144 — full memory cost, zero extra window.
The same test showed there is **no 512K middle ground**: the cap applies to any
`c` above 262,144, so 512K would pay ~18 GiB more KV than 256k and still serve
a capped slot. Separately, on a **default kernel** even inside a 262k window, content
beyond ~137k positions dies at the amdgpu lockup watchdog (Vulkan reports
it as `vk::DeviceLostError`; absolute-position, not per-batch — chunked
fills crash at the same depth). `amdgpu.lockup_timeout=-1` removes the
wall entirely — the same battery filled all 254,356 usable positions, zero
errors (2026-08-23 intervention; the ROCm build survives the band on the
default kernel by submission shape — next subsection). Big windows are for
many medium contexts, or one giant prompt if you accept the prefill/decode
time at depth.

### Deep positions: the amdgpu watchdog wall — and how to remove it

A/B measured 2026-08-22 on the same box, same fork commit (`9b9ac3e38`),
same battery (`fill_battery.sh`: Q8 target + DFlash2 draft, f16 KV,
`-c 262144 -b/-ub 4096`, incremental 16k-token fills via cached prefixes):

| Backend | bare bench (Q6 / Q8) | fill fate |
|---|---|---|
| Vulkan (production build, `9b9ac3e38`) | pp512 360.6 / 365.0 · tg32 8.78 / 7.27 | **default kernel:** 💥 dies at **136,965** filled (`vk::Queue::submit: ErrorDeviceLost` ← amdgpu ring watchdog) · **`lockup_timeout=-1`:** ✅ full window, **254,356**, zero errors — *same binary, only the kernel param differs* |
| ROCm — TheRock 7.15.0a nightly | pp512 352.5 / 370.8 · tg32 8.57 / 7.18 | **default kernel:** ✅ survived **215,228** filled, zero errors (no boot param needed) |

Reading it straight:

- **The ~128k+ wall is the amdgpu lockup watchdog, full stop (causation, not
  correlation).** Kernel forensics (2026-08-23, full detail in the
  Vulkan-vs-ROCm chapter below) show every "device lost" that morning was an
  **amdgpu compute-ring lockup timeout + ring reset** fired on llama-server's
  own submission, seconds before the userspace error — and the intervention
  sealed it: `lockup_timeout=-1`, same battery, same binary → the entire
  window, zero ring events. Same weights, same flags, same commit — only the
  backend differs on the default kernel because the backends shape GPU
  submissions differently (ROCm's keep signaling; see below).
- **Vulkan is the faster deep-prefiller at every depth** — not just while it
  lives: with the watchdog off it holds the lead through the whole window
  (177→144→119 t/s at 78k→98k→117k filled vs ROCm's 72→55→44 in the same band;
  at 156k filled it's 86 vs 32 t/s; ROCm decays faster with depth throughout,
  262 t/s at 20k → 22 at 215k).
- **DFlash2 works on ROCm**: draft acceptance 0.34 on a matched probe; decode
  14.5 t/s vs Vulkan's 16.9 t/s (Q6@128k) — Vulkan ~17% ahead with spec decode.
- Upstream status (2026-08-23): the Vulkan device-lost class is still open
  upstream ([#27076](https://github.com/ggml-org/llama.cpp/issues/27076),
  [#27458](https://github.com/ggml-org/llama.cpp/issues/27458)); we also
  filed [#27588](https://github.com/ggml-org/llama.cpp/issues/27588) —
  trailing `assistant(tool_calls)` silently drops the calls in the
  auto-prefill/continuation path (found by the T0.4 template probes,
  reproduced on stock master `2115b73`); the fork's
  [issue #9](https://github.com/Nathanw1014/strix-halo-llamacpp/issues/9)
  shows a 491,520-token prefill *succeeding* on Vulkan with DeepSeek-V4 +
  q8_0 KV + `-ub 1024` — consistent with the watchdog mechanism: those knobs
  reshape dispatches, moving the timeout threshold rather than removing the
  wall (`lockup_timeout` removes it).

**To try the ROCm build yourself** (no root needed; userspace-only, sits
beside the Vulkan one):

```bash
# TheRock nightly for gfx1151 (fixed line — the 7.14.0a20260609..0612 wheels
# segfault in hsa_init on gfx1151; see TheRock issue #5763)
curl -O https://rocm.nightlies.amd.com/tarball-multi-arch/therock-dist-linux-gfx1151-7.15.0a20260728.tar.gz
mkdir -p ~/opt/rocm-7.15 && tar -xzf therock-dist-linux-gfx1151-*.tar.gz -C ~/opt/rocm-7.15
export ROCM_PATH=~/opt/rocm-7.15 PATH=$HOME/opt/rocm-7.15/bin:$PATH LD_LIBRARY_PATH=$HOME/opt/rocm-7.15/lib
cmake -B build-hip -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151 -DCMAKE_BUILD_TYPE=Release \
      -DGGML_NATIVE=ON -DLLAMA_CURL=OFF \
      -DCMAKE_C_COMPILER=$ROCM_PATH/bin/hipcc -DCMAKE_CXX_COMPILER=$ROCM_PATH/bin/hipcc
cmake --build build-hip --target llama-server llama-bench -j
# then run any recipe with build-hip/bin/llama-server instead of build-vk —
# and ./scripts/fill_battery.sh <label> ./llama.cpp/build-hip/bin/llama-server to
# reproduce the deep-fill A/B
```

For official-release ROCm (7.2.4 era), expect the "way slower than Vulkan"
reports to hold — upstream tracks the gfx1151 gaps
([#21284](https://github.com/ggml-org/llama.cpp/issues/21284),
[#24437](https://github.com/ggml-org/llama.cpp/issues/24437)); the 7.14+/TheRock
line is where parity arrives. **Deep-context escape hatch, in order:
(1) `amdgpu.lockup_timeout=-1`** — one kernel-cmdline parameter, verified
here to unlock the full window with Vulkan's speed intact (fastest prefill
at every depth); pair it with the
[stability playbook](#stability-without-the-kernel-gpu-watchdog-lockup_timeout-1-playbook).
**(2) The ROCm build** — no kernel change needed, survives the band on the
default kernel, at 1.25–2.7× slower prefill: the fallback for boxes where
boot params are off-limits.

**What 1M costs in memory** (Q6 targets; f16 measured on a real 1M load, the
rest derived from GTT deltas at 110k ctx scaled linearly — the derivation
reproduces the f16 measurement within ~3%):

| KV type | GTT at 1M ctx | verdict on this 124 GiB box |
|---|---:|---|
| f16 | ~104 GiB (measured 100.9; RAM avail 14.3 GiB) | cliff edge — barely |
| q8_0 | ~72 GiB | comfortable ✅ |
| q5_1 | ~63 GiB | comfortable |
| q4_1 / q4_0 | ~57 / ~56 GiB | comfortable |

A Q8 target adds ~7 GiB (q8_0 ≈ 80 — fits; f16 does not). Is quantized KV safe
at long range? Yes: the NIAH battery ([findings](BENCHMARKS.md#sweep-findings-at-a-glance))
retrieved **40/40 needles from f16 down to q4_0 at up to 96k ctx** — KV
quantization does not break positional retrieval on this stack. That is why
the parked 1M recipe pins q8_0.

**How to actually get 1M today:**

1. **vLLM on this very APU** — officially supported: vLLM's install docs list
   `Ryzen AI MAX / AI 300 Series (gfx1151/1150)` (ROCm 7.0.2+), and vLLM serves
   YaRN with PagedAttention. Costs: no GGUF support (separate HF/AWQ weights,
   new fingerprints), DFlash2 spec decode is llama.cpp-only (the model's trained
   MTP head may recover speed via vLLM's own spec paths — unverified), and the
   memory budget above still applies.
2. **A local cap-exemption patch** — we build the fork from source; skipping
   the clamp when YaRN is active is a few lines and would make the parked
   `Q6-1M-yarn` recipe live (single prompts still capped ~128k by the prefill
   ceiling; the *window* would work).
3. **Wait for upstream** — a llama.cpp PR exempting YaRN from the slot cap,
   plus the deep-prefill fix. Note the fork→mainline merge does **not** lift
   the cap (mainline has the same code); detection after any rebuild is a
   5-second journal grep: load the parked recipe and check that the
   `exceeds the training context - capping` warning is absent and
   `n_ctx_slot = 1048576`.

Everything needed for the day it unlocks is parked and ready at the bottom of
`models/models.ini`: the full 1M recipe (q8_0 KV — NIAH-validated), the RAM budget
above, and the two blockers documented inline.


## Quality at depth — passkey recall through the full window (2026-08-24)

Survival and speed at depth were measured (e4); quality was not — until
this ladder. `llama-passkey` (fork example, greedy, Q8, seed 42,
`-fa on`), needle hidden in junk, model asked to recall it:

| Filled context | Needle position | Recall |
|---:|---:|---|
| 147,617 | mid (~74k) | ✅ found |
| 196,793 | mid (~98k) | ✅ found |
| 245,969 | mid (~123k) | ✅ found |
| 245,969 | **near-end (~221k)** | ✅ **"The pass key is 39384."** |

Under `amdgpu.lockup_timeout=-1` the model doesn't just *survive* the
unlocked window — it **remembers across all of it**, including a needle
221k tokens deep. Combined with e4's fill-decay curve, the deep-context
story is now complete: survival ✓, speed-at-depth ✓ (49 t/s prefill at
254k), and recall ✓. Logs: `results/passkey-*.log`.

## Stability without the kernel GPU watchdog (lockup_timeout=-1 playbook)

Running with `amdgpu.lockup_timeout=-1` buys the full 256k Vulkan window
(above) at a price: **the kernel will never report a GPU hang again**. A
true wedge then means a box that looks alive but never computes. This
chapter is the unattended-stability stack that makes `-1` safe on an
inference appliance — three layers, each catching what the others can't:

1. **Hardware watchdog (already there — verify, don't build).** The board's
   SP5100 TCO timer is petted by systemd (`RuntimeWatchdogUSec=20s`,
   `RebootWatchdogUSec=10min` — OBSERVED on this box via `systemctl show`).
   Catches full-system hangs: if PID 1 stops petting, the firmware reboots
   the box in 20 s. No action needed beyond checking it's on.
2. **GPU canary (the new layer — `gpu_canary.py` + `systemd-units/gpu-canary.{service,timer}`).**
   The gap the TCO can't cover: *kernel alive, GPU ring wedged* — systemd
   keeps petting, HTTP health stays green, every inference hangs forever
   (exactly the 2026-08-22 wedges, which `-1` now silences instead of
   recovering). The canary probes every 10 min: **health green + a 1-token
   completion dead = the wedge signature**. Two consecutive dead probes →
   journal entry + reboot. Router inactive → planned offline, skip (batteries
   don't trip it); health down → service restart only (not a GPU verdict).
3. **Unattended reboot grant.** `/etc/sudoers.d/gpu-canary-reboot`:
   `piero ALL=(root) NOPASSWD: /usr/bin/systemctl reboot` — exact-argv
   scoped (one command, no arguments), so the canary can act while the
   console is locked. Remove the file to revoke.

Replication on another box: append `amdgpu.lockup_timeout=-1` to the boot
entry (systemd-boot: `/boot/loader/entries/*.conf` — keep a `.bak`), copy
the two units to `~/.config/systemd/user/`, `daemon-reload`, `enable --now
gpu-canary.timer`, drop the sudoers file. Undo is the reverse of every
step (boot-entry restore is the only reboot-requiring one). The softer
alternative — `lockup_timeout=600000` (10 min, keeps kernel recovery) — is
untested here; it's on the ledger as the desktop-friendly variant.

Why this shape: under `-1`, wedge *detection* must move to userspace (the
kernel has contractually given up reporting it), while wedge *recovery*
was always the firmware's job (TCO) — the canary just connects the two.

