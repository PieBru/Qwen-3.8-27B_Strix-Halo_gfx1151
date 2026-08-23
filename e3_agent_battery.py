#!/usr/bin/env python3
"""E3 agentic-realism battery — plan docs/PLAN-reasoning-economics.md (addendum).

Client-side agent loop against the LIVE router: model must call local tools
to answer. Cells: balanced@{off,low,medium,xhigh} + coding (budget-2048
guard). Tasks: T1 clean calculator loop, T2 error-recovery (tool fails on
first call per episode), T3 ledger synthesis. max 8 turns, max_tokens 1024,
temp 0, 2 reps. Deterministic tool executors — no LLM judge.

Evidence: results/e3-agentic.csv (+ results/e3-episodes/ per-episode traces)
Usage: uv run --with requests python3 e3_agent_battery.py [--cells ...] [--tasks ...]
"""
import argparse
import csv
import json
import os
import time

import requests

HOST = "localhost:8080"
MAX_TURNS = 8
MAXTOK = 1024

TOOLS = [
    {"type": "function", "function": {
        "name": "calculator",
        "description": "Evaluate one arithmetic expression, e.g. '17*23'. Returns {\"result\": number}.",
        "parameters": {"type": "object",
                       "properties": {"expr": {"type": "string"}},
                       "required": ["expr"]}}},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "Current weather for a city. Returns {\"temp_c\": int, \"sky\": str} or an error.",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"}},
                       "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "ledger",
        "description": "Account balance by ID. Returns {\"account\": str, \"balance_eur\": number}.",
        "parameters": {"type": "object",
                       "properties": {"account": {"type": "string"}},
                       "required": ["account"]}}},
]


def calc(expr):
    allowed = set("0123456789+-*/(). ")
    if not set(expr) <= allowed:
        return {"error": "invalid expression"}
    return {"result": eval(expr)}  # noqa: S307 — allowlist above


def exec_tool(name, args, ep_state):
    if name == "calculator":
        return calc(str(args.get("expr", "")))
    if name == "get_weather":
        # deterministic per-episode flake: 1st call errors, retry succeeds
        ep_state["weather_calls"] = ep_state.get("weather_calls", 0) + 1
        if ep_state["weather_calls"] == 1:
            return {"error": "transient upstream timeout, please retry"}
        return {"temp_c": 21, "sky": "clear"}
    if name == "ledger":
        data = {"A": 1483.50, "B": 927.25}
        acc = str(args.get("account", "")).strip().upper()
        if acc in data:
            return {"account": acc, "balance_eur": data[acc]}
        return {"error": f"unknown account {acc!r} (known: A, B)"}
    return {"error": f"unknown tool {name}"}


TASKS = {
    "T1": {
        "prompt": ("Use the calculator tool to compute 17*23 and 384/16 "
                   "(two separate calls). Then reply with the SUM of both "
                   "results alone on the last line."),
        "check": lambda txt: txt.strip().endswith("415"),
        "tools": ["calculator"],
    },
    "T2": {
        "prompt": ("What is the current temperature in Rome? Use the "
                   "get_weather tool. If it errors, diagnose and retry with "
                   "the same arguments. End your reply with the temperature "
                   "in celsius alone on the last line."),
        "check": lambda txt: txt.strip().endswith("21"),
        "tools": ["get_weather"],
    },
    "T3": {
        "prompt": ("Query the ledger for accounts A and B (two calls), then "
                   "reply with the DIFFERENCE A minus B in euros alone on "
                   "the last line."),
        "check": lambda txt: txt.strip().endswith("556.25"),
        "tools": ["ledger"],
    },
}

CELLS = [
    ("balanced", "off"), ("balanced", "low"), ("balanced", "medium"),
    ("balanced", "xhigh"), ("coding", None),
]


def run_episode(task_id, recipe, effort, rep):
    task = TASKS[task_id]
    tools = [t for t in TOOLS if t["function"]["name"] in task["tools"]]
    msgs = [{"role": "user", "content": task["prompt"]}]
    ep_state = {}
    trace = []
    total_comp = 0
    empty_answers = 0
    t0 = time.time()
    outcome = "incomplete"
    for turn in range(MAX_TURNS):
        body = {"model": f"Qwen38-27B-{recipe}", "messages": msgs,
                "tools": tools, "temperature": 0.0, "max_tokens": MAXTOK}
        if effort:
            body["chat_template_kwargs"] = {"reasoning_effort": effort}
        last = None
        for attempt in range(8):   # router swap churn (models-max 1)
            try:
                r = requests.post(f"http://{HOST}/v1/chat/completions", json=body,
                                  timeout=180)
                r.raise_for_status()
                break
            except requests.HTTPError as e:
                last = e
                if e.response is not None and e.response.status_code < 500:
                    raise
                time.sleep(3.0 * (attempt + 1))
            except (requests.ConnectionError, requests.Timeout) as e:
                last = e
                time.sleep(3.0 * (attempt + 1))
        else:
            raise last
        d = r.json()
        ch = d["choices"][0]
        m = ch.get("message", {})
        total_comp += d.get("usage", {}).get("completion_tokens", 0)
        tcs = m.get("tool_calls") or []
        content = m.get("content") or ""
        if not tcs and not content.strip():
            empty_answers += 1
        trace.append({"turn": turn, "tool_calls": [t["function"]["name"] for t in tcs],
                      "finish": ch.get("finish_reason"), "content_len": len(content)})
        if tcs:
            msgs.append({"role": "assistant", "content": content,
                         "reasoning_content": m.get("reasoning_content") or "",
                         "tool_calls": tcs})
            for tc in tcs:
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                res = exec_tool(tc["function"]["name"], args, ep_state)
                msgs.append({"role": "tool",
                             "content": json.dumps(res)})
            continue
        # final answer turn
        msgs.append({"role": "assistant", "content": content})
        outcome = "success" if task["check"](content) else "wrong_answer"
        break
    wall = time.time() - t0
    return {"outcome": outcome, "turns": len(trace), "total_comp": total_comp,
            "empty_answers": empty_answers, "wall": round(wall, 1),
            "tool_calls": sum(len(t["tool_calls"]) for t in trace),
            "retries": ep_state.get("weather_calls", 0) - 1 if task_id == "T2" else 0,
            "trace": trace}


FIELDS = ["cell", "recipe", "effort", "task", "rep", "outcome", "turns",
          "tool_calls", "retries", "total_comp_tokens", "empty_answer_turns",
          "wall_s", "ts"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/e3-agentic.csv")
    ap.add_argument("--cells", default="all")
    ap.add_argument("--tasks", default="T1,T2,T3")
    args = ap.parse_args()

    os.makedirs("results/e3-episodes", exist_ok=True)
    cells = CELLS if args.cells == "all" else [
        tuple(c.split("@")) if "@" in c else (c, None) for c in args.cells.split(",")]

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for r in csv.DictReader(fh, fieldnames=FIELDS):
                if not r["rep"].isdigit():   # skip the stray header row
                    continue
                done.add((r["recipe"], r["effort"], r["task"], int(r["rep"])))

    header_needed = not os.path.exists(args.out)
    fh = open(args.out, "a", newline="", buffering=1)
    wr = csv.DictWriter(fh, fieldnames=FIELDS)
    if header_needed:
        wr.writeheader()

    for recipe, effort in cells:
        cell = f"{recipe}@{effort}" if effort else recipe
        for task_id in args.tasks.split(","):
            for rep in range(2):
                if (recipe, effort, task_id, rep) in done:
                    continue
                ep = run_episode(task_id, recipe, effort, rep)
                row = {"cell": cell, "recipe": recipe, "effort": effort or "-",
                       "task": task_id, "rep": rep, "outcome": ep["outcome"],
                       "turns": ep["turns"], "tool_calls": ep["tool_calls"],
                       "retries": ep["retries"],
                       "total_comp_tokens": ep["total_comp"],
                       "empty_answer_turns": ep["empty_answers"],
                       "wall_s": ep["wall"],
                       "ts": time.strftime("%H:%M:%S")}
                wr.writerow(row)
                with open(f"results/e3-episodes/{cell}-{task_id}-{rep}.json", "w") as tf:
                    json.dump(ep, tf, indent=1)
                print(f"[{row['ts']}] {cell:16} {task_id} r{rep} -> "
                      f"{ep['outcome']:12} turns={ep['turns']} tools={ep['tool_calls']} "
                      f"tok={ep['total_comp']:5} empty={ep['empty_answers']} "
                      f"wall={ep['wall']}s", flush=True)
    fh.close()
    print("e3 complete")


if __name__ == "__main__":
    main()
