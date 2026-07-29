# storage.py の分割（mixin 方式）

`tictok/storage.py` は 6,109 行・単一 class に 208 method を持っていた。domain 別の
mixin へ分け、`tictok/store/` 配下の 15 file にした。**公開 API（`Storage` の method 名・
signature・戻り型）は変えていない。SQL も schema も lock 取得順も変えていない。**

## なぜ mixin なのか（他の手段を採らなかった理由）

この class の method 同士は「lock を保持したまま呼ぶ / 呼ばない」という契約で結合している。
名前が `_locked` で終わる method は、呼び出し元が `self._lock` を保持している前提で書かれて
おり、その前提の上で「判定 → INSERT → commit」を同一 lock 区間へ収めている。

独立 class へ切り出して各自が接続や lock を持つ形にすると、この契約が壊れる:

- **deadlock**: 現在の取得順は `_lock -> _buf_lock` の一方向だけ。lock の所有者が増えると
  逆順が生まれ得る。負荷と timing に依存するので、test では出ない。
- **atomicity 喪失**: batch writer は buffer の入れ替えから commit までを 1 区間で行う。
  区間を割ると、障害時にだけ「一部だけ入った」状態が生まれる。平常時は誰も気づかない。

mixin なら `self` は 1 つのままなので、契約はそのまま成立する。`Storage` が接続と lock を
1 組だけ所有し、mixin はそれを借りるだけである。**mixin は接続も lock も持たない。**

delegate（lock を持つ core object へ委譲する sub-object 群）も候補だったが、`self.` を
`self._core.` へ書き換える必要があり、208 method すべてに手が入る。code motion で済む
mixin と違い、書き換え漏れが挙動差になる。分割の目的が「長さ」である以上、本文に触らない
手段を選んだ。

## lock の所有と取得順

lock は 5 本。所有者はすべて `Storage`（`__init__` で生成）で、取得順は
`_lock -> _buf_lock` の一方向だけが存在する。他は互いに入れ子にしていない。

| lock | 守るもの |
| --- | --- |
| `_lock` | 書き込み接続 `self._conn` の直列化 |
| `_buf_lock` | batch writer の buffer（`_event_buffer` / `_viewer_buffer` / `_pending_users`） |
| `_read_lock` | 重い集計 read 専用接続 `_LockedReader` の直列化 |
| `_journal_lock` | 耐久 journal の file handle |
| `_ops_fail_lock` | ops_events 書き込み失敗の計数 |

`_locked` 接尾辞は既定で `_lock` を指す。例外は `_journal_handle_locked` で、これは
`_journal_lock` 保持前提（DB 接続には触れないため `_lock` とは独立）。

## 分割境界

| module | class | 境界 |
| --- | --- | --- |
| `_common.py` | （なし） | 定数・SCHEMA・純粋 helper・`logger`・`_LockedReader` |
| `maintenance.py` | `MaintenanceMixin` | DB 保守（退避・integrity・VACUUM）と schema migration |
| `ops_events.py` | `OpsEventsMixin` | ops_events（Layer2: 状態遷移の DB 記録） |
| `ai_cache.py` | `AiCacheMixin` | AI 分析結果の cache |
| `ingest.py` | `IngestMixin` | batch writer・耐久 journal・event 投入 |
| `sessions.py` | `SessionsMixin` | session lifecycle と従属表（markers / buckets / envelopes / collab） |
| `users.py` | `UsersMixin` | User 名寄せ・配信者 handle 解決・Fan 台帳・発掘候補 |
| `battles.py` | `BattlesMixin` | Battle と gift 貢献の集計 |
| `streamers.py` | `StreamersMixin` | 配信者別集計画面と全体 dashboard |
| `analytics_store.py` | `AnalyticsMixin` | 全体解析の session 単位 cache と集計 API |
| `recordings.py` | `RecordingsMixin` | 録画 row と容量・退避の観測 |
| `transcripts.py` | `TranscriptsMixin` | 文字起こし・横断検索・切り出し・見どころ |
| `media_jobs.py` | `MediaJobsMixin` | 映像 job queue の状態機械 |
| `settings_store.py` | `SettingsMixin` | 設定値と監視対象 |

境界を選んだ理由は各 module の docstring に書いてある。特に `ingest.py` は
**lock 区間そのもの**であり、読まずに触ると事故る。

`_locked` method は、呼び出し元と同じ module へ置くことを優先した。例外は cross-domain な
3 群で、それぞれ docstring に「誰が lock 区間の内側から呼ぶか」を書いてある:

- `_upsert_user_locked`（users）← `_upsert_users_locked`（ingest）/ `_backfill_users`（maintenance）
- `_owner_handles_locked` / `_latest_owner_handles_locked`（users）← streamers / sessions
- `_refresh_session_analytics_locked`（analytics）← sessions の `finalize_session` / ingest の `recover_from_journal`
- `_recompute_session_stats_locked` / `_rebuild_buckets_locked`（sessions）← ingest の `recover_from_journal`

## 契約の機械的な検査

docstring だけが契約を保証している状態を改善するため、静的検査を用意した。

```bash
venv/Scripts/python.exe scripts/check_storage_locks.py
```

検査する事:

1. lock の取得順が `_lock -> _buf_lock` の一方向だけであること
2. `_locked` method が、要求する lock を保持しない場所から呼ばれていないこと
   （別 mixin の呼び出し元も、間接呼び出しも辿る）
3. `_drain` の本体が単一の `with self._lock:` 区間で、commit がその内側で完結すること

分割の前後でこの出力を突き合わせ、契約が 1 文字も変わっていないことを確認してある。
**storage の lock まわりに手を入れたら、この script を通すこと。** deadlock も atomicity
喪失も test には出ない。

## 互換性

`tictok.storage` は分割前に公開していた名前をすべて公開し続ける（`__all__` に列挙）。
実体は `tictok/store/_common.py` にあり、`storage.py` は再 export である。したがって
`from tictok.storage import Storage, OPS_ERROR, SCHEMA, _identity_key, ...` はそのまま動く。

`logger` も `_common.py` が 1 つだけ持ち、名前は `"tictok.storage"` のまま。mixin へ分けても
log の出所名は変わらない（module 別に log を抽出する運用が、分割で壊れてはならない）。

### 移動に追随が要る書き方

module path を文字列で名指しする monkeypatch だけは追随が要る。今回の分割で 2 箇所:

```python
# 分割前
monkeypatch.setattr("tictok.storage.get_ops_events_query_limit", ...)
# 分割後
monkeypatch.setattr("tictok.store.ops_events.get_ops_events_query_limit", ...)
```

`from tictok.storage import X` 形式の import は再 export で吸収されるので変更不要。

## in-memory cache の上限

`Storage` が持つ in-memory cache は 2 つだけで、どちらも**挿入順の古い方から 1/4 をまとめて
捨てる**同じ方式で上限を持つ。同じ class に 2 種類の cache 戦略を並べない。

| cache | 上限定数 | 所有 mixin | 母数 |
| --- | --- | --- | --- |
| `_battle_contrib_cache` | `_BATTLE_CONTRIB_CACHE_MAX` = 2000 | `battles` | 終了済み Battle の貢献集計 |
| `_user_cache` | `_USER_CACHE_MAX` = 40000 | `users` | upsert 間引き（TTL 60 秒） |

`_event_buffer` / `_viewer_buffer` / `_pending_users` は cache ではなく batch writer の
buffer で、0.2 秒ごとに drain される。積み上がった状態そのものが異常なので、上限では
なく backlog 警告（`get_storage_backlog_warn_rows`）で扱う。

### `_USER_CACHE_MAX` を 40000 にした根拠（実測）

| 測った物 | 値 |
| --- | --- |
| 1 session あたりの distinct identity_key の最大 | 8,642 |
| 同時進行 session の最大数 | 4 |
| **TTL(60秒)窓あたりの distinct identity_key の最大（全 session 合計）** | **258** |
| events 全体の distinct identity_key | 78,355 |
| cache 1 entry の実測 size | 875 byte |

上限は「同時進行 session がそれぞれ最大数の user を載せても入り切る」= 4 × 8,642 = 34,568
に余裕を足した値。上限で溢れると TTL 内の再 upsert が DB 書き込みへ戻るので、hit 率を
落とさない側へ倒してある。

hit を生み得るのは直近 60 秒に現れた user だけで、それは 258 件しかない。上限はその 150 倍
以上なので hit 率への影響は無い。捨てられるのは「もう二度と参照されない古い行」である。

代償は memory で、上限まで埋まると約 33MB（`avatar` の URL が entry size の大半）。
上限が無い状態にはそもそも天井が無く、identity 数ぶん伸び続ける。

`_USER_CACHE_MAX` は `tictok.storage.__all__` には入れていない。あの `__all__` は
「分割前の `tictok.storage` が公開していた名前」の記録であって、新しい定数を足すと
その意味が壊れる。参照は `tictok.store._common` から行う。

## mypy

`tictok.store.*` は package 単位で `ignore_errors` にしてある（pyproject.toml）。mixin 単体では
`self._conn` / `self._lock` の出所が解決できず `attr-defined` が大量に出るためで、個々の code
不備ではない。昇格するには、共有属性を宣言した Protocol を各 mixin の base に置く。
