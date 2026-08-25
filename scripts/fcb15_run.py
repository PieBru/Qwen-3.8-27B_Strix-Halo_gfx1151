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
GRADE_MODE = "check"
_t_ITEMS = None  # traps (prompt, expected) list when selected

PROMPT = ("Write Python code exactly as specified. Reply with ONE python "
          "code block and nothing else.\n\n{spec}")

# in stdout mode item tuple is (prompt, None): use prompt directly


def _grade(src, item_idx, full_text=None):
    """Grade: check-mode runs the item harness on src; traps-mode execs src and
    compares the LAST stdout line, falling back to a prose-stated answer when the
    code block doesn't print (models sometimes answer in prose + demo code)."""
    _, harness = ITEMS[item_idx]
    if harness is None:  # traps mode
        import io as _io, contextlib as _cl
        pe = _t_ITEMS[item_idx] if isinstance(_t_ITEMS, dict) else _t_ITEMS[item_idx]
        want = pe[1]
        buf = _io.StringIO()
        try:
            with _cl.redirect_stdout(buf):
                exec(src, {})
        except Exception:
            pass
        lines = [l.strip() for l in buf.getvalue().splitlines() if l.strip()]
        if lines and lines[-1] == want:
            return True
        if full_text:
            import re as _re
            tail = full_text[-400:]
            pats = [rf"output[^0-9\n]*{_re.escape(want)}\b",
                    rf"\*\*{_re.escape(want)}\*\*",
                    rf"→\s*{_re.escape(want)}\b",
                    rf"->\s*{_re.escape(want)}\b",
                    rf"is\s+\**{_re.escape(want)}\**\s*(?:\.|$)"]
            return any(_re.search(p, tail) for p in pats)
        return False
    ns = {}; exec(harness, ns); ns["check"](src)
    return True


def selfcheck():
    bad = 0
    for i, ((spec_, h), ref) in enumerate(zip(ITEMS, REFS)):
        try:
            if not _grade(ref, i):
                print(f"SELFCHECK FAIL ref {i+1}"); bad += 1
        except Exception:
            print(f"SELFCHECK FAIL ref {i+1}"); bad += 1
    if GRADE_MODE == "check":  # leak probes only meaningful in check mode
        for i, ((spec_, h), wrong) in enumerate(zip(ITEMS, WRONG)):
            try:
                if _grade(wrong, i):
                    print(f"SELFCHECK LEAK {i+1}"); bad += 1
            except Exception:
                pass
    return bad == 0


def extract_code(text):
    m = re.findall(r"```(?:python)?\s*(.*?)```", text or "", re.S)
    return m[-1] if m else (text or "")  # LAST block = final answer (models emit sketch-first)


def one(item_idx, model, host, temp, tries=5, seed=None):
    """seed: optional int -> appended as a system-nudge-free deterministic
    variation via temperature sampling; llama-server seeds via 'seed' param."""
    spec_, harness = ITEMS[item_idx]
    last = None
    for a in range(tries):
        try:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": PROMPT.format(spec=spec_)}],
                "max_tokens": 4000, "temperature": temp,
            }
            if seed is not None:
                payload["seed"] = seed
            body = json.dumps(payload).encode()
            req = urllib.request.Request(f"http://{host}/v1/chat/completions", body,
                                         {"Content-Type": "application/json"})
            t0 = time.time()
            r = json.load(urllib.request.urlopen(req, timeout=900))
            dt = time.time() - t0
            m = r["choices"][0]["message"]
            code = extract_code(m.get("content") or "")
            try:
                ok = _grade(code, item_idx, full_text=m.get("content") or "")
            except Exception:
                ok = False
            return {"ok": ok, "wall": round(dt, 1),
                    "content_tail": (m.get("content") or "")[-120:],
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
    ap.add_argument("--mode", default="single", choices=["single", "bestof"])
    ap.add_argument("--battery", default="fcb15", choices=["fcb15", "traps", "combined"])
    ap.add_argument("--shots", type=int, default=5)
    args = ap.parse_args()

    global ITEMS, REFS, WRONG, GRADE_MODE, _t_ITEMS

    if args.battery == "combined":
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("t14", "results/traps14_items.py")
        _t = _ilu.module_from_spec(_sp); sys.modules["t14"] = _t; _sp.loader.exec_module(_t)
        _t_ITEMS = {15 + i: pe for i, pe in enumerate(_t.ITEMS)}  # traps rows live at idx>=15
        ITEMS = list(ITEMS) + [(p, None) for p, _ in _t.ITEMS]
        REFS = list(REFS) + list(_t.REFS)
        WRONG = list(WRONG) + ["print('DELIBERATELY WRONG')"] * len(_t.ITEMS)
        assert selfcheck(), "combined selfcheck failed"
    elif args.battery == "traps":
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("t14", "results/traps14_items.py")
        _t = _ilu.module_from_spec(_sp); sys.modules["t14"] = _t; _sp.loader.exec_module(_t)
        _t_ITEMS = _t.ITEMS  # (prompt, expected) for traps rows
        ITEMS = [(p, None) for p, _ in _t.ITEMS]
        REFS = _t.REFS
        WRONG = ["print('DELIBERATELY WRONG')"] * len(ITEMS)
        GRADE_MODE = "stdout"
        assert selfcheck(), "traps selfcheck failed"
    else:
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
            if args.mode == "bestof":
                solved = False
                any_ok = []
                for shot in range(args.shots):
                    r_ = one(i, args.model, args.host, 0.7, seed=1000 + shot)
                    any_ok.append(r_["ok"])
                    if r_["ok"]:
                        solved = True
                        break  # early stop: best-of-N solved
                    row = {"model": args.model, "item": i, "phase": f"shot{shot}", **r_}
                    out.write(json.dumps(row) + "\n"); out.flush()
                row = {"model": args.model, "item": i, "phase": "bestof",
                       "ok": solved, "shots_used": len(any_ok)}
                out.write(json.dumps(row) + "\n"); out.flush()
                print(f"item {i+1}: best-of-{args.shots} {'SOLVED' if solved else 'unsolved'}"
                      f" ({len(any_ok)} shots)", flush=True)
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
