# 再生音量の均し（gain曲線）

配信ごと・場面ごとの音量差を、**録画のfileを1 byteも書き換えずに**再生時だけ揃える。
serverが録画を測ってgainの時系列(曲線)をsidecarへ持ち、再生画面がGainNodeでそれを当てる。

実装は `tictok/media/loudness.py` の1箇所。目標ラウドネスと天井は音量正規化
([AUDIO_NORMALIZE.md](AUDIO_NORMALIZE.md))と同じ設定を読む — 同じ「どこへ揃えるか」を経路
ごとに別の値で持つと、再生で聞いた音と出力した音の高さが食い違う。

| 設定 | 既定 | 効く先 |
| --- | --- | --- |
| `playback_gain_enabled` | 1 | 再生時に揃えるかどうか |
| `playback_gain_max_boost_db` | 12.0 | 持ち上げる上限 |
| `playback_gain_max_cut_db` | 12.0 | 下げる上限（天井を守る引き下げはこれに縛られない） |
| `audio_normalize_lufs` | -14.0 | 目標ラウドネス（音量正規化と共有） |
| `audio_normalize_true_peak` | -1.5 | 天井（音量正規化と共有） |
| `gain_sweep_per_start` | 10 | 1回のsweepで自動生成する本数 |

## なぜ音そのものを正規化しないのか

録画の原本は素材(.ts)で、mp4はそこから作り直せる派生物である。素材を正規化して置き換えると
**素の音声はどこにも残らない**。退避(`_backup/`)は保険にならない — `backup_keep_days` の既定は
0で、完走直後にvideo frame数の一致だけを見て消す。映像はstream copyなので常に一致し、
**音の異常はこの判定を素通りする**。

素材をsegment単位で正規化することもできない。segmentは約2秒刻みで、one-pass loudnormは
3秒先読みの動的normalizerである。先読み窓より短い単位に切って個別に掛けると、gainの状態が
2秒ごとにresetされ、境界ごとに音量が跳ねる。全長を連続decodeして切り直せば直せるが、それは
`hls_pack` がbyte連結で守っているsegmentの同一性と `segments.json` のwall軸を壊し、
コメントの時刻が静かにずれる。

そこで**音は触らず、当てるべきgainだけを持つ**。原本は無傷のまま、HLS再生でもmp4再生でも
同じ曲線が効き、checkboxを切ればその場で素の音へ戻る。

## 測る

`ebur128`(EBU R128の参照実装)と `astats` を1本のfilter chainへ並べ、0.1秒ごとに
short-termラウドネス(S, 3秒窓)と区間の最大sample level(P)を取る。

```
aresample=async=1:first_pts=0:osr=48000,
asetnsamples=n=4800:p=0,
astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=Peak_level,
ebur128=metadata=1,
ametadata=mode=print:file=-
```

- **`ametadata` は1本だけにする。** key指定の `ametadata` を2本並べて同じstdoutへ流すと、
  filterごとに別のbufferを持つため行が途中で混ざる（実際に `frame:568level=-27.9` という
  壊れた行を踏んだ）。astats側を `measure_overall=Peak_level` に絞ることで、1本のまま
  必要な2値が揃い、1 frameあたり8行に収まる。
- **`asetnsamples` で1 frameを0.1秒に固定する。** これを置かないとmetadataの間隔がcodecの
  frame長(AACなら約21ms)になり、行数が5倍に膨らむ。
- **`aresample=async=1:first_pts=0`** は波形生成と同じ理由。録画はHLS由来で音声に欠落区間が
  あり、埋めないとsample数が尺より短くなって曲線が末尾へ向かってずれる。
- ebur128の `true_peaks_ch*` は**stream全体の走行最大**で、区間ごとの値ではない。この build には
  `true_peaks_per_frame_ch*` が無いため、区間peakはastats側から取る。

実測: 2.9時間の録画で **16.9〜19.3秒**（実時間の540〜620倍）、metadata 23MB・83万行。
GPUは使わない。

## 曲線にする

`build_curve()` の4段。

1. **Sを窓の中心へ戻す。** ebur128のSは `[t-3s, t]` を測った値なので、そのまま当てると
   常に1.5秒遅れる。
2. **R128と同じgateを掛ける。** 無音や間まで目標へ持ち上げると、息継ぎがすべて増幅されて
   「呼吸」が出る。絶対gate(-70 LUFS)と相対gate(統合ラウドネス -10 LU)を外れた区間は、
   直前の有効なgainを保持する。有効な区間が1つも無い録画(全編が無音)は素通し(0 dB)。
3. **peakで頭を押さえる。** `天井 - (3秒窓のPの最大)` を上限に取る。窓は中心揃えなので
   `P[i] <= 窓max[i]` が常に成り立つ。
4. **slewで滑らかにする。** 逆方向passで「下げ」を先回りさせ(6 dB/秒)、順方向passで
   「戻り」を抑える(2 dB/秒)。どちらも値を**下げる向きにしか動かさない**ので、3の上限が
   そのまま守られる。

### 天井を超えないことは構成上保証される

3と4の性質から `gain[i] <= 天井 - P[i]`、すなわち `P[i] + gain[i] <= 天井` が必ず成り立つ。
**だから再生側にlimiterを置かない。** 因果的な一極smoothing(attack/releaseの時定数)にすると
下げが後追いになり、この保証は消える — 実際に一極版では適用後peakが +1.2 dBFS まで出た。

## 実測（2.9時間の録画・30分抜粋を実際に音へ適用してebur128で測り直した）

| | 統合ラウドネス | 短期音量の広がり(p90-p10) | sample peak | true peak |
| --- | --- | --- | --- | --- |
| 元音声 | -26.4 LUFS | 9.6 LU | 0.00 dBFS(clip) | +0.6 dBFS |
| **gain曲線** | -16.6 | **8.3** | **-1.50** | -1.2 |
| loudnorm one-pass | -14.3 | 6.8 | -1.04 | -1.5 |

録画全体(2.9時間)では広がり **17.1 → 9.4 LU**。

loudnormに一歩届かないのは**原理的な差**である。あちらは波形を書き換えるlimiterを持つので
crest factorを詰められる。こちらはgainだけなので、peakの分だけ持ち上げられない。音を
書き換えない選択の代償がこの差で、天井を上げても埋まらない。

天井は `audio_normalize_true_peak`(true peakの指定)を共有するが、ここで測るのは
**sample peak** である。上表のとおり実際のtrue peakは0.3 dBほど上に出る(-1.5指定で実測-1.2)。
full scaleまではまだ1.2 dB あるので、再生でclipすることはない。

## 自動生成

sweepが積む種別の1つ(`gain`)として、音声波形・サムネ・無音skipの解析と同じ経路で自動生成
される([STARTUP_SWEEP.md](STARTUP_SWEEP.md))。種別→fact名→設定keyの対応は
`fsfacts.SIDECAR_JOB_FACTS` / `SIDECAR_SWEEP_SETTINGS` の1箇所にあり、sweep・一括処理・
ts結合後の投入がすべて同じ表を読む。

- 起動時と定期sweepで `gain_sweep_per_start` 本ずつ積む。0でこの自動処理を止める。
- ts結合の直後にも積む。ts結合は素材の本数・byte・mtimeを変えるので、先に作った曲線は
  指紋が外れて作り直しになる。
- 一括処理tabの種別(`gain`「再生gain曲線」)にも並ぶ。出力fileを作らないので、無音skipの解析と
  同じく投入前の空き容量判定を通さない([BULK_GENERATION.md](BULK_GENERATION.md))。
  一括の「済み」判定はsidecarの**実在だけ**を見るので、目標ラウドネスを変えた後に作り直す
  ときは「出力済みも作り直す」を入れること。

cacheは `.sidecars/<stem>.gain.json`（2.9時間の録画で573 KB）。指紋(mtime+size、.ts録画では
segmentの本数・合計byte・最新mtime)と**目標値**が一致する限り再測定しない。目標を変えたのに
前の曲線を返すと、設定を変えても音が変わらない。

## 再生側

`/api/recordings/{id}/gain` が曲線を返す。設定で無効なら `enabled: false` だけを返す —
0 dBの曲線を返すと、画面側は「揃えた結果たまたま0 dB」と区別が付かない。

画面(`static/videos.js`)は `<video>` の音声を `MediaElementAudioSourceNode → GainNode →
destination` へ通し、再生位置から曲線を引いて当てる。

- **AudioContextとsource nodeは `<video>` 1つにつき1回しか作れない**(2度目は
  InvalidStateError)。録画を切り替えても同じ `<video>` を使い回すので、graphはmodule levelに
  1組だけ持つ。曲線が実際に要るまで作らないのは、作った時点で音声が必ずgraphを通るように
  なるためで、使わない利用者の再生経路を変えない。
- **自動再生policyでAudioContextはsuspendedで生まれる。** resumeを忘れるとgraphを通した音声が
  丸ごと無音になる(音量が揃わないのではなく鳴らない)。再生操作のたびに起こす。
- 当てるのは再生中だけ(rAF)。止まっている間は位置が動かないので1回当てて降りる。
- **無言早送り**が下げる `video.volume` とは掛け算で重なるだけで、どちらも相手を知らなくてよい。
- Web Audioが使えない・曲線を取れない場合は**理由を名乗る**。黙って素の音を流すと、
  揃っていない音を揃ったものとして聞かせることになる。

## 関連

- [AUDIO_NORMALIZE.md](AUDIO_NORMALIZE.md) — 出力側(切り出し・焼き込み・Up出力)と、
  mp4そのものを差し替える「音量正規化」操作
- [STARTUP_SWEEP.md](STARTUP_SWEEP.md) — 自動生成の周期と候補の選び方
- [PACE_TALK.md](PACE_TALK.md) — 同じ再生画面で音量を触るもう1つの機能
