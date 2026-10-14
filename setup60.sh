#!/usr/bin/env bash
# 60秒フォーマット (render60.py) の準備: フォント (Noto Sans JP / SIL OFL)・ライブラリ
# 何度実行しても、足りないものだけ用意する
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p fonts out work assets60/common
if [ ! -f fonts/NotoSansJP.ttf ]; then
  curl -fsSL -o fonts/NotoSansJP.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
fi
python3 -c "import PIL, numpy" 2>/dev/null || pip install -q pillow numpy
python3 -c "import cv2" 2>/dev/null || pip install -q opencv-python-headless
command -v ffmpeg >/dev/null || echo "注意: ffmpeg が見つかりません。インストールしてください。"
echo "ready"
