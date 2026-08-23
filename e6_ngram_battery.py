#!/usr/bin/env python3
"""e6 ngram-replay battery — can ngram-map-k4v lift DFlash2 on OUR APU?

Pre-registered (2026-08-23, before running):
  Source: lukaLLM's RTX PRO 6000 study (reddit 1vvncyh) — ngram-map-k4v on
  top of draft-dflash gives 4.68x vs 2.79x on an 18-turn cumulative coding
  session (build phase), while single-shot is flat (+1.2%) and prose -30%.
  Untested cell on a bandwidth-bound APU (ours).

  Arms (standalone servers, balanced shape: Q6+DFlash2 draft, f16 KV,
  -c 131072 -np 1, fa on, -t 16 -tb 32):
    dflash6   : draft-dflash n-max 6              (production baseline)
    dflash6k4v: draft-dflash,ngram-map-k4v n-max 6 (their winning stack)
    dflash5k4v: draft-draft,ngram-map-k4v n-max 5  (their rec width)

  Workload: 9-turn cumulative build of one Python file (grows ~1-2k tokens
  per turn, each turn re-emits prior file content = the replay regime), then
  1 read-only "show the complete file" turn (their turn-10 class, ~fully
  draftable). Greedy temp 0, n_predict 900/turn (1200 for regen), natural
  tool-free. cache_prompt True (cumulative conversation reuses KV).

  Metrics per turn: server decode t/s + prompt_n; per arm: mean build t/s,
  regen t/s, totals. Journal-acceptance read post-hoc from server logs.

  ADOPT RULE (pre-registered): recommend k4v for the coding recipe iff
  build-phase mean t/s gain >= +15% AND no turn regresses > 10% vs dflash6.

Evidence: results/e6-ngram.csv, results/e6-ngram-server-<arm>.log
Usage: nohup uv run --with requests python3 e6_ngram_battery.py &
"""
import csv
import subprocess
import time

import requests

PORT = 8098
HOST = f"http://127.0.0.1:{PORT}"
BIN = "./llama.cpp/build-vk/bin/llama-server"
ARMS = [("dflash6", "draft-dflash", 6),
        ("dflash6k4v", "draft-dflash,ngram-map-k4v", 6),
        ("dflash5k4v", "draft-dflash,ngram-map-k4v", 5)]
CSV = "results/e6-ngram.csv"

SYSTEM = ("You are a careful Python developer. We build ONE file, "
          "app.py, incrementally. When asked to update, output the COMPLETE "
          "updated file in one code block, no commentary outside it.")

TURNS = [
    "Create app.py: a minimal Gradio chat app that echoes the user message.",
    "Add a system-prompt text field next to the input.",
    "Add a temperature slider (0 to 2, default 0.7).",
    "Add a model-name dropdown with three fixed choices.",
    "Add a Clear button that empties the conversation state.",
    "Persist the last 10 exchanges to chatlog.jsonl on every send.",
    "Add try/except around the echo call; show errors in the UI.",
    "Add a title and a short description paragraph at the top.",
    "Add a footer showing the app version, v0.9.",
]
REGEN = "Show me the complete final app.py, unchanged, in one code block."


def wait_health(proc, ceiling_s=300):
    t0 = time.time()
    while time.time() - t0 < ceiling_s:
        if proc.poll() is not None:
            raise RuntimeError("server died during load")
        try:
            if requests.get(f"{HOST}/health", timeout=3).json().get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("server never healthy")


def chat_turn(messages, n_predict):
    body = {"messages": messages, "n_predict": n_predict, "temperature": 0,
            "cache_prompt": True}
    t0 = time.time()
    r = requests.post(f"{HOST}/v1/chat/completions", json=body, timeout=330)
    wall = time.time() - t0
    r.raise_for_status()
    d = r.json()
    u = d.get("usage", {})
    t = d.get("timings", {})
    return {"content": d["choices"][0]["message"].get("content") or "",
            "completion": u.get("completion_tokens", 0),
            "prompt_tok": u.get("prompt_tokens", 0),
            "tps": t.get("predicted_per_second") or 0,
            "prefill_n": t.get("prompt_n", 0),
            "wall": round(wall, 1)}


def run_arm(arm, spec, nmax, wr):
    log = open(f"results/e6-ngram-server-{arm}.log", "w")
    srv = subprocess.Popen(
        [BIN, "-m", "./Qwen3.8-27B-UD-Q6_K_XL.gguf",
         "-md", "./Qwen3.8-27B-DFlash2-Q8_0.gguf",
         "--spec-type", spec, "--spec-draft-n-max", str(nmax),
         "-ngl", "all", "-ngld", "all", "-fa", "on",
         "-c", "131072", "-np", "1", "-b", "4096", "-ub", "4096",
         "-t", "16", "-tb", "32",
         "--jinja", "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=log, stderr=subprocess.STDOUT)
    try:
        wait_health(srv)
        print(f"[{arm}] up ({spec} n={nmax})", flush=True)
        messages = [{"role": "system", "content": SYSTEM}]
        rows = []
        for i, turn in enumerate(TURNS + [REGEN]):
            is_regen = i == len(TURNS)
            messages.append({"role": "user", "content": turn})
            res = chat_turn(messages, 1200 if is_regen else 900)
            messages.append({"role": "assistant", "content": res["content"]})
            row = {"arm": arm, "turn": i, "phase": "regen" if is_regen else "build",
                   "prompt_tok": res["prompt_tok"], "completion_tok": res["completion"],
                   "decode_tps": round(res["tps"], 1), "wall_s": res["wall"],
                   "ts": time.strftime("%H:%M:%S")}
            rows.append(row)
            wr.writerow(row)
            print(f"[{arm}] turn {i+1:2d} {'(REGEN)' if is_regen else '       '} "
                  f"prompt={res['prompt_tok']:6} gen={res['completion']:5} "
                  f"decode={res['tps']:6.1f} t/s wall={res['wall']:5.0f}s", flush=True)
        build = [r for r in rows if r["phase"] == "build"]
        regen = [r for r in rows if r["phase"] == "regen"][0]
        mean_build = sum(r["decode_tps"] for r in build) / len(build)
        print(f"[{arm}] MEAN build decode {mean_build:.1f} t/s | regen {regen['decode_tps']:.1f} t/s",
              flush=True)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=20)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()


def main():
    import os
    header_needed = not os.path.exists(CSV)
    fh = open(CSV, "a", newline="", buffering=1)
    wr = csv.DictWriter(fh, fieldnames=["arm", "turn", "phase", "prompt_tok",
                                        "completion_tok", "decode_tps", "wall_s", "ts"])
    if header_needed:
        wr.writeheader()
    for arm, spec, nmax in ARMS:
        run_arm(arm, spec, nmax, wr)
    fh.close()
    print("e6 complete", flush=True)


if __name__ == "__main__":
    main()
