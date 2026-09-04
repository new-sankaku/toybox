# 文字起こしの訂正

whisperの出力は誤りを含む。上流（model・hotwords・VADの調整・音源側）は実測で全て潰れて
いるので（`STT_SUBTITLE_TIMING.md` / `BGM_REMOVE.md`）、残るのは**出力後のtextを直す**経路
だけである。この文書はその置き場と規則を書く。

## なぜ層にするか

直した結果を `transcripts` へ書き戻すと、その録画を再文字起こしした瞬間に消える。かと
いって「直したら再文字起こし禁止」にもできない — modelを変えた・時刻mapの版が上がった
場合は、直しを捨てて取り直すのが正しいからである。

そこで `transcripts` は常に生のまま置き、訂正は `transcript_corrections` の行として別に
持ち、**読み出すときに重ねる**。

| | 表 | 寿命 |
|---|---|---|
| 生の文字起こし | `transcripts` | 再文字起こしで丸ごと入れ替わる |
| 訂正 | `transcript_corrections` | それを跨いで生き残る（跨がせない選択も出来る） |

## 重ねる場所は1つ

`Storage.get_transcript()` が重ねる。字幕の書き出し（srt/vtt/txt）・切り抜き字幕
（srt/vtt/ass）・焼き込み・横断検索index・AIの章立ては、いずれもここを通って本文を得る
ので、訂正は全部の出口へ同時に効く。

**ここを迂回する経路を足すと、その出口だけ直っていない文字が出る。** 生の文字起こしその
ものが要る場合（再文字起こしの照合・訂正画面の原文表示）だけ `raw=True` を使う。

## 同定はindexではなく (時刻, 原文)

再文字起こしするとsegmentの数もindexも時刻も変わる。indexで指した訂正は次の実行で全滅し、
しかも**別の発話に乗る**（黙って起きる最悪の壊れ方）。照合は次の組で行う。

* `|開始時刻の差| <= 2.0秒`（`corrections.MATCH_TOLERANCE_SECONDS`）
* **原文が完全一致**

どちらか一方では足りない。時刻だけでは言い直し（「トイレ行きたい」が3回続く）で隣に乗り、
原文だけでは同じ相槌（「うん」）が録画中に何百回もある。

一致しなかった訂正は `state='orphan'` で人へ返す。**近いものへ寄せにはいかない。**

## 再文字起こし時の選択

`save_transcript(..., corrections=)` と、job側の `params={"corrections": ...}`。

* `keep`（既定） … 新しいsegmentへ貼り直す。当たらなければ保留
* `discard` … 捨てる。ただし行は `state='discarded'` で残す（後から戻せる）

誤りを1件ずつ直した後なら `keep`、modelや時刻mapを変えたなら `discard` が正しい。録画ごと
に違うので実行時に選ぶ。未知の値は既定へ倒さず400で弾く — 破棄を指示したつもりの人に古い
訂正が残るのが最悪であるため。

## 語枠(words)への反映

焼き込み字幕・切り抜き字幕は `segment["text"]` ではなく `words` のtextを連結して作る
（`subtitles.split_for_display`）。segmentのtextだけ直しても字幕には出ないので、訂正は語の
枠まで下ろす必要がある。

置換された連なりは、**それが置き換えた元の連なりの時刻spanをそのまま継ぐ**。文字数で按分
して新しい時刻を作ることはしない — それは時刻の捏造で、subtitlesが一貫して拒否している当の
ものである。

実装は「文字位置の対応表」ではなく「**訂正文の全文字を語へ割り当てる**」。前者だと語と語の
ちょうど境目に入った文字がどちらの語の受け持ちにもならず黙って消える（実測: 1,069件の訂正
のうち112件でこれが起きた）。

語の連結が原文と一致しないsegment（実測3,306件中2件、U+FFFDで途切れたもの）は語を捨てる。
語を持たないsegmentは `split_for_display` がそのまま1枚で出すので、割れないだけで済む
——割った振りをするより害が小さい。

## 検索indexは張り直しが要る

索引（`search_hits` / `search_fts`）は本文を**写し取った別の行**で、読み出し時の重ね合わせ
を通らない。訂正を入れたら `indexer.index_transcript(storage, recording)` を回す。回さないと
画面の字幕と検索結果が食い違う。

## API

| | |
|---|---|
| `GET /api/recordings/{id}/transcript/corrections` | 一覧（`include_discarded` で破棄済みも） |
| `POST /api/recordings/{id}/transcript/corrections` | まとめて投入（`(start, src)` で上書き＝冪等） |
| `PATCH /api/recordings/{id}/transcript/corrections` | 状態変更（active/orphan/discarded） |
| `DELETE /api/recordings/{id}/transcript/corrections/{cid}` | 本当に消す |
| `POST /api/recordings/{id}/transcribe?corrections=keep\|discard` | 再文字起こし時の扱い |

取り込みscriptは `scripts/import_transcript_corrections.py`。`src` が実segmentと一字一句
一致するかを**全件検査してから**書き込み、1件でも合わなければ何も入れない（半分だけ入った
訂正が字幕へ出る方が、入らないより悪い）。

## 実績

録画00478（recording 897 / streamer_a・182分・3,306 segment）へ **1,070件（32.4%）** を投入。
根拠の内訳は commentと一致 323 / 文脈 219 / 言い直し 204 / 人名（event由来）202 /
表記統一 121。

**視聴者commentが正解textの源になる。** 配信者はcommentを読み上げるので、`events.comment`
と突き合わせると誤りが一意に確定する。人名は `events.user_nickname` と
`battles.data_json` の opponents（コラボ相手）から取れる。

60件は「不明」として直していない。文脈に手がかりが無い単発の聞き違いで、音を聴かずに埋め
れば捏造になる。
