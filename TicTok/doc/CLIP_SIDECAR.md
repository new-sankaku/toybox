# 切り抜きのsidecar(字幕・comment)

切り抜きmp4の隣へ、その区間の文字起こしとcommentをfileとして出す機能。

## なぜ要るのか

切り抜きの実体は `tictok/media/clipper.py` の `make_clip()` で、ffmpegのstream copy 1本
(`-c copy`)である。元録画はHLS由来でvideo streamとaudio streamしか持たないため、切り抜きも
video+audioだけになる。つまり**話した内容もcommentも切り抜きmp4には一切残らない**。

素材はDBに揃っている(転写は `transcripts`、commentは `search_hits` の `source = comment`)。
足りなかったのは、それを切り抜きの時間軸へ載せ替える経路だけだった。

焼き込み出力(`variant = "overlay"`)を切り抜けば字幕もcommentも映ってはいるが、あれは画素へ
焼き込んだもので、NLE側で位置調整も非表示もできない。素材として潰しが効かないため、sidecarとは
用途が別である。

## 出るもの

`<record root>/_clips/<配信者>/` に、mp4と同じbase名で並ぶ。

| file | 中身 |
| --- | --- |
| `<name>.mp4` | 切り抜き本体(従来どおり) |
| `<name>.srt` | その区間の文字起こし |
| `<name>.comments.srt` | comment字幕(`[nickname] 本文`) |
| `<name>.comments.csv` | comment一覧(`time_seconds, timecode, nickname, body`) |

中身が空になるものは書かない。空のsidecarを置くと、NLEは字幕trackが在るものとして読み込み
「字幕は付いているのに何も出ない」という切り分けにくい状態になる。

## 0点はstartではなくactual_start_seconds

この機能で唯一壊れやすいのがここ。

stream copyは要求位置ではなく**直前のkeyframeから**始まる。keyframe間隔は配信側のencoder設定
次第で、実測2.1秒〜37.6秒とばらつく(`clipper.py` のmodule docstringを参照)。要求のstartを
sidecarの0点にすると、全cueがそのlead秒ぶん後ろへずれる。

`make_clip()` は `actual_start_seconds`(= 要求start - lead)を返すので、必ずそちらを0点に使う。
lead区間も切り抜きの中身なので、そこに掛かる発話・commentもsidecarへ入れる。

### leadはvideo trackの尺から引く

leadは「出力の尺 - 要求の尺」で求まるが、その尺に**containerの尺(`format=duration`)を使っては
いけない**。containerの尺は全streamの最大終端-最小開始なので、音量正規化(`normalize`)で音声を
再encodeする経路では、loudnorm/aresampleがsampleを詰めた分やAAC encoderのdelayまで含む。
それをleadとして扱うと、**音声filterの都合でsidecarの0点がずれる**。

leadが表すのは「videoがkeyframeまで手前へ伸びた量」なので、常にstream copyされる
**video trackの尺**(`_video_duration_seconds`)だけを測る。containerの尺は音声filterが尺を
変えたことを検知するcanaryとして別に使い続ける(`clip.duration_mismatch`)。

窓の終端はcontainerの尺で取る。videoより後ろへ伸びる音声まで拾えるので末尾のcueを取りこぼさない
(0点と違い、終端は多めに取っても実害が無い)。

### 0点が測れなければ書かない

ffprobeが無い等でvideo trackの尺が測れないと、leadは `None` になる。このとき要求のstartを0点と
して書くと、**最大37秒ずれた字幕が「それらしく」出来上がる**。ズレていることはNLEへ載せて見るまで
分からないので、書かずに理由を返す(`skipped`)。

再encode(`precise = True`)はframe精度で切れるため0点は要求のstartそのもので、leadは存在しない。
この経路は測定に依存せず書き出せる。

## 元録画から切ったものにしか出さない

DBの時刻は元録画mp4のPTS軸に載っている。焼き込み出力・Up出力は再encodeを挟んで尺が動き得るため、
そこから切った切り抜きに対しては時刻を保証できない。保証できないまま出すと外部NLEで
「それらしいが合っていない字幕」になり、誤りを検出する手段が無くなる。

よって `variant != "source"` では書かず、理由を戻り値の `skipped` に載せて画面まで運ぶ
(`subtitles.usable_segments()` が時刻の欠けたsegmentを推測で埋めないのと同じ方針)。

時刻mapの版が古いtranscript(`subtitles.timemap_current()` が False)は書き出しは通し、
`timemap_stale` を立てて画面に「ズレの可能性あり」と出す。sidecarは外部で直せるので、
焼き込みのように取り返しがつかない用途とは扱いを変えている。

## commentのcueの作り方

commentは投稿時刻だけを持つ点eventで尺が無いため、cueの長さはこちらで決めるほかない。
既定は `TICTOK_COMMENT_SUBTITLE_SECONDS`(4秒)で、次のcueが開く時刻で打ち切るので上限として働く。

開いているcueの最中に届いたcommentは、重なるcueを新しく開かずに**同じcueへ行として足す**。
SRTのcueは本来前後しない前提で、重なると読み手(playerやNLE)によって片方が消えたり順が入れ替わったり
する。1 cueへ束ねる件数は `TICTOK_COMMENT_SUBTITLE_MAX_LINES`(4件)で頭打ちにする。

ただし**同時刻**のcommentだけは上限を超えても同じcueへ入れる。時刻が同じものは時間軸で分けようが
なく、cueを閉じると長さ0のcueになって内容ごと落ちるため。

## commentの書き出しAPI

sidecarとは別に、録画1本ぶん(または任意区間)のcommentを単体で取り出せる。

```
GET /api/recordings/{recording_id}/comments/export?format=srt|csv|json&start=&end=
```

`start` / `end` を渡すとその区間だけを書き出し、`start` を0点として相対時刻へ写す。
画面からは Comment panel の「SRTを保存」「CSVを保存」で呼ぶ。

## 設定値

| 環境変数 | 既定 | 用途 |
| --- | --- | --- |
| `TICTOK_CLIP_SIDECAR` | `1` | 切り出し時にsidecarを書くか |
| `TICTOK_COMMENT_SUBTITLE_SECONDS` | `4.0` | comment 1 cueの長さの上限 |
| `TICTOK_COMMENT_SUBTITLE_MAX_LINES` | `4` | 1 cueへ束ねるcommentの上限件数 |

## 関連file

- `tictok/media/clip_sidecar.py` — 窓取りと書き出しの本体
- `tictok/media/comment_track.py` — comment → cue / CSV / JSON
- `tictok/record/subtitles.py` — `window_segments()` が転写の窓取りと相対化を担う
- `tictok/server.py` — `_write_clip_sidecars()`、`export_comments_api()`
- `tests/test_clip_sidecar.py` — 0点がactual_start_secondsであることの検証
