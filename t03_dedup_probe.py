#!/usr/bin/env python3
"""T0.3 probe — plan docs/PLAN-reasoning-economics.md.

Verifies on the LIVE router (post v22.3 swap):
 1. DEDUP: an assistant message carrying BOTH `reasoning_content` and an
    inline `<think>...</think>` in content renders exactly ONE think block
    (v22.3 fix; closes the postponed reasoning_format=none double-wrap risk:
    a client that gets thinking inline in content and replays it alongside
    the reasoning field must not poison history).
 2. PREFIX-ID: render(messages[:k]) is a byte-prefix of render(messages[:k+1])
    at generation boundaries (live KV-cache stability; static fuzz already
    holds it over 500 cases).

Usage: uv run --with requests python3 t03_dedup_probe.py [--label run]
Exit 0 iff all checks pass. Evidence: results/t03-<label>.json
"""
import argparse
import json
import sys

import requests

THINK_MSG = {
    "role": "assistant",
    "content": "<think>\ninline reasoning body\n</think>\n\nThe answer is 391.",
    "reasoning_content": "explicit reasoning body from the field",
}


def apply_tpl(messages, host, model, add_gen=True):
    body = {"model": model, "messages": messages, "add_generation_prompt": add_gen}
    r = requests.post(f"http://{host}/apply-template", json=body, timeout=30)
    r.raise_for_status()
    return r.json()["prompt"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost:8080")
    ap.add_argument("--model", default="Qwen38-27B-balanced")
    ap.add_argument("--label", default="run")
    args = ap.parse_args()

    checks = {}

    # 1. dedup: one think block for the dual-carry assistant message
    msgs = [{"role": "user", "content": "17*23?"},
            THINK_MSG,
            {"role": "user", "content": "and in roman numerals?"}]
    p = apply_tpl(msgs, args.host, args.model)
    # counts must EXCLUDE the generation-prompt tail (<think> from prefill)
    hist = p[: p.rfind("<|im_start|>assistant\n<think>")]
    n_open = hist.count("<think>")
    n_close = hist.count("</think>")
    checks["dedup_one_think_block"] = (n_open, n_close) == (1, 1)
    checks["_counts"] = {"open": n_open, "close": n_close, "tail_stripped": len(p) - len(hist)}

    # reasoning_content must win (explicit field), inline copy stripped
    checks["explicit_field_wins"] = "explicit reasoning body from the field" in p
    checks["inline_copy_stripped"] = "inline reasoning body" not in p.replace(
        "explicit reasoning body from the field", "")
    checks["answer_kept"] = "The answer is 391." in p

    # 2. prefix identity at GENERATION boundaries: every turn ends with a user
    #    message (the state the server actually renders for generation); the
    #    k-th gen prompt must be a byte-prefix of the (k+1)-th gen prompt.
    #    (A trailing assistant is a server-side continuation path, not a
    #    generation boundary — excluded by design, see results notes.)
    turns = [[{"role": "user", "content": "q1"}],
             [{"role": "user", "content": "q1"},
              {"role": "assistant", "content": "<think>\nt1\n</think>\n\na1", "reasoning_content": "t1"},
              {"role": "user", "content": "q2"}],
             [{"role": "user", "content": "q1"},
              {"role": "assistant", "content": "<think>\nt1\n</think>\n\na1", "reasoning_content": "t1"},
              {"role": "user", "content": "q2"},
              {"role": "assistant", "content": "<think>\nt2\n</think>\n\na2", "reasoning_content": "t2"},
              {"role": "user", "content": "q3"}]]
    prev = None
    prefix_ok = True
    for k, msgs_k in enumerate(turns):
        cur = apply_tpl(msgs_k, args.host, args.model)
        if prev is not None and not cur.startswith(prev):
            prefix_ok = False
            break
        prev = cur
    checks["prefix_identity_live"] = prefix_ok

    ok = all(v for k, v in checks.items() if not k.startswith("_"))
    for k, v in checks.items():
        if not k.startswith("_"):
            print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"\n{'ALL GREEN' if ok else 'RED'}")
    with open(f"results/t03-{args.label}.json", "w") as fh:
        json.dump({"label": args.label, "checks": checks}, fh, indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
