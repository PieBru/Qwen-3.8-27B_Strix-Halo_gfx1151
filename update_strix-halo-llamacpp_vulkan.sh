#!/bin/bash
# Update + rebuild the strix-halo llama.cpp Vulkan build (branch strix-halo-vulkan
# of https://github.com/Nathanw1014/llama.cpp) and verify the GPU backend.
# Aligned with QUICK_START.md — run it from the directory containing this script.

set -euo pipefail

REPO_DIR="llama.cpp"            # clone of Nathanw1014/llama.cpp
BRANCH="strix-halo-vulkan"      # dequant-once + all-quant transpose + mmid stack
BUILD_DIR="build-vk"

cd "$(dirname "$0")"            # work relative to this script's location
cd "$REPO_DIR"

# Update to the latest validated Vulkan stack
git fetch origin
git checkout "$BRANCH"
git pull --ff-only

# Configure + build (system glslc 2026.3 and Vulkan/SPIRV headers already qualify,
# so no -DVulkan_* overrides; GGML_NATIVE=ON is correct — this CPU is Strix Halo)
cmake -B "$BUILD_DIR" -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release \
    -DGGML_NATIVE=ON -DLLAMA_CURL=OFF
cmake --build "$BUILD_DIR" --target llama-server llama-cli llama-bench -j"$(nproc)"

# Verify GPU backend, not a silent CPU fallback (~7x slower — see QUICK_START.md)
export AMD_VULKAN_ICD=RADV
devices="$("$BUILD_DIR"/bin/llama-cli --list-devices)"
echo "$devices"
echo "$devices" | grep -q "Vulkan0: AMD Radeon 8060S" || {
    echo "ERROR: Vulkan device not detected — llama.cpp would fall back to CPU." >&2
    exit 1
}
echo "OK: Vulkan backend on Radeon 8060S confirmed."

# Optional smoke test (uncomment — picks a local model):
# "$BUILD_DIR"/bin/llama-cli -m ../Qwen3.8-27B-DFlash2-Q4_K_M.gguf -ngl 999 -p "Hello" -n 64
