# 接続時の遡り（backlog）による Event の二重記録

## 症状

配信の開始時と、配信が途切れて復帰したときに、同じCommentが何度も記録される。

実測（2026-08-28 時点のDB, events 1,401,662行）:

| kind | 総数 | 重複 | 率 |
|---|---|---|---|
| comment | 202,726 | 3,204 | 1.58% |
| gift | 34,633 | 317 | 0.92% |
| like | 815,042 | 231 | 0.03% |
| join | 332,075 | 109 | 0.03% |

極端な例（session 581, @wicha_3111）は **distinct 10件のCommentが124行**になっていた。
内訳は 20回x2種 / 19回x3種 / 17回x1種 / 4回x1種 / 2回x3種。この配信は数分おきに切断と
再接続を繰り返していた。

## 原因

TikTokのlive websocketは、**接続時の初回fetch応答にそのRoomの直近messageを載せて返す**
（`ProtoMessageFetchResult` が `messages` と併せて `history_comment_cursor` /
`history_no_more` を持つ）。TikTokLiveの `process_connect_events` は既定で有効なので、
その遡り分は普通のeventとしてlistenerへ届く。

接続が起きるのは「配信の開始時」と「切断からの復帰時」なので、症状の出る場面と一致する。

受け側には判別する鍵が無かった。`events` 表に message_id 列も一意制約も無く、
`_on_comment` にも `add_event` にも重複判定が無いので、届いたら必ず1行増えていた。

### 1回の接続につき2行入る

session 581 の同一Comment（create_time 1787780587.671）の挿入時刻は、すべて
`... のLIVE に接続しました` の時刻と一致し、**1接続につき0.1秒差で2行**入っていた。

```
2222905  time=1787781150.693   ← 初回fetchの messages
2222911  time=1787781150.807   ← 接続直後の最初のpush frame（同じcursorから送り直す分）
         system 1787781150.812 "@wicha_3111 のLIVE (Room 7678...) に接続しました。"
```

`process_connect_events=False` を渡しても前者しか止まらない。これが「その1行では直らない」
理由である。

### 遡りは件数で決まる（時間ではない）

接続直後に入ったComment 4,079件の遡り幅:

| p50 | p90 | p99 | 最大 |
|---|---|---|---|
| 81秒前 | 655秒前 | 3,140秒前 | 5,171秒前 |

静かなRoomほど、同じ件数でも古いmessageまで届く。記憶の窓を件数で切ると、賑わいに
よって覚えていられる時間が変わってしまうため、窓は**時間で切る**。

## 対策

### 1. 受信側で落とす（第一の防波堤）

`tictok/collect/dedup.py`

- `SeenMessages` — 処理済み `message_id` を窓（既定2時間、設定
  `message_dedup_window`）のあいだ覚えておく。**配信者1人につき1つで、sessionと再接続を
  跨いで生かす。** clientは再接続のたびに作り直されるため、clientに持たせると落としたい
  相手そのものが毎回素通りする。session跨ぎの遡り（実測369件）も同じ記憶で落ちる。
- `DedupTikTokLiveClient` — `_parse_webcast_response_message` を override し、既出の
  message をeventへ配る前に丸ごと落とす。

**鍵は `base_message.message_id` だけを使う。** TikTokがmessage 1件ごとに振る一意のidで、
遡り分は元と同じidで届く。text+時刻の一致では判定しない — 同じ人が同じ短文（「おは」等）を
続けて送るのは普通に起きるので、それを重複と見なすと本物のCommentが消える。

落とす位置がmessage単位なのは、1つのmessageから生まれる custom event（FollowEvent /
ShareEvent / SuperFanEvent）と proto event が同じ message_id を共有しているためである。
event単位で落とすと、最初の1つを通した時点で残りが道連れになる。

受信側で落とすので、`stats` もtimeline bucketも重複を数えない。DB側の制約だけで止めると、
行は1つでも `stats_json` の件数だけが水増しされる。

相手Room listener（`OpponentRoomListener`）にも同じ記憶を持たせている。撃ち直すたびに
同じGiftを数え直すと、相手陣の実弾合計が接続回数ぶん水増しされるため。

### 2. DB側の一意制約（耐久側の防波堤）

- `events.message_id`（INTEGER）を追加。既存行はNULL＝計装前の未計測で、埋める手は無い
  （TikTokからしか得られない値である）。
- 部分UNIQUE index `idx_events_message ON events(session_id, kind, message_id)
  WHERE message_id IS NOT NULL`
- INSERT に `ON CONFLICT (session_id, kind, message_id) WHERE message_id IS NOT NULL
  DO NOTHING`

効くのはprocessが落ちて記憶を失った直後だけだが、その窓こそ再接続が集中する場面である。

`OR IGNORE` にしてはならない。孤児eventのFK違反まで飲み込み、poison-pillの検知
（`_write_isolating_locked` の隔離経路）が効かなくなる。衝突の対象をこのindexの3列に
限定してあるので、FK違反とNOT NULL違反はこれまで通り送出される。

一意制約が **kind を含む** のは、1つのmessageが複数kindの行を生む形が将来現れても片方を
黙って捨てないためである。同じmessageから同じkindの行が2つ出るのは遡りの二重記録だけで、
これが落としたい相手そのものである。

一意制約が **session内で閉じている** のは、session跨ぎの重複は「どちらのsessionの
出来事だったか」の判断を伴うためである。そちらは受信側の記憶が担当する。

### 3. 既存行の掃除（1回きり）

`MaintenanceMixin._purge_connect_backlog_dupes`（marker `purge_connect_backlog_dupes_v1`）

message_id を持たない既存行は `(session_id, kind, user_id, text, create_time)` で畳み、
最古の1件を残す。一致を要求する組に **create_time（TikTokが打ったms精度の時刻）** を
含めているのが要点で、同じ人が同じ文を同じmilli秒に二度送ることは無い。text単独や
「近い時刻」で畳むと、本物の連投が消える。

session跨ぎ（369件）は触らない。消せばもう一方のsessionの集計が動くため、判断が要る。

削った後は journalからの復元と同じ順で `stats_json` と buckets を作り直す。解析cacheは
行を消すに留める（再計算はread専用接続を使う `_ensure_analytics_cache` の仕事で、
migrationの途中でcommitを挟まずに済む）。`stats_json` には provenance として
`deduplicated: true` を残す（`recovered` は行が増えた復元の印なので使い回さない）。

実DB copyでの実測: **3,862行を削除、215 sessionを作り直して3.0秒**（Storage初期化全体で
8.3秒）。2回目の起動はmarkerで素通りし0.3秒。残存重複0件。

## 関連

- `tictok/collect/dedup.py` — 受信側の除去
- `tictok/store/_common.py` `_events_insert_sql` / `_EVENTS_COLUMNS` — 一意制約と列
- `tictok/store/maintenance.py` `_purge_connect_backlog_dupes` — 既存行の掃除
- 設定 `message_dedup_window`（収集と接続）
