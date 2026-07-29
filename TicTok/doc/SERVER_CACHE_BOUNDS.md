# server側cacheの上限 (tictok/api/fsfacts.py)

## 直した問題

fsfactsの3つのcacheはTTLで「その値がまだ正しいか」しか見ておらず、**期限切れのentryを消す者が
いなかった**。keyは録画のpath(と一括画面の要求種別)なので、processが見たpathの数だけ単調に
伸び続ける。restartでしか縮まない。

## 上限値の根拠(実測)

### `_fs_state_cache` / `_fs_bulk_cache` — `_FS_FACTS_CACHE_MAX = 4000`

上限は**録画数を下回ってはいけない**。一覧のpollは毎回全録画をstatしに来るので、上限が録画数
より小さいと同じpoll中に自分で自分を追い出し、cacheが防ぐはずだったstatの嵐へ戻る。

実測(tictok.db, 2026-07-29):

| 項目 | 実測値 |
| --- | --- |
| 録画数 | 374本 |
| 観測期間 | 43.1日 |
| 増加ペース | 8.68本/日 |
| path長 | 平均69.5文字 |
| 1 entry | `_fs_state_cache` 264 byte / `_fs_bulk_cache` 1,110 byte |

4000は現在の録画数の10倍強で、この増加ペースのまま **約418日(1年以上)連続稼働**しても最初の
1件も捨てない。上限まで埋まってもmemoryは両方で約5.5MB。restartで空に戻るので、これは「捨てる」
ための値ではなく「際限なく伸びない」ための天井である。

### `_bulk_status_cache` — `_BULK_STATUS_CACHE_MAX = 256`

keyは要求種別を並べた文字列(`",".join(sorted(requested))`)なので、正当なkeyは `BULK_KINDS`
7種の空でない部分集合ぶん = **127通り**しかない。それでも天井が要るのは、keyが要求文字列から
作られていて重複が別keyになるため:

```
?kinds=overlay            -> "overlay"
?kinds=overlay,overlay    -> "overlay,overlay"        # 別entry
?kinds=overlay,overlay,…  -> 長さの数だけ別entry
```

正当な種別だけを並べても、長さの数だけkeyが増える。127の2倍を上限にすれば通常の利用で捨てる
ことは無く、重複による増殖だけが頭打ちになる。1 entryは実測4,365 byte(配信者3名ぶんの集計)。

## 実装

`_BoundedCache(dict)` を1つ置き、3つのcacheをそれで作る。`dict` を継承しているのは、書き込み側
の1つ(`routes/bulk.py` の `_bulk_status_cache[key] = …`)がfsfactsの外に在るため。上限の判断を
代入そのものへ載せておけば、書き込み点が増えても捨て忘れが起きない。`.get` / `.clear` / `in`
はdictのままなので、**無効化点を `media_jobs._media_job_runner` の1箇所に揃えてある構造**は
変わらない(`_bulk_status_cache` を fsfacts に同居させている理由もそこにある)。

捨てるのは**新しいkeyを載せるときだけ**、古い方から1/4。既存keyの更新ではdictは伸びないので、
そこで捨てるとTTL内の生きたentryを巻き添えにhit率だけが落ちる。方式・比率とも
`tictok/store/_common.py` の `_USER_CACHE_MAX` に揃えてある(dictは挿入順を保つ)。
