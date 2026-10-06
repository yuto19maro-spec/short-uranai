#!/usr/bin/env python3
"""誕生日ランキング ショート動画レンダラー

使い方:
    python3 render.py scripts/sample.json -o out/sample.mp4
    python3 render.py scripts/sample.json --preview 3.0   # 指定秒の静止画だけ書き出す

台本(JSON)の書式は README.md を参照。
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
from functools import lru_cache

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30

FONT_PATH = os.path.join(ROOT, "fonts", "NotoSerifJP.ttf")   # 可変フォント (setup.sh で取得)
FONT_WEIGHT = {"heavy": b"Black", "sub": b"Black"}

# ---------------------------------------------------------------- layout
# 参考動画(720x1280)を実測して 1080x1920 に換算した値
BAND_Y0, BAND_Y1, BAND_ALPHA = 465, 1785, 0.55
TITLE_Y2 = (333, 437)        # 2行タイトルの各行の中心Y
TITLE_Y1 = 333               # 1行タイトルの中心Y
TITLE_SIZE = 96
LABEL_CX = 185               # 「N位」の中心X
TEXT_CX = 675                # 「◯日生まれ」/説明文の中心X
ROW_Y = [660, 910, 1160, 1388, 1605]   # 「N位」の中心Y (1位..5位)
MAIN_DY, SUB_DY = -28, 60
LABEL_SIZE, MAIN_SIZE, SUB_SIZE = 122, 92, 40
CTA_Y0, CTA_Y1 = 772, 1148
CTA_LINES_Y = [848, 960, 1072]
CTA_SIZE = 66

# ---------------------------------------------------------------- timing (秒, セグメント先頭からの相対)
DEFAULT_TIMING = {
    "reveal": [None, 1.55, 1.1, 0.65, 0.2],   # 2位..5位が出るタイミング (index0=1位はslamで別管理)
    "slam": 2.4,            # 1位が飛び込んでくる開始
    "slam_dur": 0.55,
    "main_cps": 0.05,       # 「◯日生まれ」1文字あたり秒
    "sub_cps": 0.024,       # 説明文 1文字あたり秒
    "cta_delay": 0.35,      # 1位着地からCTAボックスまで
    "cta_wipe": 0.28,
    "cta_cps": 0.018,
    "len_no_cta": 4.0,      # CTAなしセグメントの長さ
    "len_cta": 4.8,         # CTAありセグメントの長さ
}

# ---------------------------------------------------------------- styles
STYLES = {
    # fill: (上色, 下色) のグラデーション / glow: ぼかし半径 / stroke: 縁取り幅
    "title": dict(font="heavy", fill=((255, 251, 228), (214, 158, 60)), fill_mid=(244, 210, 128),
                  stroke=4, stroke_col=(60, 32, 6), glow=9, glow_col=(0, 0, 0), glow_a=0.9,
                  shadow=(0, 6), shadow_a=0.85),
    "label1": dict(font="heavy", fill=((255, 255, 250), (255, 226, 185)), stroke=4, stroke_col=(226, 110, 26),
                   glow=9, glow_col=(240, 110, 20), glow_a=0.55, shadow=(0, 4), shadow_a=0.6),
    "label2": dict(font="heavy", fill=((255, 255, 255), (255, 226, 228)), stroke=4, stroke_col=(196, 22, 52),
                   glow=8, glow_col=(140, 0, 28), glow_a=0.5, shadow=(0, 4), shadow_a=0.6),
    "label3": dict(font="heavy", fill=((255, 255, 255), (232, 255, 232)), stroke=4, stroke_col=(30, 156, 56),
                   glow=8, glow_col=(10, 100, 28), glow_a=0.5, shadow=(0, 4), shadow_a=0.6),
    "label4": dict(font="heavy", fill=((255, 255, 255), (242, 242, 242)), stroke=2, stroke_col=(40, 40, 40),
                   glow=8, glow_col=(0, 0, 0), glow_a=0.7, shadow=(0, 5), shadow_a=0.7),
    "main1": dict(font="heavy", fill=((255, 255, 255), (255, 244, 226)), stroke=3, stroke_col=(236, 128, 36),
                  glow=9, glow_col=(245, 120, 20), glow_a=0.55, shadow=(0, 3), shadow_a=0.5),
    "main2": dict(font="heavy", fill=((255, 246, 240), (255, 222, 210)), stroke=3, stroke_col=(184, 28, 52),
                  glow=7, glow_col=(130, 0, 26), glow_a=0.45, shadow=(0, 3), shadow_a=0.5),
    "main3": dict(font="heavy", fill=((246, 255, 246), (218, 252, 218)), stroke=3, stroke_col=(28, 146, 48),
                  glow=7, glow_col=(10, 96, 28), glow_a=0.45, shadow=(0, 3), shadow_a=0.5),
    "main4": dict(font="heavy", fill=((255, 255, 255), (242, 242, 242)), stroke=2, stroke_col=(30, 30, 30),
                  glow=7, glow_col=(0, 0, 0), glow_a=0.75, shadow=(0, 4), shadow_a=0.7),
    "sub1": dict(font="sub", fill=((255, 230, 130), (238, 184, 50)), stroke=2, stroke_col=(60, 30, 0),
                 glow=5, glow_col=(0, 0, 0), glow_a=0.8, shadow=(0, 2), shadow_a=0.6),
    "sub2": dict(font="sub", fill=((255, 255, 255), (246, 246, 246)), stroke=2, stroke_col=(20, 20, 20),
                 glow=5, glow_col=(0, 0, 0), glow_a=0.8, shadow=(0, 2), shadow_a=0.6),
    "sub3": dict(font="sub", fill=((130, 255, 130), (64, 222, 74)), stroke=2, stroke_col=(0, 46, 8),
                 glow=5, glow_col=(0, 0, 0), glow_a=0.8, shadow=(0, 2), shadow_a=0.6),
    "cta_red": dict(font="heavy", fill=((238, 48, 44), (204, 22, 26)), stroke=3, stroke_col=(255, 250, 238),
                    glow=5, glow_col=(120, 60, 0), glow_a=0.3, shadow=(0, 2), shadow_a=0.25),
    "cta_brown": dict(font="heavy", fill=((118, 80, 32), (82, 52, 16)), stroke=3, stroke_col=(255, 250, 238),
                      glow=5, glow_col=(80, 40, 0), glow_a=0.3, shadow=(0, 2), shadow_a=0.25),
    "cta_purple": dict(font="heavy", fill=((250, 244, 255), (228, 210, 255)), stroke=4, stroke_col=(122, 54, 236),
                       glow=8, glow_col=(128, 60, 255), glow_a=0.8, shadow=(0, 0), shadow_a=0.0),
}
STYLES["label5"] = STYLES["label4"]
STYLES["main5"] = STYLES["main4"]
STYLES["sub4"] = STYLES["sub2"]
STYLES["sub5"] = STYLES["sub2"]


@lru_cache(maxsize=None)
def font(kind, size):
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_name(FONT_WEIGHT[kind])
    return f


def _gradient(w, h, top, bottom, mid=None):
    t = np.linspace(0, 1, h)[:, None]
    top, bottom = np.array(top, float), np.array(bottom, float)
    if mid is None:
        col = top + (bottom - top) * t
    else:
        mid = np.array(mid, float)
        col = np.where(t < 0.5, top + (mid - top) * (t * 2), mid + (bottom - mid) * ((t - 0.5) * 2))
    arr = np.repeat(col[:, None, :], w, axis=1)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _colored(mask, rgb, alpha=1.0):
    layer = Image.new("RGBA", mask.size, tuple(rgb) + (0,))
    if alpha != 1.0:
        mask = mask.point(lambda v: int(v * alpha))
    layer.putalpha(mask)
    return layer


@lru_cache(maxsize=512)
def render_text(text, style_name, size, scale=1.0):
    """装飾付きテキストを RGBA 画像で返す。戻り値: (img, (ox, oy), advances)
    ox, oy: 画像左上から文字原点(左端, ベースライン中心ではなく ascender上端)までのオフセット
    advances: i文字目までの累積幅 (タイプライター用のクリップ位置)"""
    st = STYLES[style_name]
    k = scale
    f = font(st["font"], max(1, int(round(size * k))))
    pad = int((st["glow"] * 3 + st["stroke"] * 2 + 12) * k)
    bbox = f.getbbox(text)
    tw, th = bbox[2], bbox[3]
    w, h = tw + pad * 2, th + pad * 2
    stroke = max(1, int(round(st["stroke"] * k)))

    fill_m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(fill_m).text((pad, pad), text, font=f, fill=255)
    stroke_m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(stroke_m).text((pad, pad), text, font=f, fill=255, stroke_width=stroke, stroke_fill=255)

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if st["shadow_a"] > 0:
        sx, sy = int(st["shadow"][0] * k), int(st["shadow"][1] * k)
        sm = ImageChops.offset(stroke_m, sx, sy).filter(ImageFilter.GaussianBlur(3 * k))
        out = Image.alpha_composite(out, _colored(sm, (0, 0, 0), st["shadow_a"]))
    if st["glow"] > 0:
        gm = stroke_m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(st["glow"] * k))
        g = _colored(gm, st["glow_col"], min(1.0, st["glow_a"] * 1.6))
        out = Image.alpha_composite(out, g)
    out = Image.alpha_composite(out, _colored(stroke_m, st["stroke_col"]))
    top, bottom = st["fill"]
    # グラデーションは文字の高さ範囲に合わせる
    gy0, gy1 = pad + bbox[1], pad + bbox[3]
    grad = _gradient(w, max(1, gy1 - gy0), top, bottom, st.get("fill_mid"))
    full = Image.new("RGB", (w, h), top)
    full.paste(grad, (0, gy0))
    full.paste(Image.new("RGB", (w, h - gy1), bottom), (0, gy1))
    fl = full.convert("RGBA")
    fl.putalpha(fill_m)
    out = Image.alpha_composite(out, fl)

    adv = [0.0]
    for i in range(1, len(text) + 1):
        adv.append(f.getlength(text[:i]))
    return out, (pad, pad), tuple(adv), (tw, bbox[1], th)


def paste_text(canvas, text, style, size, cx, cy, chars=None, scale=1.0, alpha=1.0):
    """(cx, cy) を文字列の見た目の中心にして描画。chars: 表示する文字数(タイプライター)"""
    if not text or chars == 0:
        return
    img, (ox, oy), adv, (tw, ty0, ty1) = render_text(text, style, size, scale)
    if chars is not None and chars < len(text):
        clip = int(ox + adv[chars] + 2 * scale)
        img = img.crop((0, 0, clip, img.height))
    if alpha < 1.0:
        a = img.getchannel("A").point(lambda v: int(v * alpha))
        img = img.copy()
        img.putalpha(a)
    x = int(round(cx - (ox + tw / 2)))
    y = int(round(cy - (oy + (ty0 + ty1) / 2)))
    canvas.alpha_composite(img, (x, y)) if x >= 0 and y >= 0 and x + img.width <= W and y + img.height <= H \
        else _safe_paste(canvas, img, x, y)


def _safe_paste(canvas, img, x, y):
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + img.width), min(H, y + img.height)
    if x1 <= x0 or y1 <= y0:
        return
    canvas.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def fit_size(text, style, size, max_w):
    f = font(STYLES[style]["font"], size)
    while f.getlength(text) > max_w and size > 20:
        size -= 2
        f = font(STYLES[style]["font"], size)
    return size


def ease_out_cubic(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


# ---------------------------------------------------------------- CTA rich text
def parse_rich(line):
    """'必ず{『いいね』}して' → [('必ず', False), ('『いいね』', True), ('して', False)]"""
    parts, buf, hi = [], "", False
    for ch in line:
        if ch == "{" and not hi:
            if buf:
                parts.append((buf, False))
            buf, hi = "", True
        elif ch == "}" and hi:
            if buf:
                parts.append((buf, True))
            buf, hi = "", False
        else:
            buf += ch
    if buf:
        parts.append((buf, hi))
    return parts


def draw_cta_line(canvas, line, base_style, cy, chars):
    parts = parse_rich(line)
    plain = "".join(p for p, _ in parts)
    size = fit_size(plain, base_style, CTA_SIZE, W - 50)
    f = font("heavy", size)
    total = f.getlength(plain)
    x = (W - total) / 2
    shown = 0
    for seg, hi in parts:
        segw = f.getlength(seg)
        n = len(seg) if chars is None else max(0, min(len(seg), chars - shown))
        if n > 0:
            paste_text(canvas, seg, "cta_purple" if hi else base_style, size, x + segw / 2, cy, chars=n)
        shown += len(seg)
        x += segw


@lru_cache(maxsize=4)
def cta_box_image():
    h = CTA_Y1 - CTA_Y0
    box = _gradient(W, h, (255, 252, 238), (244, 228, 190), (251, 241, 215)).convert("RGBA")
    a = np.full((h, W), 250, np.uint8)
    edge = 6
    for i in range(edge):
        a[i, :] = a[h - 1 - i, :] = int(250 * (i + 1) / (edge + 1))
    box.putalpha(Image.fromarray(a))
    # 上下に薄い影
    sh = Image.new("RGBA", (W, h + 40), (0, 0, 0, 0))
    m = Image.new("L", (W, h + 40), 0)
    ImageDraw.Draw(m).rectangle((0, 20, W, h + 20), fill=120)
    m = m.filter(ImageFilter.GaussianBlur(10))
    sh.putalpha(m)
    sh.alpha_composite(box, (0, 20))
    return sh


# ---------------------------------------------------------------- overlay effects
class Rain:
    """参考動画の細い斜めの雨線"""

    def __init__(self, seed=7, density=9):
        self.rng = random.Random(seed)
        self.drops = []
        self.density = density

    def step(self, canvas, frame):
        rng = self.rng
        while len(self.drops) < self.density:
            self.drops.append([rng.uniform(-100, W + 200), rng.uniform(-400, H), rng.uniform(90, 170),
                               rng.uniform(55, 80), rng.uniform(0.18, 0.4), rng.choice([2, 2, 3])])
        d = ImageDraw.Draw(canvas)
        ang = math.radians(8)  # 右上→左下にわずかに傾く
        keep = []
        for dr in self.drops:
            x, y, ln, sp, a, wd = dr
            x2, y2 = x - math.sin(ang) * ln, y + math.cos(ang) * ln
            d.line((x, y, x2, y2), fill=(235, 240, 255, int(255 * a)), width=wd)
            dr[0] -= math.sin(ang) * sp
            dr[1] += math.cos(ang) * sp
            if dr[1] < H + 50:
                keep.append(dr)
        self.drops = keep


@lru_cache(maxsize=2)
def band_image():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((0, BAND_Y0, W, BAND_Y1), fill=(0, 0, 0, int(255 * BAND_ALPHA)))
    return img


@lru_cache(maxsize=2)
def glow_image():
    """1位着地時のゴールドの光"""
    gw, gh = 1300, 520
    yy, xx = np.mgrid[0:gh, 0:gw]
    r = np.sqrt(((xx - gw / 2) / (gw / 2)) ** 2 + ((yy - gh / 2) / (gh / 2)) ** 2)
    a = np.clip(1 - r, 0, 1) ** 1.6
    arr = np.zeros((gh, gw, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = 255, 178, 70
    arr[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


# ---------------------------------------------------------------- background
class BgReader:
    def __init__(self, path, offset=0.0):
        self.path = path
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},format=rgb24")
        cmd = ["ffmpeg", "-v", "error", "-stream_loop", "-1", "-ss", str(offset), "-i", path,
               "-vf", vf, "-f", "rawvideo", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)

    def read(self):
        buf = self.proc.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            return np.zeros((H, W, 3), np.uint8)
        return np.frombuffer(buf, np.uint8).reshape(H, W, 3)

    def close(self):
        self.proc.kill()
        self.proc.wait()


def resolve(path, base):
    if os.path.isabs(path):
        return path
    for b in (base, ROOT):
        p = os.path.join(b, path)
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, path)


# ---------------------------------------------------------------- timeline
def build_timeline(script):
    timing = dict(DEFAULT_TIMING)
    timing.update(script.get("timing", {}))
    segs, t = [], 0.0
    for i, s in enumerate(script["segments"]):
        tm = dict(timing)
        tm.update(s.get("timing", {}))
        cta = s.get("cta")
        length = s.get("duration") or (tm["len_cta"] if cta else tm["len_no_cta"])
        if i == len(script["segments"]) - 1:
            length += script.get("tail", 0.2)
        segs.append(dict(seg=s, start=t, end=t + length, tm=tm))
        t += length
    return segs, t


def bg_schedule(script, segs, base):
    """[(global_start, path, offset)] を返す。セグメントの "bg" は文字列 or [[path, 相対秒], ...]"""
    sched = []
    for sg in segs:
        bg = sg["seg"].get("bg", script.get("bg"))
        if bg is None:
            continue
        items = [[bg, 0]] if isinstance(bg, str) else bg
        for it in items:
            path, rel = it[0], it[1]
            off = it[2] if len(it) > 2 else 0.0
            sched.append((sg["start"] + rel, resolve(path, base), off))
    sched.sort(key=lambda x: x[0])
    return sched


def draw_segment(canvas, sg, lt, rain_layer):
    s, tm = sg["seg"], sg["tm"]
    canvas.alpha_composite(band_image())

    # title
    lines = s["title"] if isinstance(s["title"], list) else s["title"].split("\n")
    if len(lines) == 1:
        size = fit_size(lines[0], "title", TITLE_SIZE, W - 60)
        paste_text(canvas, lines[0], "title", size, W / 2, TITLE_Y1)
    else:
        size = min(fit_size(l, "title", TITLE_SIZE, W - 60) for l in lines[:2])
        for l, y in zip(lines[:2], TITLE_Y2):
            paste_text(canvas, l, "title", size, W / 2, y)

    # labels
    for r in range(5):
        paste_text(canvas, f"{r + 1}位", f"label{r + 1}", LABEL_SIZE, LABEL_CX, ROW_Y[r])

    ranks = s["ranks"]  # [[main, sub], ...] 1位→5位
    for r in range(4, 0, -1):
        t0 = tm["reveal"][r]
        if lt < t0:
            continue
        main, sub = ranks[r][0], ranks[r][1]
        msize = fit_size(main, f"main{r + 1}", MAIN_SIZE, 700)
        ssize = fit_size(sub, f"sub{r + 1}", SUB_SIZE, 760)
        mt = (lt - t0) / tm["main_cps"]
        paste_text(canvas, main, f"main{r + 1}", msize, TEXT_CX, ROW_Y[r] + MAIN_DY, chars=min(len(main), int(mt) + 1))
        st = (lt - t0 - len(main) * tm["main_cps"]) / tm["sub_cps"]
        if st >= 0:
            paste_text(canvas, sub, f"sub{r + 1}", ssize, TEXT_CX, ROW_Y[r] + SUB_DY, chars=min(len(sub), int(st) + 1))

    # 1位 slam
    main, sub = ranks[0][0], ranks[0][1]
    msize = fit_size(main, "main1", MAIN_SIZE, 700)
    ts, dur = tm["slam"], tm["slam_dur"]
    land = ts + dur
    if lt >= ts:
        p = (lt - ts) / dur
        fx, fy = TEXT_CX, ROW_Y[0] + MAIN_DY
        if p < 1.0:
            e = ease_out_cubic(p)
            sc = 5.2 + (1.0 - 5.2) * e
            cx = (W / 2 - 40) + (fx - (W / 2 - 40)) * e
            cy = (ROW_Y[1] - 40) + (fy - (ROW_Y[1] - 40)) * e
            a = min(1.0, p / 0.12)
            # 残像 (ズームブラー)
            for k, ga in ((1.18, 0.25), (1.08, 0.45)):
                paste_text(canvas, main, "main1", msize, cx, cy, scale=round(sc * k, 2), alpha=a * ga)
            paste_text(canvas, main, "main1", msize, cx, cy, scale=round(sc, 2), alpha=a)
        else:
            gl = 1.0 - min(1.0, (lt - land) / 0.7)
            if gl > 0:
                g = glow_image()
                ga = g.getchannel("A").point(lambda v: int(v * 0.85 * gl))
                g2 = g.copy()
                g2.putalpha(ga)
                _safe_paste(canvas, g2, int(W / 2 - g.width / 2 + 60), int(ROW_Y[0] - g.height / 2))
            paste_text(canvas, main, "main1", msize, fx, fy)
            st = (lt - land - 0.08) / tm["sub_cps"]
            if st >= 0:
                ssize = fit_size(sub, "sub1", SUB_SIZE, 760)
                paste_text(canvas, sub, "sub1", ssize, TEXT_CX, ROW_Y[0] + SUB_DY, chars=min(len(sub), int(st) + 1))

    # CTA
    cta = s.get("cta")
    if cta and lt >= land + tm["cta_delay"]:
        ct = lt - land - tm["cta_delay"]
        box = cta_box_image()
        wp = ease_out_cubic(ct / tm["cta_wipe"])
        bw = int(W * wp)
        if bw > 0:
            canvas.alpha_composite(box.crop((0, 0, bw, box.height)), (0, CTA_Y0 - 20))
        tt = (ct - tm["cta_wipe"] * 0.4) / tm["cta_cps"]
        if tt >= 0:
            shown = int(tt) + 1
            for li, line in enumerate(cta["lines"][:3]):
                n = len(line.replace("{", "").replace("}", ""))
                color = (cta.get("colors") or ["red", "brown", "red"])[li]
                draw_cta_line(canvas, line, "cta_" + color, CTA_LINES_Y[li], min(n, shown))
                shown -= n
                if shown <= 0:
                    break

    canvas.alpha_composite(rain_layer)


def render(script_path, out_path, preview=None, start=None, end=None):
    base = os.path.dirname(os.path.abspath(script_path))
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    segs, total = build_timeline(script)
    sched = bg_schedule(script, segs, base)
    nframes = int(round(total * FPS))

    frames = range(nframes)
    if preview is not None:
        frames = [int(preview * FPS)]
    elif start is not None or end is not None:
        frames = range(int((start or 0) * FPS), int((end or total) * FPS))

    rain = Rain(density=script.get("rain_density", 9)) if script.get("rain", True) else None
    brightness = script.get("bg_brightness", 1.0)

    enc = None
    if preview is None:
        tmp_video = out_path + ".video.mp4"
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                                "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                                tmp_video], stdin=subprocess.PIPE)

    reader, cur = None, None
    for fi in frames:
        t = fi / FPS
        # background
        active = None
        for item in sched:
            if item[0] <= t + 1e-6:
                active = item
        if active is not cur:
            if reader:
                reader.close()
            reader = None
            if active:
                skip = t - active[0] if preview is not None else max(0.0, t - active[0])
                reader = BgReader(active[1], active[2] + skip)
            cur = active
        bg = reader.read() if reader else np.full((H, W, 3), 20, np.uint8)
        if brightness != 1.0:
            bg = np.clip(bg.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
        canvas = Image.fromarray(bg, "RGB").convert("RGBA")

        rain_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if rain:
            rain.step(rain_layer, fi)
        sg = next((x for x in segs if x["start"] <= t < x["end"]), segs[-1])
        draw_segment(canvas, sg, t - sg["start"], rain_layer)

        rgb = canvas.convert("RGB")
        if preview is not None:
            rgb.save(out_path)
            print("wrote", out_path)
        else:
            enc.stdin.write(rgb.tobytes())
        if fi % 30 == 0:
            print(f"\r{t:5.1f}/{total:.1f}s", end="", file=sys.stderr, flush=True)
    if reader:
        reader.close()
    if enc is None:
        return
    enc.stdin.close()
    enc.wait()
    print(file=sys.stderr)
    mux_audio(script, base, out_path + ".video.mp4", out_path, total)
    os.remove(out_path + ".video.mp4")
    print("wrote", out_path)


def mux_audio(script, base, video, out, total):
    bgm = script.get("bgm")
    vol = script.get("bgm_volume", 1.0)
    if bgm:
        bgm = resolve(bgm, base)
        af = f"volume={vol},afade=t=out:st={max(0, total - 0.6)}:d=0.6"
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", video, "-stream_loop", "-1", "-ss",
               str(script.get("bgm_start", 0)), "-i", bgm, "-filter:a", af, "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", out]
    else:  # 無音トラックを付けておく (アプリ側で音源を付ける前提)
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", video, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest",
               "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out")
    ap.add_argument("--preview", type=float, help="指定秒の1フレームをPNGで書き出す")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    a = ap.parse_args()
    name = os.path.splitext(os.path.basename(a.script))[0]
    out = a.out or os.path.join(ROOT, "out", name + (f"_{a.preview:.2f}.png" if a.preview is not None else ".mp4"))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    render(a.script, out, a.preview, a.start, a.end)
