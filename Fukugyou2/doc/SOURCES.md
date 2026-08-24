# 情報源

作成 2026-08-24 / 設定の実体: `config/sources.yaml`

**endpoint と 利用上限 を code に埋めないため、設定は `config/sources.yaml` に置いています。** ここはその補足です。

---

## 1. 使っている情報源

| 情報源 | 用途 | 認証 | 上限 | 備考 |
|---|---|---|---|---|
| **Hacker News / Algolia Search API** | 工程1 事例の収集、工程4 英語圏の言及量 | 不要 | 公表は 10,000 request/時 | `tags=story`、`numericFilters` で点数と期間を絞ります |
| **Qiita API v2** | 工程4 日本語圏の言及量 | 不要（token 可） | **認証なし 60 request/時** / token あり 1,000 request/時 | 総件数は `total-count` header。残数は `rate-remaining` header |
| **Zenn 記事検索** | 工程4 日本語圏の補助 | 不要 | 公表なし | **総件数を返しません。** 上限 page までの実数と、打ち切りの有無を出します |
| **事例 site（直接取得）** | 工程2 価格の証拠 | 不要 | — | robots.txt を尊重。1事例あたり最大2 request |

## 2. 既知の癖

- **Hacker News の点数は人気であり、金ではありません。** 高得点の事例が儲かっている事例ではありません。
- **Algolia の `query` は AND 検索です。** 語を増やすほど該当件数が急に減ります。config に語を足すときは、必ず該当件数を見てください（0件の語を残さないこと）。
- **Qiita の `query` も AND です。** `請求書 自動化` は両方を含む記事だけを数えます。
- **Zenn は `next_page` で続きを示します。** 上限 page で切ったかどうかを出力に残しています。
- **robots.txt が 401 / 403 を返す site は「全面禁止」として扱います。** 404 など「存在しない」場合は許可（RFC 9309）です。取得できなかった場合は「不明」とし、**取りに行きません**。
- **画面を JavaScript で描く site の価格は取れません。** 「未取得」と「証拠なし」は別物として記録しています。

## 3. 使っていない情報源と、その理由

| 情報源 | 理由 |
|---|---|
| **Product Hunt** | API に OAuth token が必要です。取得したら `config/sources.yaml` に足せます |
| **Indie Hackers** | 公開 API がありません。金額の記載が多く価値は高いため、**手で読む対象**とします |
| **Reddit** | 2023年に API の条件が変わりました。**規約を読んでから**でないと足しません |
| **Y Combinator の企業一覧** | 一覧の取得に埋め込み鍵が要るため、規約上の可否が不明です |
| **Crunchbase 等の有料 database** | 費用が発生します。1周目では使いません |

**足す場合は `config/sources.yaml` に定義を書き、`doc/SOURCES.md` に上限と癖を書いてから実装してください。** 順序を逆にすると、上限を超えてから気づきます。

## 4. 規約と礼儀

- request の間隔は `config/sources.yaml` の `sleep_seconds` で空けています。**短くしないでください。**
- User-Agent に用途と参照先を入れています（`tools/casebase.py` の `UA`）。
- **取得した生 response は再配布しません。** `log/raw/` は再解析のための手元の控えです。page の生 HTML は `.gitignore` で git に入れません。
- 個人が特定できる情報（投稿者名以外）は収集しません。
