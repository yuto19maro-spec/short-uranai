#!/usr/bin/env bash
# フォント取得 (Noto Serif JP / SIL Open Font License) と海の背景動画の生成
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p fonts bg out
if [ ! -f fonts/NotoSerifJP.ttf ]; then
  curl -fsSL -o fonts/NotoSerifJP.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifjp/NotoSerifJP%5Bwght%5D.ttf"
fi
python3 -c "import PIL, numpy" 2>/dev/null || pip install pillow numpy
ls bg/sea_*.mp4 >/dev/null 2>&1 || python3 make_sea_bg.py
echo "ready"
