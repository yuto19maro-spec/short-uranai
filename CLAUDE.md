# short-uranai

誕生日ランキングのショート動画（縦型・海の背景）を作るリポジトリ。

- ユーザーが「ランキング頼む」などと言ったら、`.claude/skills/ranking/SKILL.md` の手順で動画を作る
- 動画のフォーマット（`render.py` のレイアウト・演出・タイミング）はユーザー確認済みで完成している。頼まれない限り変更しない
- ユーザーとのやりとりは日本語で行う
- 60秒の1テーマ深掘り型（`render60.py` / `scripts60/`）は別フォーマット。ローカルPCでの書き出しは `.claude/skills/uranai60/SKILL.md`、仕様は `README60.md`、台本は `scripts60/TEMPLATE.md`（台本の型）に従って書く
- 人生の気づき・開運の「〇〇5選」型も `render60.py` / `scripts60/` で作る。台本の型は `scripts60/TEMPLATE_KIZUKI.md`（見本 `scripts60/okane_yoru.json`）
