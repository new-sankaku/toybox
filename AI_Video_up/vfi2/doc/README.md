# vfi2 — フレーム補完の再設計と高速化

`vfi/`(1巡目、素直な x2 の検証)の続きです。1巡目の結論は
`../../doc/フレーム補完_計測結果.md` にあります。

## 何が問題だったか

素直な x2 は「絵の枚数」を倍にしますが「保持時間」を均しません。
B_talk(会話)の実測:

| | 元 (23.976fps) | 素直なx2 (47.952fps) |
|---|---|---|
| 絵の枚数 | 132 | 257 |
| 保持長で最も多い物 | 3 frame が 86件 | 1 frame が 134件 / 5 frame が 85件 |
| 保持時間 p50 | 125 ms | 21 ms |

出力は `元の絵×5(104ms) → 作った絵(21ms) → 元の絵×5(104ms) → …` という形で、
作った絵は 21ms しか映りません。これが「効果が出ていない」の正体です。

## 担当

| doc | 担当 | 内容 |
|---|---|---|
| `診断.md` | shindan | 効果が出ない理由の定量化と、滑らかさ metric の設計 |
| `model比較.md` | models | RIFE 以外を含む model の速度・品質・任意 tau 対応 |
| `高速化.md` | speed | decode/推論/encode の再設計と実測 |
| `時刻張り直し.md` | retime | 絵の列に対する補間と時刻の張り直し(中心施策) |
| `使い方.md` | tool | 実運用 tool (`../vfi.py` と `2_動画_アニメ_フレーム補完_47fps.bat`) の説明書 |

生の記録は `../results/results.jsonl` に1件ずつ追記されます。

## 滑らかさの指標 — `smooth.py`

チーム全体でこの2つを見て良し悪しを決めます。どちらも単位は px、0 が完璧。

| 指標 | 意味 | frame rate を上げると |
|---|---|---|
| `lag_px` | 作画された絵と絵の間を等速で動いたとみなしたときの、**画面に出ている絵の位置のずれ**(時間平均) | **下がらない**。保持時間で決まる |
| `step_px` | 隣接する出力 frame 間の変位 p95。1枚あたりの跳び幅 | 反比例して下がる |

素直な x2 が `step_px` しか動かさないことが「効果が出ない」の正体です。
誤差は frame の**表示区間の中央**で測ります(先頭で測ると、標本の少ない
低 fps ほど誤差が過小に出て、24fps 1コマ打ちの素材が lag=0 になります)。

```python
import smooth

smooth.measure(video, src_clip, fps_out=None, move_min=16, tag=None, record=True) -> dict
    # video    出力 file の path / lib.CLIPS の clip 名 / scan_frames() の戻り dict
    # src_clip 元素材の clip 名。絵の切り替わり時刻と cut をここから採る
    # 戻り: lag_px lag_p95_px lag_rel step_px step_p95_px step_cv
    #       drawings drawing_rate hold_ms_p50 hold_ms_p95 new_pct
    #       frames fps dur_s covered
    # results.jsonl へ kind="smooth" で自動追記されます

smooth.scan(video, move_min=16) -> dict(grays, starts, n, w, h, fps, key)
    # 1回の走査で「480x270 gray の全frame」と「絵の切り替わり位置」を得る

smooth.scan_frames(frames, key, w, h, fps, move_min=16) -> 同上
    # 生成した frame の列(BGR24 uint8 の numpy か cuda tensor)をその場で測る。
    # 1080p を lossless で置くと1本 9GB になるので、file にしないで済ませる用

smooth.gap_spans(clip) -> (gaps, spans)
    # 隣接する絵の組 [(a,b), ...] と、その間の変位 p95(px)。
    # model が実際に跨ぐ量そのもの。32px を超えると model は単純平均に負ける

smooth.displacements(grays, pairs=None) -> np.ndarray  # 変位 p95(px)
smooth.gaps_of(clip) -> [(a, b), ...]                  # cut を跨がない絵の組
```

結果は cache されます(`results/smooth/`)。`scan_frames` の `key` は
中身が変われば変えてください(変えないと古い cache が返ります)。

**注意**: `lag_px` は「素材の絵が置かれている時刻」を正解とみなします。
`retime.py` の `even_anchors`(shot 内で絵の時刻を等間隔へ均す)を使うと、
均した量がそのまま `lag_px` に乗ります。これは指標の欠陥ではなく、
**絵の表示時刻を動かすこと自体が元の意図からのずれ**だという立場です。
