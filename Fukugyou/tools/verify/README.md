# 検証script — 報告書の数値を出したもの

**これらは session 限りの一時folderにしか無く、消えれば報告書の数値が再現不能になる状態でした**（2026-08-12 に取り込み）。
`doc/verify/` の各文書が引用している数値は、ここの script が出したものです。

すべて標準libraryのみで動きます（`tenji*.py` を除く）。引数は不要です。

| script | 出典文書 | 出している数値 |
|---|---|---|
| `x2_a〜x2_i.py` | `doc/verify/X2_reachmath.md` | 集客の数理。**個別の声かけの上限12.1件**、`M = c·B ÷ (1−e^(−c·T))`、単価4行が「目標契約数が12.1件を超えるか」の言い換えである証明（`x2_i.py`） |
| `x3_gates.py` `x3_gates2.py` `x3_gates3.py` | `doc/verify/X3_gates.md` | 関門の選別力。**段階2 の通過率36.4%に対し無作為の期待値39.9%**、関門ごとの棄却率と1候補あたり所要時間 |
| `w3_reach_stats.py` `w3_supp.py` `w3_supp2.py` | `doc/verify/W3_reach_stats.md` | 必要な月次獲得の検算（常微分方程式との突き合わせ）、**45名の歩留まり表**、経路別の必要接触数 |
| `v5_stats.py` | `doc/verify/V5_stats.md` | 冪則分布では**分類の平均が安定しない**こと、規則 of three の 同じ集団による相関 補正（**単一経路30名で20.7〜40.9%**） |
| `tenji.py`〜`tenji6.py` | `doc/verify/W1_reach.md` | 展示会の会期。**809件中764件（94.4%）が平日のみ**。`tenji6.py` は祝日を除いても763件（94.3%） |

## 実行

```bash
python tools/verify/x2_i.py
python tools/verify/x3_gates3.py
python tools/verify/w3_reach_stats.py
python tools/verify/v5_stats.py
```

`tenji*.py` は元PDFが要ります。第1引数で渡してください。

```bash
curl -sLo tenji2026.pdf https://cdn.clipkit.co/tenants/897/resources/assets/000/001/402/original/2026tenjilist.pdf
python tools/verify/tenji6.py tenji2026.pdf
```

`pymupdf` が要ります。**PDF自体は保存していません**（1.6MB）。上のURLは 2026-08-12 時点で200を返します。

## 注意

**これらは検証用で、実行時に使う道具ではありません。** 実行時に使うのは `tools/economics.py`（逆算）と
`tools/scan_stock_params.py`（掲載・記事の集客量の実測）の2本だけです。

**数値を書き換えたくなったら、まず該当の script を走らせてください。**
`MARKET_RESEARCH.md` §10 の誤りの型4「関門を作って、機能するか検算しなかった」と
型6「予算の総和を検算しなかった」は、どちらも**手で書いた表を検算しなかった**ことが原因です。
