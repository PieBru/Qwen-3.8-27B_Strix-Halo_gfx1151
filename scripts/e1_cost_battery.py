#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""E1 cost battery — plan docs/PLAN-reasoning-economics.md.

Measures token/wall-time cost of reasoning levels on the two quant tiers,
through the LIVE router (realistic serving: DFlash2 spec decode active).

Arms:
  main       24 prompts (8 easy / 8 medium / 8 hard, self-built) x
             {off, low, medium, xhigh} x {Q8 quality@64k, Q6 balanced}, temp 0
  budget     8 hard prompts, Q8, effort=medium, reasoning_budget_tokens=256
             (H2: hard cap -> reasoning tokens <= 256, graceful stop)
  variance   6 prompts (2/2/2), Q8, {low, medium}, temp 1.0, 3 reps
             (H1 anomaly lives in variance)

max_tokens 4096 right-censors completions (counted as truncated=true; a
truncation at the cap means the level's true cost is >= cap).

Exact reasoning-token split: response reasoning_content/content are
tokenized via the router's /tokenize (same vocab as serving).

Usage:
  uv run --with requests python3 e1_cost_battery.py [--only main|budget|variance]
                                        [--out results/e1-cost.csv]
Writes CSV (append-safe, one row per completion) + prints running progress.
"""
import argparse
import csv
import json
import os
import sys
import time

import requests

HOST = "localhost:8080"
MODELS = {"Q8": "Qwen38-27B-quality@64k", "Q6": "Qwen38-27B-balanced"}
EFFORTS = ["off", "low", "medium", "xhigh"]
MAXTOK = 4096
REQ_TIMEOUT = 300

PROMPTS = {
    "easy": [
        "What is 17 times 23? Reply with the number only.",
        "Convert 75 kilometers to miles. Reply with the number only.",
        "A shirt costs 40 euros and is discounted by 25 percent. Final price?",
        "How many days are in a leap year? Reply with the number only.",
        "What is the capital of Australia? One word.",
        "Sum the integers from 1 to 100. Reply with the number only.",
        "If a train travels 60 km in 45 minutes, what is its speed in km/h?",
        "How many minutes are in 2.5 hours? Reply with the number only.",
    ],
    "medium": [
        "A rectangle's length is twice its width. Its perimeter is 36 cm. What is its area?",
        "In a bag are 4 red, 5 blue and 3 green balls. Two are drawn without replacement. "
        "Probability that they differ in color? Give an exact fraction.",
        "A shop sells pens at 3 for 2 euros. How much do 14 pens cost?",
        "If 3 printers print 60 pages in 5 minutes, how long do 5 printers need for 100 pages?",
        "A number doubled, then reduced by 7, equals 11. What is the number squared?",
        "Anna reads 20 pages on day 1 and doubles her count every following day. "
        "On which day does she finish a 310-page book?",
        "Two dice are rolled. Probability the sum is prime? Exact fraction.",
        "A car loses 15% of its value each year. After how many full years is it "
        "worth less than half its original price?",
    ],
    "hard": [
        "Find the last two digits of 7^2026. Show the reasoning chain.",
        "Positive integers a and b satisfy a*b = 6*(a+b) with a <= b. List all pairs.",
        "How many trailing zeros does 500! have? Show the computation.",
        "In how many ways can 8 identical candies be split among 4 children so that "
        "each child gets at least one candy?",
        "Triangle ABC has AB=13, BC=14, CA=15. Compute the exact area and the "
        "circumradius.",
        "Find the smallest positive integer n such that n^2 ends in the digits 26.",
        "A sequence starts 2, 3 and each new term is the sum of all previous terms. "
        "What is the 10th term?",
        "Compute sum(k^2, k=1..100) modulo 7.",
    ],
}
VAR_PROMPTS = [PROMPTS["easy"][0], PROMPTS["easy"][4],
               PROMPTS["medium"][0], PROMPTS["medium"][2],
               PROMPTS["hard"][1], PROMPTS["hard"][2]]

FIELDS = ["arm", "model_tier", "model", "effort", "difficulty", "prompt_id",
          "temp", "rep", "prompt_tokens", "completion_tokens",
          "reasoning_tokens", "content_tokens", "wall_s", "tps",
          "finish_reason", "truncated", "budget_msg_seen", "ts"]


def chat(model, effort, user, temp=0.0, budget=None, rep=0, maxtok=MAXTOK):
    body = {"model": model,
            "messages": [{"role": "user", "content": user}],
            "chat_template_kwargs": {"reasoning_effort": effort},
            "temperature": temp, "max_tokens": maxtok}
    if budget is not None:
        body["reasoning_budget_tokens"] = budget
        body["reasoning_budget_message"] = "reasoning budget reached, answer now"
    t0 = time.time()
    def _do():
        r = requests.post(f"http://{HOST}/v1/chat/completions", json=body,
                          timeout=REQ_TIMEOUT)
        r.raise_for_status()
        return r
    r = _retry(_do, tries=8, backoff=3.0)  # tolerate model-swap reload churn (models-max 1)
    wall = time.time() - t0
    d = r.json()
    ch = d["choices"][0]
    msg = ch.get("message", {})
    reasoning = msg.get("reasoning_content") or ""
    content = msg.get("content") or ""
    budget_msg = "reasoning budget reached" in reasoning
    usage = d.get("usage", {})
    return {"prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning": reasoning, "content": content,
            "finish": ch.get("finish_reason"), "wall": wall,
            "budget_msg_seen": budget_msg}


def _retry(fn, tries=4, backoff=2.0):
    last = None
    for i in range(tries):
        try:
            return fn()
        except requests.HTTPError as e:
            last = e
            if e.response is not None and e.response.status_code < 500 and e.response.status_code != 429:
                raise
            time.sleep(backoff * (i + 1))
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            time.sleep(backoff * (i + 1))
    raise last


def ntokens(text, model, total_completion=None, other_text=""):
    """Exact token count via /tokenize; falls back to proportional estimate
    (chars-based, using total_completion as the anchor) if the router's
    tokenize proxy keeps failing."""
    if not text:
        return 0
    def _do():
        r = requests.post(f"http://{HOST}/tokenize",
                          json={"content": text, "model": model}, timeout=120)
        r.raise_for_status()
        return len(r.json()["tokens"])
    try:
        return _retry(_do, tries=2)
    except Exception:
        if total_completion is not None and (len(text) + len(other_text)) > 0:
            est = round(total_completion * len(text) / (len(text) + len(other_text)))
            print(f"  [tokenize failed -> proportional est {est}]", flush=True)
            return est
        raise


def row_for(arm, tier, effort, diff, pid, temp, rep, res):
    rt = ntokens(res["reasoning"], MODELS[tier],
                 total_completion=res["completion_tokens"], other_text=res["content"])
    ct = ntokens(res["content"], MODELS[tier])
    comp = res["completion_tokens"] or (rt + ct)
    return {"arm": arm, "model_tier": tier, "model": MODELS[tier],
            "effort": effort, "difficulty": diff, "prompt_id": pid,
            "temp": temp, "rep": rep,
            "prompt_tokens": res["prompt_tokens"], "completion_tokens": comp,
            "reasoning_tokens": rt, "content_tokens": ct,
            "wall_s": round(res["wall"], 2),
            "tps": round(comp / res["wall"], 2) if res["wall"] > 0 else "",
            "finish_reason": res["finish"],
            "truncated": res["finish"] not in ("stop", "eog", None),
            "budget_msg_seen": res["budget_msg_seen"],
            "ts": time.strftime("%H:%M:%S")}


def sanity():
    """Probe validity: each model answers and reports its own alias."""
    for tier, model in MODELS.items():
        d = chat(model, "low", "Reply with exactly: OK", rep=0)
        assert "OK" in d["content"].upper() or d["content"], f"sanity {tier}: {d}"
        r = requests.get(f"http://{HOST}/props?model={model}", timeout=10)
        ctx = r.json().get("default_generation_settings", {}).get("n_ctx")
        print(f"sanity {tier} ({model}): ctx={ctx}, first content={d['content'][:30]!r}")
        assert ctx in (65536, 131072), f"unexpected ctx {ctx} for {model}"


def run_arm(arm, rows, wr, done):
    # NOTE: arm order budget,variance BEFORE the Q6 half of main minimizes
    # model swaps on a models-max=1 router (all three Q8-heavy groups first).
    if arm == "main":
        for tier in ("Q8", "Q6"):
            for effort in EFFORTS:
                for diff, plist in PROMPTS.items():
                    for pid, p in enumerate(plist):
                        if (arm, tier, effort, diff, pid, "0.0", 0) in done:
                            continue
                        res = chat(MODELS[tier], effort, p)
                        row = row_for(arm, tier, effort, diff, pid, 0.0, 0, res)
                        rows.append(row); wr.writerow(row); print_progress(row)
    elif arm == "budget":
        for pid, p in enumerate(PROMPTS["hard"]):
            if (arm, "Q8", "medium", "hard", pid, "0.0", 0) in done:
                continue
            res = chat(MODELS["Q8"], "medium", p, budget=256)
            row = row_for(arm, "Q8", "medium", "hard", pid, 0.0, 0, res)
            rows.append(row); wr.writerow(row); print_progress(row)
    elif arm == "variance":
        for effort in ("low", "medium"):
            for pid, p in enumerate(VAR_PROMPTS):
                diff = ["easy", "easy", "medium", "medium", "hard", "hard"][pid]
                for rep in range(3):
                    if (arm, "Q8", effort, diff, pid, "1.0", rep) in done:
                        continue
                    res = chat(MODELS["Q8"], effort, p, temp=1.0, rep=rep)
                    row = row_for(arm, "Q8", effort, diff, pid, 1.0, rep, res)
                    rows.append(row); wr.writerow(row); print_progress(row)


def print_progress(row):
    print(f"[{row['ts']}] {row['arm']:8} {row['model_tier']} {row['effort']:6} "
          f"{row['difficulty']:6} p{row['prompt_id']} -> think={row['reasoning_tokens']:5} "
          f"vis={row['content_tokens']:4} wall={row['wall_s']:6}s "
          f"{'TRUNC' if row['truncated'] else ''}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="main,budget,variance")
    ap.add_argument("--out", default="results/e1-cost.csv")
    ap.add_argument("--skip-sanity", action="store_true")
    args = ap.parse_args()

    if not args.skip_sanity:
        sanity()

    exists = os.path.exists(args.out)
    done = set()
    if exists:
        with open(args.out) as fh_r:
            for r in csv.DictReader(fh_r):
                if r.get("arm") != "selftest":
                    done.add((r["arm"], r["model_tier"], r["effort"], r["difficulty"],
                              int(r["prompt_id"]), r["temp"], int(r["rep"])))
    print(f"resume: {len(done)} rows already in {args.out}")
    fh = open(args.out, "a", newline="", buffering=1)
    wr = csv.DictWriter(fh, fieldnames=FIELDS)
    if not exists:
        wr.writeheader()
    rows = []
    try:
        for arm in args.only.split(","):
            run_arm(arm.strip(), rows, wr, done)
    finally:
        fh.flush()
    print(f"\nrows this run: {len(rows)} -> {args.out}")


if __name__ == "__main__":
    main()
