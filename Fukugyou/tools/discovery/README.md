# discovery — 困りごとの候補を、粗く集めて・粗く捨てて・精査する

作成 2026-08-24

**なぜ作ったか**: 2026-08-18 に、次の4つの誤判定を実際にやりました。

| 誤判定 | 中身 |
|---|---|
| 有料 community の会員取材記事を、本人の体験談として数えた | `note.com/mokuyokai/n/nf5ed325f66fc` |
| 企業の AI hackathon の題材を、困りごと駆動として数えた | `zenn.dev/hacobu/articles/75d4baed347a01` |
| 社内のレジ袋請求という別作業を、同じ困りごととして数えた | `qiita.com/matsu_yoshi59/items/9eecca795e9fd56a1427` |
| snippet しか読んでいないのに、全文を読んだものとして引用した | 全般 |

**結果、「6人が同じ困りごと」と報告したものが、全文確認後は1人でした。**

---

## 3段の構成と、AI / program の分担

| 段 | やること | program | AI |
|---|---|---|---|
| **A 粗い一覧化** | 全文を取る | `fetch_body.py` — Qiita は API、他は HTML。取得日を刻み、生 response を保存 | 検索して URL を集める（人が確定する） |
| **B 粗い取捨選択** | 機械的に判定できる旗を立てる | `screen.py` — `config/discovery_rules.yaml` の規則 | 意味の判断（別作業の混入など）は AI |
| **C 精査** | 構造化して抽出する | `verify_quotes.py` — **AI の引用が原文に実在するか照合** | 全文を読んで抽出。**引用を必ず付ける** |

**要点は段 C です。** AI に抽出させたら、その引用が原文に実在するかを program が照合します。
**引用が原文に無ければ、AI が何と書いていても「記載なし」に落とします。** snippet の水増しと捏造は、これで機械的に止まります。

---

## 使い方

```bash
# A: 全文を取る（URL は人が書いた file から読む。候補を生成しない）
python tools/discovery/fetch_body.py --urls log/urls.txt --limit 20 --out log/bodies/

# B: 規則で旗を立てる
python tools/discovery/screen.py --bodies log/bodies/ --rules config/discovery_rules.yaml

# C: AI に抽出させたあと、引用を照合する
python tools/discovery/verify_quotes.py --bodies log/bodies/ --extract log/extract.json
```

`--limit` は必須です（`AUTOMATION.md` §2 制約2）。`pyyaml` が要ります。

## 段 C で AI に渡す指示

抽出は次の形で返させてください。**value だけを返させないこと。** quote が無い項目は照合できません。

```json
{"items": [
  {"slug": "<bodies/ の file 名から .txt を除いたもの>",
   "fields": {
     "pain":       {"value": "困りごと", "quote": "原文そのまま"},
     "frequency":  {"value": "頻度",     "quote": "原文そのまま"},
     "time":       {"value": "所要時間", "quote": "原文そのまま"},
     "product":    {"value": "使っていた製品", "quote": "原文そのまま"},
     "gap":        {"value": "その製品の何が足りなかったか", "quote": "原文そのまま"},
     "investment": {"value": "金か時間を投じたか", "quote": "原文そのまま"},
     "motive":     {"value": "困って作ったか、作りたくて作ったか", "quote": "原文そのまま"}
   }}
]}
```

**本文に書かれていない項目は、value を「記載なし」にして quote を空にしてください。**
埋めようとすると `verify_quotes.py` が落とします。

## 規則の検証結果（2026-08-24 実測）

上記の誤判定4件＋対照1件に `screen.py` をかけた結果です。

| 記事 | 立った旗 | 期待どおりか |
|---|---|---|
| AI木曜会（有料 community の取材記事） | `third_party_report` / `promotion` | ○ |
| Hacobu（hackathon の題材） | `no_first_person` / `weak_motive` | ○ |
| タツキ（困りごとの記述が薄い） | `no_first_person` / `no_quantified_pain` | ○ |
| 木村（本物。一人称・実測あり） | **なし** | ○ |
| matsu_yoshi59（別作業の混入） | なし | **×（規則では取れない）** |

**最後の1件は規則を通過します。** 「レジ袋の社内請求は別の作業である」は意味の判断で、
語の照合では判定できません。**ここは段 C の AI の担当で、program には落とせません。**

`verify_quotes.py` の検証（捏造引用を2件混ぜた）:

| 引用 | 判定 |
|---|---|
| 「60件程度の承認をするだけで概ね1時間」（実在） | 採用 |
| 「freeeの請求書機能では対応できませんでした」（捏造） | **不採用** |
| 「freeeの自動連携が使えないため手入力していました」（捏造） | **不採用** |

## この道具の限界

- **旗が立った＝棄却ではありません。** 人が本文を見る対象を絞るための印です（`AUTOMATION.md` §2 制約8）。
- **規則は語の照合だけです。** 皮肉・比喩・別作業の混入は取れません。
- **引用が実在しても、内容が正しいとは限りません。** AI木曜会の記事は「10時間かかりそう」「2時間で完了」
  と書きながら結論で「毎月23時間かかっていた」としており、**原文自体が矛盾しています。**
  照合器はこれを通します。数字の整合は人が見てください。
- 規則は上記5件からしか起こしていません。**標本5件です。** 誤判定が出たら規則を足してください。
