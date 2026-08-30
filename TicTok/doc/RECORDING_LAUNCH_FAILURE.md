# 録画が1 segmentも書けずに終わったときの診断

`録画を開始できませんでした（4回試行、stream接続不良）。` で終わる失敗の原因を、後から
log だけで絞れるようにする仕組み。

## この失敗の何が読めなかったか

捕捉ffmpegは `-loglevel warning` で走る。HTTP error なら `Will reconnect ...` が出るし、
入力に映像が無ければ `Stream map ... matches no streams` が出る。ところが**接続は張れて
いるのにpacketが来ない**型の失敗では、ffmpegは14秒間生きたまま何も書かず、stderrは
0 byteのまま終わる。実測 2026-08-25 08:08〜08:13(`wicha_3111`)は5巡すべてこれで、
`recording.launch_failed` に残るのは `segments: 0` と空のstderrだけだった。

源が止まっていたのか、こちら側が取りこぼしたのかは、この記録からは区別できない。

## 測ること

全試行が空振りで終わった直後、同じstream URLを短時間 `-f null` へ流し、`-loglevel info`
の出力を失敗logへ畳み込む(`Recorder._probe_source`)。読み分けはこうなる。

| 測定の中身 | 読み |
|---|---|
| `Stream #0:0 Video` が出て `frame= 0` / `video:0KiB` | 源が映像を出していない(配信側の断) |
| frameが立ち byte数も増える | 源は出している。落ちているのはこちら側(muxer・keyframe待ち・書き込み) |
| `HTTP error 4xx/5xx` | URLが失効・室が録画不可 |
| `probe_timed_out: true` | 接続は張れるが読めない。源かCDN edgeの停止 |

`recording.launch_failed` の ctx に `probe_cmd` / `probe_exit_code` /
`probe_elapsed_seconds` / `probe_timed_out` / `probe_stderr_tail` が載る。

## log量

- 平常時は増えない。捕捉のloglevelは `warning` のまま、測定は**失敗した録画にしか**走らない。
- 1件あたり 0.6〜1.5KB(健全な源で1.5KB、404で0.6KB)。
- 配信者ごとに `TICTOK_RECORD_SOURCE_PROBE_INTERVAL_SECONDS`(既定600秒)に1回まで。復旧loop
  は失敗を約1分ごとに繰り返すので、間引かないと同じ内容が積み上がり、測定のぶんだけ復帰も
  遅れる。上の5分間の連続失敗(8件)なら測定は1回。
- 2回目以降は `probe_skipped: "throttled"` と直前の測定からの経過秒だけが載る。

## 設定

| env var | 既定 | 意味 |
|---|---|---|
| `TICTOK_RECORD_SOURCE_PROBE_SECONDS` | 8.0 | 測定の長さ。0で無効。`-t` と `-rw_timeout` の両方に効く |
| `TICTOK_RECORD_SOURCE_PROBE_INTERVAL_SECONDS` | 600.0 | 同じ配信者を続けて測らない間隔 |
| `TICTOK_LOG_SOURCE_PROBE_CHARS` | 1200 | 残すstderrの文字数。stream構成・byte数・frame数はすべて末尾に出るのでtailで足りる |

## 採らなかった案

**捕捉自体を `-loglevel info` にする**: 失敗した回だけ上げる術が無い。retry巡から上げると、
その巡が健全化したときに録画が続く限りinfoで書き続けることになり、segmentごとの
`Opening ...` と progress で 1本あたり約1MB/時になる。

**入力byte数をhealth判定へ足す**: `-progress` の常時出力(録画1本あたり0.6MB/時)が要るうえ、
retryの判定そのものを変えることになる。「packetは来ているのにsegmentが出ない」かどうかは
測定の frame数 で同じだけ分かるので、健全な経路には触らない側を採った。
