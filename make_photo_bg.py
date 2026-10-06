#!/usr/bin/env python3
"""静止画の海の背景に動きを付けて動画化する。

    python3 make_photo_bg.py bg/photos/sea1.png --horizon 0.477 --water-end 0.80 -o bg/sea1.mp4

付ける動き:
  - ゆっくりズームイン
  - 水平線より下を波のように揺らす (遠くは細かく・手前は大きく)
  - 水面の明るい反射をキラキラ点滅させる
  - 星をまたたかせる
"""
import argparse
import subprocess

import cv2
import numpy as np

W, H, FPS = 1080, 1920, 30


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--horizon", type=float, required=True, help="水平線の高さ (画像の上から0〜1)")
    ap.add_argument("--water-end", type=float, default=1.0, help="波打ち際の高さ。これより下(砂浜)は揺らさない")
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--zoom", type=float, default=0.07, help="ズーム量 (0.07 = 7%%拡大)")
    ap.add_argument("--ripple", type=float, default=3.0, help="波の揺れ幅(px)")
    ap.add_argument("--glitter", type=float, default=0.45)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    src = cv2.imread(a.image, cv2.IMREAD_COLOR)
    src = cv2.resize(src, (W, H), interpolation=cv2.INTER_LANCZOS4).astype(np.float32) / 255.0
    lum = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    hy = a.horizon * H
    we = a.water_end * H

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    # 揺れの強さ: 水平線で0 → 手前ほど大きく → 波打ち際の先で0
    depth = np.clip((yy - hy) / (H - hy), 0, 1)
    env = smooth(hy + 2, hy + 60, yy) * (0.15 + 0.85 * depth) * (1 - smooth(we, we + 0.07 * H, yy))
    # 遠くほど波が細かく見えるように対数で縦方向の位相を圧縮
    py = np.log(np.maximum(yy - hy, 0) + 12.0) * 55.0

    # キラキラ: 水面の明るい部分
    water = (yy > hy + 3).astype(np.float32) * (1 - smooth(we + 0.03 * H, we + 0.09 * H, yy) * 0.6)
    bright = smooth(0.45, 0.85, lum) * water
    phase = cv2.GaussianBlur(rng.random((H, W)).astype(np.float32), (0, 0), 1.2)
    phase = (phase - phase.min()) / (phase.max() - phase.min() + 1e-6) * 40.0
    speed = (4.0 + rng.random((H, W)) * 5.0).astype(np.float32)

    # 星: 周囲より明るい小さな点
    sky = (yy < hy - 10).astype(np.float32)
    star = np.clip(lum - cv2.GaussianBlur(lum, (0, 0), 4), 0, 1) * sky
    star = smooth(0.06, 0.25, star)
    star_phase = (rng.random((H, W)) * 6.28).astype(np.float32)

    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", a.out],
                           stdin=subprocess.PIPE)
    n = int(a.duration * FPS)
    cx, cy = W / 2, hy
    for fi in range(n):
        t = fi / FPS
        # 明るさの変化 (ソース空間)
        tw = np.clip(np.sin(t * speed + phase), 0, 1) ** 6
        frame = src + (src * 0.7 + 0.3) * (bright * tw * a.glitter)[..., None]
        st = 0.55 + 0.45 * np.sin(t * 3.5 + star_phase)
        frame = frame + (star * (st - 0.75) * 0.9)[..., None]

        # ズーム + 波の揺れ (出力→ソースの座標変換)
        z = 1.0 + a.zoom * (t / a.duration)
        sx = cx + (xx - cx) / z
        sy = cy + (yy - cy) / z
        dx = a.ripple * env * (np.sin(py - t * 2.4) + 0.5 * np.sin(py * 2.3 + xx * 0.012 - t * 3.3))
        dy = a.ripple * 0.45 * env * np.sin(py * 1.4 - t * 1.9)
        out = cv2.remap(frame, (sx + dx).astype(np.float32), (sy + dy).astype(np.float32),
                        cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        enc.stdin.write((np.clip(out, 0, 1) * 255).astype(np.uint8).tobytes())
    enc.stdin.close()
    enc.wait()
    print("wrote", a.out)


if __name__ == "__main__":
    main()
