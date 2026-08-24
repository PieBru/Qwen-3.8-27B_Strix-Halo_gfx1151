#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""e5 threads-batch & concurrency battery — README 'Threads & 2-client' chapter data.

Question: with full GPU offload (-ngl all), what do -t/-tb = 1..2 cost vs the
production -t 16 -tb 32, when TWO concurrent clients hit the server (-np 2)?

Matrix (all: Q6 + DFlash2 draft, f16 KV, -c 131072 split 2x65536 slots, fa on):
  t16-tb32 (production baseline), t1-tb1, t1-tb2, t2-tb1, t2-tb2
Load: 2 concurrent client threads x 4 requests each; every request re-prefills
~4k tokens (cache_prompt=false) then decodes 128 (ignore_eos) — identical
workload per client, interleaved starts.
Metrics per request: prefill t/s, decode t/s, wall (server timings + client
wall). Aggregates per config: per-client means + combined decode throughput.

Evidence: results/e5-threads.csv + results/e5-threads-server-<cfg>.log
Usage: nohup uv run --with requests python3 e5_threads_battery.py &
"""
import csv
import statistics as st
import subprocess
import threading
import time

import requests

PORT = 8098
HOST = f"http://127.0.0.1:{PORT}"
BIN = "./llama.cpp/build-vk/bin/llama-server"
PROMPT = open("results/prompt_4k.txt", encoding="utf-8").read()
CONFIGS = [("t16-tb32", 16, 32), ("t1-tb1", 1, 1), ("t1-tb2", 1, 2),
           ("t2-tb1", 2, 1), ("t2-tb2", 2, 2)]
CLIENTS = 2
REQS = 4
CSV = "results/e5-threads.csv"


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


def one_request(client_id, req_id, out):
    body = {"prompt": f"(client {client_id}, request {req_id})\n" + PROMPT,
            "n_predict": 128, "temperature": 0, "cache_prompt": False,
            "ignore_eos": True}
    t0 = time.time()
    r = requests.post(f"{HOST}/completion", json=body, timeout=1200)
    wall = time.time() - t0
    r.raise_for_status()
    d = r.json()
    t = d.get("timings", {})
    pn = t.get("prompt_n", 0) or 0
    pms = t.get("prompt_ms", 0) or 0
    dn = t.get("predicted_n", 0) or 0
    dms = t.get("predicted_ms", 0) or 0
    out.append({"client": client_id, "req": req_id, "prompt_n": pn,
                "prefill_tps": pn / pms * 1000 if pms else 0,
                "decode_n": dn,
                "decode_tps": dn / dms * 1000 if dms else 0,
                "wall_s": round(wall, 1),
                "ttfb_note": ""})


def run_config(cfg, t, tb, wr):
    log = open(f"results/e5-threads-server-{cfg}.log", "w")
    srv = subprocess.Popen(
        [BIN, "-m", "models/Qwen3.8-27B-UD-Q6_K_XL.gguf",
         "-md", "models/Qwen3.8-27B-DFlash2-Q8_0.gguf",
         "--spec-type", "draft-dflash", "--spec-draft-n-max", "6",
         "-ngl", "all", "-ngld", "all", "-fa", "on",
         "-c", "131072", "-np", "2", "-b", "4096", "-ub", "4096",
         "-t", str(t), "-tb", str(tb),
         "--jinja", "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=log, stderr=subprocess.STDOUT)
    try:
        wait_health(srv)
        print(f"[{cfg}] server up (t={t} tb={tb}, np=2)", flush=True)
        out = []
        threads = []
        for c in range(CLIENTS):
            def worker(cid=c):
                for i in range(REQS):
                    one_request(cid, i, out)
                    time.sleep(0.5)
            th = threading.Thread(target=worker)
            threads.append(th)
        t0 = time.time()
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        total_wall = time.time() - t0
        for row in out:
            row.update({"cfg": cfg, "t": t, "tb": tb})
            wr.writerow(row)
        combined = sum(r["decode_tps"] for r in out) / REQS  # avg per-round sum of 2 clients
        print(f"[{cfg}] done in {total_wall:.0f}s | prefill mean/client "
              f"{st.mean(r['prefill_tps'] for r in out):.0f} t/s | decode mean/client "
              f"{st.mean(r['decode_tps'] for r in out):.1f} t/s | "
              f"combined decode ~{sum(r['decode_tps'] for r in out[:REQS]):.1f} t/s",
              flush=True)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=20)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()


def main():
    header_needed = True
    import os
    if os.path.exists(CSV):
        header_needed = False
    fh = open(CSV, "a", newline="", buffering=1)
    wr = csv.DictWriter(fh, fieldnames=["cfg", "t", "tb", "client", "req",
                                        "prompt_n", "prefill_tps", "decode_n",
                                        "decode_tps", "wall_s", "ttfb_note"])
    if header_needed:
        wr.writeheader()
    for cfg, t, tb in CONFIGS:
        run_config(cfg, t, tb, wr)
    fh.close()
    print("e5 complete", flush=True)


if __name__ == "__main__":
    main()
