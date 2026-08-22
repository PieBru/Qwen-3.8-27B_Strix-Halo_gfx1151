#!/usr/bin/env bash
# fill_battery.sh — incremental deep-fill battery, A/B backend-agnostic.
# Reproduces the 2026-08-21 Vulkan ~160k vk::DeviceLost crash shape:
#   Q8 target + DFlash2 draft, f16 KV, -c 262144, -b/-ub 4096, fa on, 16t/32tb.
# Usage: ./fill_battery.sh <label> <llama-server-binary> [port]
# Env: SPEC=dflash2|none|mtp  (draft path; default dflash2 — our production shape)
#      TARGET=positions       (stop early; default 176000)
#      UB=microbatch           (default 4096; fork issue #9's 491k run used 1024)
# Drives llama-server /completion with 16k-token chunks, KV-prefix cached
# (incremental prefill), logging cum positions + prefill t/s per chunk.
set -u
LABEL=${1:?label}
BIN=${2:?llama-server binary}
PORT=${3:-8098}
SPEC=${SPEC:-dflash2}
UB=${UB:-4096}
REPO=$(cd "$(dirname "$0")" && pwd)
CHUNK="$REPO/results/prompt_16k.txt"
TARGET=${TARGET:-176000}
LOG="$REPO/results/hip-$LABEL-server.log"
CSV="$REPO/results/hip-$LABEL-fill.csv"

# guard: chunk file must exist and be big enough (~16k tokens)
[ -s "$CHUNK" ] || { echo "FATAL: missing $CHUNK"; exit 1; }

SPECARGS=()
case "$SPEC" in
  dflash2) SPECARGS=( -md "$REPO/Qwen3.8-27B-DFlash2-Q8_0.gguf" \
                      --spec-type draft-dflash --spec-draft-n-max 6 ) ;;
  mtp)     SPECARGS=( --spec-type draft-mtp --spec-draft-n-max 6 ) ;;
  none)    SPECARGS=() ;;
  *) echo "FATAL: unknown SPEC=$SPEC"; exit 1 ;;
esac

"$BIN" \
  -m "$REPO/Qwen3.8-27B-UD-Q8_K_XL.gguf" \
  "${SPECARGS[@]}" \
  -ngl all -ngld all -fa on \
  -c 262144 -np 1 -b 4096 -ub "$UB" -t 16 -tb 32 \
  --jinja --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT

# wait for readiness (ceiling 240 s)
for i in $(seq 1 48); do
  sleep 5
  curl -s --max-time 3 "127.0.0.1:$PORT/health" | rg -q '"status":"ok"' && break
  kill -0 $SRV 2>/dev/null || { echo "SERVER DIED AT BOOT (see $LOG)"; exit 1; }
done
curl -s --max-time 3 "127.0.0.1:$PORT/health" | rg -q '"status":"ok"' || { echo "SERVER NEVER READY"; exit 1; }
echo "server up (pid $SRV), battery start $(date -Is)"

python3 - "$PORT" "$CHUNK" "$TARGET" "$CSV" <<'EOF'
import json, sys, time, urllib.request, urllib.error

port, chunk_path, target, csv_path = sys.argv[1:5]
chunk = open(chunk_path, 'r', encoding='utf-8').read()
full = ""
if len(chunk.split()) < 5000:
    print("FATAL: chunk file too small"); sys.exit(1)

url = f"http://127.0.0.1:{port}/completion"
filled = 0   # REAL positions: sum of prompt_n deltas (newly prefilled per call)
rows = []
it = 0
with open(csv_path, 'w') as f:
    f.write("chunk,cum_filled,prompt_n,prompt_ms,prefill_tps\n")
    while filled < int(target) and it < 24:
        it += 1
        full += chunk   # GROWING prompt: server KV-prefix-caches the old part,
                        # prefills only the delta -> true incremental fill
        body = json.dumps({"prompt": full, "n_predict": 4, "temperature": 0,
                           "cache_prompt": True}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=2400) as r:
                d = json.loads(r.read())
        except Exception as e:
            print(f"REQUEST FAILED at filled={filled}: {e}")
            print("VERDICT: CRASH (server unreachable mid-fill)")
            sys.exit(2)
        t = d.get("timings", {})
        pn, pms = t.get("prompt_n", 0), t.get("prompt_ms", 0)
        if pn < 1000 and it > 1:
            print(f"GUARD: prompt_n={pn} unexpectedly small - prefix cache ate the chunk; aborting (invalid battery)")
            sys.exit(3)
        filled += pn
        tps = pn / pms * 1000 if pms else 0
        f.write(f"{it},{filled},{pn},{pms:.0f},{tps:.1f}\n"); f.flush()
        print(f"chunk {it:2d}: +{pn:6d} -> filled={filled:7d}  prefill={tps:7.1f} t/s ({pms/1000:5.1f}s)")
    else:
        if filled >= int(target):
            print(f"VERDICT: SURVIVED to {filled} filled positions")
EOF
rc=$?
echo "battery rc=$rc $(date -Is)"
if ! kill -0 $SRV 2>/dev/null; then
  echo "VERDICT: SERVER DIED during battery (see $LOG tail below)"
  tail -5 "$LOG"
else
  echo "server still alive after battery"
fi
exit $rc
