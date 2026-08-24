#!/bin/bash
# download_models.sh — fetch every GGUF this repo needs, sha256-verified.
#
# Targets (Unsloth Dynamic K_XL) come from the unsloth repo tip as measured
# here; the DFlash2 draft comes from the z-lab repo; the vision projector
# (mmproj) lives in the unsloth repo too. Each file is verified against the
# sha256 the configs were measured with BEFORE it is installed under its
# final name (downloads land as *.part-* and are renamed only after the
# hash check), and the unsloth tip is checked for drift so a silent
# re-quant can't surprise you.
#
# Usage:
#   ./download_models.sh                 # everything: 3 targets + draft + mmproj (~73 GiB)
#   ./download_models.sh q6 draft        # just what you need (e.g. no vision, no Q8)
#   ./download_models.sh --check         # verify files already on disk, download nothing
#
# Speed: 10 parallel HTTP range requests per file (~8x a single stream on a
# typical home link; measured 106 MB/s vs 13 MB/s).
set -euo pipefail
cd "$(dirname "$0")/.."

UNSLOTH=https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main
ZLAB=https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2-GGUF/resolve/main
API_UNSLOTH=https://huggingface.co/api/models/unsloth/Qwen3.8-27B-GGUF/tree/main

declare -A WANT_SHA WANT_BYTES SRC FNAME
WANT_SHA[q8]=af36ecb6b5db;    WANT_BYTES[q8]=31457991680;   SRC[q8]=$UNSLOTH; FNAME[q8]=Qwen3.8-27B-UD-Q8_K_XL.gguf
WANT_SHA[q6]=701d8fa9ed21;    WANT_BYTES[q6]=25299061664;   SRC[q6]=$UNSLOTH; FNAME[q6]=Qwen3.8-27B-UD-Q6_K_XL.gguf
WANT_SHA[q5]=8601193d3d57;    WANT_BYTES[q5]=20876938144;   SRC[q5]=$UNSLOTH; FNAME[q5]=Qwen3.8-27B-UD-Q5_K_XL.gguf
WANT_SHA[draft]=7f1c9a31a6ed; WANT_BYTES[draft]=2056414752; SRC[draft]=$ZLAB; FNAME[draft]=Qwen3.8-27B-DFlash2-Q8_0.gguf
WANT_SHA[mmproj]=cbb841a9ee06; WANT_BYTES[mmproj]=927607488; SRC[mmproj]=$UNSLOTH; FNAME[mmproj]=mmproj-F16.gguf

NCHUNK=10

usage(){ grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
die(){ echo "error: $*" >&2; exit 1; }

verify_one(){  # <key>
  local q=$1 f=${FNAME[$1]}
  [ -f "$f" ] || { echo "$q: MISSING ($f)"; return 1; }
  local got=$(sha256sum "$f" | cut -c1-12) size=$(stat -c%s "$f")
  if [ "$got" = "${WANT_SHA[$q]}" ] && [ "$size" = "${WANT_BYTES[$q]}" ]; then
    echo "$q: OK ($f, $((size/2**30)) GiB, sha $got)"
  else
    echo "$q: MISMATCH — got sha $got size $size, want ${WANT_SHA[$q]} ${WANT_BYTES[$q]}"
    echo "    (a same-named file with a different hash is a NEWER re-quant;"
    echo "     the configs here were measured against sha ${WANT_SHA[$q]} — see README Models)"
    return 1
  fi
}

download_one(){  # <key>
  local q=$1
  local f=${FNAME[$1]}
  local tmp=".part-$f"
  local url="${SRC[$1]}/$f"

  # tip-drift check for unsloth-hosted files
  if [ "${SRC[$q]}" = "$UNSLOTH" ]; then
    local api_sha
    api_sha=$(curl -sL --max-time 30 "$API_UNSLOTH" \
              | python3 -c "import json,sys
for e in json.load(sys.stdin):
    if e.get('path','').endswith('$f'):
        print((e.get('lfs') or {}).get('oid','')[:12]); break" 2>/dev/null || true)
    if [ -n "$api_sha" ] && [ "$api_sha" != "${WANT_SHA[$q]}" ]; then
      echo "WARNING: unsloth repo tip for $f now serves sha $api_sha, but this repo"
      echo "         was measured with ${WANT_SHA[$q]}. Downloading the TIP file;"
      echo "         expect the final hash check to fail (by design)."
    fi
  fi

  local size
  size=$(curl -sIL --retry 3 "$url" | grep -i '^content-length' | tail -1 | tr -d '\r' | awk '{print $2}')
  [ -n "$size" ] && [ "$size" -gt 0 ] || die "no content-length for $url (offline? HF down?)"
  echo ">> $q: $f — $((size/2**30)) GiB in $NCHUNK parallel chunks"
  local chunk=$(( (size + NCHUNK - 1) / NCHUNK )) pids=()
  rm -f "$tmp".part*
  for i in $(seq 0 $((NCHUNK-1))); do
    local s=$((i*chunk)) e=$(( (i+1)*chunk - 1 )); [ "$e" -ge "$size" ] && e=$((size-1))
    [ "$s" -gt "$e" ] && continue
    curl -sL --retry 5 --retry-all-errors -r "$s-$e" -o "$tmp.part$i" "$url" &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p" || die "a chunk failed for $f (rerun; completed chunks are not reused)"; done
  cat $(ls "$tmp".part* | sort -V) > "$tmp"
  rm -f "$tmp".part*
  [ "$(stat -c%s "$tmp")" = "$size" ] || { rm -f "$tmp"; die "assembled size mismatch for $f"; }
  local got=$(sha256sum "$tmp" | cut -c1-12)
  [ "$got" = "${WANT_SHA[$q]}" ] || { rm -f "$tmp"; die "$f hash mismatch (got $got, want ${WANT_SHA[$q]}) — file removed"; }
  mv "$tmp" "$f"
  echo ">> $q: verified sha $got — installed $f"
}

[ $# -eq 0 ] && set -- q5 q6 q8 draft mmproj
ARGS=()
for a in "$@"; do
  case "$a" in
    q5|q6|q8|draft|mmproj) ARGS+=("$a");;
    --check)  CHECK=1;;
    -h|--help) usage 0;;
    *) usage 1;;
  esac
done
command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required (tip-drift check)"

if [ "${CHECK:-0}" = 1 ]; then
  rc=0; for q in q5 q6 q8 draft mmproj; do verify_one "$q" || rc=1; done
  [ $rc -eq 0 ] && echo "all five GGUFs on disk match the README fingerprints"
  exit $rc
fi
[ ${#ARGS[@]} -gt 0 ] || die "nothing to do (use q5/q6/q8/draft/mmproj or --check)"

for q in "${ARGS[@]}"; do
  if verify_one "$q" >/dev/null; then echo ">> $q: already on disk and verified — skipping"
  else download_one "$q"; fi
done
echo
echo "Done. Every recipe the router serves is now covered by a verified file;"
echo "run ./download_models.sh --check anytime to re-verify."
