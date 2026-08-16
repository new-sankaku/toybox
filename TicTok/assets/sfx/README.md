# 効果音（作品の書き出し用）

`tictok/media/sfx.py` の manifest が指す実体の置き場。repo には入れず、初回だけ配布元から
取得して SHA-256 で固定する（`assets/fonts` と同じ方式）。

## 出所とライセンス

すべて [CC0-Public-Domain-Sounds](https://github.com/lavenderdotpet/CC0-Public-Domain-Sounds)
から。repo 全体が **CC0 1.0 Universal**（権利放棄済み）で、帰属表示の義務が無い。

義務のあるライセンスを混ぜないのは、投稿のたびに表記が要る形になり、**それを機械が保証
できない**ため。成果物は人手を介さず出るので、出力のたびに人が表記を確かめる前提は置けない。

| 用途 | file | 元 |
|---|---|---|
| シーンの継ぎ目 | `transition.wav` | `Micro Pack - Organic Wooshes/Swish 4.wav` |
| テロップの出現 | `telop.ogg` | `50-CC0-retro-synth-SFX/synth_beep_03.ogg` |
| ギフト着弾 | `gift.wav` | `MMRetroArcadeSoundsPack1_0_5/Misc/wav/Bell4.wav` |

## どう選んだか

**先に数値の条件を宣言し、満たさない候補は聴く前に落とした。** 52候補を実測して16件しか
通っていない。条件は `sfx.ACCEPTANCE`（尺・立ち上がり・スペクトル重心）と、クリップの
実測（full scale張り付きが0.1%以下）。

重心に下限を置くのは、**人の声（300Hz〜3.4kHz）の中心と主成分がぶつからない**ようにする
ため。落ちた内容にも意味があった —— UI音として配られている `LQ_interface` の一群は
尺800〜1100ms・重心175〜670Hz、つまり声の帯域そのもので、敷けば喋りが濁る。
**名前が「interface」であることは、配信の上に乗せてよいことを意味しない。**

当初は「peak <= -1dBFS」も条件にしていたが、これは測る対象を間違えていた。peakは増幅で
幾らでも動く量で、素材が壊れているかどうかとは別である。クリップの実測へ置き換えた。

## 差し替えるとき

1. `sfx.ACCEPTANCE` の条件を満たすか**先に測る**
2. manifest の `sha256` / `peak_db` / `seconds` を実測値で更新する
3. `tests/test_sfx.py` の `test_every_asset_passes_the_acceptance_rules_it_was_chosen_by`
   が通ることを確かめる

指紋が合わない素材は**代替せずに止まる**。同じ設定なのに機械ごとに違う音が鳴る状態を
作らないため。
