# LIVE検出のしくみ（WAF回避）

## 背景：なぜ素のHTTPでは検出できないか

TikTokのLIVE状態は `https://www.tiktok.com/@<id>/live` のページHTMLに埋め込まれた
`SIGI_STATE` JSON（`LiveRoom.liveRoomUserInfo.user` の `roomId` / `status`）から判定する。

このページは現在 **SlardarWAF**（JS challenge gate）で保護されており、JSを実行できない
HTTPクライアントには本来のページではなくchallenge stub（約1155 byte、`_wafchallengeid` を含む）
を返す。実測：

| 方法 | 結果 |
|---|---|
| httpx（Chrome UA） | WAF challenge stub（SIGI_STATEなし） |
| curl_cffi（chrome131 TLS偽装） | WAF challenge stub（SIGI_STATEなし） |
| 本物のbrowser（Chromium） | **通過**。SIGI_STATE取得・roomId解決成功 |

要点：
- ゲートは**IPではなく「JS challengeを解けるbrowserか」**を見る。VPN（特にdatacenter IP）では解決しない。
- ブラウザは**未log inのまま匿名で通過**する。`sessionid` 認証は不要。
- challenge通過後にbrowserが得る `_waftokenid` cookieは、HTTPクライアントへ移植しても通らない
  （TLS fingerprint等に紐づくため。実測で403）。

## 解決：browser経由でroomIdを解決する

`live_resolver.BrowserLiveResolver` がprocessに常駐のheadless Chromiumを1つ起動し、
`/@<id>/live` をbrowser context内で開いて `SIGI_STATE` から live状態を解決する。

- 解決ロジックは `interpret_live_state()`（TikTokLiveライブラリと同じ判定）：
  - `SIGI_STATE` なし → `LiveResolveBlocked`（WAF未通過/transient。backoffして再試行）
  - `LiveRoom` なし → `UserNotFoundError`（LIVE不可/存在しないUser）
  - `status == 4` → offline（`None`）
  - それ以外で `roomId` あり → live（`roomId` を返す）
- contextは使い回すのでWAF通過状態・cookieが全監視で共有される。
- navigationは `ProbeGate` でアクセス間隔を維持（IP単位の負荷を抑制）。

### browserが死んだら作り直す

常駐browserは落ちる。chromiumのcrash、playwrightのdriver process（node）の死、host
のsleepなどで、**以後の全呼び出しが同じ例外を返し続ける**。

```
BrowserContext.new_page: Connection closed while reading from the driver
```

driver processが死んだ場合、browser側へcloseが届かないので `browser.is_connected()`
はTrueのまま残る。つまり接続状態を見るだけでは検知できない。実測 2026-08-26 12:55〜18:06
は、この状態で229回連続失敗し、監視3件のlive検出が5時間止まったまま復帰しなかった
（collector側は例外を受けてbackoffするだけで、resolverを作り直す者が居なかった）。

`resolve()` は毎回 `_ensure_browser()` を通す。

| 検知 | 判定 |
|---|---|
| `browser.is_connected()` が False | chromiumのcrash。即座に作り直す |
| browser側の呼び出しが連続 `TICTOK_RESOLVER_RESTART_AFTER_FAILURES` 回失敗 | driverの死・contextの詰まり。作り直す |
| 1回の解決が `TICTOK_RESOLVER_TIMEOUT_MS` の3倍を超えて返らない | driverの無応答。打ち切って失敗として数える |

- 数えるのは **new_page / goto / evaluate が例外を上げた回数** だけ。WAF未通過（pageは
  読めたが `SIGI_STATE` が無い）はbrowserの健康状態ではないので数えない。1回でも読めた
  時点で連続失敗は0に戻る（WAF通過済みのcontextを単発の失敗で捨てない）。
- 作り直しは `TICTOK_RESOLVER_RESTART_COOLDOWN_SECONDS` に1回まで。chromiumを起動でき
  ない状態（未install等）でprobeごとに起動を試み続けないため。cooldown中の解決要求は
  `LiveResolveBlocked` で返り、collector側の通常のbackoffに乗る。
- 閉じる各段（context/browser/playwright）には待ち上限を掛ける。応答しないdriverに対して
  停止処理そのものが止まるのを防ぐ。

**死なずに固まる型が最悪**である。playwrightの `new_page` / `evaluate` / `page.close` には
timeoutが無い（`goto` と `wait_for_selector` だけが持つ）。resolverは解決を直列化する
lockを握っているので、1回の呼び出しが返らないと**全監視のlive検出がlogを1行も残さずに
停止する**。例外すら出ないので、driverの死（少なくとも失敗logは出る）より発見が遅れる。
そのため解決1回の実時間に上限を置き、超えたら打ち切って失敗として数える。

### live検出が止まる経路

| 経路 | 起きること | 扱い |
|---|---|---|
| driver processの死 | 以後の全呼び出しが同じ例外。log は出るが復帰しない | 連続失敗で作り直す |
| driverの無応答 | lockを握ったまま停止。logは無音 | 実時間の上限で打ち切り、失敗として数える |
| chromiumのcrash | `is_connected()` がFalse | 即座に作り直す |
| WAFの持続block | `SIGI_STATE` が読めない。検出は遅れるが止まらない | backoffして再試行（作り直さない） |
| 監視loop taskの異常終了 | この配信者の収集・録画が丸ごと停止 | 状態を error にして画面とlogへ。**自動再開はしない**（[collector._run](../tictok/collect/collector.py)） |

### connect()もwww.tiktok.comを踏まない

解決した `roomId` を `client.connect(room_id=..., fetch_live_check=False, fetch_room_info=True)`
に渡す。これによりconnect内部のHTML scrape（`fetch_room_id_from_html`）を回避する。
`room_info` は `webcast.tiktok.com`、websocket署名は sign server で、いずれもSlardarWAF対象外。
→ **検出も再接続もwww.tiktok.comのWAFを踏まない。**

### 録画中の挙動
録画（ffmpeg）はCDN（`pull-hls-*.tiktokcdn.com`）からsegmentを取得し、WAF対象外なので影響なし。
websocket切断後の再接続も、保持済み `roomId` でconnectするためWAFを踏まずに復帰できる。

## 設定（config）

| 環境変数 | 既定 | 説明 |
|---|---|---|
| `TICTOK_RESOLVER_HEADLESS` | `1` | Chromiumをheadlessで起動。WAFがheadlessを弾く場合は `0`（headed）にする。 |
| `TICTOK_RESOLVER_TIMEOUT_MS` | `20000` | ページ遷移と `SIGI_STATE` 待機のtimeout（ms）。 |
| `TICTOK_RESOLVER_RESTART_AFTER_FAILURES` | `3` | browserを作り直すまでの連続失敗回数。 |
| `TICTOK_RESOLVER_RESTART_COOLDOWN_SECONDS` | `30` | 作り直しの最短間隔（秒）。 |
| `TICTOK_RESOLVER_CLOSE_TIMEOUT_SECONDS` | `10` | 閉じる各段の待ち上限（秒）。 |

## 依存

`playwright`（requirements.txt）と Chromium 本体が必要。
`run.bat` / `run.sh` の初回セットアップで `playwright install chromium` を実行する。
手動の場合：

```
venv/Scripts/python -m playwright install chromium   # Windows
venv/bin/python -m playwright install chromium        # Linux
```
