#!/usr/bin/env python3
"""Pixabay の動画素材を 60秒動画 (render60.py) の背景に使うためのツール

APIキーは環境変数 PIXABAY_API_KEY から読む (リポジトリやチャットには書かない)。
    Windows (PowerShell): setx PIXABAY_API_KEY "キー"   → 新しく開いたターミナルから有効

使い方:
    python3 pixabay60.py test                          # キーが動くか確認 (キーの値は表示しない)
    python3 pixabay60.py search "golden clouds"        # 検索して候補を一覧 (縦長の候補を優先表示)
    python3 pixabay60.py fetch scripts60/<name>.json   # 台本の "videos" に書いたカットの動画をまとめてダウンロード

台本の書き方: "images" と同じキーで "videos": {"キー": "英語の検索ワード"} を書くと、
そのキーのカットは AI画像の代わりに動画が背景になる (assets60/<name>/<キー>.mp4)。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
API = "https://pixabay.com/api/videos/"
CACHE_DIR = os.path.join(ROOT, "work", "pixabay_cache")   # 検索結果は24時間キャッシュする (Pixabay API の利用規約)
UA = {"User-Agent": "short-uranai/1.0"}


def fail(msg):
    print("エラー: " + msg, file=sys.stderr)
    sys.exit(1)


def api_key():
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        fail("環境変数 PIXABAY_API_KEY がありません。\n"
             '  Windows: PowerShell で setx PIXABAY_API_KEY "キー" を実行し、ターミナル（チャット）を開き直してください')
    return key


def search(query, per_page=30):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cpath = os.path.join(CACHE_DIR, urllib.parse.quote(query, safe="") + ".json")
    if os.path.exists(cpath) and time.time() - os.path.getmtime(cpath) < 24 * 3600:
        with open(cpath, encoding="utf-8") as f:
            return json.load(f)
    params = {"key": api_key(), "q": query, "per_page": per_page, "safesearch": "true", "order": "popular"}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            fail(f"Pixabay がキーを受け付けませんでした (HTTP {e.code})。キーが正しいか確認してください")
        raise
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def best_file(hit):
    """長辺1920px以下でいちばん大きいファイルを選ぶ (4K は重いので避ける)"""
    vids = [v for v in hit.get("videos", {}).values() if v.get("url") and v.get("width")]
    if not vids:
        return None
    vids.sort(key=lambda v: (max(v["width"], v["height"]) > 1920, -(v["width"] * v["height"])))
    return vids[0]


def rank_hits(hits, min_dur):
    """縦長 → 長さが足りる → 人気 の順に並べる"""
    def score(h):
        v = best_file(h) or {"width": 1, "height": 1}
        portrait = v["height"] > v["width"]
        return (not portrait, h.get("duration", 0) < min_dur, -h.get("downloads", 0))
    return sorted([h for h in hits if best_file(h)], key=score)


def cmd_test(args):
    data = search("clouds sky", per_page=5)
    n = data.get("totalHits", 0)
    print(f"OK: PIXABAY_API_KEY は有効です（「clouds sky」で {n} 件ヒット）")
    for h in data.get("hits", [])[:3]:
        v = best_file(h)
        print(f"  - {h['duration']}秒 {v['width']}x{v['height']}  {h['pageURL']}")


def cmd_search(args):
    if not args:
        fail('検索ワードを指定してください 例: python3 pixabay60.py search "golden clouds"')
    q = " ".join(args)
    hits = rank_hits(search(q).get("hits", []), 3)
    print(f"「{q}」の候補 {len(hits)} 件（縦長を優先）")
    for i, h in enumerate(hits[:15]):
        v = best_file(h)
        shape = "縦" if v["height"] > v["width"] else "横"
        print(f"{i:2d} [{shape}] {h['duration']:3d}秒 {v['width']}x{v['height']}  {h['tags']}\n     {h['pageURL']}")


def download(url, path):
    tmp = path + ".part"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(tmp, path)


def cmd_fetch(args):
    if not args:
        fail("台本を指定してください 例: python3 pixabay60.py fetch scripts60/<name>.json")
    with open(args[0], encoding="utf-8") as f:
        sc = json.load(f)
    name = sc.get("name") or os.path.splitext(os.path.basename(args[0]))[0]
    videos = sc.get("videos", {})
    if not videos:
        print("この台本には \"videos\" がありません（全カット AI画像）")
        return
    out_dir = os.path.join(ROOT, "assets60", name)
    os.makedirs(out_dir, exist_ok=True)
    used = set()          # 同じ動画を別のカットに使い回さない
    for key, query in videos.items():
        path = os.path.join(out_dir, key + ".mp4")
        meta = os.path.join(out_dir, key + ".pixabay.json")
        if os.path.exists(path):
            print(f"[済] {key}")
            if os.path.exists(meta):
                used.add(json.load(open(meta, encoding="utf-8")).get("id"))
            continue
        hits = [h for h in rank_hits(search(query).get("hits", []), 3) if h["id"] not in used]
        if not hits:
            print(f"[なし] {key}: 「{query}」で見つかりませんでした。検索ワードを変えてください")
            continue
        h = hits[0]
        v = best_file(h)
        download(v["url"], path)
        used.add(h["id"])
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"id": h["id"], "query": query, "pageURL": h["pageURL"], "user": h.get("user"),
                       "duration": h["duration"], "width": v["width"], "height": v["height"]},
                      f, ensure_ascii=False, indent=1)
        shape = "縦" if v["height"] > v["width"] else "横（中央を縦に切り抜いて使う）"
        print(f"[DL] {key}: {h['duration']}秒 {v['width']}x{v['height']} {shape}  {h['pageURL']}")
        time.sleep(0.5)
    print(f"保存先: {out_dir}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("test", "search", "fetch"):
        print(__doc__)
        sys.exit(1)
    {"test": cmd_test, "search": cmd_search, "fetch": cmd_fetch}[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
