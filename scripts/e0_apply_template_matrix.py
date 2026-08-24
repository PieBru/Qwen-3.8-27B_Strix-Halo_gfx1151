#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""E0 control-surface matrix — plan T0.2 (docs/PLAN-reasoning-economics.md).

POSTs a fixed conversation to the LIVE router's /apply-template for every
reasoning-effort spelling x thinking state and asserts, per row, the rendered
prompt carries the expected effort marker and generation-prompt tail.

Markers (froggeric v22.x template):
  low    -> 'Reasoning effort is set to low.'
  xhigh  -> 'Reasoning effort is set to xhigh.'
  medium -> neither string (zero injection by design)
  thinking ON  tail:  '<|im_start|>assistant\n<think>\n'
  thinking OFF tail:  '<|im_start|>assistant\n<think>\n\n</think>\n\n'
Inline tags <|think_low|>/<|think_xhigh|>/<|think_off|> must steer AND be
stripped from the rendered text.

Usage:  uv run --with requests python3 e0_apply_template_matrix.py [--host localhost:8080] [--model Qwen38-27B-balanced]
Exit 0 iff every row passes. Evidence: results/e0-matrix-<label>.json
"""
import argparse
import json
import sys
import time

import requests

M_LOW = "Reasoning effort is set to low."
M_XHIGH = "Reasoning effort is set to xhigh."
TAIL_ON = "<|im_start|>assistant\n<think>\n"
TAIL_OFF = "<|im_start|>assistant\n<think>\n\n</think>\n\n"

# (label, body_kwargs, expect_marker, expect_thinking, tag_to_strip)
MATRIX = [
    ("default-no-kwargs",        {},                                            None,   True,  None),
    ("effort-low",               {"reasoning_effort": "low"},                   M_LOW,  True,  None),
    ("effort-medium",            {"reasoning_effort": "medium"},                None,   True,  None),
    ("effort-xhigh",             {"reasoning_effort": "xhigh"},                 M_XHIGH, True, None),
    ("alias-minimal",            {"reasoning_effort": "minimal"},               M_LOW,  True,  None),
    ("alias-high",               {"reasoning_effort": "high"},                  M_XHIGH, True, None),
    ("alias-max",                {"reasoning_effort": "max"},                   M_XHIGH, True, None),
    ("alias-ultracode",          {"reasoning_effort": "ultracode"},             M_XHIGH, True, None),
    ("alias-extreme",            {"reasoning_effort": "extreme"},               M_XHIGH, True, None),
    ("kwarg-off",                {"reasoning_effort": "off"},                   None,   False, None),
    ("top-none",                 {"none_special": True},                        None,   False, None),
    ("kwarg-enable-false",       {"enable_thinking": False},                    None,   False, None),
    ("off-plus-low",             {"reasoning_effort": "low",
                                  "enable_thinking": False},                    None,   False, None),
    ("inline-think-low",         {"inline": "<|think_low|>"},                   M_LOW,  True,  "<|think_low|>"),
    ("inline-think-xhigh",       {"inline": "<|think_xhigh|>"},                 M_XHIGH, True, "<|think_xhigh|>"),
    ("inline-think-off",         {"inline": "<|think_off|>"},                   None,   False, "<|think_off|>"),
]

USER_TEXT = "Compute 17*23 and explain the steps."


def render(host, model, kwargs):
    body = {"model": model,
            "messages": [{"role": "user", "content": USER_TEXT + (kwargs.get("inline") or "")}],
            "add_generation_prompt": True}
    if kwargs.get("none_special"):
        body["reasoning_effort"] = "none"  # top-level OAI field (server special-case)
    else:
        ctk = {}
        if "reasoning_effort" in kwargs:
            ctk["reasoning_effort"] = kwargs["reasoning_effort"]
        if "enable_thinking" in kwargs:
            ctk["enable_thinking"] = kwargs["enable_thinking"]
        if ctk:
            body["chat_template_kwargs"] = ctk
    t0 = time.time()
    r = requests.post(f"http://{host}/apply-template", json=body, timeout=30)
    dt = (time.time() - t0) * 1000
    r.raise_for_status()
    return r.json()["prompt"], dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost:8080")
    ap.add_argument("--model", default="Qwen38-27B-balanced")
    ap.add_argument("--label", default="run")
    args = ap.parse_args()

    results, fails = [], 0
    for label, kwargs, marker, thinking, tag in MATRIX:
        prompt, dt = render(args.host, args.model, kwargs)
        got_marker = M_LOW if M_LOW in prompt else (M_XHIGH if M_XHIGH in prompt else None)
        tail_ok = prompt.endswith(TAIL_ON) if thinking else prompt.endswith(TAIL_OFF)
        marker_ok = (got_marker == marker)
        tag_ok = (tag not in prompt) if tag else True
        ok = marker_ok and tail_ok and tag_ok
        fails += 0 if ok else 1
        results.append({"label": label, "ok": ok, "marker_ok": marker_ok,
                        "tail_ok": tail_ok, "tag_ok": tag_ok,
                        "got_marker": got_marker, "render_ms": round(dt, 1)})
        print(f"{'PASS' if ok else 'FAIL'}  {label:22} marker={got_marker or '-':6} "
              f"tail={'on' if thinking else 'off':3} render={dt:.0f}ms")

    print(f"\n{len(MATRIX) - fails}/{len(MATRIX)} rows passed")
    out = f"results/e0-matrix-{args.label}.json"
    with open(out, "w") as fh:
        json.dump({"label": args.label, "model": args.model, "rows": results}, fh, indent=1)
    print(f"evidence: {out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
