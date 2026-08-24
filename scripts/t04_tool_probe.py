#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""T0.4 probe — plan docs/PLAN-reasoning-economics.md.

Tool-call round-trip verification on the LIVE router (post v22.3 swap).

Part A (render checks via /apply-template, no inference):
  A1 mapping-args tool_calls render as <tool_call> XML with <parameter=k>
  A2 JSON-STRING arguments (OpenAI client shape) render without crash
  A3 scalar argument renders (v22.3 | tojson fix; v22.1.1 dropped it)
  A4 tool error payload -> ⚠️ SYSTEM WARNING injected
  A5 success envelope ("error": null) -> NO warning (false-positive fix)
  A6 mid-loop developer message -> merged into system head, no crash
  A7 assistant reasoning + tool_calls renders think block + tool_call

Part B (live inference through the router, effort=low):
  B1 model emits a well-formed tool call; tool result replayed; final answer.

Usage: uv run --with requests python3 t04_tool_probe.py [--label run] [--skip-b]
Exit 0 iff all requested checks pass. Evidence: results/t04-<label>.json
"""
import argparse
import json
import sys

import requests

WARN1 = "⚠️ SYSTEM WARNING: The previous tool call returned an error."
WARN2 = "consecutive tool errors"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}, "unit": {"type": "string"}},
            "required": ["city"],
        },
    },
}]


def apl(host, model, body):
    r = requests.post(f"http://{host}/apply-template", json=body, timeout=30)
    r.raise_for_status()
    return r.json()["prompt"]


def part_a(host, model):
    checks = {}

    def hist(tool_calls, tool_resp):
        # REAL agent shape: assistant tool-call turn is NEVER trailing — a tool
        # response follows, so the template (not the server continuation path)
        # renders it. Trailing-assistant + tool_calls is a server continuation
        # path that drops the calls (documented edge, not template behavior).
        msgs = [{"role": "user", "content": "weather in Rome?"},
                {"role": "assistant", "content": "", "tool_calls": tool_calls}]
        if tool_resp is not None:
            msgs.append({"role": "tool", "content": tool_resp})
        return apl(host, model, {"model": model, "messages": msgs,
                                 "tools": TOOLS, "add_generation_prompt": True})

    tc_map = [{"type": "function", "function": {"name": "get_weather",
                                                "arguments": {"city": "Rome", "unit": "celsius"}}}]
    tc_str = [{"type": "function", "function": {"name": "get_weather",
                                                "arguments": "{\"city\": \"Rome\"}"}}]
    tc_scalar = [{"type": "function", "function": {"name": "get_weather", "arguments": 444}}]

    p1 = hist(tc_map, '{"temp": 21}')
    checks["A1_mapping_args_xml"] = ("<function=get_weather>" in p1
                                     and "<parameter=city>" in p1
                                     and p1.count("Rome\n</parameter>") >= 1)

    p2 = hist(tc_str, '{"temp": 21}')
    checks["A2_json_string_args"] = ("<parameter=city>" in p2
                                     and "Rome\n</parameter>" in p2)

    p3 = hist(tc_scalar, '{"temp": 21}')
    checks["A3_scalar_arg_rendered"] = ("<function=get_weather>\n444</function>" in p3)

    p4 = hist(tc_map, '{"error": "boom"}')
    checks["A4_error_warns"] = WARN1 in p4

    p5 = hist(tc_map, '{"result": {"temp": 21, "sky": "clear"}, "error": null}')
    checks["A5_success_nowarn"] = (WARN1 not in p5 and WARN2 not in p5)

    dev = [{"role": "developer", "content": "Use metric units always."},
           {"role": "developer", "content": "Prefer terse answers."}]
    p6 = hist(tc_map, '{"temp": 21}')
    p6d = apl(host, model, {"model": model, "messages": dev + [
        {"role": "user", "content": "weather in Rome?"},
        {"role": "assistant", "content": "", "tool_calls": tc_map},
        {"role": "tool", "content": "{\"temp\": 21}"}],
        "tools": TOOLS, "add_generation_prompt": True})
    checks["A6_developer_merged"] = ("<|im_start|>developer" not in p6d
                                     and "metric units" in p6d and "terse answers" in p6d
                                     and "<parameter=city>" in p6d)
    _ = p6

    p7 = apl(host, model, {"model": model,
                           "messages": [{"role": "user", "content": "weather?"},
                                        {"role": "assistant", "content": "",
                                         "reasoning_content": "need the tool",
                                         "tool_calls": tc_map},
                                        {"role": "tool", "content": "{\"temp\": 21}"}],
                           "tools": TOOLS, "add_generation_prompt": True})
    at = p7.split("<|im_start|>assistant")[1] if "<|im_start|>assistant" in p7 else ""
    checks["A7_think_plus_toolcall"] = ("<think>\nneed the tool\n</think>" in at
                                        and "<function=get_weather>" in at)
    return checks


def part_b(host, model):
    checks = {}
    msgs = [{"role": "user", "content": "What is the weather in Rome right now? Use the tool."}]
    r = requests.post(f"http://{host}/v1/chat/completions", json={
        "model": model, "messages": msgs, "tools": TOOLS,
        "chat_template_kwargs": {"reasoning_effort": "low"},
        "max_tokens": 300, "temperature": 0.0,
    }, timeout=180)
    r.raise_for_status()
    m = r.json()["choices"][0]["message"]
    tcs = m.get("tool_calls") or []
    checks["B1_toolcall_emitted"] = bool(tcs) and tcs[0]["function"]["name"] == "get_weather"
    args_ok = False
    if tcs:
        try:
            a = json.loads(tcs[0]["function"]["arguments"])
            args_ok = "rome" in str(a).lower()
        except Exception:
            args_ok = False
    checks["B1_args_valid_json"] = args_ok

    if tcs:
        msgs += [{"role": "assistant", "content": m.get("content") or "",
                  "reasoning_content": m.get("reasoning_content") or "",
                  "tool_calls": tcs},
                 {"role": "tool", "content": '{"temp": 21, "sky": "clear", "unit": "celsius"}'}]
        r2 = requests.post(f"http://{host}/v1/chat/completions", json={
            "model": model, "messages": msgs, "tools": TOOLS,
            "chat_template_kwargs": {"reasoning_effort": "low"},
            "max_tokens": 200, "temperature": 0.0,
        }, timeout=180)
        r2.raise_for_status()
        final = r2.json()["choices"][0]["message"].get("content") or ""
        checks["B2_final_answer"] = ("21" in final) and ("rome" in final.lower() or "clear" in final.lower())
        checks["_final_excerpt"] = final[:160]
    else:
        checks["B2_final_answer"] = False
        checks["_final_excerpt"] = "no tool call emitted"
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost:8080")
    ap.add_argument("--model", default="Qwen38-27B-balanced")
    ap.add_argument("--label", default="run")
    ap.add_argument("--skip-b", action="store_true")
    args = ap.parse_args()

    checks = part_a(args.host, args.model)
    if not args.skip_b:
        checks.update(part_b(args.host, args.model))

    ok = all(v for k, v in checks.items() if not k.startswith("_"))
    for k, v in checks.items():
        if not k.startswith("_"):
            print(f"{'PASS' if v else 'FAIL'}  {k}")
    if "_final_excerpt" in checks:
        print("final:", checks["_final_excerpt"])
    print(f"\n{'ALL GREEN' if ok else 'RED'}")
    with open(f"results/t04-{args.label}.json", "w") as fh:
        json.dump({"label": args.label, "checks": checks}, fh, indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
