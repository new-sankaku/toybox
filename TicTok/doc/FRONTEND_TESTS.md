# 画面(static/)のtest

Python側は `tests/` に一式あるが、`static/` の JS は長らくtestが0件だった。
この文書はそこへ入れた2層のtestの走らせ方と、なぜその形にしたかを残す。

| 層 | 道具 | 対象 | 実行 |
|---|---|---|---|
| unit | vitest + jsdom | `static/*.js` の関数・DOM描画 | `npm test` |
| E2E | pytest + playwright | 実serverを起こしてheadless Chromiumで11画面 | `pytest tests/test_e2e_ui.py` |

## 走らせ方

### unit (vitest)

```bash
cd TicTok
npm install          # 初回だけ
npm test             # 1回走らせる
npm run test:watch   # file変更で走らせ続ける
npm run test:coverage
```

coverage は全体 39.2% / 分岐 77.8% / `common.js` 68.1%。行数そのものは狙っていない —
**壊れたときに画面が黙って嘘をつく分岐**を優先して埋めているので、見るなら分岐のほうである。

Node 20以上が要る。`node_modules/` と `coverage/` はrepo rootの `.gitignore` で除外済み。

### E2E (playwright)

Python側の playwright を使う。node側へ2つ目のplaywrightは入れない。

```bash
cd TicTok
venv/Scripts/python.exe -m playwright install chromium   # 初回だけ (Linux: venv/bin/python)
venv/Scripts/python.exe -m pytest tests/test_e2e_ui.py -q
```

Chromiumの実体が無い環境では自動でskipする(判定は
`tests/test_e2e_ui.py` の `_require_browser`)。`slow` markerが付いているので
`pytest -m "not slow"` で外せる。

### playwrightは async API を使う(sync APIは使えない)

**sync API (`sync_playwright`) はこのrepoでは使えない。** driverをgreenlet上の専用
event loopで回すため、`sync_playwright()` が開いている間ずっと**そのthreadの
running loopが設定されたまま**になる。実測:

```
inside with-block: running_loop=<ProactorEventLoop running=True> asyncio.run=FAIL
after exit:        running_loop=None                             asyncio.run=OK
```

`pytest.ini` は `asyncio_mode = auto` なので、pytest-asyncioは各testで
`asyncio.Runner.run()` を呼ぶ。上の窓の中でそれが走ると
`RuntimeError: Runner.run() cannot be called from a running event loop` で落ちる。

これを **session scopeのfixtureで開くと窓がsession全体に広がる**。実際にそれをやって、
`test_e2e_ui.py` 以降のasync testを259件巻き添えにした(alphabet順で次に来る
`test_ffprobe.py` から全滅した)。単独実行では通るので、file単位のtestでは見つからない。

async API (`async_playwright`) ならpytest-asyncioと同じloopに乗るので、この問題自体が
起きない。**根本解決なのでこちらを採る。** 代案として検討した「別processへ隔離」は、
症状を隠すだけでCIに載せた時点で同じ問題に戻るため採らなかった。

その代わり、async fixtureのloop scopeは `asyncio_default_fixture_loop_scope = function`
に従う。`browser` をsession scopeにするとloop scopeが食い違うため、**testごとに
Chromiumを起こす**。起動は1秒未満で、serverのほうは session scope で使い回すので実害は小さい
(E2E 16件で約44秒)。

`ui_server` fixtureは subprocess と urllib だけで書く。ここはsessionを跨いで生きるので、
event loopに触れる物を置くと同じ事故が再発する。

### E2Eを足したら必ず全体suiteで回す

```bash
venv/Scripts/python.exe -m pytest -q      # 2014 passed / 2 skipped
```

`pytest tests/test_e2e_ui.py` が通ることは検証にならない。上の事故は
**他fileとの干渉**なので、単独実行では原理的に見えない。

## E2Eの隔離: 本番の録画資産へ触れさせない

> **確認のためにserverを1回起こすだけで、実配信へ接続して録画fileをdiskへ書く。**
> userのserverが同じ配信を録画していれば**二重録画**になる。
> `TICTOK_NO_RESTORE=1` を付けずにserverを起こしてはいけない。

これは「起こり得る」話ではなく、2026-07-20に**2回実際に起きている**。1回目は本番server
がfileを掴んでいてPermissionErrorで止まった(実害なし)。2回目は書き込みまで到達した:

- 実配信roomへ接続し、新規sessionとして二重録画(ts 40 segment / 9.8MB)
- 録画途中のHLSから114MBのmp4を**本番pathへ**早期生成
- 失敗した解像度正規化の17MB log残骸

本番DBと本番録画そのものは無事だったが、実録画dirに孤児fileが残った。
**実害で済むかはタイミング次第**である。

### 隔離の4条件

`tests/test_e2e_ui.py` は次の4つを**同時に**満たしてからserverを起こす。1つでも欠けると
隔離は崩れる。

| # | 条件 | 何を止めるか |
|---|---|---|
| 1 | **空のDB**(本番DBのcopyではない) | 監視対象0・中断録画0 → 復元も回収も走らない |
| 2 | **tmp配下の record / log / journal / sample dir** | 成果物が本番dirへ落ちない |
| 3 | **`TICTOK_NO_RESTORE=1`** | 前回の監視対象の復元 = 実配信への接続 |
| 4 | **空きport** | userのserverと同時に動かせる |

instance lockは `<db path>.lock` なので、4がそろえばuserのserverを止めずに並走できる。

### `TICTOK_NO_RESTORE=1` が必須である理由

既定の起動は**前回の監視対象をそのまま復元する**。復元とは「そのTikTok IDのLIVEを見に行く」
ことなので、serverを上げた瞬間に実配信へ接続し、LIVE中なら録画を始めてdiskへ書く。
「画面を見たいだけ」の起動でこれが走る。

`tictok/core/config.py` の `get_no_restore` にも同じことが書いてある。CI・静的解析・
手動検証はこれを1にして起動する。監視の追加・削除操作そのものは通常どおり効くので、
**機能検証の妨げにはならない**。

**ただし `TICTOK_NO_RESTORE=1` だけでは不十分**。これが止めるのは監視対象の復元だけで、
起動時の**中断録画の回収**(`_recover_interrupted_recordings_bg`)は止まらない。回収対象は
DBの録画行から引かれるので、**空DBであること**(条件1)が同時に要る。この2つは
どちらか一方では効かない。

### 本番DBのcopyで起動してはいけない

`record_dir` / `record_dir_final` は**DBのsettings表**にあり、解決順は **DB > env**。
本番DBをcopyして起動すると、`TICTOK_RECORD_DIR` を渡しても**本番の録画folderを掴む**。
そこへ上の「中断録画の回収」が重なると、検証serverが本番の録画中mp4に対して回収と
解像度正規化を試みる。2026-07-20の事故はこの経路である。

空DBならsettings表も空なので、envがそのまま効く。**これが画面確認で使える唯一安全な形。**

### DBだけ見て安全宣言をしない

2026-07-20の2回目は、DB側の隔離が効いていたため「副作用なし」と誤報告された。
server起動の副作用はfile systemと外部接続に出るので、確認範囲をそこまで広げる。

fixtureは起動直後と終了後に「sandboxのrecord dirへ `.ts` / `.mp4` が現れていないこと」を
確かめる。ここが鳴ったら、隔離が破れていて実配信へ繋がっている。

### 手でserverを上げて画面を見たいとき

testと同じ条件を手で組む。値はすべてsandboxを指すこと。

```bash
# Windows。Linuxは venv/bin/python、path区切りは / のまま
TICTOK_DB_PATH=<sandbox>/tictok.db \
TICTOK_RECORD_DIR=<sandbox>/recordings \
TICTOK_RECORD_DIR_FINAL=<sandbox>/recordings \
TICTOK_LOG_DIR=<sandbox>/logs \
TICTOK_JOURNAL_DIR=<sandbox>/journal \
TICTOK_SAMPLE_DIR=<sandbox>/samples \
TICTOK_PORT=<空きport> TICTOK_NO_RESTORE=1 \
TICTOK_STT_ENABLED=0 TICTOK_SEMANTIC_ENABLED=0 TICTOK_UPSCALE_ENABLED=0 TICTOK_AI_ENABLED=0 \
venv/Scripts/python.exe main.py
```

`<sandbox>` は本番treeの外に取る。DB fileは作らなくてよい(空DBとして生成される)。
`TICTOK_*` は `.env` より環境変数が優先されるので、この形で上書きが効く。

終わったらsandboxのrecord dirが空のままであることを確かめる。

### 重いmodelを起動pathから外す

`.env` が STT / semantic / upscale を有効にしていることがある。画面の描画確認には
要らないうえ、文字起こし(CTranslate2)とtorchの同居は cuDNN の衝突でprocessごと
即死する。E2Eは `TICTOK_STT_ENABLED=0` / `TICTOK_SEMANTIC_ENABLED=0` /
`TICTOK_UPSCALE_ENABLED=0` / `TICTOK_AI_ENABLED=0` を明示して起動する。

### serverのstdoutをpipeで受けない

`subprocess.PIPE` で受けたまま読まないと、logでbufferが埋まってserverが止まる。
起動待ちがtimeoutする形で出るので原因が分かりにくい。fileへ落とす。

## unit testの作り: 本番と同じclassic scriptとして読む

`static/` の JS は ES module ではない。11枚のHTMLが `<script src="/static/common.js">`
で読み込み、関数はglobalに生える。

test も**同じ読み方を再現する**。`tests/js/helpers/page.js` が jsdom を組み立て、
HTML自身の `<script src>` が指すfileを `<script>` 要素として順に流し込む。

- 読み込むscriptの一覧は**HTMLから取る**。testに一覧を持たせると、pageへscriptを
  足したときにtestだけ古いまま残る
- `eval` では読めない。`static/*.js` は先頭が `"use strict"` で、strict evalは独自の
  scopeに閉じるため関数がglobalへ生えない。script要素として食わせるのが唯一の正しい形
- top-levelの `const` / `let` は `window` のpropertyにならない(global lexical scopeへ
  入る)。`page.get("state")` が indirect eval でそこへ届く。`function` 宣言は
  `page.win.<name>` でそのまま読める
- 流し込む source の末尾に `//# sourceURL=` を足す。これが無いとjsdomの無名scriptとして
  扱われ、stack traceが読めないうえ**coverageが全file 0%になる**

### stub

- **vendor** (`hls.min.js` / `chart.umd.min.js`) は本物を読まない。呼ばれ方を記録する
  stubを置く
- **fetch** は test が `routes` で明示したpathだけ応答する。未指定は404にして、app自身の
  error経路(「取得できていない」表示)を通す。未知のpathへ空dataを返すと、実際には
  壊れている画面がtestでは正常に見える
- **jsdomに無いbrowser API** は `static/` が実際に触る物だけ補う(`WebSocket` /
  `canvas 2d context` / `scrollIntoView` / `HTMLMediaElement.play` /
  `IntersectionObserver` / `navigator.clipboard`)。網羅的なpolyfillは入れない —
  触っていないAPIを生やすと、本番に無い前提の上でtestが通る

### 日時の固定

日時helperは `toLocaleString("ja-JP")` で書式を作るため、実行機のtimezoneに結果が
引きずられる。`vitest.config.js` で `TZ=Asia/Tokyo`(appの既定 `get_locale_tz` と同じ)へ
固定している。

## 何をtestしているか

### `tests/js/pages.boot.test.js`
11枚のHTMLすべてを組み立て、JS errorなしでbootすること・navが11本描かれ現在地だけが
activeになることを見る。関数名の衝突、page JS が common.js より先に必要な物を触る、
bootstrapがDOMに無いidを掴む — このどれが起きても画面は白いまま何も出さないが、
その壊れ方は「なんとなく変」で済まされて気付かれにくい。

### `tests/js/common.*.test.js`
`common.js` は11枚すべてが読む共通基盤なので、ここが崩れると全画面が同時に崩れる。

- `common.format` — 数値・時刻・容量・Session番号・録画名の書式、HTTP errorの日本語化
- `common.battle` — PKの陣営構造(participants / teams / topology / BSと実弾)
- `common.dom` — `renderTableRows`(数値列のheader整合)、`chipBar`、一覧placeholderの
  3状態、空き容量バー、toast、segmented control、job帯
- `common.jump` — Ctrl+K の横断jump(取得→絞り込み→描画の通し)

### `tests/js/analytics.calc.test.js` / `tests/js/videos.logic.test.js`
統計そのものは backend が出すが、単位・丸め・「値が無い」の描き分けは画面が持つ。
録画の実体(TS/MP4)の名乗り、切り出し範囲、segment吸着も同様。

### 「黙って嘘をつく」分岐を狙ったtest

表示が消えるbugは気付かれるが、**それらしく描かれたまま対応が狂う**類は気付かれない。
以下はその観点で選んだ箇所である。

| file | 何がずれると嘘になるか |
|---|---|
| `common.timeline.test.js` | 同接(level)を合計してしまう / 欠損bucketの同接を0にして配信が急落したように描く / 切り詰めと束ねの順序が入れ替わり1点の意味が変わる |
| `videos.timeaxis.test.js` | bar上の位置と別の場面のthumbnailを出す / 別のコメントに★が付く(idではなく行順で塗る) / 録画に無い素材版を選べてしまう / 切り出し指定の二重DOMが片方だけ古い |
| `history.sort.test.js` | 表は正しいのに列headerとselectが逆の順序を名乗る(`aria-sort`含む) / 同値の並びが描画ごとに揺れる |
| `jobs.rows.test.js` | filterに一致したjobが、group合成行が落ちた巻き添えで一覧から消える |
| `capacity.forecast.test.js` | 予測を出せない理由を伏せて数字や0を描き、満杯までの猶予を長く読ませる |
| `common.dom.test.js` | 数値列のheaderだけ左寄せのまま残り、項目と値が縦にずれる |

いずれも「0件」と「取得できていない」を描き分ける、という同じ原則の別の顔である。

## ES module化はしていない

### 判断

`static/` は17,959行あって `import` / `export` が**0件**。11枚のHTMLが `<script src>` で
読み、関数はglobalに生えて、file間はそのglobalを通して参照し合っている。

`<script type="module">` へ移すと変わるのは名前空間だけではない。

- **実行timingが変わる**。moduleは常にdeferで、HTML解析の完了後に走る。今の
  `<script src>` は書かれた位置で同期実行される。bootstrapが「その時点のDOM」を前提に
  している画面(`videos.js` は末尾で `bind()` と `loadStatus()` を直接呼ぶ)は影響を受ける
- **scopeが変わる**。top-levelがmodule scopeになるので、file間で見えていた関数・定数を
  すべて `export` / `import` で結び直す必要がある。参照は13 file間で双方向にある
- **読み込み順の保証が変わる**。今は `common.js` が先、page JSが後、という
  HTMLの記述順そのものが依存関係。moduleではimport graphで解き直すことになる

これは「testを入れる」作業の範囲ではなく、**本番の読み込み方を丸ごと差し替える改修**で、
「既存UIの見た目と挙動を変えない」という前提と両立しない。classic scriptのままtestできる
ことを確かめたうえで、module化しない判断をした。`static/` へは1行も変更していない。

### 将来module化する場合、testはどうなるか

**個々のtestは書き直さない。** 直すのは `tests/js/helpers/page.js` の読み込み部分だけで、
そこは1箇所に閉じてある。

| 変わるもの | 内容 |
|---|---|
| `helpers/page.js` の script注入 | `<script>` 要素の注入 → `import()` へ差し替え |
| `page.get(name)` | 不要になる(module化すれば `import` で直接取れる) |
| stubの入れ方 | window へ生やす形 → `vi.mock()` へ寄せられる |

| 変わらないもの | 内容 |
|---|---|
| 各 `*.test.js` の assertion | `expect(fmtNum(1234567)).toBe("1,234,567")` の類は全部そのまま |
| `pages.boot.test.js` の意図 | 「11枚が error なく組み上がる」は module化後も要る |
| E2E (`tests/test_e2e_ui.py`) | browser越しなので読み込み方式に依存しない。無変更 |

つまり今のtestは module化の**足場**になる。先にtestを入れておけば、module化が挙動を
変えていないことをこの191件で確かめられる。順序としてはこちらが先で正しい。
