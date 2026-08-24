# Reasoning levels — cost and quality, measured

> From [Qwen3.8-27B on Strix Halo](../README.md) — what low/medium/xhigh actually cost and buy on this model, and the budget guard.

## Reasoning levels: cost and quality — measured

Qwen3.8 steers reasoning depth in the *prompt* (`low` / `medium` / `xhigh`,
aliases mapped by the template). Everyone repeats claims about what these
levels cost and buy; almost nobody measures. We did — full harness in the
repo (`e1_cost_battery.py`, `e2_quality_battery.py`, `e2b_hard_battery.py`,
`e2c_frontier_battery.py`, evidence in `results/e1-cost.csv`,
`results/e2-quality.csv`, `results/e2b-hard.csv`, `results/e2c-frontier.csv`;
plan with pre-registered decision rules in `docs/PLAN-INDEX.md (landed — archived locally)`).
Everything below: served through the router (DFlash2 active), temp 0, exact
reasoning/visible token split via `/tokenize`, template v22.3.

### Cost (E1: 24 prompts × 4 levels × 2 quants + variance + budget arms)

Medians (p50, temp 0, n=8 per difficulty cell):

| Cell | think p50 | think p90 | visible p50 | total p50 | wall p50 |
|---|---|---|---|---|---|
| Q8 off    | **0**   | 0   | **442** | 442 | 14.9 s |
| Q8 low    | 208     | 659 | 179     | 424 | 14.2 s |
| Q8 medium | 186     | 736 | 167     | 344 | 13.2 s |
| Q8 xhigh  | 144     | 610 | **94**  | **238** | 17.5 s |
| Q6 off    | 0       | 0   | 428     | 429 | 26.5 s |
| Q6 low    | 197     | 489 | 140     | 340 | 23.6 s |
| Q6 medium | 220     | 547 | 123     | 384 | 22.9 s |
| Q6 xhigh  | 158     | 604 | **82**  | **248** | 15.7 s |

Three things fall out:

1. **The effort knob does not order thinking cost.** Median thinking tokens
   are flat (or *lower* at xhigh!) across low/medium/xhigh — what the knob
   changes is instruction text, not a budget. p90 spread is where the levels
   differ, and it overlaps heavily.
2. **`off` is not cheap on hard work.** Without a scratchpad the model
   rambles: on hard prompts visible output p50 was 953 tokens (Q8) vs 296 at
   medium. Thinking *shortens* the answer so much that **xhigh had the lowest
   total tokens** (238 vs off's 442, Q8).
3. **The reliable cost control is `reasoning_budget_tokens`, not the level.**
   The budget arm (hard prompts, medium, cap 256) came in at ≤262 thinking
   tokens 8/8 (6/8 printed the graceful "budget reached, answer now"
   message, all finished `stop`). That's the fork's PR-#21141 lineage doing
   exactly what the soft knob can't.

The tinkerer anomaly ("low out-thinks medium/high") is real but statistical,
not a no-op: at temp 1.0 on *hard* prompts, P(think_low > median think_medium)
= **0.50** (easy 0.00, medium 0.17) — the distributions overlap; E0 confirmed
the knob reaches the rendered prompt every time (16/16 matrix rows pass,
`results/e0-matrix-*.json`).

### Quality (E2 → E2b → E2c, deterministic checkers, no LLM judge)

| Battery | Items | Q8@off | Q8@med | Q8@xhigh | Q6@off | Q6@xhigh |
|---|---|---|---|---|---|---|
| E2 routine (numeric/json/code/multihop) | 20/cell | 95% | 90% | 95% | 95% | 90% |
| E2b hard (competition-style) | 10/cell | 100%* | 100%* | 100%* | 100%* | 100%* |
| E2c frontier (olympiad, @4k budget) | 10/cell | **80%** | 60% | 60% | **100%** | 70% |
| E2c same failures re-run @16k budget | 13 | — | 4/4 | 3/4 | — | 3/3 |

\* after fixing a grader off-by-one (the model was right, the answer key
wasn't — see honesty notes).

Read that bottom row pair twice, it's the headline:

- **At a bounded completion budget (4k, what agents and routers typically
  allow), thinking mode is a liability on frontier items** — not because the
  reasoning is wrong, but because it can burn the entire budget and return
  *nothing* (`finish=length`, empty answer: 4/10 for Q8@medium and Q8@xhigh,
  3/10 for Q6@xhigh — while Q6@off solved 10/10).
- **Raise the budget to 16k and the same cells recover 10/13 instantly** —
  thinking runs 631–8,481 tokens and finishes — at **125–541 s wall** vs the
  off-mode's 46–52 s. One outlier (Q8@xhigh, primes-counting) burned even
  16k. So: capability intact; *budget exhaustion* is the failure mode.
- On everything short of frontier difficulty, **thinking-off costs nothing
  measurable** (E2/E2b ceilings at 90–100% for every cell, both quants).
  The 20–60 pt horror numbers from prior generations do not transfer to
  this model on routine work.

### What we run because of this

- **No recipe effort pins** — the pre-registered rule (Δaccuracy ≥ 3 pts AND
  wall ≤ 1.15×) is not met; anything it would buy is within noise. Default
  `medium` stands for the router; clients can pass `reasoning_effort` or the
  inline `<|think_low|>`/`<|think_xhigh|>`/`<|think_off|>` tags per request.
- **For bounded-budget agent contexts** (pi, tool loops, routers with caps):
  either ask without thinking for compute-shaped tasks, or send
  `"reasoning_budget_tokens": 512` (measured: hard cap, graceful stop) so a
  deep thinker can't starve the answer. This is a client-side body field —
  no server restart, no recipe change.
- **Never rely on the level name as a cost control** — it isn't one (table
  above); it's a *style* steering.

### Honesty notes (what the graders caught, in both directions)

- One E1 prompt was mathematically impossible ("n² ends in 26" — no square
  ends in 26 mod 100); the E2b selfcheck caught it before launch (replaced
  with a solvable variant) and it explains that prompt's token blowups.
- E2b's answer key had an off-by-one (8-candy stars-and-bars: key said 56,
  truth 35 — the *model* was right in all 5 cells; key regenerated by
  brute force, rows re-graded from stored outputs).
- E2's json category "failures" are spec-ambiguity artifacts (per-disk vs
  total TB; `#88117` vs `88117`), identical across cells — not extraction
  errors. Treat json rows as 100%-±strictness.
- Wall-clock on a models-max=1 router carries reload spikes; 18/236 E1 rows
  flagged and excluded from wall claims. Token counts are reload-immune.
- n is honest: 8/cell (E1), 5–10/cell (E2 tiers), single run at temp 0;
  the frontier gap (100% vs 60–80%) is far outside that noise, the routine
  tiers' differences are inside it — and reported as such.

