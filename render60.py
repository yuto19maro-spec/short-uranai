#!/usr/bin/env python3
"""60秒 誕生日TOP5 ショート動画レンダラー（1テーマ深掘り型）

伸びている占いショートの構成を再現する縦型動画（1080x1920 / 30fps / ぴったり60.00秒）。
1カット = テロップ1枚 + AI画像1枚 + ナレーション1区切り。

使い方:
    python3 render60.py scripts60/<name>.json images            # 必要な画像と生成プロンプトの一覧 (未生成のものに印)
    python3 render60.py scripts60/<name>.json voice             # VOICEVOX でナレーション生成 (要: VOICEVOX 起動)
    python3 render60.py scripts60/<name>.json sheet             # 全カットの静止画一覧 out/<name>_sheet.jpg
    python3 render60.py scripts60/<name>.json render            # 本番 out/<name>.mp4
    python3 render60.py scripts60/<name>.json render --silent   # VOICEVOX 無しで尺だけ仮置きして確認用に書き出す
    python3 render60.py scripts60/<name>.json post              # 投稿文 (YouTube/Instagram/TikTok) だけ書き出す

台本(JSON)の書式は README60.md を参照。
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import cv2
except ImportError:
    cv2 = None

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
SR = 24000                      # VOICEVOX の出力サンプルレート
FONT_PATH = os.path.join(ROOT, "fonts", "NotoSansJP.ttf")   # 可変フォント (setup60.sh で取得)
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")

# ---------------------------------------------------------------- 見た目 (参考動画 720x1280 を実測して換算)
COLORS = {
    "w": (255, 255, 255),       # 通常
    "y": (255, 212, 0),         # {強調}  黄色
    "r": (238, 38, 24),         # [警告]  赤
}
BODY_SIZE = 66                  # 通常テロップ
BODY_STROKE = 7
BODY_MAX_W = 980
TITLE_SIZES = [100, 132, 100]   # タイトル3行 (導入 / 核心ワード / 誕生日TOP5)
TITLE_COLORS = ["w", "y", "r"]  # 各行の基本色 (行内の {} [] で上書き可)
TITLE_STROKE = 11
TEXT_CY = 960                   # テロップ中心Y (画面中央)
LINE_GAP = 1.32                 # 行送り (文字サイズ比)

# ---------------------------------------------------------------- 尺
PAD = 0.05                      # ナレーション後の間 (秒)。参考動画はほぼ切れ目なく読み続ける
TITLE_EXTRA = 0.35              # タイトルカットだけ少し長く見せる
VIDEO_LEN = 60.0                # 完成尺 (秒)。ぴったりこの長さで書き出す
FIT_LO, FIT_HI = 57.8, 59.6     # ナレーションだけの合計がこの範囲に入るよう話速を調整
FIT_TARGET = 58.8               # 調整時の狙い。残りは各カットの間に均等に足して VIDEO_LEN にそろえる
SPEED_MIN, SPEED_MAX = 0.95, 1.6
ZOOM = 0.07                     # 1カット中のゆっくりズーム量


def fail(msg):
    print("エラー: " + msg, file=sys.stderr)
    sys.exit(1)


# ================================================================ 台本
def load_script(path):
    with open(path, encoding="utf-8") as f:
        sc = json.load(f)
    sc.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    sc.setdefault("voice", {})
    sc["voice"].setdefault("speaker", 14)
    sc["voice"].setdefault("speed", 1.15)
    common_path = os.path.join(ROOT, "scripts60", "common_images.json")
    common = {}
    if os.path.exists(common_path):
        with open(common_path, encoding="utf-8") as f:
            common = json.load(f)["images"]
    sc["_common"] = common
    for i, c in enumerate(sc["cuts"]):
        if "img" not in c:
            fail(f"カット{i} に img がありません")
        if "say" not in c:
            raw = "".join(c["title"]) if "title" in c else c["text"]
            # 引用符は VOICEVOX で不自然な間が入るので読みから外す
            c["say"] = strip_markup(raw).replace("\n", "").translate(str.maketrans("", "", "“”「」"))
    return sc


def strip_markup(s):
    for ch in "{}[]":
        s = s.replace(ch, "")
    return s


def image_prompt(sc, key):
    if key.startswith("common/"):
        return sc["_common"].get(key[7:])
    return sc["images"].get(key)


def image_path(sc, key):
    if key.startswith("common/"):
        base = os.path.join(ROOT, "assets60", "common", key[7:])
    else:
        base = os.path.join(ROOT, "assets60", sc["name"], key)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        if os.path.exists(base + ext):
            return base + ext
    return None


def all_image_keys(sc):
    keys = []
    for c in sc["cuts"]:
        if c["img"] not in keys:
            keys.append(c["img"])
    return keys


# ================================================================ ナレーション (VOICEVOX)
def vv_post(path, params, body=None):
    url = VOICEVOX_URL + path + "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def query(text, speaker):
    return json.loads(vv_post("/audio_query", {"text": text, "speaker": speaker}))


def synth_query(q, speaker, speed):
    q["speedScale"] = speed
    q["prePhonemeLength"] = 0.02
    q["postPhonemeLength"] = 0.03
    q["outputSamplingRate"] = SR
    q["outputStereo"] = False
    return vv_post("/synthesis", {"speaker": speaker}, q)


def wav_bytes_to_array(b):
    path = io.BytesIO(b)
    with wave.open(path) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        if w.getnchannels() == 2:
            a = a.reshape(-1, 2).mean(1)
        if w.getframerate() != SR:
            n = int(len(a) * SR / w.getframerate())
            a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a


def mora_count(q):
    return sum(len(ap["moras"]) for ap in q["accent_phrases"])


def mora_ends(q):
    """各モーラの終わりの時刻 (直後の息継ぎも含める) と全体の長さ。speedScale=1 の秒"""
    t = q["prePhonemeLength"]
    ends = []
    for ap in q["accent_phrases"]:
        for m in ap["moras"]:
            t += (m.get("consonant_length") or 0) + m["vowel_length"]
            ends.append(t)
        if ap.get("pause_mora"):
            t += ap["pause_mora"]["vowel_length"]
            ends[-1] = t
    return ends, t + q["postPhonemeLength"]


def sentence_groups(sc):
    """"cont": true のカットは前のカットと同じ文として続けて読む"""
    groups = []
    for i, c in enumerate(sc["cuts"]):
        if c.get("cont") and groups:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def synth_group(sc, idxs, speed):
    """1つの文をまとめて合成し、テロップの切り替わり位置 (モーラ境界) で切り分ける。
    カットごとにバラバラに合成すると、文の途中で抑揚が途切れて不自然になるため。"""
    spk = sc["voice"]["speaker"]
    says = [sc["cuts"][i]["say"] for i in idxs]
    q = query("".join(says), spk)
    a = wav_bytes_to_array(synth_query(q, spk, speed))
    if len(idxs) == 1:
        return [a]
    counts = [mora_count(query(t, spk)) for t in says]
    ends, total = mora_ends(q)
    if sum(counts) != len(ends):
        print(f"注意: 「{''.join(says)}」の区切り位置を特定できないので、カットごとに分けて合成します")
        return [wav_bytes_to_array(synth_query(query(t, spk), spk, speed)) for t in says]
    scale = len(a) / SR / total
    pieces, prev, k = [], 0, 0
    for n in counts[:-1]:
        k += n
        cut = int(ends[k - 1] * scale * SR)
        pieces.append(a[prev:cut])
        prev = cut
    pieces.append(a[prev:])
    return pieces


def voice_dir(sc):
    return os.path.join(ROOT, "work", sc["name"], "voice")


def group_files(sc, idxs, speed):
    key = "|".join(sc["cuts"][i]["say"] for i in idxs)
    h = hashlib.md5(f'{key}|{sc["voice"]["speaker"]}|{speed:.3f}|v2'.encode()).hexdigest()[:10]
    return [os.path.join(voice_dir(sc), f"{h}_{j}.wav") for j in range(len(idxs))]


def read_wav(path):
    with open(path, "rb") as f:
        return wav_bytes_to_array(f.read())


def write_wav(path, a):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def continues(sc, k):
    """カット k の次のカットが同じ文の続きか"""
    return k + 1 < len(sc["cuts"]) and bool(sc["cuts"][k + 1].get("cont"))


def natural_durations(sc, voices):
    """ナレーションの長さ + 間 (引き伸ばす前)。文の途中のカットには間を入れない"""
    d = []
    for k, (c, v) in enumerate(zip(sc["cuts"], voices)):
        t = len(v) / SR + (0 if continues(sc, k) else PAD)
        if "title" in c:
            t += TITLE_EXTRA
        d.append(max(t, 0.6))
    return d


def cut_durations(sc, voices):
    """各カットの尺。余りを文の切れ目に均等に足して合計を VIDEO_LEN ちょうどにする"""
    d = natural_durations(sc, voices)
    extra = VIDEO_LEN - sum(d)
    if extra < 0:
        fail(f"ナレーションが {sum(d):.1f} 秒あり {VIDEO_LEN:.0f} 秒に収まりません。台本を短くしてください。")
    ends = [k for k in range(len(d)) if not continues(sc, k)]
    for k in ends:
        d[k] += extra / len(ends)
    return d


def check_voicevox():
    try:
        urllib.request.urlopen(VOICEVOX_URL + "/version", timeout=5).read()
    except Exception:
        fail(f"VOICEVOX に接続できません ({VOICEVOX_URL})。VOICEVOX アプリを起動してから再実行してください。")


def voices_at(sc, speed, create):
    voices = [None] * len(sc["cuts"])
    for g in sentence_groups(sc):
        files = group_files(sc, g, speed)
        if not all(os.path.exists(f) for f in files):
            if not create:
                return None
            for f, piece in zip(files, synth_group(sc, g, speed)):
                write_wav(f, piece)
        for i, f in zip(g, files):
            voices[i] = read_wav(f)
    return voices


def make_voices(sc):
    """全カットのナレーションを作り、合計が FIT_LO〜FIT_HI 秒になるよう話速を自動調整する。"""
    check_voicevox()
    os.makedirs(voice_dir(sc), exist_ok=True)
    speed = sc["voice"]["speed"]
    for _ in range(6):
        voices = voices_at(sc, speed, True)
        total = sum(natural_durations(sc, voices))
        print(f"話速 {speed:.2f} → ナレーション合計 {total:.1f} 秒")
        if FIT_LO <= total <= FIT_HI:
            break
        new = min(max(round(speed * total / FIT_TARGET, 3), SPEED_MIN), SPEED_MAX)
        if new == speed:
            break
        speed = new
    if speed > 1.3:
        print(f"注意: 話速が {speed:.2f} と速めです。台本の読み上げ文字数を減らすと聞きやすくなります（kana コマンドで確認）")
    with open(os.path.join(voice_dir(sc), "speed.txt"), "w") as f:
        f.write(str(speed))
    return voices


def load_voices(sc, silent):
    if silent:
        # VOICEVOX 無しの仮尺 (1文字 0.11秒)
        return [np.zeros(int((0.11 * len(c["say"]) + 0.2) * SR), np.float32) for c in sc["cuts"]]
    sp = os.path.join(voice_dir(sc), "speed.txt")
    if os.path.exists(sp):
        voices = voices_at(sc, float(open(sp).read()), False)
        if voices is not None:
            return voices
    return make_voices(sc)     # 未作成 or 台本が変わっていたら作り直す


# ================================================================ 画像
def placeholder(key):
    """画像が未生成のときの仮背景 (色は key から決める)"""
    h = int(hashlib.md5(key.encode()).hexdigest()[:6], 16)
    c1 = np.array([(h >> 16) & 255, (h >> 8) & 255, h & 255], np.float32) * 0.45
    c2 = c1 * 0.25
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    img = (c1 * (1 - t) + c2 * t) * np.ones((1, W, 1), np.float32)
    im = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.text((40, 60), "NO IMAGE: " + key, fill=(255, 255, 255), font=font(40, "Bold"))
    return im


def cover(im, w, h):
    im = im.convert("RGB")
    s = max(w / im.width, h / im.height)
    nw, nh = round(im.width * s), round(im.height * s)
    im = im.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - w) // 2, (nh - h) // 2
    return im.crop((x, y, x + w, y + h))


def load_bg(sc, key):
    p = image_path(sc, key)
    im = Image.open(p) if p else placeholder(key)
    # ズームで切り抜くので少し大きめに用意
    return np.asarray(cover(im, int(W * (1 + ZOOM)), int(H * (1 + ZOOM))))


# ================================================================ テロップ
_fonts = {}


def font(size, weight="Black"):
    k = (size, weight)
    if k not in _fonts:
        if not os.path.exists(FONT_PATH):
            fail("フォントがありません。先に ./setup60.sh を実行してください。")
        f = ImageFont.truetype(FONT_PATH, size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        _fonts[k] = f
    return _fonts[k]


def parse_runs(line, base):
    """'通常{黄色}[赤]' → [(文字列, 色キー)]"""
    runs, cur, col = [], "", base
    for ch in line:
        if ch in "{[":
            if cur:
                runs.append((cur, col))
            cur, col = "", ("y" if ch == "{" else "r")
        elif ch in "}]":
            if cur:
                runs.append((cur, col))
            cur, col = "", base
        else:
            cur += ch
    if cur:
        runs.append((cur, col))
    return runs


def draw_lines(lines, sizes, stroke, base_colors, weight):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fitted = []
    for line, size, base in zip(lines, sizes, base_colors):
        runs = parse_runs(line, base)
        text = "".join(r[0] for r in runs)
        s = size
        while s > 24 and font(s, weight).getlength(text) + stroke * 2 > BODY_MAX_W:
            s -= 2
        fitted.append((runs, s, round(stroke * s / size)))
    heights = [s * LINE_GAP for _, s, _ in fitted]
    y = TEXT_CY - sum(heights) / 2
    for (runs, s, st), lh in zip(fitted, heights):
        f = font(s, weight)
        total = sum(f.getlength(t) for t, _ in runs)
        x = (W - total) / 2
        cy = y + lh / 2
        for t, col in runs:
            d.text((x, cy), t, font=f, fill=COLORS[col], anchor="lm",
                   stroke_width=st, stroke_fill=(0, 0, 0))
            x += f.getlength(t)
        y += lh
    return layer


def text_layer(cut):
    if "title" in cut:
        lines = cut["title"]
        return draw_lines(lines, TITLE_SIZES[:len(lines)], TITLE_STROKE,
                          TITLE_COLORS[:len(lines)], "Black")
    lines = cut["text"].split("\n")
    return draw_lines(lines, [BODY_SIZE] * len(lines), BODY_STROKE, ["w"] * len(lines), "Black")


# ================================================================ 合成
def frame_at(bg, alpha, rgb, p, zoom_in, text_opacity=1.0):
    """p: 画像の表示区間内の進み 0..1 (同じ画像が続くカットはまとめて1区間)"""
    z = ZOOM * (p if zoom_in else 1 - p)
    bh, bw = bg.shape[:2]
    cw, ch = W * (1 + z) , H * (1 + z)
    x0, y0 = (bw - cw) / 2, (bh - ch) / 2
    if cv2 is not None:
        m = np.float32([[cw / W, 0, x0], [0, ch / H, y0]])
        fr = cv2.warpAffine(bg, m, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    else:
        fr = np.asarray(Image.fromarray(bg).resize((W, H), Image.BILINEAR,
                                                   box=(x0, y0, x0 + cw, y0 + ch)))
    if text_opacity < 1:
        alpha, rgb = alpha * text_opacity, rgb * text_opacity
    return (fr * (1 - alpha) + rgb).astype(np.uint8)


def prep_cut(sc, cut, bg=None):
    if bg is None:
        bg = load_bg(sc, cut["img"])
    lay = np.asarray(text_layer(cut)).astype(np.float32) / 255
    alpha = lay[..., 3:4]
    return bg, alpha, lay[..., :3] * 255 * alpha


def cmd_images(sc, args):
    missing = 0
    print(f"画像の保存先: assets60/{sc['name']}/<名前>.png  (common/～ は assets60/common/<名前>.png)")
    print(f"共通スタイル: {sc.get('style', '')}\n")
    for k in all_image_keys(sc):
        p = image_path(sc, k)
        mark = "OK " if p else "未 "
        missing += p is None
        print(f"[{mark}] {k}\n      {image_prompt(sc, k)}")
    print(f"\n未生成: {missing} 枚")


def cmd_kana(sc, args):
    """VOICEVOX が実際にどう読むかを文ごとにカナで表示する (読み間違いのチェック用)"""
    check_voicevox()
    spk = sc["voice"]["speaker"]
    chars = 0
    for g in sentence_groups(sc):
        text = "".join(sc["cuts"][i]["say"] for i in g)
        q = query(text, spk)
        print(f"{g[0]:2d}{'-' + str(g[-1]) if len(g) > 1 else '  '} {text}\n      {q.get('kana', '')}")
        chars += len(text)
    print(f"\n読み上げ文字数: {chars} 文字（目安 400 前後。多いと話速が上がりすぎる）")


def cmd_voice(sc, args):
    make_voices(sc)
    print("ナレーション作成完了: " + voice_dir(sc))


def cmd_sheet(sc, args):
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    cols, tw, th = 7, 216, 384
    rows = (len(sc["cuts"]) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th))
    for i, c in enumerate(sc["cuts"]):
        bg, a, rgb = prep_cut(sc, c)
        fr = Image.fromarray(frame_at(bg, a, rgb, 0.5, True)).resize((tw, th), Image.LANCZOS)
        sheet.paste(fr, ((i % cols) * tw, (i // cols) * th))
    out = os.path.join(ROOT, "out", f"{sc['name']}_sheet.jpg")
    sheet.save(out, quality=88)
    print(out)


def cmd_render(sc, args):
    voices = load_voices(sc, args.silent)
    durs = cut_durations(sc, voices)
    total = sum(durs)
    print(f"カット数 {len(durs)} / 合計 {total:.2f} 秒")

    # 音声トラック
    audio = np.zeros(round(total * SR), np.float32)
    t = 0.0
    for v, d in zip(voices, durs):
        i = int(t * SR)
        v = v[:len(audio) - i]
        audio[i:i + len(v)] += v
        t += d
    if sc.get("bgm"):
        bgm_path = os.path.join(ROOT, sc["bgm"])
        raw = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", bgm_path,
                              "-t", f"{len(audio) / SR}", "-ac", "1", "-ar", str(SR),
                              "-f", "s16le", "-"], capture_output=True, check=True).stdout
        b = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        audio[:len(b)] += b * float(sc.get("bgm_volume", 0.12))
    audio = np.clip(audio, -1, 1)
    work = os.path.join(ROOT, "work", sc["name"])
    os.makedirs(work, exist_ok=True)
    wav = os.path.join(work, "narration.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())

    out = args.output or os.path.join(ROOT, "out", sc["name"] + ".mp4")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    nframes = round(total * FPS)
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-i", wav,
                           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "192k", "-t", f"{nframes / FPS:.3f}",
                           "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    starts = np.cumsum([0] + durs)
    # 同じ画像が続くカットは1つの区間としてズームを途切れさせない
    group, gstart, gend = [], {}, {}
    for k, c in enumerate(sc["cuts"]):
        if k == 0:
            group.append(0)
        else:
            group.append(group[-1] + (c["img"] != sc["cuts"][k - 1]["img"]))
        gstart.setdefault(group[k], starts[k])
        gend[group[k]] = starts[k + 1]
    ci, cache = -1, None
    for n in range(nframes):
        tt = n / FPS
        k = min(int(np.searchsorted(starts, tt, side="right")) - 1, len(durs) - 1)
        if k != ci:
            same = cache is not None and sc["cuts"][k]["img"] == sc["cuts"][ci]["img"]
            ci, cache = k, prep_cut(sc, sc["cuts"][k], cache[0] if same else None)
            print(f"\rカット {k + 1}/{len(durs)}", end="", flush=True)
        g = group[k]
        p = (tt - gstart[g]) / (gend[g] - gstart[g])
        # タイトルは画像が先に出て、0.12秒後から0.2秒かけて文字がふわっと出る
        op = min(max((tt - starts[k] - 0.12) / 0.2, 0.0), 1.0) if "title" in sc["cuts"][k] else 1.0
        ff.stdin.write(frame_at(*cache, p, g % 2 == 0, op).tobytes())
    ff.stdin.close()
    ff.wait()
    print("\n" + out)
    write_post(sc)


def write_post(sc):
    """投稿文 (YouTube / Instagram / TikTok) をまとめて out/<name>_post.txt に書き出す"""
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    if sc.get("pinned_comment"):
        cpath = os.path.join(ROOT, "out", sc["name"] + "_pinned_comment.txt")
        with open(cpath, "w", encoding="utf-8") as f:
            f.write(sc["pinned_comment"] + "\n")
    parts = [
        ("YouTube タイトル", sc.get("youtube_title")),
        ("YouTube 説明欄", sc.get("youtube_description", "VOICEVOX:冥鳴ひまり")),
        ("YouTube 投稿者コメント（投稿したらすぐ書いて固定）", sc.get("pinned_comment")),
        ("Instagram キャプション", sc.get("instagram_caption")),
        ("Instagram 投稿者コメント（固定）", sc.get("pinned_comment")),
        ("TikTok キャプション", sc.get("tiktok_caption")),
        ("TikTok 投稿者コメント（固定・150文字以内）", sc.get("tiktok_pinned_comment")),
    ]
    path = os.path.join(ROOT, "out", sc["name"] + "_post.txt")
    with open(path, "w", encoding="utf-8") as f:
        for head, body in parts:
            if body:
                f.write(f"■ {head}\n{body}\n\n")
    tk = sc.get("tiktok_pinned_comment") or ""
    if len(tk) > 150:
        print(f"注意: TikTok の固定コメントが {len(tk)} 文字あります（150文字まで）", file=sys.stderr)
    print("投稿文: " + path)


def cmd_post(sc, args):
    write_post(sc)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("command", choices=["images", "kana", "voice", "sheet", "render", "post"])
    ap.add_argument("-o", "--output")
    ap.add_argument("--silent", action="store_true", help="VOICEVOX 無しで仮の尺で書き出す")
    args = ap.parse_args()
    sc = load_script(args.script)
    {"images": cmd_images, "kana": cmd_kana, "voice": cmd_voice, "sheet": cmd_sheet,
     "render": cmd_render, "post": cmd_post}[args.command](sc, args)


if __name__ == "__main__":
    main()
