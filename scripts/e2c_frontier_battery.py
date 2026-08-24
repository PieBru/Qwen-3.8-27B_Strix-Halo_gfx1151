#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""E2c frontier battery — plan docs/PLAN-reasoning-economics.md.

Escalation after E2 (routine, 90-95%) and E2b (hard, 100% after grader fix)
both hit the ceiling: olympiad-style items where prior-gen reasoning models
show large thinking-mode deltas. Truths computed by brute force in this file.

Cells: Q8@off, Q8@xhigh, Q8@medium, Q6@off, Q6@xhigh (10 items each).
Usage: uv run --with requests python3 e2c_frontier_battery.py [--selfcheck]
"""
import argparse
import csv
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2_quality_battery import (  # noqa: E402
    MODELS, chat, ntokens, check_numeric, last_number)


def r2_2026():
    n = 0
    for x in range(-46, 47):
        for y in range(-46, 47):
            if x * x + y * y == 2026:
                n += 1
    return n


def last_two_nonzero_factorial_100():
    f = math.factorial(100)
    while f % 10 == 0:
        f //= 10
    return f % 100


def mult_order_3_mod_101():
    v, k = 3, 1
    while v != 1:
        v = v * 3 % 101
        k += 1
    return k


def is_prime(n):
    if n < 2:
        return False
    return all(n % d for d in range(2, int(n ** 0.5) + 1))


ITEMS = [
    ("How many ORDERED pairs of positive integers (a, b) satisfy 1/a + 1/b = 1/6?",
     lambda: sum(1 for a in range(1, 501) for b in range(1, 501)
                 if abs(1 / a + 1 / b - 1 / 6) < 1e-12)),
    ("What are the last two NON-ZERO digits of 100! ?",
     last_two_nonzero_factorial_100),
    ("How many primes p < 100 have the property that p^2 + 2 is also prime?",
     lambda: sum(1 for p in range(2, 100) if is_prime(p) and is_prime(p * p + 2))),
    ("Find the smallest palindrome greater than 1,000,000 that is divisible by 7.",
     lambda: next(n for n in range(1_000_001, 2_000_000)
                  if str(n) == str(n)[::-1] and n % 7 == 0)),
    ("How many integer pairs (x, y) — counting order and signs — satisfy "
     "x^2 + y^2 = 2026?",
     r2_2026),
    ("What is the sum of the decimal digits of 2^50?",
     lambda: sum(int(c) for c in str(2 ** 50))),
    ("Compute the floor of the sum of 1/sqrt(k) for k = 1 to 1000.",
     lambda: int(math.floor(sum(1 / math.sqrt(k) for k in range(1, 1001))))),
    ("How many subsets of {1, 2, ..., 10} contain no two consecutive integers?",
     lambda: sum(1 for m in range(1024)
                 if all(not ((m >> i) & 1 and (m >> (i + 1)) & 1) for i in range(9)))),
    ("What is the multiplicative order of 3 modulo 101 (smallest k > 0 with "
     "3^k ≡ 1 mod 101)?",
     mult_order_3_mod_101),
    ("How many primes are there strictly between 1000 and 2026?",
     lambda: sum(1 for n in range(1001, 2026) if is_prime(n))),
]

TAIL = (" Show your reasoning, then end your reply with the final numeric "
        "answer alone on the last line.")

FIELDS = ["cell", "model_tier", "effort", "item_id", "correct",
          "expected", "got", "reasoning_tokens", "content_tokens",
          "wall_s", "finish_reason", "ts"]

CELLS = [("Q8", "off"), ("Q8", "xhigh"), ("Q8", "medium"),
         ("Q6", "off"), ("Q6", "xhigh")]


def selfcheck():
    ok = True
    for i, (_, ver) in enumerate(ITEMS):
        exp = ver()
        if not check_numeric(f"work\n{exp}", str(exp)):
            print(f"SELFCHECK FAIL item {i} (expected {exp})")
            ok = False
        # cross-check a couple of closed forms against brute force results
    truths = [v() for _, v in ITEMS]
    assert truths[7] == 144, "no-consecutive subsets must be Fib(12)=144"
    print("SELFCHECK", "OK" if ok else "FAILED", "| truths:", truths)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/e2c-frontier.csv")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if not selfcheck():
        sys.exit(2)
    if args.selfcheck:
        return

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for r in csv.DictReader(fh, fieldnames=FIELDS):
                done.add((r["model_tier"], r["effort"], int(r["item_id"])))
    print(f"resume: {len(done)} done")

    header_needed = not os.path.exists(args.out)
    fh = open(args.out, "a", newline="", buffering=1)
    wr = csv.DictWriter(fh, fieldnames=FIELDS)
    if header_needed:
        wr.writeheader()
    for tier, effort in CELLS:
        for iid, (q, ver) in enumerate(ITEMS):
            if (tier, effort, iid) in done:
                continue
            exp = str(ver())
            res = chat(MODELS[tier], effort, q + TAIL)
            got = last_number(res["content"] or "")
            correct = check_numeric(res["content"] or "", exp)
            row = {"cell": f"{tier}@{effort}", "model_tier": tier,
                   "effort": effort, "item_id": iid, "correct": int(correct),
                   "expected": exp, "got": got,
                   "reasoning_tokens": ntokens(res["reasoning"], MODELS[tier]),
                   "content_tokens": ntokens(res["content"], MODELS[tier]),
                   "wall_s": round(res["wall"], 2),
                   "finish_reason": res["finish"],
                   "ts": time.strftime("%H:%M:%S")}
            wr.writerow(row)
            print(f"[{row['ts']}] {row['cell']:11} i{iid} -> "
                  f"{'PASS' if correct else 'FAIL'} exp={exp} got={got} "
                  f"think={row['reasoning_tokens']:5} wall={row['wall_s']:6}s",
                  flush=True)
    fh.close()
    print("battery complete")


if __name__ == "__main__":
    main()
