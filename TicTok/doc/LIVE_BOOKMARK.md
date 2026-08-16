# live監視中の見どころ登録

監視画面(`/`)と全体監視(`/overview`)で、録画中に面白い瞬間が来たらその場で1押しで見どころを
登録する。配信終了後は `/videos` の見どころとして、既存の `bookmarks` 表にそのまま並ぶ。

- 押下: `POST /api/monitors/{unique_id}/bookmark`
- 画面: 監視画面の `🔖 見どころ` button と **Bキー**、全体監視のtileの `🔖`

## 中核: wall-clock軸 -> media PTS軸の再map

押した瞬間に判るのは**wall-clock**だけである。しかし録画mp4の時間軸は**media PTS**で、
両者は一致しない。`start = now - started_at` のまま保存すると、印は長時間配信ほど手前を指す。

### 実測(本番録画・2026-07-20)

| 録画 | 長さ | mp4長 | 末尾付近での naive とのズレ |
|---|---|---|---|
| rec 690 | 5分 | 258.7s | **39.5s** |
| rec 689 | 23分 | 1416.7s | **53.7s** |
| rec 688 | 37分 | 2377.5s | **127.6s** |
| rec 687 | **112分** | 7088.2s | **340.3s** |

ズレは時間に対してほぼ線形に増える(mp4長 / media長 ≈ 1.05)。**2時間の配信では約6分ずれる**ので、
再mapを省いた実装は機能として成立しない。

rec 690では末尾で naive 298.2s に対し正解 258.7s と、naiveが**mp4の終端を超える**ケースも出る
(再接続でwallは進んだがmediaは進まなかった区間があるため)。

### 変換は焼き込みと同じ実装を使う

`video_overlay._make_time_mapper(anchors, started_at, ended_at, video_duration, None, media_pts)`
をそのまま呼ぶ。入力は録画のsidecar `.timing.json`(`_load_timing_anchors` / `_load_media_pts`)。

ここで別実装を持つと、同じ録画に対して**焼き込みのコメント位置と見どころの位置が食い違う**。
`recorder.py` からの取り込みは関数内import(`video_overlay` が `recorder` をimportしており、
top-levelだと循環する)。既存の `reencode_single_resolution` と同じ作法である。

### 確定できないときは確定させない

`_remap_live_bookmarks` は timing map が無い/anchorが2点未満なら**何も書かず警告して戻る**。

これは実際に起こる: 解像度正規化がCFR再encodeへ落ちるとmedia->pts対応が壊れるため、
recorderは `.timing.json` を破棄する。その状態で暫定値を確定扱いにすると、ズレた値が
「正しい値」として残る。再mapは正規化の**後**に呼ぶ(前に呼ぶと、破棄される前のmapで
確定させてしまう)。

## data model

`bookmarks` に2列追加(既存DBは `_migrate` でALTER)。

| 列 | 意味 |
|---|---|
| `live_wall` | 押した瞬間のwall-clock。再mapの唯一の入力。`/videos`から作った行はNULL |
| `pts_mapped` | 1=startはmp4のPTS軸。0=まだwall-clock由来の暫定値 |

押下時は `start`(=録画開始からの経過秒の暫定値)・`live_wall`・`pts_mapped=0` で入り、
finalizeの再mapで `start` をPTS値へ書き換えて `pts_mapped=1` にする。

`start` を暫定値で埋めるのは、`start` が NOT NULL で既存の全consumerが読む列だからである。
暫定であることは `pts_mapped=0` が担い、**画面はこれを見て「暫定」と表示できる**。
finalizeが走らないまま終わった行も0のまま残るので、黙って確定値のふりをすることはない。

既存行は `live_wall IS NULL` / `pts_mapped=1`(既定値)。`/videos` から作る行のstartは
最初からPTS軸なので、これが正しく、再map対象にも入らない。

## 設計判断: 録画していない配信には打てない (409)

見どころは**動画の中の位置**を指すものなので、録画が無ければ後から戻る先が無い。
`bookmarks.recording_id` も NOT NULL REFERENCES recordings である。
録画外でも打てるようにすると、再生できない印だけが溜まる。

session全体に対する印が要る場合は、それは既存の `markers` 表(session_id + time + kind)の
役割であり、見どころとは別物として設計するべきである。

## 時刻はServerが打つ

clientは時刻を送らない。押した時刻をbrowserから受け取ると、browserの時計ずれがそのまま
印のずれになり、さらに収集側の時計(録画の `started_at`)と別の時計を混ぜることになる。

## 検証

実録画の `.timing.json` を正解として、実装した再map経路を通した結果(誤差 <0.05s):

| 押下(録画開始からの経過) | naive | 再map後 | 正解(anchor) | 誤差 | 補正量 |
|---|---|---|---|---|---|
| 1685.2s | 1685.2s | 1777.1s | 1777.1s | +0.000s | +91.9s |
| 3371.1s | 3371.1s | 3543.6s | 3543.6s | +0.000s | +172.5s |
| 6736.5s | 6736.5s | 7086.2s | 7086.2s | +0.000s | **+349.7s** |

anchorsは録画時に記録された (wall, media) の実対応なので、anchor上の時刻で打てば
正解が判る。

## 位置と尺の編集 (`PATCH /api/bookmarks/{id}`)

見どころtabの「位置」「尺」は入力欄で、`start` / `end` をその場で直せる。直せないと、
点に尺を与えるにも端を1秒詰めるにも再生画面へ戻って記録し直すことになり、古い行を
消し忘れれば同じ場面の見どころが2件残る。

2つの欄は独立に効く。位置は**尺を保ったまま窓ごと**動かし(画面が `start` と `end` の
両方を送る)、尺は位置を据えたまま終端だけを動かす。尺の欄を空にすると `end: null` で
範囲を捨てて点へ戻る。`end` は `model_fields_set` で「触らない」と区別する
(Noneを既定値と読み違えると範囲が黙って外れる)。

**`pts_mapped = 0` の行は断る (422)。** startはwall-clock由来の暫定値で、finalizeの
再mapが上書きする(実測で数十〜数百秒動く)。手で入れた `end` だけが残れば
`start < end` という前提も黙って崩れる。画面は同じ根拠で入力欄を無効化し、
理由(録画の確定後に定まる)をtitleで名乗る。メモとグループはPTS軸と関係が無いので、
押した直後でも直せる。

## `/videos` 側に必要な変更(未実装・範囲外)

- `pts_mapped = 0` の行を「暫定位置」と**位置の値そのもの**で判るように出す。
  現状は位置・尺の入力欄が無効になるだけで、値は他の行と同じ見た目で並ぶ。
- live由来(`live_wall IS NOT NULL`)を見分けたい場合の表示。

APIの `GET /api/bookmarks` は `b.*` を返すので、両列とも既にpayloadに含まれている。
