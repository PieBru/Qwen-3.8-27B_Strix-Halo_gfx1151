# Lessons learned

> From [Qwen3.8-27B on Strix Halo](../README.md) — the ten hard-won rules; the methodology in the wild.

## Lessons learned

1. **Measure back-to-back or not at all.** Absolute t/s drifts with box state; only
   interleaved pairs give trustworthy rankings. Mind **run order** too: the first
   server after a cold start pays page-cache warm-up, so sequential ladders lean
   toward whatever ran last. Reversed-order passes are how you catch both biases.
2. **zram eats inference.** GTT weight pages are shmem-backed → swappable → they
   compress into zram under load churn, and decode then pays per-token
   decompression (up to ~30%). Fixes, best first: (a) `-lm mmap+mlock` so the
   weights can never be swapped (needs `memlock` unlimited — see next);
   (b) tune the pressure that triggers swapping instead of disabling it:
   `vm.swappiness` (default 60 biases toward swapping anon pages; 1–10 makes zram
   a last resort) and `vm.watermark_scale_factor` (how early kswapd wakes);
   (c) `sudo swapoff -a` disables zram entirely until reboot — safe on 128 GB with
   the box otherwise quiet, but it removes the safety net and makes the kernel's
   precautional OOM killer trigger earlier under pressure. We prefer (a)+(b).

   The exact (b) we run on both boxes — `/etc/sysctl.d/99-llama-inference.conf`:
   `vm.swappiness = 10` (zram a last resort) and `vm.watermark_scale_factor = 125`
   (wake kswapd earlier — the install-time value of 10 gives a ~13 MiB wake gap
   on 124 GiB, i.e. almost never, which caused late direct-reclaim stalls; 125
   gives ~158 MiB of background-reclaim headroom). Apply with
   `sudo sysctl --system`; flush a filled zram without rebooting with
   `sudo swapoff /dev/zram0 && sudo systemctl restart
   systemd-zram-setup@zram0.service` (checked RAM headroom first). Monitor with
   `swapon --show` and `/sys/block/zram0/mm_stat` — the first column should stay
   near 0 during normal serving; anything growing means something swapped and
   decode is paying for it.
3. **mlock needs a limit raise — and fails SILENTLY without it.** Default
   `ulimit -l` here was 8192 KB (8 MB-class) and multi-GB buffers then fail with
   `Cannot allocate memory`. One-time, then re-login:
   `echo -e 'piero soft memlock unlimited\npiero hard memlock unlimited' | sudo tee /etc/security/limits.d/99-llama-mlock.conf`
   ⚠️ The server only *warns* on mlock ENOMEM and keeps serving **unprotected** —
   it does not abort. After re-login verify: `ulimit -l` must print `unlimited`.
4. **Power is a throttling detector, not a cost metric.** We log PPT only to
   confirm the box holds a flat 85 W (no throttle). A Strix Halo's max draw is more
   than an order of magnitude below a pre-Blackwell NVIDIA desktop part — the
   interesting wattage story is elsewhere.
5. **A clean box is part of the benchmark.** You don't need to dedicate the machine
   to inference — but if you want SOTA-at-home, privilege inference quality over
   co-located niceties (a SQL server, several heavy LLMs on the same box). One
   model, mlocked, on quiet unified memory.
6. **Trust but verify the fork's failure modes.** The `vk::DeviceLostError` ceiling
   (deep prefill ≥128k) and the one-off KV core dump were found by sweeping —
   neither appears in casual use. Allocation ≠ prefill: 256k ctx loads in 20 s.
   (The ceiling later root-caused to the amdgpu lockup watchdog — kernel
   forensics + `lockup_timeout=-1` intervention; see the Vulkan-vs-ROCm
   chapter. The lesson stands: sweep, don't trust.)
7. **Vision is cheap — until an image actually arrives.** Attaching `mmproj-F16`
   to a spec recipe costs almost nothing statically (+~1.2 GB GTT, +~0.6 s load;
   text decode neutral) and the recipe serves text at full speed — but the first
   real image request dies with `decode() failed: failed to process speculative
   batch`: image embeddings are incompatible with the DFlash2 spec path in this
   fork. Hence vision is its own `Qwen38-27B-vision` recipe with `spec-type = none` —
   it pays the no-spec decode tax (8.4 t/s vs 21–29 for the same weights with
   spec; image encode itself is fast, <0.5 s warm for 512 px) so every text recipe
   keeps its speed, and it's the lightest resident recipe (~32 GiB, no draft
   model). **"It loads" ≠ "it works"** — a vision setup that was never probed with
   a real image is unverified. (`--mmproj` is a per-section ini key by design; the
   router strips it from the shared CLI.)
8. **Router CLI args silently override per-recipe ini keys.** The router overlays
   its own command line onto every `models.ini` section: a key present in both is
   always won by the CLI and the section key is dead — no warning is logged. The
   per-child `n_max=` journal line is the ground truth. Rule: shared flags ride the
   router CLI, divergent keys (`spec-type`, `spec-draft-n-max`, `model-draft`,
   `mmproj`) live *only* in the sections.
9. **Sampling penalties are poison for speculative decode.** `repeat_penalty 1.05`
   collapses DFlash2 draft acceptance from 0.647 to 0.450 (mean accepted run
   4.8 → 3.4 tokens) — the penalized logits stop agreeing with the draft's
   continuations, so most drafted tokens get rejected and decode reverts toward
   no-spec speed. Measured cost (same loaded model, temp 0): Q6 29.0 → 21.0 (−28%),
   Q5-turbo ~23 → ~17 (−25%), Q8 ~17 → ~13 (−23%). Prefill is immune (no
   sampling) and no-spec recipes (vision) are unaffected. Per-request only, when
   repetition actually bites.
10. **Re-sending an identical prompt after a long-prompt task serves garbage
    (slot-KV contamination).** Repro (any quant, single-slot router): send prompt
    A (short) → send prompt B (~5k tokens) → send A again. The third request's
    prefix-match trusts a KV that no longer holds A, evaluates only ~3–4 of A's
    12 tokens, and decodes from a corrupted context: one quant degenerates to
    garbage (acceptance 0.02), another echoes prior content deterministically
    (acceptance 0.95 — fast *and* wrong). A different prompt recovers immediately.
    **Workaround (verified): per-request `"cache_prompt": false` on re-sent
    identical prompts.** Benchmarking corollary: only fresh-slot (first task after
    load) numbers are honest.
