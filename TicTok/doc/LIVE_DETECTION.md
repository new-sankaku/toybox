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

## 依存

`playwright`（requirements.txt）と Chromium 本体が必要。
`run.bat` / `run.sh` の初回セットアップで `playwright install chromium` を実行する。
手動の場合：

```
venv/Scripts/python -m playwright install chromium   # Windows
venv/bin/python -m playwright install chromium        # Linux
```
