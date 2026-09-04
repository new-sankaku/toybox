# 録画の尺と ended_at

## 2つの時間を混ぜない

録画1本には別物の時間が2つある。混ぜると静かに壊れる。

| 列 | 意味 | 出所 |
|---|---|---|
| `recordings.duration_seconds` | **動画そのものの長さ**(尺) | 出来たmp4のffprobe実測。測れなければNULL |
| `recordings.started_at` / `ended_at` | **捕捉していた壁時計の区間** | 録画開始時刻と、捕捉が終わった時刻 |

壁時計は尺ではない。捕捉が停滞した秒も再接続の待ちも `ended_at - started_at` には載るが、
動画には載らない(実測で1.6倍)。画面の「尺」・一括投入の見積り・所要時間の実測比は、すべて
`duration_seconds` だけを見る。

逆に `ended_at` は尺の代わりではなく、**その録画がどの時間帯のeventを含むか**を決める窓で
ある。焼き込みのcomment配置も検索indexも `[started_at, ended_at]` でeventを絞る。

## 障害: 作り直しが ended_at を「今」で潰していた

`Recorder._finalize` は捕捉が終わった瞬間に `ended_at = time.time()` を打つ。live captureでは
これが正しい。ところが**中身を作り直す2経路**が同じ `_finalize` を通り、その値をDBへ書き
戻していた。

- 起動時の中断録画復旧 (`recover_interrupted_recordings`)
- 再mp4化 (`_reprocess_recording`、一括投入を含む)

作り直しは中身を作り直すだけで、捕捉が終わった時刻を動かさない。にもかかわらず**実行した
時刻**が `ended_at` になっていた。

batchで走ると、その回に処理した全行の `ended_at` が同じ時刻に揃う。`started_at` は元のまま
なので、古い録画ほど差が開く。新しい順に並ぶ一覧では下へ行くほど尺が伸び、**積算している
ように見える**。

実測(2026-07-25時点、331本):

```
id=708  DB  34時間02分  実尺 3時間07分   ended_at 07-24 08:15
id=707  DB  44時間45分  実尺 4時間24分   ended_at 07-24 08:08
id=706  DB  57時間46分  実尺 2時間43分   ended_at 07-24 08:05  ← ended_atがほぼ同一
id=705  DB  65時間10分  実尺 1時間17分   ended_at 07-24 08:00
id=84   DB 650時間57分  実尺 0時間00分   (x91801)
```

被害は表示に留まらない。潰れた `ended_at` は event窓を数日ぶん広げるため、焼き込みが次の
録画ぶんのcommentまで巻き込む。

## 直し方

- `update_recording` は live capture 専用。`ended_at` をそのまま書く。
- 作り直しは `update_rebuilt_recording` を使う。`ended_at = COALESCE(ended_at, ?)` で、
  **既にある値には触れない**。`ended_at` を持たない行(中断のまま終わった録画)だけ
  `started_at + 実尺` で埋める(捕捉は実時間で進むので、これが捕捉の終わり)。
- `duration_seconds` は `COALESCE(?, duration_seconds)`。測れなかった書き戻しが、測れて
  いた値を消さないようにする。Noneは「据え置き」であって「不明で上書き」ではない。

## 既存行の是正

`scripts/repair_recording_durations.py`。既定はdry-run、`--apply` で書き込む。

`ended_at` は「捕捉の終わりではありえない」ことを証拠で示せて、**かつ正しい値を計算できる
行だけ**直す。置き換える値は常に `started_at + 実尺`。

証拠は2つ:

1. 壁時計が実尺の3倍+1時間を超える。正常な伸びは実測で最大1.6倍なので混ざらない
   (実測の分離: 是正対象は最小10.1倍、非対象は最大1.57倍)
2. `reprocessed_at` と `ended_at` がほぼ同時刻 = 再mp4化が書いた跡そのもの
   (録画直後に作り直した正常な行を巻き込まないよう、壁時計が実尺を明確に超える場合だけ)

### sessions.ended_at を上限に使ってはいけない

一見すると「録画はsessionより後に終われない」ので `sessions.ended_at` が使えそうに見える。
**使えない**。sessionの `ended_at` は最初の切断で埋まり、その後も録画は続く。

実測: session#291 は `disconnected` / `ended_at` 21:12 だが、その配信の録画は 20:36 から
01:18 まで4本続いている。この上限で丸めると 2.7GB の録画が6秒に化ける。

### 尺の出所 — mp4を消した録画でも大抵は残っている

mp4を削除しても、その録画を測って書かれた値は方々に残っている。強い順に:

| 出所 | 中身 | 実測331本での件数 |
|---|---|---|
| 現行mp4 | ffprobe | 119 |
| HLS playlist | EXTINF合計(素材そのものの尺) | 26 |
| `.sidecars/*.timing.json` | `media_duration`(recorderがfinalizeで書く) | 48 |
| `.sidecars/*.thumbs.json` | `sprite.duration_seconds`(サムネ生成時の実測) | 5 |
| `transcripts.duration` | 文字起こし時にmp4を読んだ値(migrationがbackfill) | 28 |
| `_backup/` の退避mp4 | 最後の手段 | 1 |

現行mp4が残る12本で突き合わせた誤差は、timing map が最大3.9秒(2.3%)、thumb sheet は
1本を除き完全一致(その1本は生成後に再mp4化された古い世代で3%差)。直そうとしている
誤差が10〜90000倍であることを思えば十分な精度である。

`_backup` だけは注意が要る。旧経路(concat demuxer)で作った退避は幻の音声穴でtimestampが
伸びており、同じ内容を作り直すと尺だけが数%縮む(実測: 4151秒 → 4000秒、frame数は同一)。
数%長い側に外れうるのを承知で使う — event窓は広い側に外れる方が安全で、狭めると
commentが落ちる。

### 1つも残っていない録画

fileも派生物も削除済みの録画は、**どんなplayerでも測りようがない**(測る対象が無い)。
実測では331本中9本がこれに当たる。

既定では触らない。実害は限定的で、mp4が無い以上その`ended_at`をevent窓として使う経路
(焼き込み・検索index)は動きようがなく、尺は`duration_seconds`がNULLなので画面には
「—」と出る。残るのはanalyticsの録画カバレッジが壁時計ぶん過大になることだけ。

`--clear-broken-ended-at` を付けると、それらの `ended_at` を NULL(不明)にする。上限で
丸めないのは、丸めた値が測った値と見分けられなくなるためで、NULLならカバレッジも
そのsessionを計測不能として正しく除外する。

## 注意

- 列の追加はserver起動時のmigrationが行う。scriptは列が無ければ何もせず止まる
  (schemaの定義箇所が2つに割れると、片方だけ直る状態が生まれる)。
- migrationは文字起こしを持つ録画だけ `transcripts.duration` で初期値を埋める。文字起こしはmp4その
  ものを読んで作られており、fileからの推測ではない。
- 録画カバレッジ(analytics)は壁時計のままでよい。あれは「sessionのどこを録画していたか」
  を問う指標で、動画の長さではない。`ended_at` の是正で正しくなる。

## 障害: 捕捉processが孤児化し、録画行の主が居ないdirへ書き続けていた

serverがきれいに終われば捕捉ffmpegは `Recorder._terminate` が止める。だがserverがその後始末
を通らずに死ぬ経路がある(hard kill・コンソールのCLOSE・native crash)。**Windowsは親の終了で
子を道連れにしない**ので、そのffmpegは生き残る。

実測(2026-08-02): serverのコンソールにCTRLイベントが届き、捕捉ffmpegとSTTの子が同時に
`0xC000013A`(STATUS_CONTROL_C_EXIT)で落ちてserver自身も停止した。過去ぶんを数えると直近60件中
**7件**が孤児に書かれた状態で、孤児が積んだ素材は **12.9 GB**。

| 録画 | 録画行の尺 | dirに実在する素材 | 超過 |
|---|---|---|---|
| 00425_streamer_c_20260801_163324 | **12.0秒** | 16,861.8秒 | +16,850秒 |
| 00426_streamer_c_20260801_165447 | **17.6秒** | 15,576.4秒 | +15,559秒 |
| 00436_viewer_11_20260801_183012 | 12,180.0秒 | 22,564.7秒 | +10,385秒 |

容量だけの話では済まない。再生playlist(`files._finalized_playlist`)はdirの採用集合から
描き直すので、**playerが再生する尺と録画行の尺が別物になる**。文字起こし・切り出し・軸の一致判定は
いずれも素材を読むため、録画行の尺を信じている側が全部ずれる(実測: 素材17.6秒の録画に
2,194秒の文字起こしが付いた)。

孤児を作らせない方法は無い — 強制終了は定義上、後始末を通らない。対処は
`tictok/core/orphan_capture.py` が担う: 捕捉を起こすたびに session dir へ pid と**そのprocessの
作成時刻**を書き(`capture.pid`)、次の起動が両方一致するものだけを止める。作成時刻まで見るのは
pidが再利用されるためで、身元を確かめられない相手には触れない。

**回収は「中断した録画の復旧」より先に行う**(`startup.lifespan`)。復旧は素材を見て録画を
確定させるので、まだ書き続けている孤児が居ると確定した尺が直後から嘘になる。同じ理由で
`manager.restore()`(実配信へ繋いで録画を再開する)よりも前に置く。
