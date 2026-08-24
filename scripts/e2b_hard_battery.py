#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""E2b hard battery — plan docs/PLAN-reasoning-economics.md (tier-1 follow-up).

E2 tier-1 hit a ceiling (90-95% everywhere -> no measurable thinking step).
This battery targets the regime where reasoning should matter: 10 hard,
deterministically-checkable items whose EXPECTED ANSWERS ARE COMPUTED BY THE
GRADER ITSELF (brute force / closed form in this file) — expected values
cannot be mistyped. Cells: Q8@off, Q8@xhigh, Q8@medium, Q6@off, Q6@xhigh.

Contract per item: same as E2 numeric — final numeric answer alone on the
last line; grader takes the LAST number and compares to the computed truth.

Usage:
  uv run --with requests python3 e2b_hard_battery.py [--selfcheck]
"""
import argparse
import csv
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2_quality_battery import (  # noqa: E402
    HOST, MODELS, chat, ntokens, check_numeric, last_number, _retry)

# (prompt, verifier) — verifier computes the exact expected answer
ITEMS = [
    ("Find the last two digits of 7^2026 (i.e. 7^2026 mod 100).",
     lambda: pow(7, 2026, 100)),
    ("How many trailing zeros does 500! have?",
     lambda: sum(500 // 5**k for k in range(1, 10))),
    ("Compute the sum of k^2 for k = 1..100, then give that sum modulo 7.",
     lambda: sum(k * k for k in range(1, 101)) % 7),
    ("Find the smallest positive integer n such that n^2 ends in the digits 44.",
     lambda: next(n for n in range(1, 100000) if n * n % 100 == 44)),
    ("How many pairs of positive integers (a, b) with a <= b satisfy "
     "a*b = 6*(a+b)?",
     lambda: sum(1 for a in range(1, 200) for b in range(a, 200)
                 if a * b == 6 * (a + b))),
    ("How many ways can 8 identical candies be split among 4 children so "
     "that each child gets at least one candy?",
     lambda: sum(1 for x1 in range(1, 9) for x2 in range(1, 9 - x1)
                 for x3 in range(1, 9 - x1 - x2) if 8 - x1 - x2 - x3 >= 1)),
    ("A triangle has sides 13, 14 and 15. Give its exact area.",
     lambda: 84),  # Heron: s=21, sqrt(21*8*7*6) = sqrt(7056) = 84
    ("How many three-digit positive integers are divisible by 7 but NOT by 3?",
     lambda: sum(1 for n in range(100, 1000) if n % 7 == 0 and n % 3 != 0)),
    ("A fair coin is flipped 10 times. How many distinct sequences contain "
     "exactly 4 OR exactly 5 heads?",
     lambda: 210 + 252),  # C(10,4)+C(10,5) = 210+252
    ("Find the remainder when 2^100 is divided by 7.",
     lambda: pow(2, 100, 7)),
]

TAIL = (" Show your reasoning, then end your reply with the final numeric "
        "answer alone on the last line.")

FIELDS = ["cell", "model_tier", "effort", "item_id", "correct",
          "expected", "got", "reasoning_tokens", "content_tokens",
          "wall_s", "finish_reason", "ts"]

CELLS = [("Q8", "off"), ("Q8", "xhigh"), ("Q8", "medium"),
         ("Q6", "off"), ("Q6", "xhigh")]


def selfcheck():
    """Grader computes every truth itself; verify check_numeric accepts it."""
    ok = True
    for i, (_, ver) in enumerate(ITEMS):
        exp = ver()
        if not check_numeric(f"reasoning\n{exp}", str(exp)):
            print(f"SELFCHECK FAIL item {i} (expected {exp})")
            ok = False
    # sabotage: a wrong nearby number must be rejected for large ints
    exp0 = ITEMS[0][1]()
    if check_numeric(str(exp0 + 1), str(exp0)) and exp0 > 10:
        print("SELFCHECK FAIL: off-by-one accepted on item 0")
        ok = False
    print("SELFCHECK", "OK" if ok else "FAILED",
          "| truths:", [v() for _, v in ITEMS])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/e2b-hard.csv")
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
