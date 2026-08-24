# Headline findings — the evidence behind the claims

> From [Qwen3.8-27B on Strix Halo](../README.md) — the full version of the
> front page's findings list, with every number's evidence link.

Seven results from this setup that invert what most LLM users expect — each
measured, each linked to its evidence:

1. **Context allocation is free; filling it is not.** Decode speed does not
   scale with the *allocated* window on this hybrid-SSM model — 28–30 t/s
   whether `c` is 32k or 256k (Q8: 24.7 vs 24.9). Most layers carry a
   constant-size recurrent state; only fill depth costs
   (~10 t/s by 78k filled → 5.5 at 254k on the Q8 probe; see the decay
   table in the [recipes deep-dive](RUNNING.md)). Consequence: the
   `quality@64k…@256k` presets turn the window into a per-request dial that
   costs only RAM. Details in the
   [findings](BENCHMARKS.md#sweep-findings-at-a-glance) and the
   [recipes](RECIPES.md) notes.
2. **A lighter quant is *slower* here, not faster.** With speculative decode,
   Q4 (16.7 GiB of weights) decodes at 28 t/s vs Q5's 32 — quant noise
   collapses DFlash2 draft acceptance (0.647 → 0.41) and rejected drafts eat
   the bandwidth win whole.
   [Why Q4 was dropped](BUILDING.md#ud-q4_k_xl-evaluated-and-dropped-2026-08-21--gguf-deleted-locally)
3. **Sampling penalties are poison for speculative decode.** A mild
   `repeat_penalty 1.05` costs **23–28% decode t/s** on every spec recipe —
   penalized logits stop agreeing with the draft (acceptance 0.647 → 0.450).
   Prefill is immune; use it per-request only. [Lesson #9](LESSONS.md)
4. **f16 KV is both faster *and* higher-fidelity here.** 128 GiB of unified
   memory inverts the usual trade: q8_0 KV measured slower than f16 (Q6 19.2
   vs 20.8 t/s) — so the quality choice is also the speed choice. And if you
   do need to shrink a window: retrieval survives KV quantization down to q4_0
   (40/40 needles, f16→q4_0, up to 96k).
   [Findings](BENCHMARKS.md#sweep-findings-at-a-glance)
5. **Two recipes = two full weight copies, even for the same GGUF file.**
   mmap shares the file pages, but each recipe's process uploads its own GTT
   weights copy — measured 41.0 → 71.5 GiB RAM when vision loaded next to
   balanced (same Q6 file). No flag or Linux trick dedups device memory
   across processes. (Concurrency note, [recipes](RECIPES.md))
6. **Vision is free until the first image arrives.** Attaching mmproj costs
   ~nothing statically and text runs at full speed — but image tokens crash
   the DFlash2 speculative batch, so the vision recipe rides without spec
   decode (8.4 t/s vs 29 for the same weights). "It loads" ≠ "it works".
   [Lesson #7](LESSONS.md)
7. **Thinking is not the expensive part — running out of it is.** On
   olympiad-style items at a 4k completion budget, *thinking* modes failed
   30–40% by burning the whole budget on reasoning and returning **nothing**,
   while non-thinking solved 10/10. The effort knob doesn't order cost
   (median thinking tokens are flat low→xhigh); only `reasoning_budget_tokens`
   is a real cap. Full story:
   [Reasoning levels — measured](REASONING.md).

8. **Greedy beats sampling for coding — until it gets stuck.** A
   temperature sweep on coding tasks (130 runs, routine tier + hard-tier
   escalation; e7 battery) found: at the routine tier the model is at
   ceiling at every temperature {0, 0.3, 0.6, 0.8, 1.0} — and greedy costs
   ~10% FEWER tokens (222 vs 242–253 per solve). At the hard tier, greedy
   fails *deterministically* (same wrong approach every time) while temp
   0.6 recovers on retry (4/5 → 5/5 solved). The community's
   "temp 0.6–0.8 is better for coding" is thus **half-right**: sampling
   helps exactly where greedy ruts exist, and is pure token overhead
   everywhere else. Practical rule: code at temp 0, retry stuck items
   once at 0.6. Evidence: `results/e7-temp.csv`, `results/e7x-hard.csv`.

Plus one bonus result that earned its keep quietly: **the model still
remembers at the depths we unlocked** — a passkey needle hidden 221k tokens
deep inside a 246k context was recalled exactly
([quality at depth](DEEP-CONTEXT.md#quality-at-depth--passkey-recall-through-the-full-window-2026-08-24)).

Also big, but limitation-shaped rather than surprise-shaped: the 1M-context
story (262k servable ceiling, measured RAM budget, three routes to 1M) has
[its own chapter](DEEP-CONTEXT.md).
