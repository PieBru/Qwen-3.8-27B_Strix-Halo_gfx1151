#!/bin/bash
# Unified Qwen3.8-27B + DFlash2 spec-decode launcher (strix-halo-vulkan fork).
#
# Defaults encode the config-research winners (README "Recommended configs (per goal)"):
# f16 KV everywhere, --spec-draft-n-max 6, -b/-ub 4096, -t 16 -tb 32, mlock'd weights.
#
# Usage:
#   ./run_llama-server.sh --goal max-quality       # Q8 @ 192k  — final answers, code
#   ./run_llama-server.sh --goal balanced-quality  # Q8 @ 64k   — correctness first
#   ./run_llama-server.sh --goal balanced-speed    # Q6 @ 64k   — daily driver (default)
#   ./run_llama-server.sh --goal max-speed         # Q6 @ 64k, trim --ctx for more t/s
# Overrides (any preset field can be overridden individually):
#   --model q4|q5|q6|q8   target UD quant (q6/q8 recommended; q5 legacy, q4 fetchable)
#   --ctx N               context size (SSM state is tiny; decode cost grows with it)
#   --nmax N              --spec-draft-n-max (6-7 plateau; 4 clearly worse)
#   --kv f16|q8_0         target+draft KV type (f16 measured FASTER and is higher fidelity)
#   --port N              listen port (default 8081)
#   --draft FILE          draft GGUF (default Qwen3.8-27B-DFlash2-Q8_0.gguf)
#   --no-mlock            don't pin weights in RAM (mlock needs memlock unlimited,
#                         see README "Lessons learned"; without it zram can eat ~30% tg)
#   --dry-run             print the resolved command, don't exec
set -euo pipefail
cd "$(dirname "$0")"

GOAL=""; MODEL=""; CTX=65536; NMAX=6; KV=f16; PORT=8081
DRAFT=Qwen3.8-27B-DFlash2-Q8_0.gguf; MLOCK=1; DRY=0
CTX_SET=0; MODEL_SET=0

while [ $# -gt 0 ]; do case "$1" in
  --goal) GOAL=$2; shift 2;;
  --model) MODEL=$2; MODEL_SET=1; shift 2;;
  --ctx) CTX=$2; CTX_SET=1; shift 2;;
  --nmax) NMAX=$2; shift 2;;
  --kv) KV=$2; shift 2;;
  --port) PORT=$2; shift 2;;
  --draft) DRAFT=$2; shift 2;;
  --no-mlock) MLOCK=0; shift;;
  --dry-run) DRY=1; shift;;
  -h|--help) grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "error: unknown argument: $1 (see --help)" >&2; exit 1;;
esac; done

case "$GOAL" in
  max-quality)      MODEL=q8; [ "$CTX_SET" = 0 ] && CTX=196608;;
  balanced-quality) MODEL=q8; [ "$CTX_SET" = 0 ] && CTX=65536;;
  balanced-speed)   MODEL=q6; [ "$CTX_SET" = 0 ] && CTX=65536;;
  max-speed)        MODEL=q6; [ "$CTX_SET" = 0 ] && CTX=65536;;   # same config: 16k-64k measured flat; trim --ctx only to fit the task
  "") MODEL=${MODEL:-q6};;                       # bare invocation = balanced-speed
  *) echo "error: --goal must be max-quality|balanced-quality|balanced-speed|max-speed" >&2; exit 1;;
esac

TARGET=Qwen3.8-27B-UD-${MODEL^^}_K_XL.gguf
[ -f "$TARGET" ] || { echo "error: target $TARGET not found (see README Models for the pinned download)" >&2; exit 1; }
[ -f "$DRAFT"  ] || { echo "error: draft $DRAFT not found" >&2; exit 1; }

KVARGS=()
[ "$KV" = q8_0 ] && KVARGS=(-ctk q8_0 -ctv q8_0 -ctkd q8_0 -ctvd q8_0)
MLOCKARGS=(); [ "$MLOCK" = 1 ] && MLOCKARGS=(-lm mmap+mlock)

CMD=(./llama.cpp/build-vk/bin/llama-server
  -m "$TARGET" -md "$DRAFT"
  -ngl all -ngld all -fa on "${MLOCKARGS[@]}"
  "${KVARGS[@]}"
  -c "$CTX" -np 1 -b 4096 -ub 4096 -t 16 -tb 32
  --spec-type draft-dflash --spec-draft-n-max "$NMAX"
  --chat-template-file sharp.jinja
  --jinja --host 0.0.0.0 --port "$PORT" --metrics)

echo ">> goal=${GOAL:-custom} model=$MODEL ctx=$CTX kv=$KV nmax=$NMAX mlock=$MLOCK port=$PORT"
[ "$DRY" = 1 ] && { printf '   %q' "${CMD[@]}"; echo; exit 0; }

ulimit -l unlimited 2>/dev/null || true   # no-op until limits.d allows (README lessons)
export AMD_VULKAN_ICD=RADV
exec "${CMD[@]}"
