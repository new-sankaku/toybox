# server.py の分割

`tictok/server.py`(7,537行 / route 156本 / top-level 定義 503件)を `tictok/api/` 配下へ
機能別に分けた記録。**挙動は変えていない** — route path・応答の形・status code・error文言は
1文字も動かしていない。

## 層

参照は必ず下向き。上の層を呼びたくなったら層の切り方が違うという合図である。

| 層 | module | 持ち物 |
|---|---|---|
| 1 | `api/runtime.py` | process全体で1つしかない物。log初期化・Storage・単一instance lock・起動時復旧・設定・録画dir解決・avatar/gift cache・通知・collector manager。**tictok.api の他moduleを一切importしない** |
| 2 | `api/files.py` | 録画1行(recordings表のdict)から実体を引く。path解決・素材(.ts)とmp4の実在判定・削除の道連れ範囲・再生variant・尺 |
| 3 | `api/fsfacts.py` | filesystemから引いた事実のTTL cacheと一括取得。一括画面のstatus rollup cacheも同居 |
| 4 | `api/disk.py` | 容量・空き・退避(final dirへの移送)・保持policyの**計算** |
| 5 | `api/media_jobs.py` | 映像jobの永続queueとjob本体(焼き込み・Up出力・再mp4化・音量正規化・ts結合・切り出し・転写) |
| 6 | `api/startup.py` / `api/routes/*.py` | lifespanと起動時処理 / 各router |
| — | `api/access_log.py` | access logと計測のmiddleware、静的fileのcache方針。他のapi moduleに依存しない |

`tictok/server.py` は `app` を組み立てて `main` を出すだけの薄い層として残した
(`main.py` の `from tictok.server import main` はそのまま)。

## routeの分け方

**「誰が何を見に来るか」で切った。route pathの前置きでは切っていない。**

| module | route数 | 範囲 |
|---|---:|---|
| `routes/pages.py` | 12 | 画面(HTML)とavatar画像 |
| `routes/system.py` | 14 | 設定・通知・運用event(ops)・性能計測・DB保守 |
| `routes/monitors.py` | 12 | 監視対象(live中の配信者)とlive中の実況値 |
| `routes/sessions.py` | 10 | 1回の配信の一覧・詳細・battle/collab・export・順位表 |
| `routes/recordings.py` | 18 | 録画を**読む**口(再生・字幕・comment・波形・サムネ・切抜き候補)と削除 |
| `routes/media.py` | 18 | 成果物を**作る**投入とjob台帳 |
| `routes/storage.py` | 10 | 容量・空き・退避・保持policy |
| `routes/bulk.py` | 5 | 一括生成 |
| `routes/search.py` | 19 | 検索(全文・意味)・cut list・bookmark・文字起こしqueue |
| `routes/ai.py` | 5 | comment分析と配信者review |
| `routes/streamers.py` | 13 | 配信者・fan・発見候補 |
| `routes/analytics.py` | 19 | 全体解析 |
| `routes/ws.py` | 1 | websocket |
| **合計** | **156** | |

同じ `/api/recordings/{id}` でも、**読む側が `recordings`・投入側が `media`** に分かれている。
壊れたときに見る場所が違うからで、pathの綴りで揃えても診断の役に立たない。

`_bulk_status_cache` を `fsfacts` へ置いたのは、捨てる契機が他のfs cacheと完全に同じ
(`media_jobs._media_job_runner` の1箇所)ため。無効化点を2つに割らない。

## module間の参照規約(重要)

**`from ... import name` で束ねず、`module.name` と呼び出し時に引く。**

```python
# 駄目 — 自分のbindingを持つので、他所からの差し替えが届かない
from tictok.api.files import _safe_recording_path
_safe_recording_path(path)

# これ — 呼び出しのたびに module から引く
from tictok.api import files
files._safe_recording_path(path)
```

理由は2つ。

1. **testの差し替えが効くこと。** `monkeypatch.setattr(files, "_safe_recording_path", ...)`
   は module の属性を書き換える。呼ぶ側が `from ... import` で束ねていると自分のbindingを
   見続けるので、**patchが効かないのにtestは緑のまま**になる(差し替えは「本物を呼ばせない」
   ためのものが多く、効かなければ本物が走り、たまたま同じ結果になれば通ってしまう)。
2. **循環importを作らないこと。** 名前解決が呼び出し時なので、下の層が上の層の実体を
   import時に必要としない。

この規約が守られていることは `tictok/api/*.py` に
`from tictok.api.<module> import <name>` 形式のimportが1件も無いことで機械的に確かめられる。

唯一「queueがjob本体を呼ぶ」だけは下から上への参照になりかけたので、queue
(`media_job_queue`)をjob本体と同じ `media_jobs` へ置いて解いた。

## 検証

| 見たもの | 結果 |
|---|---|
| route表(path/method/endpoint名/status)の分割前後の一致 | 161 route(うちAPI 156)が**集合として完全一致**。欠け0・余分0 |
| routeの重なり | 同一methodで互いのpatternに一致する組は**0**。routerの取り込み順は一致判定に影響しない |
| 応答class | `route.response_class` は `DefaultPlaceholder` になるが(この版のFastAPIはinclude_routerしたrouteを `_IncludedRouter` の中に置き、解決時期が変わる)、**実requestでint64が文字列へ寄ることを確認済み** — `JsSafeJSONResponse` は効いている |
| test | `pytest -q --ignore=tests/test_e2e_ui.py --ignore=tests/test_ffprobe.py` で **1981 passed / 2 skipped / 0 failed**(分割前と同一) |
| module levelの差し替えが効くこと | 下記 |
| 実起動 | `TICTOK_NO_RESTORE=1` + 空DB + tmp record dir + 別portで起動し、画面11本・API 51本・websocketがすべて200/正常。失敗0 |

### 差し替え(monkeypatch)が効いていることの確認

差し替えには2種類あり、危険なのは後者だけである。

* **objectの属性** (`storage.session_buckets`, `settings.get`, `smile.ensure_smile_profile`,
  `asyncio.create_subprocess_exec` 等) — 実体を書き換えるので、どのmoduleから参照しても
  同じobjectに当たる。moduleの置き場所が変わっても壊れない。
* **module levelの名前の張り替え** (`setattr(runtime, "RECORD_DIR", ...)` 等) — 呼ぶ側が
  自分のbindingを持つと届かない。**これが本命。**

後者について、差し替える値を「触れば必ず落ちる毒」へすり替え、対象のtestが**確かに落ちる**
ことを1件ずつ確認した。落ちなければその差し替えは死んでいる(本物が走っている)。
検査したのは23種類・122箇所で、**105箇所が落ちた**。落ちなかった17箇所は内訳まで確かめてあり、
向き先の誤りは1件も残っていない:

* 8件 `fsfacts._recording_has_hls` — testのhelperが同時に `_bulk_hls_batch` も差し替えて
  `facts["has_hls"]` を先に埋めるので、`_bulk_classify` の遅延fallbackへ入らない。
  **分割前のcodeも同じ構造**なので分割で生じた話ではない。bindingが生きていることは、
  factsを埋めずに `_bulk_classify` を呼んで差し替えた側が呼ばれることで別途確認した
* 1件 `media_jobs._duration_seconds` — 同じtestの中で後からもう一度同じ名前を差し替えており、
  先の差し替えは上書きされる(後の1件は落ちる)
* 8件 — そのtestが早い段階の失敗や短絡を主張するもので、差し替えた経路まで到達しない。
  いずれも**同じ対象を別のtestが落としている**ので向き先は正しい

なお `runtime.FINAL_DIR` は21箇所で落ち、落ちなかった2箇所は該当testがFINAL_DIRを読まない
経路だった。

`_duration_seconds` のように**同じ名前でもtestごとに呼ぶ経路が違う**ものがある。
これは経路ごとに向き先を変えている:

| test | 向き先 | 理由 |
|---|---|---|
| `_restore_reprocess_backup` 系 | `startup` | 中断jobの後始末が呼ぶ |
| 音量正規化 | `media_jobs` | `_audionorm_recording` が呼ぶ |
| 切抜き候補 | `routes.recordings` | 候補算出が呼ぶ |

## 触っていないもの

* 性能改善(`asyncio.to_thread` 化など)は**一切していない**。別の波の担当
* comment と docstring は行span単位で切り出したため1文字も落ちていない
* `tictok/storage.py`, `tictok/core/config.py`, `tictok/media/`, `tictok/record/`,
  `tictok/search/`, `static/` には触っていない
