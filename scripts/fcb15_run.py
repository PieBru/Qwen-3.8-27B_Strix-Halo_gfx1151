#!/usr/bin/env python3
"""fcb15_run — run the FCB-15 frontier battery against an endpoint.

Usage:
  uv run --with requests python3 scripts/fcb15_run.py --tag calib27B \
      --model Qwen38-27B-coding [--host 127.0.0.1:8080] [--n N]

Protocol (FCB15-CALIBRATION-INTERNAL.md): temp 0 primary; on failure ONE
retry at temp 0.6 (E7 rule). Records greedy + retry results separately.
JSONL resume-safe (skips completed (model,item) cells).
"""
import os
import sys
import json
import re
import time
import argparse
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "results")
from fcb15_items import ITEMS, REFS, WRONG  # noqa: E402

PROMPT = ("Write Python code exactly as specified. Reply with ONE python "
          "code block and nothing else.\n\n{spec}")


def selfcheck():
    bad = 0
    for i, ((spec_, h), ref) in enumerate(zip(ITEMS, REFS)):
        try:
            ns = {}; exec(h, ns); ns["check"](ref)
        except Exception:
            print(f"SELFCHECK FAIL ref {i+1}"); bad += 1
    for i, ((spec_, h), wrong) in enumerate(zip(ITEMS, WRONG)):
        try:
            ns = {}; exec(h, ns); ns["check"](wrong)
            print(f"SELFCHECK LEAK {i+1}"); bad += 1
        except Exception:
            pass
    return bad == 0


def extract_code(text):
    m = re.findall(r"```(?:python)?\s*(.*?)```", text or "", re.S)
    return m[0] if m else (text or "")


def one(item_idx, model, host, temp, tries=5):
    spec_, harness = ITEMS[item_idx]
    last = None
    for a in range(tries):
        try:
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": PROMPT.format(spec=spec_)}],
                "max_tokens": 4000, "temperature": temp,
            }).encode()
            req = urllib.request.Request(f"http://{host}/v1/chat/completions", body,
                                         {"Content-Type": "application/json"})
            t0 = time.time()
            r = json.load(urllib.request.urlopen(req, timeout=900))
            dt = time.time() - t0
            m = r["choices"][0]["message"]
            code = extract_code(m.get("content") or "")
            ok = False
            try:
                ns = {}; exec(harness, ns); ns["check"](code); ok = True
            except Exception:
                ok = False
            return {"ok": ok, "wall": round(dt, 1),
                    "reason_w": len((m.get("reasoning_content") or "").split()),
                    "content_w": len((m.get("content") or "").split()),
                    "finish": r["choices"][0].get("finish_reason")}
        except Exception as e:
            last = e
            time.sleep(3 * (a + 1))
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:8080")
    ap.add_argument("--model", default="Qwen38-27B-coding")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    assert selfcheck(), "battery selfcheck failed — refusing to run"

    out_path = f"results/fcb15-{args.tag}.jsonl"
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                r = json.loads(line)
                done.add((r["model"], r["item"]))
            except Exception:
                pass

    greedy_ok = retry_ok = 0
    n_items = len(ITEMS)
    with open(out_path, "a") as out:
        for i in range(n_items):
            if (args.model, i) in done:
                continue
            g = one(i, args.model, args.host, 0.0)
            row = {"model": args.model, "item": i, "phase": "greedy", **g}
            out.write(json.dumps(row) + "\n"); out.flush()
            greedy_ok += g["ok"]
            rr = None
            if not g["ok"]:
                rr = one(i, args.model, args.host, 0.6)
                row = {"model": args.model, "item": i, "phase": "retry06", **rr}
                out.write(json.dumps(row) + "\n"); out.flush()
                retry_ok += rr["ok"]
            print(f"item {i+1}: greedy {'PASS' if g['ok'] else 'FAIL'}"
                  + (f" | retry@0.6 {'PASS' if rr and rr['ok'] else 'FAIL'}" if rr else "")
                  + f" ({g['wall']}s)", flush=True)

    # summary over ALL rows (incl. resumed)
    rows = [json.loads(l) for l in open(out_path) if args.model in l]
    g_rows = [r for r in rows if r["phase"] == "greedy"]
    r_rows = [r for r in rows if r["phase"] == "retry06"]
    gs = sum(r["ok"] for r in g_rows)
    rs = gs + sum(r["ok"] for r in r_rows)
    print(f"\nSUMMARY {args.model} [{args.tag}]: greedy {gs}/{len(g_rows)}"
          f" | with-retry {rs}/{len(g_rows)}", flush=True)


if __name__ == "__main__":
    main()
