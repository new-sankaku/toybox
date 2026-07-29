# 保持policy(retention)の資産序列

## 削除順序は3段で固定

`tictok/record/retention.py` が候補を組み、`tictok/server.py` の `_RETENTION_DELETERS` が消す。

| phase | 中身 |
|---|---|
| ① transient | 中断したrender/再encodeが残した中間file(`.cfrbase.mp4` `.comments.mov` `.norm.tmp` 等) |
| ② derived | 作り直せる派生物。焼き込み・Up出力に加え、**素材が残る録画のmp4本体** |
| ③ source | 再取得不能な原本。**素材が残る録画では素材(.ts)そのもの**、素材が無い録画ではmp4本体 |

順序は崩さない。原本を先に消すと reprocess・再output・transcribe・clip・heat がまとめて
復旧不能になる。実行は dry-run(`POST /api/storage/retention`)→ `apply` + `confirm` の2段で、
設定値だけでは何も消えない。既定は ②③ とも0(=実行しない)。

## 何が原本かは録画ごとに違う

録画の原本はHLS素材(`<root>/<streamer>/ts/<stem>/`)で、mp4はそこから作った成果物である。
よって**素材が残っている録画ではmp4は派生物**で、②で回収してよい(消しても再mp4化で戻る)。
素材が残っていない録画では、従来どおりmp4が唯一の再取得不能資産で、③でしか触らない。

判定は `has_media(recording)` として server から渡す。retention module 側の既定は「素材なし」
= mp4を原本として保護する側で、**判定手段が無い・判定できないときは必ずそちらへ倒す**。
分からないまま原本を派生物へ落とすと、最後の1本を消すことになる。

2026-07-25実測: 完了録画331本のうち、素材あり128本(mp4 316.3GB)が②へ回り、素材なし198本
(mp4 42.4GB)はmp4が③のまま。

## 「素材がある」の定義は1箇所

`_has_usable_media(seg_dir)` = `layout.has_media()`(`seg*.ts` と `pack*.ts` の両方)**かつ**
`index.m3u8` が在ること。再mp4化も再生もplaylistのEXTINF順にsegmentを読むので、listの無い
segmentの山からは何も組み立てられない。「.tsが在る」だけを根拠にすると、作り直せない録画の
mp4を派生物と見なして消しにいく。

この判定は 再生経路の選択(`_recording_hls_dir`)・再mp4化の可否(`_find_hls_root`)・retentionの
資産序列(`_bulk_hls_batch` 経由)の3つが**同じ関数**を通る。場所ごとに違う条件で見ると、同じ
録画の扱いが画面と削除で食い違う。

## 二重の安全弁

1. **plan時**: 母集合ぶんの `has_media` は `_bulk_fs_facts_batch` + `_bulk_hls_batch`(配信者ごとの
   `ts/` を1回scandir)で埋める。一括削除(`delete_mp4`)の判定と同じ事実を使う。
2. **削除の直前**: `_delete_derived_item` はplanの判定を信用せず、`_recording_media_dirs()` で
   もう一度素材を確かめてからmp4を消す。planを組んでから実行までの間に素材が消えていれば、
   そのmp4はもう最後の1本なので残し、`retention.source_kept` をwarningで残す。実行中jobが
   掴んでいる録画(`busy_recording_ids`)も同じ理由で外す(走っているffmpegの入力が消える)。

mp4を消す処理そのものは一括削除と同じ `_delete_source_mp4()`。DB行の「作り直し済み」
「正規化済み」を落とす後始末まで共通で、2箇所に持たない。

## bytesの数え方

素材が残る録画では、②がmp4を、③が素材を数える。同じ録画のmp4を③にも載せると、planの
解放見込みが実在しない容量まで膨らむ(②で消えたものを③でもう一度数えることになる)。
③のbytesは `_retention_media_usage()` が session dir を `scandir` で走査した実体量で、束ね前の
録画は数千のsegmentを抱えるため、fileごとのstatは起こさない。
