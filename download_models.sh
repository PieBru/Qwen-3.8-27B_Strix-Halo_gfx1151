#!/bin/bash
# download_models.sh — fetch the Unsloth Dynamic K_XL target GGUFs for this repo.
#
# Downloads the exact files the README's Models table was measured with (the
# unsloth repo tip as of 2026-08-21), verifies each one's sha256 before
# installing the final filename, and never leaves a half-downloaded file under
# the canonical name (downloads land as *.part-<name> and are renamed only
# after the hash check passes).
#
# Usage:
#   ./download_models.sh            # download all three targets (~70 GiB)
#   ./download_models.sh q6 q8      # just the ones you want
#   ./download_models.sh --check    # only verify files already on disk
#
# Speed: uses 10 parallel HTTP range requests (~8x faster than a single
# stream on a typical home link; measured 106 MB/s vs 13 MB/s).
#
# NOTE: this covers the TARGET models only. You also need, from their own
# sources (not in the unsloth repo — see README "Models"):
#   - a Qwen3.8-27B-DFlash2 draft GGUF (speculative decoding, loaded via -md)
#   - mmproj-F16.gguf                (vision projector, only for the vision recipe)
set -euo pipefail
cd "$(dirname "$0")"

REPO_URL=https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main
API_URL=https://huggingface.co/api/models/unsloth/Qwen3.8-27B-GGUF/tree/main

# The files this repo was measured with (README "Models" table). If unsloth
# re-quantizes again, the sha256 below won't match the repo tip anymore and
# this script will tell you — then re-check the README before trusting new
# files under the same names.
declare -A WANT_SHA WANT_BYTES
WANT_SHA[q8]=af36ecb6b5db;  WANT_BYTES[q8]=31457991680
WANT_SHA[q6]=701d8fa9ed21;  WANT_BYTES[q6]=25299061664
WANT_SHA[q5]=8601193d3d57;  WANT_BYTES[q5]=20876938144
declare -A FNAME=( [q8]=Qwen3.8-27B-UD-Q8_K_XL.gguf
                   [q6]=Qwen3.8-27B-UD-Q6_K_XL.gguf
                   [q5]=Qwen3.8-27B-UD-Q5_K_XL.gguf )

NCHUNK=10

usage(){ grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
die(){ echo "error: $*" >&2; exit 1; }

verify_one(){  # <quant> -> prints OK/<status>, returns nonzero on mismatch
  local q=$1 f=${FNAME[$1]}
  [ -f "$f" ] || { echo "$q: MISSING ($f)"; return 1; }
  local got=$(sha256sum "$f" | cut -c1-12) size=$(stat -c%s "$f")
  if [ "$got" = "${WANT_SHA[$q]}" ] && [ "$size" = "${WANT_BYTES[$q]}" ]; then
    echo "$q: OK ($f, $((size/2**30)) GiB, sha $got)"
  else
    echo "$q: MISMATCH — got sha $got size $size, want ${WANT_SHA[$q]} ${WANT_BYTES[$q]}"
    echo "    (a same-named file with a different hash is a NEWER unsloth re-quant;"
    echo "     the configs here were measured against sha ${WANT_SHA[$q]} — see README Models)"
    return 1
  fi
}

download_one(){  # <quant>
  local q=$1 f=${FNAME[$1]} tmp=".part-$f"
  local url="$REPO_URL/$f"

  # tip-drift check: warn if the unsloth repo no longer serves our hash
  local api_sha
  api_sha=$(curl -sL --max-time 30 "$API_URL" \
            | python3 -c "import json,sys
for e in json.load(sys.stdin):
    if e.get('path','').endswith('$f'):
        print((e.get('lfs') or {}).get('oid','')[:12]); break" 2>/dev/null || true)
  if [ -n "$api_sha" ] && [ "$api_sha" != "${WANT_SHA[$q]}" ]; then
    echo "WARNING: unsloth repo tip for $f now serves sha $api_sha, but this repo"
    echo "         was measured with ${WANT_SHA[$q]}. Downloading the TIP file;"
    echo "         expect it to fail the final hash check (by design) — re-check"
    echo "         README Models before adopting a re-quant."
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
  for p in "${pids[@]}"; do wait "$p" || die "a chunk download failed for $f (rerun this script; completed chunks are not reused)"; done
  cat $(ls "$tmp".part* | sort -V) > "$tmp"
  rm -f "$tmp".part*
  [ "$(stat -c%s "$tmp")" = "$size" ] || { rm -f "$tmp"; die "assembled size mismatch for $f"; }
  local got=$(sha256sum "$tmp" | cut -c1-12)
  [ "$got" = "${WANT_SHA[$q]}" ] || { rm -f "$tmp"; die "$f hash mismatch (got $got, want ${WANT_SHA[$q]}) — file removed; see the warning above if any"; }
  mv "$tmp" "$f"
  echo ">> $q: verified sha $got — installed $f"
}

[ $# -eq 0 ] && set -- q5 q6 q8
ARGS=()
for a in "$@"; do
  case "$a" in
    q5|q6|q8) ARGS+=("$a");;
    --check)  CHECK=1;;
    -h|--help) usage 0;;
    *) usage 1;;
  esac
done
command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required (tip-drift check + none else)"

if [ "${CHECK:-0}" = 1 ]; then
  rc=0; for q in q5 q6 q8; do verify_one "$q" || rc=1; done
  [ $rc -eq 0 ] && echo "all target GGUFs on disk match the README fingerprints"
  exit $rc
fi
[ ${#ARGS[@]} -gt 0 ] || die "nothing to do (use q5/q6/q8 or --check)"

for q in "${ARGS[@]}"; do
  if verify_one "$q" >/dev/null; then echo ">> $q: already on disk and verified — skipping (use --check for details)"
  else download_one "$q"; fi
done
echo
echo "Done. Still needed from their own sources (see README Models):"
echo "  - Qwen3.8-27B-DFlash2 draft GGUF (required for all text recipes)"
echo "  - mmproj-F16.gguf                (only for the vision recipe)"
