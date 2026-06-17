# TikTok LIVE polling のBot検知 調査と対策

## 1. 結論（要点）

TicTokのpollingが「Bot扱い」される原因は、**2つの独立した経路**に分かれます。

| 経路 | 宛先 | 制約 | 影響 |
|------|------|------|------|
| A. 接続/署名 | EulerStream署名Server (`tiktok.eulerstream.com`) | 匿名(API key無し)で **5/分・30/時・100/日** (per IP) | 複数監視・再接続で即枯渇。**これが主因** |
| B. 直接request | TikTok本体 (`www.tiktok.com`, `webcast.tiktok.com`) | 明確な公開上限は無いが、fingerprintで検知 | datacenter IP・長時間pollingで段階的にblock |

本Repositoryで実測した結果、**経路Aが支配的**でした。

## 2. 再現（実測）

`TikTokLive==6.6.5` を用いて本環境から検証しました。

### 2.1 経路B（is_live polling）は中量では耐える

`fetch_is_live` の実体である `GET www.tiktok.com/api-live/user/room/` を、
8 accountへ約90秒間連続(256 request)pollingしても全て `HTTP 200` でした。
→ **10秒間隔のis_live確認そのものは、少数監視では即時blockの主因ではありません。**

### 2.2 経路A（署名Server）が本命

`client.connect()` は内部でEulerStream署名Serverを呼びます。匿名のrate limitを直接取得した結果:

```
GET https://tiktok.eulerstream.com/webcast/rate_limits/
{"day":{"max":100},"hour":{"max":30},"minute":{"max":5}}
```

- **1分間に5接続まで**。複数accountを同時に監視開始すると即上限。
- 監視中の切断→再接続も1接続を消費。`reconnect_max_attempts=10` の指数backoffが
  rate limit中に走ると、**429を受けてさらにrequestを重ね、上限を悪化させる悪循環**。
- 100/日を使い切ると、以降は全監視が `reconnecting`/`error` から復帰不能。

## 3. Code上の問題点

1. **API key未設定** — EulerStream署名Serverを匿名tierで使用（5/分の最小枠）。
   Repository内に署名key/URLの設定箇所が存在しませんでした。
2. **rate limitの誤処理** — `SignatureRateLimitError` (429) が汎用 `TikTokLiveError`
   として "transient" 扱いされ、`reconnect_base_delay`(2秒)からの再接続に巻き込まれていました。
   Serverが返す `retry_after`/`reset_time` を無視してすぐ叩き直すため、上限を自ら悪化させていました。
3. **fingerprintのhygiene不足**
   - `curl_cffi` 未install（`requirements.txt` が `TikTokLive` baseのみ）。直接requestは
     plainなhttpx = **PythonのTLS(JA3) fingerprint**で送出され、browserに偽装できていませんでした。
   - polling間隔にjitterが無く、複数監視が**同時刻に揃って**pollingしていました（thundering herd）。
   - proxy設定の口が無く、全requestが単一IPに集中していました。

## 4. 対策（実装済み）

### 4.1 署名Server credentialのconfig化（経路A・主対策）

`config.py` に環境変数を追加。hard-codeせず、未設定時はlibrary既定にfallbackしません
（明示設定時のみ上書き）。

| 環境変数 | 用途 |
|----------|------|
| `TICTOK_SIGN_API_KEY` | EulerStream API key。設定で日次/分次の上限が大幅緩和 |
| `TICTOK_SIGN_API_URL` | 署名Server URLの差し替え（self-host / 代替provider用） |
| `TICTOK_WEB_PROXY` | 直接request用のHTTP proxy（経路B対策） |

`collector.py` の全client生成箇所（本接続・live確認probe・offline再確認probe）を
`new_client()` factory経由に統一し、上記を一括注入します。

### 4.2 rate limit専用のbackoff（経路A・悪循環の停止）

`_connect_once` で `SignatureRateLimitError` を個別捕捉し、`_wait_for_ratelimit()` で
Server提示の `retry_after`（下限 `reconnect_max_delay`、上限3600秒）だけ待機します。
**通常の再接続budget(`reconnect_max_attempts`)を消費しない**ため、rate limitで監視が
error停止せず、枠回復後に自動復帰します。userへは原因とAPI key推奨を通知します。

### 4.3 fingerprint hygiene（経路B）

- `requirements.txt` を `TikTokLive[interactive]` に変更し、`curl_cffi` によるbrowser
  TLS(JA3)偽装を有効化。
- `live_check_jitter`(既定0.3)設定を追加。確認間隔へ最大この比率の揺らぎを加え、複数監視の
  pollingを分散。監視開始時にも初回stagger（揺らぎ待機）を入れて同時startを回避。

## 5. 運用推奨

1. **EulerStream API keyの取得**（最優先）。`TICTOK_SIGN_API_KEY` に設定。
   無料tierでも匿名枠より大幅に緩和されます。
2. 多数accountを監視する場合は **datacenter IPを避け**、`TICTOK_WEB_PROXY` で
   住宅系proxyを併用。
3. `live_check_interval` は必要十分に長く（既定60秒）。10秒は枠を圧迫します。

## 6. 検証

- `tests/test_collector.py` に `test_signature_ratelimit_waits_and_recovers` を追加。
  429受信後に待機して復帰し、再接続budgetを消費しないことを確認。
- 既存testは全てpass。
