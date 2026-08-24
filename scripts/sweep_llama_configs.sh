#!/bin/bash
# Staged config search for Qwen3.8-27B on Strix Halo (gfx1151, Vulkan fork 7b6c613).
# Design: see README "Config research" — one axis per stage, winners carried forward.
# Usage:  ./sweep_llama_configs.sh [stage]    (0|1|2|3|4|5|all, default: all)
# Output: results/sweep.csv + results/<tag>.log per config. Guards: per-server wait
# ceiling 240 s, per-curl --max-time, crash-tolerant (status column), stage ceilings.

set -u
cd "$(dirname "$0")/.."
BIN=./llama.cpp/build-vk/bin/llama-server
# build-vk's RUNPATH is a stale pre-move path (trailing ':' = CWD fallback); without
# this export the server fails to dlopen libggml-vulkan.so.0 outside its bin dir.
export LD_LIBRARY_PATH="$PWD/llama.cpp/build-vk/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
PORT=8099
RES=results; mkdir -p "$RES"
CSV=$RES/sweep.csv
DRAFT=models/Qwen3.8-27B-DFlash2-Q8_0.gguf      # fixed: only draft on disk (Q4_K_M was ~+5% but deleted)
[ -f "$CSV" ] || echo "tag,model,ctk,ctv,ctkd,ctvd,ctx,b,ub,tb,nmax,status,load_s,rss_kb,tg_ts,pp4k_ts" >> "$CSV"

# --- deterministic prompts (built once) -----------------------------------
python3 - <<'EOF' 2>/dev/null
import os
def filler(words):
    s=[]
    base=("The pipeline stages transform the representation in ways that preserve "
          "semantic content while reducing dimensional overhead across layers. ")
    while words>0:
        s.append(base); words-=21
    return "".join(s)
os.makedirs("results", exist_ok=True)
open("results/prompt_short.txt","w").write("Explain briefly why the sky is blue at sunset.\n")
open("results/prompt_4k.txt","w").write("Context notes:\n"+filler(5400)+"\n\nSummarize the key point in one sentence.\n")
open("results/prompt_16k.txt","w").write("Context notes:\n"+filler(21600)+"\n\nSummarize the key point in one sentence.\n")
EOF

srv_pid=0
cleanup(){ [ "$srv_pid" -gt 0 ] && kill -- -"$srv_pid" 2>/dev/null; sleep 2; }
trap cleanup EXIT

json_field(){ python3 -c "
import json,sys
try: print(round(json.load(sys.stdin)['timings']['$1'],2))
except Exception: print('')"; }

# run_config <tag> <model> <ctk> <ctv> <ctkd> <ctvd> <ctx> <b> <ub> <tb> <nmax> <tests>
# SWEEP_TAG_PREFIX env var prefixes the tag (e.g. r2- for a repeat pass) so CSV
# rows from re-runs stay distinguishable.
run_config(){
  local tag="${SWEEP_TAG_PREFIX:-}$1" model=$2 ctk=$3 ctv=$4 ctkd=$5 ctvd=$6 ctx=$7 b=$8 ub=$9 tb=${10} nmax=${11} tests=${12}
  local kvargs=() dkvargs=()
  [ "$ctk" != "-" ] && kvargs=(-ctk "$ctk" -ctv "$ctv")
  [ "$ctkd" != "-" ] && dkvargs=(-ctkd "$ctkd" -ctvd "$ctvd")
  local log=$RES/$tag.log
  local t0=$(date +%s)
  setsid env AMD_VULKAN_ICD=RADV $BIN -m "$model" -md "$DRAFT" \
    -ngl all -ngld all -fa on "${kvargs[@]}" "${dkvargs[@]}" \
    -c "$ctx" -np 1 -b "$b" -ub "$ub" -t 16 -tb "$tb" \
    --spec-type draft-dflash --spec-draft-n-max "$nmax" \
    --chat-template-file models/sharp.jinja --jinja --host 127.0.0.1 --port $PORT --metrics \
    > "$log" 2>&1 &
  srv_pid=$!
  local ok=""
  for i in $(seq 120); do
    sleep 2
    grep -aq 'listening on' "$log" && { ok=1; break; }
    kill -0 "$srv_pid" 2>/dev/null || break   # server died: fail fast
  done
  local load_s=$(( $(date +%s) - t0 ))
  if [ -z "$ok" ]; then
    echo "$tag,$model,$ctk,$ctv,$ctkd,$ctvd,$ctx,$b,$ub,$tb,$nmax,LOAD_FAIL($load_s),,,,," >> "$CSV"
    cleanup; srv_pid=0; return
  fi
  # NOTE: fork logs no KV lines; RSS delta across ctx sizes is the empirical measure
  # (weights+draft+compute are ctx-invariant; the delta isolates the ctx-scaling part).
  # Qwen3.8 is a hybrid SSM — expect only a few full-attn layers to scale (~B/token).
  local rss=$(awk '/VmRSS/{print $2}' /proc/$srv_pid/status 2>/dev/null)
  local tg="" pp=""
  if [[ "$tests" == *tg* ]]; then
    tg=$(curl -s --max-time 600 http://127.0.0.1:$PORT/completion -H 'Content-Type: application/json' \
      -d "{\"prompt\":\"$(cat results/prompt_short.txt | head -c 400 | tr -d '"')\",\"n_predict\":256,\"temperature\":0}" \
      | json_field predicted_per_second)
  fi
  if [[ "$tests" == *pp* ]]; then
    python3 -c "
import json,urllib.request
p=open('results/prompt_4k.txt').read()
req=urllib.request.Request('http://127.0.0.1:$PORT/completion',
  data=json.dumps({'prompt':p,'n_predict':16,'temperature':0}).encode(),
  headers={'Content-Type':'application/json'})
d=json.load(urllib.request.urlopen(req,timeout=900))
print(round(d['timings']['prompt_per_second'],1))" 2>/dev/null
  fi
  echo "$tag,$model,$ctk,$ctv,$ctkd,$ctvd,$ctx,$b,$ub,$tb,$nmax,OK,$load_s,${rss:-NA},${tg:-NA},${pp:-NA}" >> "$CSV"
  echo "  $tag: status=OK tg=$tg pp4k=$pp load=${load_s}s rss=${rss:-NA}kB" >&2
  cleanup; srv_pid=0
}

stage0(){  # capacity probe: RSS at two ctx sizes -> KV/token -> big-ctx feasibility
  for m in Q6 Q8; do
    f=Qwen3.8-27B-UD-${m}_K_XL.gguf
    run_config "s0-${m}-c8k"  "$f" q8_0 q8_0 q8_0 q8_0 8192 4096 4096 32 4 tg
    run_config "s0-${m}-c64k" "$f" q8_0 q8_0 q8_0 q8_0 65536 4096 4096 32 4 none
  done
  python3 - "$CSV" <<'EOF'
import csv,sys
rows={r['tag']:r for r in csv.DictReader(open(sys.argv[1])) if r['tag'].startswith('s0-')}
print("\n=== Stage 0 feasibility (RSS-delta KV estimate, q8_0 KV) ===")
for m in ('Q6','Q8'):
    a,b=rows.get(f's0-{m}-c8k'),rows.get(f's0-{m}-c64k')
    if not a or not b or 'NA' in (a['rss_kb'],b['rss_kb']): print(m,'missing data'); continue
    per=(int(b['rss_kb'])-int(a['rss_kb']))*1024/(65536-8192)
    print(f"{m}: ~{per:.0f} B/token -> 256k est {per*262144/2**30:.2f} GiB | RSS8k={int(a['rss_kb'])//1024}MB RSS64k={int(b['rss_kb'])//1024}MB | ctx is cheap (hybrid SSM): pick -c for the crash ceiling, not memory")
EOF
}

stage1(){  # spec-draft-n-max 3..9 (decode-dominant axis); models on argv (default "Q6 Q8"; add Q5 etc.)
  local models="${*:-Q6 Q8}"
  for m in $models; do
    local f=Qwen3.8-27B-UD-${m}_K_XL.gguf
    for n in 3 4 5 6 7 8 9; do run_config "s1-${m}-n${n}" "$f" q8_0 q8_0 q8_0 q8_0 65536 4096 4096 32 "$n" tg; done
  done
}

stage2(){  # KV types 2x2 (target q8/f16 x draft q8/f16) — pass "MODEL:NMAX" specs (default "Q6:4 Q8:4")
  local specs=${*:-"Q6:4 Q8:4"}
  for spec in $specs; do local m=${spec%%:*} n=${spec##*:}; local f=Qwen3.8-27B-UD-${m}_K_XL.gguf
    run_config "s2-${m}-kvT-q8-dkv-q8"  "$f" q8_0 q8_0 q8_0 q8_0 65536 4096 4096 32 "$n" tgpp
    run_config "s2-${m}-kvT-q8-dkv-f16" "$f" q8_0 q8_0 -     -     65536 4096 4096 32 "$n" tgpp
    run_config "s2-${m}-kvT-f16-dkv-q8" "$f" -     -     q8_0 q8_0 65536 4096 4096 32 "$n" tgpp
    run_config "s2-${m}-kvT-f16-dkv-f16" "$f" -     -     -     -     65536 4096 4096 32 "$n" tgpp
  done
}

stage3(){  # context ladder INCLUDING a 64k in-window control (pass "model ctk ctkd nmax" rows on argv;
  # optional 6th+ fields override the ctx ladder itself — use to break run-order confounds)
  for cfg in "$@"; do set -- $cfg; local m=$1 ctk=$2 ctkd=$3 n=$4 b=${5:-4096}
    local f=Qwen3.8-27B-UD-${m}_K_XL.gguf
    local ctxs="65536 131072 196608 262144"; [ $# -gt 5 ] && ctxs="${*:6}"
    for ctx in $ctxs; do
      run_config "s3-${m}-c$((ctx/1024))k" "$f" "$ctk" "$ctk" "$ctkd" "$ctkd" "$ctx" "$b" "$b" 32 "$n" tg
    done
  done
}

stage4(){  # batch/ubatch at winner (prefill axis): pass "model ctk ctkd nmax ctx" rows
  for cfg in "$@"; do set -- $cfg; local m=$1 ctk=$2 ctkd=$3 n=$4 ctx=$5
    local f=Qwen3.8-27B-UD-${m}_K_XL.gguf
    for bu in 2048 4096 8192; do run_config "s4-${m}-bu${bu}" "$f" "$ctk" "$ctk" "$ctkd" "$ctkd" "$ctx" "$bu" "$bu" 32 "$n" tgpp; done
  done
}

stage5(){  # -tb 16 vs 32 (expected parity): pass "model ctk ctkd nmax ctx bu" rows
  for cfg in "$@"; do set -- $cfg; local m=$1 ctk=$2 ctkd=$3 n=$4 ctx=$5 bu=$6
    local f=Qwen3.8-27B-UD-${m}_K_XL.gguf
    run_config "s5-${mm:-$m}-tb16" "$f" "$ctk" "$ctk" "$ctkd" "$ctkd" "$ctx" "$bu" "$bu" 16 "$n" tg
    run_config "s5-${m}-tb32" "$f" "$ctk" "$ctk" "$ctkd" "$ctkd" "$ctx" "$bu" "$bu" 32 "$n" tg
  done
}

case "${1:-all}" in
  0) stage0;;
  1) stage1 "${@:2}";;
  2) stage2 "${@:2}";;
  3) stage3 "${@:2}";;
  4) stage4 "${@:2}";;
  5) stage5 "${@:2}";;
  all) stage0; stage1; echo ">>> stage 2+: run with winners, e.g. ./sweep_llama_configs.sh 2 5 5";;
  *) echo "usage: $0 [0|1|2|3|4|5|all]"; exit 1;;
esac
