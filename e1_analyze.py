#!/usr/bin/env python3
"""E1 analysis — plan docs/PLAN-reasoning-economics.md.

Dedups results/e1-cost.csv (restarts appended duplicate cells; keeps the LAST
occurrence), flags wall-time outliers (router model-swap contamination), and
prints the cost tables + hypothesis verdicts:

  H1 (anomaly/variance): P(think_low > median(think_medium)) per stratum
     -- confirmed iff >= 0.25 on some stratum
  H2 (budget hard cap): reasoning_tokens <= 256 (+small tokenizer slack)
     and graceful-stop message observed
Usage: uv run python3 e1_analyze.py [--csv results/e1-cost.csv]
"""
import argparse
import csv
import statistics as st
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="results/e1-cost.csv")
    args = ap.parse_args()

    rows = {}
    for r in csv.DictReader(open(args.csv)):
        key = (r["arm"], r["model_tier"], r["effort"], r["difficulty"],
               int(r["prompt_id"]), r["temp"], int(r["rep"]))
        rows[key] = {k: (int(v) if k in ("prompt_tokens", "completion_tokens",
                                         "reasoning_tokens", "content_tokens") else
                         float(v) if k in ("temp", "wall_s", "tps") else v)
                     for k, v in r.items()}
    data = list(rows.values())
    print(f"unique cells: {len(data)}")

    # wall-time contamination flag: DFlash2 decode floor ~10 t/s; below that
    # on >50-token completions means a model reload inflated the wall clock
    for d in data:
        d["suspect_wall"] = (d["completion_tokens"] > 50 and
                             d["tps"] < 10.0)

    print("\n=== MAIN ARM: median cost per (tier, effort, difficulty) ===")
    print(f"{'tier':4} {'effort':7} {'diff':7} {'n':>3} {'think':>7} {'vis':>6} "
          f"{'wall_s':>7} {'tps':>6} {'trunc%':>6} {'suspect':>8}")
    groups = defaultdict(list)
    for d in data:
        if d["arm"] == "main":
            groups[(d["model_tier"], d["effort"], d["difficulty"])].append(d)
    for (tier, eff, diff) in sorted(groups):
        g = groups[(tier, eff, diff)]
        med = lambda k: st.median(x[k] for x in g)
        trunc = 100 * sum(x["truncated"] in ("True", True) for x in g) / len(g)
        susp = sum(x["suspect_wall"] for x in g)
        print(f"{tier:4} {eff:7} {diff:7} {len(g):3} {med('reasoning_tokens'):7.0f} "
              f"{med('content_tokens'):6.0f} {med('wall_s'):7.1f} {med('tps'):6.1f} "
              f"{trunc:6.1f} {susp:8}")

    print("\n=== MAIN ARM: aggregated per (tier, effort) ===")
    agg = defaultdict(list)
    for d in data:
        if d["arm"] == "main":
            agg[(d["model_tier"], d["effort"])].append(d)
    for (tier, eff) in sorted(agg):
        g = agg[(tier, eff)]
        med = lambda k: st.median(x[k] for x in g)
        print(f"{tier}@{eff:7}: think p50={med('reasoning_tokens'):6.0f} "
              f"p90={st.quantiles([x['reasoning_tokens'] for x in g], n=10)[-1]:6.0f} "
              f"vis p50={med('content_tokens'):6.0f} wall p50={med('wall_s'):6.1f}s "
              f"total_tok p50={med('completion_tokens'):6.0f}")

    print("\n=== H1 variance arm (Q8, temp 1.0, 3 reps x 6 prompts) ===")
    var = defaultdict(list)
    for d in data:
        if d["arm"] == "variance":
            var[(d["effort"], d["difficulty"])].append(d["reasoning_tokens"])
    h1_confirmed = False
    for diff in ("easy", "medium", "hard"):
        lows = var.get(("low", diff), [])
        meds = var.get(("medium", diff), [])
        if not lows or not meds:
            continue
        medm = st.median(meds)
        p = sum(l > medm for l in lows) / len(lows)
        flag = "H1 CONFIRMED (>=0.25)" if p >= 0.25 else ""
        h1_confirmed |= p >= 0.25
        print(f"{diff:7}: P(think_low > med(think_medium)) = {p:.2f}  "
              f"(lows {sorted(lows)}, med-of-mediums {medm:.0f})  {flag}")
    print(f"H1 overall: {'CONFIRMED' if h1_confirmed else 'NOT confirmed'}")

    print("\n=== H2 budget arm (Q8 medium, reasoning_budget_tokens=256, hard) ===")
    bud = [d for d in data if d["arm"] == "budget"]
    ok_cap = 0
    for d in bud:
        within = d["reasoning_tokens"] <= 256 + 12  # tokenizer re-count slack
        ok_cap += within
        print(f"hard p{d['prompt_id']}: think={d['reasoning_tokens']:5} "
              f"cap_ok={within} budget_msg={d['budget_msg_seen']} "
              f"finish={d['finish_reason']} wall={d['wall_s']:.1f}s")
    print(f"H2: {ok_cap}/{len(bud)} within cap; "
          f"budget_msg_seen on {sum(d['budget_msg_seen'] in ('True', True) for d in bud)}/{len(bud)}")

    print("\n=== OFF-arm visible-token bloat (hard prompts) ===")
    for tier in ("Q8", "Q6"):
        off = [d for d in data if d["arm"] == "main" and d["model_tier"] == tier
               and d["effort"] == "off" and d["difficulty"] == "hard"]
        med = [d for d in data if d["arm"] == "main" and d["model_tier"] == tier
               and d["effort"] == "medium" and d["difficulty"] == "hard"]
        if off and med:
            print(f"{tier} hard: vis(off) p50={st.median(x['content_tokens'] for x in off):.0f} "
                  f"vs vis(medium) p50={st.median(x['content_tokens'] for x in med):.0f}; "
                  f"total(off) p50={st.median(x['completion_tokens'] for x in off):.0f} "
                  f"vs total(medium) p50={st.median(x['completion_tokens'] for x in med):.0f}")

    n_sus = sum(d["suspect_wall"] for d in data)
    print(f"\nwall-suspect rows (excluded from wall claims): {n_sus}/{len(data)}")


if __name__ == "__main__":
    main()
