# 保存済み設定値(DB)の検証 (tictok/core/settings.py)

## 直した問題

`Settings.update()` は型・範囲・選択肢・pathを検証し、`int(10.9)` の黙った切り捨てまで拒否する。
`_env_default()` も同じgateを通す。しかし **DB読み込み経路だけが素のcast** だった。

```python
self._values[key] = definition["type"](stored[key])   # try/exceptも範囲checkも無し
```

DBへは `update()` 経由でしか入らない建前だが、`SETTING_DEFS` の type / min / max / options を
後から変更すると、保存された時点では正しかった既存行がその建前を破る。実測した挙動:

| 保存値 | 旧挙動 |
| --- | --- |
| `bucket_seconds="abc"` | `ValueError: invalid literal for int() with base 10: 'abc'` で起動停止。**どのkeyか名乗らない** |
| `bucket_seconds="10.9"` | 同上（storageが `str()` 保存するため切り捨てではなく例外） |
| `bucket_seconds=99999` (max 600) | **黙って通る**。update()なら422で拒否される値 |
| `bucket_seconds=-5` (min 1) | **黙って通る** |
| `clip_default_mode="no-such-mode"` | **黙って通る**。`_validate_choice` の「綴り違いを黙って別の設定として受けると画面と挙動が食い違う」がDB経路には効いていない |
| `record_dir="relative/dir"` | **黙って通る**。`_check_path_shape` を通っていない |

## 採用した設計

DB値も `update()` と同じgate（`_validate_choice` / `_check_path_shape` / `_validate_number`）へ
通す。不正だったときの扱いを、**値が存在するか**で二分した。

### 型として読めない → 起動を止める

走らせる値が存在しないので続行できない。既定値で代替するのはFallback禁止に反する。旧来も起動は
死んでいたので挙動は同じだが、log と例外が key・保存値・label・組み込み既定値・直し方
（設定画面で保存し直す / settings表の該当行を削除する）を名指しする。
event key は `process.settings_db_unreadable`。

### 型は読めるが定義に反する（範囲外・選択肢外・pathのshape不正）→ 起動は続け、値はそのまま

- **既定値へは差し替えない**。差し替えると画面には既定値が現在値として並び、operatorは自分の
  設定が捨てられたことを知る術がない。
- 代わりに全経路で名指しする: ERROR log（`process.settings_db_invalid`、key/保存値/理由/組み込み
  既定値）、ops_events（severity=error。「起動時に不正な設定で走り始めた」は数か月後に再構成
  したい状態遷移）、`describe()` の `invalid` field（適合している間はfield自体を出さない）、
  および `Settings.invalid_values()`。
- `update()` でそのkeyを保存し直すと印は解ける（同じgateを通った証拠なので）。

### なぜ env と扱いが違うのか

`_env_default()` は不正なら即座に起動を止める。理由は `.env` の修正に server が要らないから。
DB値の修正tool は**設定画面そのもの**で、これは server が動いていないと開けない。範囲が動いた
だけで起動を拒むと、その値を直す唯一の画面ごと止まり、sqlite を直接叩く以外に復旧手段が無くなる。

`_load` の既存comment「不正なenvはここで起動を止め、設定画面が開けなくなる形で露見させない」の
意図は「露見はさせるが、operatorが直せる場所で」である。不正なDB値は `describe()` を壊さない
（画面は開く）ことを実測で確認したうえで、DB値ではこれを
**「設定画面が開ける形で露見させる」**として引き継いだ。

## 採らなかったこと

**定義に無い行の警告**: settings表は `store/maintenance.py` が移行済みmarkerを
`_migration:<name>` で置く共有の表でもある。「SETTING_DEFSから消えた設定の残骸」と区別するには
prefixの決め打ちが要り、命名が変われば黙って壊れる（hard-code禁止）。定義に無いkeyは今までどおり
読まないだけにした。

## 公開surfaceの変更

- 追加のみ: `Settings.invalid_values()`、`describe()` entry の `invalid` field（不正なkeyにのみ出現）。
- 既存のgetter・`update()`・`all_values()`・`describe()` の既存fieldは変更なし。
