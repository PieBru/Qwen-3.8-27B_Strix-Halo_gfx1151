#!/bin/bash
# Unified Qwen3.8-27B + DFlash2 spec-decode launcher (strix-halo-vulkan fork).
#
# Defaults encode the config-research winners (README "Recommended configs (per goal)"):
# f16 KV everywhere, --spec-draft-n-max 6, -b/-ub 4096, -t 16 -tb 32, mlock'd weights,
# sampling default --presence-penalty 0.0 only. repeat-penalty is NOT served:
# it collapsed DFlash2 acceptance (0.647->0.450) and cost 23-28% decode t/s on
# every spec recipe (README lessons #9); send it per-request only when
# repetition actually bites.
#
# Usage:
#   ./run_llama-server.sh --goal max-quality       # Q8 @ 192k  — final answers, code
#   ./run_llama-server.sh --goal balanced-quality  # Q8 @ 64k   — correctness first
#   ./run_llama-server.sh --goal balanced-speed    # Q6 @ 64k   — daily driver (default)
#   ./run_llama-server.sh --goal max-speed         # Q6 @ 64k, trim --ctx for more t/s
# Overrides (any preset field can be overridden individually):
#   --model q5|q6|q8    target UD quant (q6/q8 recommended, q5 = turbo;
#                         q4 evaluated 2026-08-21 and dropped — see README Models)
#   --ctx N               context size (SSM state is tiny; allocation measured flat 64k-256k on a quiet box)
#   --nmax N              --spec-draft-n-max (6-7 plateau; 4 clearly worse);
#                         single-model mode only — with --router it's an error:
#                         spec keys live per-recipe in models.ini (the router CLI
#                         overlays every section, so a shared --spec-* would
#                         override each recipe's own key — server-models.cpp:551)
#   --kv f16|q8_0         target+draft KV type (f16 measured FASTER and is higher fidelity)
#   --port N              listen port (default 8081)
#   --draft FILE          draft GGUF (default Qwen3.8-27B-DFlash2-Q8_0.gguf)
#   --no-mlock            don't pin weights in RAM (mlock needs memlock unlimited,
#                         see README "Lessons learned"; without it zram can eat ~30% tg)
#   --models-max N        router: max models resident at once (default 1; every
#                         recipe is 20-31 GB of weights + draft mlock'd — 2+
#                         resident exhausted memory and hard-hung the whole box,
#                         ssh included; 2026-08-21, models-max 5 → 1)
#   --router               serve ALL recipes from models.ini via llama-server router
#                         mode (names: Qwen38-27B-<QUANT>-<CTX>-<ROLE>, e.g.
#                         Qwen38-27B-Q6-65K-fast; old short names stay valid as
#                         aliases via LLAMA_ARG_ALIAS in models.ini)
#   --dry-run             print the resolved command, don't exec
set -euo pipefail
cd "$(dirname "$0")"

GOAL=""; MODEL=""; CTX=65536; NMAX=6; KV=f16; PORT=8081; ROUTER=0; MMAX=1
NMAX_SET=0
DRAFT=Qwen3.8-27B-DFlash2-Q8_0.gguf; MLOCK=1; DRY=0
CTX_SET=0; MODEL_SET=0

while [ $# -gt 0 ]; do case "$1" in
  --goal) GOAL=$2; shift 2;;
  --router) ROUTER=1; shift;;
  --models-max) MMAX=$2; shift 2;;
  --model) MODEL=$2; MODEL_SET=1; shift 2;;
  --ctx) CTX=$2; CTX_SET=1; shift 2;;
  --nmax) NMAX=$2; NMAX_SET=1; shift 2;;
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
  max-speed)        MODEL=q6; [ "$CTX_SET" = 0 ] && CTX=65536;;   # same config: 64k-256k measured flat; trim --ctx only to fit the task
  "") MODEL=${MODEL:-q6};;                       # bare invocation = balanced-speed
  *) echo "error: --goal must be max-quality|balanced-quality|balanced-speed|max-speed" >&2; exit 1;;
esac

KVARGS=()
[ "$KV" = q8_0 ] && KVARGS=(-ctk q8_0 -ctv q8_0 -ctkd q8_0 -ctvd q8_0)
MLOCKARGS=(); [ "$MLOCK" = 1 ] && MLOCKARGS=(-lm mmap+mlock)

if [ "$ROUTER" = 1 ]; then
  # Router mode: every recipe's shared flags on the CLI; models.ini sections carry
  # ONLY per-recipe keys (weights file + ctx + n-max + old-name alias).
  # Names clients use: Qwen38-27B-<QUANT>-<CTX>-<ROLE> (e.g. Qwen38-27B-Q6-65K-fast).
  #
  # Spec/draft keys are NOT here on purpose: the router overlays its own CLI args
  # onto every section (fork's server-models.cpp merge), so a shared
  # --spec-type/--spec-draft-n-max/-md would clobber each recipe's own key —
  # turbo's n-max 5 never actually applied while they lived here. They live
  # per-section in models.ini now; the vision recipe pins spec-type = none.
  [ "$NMAX_SET" = 0 ] || { echo "error: --nmax is single-model mode only; edit models.ini per-recipe spec-draft-n-max" >&2; exit 1; }
  [ -f models.ini ] || { echo "error: models.ini not found next to this script" >&2; exit 1; }
  # Router mode also scans the HF cache (~/.cache/huggingface) for servable models;
  # pin LLAMA_CACHE to an empty dir so ONLY the models.ini recipes are served.
  mkdir -p .llama-cache
  export LLAMA_CACHE="$PWD/.llama-cache"
  CMD=(./llama.cpp/build-vk/bin/llama-server
    --models-preset models.ini --models-max "$MMAX"
    -ngl all -ngld all -fa on "${MLOCKARGS[@]}" "${KVARGS[@]}"
    -b 4096 -ub 4096 -np 1 -t 16 -tb 32
    --presence-penalty 0.0
    --chat-template-file sharp.jinja
    --jinja --host 0.0.0.0 --port "$PORT" --metrics)
  echo ">> router: recipes from models.ini on :$PORT (mmax=$MMAX kv=$KV mlock=$MLOCK pen=0.0)"
  [ "$DRY" = 1 ] && { printf '   %q' "${CMD[@]}"; echo; exit 0; }
  # build-vk's RUNPATH is a stale pre-move path; this export keeps libs resolvable.
  export LD_LIBRARY_PATH="$PWD/llama.cpp/build-vk/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export AMD_VULKAN_ICD=RADV
  exec "${CMD[@]}"
fi

TARGET=Qwen3.8-27B-UD-${MODEL^^}_K_XL.gguf
[ -f "$TARGET" ] || { echo "error: target $TARGET not found (see README Models for the unsloth repo download)" >&2; exit 1; }
[ -f "$DRAFT"  ] || { echo "error: draft $DRAFT not found" >&2; exit 1; }

CMD=(./llama.cpp/build-vk/bin/llama-server
  -m "$TARGET" -md "$DRAFT"
  -ngl all -ngld all -fa on "${MLOCKARGS[@]}"
  "${KVARGS[@]}"
  -c "$CTX" -np 1 -b 4096 -ub 4096 -t 16 -tb 32
  --presence-penalty 0.0
  --spec-type draft-dflash --spec-draft-n-max "$NMAX"
  --chat-template-file sharp.jinja
  --jinja --host 0.0.0.0 --port "$PORT" --metrics)

echo ">> goal=${GOAL:-custom} model=$MODEL ctx=$CTX kv=$KV nmax=$NMAX mlock=$MLOCK port=$PORT"
[ "$DRY" = 1 ] && { printf '   %q' "${CMD[@]}"; echo; exit 0; }

# build-vk's RUNPATH is a stale pre-move path; without this export the server
# fails to dlopen libggml-vulkan.so.0 when invoked outside its own bin dir.
export LD_LIBRARY_PATH="$PWD/llama.cpp/build-vk/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
ulimit -l unlimited 2>/dev/null || true   # no-op until limits.d allows (README lessons)
export AMD_VULKAN_ICD=RADV
exec "${CMD[@]}"
