#!/usr/bin/env bash
# 動画を作る準備: フォント取得 (Noto Serif JP / SIL OFL)・ライブラリ・背景動画の生成
# 何度実行しても、足りないものだけ用意する
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p fonts bg out
if [ ! -f fonts/NotoSerifJP.ttf ]; then
  curl -fsSL -o fonts/NotoSerifJP.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifjp/NotoSerifJP%5Bwght%5D.ttf"
fi
python3 -c "import PIL, numpy" 2>/dev/null || pip install -q pillow numpy
python3 -c "import cv2" 2>/dev/null || pip install -q opencv-python-headless

# 静止画の海背景 → 動きを付けた動画 (水平線の高さ・波打ち際の高さは画像ごとに調整済み)
photo_bg() {  # name horizon water_end seed glitter
  [ -f "bg/$1.mp4" ] || python3 make_photo_bg.py "bg/photos/$1.png" --horizon "$2" --water-end "$3" \
    --seed "$4" --glitter "$5" -o "bg/$1.mp4" &
}
photo_bg sea1 0.477 0.80 1 0.45
photo_bg sea2 0.486 0.80 2 0.45
photo_bg sea3 0.496 1.0 3 0.45
photo_bg sea4 0.443 0.74 4 0.30
wait
echo "ready"
