---
name: uranai60
description: 60秒の「誕生日TOP5」1テーマ深掘り型ショート動画（AI画像＋VOICEVOXナレーション）を作る。「60秒の動画作って」「scripts60 の動画を作って」「前世ランキングの動画」など、scripts60/ の台本から動画を書き出すときに使う。18.6秒の4タイトル型（ranking スキル）とは別物。
---

# 60秒 誕生日TOP5 動画を作る（ローカルPC用）

伸びている占いショート（登録者2.7万・最大450万再生）の構成を再現したフォーマット。
台本は `scripts60/<name>.json` に用意済み（クラウドのセッションで作って push してある）。
このスキルは **ローカルPC** で、Codex（画像）と VOICEVOX（音声）を使って動画を書き出す。
`render60.py` のレイアウト・尺の決め方は確定版なので、頼まれない限り変更しない。変えるのは台本と画像だけ。

## 0. 最新を取得して準備

```bash
git pull
./setup60.sh        # フォント (fonts/NotoSansJP.ttf)・Pillow/numpy/OpenCV を足りない分だけ用意
```

## 1. 画像を作る（このPCの Codex）

```bash
python3 render60.py scripts60/<name>.json images
```

必要な画像の一覧・保存先・プロンプトが出る（`[未 ]` が未生成）。

- 保存先: `assets60/<name>/<キー>.png`、`common/～` は `assets60/common/<キー>.png`（全動画で使い回す。既にあれば作らない）
- プロンプト = 各画像のプロンプト + 台本の `style`（共通スタイル）。`common/～` のプロンプトは `scripts60/common_images.json`
- **縦長 (9:16 / 1024x1536 など) で、画像内に文字を入れない**。サイズや比率が多少違っても render60.py が中央でトリミングする
- 生成はこのPCの Codex で行う（以前ユーザーと画像を作ったときと同じやり方）。例:
  `codex exec --full-auto "次の内容で縦長(1024x1536)の画像を生成し、assets60/zense_ouzoku/title.png に保存して: <プロンプト>"`
  何枚かずつまとめて頼んでもよい。全部そろったら `images` をもう一度実行して `未生成: 0 枚` を確認
- 人物の顔・手が崩れた画像、文字が入った画像は作り直す

## 2. ナレーション（このPCの VOICEVOX）

VOICEVOX アプリ（エンジン: http://127.0.0.1:50021）を起動してから:

```bash
python3 render60.py scripts60/<name>.json voice
```

- 話者は台本の `voice.speaker`（既定 14 = 冥鳴ひまり ノーマル。落ち着いた女性の声で参考動画に近い）。
  ID がこのPCの VOICEVOX と違う場合は `curl http://127.0.0.1:50021/speakers` で確認して台本を直す
- ナレーションの合計が約58〜59.6秒になるよう話速を自動調整する（長ければ速く、短ければゆっくり）
- 読み間違いがあれば、そのカットに `"say"`（読み上げ用のひらがな表記）を足して再実行。
  日付は「9日→ここのか」のように say で読みを指定してある

## 3. 確認して書き出す

```bash
python3 render60.py scripts60/<name>.json sheet     # out/<name>_sheet.jpg に全カットの一覧
python3 render60.py scripts60/<name>.json render    # out/<name>.mp4 (ぴったり60.00秒) と固定コメント文
```

- 尺は **ぴったり60.00秒（1800フレーム）** に自動でそろう（余りは各カットの間に均等に足す）。書き出し後に
  `ffprobe -v error -show_entries format=duration -of csv=p=0 out/<name>.mp4` が `60.000000` か確認する
- sheet を見て、テロップと画像の内容が合っているか・文字のはみ出しがないかを確認
- 書き出した mp4 をユーザーに渡す。BGM は台本に `"bgm": "bgm/xxx.mp3"` を書けば小さめに混ぜる（無ければアプリ側で付ける）

## 4. 投稿時に使うもの（ユーザーに伝える）

- YouTubeタイトル: 台本の `youtube_title`
- **固定コメント**: `out/<name>_pinned_comment.txt`（1位の誕生日。動画は「この誕生日はコメント欄」で終わるので必ず固定する）
- 概要欄に `VOICEVOX:<話者名>` のクレジットを書く（VOICEVOX の利用規約）

## 5. 保存

画像 (`assets60/`)・音声 (`work/`)・動画 (`out/`) はコミットしない（.gitignore 済み）。
台本を直した場合だけコミットして push する。
