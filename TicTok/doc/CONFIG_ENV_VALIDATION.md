# 環境変数の型検証 (tictok/core/config.py)

## 直した問題

`config.py` の169個のgetterは「環境変数を1つ読み、型を付け、未設定なら既定値を返す」だけの
関数だが、その型付けは全て手書きで、`int()` / `float()` が107箇所ありながら `ValueError` の
処理は1箇所も無かった。

結果、`.env` の打ち間違い1つが**起動時ではなく、その設定を最初に読む時点**で例外になる。
値の多くはmedia jobの実行中にしか読まれないため、1文字の誤りが数時間後のjob失敗や深い場所の
500として現れ、原因が環境変数だとは分からなかった。真偽値はさらに悪く、真tokenとの一致だけを
見ていたので `TICTOK_AI_ENABLED=ture` は**例外にすらならず**、機能を丸ごと無効にしたまま何も
言わなかった。

## 採用した設計

### 1. 型ごとのhelperへ集約

`_env_int(key, default)` / `_env_float(key, default)` / `_env_bool(key, default)` を用意し、
107箇所のcastを通した。既定値は `os.environ.get` の第2引数の文字列ではなく実型で持つ
(`_env_int("TICTOK_PORT", 8520)`)。getterの名前・signature・戻り型は変えていない。

受理する真偽token: `1/true/yes/on`(真) と `0/false/no/off`(偽)。大文字小文字と前後の空白は
問わない。以前 `on` を受けていたのは `TICTOK_FFMPEG_LOG_KEEP_ON_SUCCESS` だけだったが、
getterごとに受理tokenが違う理由が無いので統一した。

### 2. 不正値は「logを残して例外」。既定値へは落とさない

黙って既定値へ戻すと、設定したつもりの値が効かないまま動き続ける — 打ち間違いより質の悪い
状態になる (CLAUDE.md: No fallback)。logは `tictok.config` へERRORで、keyと生の値と既定値、
および「その行を削除すれば既定値に戻る」という直し方まで含めて出す。例外はjobの深い場所で
握り潰されうるので、原因は必ずlog側にも残す。

例外型は `ConfigError(ValueError)`。helper化前は素の `ValueError` が出ていたため、既に
`ValueError` を捕まえている呼び出し側の挙動を変えないまま、config由来かを `isinstance` で
区別できるようにしてある。

`nan` / `inf` は `float()` を通ってしまうが弾く。閾値として使うと比較が常に偽になり、
「その閾値が効いていない」ことは出力を見ても気付けない。

範囲(最小/最大)はここでは見ない。範囲を持つ設定は `SETTING_DEFS` 側にあり、
`Settings._env_default` が同じ方針(logを残して例外)で既に検証している。

### 3. 起動時に全件まとめて報告する `validate_env()`

getterは呼ばれた時点で例外にするが、それだけでは「その設定を最初に使う機能」を動かすまで
打ち間違いに気付けない。`validate_env()` は引数を取らない全getterを1度ずつ呼び、
**最初の1件で止めずに**全件集めてから `ConfigError` を投げる (1件直しては再起動して次の1件を
見つける、を繰り返させないため)。

import時に自動実行はしない。このmoduleは `logging_setup` 自身からimportされるので、import
時点ではhandlerがまだ無く、「どのkeyがどう不正か」を伝えるlogが出力先を持たない
(`dotenv_summary` のdocstringにある制約と同じ)。

## 起動経路への接続(接続済み)

`tictok/api/runtime.py` の、`.env` 読み込みを報告するlogの直後・`Storage` を開く前で呼ぶ。

```python
try:
    validate_env()
except ConfigError as exc:
    logger.error("起動できません: %s", exc, exc_info=True,
                 extra={"event": "process.config_env_invalid_startup"})
    raise SystemExit(1)
```

instance lockより**前**に置くのが要点。設定が誤っていて起動できないprocessが、その手前で
instance lockと `cleanup_stale_sessions()` を通ってしまうと、**先に動いているprocessのlive
sessionを畳んでから死ぬ**。validate_envは読むだけの検査なので、この位置なら何も壊さずに
引き返せる。失敗の出し方(ERROR log + `SystemExit(1)`)は、同じfileのinstance lock衝突に揃えた。

実測(不正なenv var 3件を与えて起動):

```
INFO  tictok.server 環境設定fileを読み込みました（存在=True 適用=7件）
ERROR tictok.config 環境変数の値が整数として読めません: TICTOK_PORT='85二0'（既定値は 8520。この行を削除すれば既定値に戻ります）
ERROR tictok.config 環境変数の値が実数として読めません: TICTOK_SMILE_THRESHOLD='0.5.5'（…）
ERROR tictok.config 環境変数の値が真偽値(…)として読めません: TICTOK_STT_ENABLED='ture'（…）
ERROR tictok.config 環境変数の設定値が3件不正です。起動前に .env を修正してください: …
ERROR tictok.server 起動できません: 環境変数の設定値が3件不正です: …
（終了code 1。storageの初期化・instance lockのlogはこの後に1行も出ない）
```
