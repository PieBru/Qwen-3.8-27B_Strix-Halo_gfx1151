#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""e4 fill-decode decay battery — re-measures the README fill-decay table.

Why: the adversarial audit (2026-08-23) flagged that the original decode-vs-
filled table (24.7 -> 9.8 t/s) had no committed raw logs. This battery
re-measures it end-to-end AND extends past 128k for the first time under
amdgpu.lockup_timeout=-1 (the old run's table stopped at the death row).

Method: standalone llama-server (Q8 + DFlash2 draft, f16 KV, -c 262144,
-b/-ub 4096, fa on — identical shape to fill_battery.sh), growing 16k-token
chunk fills via cache_prompt, and after each chunk a 256-token decode probe
(temp 0). Decode t/s parsed from the server's own timings field.
The router on :8080 stays untouched (agent session alive); minor GPU-sharing
with it is possible and noted per-row via wall vs server-internal time.

Evidence: results/e4-decay.csv (+ server log results/e4-decay-server.log)
Usage: nohup uv run --with requests python3 e4_decay_battery.py &
"""
import json
import subprocess
import time

import requests

PORT = 8098
HOST = f"http://127.0.0.1:{PORT}"
MODEL_ARGS = [
    "./llama.cpp/build-vk/bin/llama-server",
    "-m", "./Qwen3.8-27B-UD-Q8_K_XL.gguf",
    "-md", "./Qwen3.8-27B-DFlash2-Q8_0.gguf",
    "--spec-type", "draft-dflash", "--spec-draft-n-max", "6",
    "-ngl", "all", "-ngld", "all", "-fa", "on",
    "-c", "262144", "-np", "1", "-b", "4096", "-ub", "4096", "-t", "16", "-tb", "32",
    "--jinja", "--host", "127.0.0.1", "--port", str(PORT),
]
CHUNK = open("results/prompt_16k.txt", encoding="utf-8").read()
# Probe suffix: forces a real ~256-token generation every time (bare filler
# continuation EOSes after ~50 tokens -> invalid t/s samples). Fixed text so
# the prefix cache still hits the whole filled part.
PROBE_SUFFIX = ("\n\nIgnoring the text above, write a vivid 300-word story "
                "about a lighthouse keeper. Do not stop early.")
CSV = "results/e4-decay.csv"
LOG = "results/e4-decay-server.log"


def wait_health(proc, ceiling_s=300):
    t0 = time.time()
    while time.time() - t0 < ceiling_s:
        if proc.poll() is not None:
            raise RuntimeError("server died during load")
        try:
            if requests.get(f"{HOST}/health", timeout=3).json().get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("server never became healthy")


def timings_of(d):
    """Normalize /completion timings across field-name variants."""
    t = d.get("timings", {}) or {}
    pn = t.get("prompt_n", 0) or 0
    pms = t.get("prompt_ms", 0) or 0
    dn = t.get("predicted_n", t.get("n_tokens", 0)) or 0
    dms = t.get("predicted_ms", t.get("eval_ms", 0)) or 0
    dtps = t.get("predicted_per_second") or (dn / dms * 1000 if dms else 0)
    return pn, pms, dn, dms, dtps


def complete(prompt, n_predict, probe=False):
    body = {"prompt": prompt, "n_predict": n_predict, "temperature": 0,
            "cache_prompt": True}
    if probe:
        body["ignore_eos"] = True   # deep-filler continuations EOS at 1 token
    t0 = time.time()
    r = requests.post(f"{HOST}/completion", json=body, timeout=1200)
    wall = time.time() - t0
    r.raise_for_status()
    return r.json(), wall


def main():
    srv = subprocess.Popen(MODEL_ARGS, stdout=open(LOG, "w"), stderr=subprocess.STDOUT)
    try:
        wait_health(srv)
        print(f"server up (pid {srv.pid})", flush=True)

        with open(CSV, "w") as f:
            f.write("chunk,filled,prefill_n,prefill_ms,prefill_tps,"
                    "decode_n,decode_ms,decode_tps,probe_wall_s,ts\n")
            full = ""
            filled = 0
            # fresh-slot decode probe before any fill (same probe shape)
            d, wall = complete(PROBE_SUFFIX.strip(), 256, probe=True)
            pn, pms, dn, dms, dtps = timings_of(d)
            f.write(f"0,0,0,0,0,{dn},{dms:.0f},{dtps:.1f},{wall:.1f},"
                    f"{time.strftime('%H:%M:%S')}\n")
            print(f"fresh: decode {dtps:.1f} t/s (n={dn})", flush=True)

            for it in range(1, 14):  # 13 chunks -> ~254k
                full += CHUNK
                d, wall = complete(full, 4)   # fill (prefill) step
                pn, pms, _, _, _ = timings_of(d)
                filled += pn
                prefill_tps = pn / pms * 1000 if pms else 0
                # decode probe at this depth (suffix re-prefills ~20 tokens)
                d2, wall2 = complete(full + PROBE_SUFFIX, 256, probe=True)
                _, _, dn, dms, decode_tps = timings_of(d2)
                f.write(f"{it},{filled},{pn},{pms:.0f},{prefill_tps:.1f},"
                        f"{dn},{dms:.0f},{decode_tps:.1f},{wall2:.1f},"
                        f"{time.strftime('%H:%M:%S')}\n")
                f.flush()
                print(f"chunk {it:2d}: filled={filled:7d} prefill={prefill_tps:7.1f} t/s "
                      f"decode={decode_tps:5.1f} t/s (n={dn})", flush=True)
            print("VERDICT: SURVIVED + full decay curve", flush=True)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=20)
        except subprocess.TimeoutExpired:
            srv.kill()
        print("server stopped", flush=True)


if __name__ == "__main__":
    main()
