# Plan: Reasoning economics & template v22.3 — measured, on our stack

Status: PROPOSED (2026-08-22) · not yet executed · pre-development artifact per
house rules (AGENTS.md: plans/specs are the legitimate .md class).

## Why

Three threads converged: (1) tinkerers report Qwen3.8's reasoning levels
misbehave — sometimes "low" out-reasons "high"; (2) we run two quant tiers
(Q8/Q6) and two fence recipes, but have never measured what a reasoning level
is *worth* relative to a quant step; (3) our chat template (froggeric v22.1.1)
is two minor versions behind a fast-moving upstream, and the delta is
substantive. Everything below turns these into binary questions with
pre-registered decision rules, on our own rig, reproducible from the repo.

## Research findings (all evidence in hand)

- **Levels are soft steering, not caps.** Qwen3.8 has 3 native levels
  (low/medium/xhigh; card default xhigh). Effort shifts a *distribution*; the
  only hard limiter is the server's `--reasoning-budget N` (+ graceful
  termination message, fork PR #21141 lineage).
- **The anomaly is multiply documented, mechanism unproven.** HF #136
  ("overthink eats context"), #113 ("cannot stop thinking"), llama.cpp #27023
  ("reasoning_effort seems broken" — template-dependent no-ops), and the vendor
  card itself: lower effort can *increase* total tokens/time in agentic loops
  via retry cascades. Candidate mechanisms we can discriminate: (a)
  distribution overlap, (b) silent no-op (level never reaches the template),
  (c) task-dependence.
- **No non-thinking quality number exists for this model.** The 3.8-27B card
  publishes thinking-mode benchmarks only; prior-gen family cards showed ~0–3
  pts loss on routine tasks, ~20–60 pts on hard reasoning (INFERRED
  carryover). The card's separate non-thinking sampler (temp 0.7/pp 0.8/
  presence 1.5) signals expected degeneration pressure.
- **Our stack's template layer is load-bearing.** Certified via froggeric's
  own `check_applied.py`: our Unsloth v3 UD GGUFs embed the **stock official
  template** ("⚠️ Stock / unpatched") — Unsloth did *not* absorb the fixes.
  Our `--chat-template-file sharp.jinja` (v22.1.1) is what restores
  `enable_thinking=false` (official: fatal crash — we use it daily), cures
  empty-think poisoning, survives JSON-string tool args, and maps client
  aliases.
- **v22.3 (2026-08-20) is substantive**: 158 changed lines vs our v22.1.1.
  Two-tier tool-error escalation (no false retries on `"error": null` or code
  grep hits); reasoning de-dup (clients sending both `reasoning_content` and
  inline `<think>` no longer double-emit — exactly our postponed
  `reasoning_format=none` risk); complete tool-arg serialization (`| tojson`;
  v22.1.1 silently drops some shapes); multi-system/`developer` head merging;
  new aliases (`off`, `ultracode`, `extreme`, `max`).
- **One unverified perf claim**: "deep Jinja nesting drops llama.cpp speed by
  80%; flattened AST maximizes throughput." Testable in minutes.

## Questions, as falsifiable hypotheses

| # | Question | Hypothesis to test |
|---|---|---|
| Q1 | Token/wall-time/context cost of levels; anomaly real? | H1: P(low thinking > median medium) ≥ 25% on some strata. H2: only `--reasoning-budget` gives a reliable cost ceiling. H3: anomaly is (a) overlap or (b) no-op — E0 discriminates. |
| Q2 | Quality impact per level per quant; crossover? | H4: reasoning on/off moves accuracy ≥ 3× more than the Q8→Q6 step on reasoning-shaped tasks. H5 (crossover): Q6@xhigh ≥ Q8@medium − 1 pt at ≤ its wall-time. |
| Q3 | Cost of thinking fully off, measured | Quantified as the `off` cell of E2 (replacing prior-gen inference). |
| Q4 | Adopt v22.3? | Green on test suite + fuzz + E0 matrix + live round-trips ⇒ ship. Any red ⇒ document, stay, report upstream. |
| Q5 | Template speed claim | H6: prompt-processing throughput differs measurably between v22.1.1, v22.3, and embedded-official renders (same prompt, same model, n=3). |

## Experiments

### T0 — Template adopt-track (~1 h, mostly CPU; router untouched until final swap)

1. Froggeric's own suite: `test_v22.py`, property-based `fuzz_template.py`,
   minify check — local, no GPU.
2. E0 control-surface matrix via `/apply-template` on the live router: effort
   ∈ {off, low, medium, xhigh, +aliases} × {thinking on/off} — rendered
   prompts must differ per level (no-op detector for #27023-class bugs).
3. `reasoning_format=none` live probe (postponed item folded in): inline
   thinking renders; replayed inline `<think>` does **not** double-wrap on
   v22.3 (the dedup fix) — incl. KV-prefix identity check.
4. Tool-call round-trip via the router's `--agent` surface: XML + JSON-string
   args + an error response (tiering) + mid-loop developer message (head
   merge).
5. Template speed probe (Q5): same 8k prompt through v22.1.1 vs v22.3 vs
   embedded official; report prompt-eval t/s, n=3.
6. Ship decision: v22.3 → `sharp.jinja`, restart, catalog + completion + pi
   e2e probes; README notes the `check_applied.py` certification and that the
   override is load-bearing.

### E1 — Cost battery (~1.5 h GPU)

24 fixed prompts stratified easy/medium/hard × {off, low, medium, xhigh} ×
{Q8, Q6}; temp 0 everywhere + a temp-1.0 n=3 subset on 6 prompts (the anomaly
lives in variance). Per run: thinking tokens, visible tokens, prefill/decode
wall-time, context growth. Also one `--reasoning-budget` arm (H2). Output:
cost table + p50/p90 per level.

### E2 — Quality battery (tiered; Tier-1 ≈ 1 h, full ≈ 4.5 h)

40 self-built, deterministically-checkable items — 10 numeric word problems
(exact match), 10 JSON extractions (schema validation), 10 small code gens
(unit tests), 10 multi-hop QA over local corpus (exact string). No verbatim
public benchmark items; no LLM judge. Cells: {Q8, Q6} × {off, low, medium,
xhigh}. Tier-1 = 20 items × 4 pivotal cells ({Q6,Q8} × {off, xhigh} +
Q8@medium baseline) → first signal cheaply; full 8-cell only if Tier-1
promising. Metrics: accuracy, quality/token, quality/wall-minute. Headline:
Q6@xhigh vs Q8@low vs Q8@medium.

### E3 — Agentic realism (optional Tier-3, ~2 h)

3 multi-turn tasks × 2 runs per pivotal cell; metric = total tokens/time to
task success (tests the vendor's retry-cascade warning — where "cheap" levels
cost more end-to-end).

## Pre-registered decision rules

- **Adopt v22.3** iff T0.1–T0.4 all green.
- **Change a recipe's standing effort** iff accuracy Δ ≥ 3 pts and wall-time
  ≤ 1.15× baseline.
- **Declare "Q6+reasoning beats Q8"** iff Q6@xhigh ≥ Q8@medium − 1 pt *and*
  total wall-time ≤ Q8@medium's.
- **Declare the anomaly confirmed** iff H1 holds at the pre-registered 25%;
  root-caused if E0 shows no-op, else attributed to overlap/task-dependence
  via the p90/median split.
- Any negative result ships too — the README section is evidence either way.

## Logistics

Same discipline as the fill battery: committed scripts (`/apply-template`
harness, cost/quality runners), per-run CSVs + server logs in `results/`,
guards against silent server death and port collisions, router restored +
preload verified at every session end. Sequencing: **T0 first** (it changes
what E1/E2 measure — levels must be proven live before costing them), then
E1, then E2-Tier-1, then (data-permitting) E2-full + E3. Total: ~3 h to first
decisions, ~8–9 h GPU for everything including optionals — one or two evening
slots, or split across nights after the dream run.

## Deliverables

README section "Reasoning levels: cost and quality" (tables, charts if
warranted); possibly per-recipe effort pins (speed→low, balanced→medium,
quality→xhigh); v22.3 shipped with certification note; closure of the
postponed `reasoning_format=none` item; and the Q6-vs-Q8 reasoning crossover
answered with our own numbers.
