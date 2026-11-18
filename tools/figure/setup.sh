#!/bin/bash
# tools/figure/setup.sh   one-time setup for the figure recipe on an Apple Silicon Mac.
# describe: LFM3-VL-2B 4 bit through mlx-vlm, same venv (about 1.6 GB)
# style: FLUX.2 klein 4B edit through mflux, in ~/.cache/stone-style/.venv (about 5 GB of weights at 4 bit)
# lift:  tools/lift (its own uv project; see tools/lift/README.md)
set -euo pipefail
cd "$(dirname "$0")/../.."
STYLE=${STONE_STYLE_HOME:-$HOME/.cache/stone-style}
mkdir -p "$STYLE"
[ -x "$STYLE/.venv/bin/python" ] || uv venv -q -p 3.12 "$STYLE/.venv"
uv pip install -q -p "$STYLE/.venv" mflux==0.24.0 mlx-vlm==0.7.12 "huggingface_hub[hf_xet]"
python3 tools/figure/fetch.py LiquidAI/LFM3-VL-2B-MLX-4bit "$STYLE/models/lfm3-vl-2b-4bit"
python3 tools/figure/fetch.py mflux-community/flux2-klein-4b-mflux-q4 "$STYLE/models/flux2-klein-4b-q4"
V=tools/lift/vendor/Hunyuan3D-2
[ -d "$V/.git" ] || git clone -q https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git "$V"
git -C "$V" checkout -q f8db63096c8282cb27354314d896feba5ba6ff8a
uv sync -q --python 3.12 --project tools/lift
# the lift weights (about 3.8 GB) download on the first stone build of a figure
echo "figure tools ready: style in $STYLE, lift in tools/lift"
