# 配信者まるごとの一括処理

文字起こし(`transcribe`) / 笑い声分析(`laugh`) / 無音skipの解析(`voice`) / 焼き込み(`overlay`) /
Up出力(`upscale`) / 再mp4化(`reprocess`) / 音量正規化(`audionorm`) / ts結合(`pack`) /
元mp4の削除(`delete_mp4`)を、Sessionではなく
**配信者単位**(または全配信者、あるいは選んだ録画だけ)で実行する。画面は配信者動画
(`/videos`)の「一括処理」tab、API は
`GET /api/bulk/status`, `GET /api/bulk/estimate`, `GET /api/bulk/recordings`,
`POST /api/bulk/queue`, `POST /api/bulk/delete-mp4`。

「生成」ではなく「処理」なのは、作らずに**消す**種別を含むようになったため。

音量正規化そのものの設計(なぜone-pass loudnorm単体か)は [AUDIO_NORMALIZE.md](AUDIO_NORMALIZE.md)。

## なぜ配信者タブではなく配信者動画タブか

配信者(`/streamers`)は「1人を選んで全Sessionを集約分析する」画面で、次の2つを持っていない。

- **全配信者横断の投入**を表現する場所（構造上、1人ぶんしか出せない）
- **対象数の判定**（もう全部出力済みの配信者をdisableできない）

一方 `/videos` の「一括処理」tabは *配信者別の表 + 全配信者への投入* という形を持っており、
種別が増えても同じ表に列が増えるだけである。同tabのcomment(videos.html)にある
「toolbarにselect+buttonを重ねると、済んだ配信者も投入できてしまう劣った経路が並ぶだけだった」
という判断をそのまま引き継ぐため、**配信者画面には投入buttonを置かず、linkだけ**を出す
(`/videos?streamer=<unique_id>#bulk`)。

### 出力fileを作らない種別

無音skipの解析は録画1本あたり数百kBのsidecarしか残さない。投入前の空き容量判定
(`_require_disk_space`)を通さないのはそのためで、通すと「空きが無いから声の解析もできない」
という無関係な行き止まりになる。画面側でも見積りのmp4容量とdisk警告を出さない
(`BULK_NO_MP4_KINDS` / `BULK_NO_DISK_KINDS`。文字起こし・笑い声分析と同じ扱い)。

## 画面は「種別を選ぶ」ではなく「配信者×種別の表」

行が配信者、列が種別で、cellの数字は**押したら何本走るか**(未処理本数)。列見出しを押すと
表示中の全配信者ぶん、cellを押すとその配信者ぶんの投入前確認と録画一覧が、押した行の直下へ
開く。

種別を1つ選んで表を描き替える形をやめたのは、「どの種別がどれだけ残っているか」を知るのに
種別の数だけ選び直す必要があり、しかも**選ぶまでその列の数字が存在しなかった**ため。
`GET /api/bulk/status` は種別をまたいで1 requestで返るので、選ばせる理由が無い。

かつて `reprocess` だけを既定の集計から外していたのは「対象判定に録画ごとの`.ts`走査を伴う」
ためだったが、その走査(`_bulk_hls_batch`)は `overlay` / `upscale` の判定でも要るので既定でも
走っていた。除外は集計costを何も減らしておらず、画面に「選ぶまで数字が出ない列」を作るだけ
だった。全種別を数えても増えるのは判定loop(dict操作)とDB照会2本だけである。

この表は**配信者の名簿でもある**。実体の有無(`playable`)とコメント索引の本数
(`comment_indexed`)を同じ応答に載せ、検索側の配信者selectもここから作る。同じ全録画走査を
する一覧を別endpointにもう1本持っていた頃(`GET /api/search/status`)は、同じ画面に母集合の
違う「録画」列が2つ並び、数が食い違っていた。

## 投入前の見積り

配信者まるごとの焼き込みは日単位で走り、中間fileでdiskを食う。押した瞬間に数百本積むのでは
なく、必ず `GET /api/bulk/estimate` を挟んで次を見せる。

| 項目 | 出所 |
| --- | --- |
| 対象本数 / 総録画時間 | `_bulk_plan()` の結果そのもの |
| 元mp4の合計 / 最大の1本 | 実file の `stat()` |
| 所要時間 | **過去に完了した同種jobの実測比の中央値** |
| 空き容量 / 下限割れ | `_disk_report()` |

所要時間の倍率を設定値や定数で持たない。GPU・model・解像度で数倍変わるため必ず外れる。
実績が1件も無ければ `eta_seconds` は `null` で返し、画面は「実績が無いため不明」と出す
(それらしい数字を置くと、実測から出した数字と区別できなくなる)。

容量は「合計」ではなく**同時に走る本数ぶん**を空きと並べて出す。中間fileは作って消えるので、
山になるのは合計ではなくその瞬間に走っているjobぶんである(同時実行数は `media_queue_workers`)。

## 投入の単位

| 単位 | 押す場所 | 対象 |
| --- | --- | --- |
| 全配信者 | 列見出しのbutton(種別名) | 表に出ている全配信者の未処理 |
| 配信者1人 | cellを開いて「対象すべてN本を投入」 | その配信者の未処理すべて |
| 録画を選んで | cellを開いて「録画を選んで投入」の一覧で選び「選んだN本を投入」 | 選んだ録画だけ |

cellのbuttonは**枠を出して押せると名乗らせる**。地も枠も透明にしていた頃は、押せるcellが
他の数値列(録画・comment索引・総時間)と見分けが付かず、表全体が本数の一覧に見えていた。
押せる合図が出ているのは列見出しだけだったため、録画を選ぶ道に気付けず、まるごと投入しか
使われなかった。

同じcellの録画一覧が開いている間は、まるごと投入を主のbuttonにしない(色の強い方だけが
押され、選択が無視される)。投入buttonは範囲を語で名指しする —— 「この内容で」では、隣に
選んでの投入が開いている以上、選んだぶんが走ると読める。

録画ごとの可否は `GET /api/bulk/recordings` が返す。画面側は判定を持たない — 2箇所で判定すると
「選べるのに投入されない録画」が出る。選ばなかった録画は**対象外の内訳に数えない**(選外を
混ぜると、選ばなかったぶんが不具合で弾かれたように読める)。

## 投入前の確認をどこへ出すか

確認は**押した行の直下へ、表の行として**開く。表の外(toolbarの下)へ出していた頃は、開いた
瞬間に配信者一覧がまるごと下へ動き、しかもどの行に対する確認なのかが読み取れなかった。
確認の見出しには「種別 / 対象配信者 / 選択本数 / 処理済みも作り直すか」を必ず名乗らせる。
「この内容で投入」とだけ出ていた頃は、その"内容"がどこにも書かれていなかった。

全配信者ぶんの確認だけは掛ける行が無いので、表の先頭行として開く。

## 対象の選び方

見積りと投入は**同じ `_bulk_plan()` を通す**。ここを別々に絞ると「確認した本数と積まれた
本数が違う」という最悪の壊れ方をする。

| 除外するもの | 理由 |
| --- | --- |
| 録画中 | 実行中のfileを読ませない |
| 録画fileが無い | workerが1件ずつ404で落ちるだけ |
| .tsが残っていない(再mp4化のみ) | 元segmentが無ければ作り直せない |
| 処理済み | 「出力済みも作り直す」で対象へ戻せる |
| 既にqueueにある | 同一出力pathへ2本走らせても片方は必ず捨てられる |

「処理済み」の判定元は種別で違う。焼き込み・Up出力はfilesystem(出力fileの実在)、音量正規化は
**DBの `recordings.audio_normalized_at` だけ**を見る。loudnormはmp4に痕跡を残さないので、
fileからは正規化済みか判別できない(推測で埋めてはいけない)。再mp4化は元mp4を作り直すので、
正規化せずに作り直したら必ずこの列をNULLへ戻す。文字起こしは `transcripts` 表の有無だけ。
無音skipの解析(`voice`)はsidecar(`.voice.json`)の実在だけで、DBに印を持たない — sweepと
同じ判定を `fsfacts.SIDECAR_JOB_FACTS` の1箇所から引く（一括とsweepで「済み」の意味が
食い違うと、片方が積み続ける）。

「既にqueueにある」の照合先も種別で違う。映像jobは `pending_media_job_keys()`、文字起こしは
`pending_transcription_ids()`(台帳が別)。**素材やmp4を置き換える種別(`pack`・`delete_mp4`)の
「処理中の録画」は両方の和**を見る — 文字起こしもGPUの裏で元mp4/.tsを読み続けるので、その足元で
消す/束ね直すと読み手が壊れる(削除の実行直前に見る `busy_recording_ids()` と同じ集合)。

除外した件数は理由ごとに数えて返す。「対象0本」とだけ出ると、原因を探して回ることになる。

## group と domain

session一括と同じく、行は**録画ごとに分ける**(再起動しても残りが走る・1本だけ取り消せる)。
同じ `group_id` を振るので、`POST /api/jobs/{group_id}/cancel` で一括ぶんをまとめて取り消せる。

ただし `group_payload()` は **`group_id` を持つ = Session出力** とは見なさない。一括groupは
複数sessionへまたがるため、`session_overlay` として出すと履歴画面が先頭録画のsession行1つを
掴み、そのsessionに属さない録画まで含む進捗と件数をそこへ貼り付けてしまう。投入時に
`params={"bulk": True}` を付け、group の domain を `bulk_overlay` / `bulk_upscale` /
`bulk_reprocess` / `bulk_audionorm` に分け、`session_id` は `None` にする。

session数から推測しない。1 sessionしか持たない配信者への一括投入がSession出力として
畳まれてしまう。

## 進捗

この画面は進捗表を持たない。jobの台帳はJob画面(`/jobs`)が唯一の置き場で、縮小版を並べると
どちらが最新か分からなくなる(取消も再実行も向こうにしかない)。tabからはlinkだけを出す。
**文字起こしも同じ台帳(kind=stt)に載る**ので、行き先を種別で分けることもしない。

以前はこの画面に文字起こし専用のqueue表と一括取消buttonが同居していた。台帳が別だった頃の
名残で、`_enqueue_stt_jobs` が media_job_queue へ載せるようになった時点で **Job画面と同じ行を
2箇所で描く**状態になっていた(しかもWSの `transcribe_queue` 通知はもう飛ばないので、あちらの
表は自動更新すらしていなかった)。表はJob画面へ寄せ、そこに無かった一括取消は
`POST /api/jobs/cancel-matching?kind=` としてJob画面側へ移した — 種別filterと同じ範囲に効き、
範囲はserverが決める(手元の行だけを対象にすると、limitで切れた古い行が黙って残る)。

jobが1本終わると出力fileの有無が変わるため、`_media_job_runner` の `finally` で
`_fs_state_cache` / `_fs_bulk_cache` / `_bulk_status_cache` を捨てる。完了通知の直後に画面が
引き直したとき、TTLが残っていると「まだ未出力」と読める古い集計が返る。

## 集計コストとcache

対象判定 `_bulk_classify()` は録画1本ごとに **mp4の`stat()`・出力fileの`stat()`・HLS dirの
`glob("seg*.ts")`** を伴う。これを種別ごと(status は全種別)・呼び出しごとに繰り返すと、録画数が
多い配信者で `status` / `recordings` / `estimate` が数秒級に膨らむ(特に `reprocess` の glob)。

そのため filesystem 由来の事実は path を key に `_fs_bulk_cache`(TTL `_FS_BULK_TTL_SECONDS`) へ束ね、
`_bulk_classify()` はこの facts を受け取る純関数にして loop 内では disk を叩かない。二重投入の判定も
録画数ぶんの個別queryを避け、`storage.pending_media_job_keys()` で待機/実行中の
`(kind, recording_id)` を1回だけ集合化して照合する。無効化はfile が変わる唯一の契機であるjob完了
時の `_fs_bulk_cache.clear()` に一本化する(外部での手動移動はTTLぶん遅れて反映される)。

### 存在確認は録画ごとstatではなくdir単位のscandir

元mp4・焼き込み・Up出力は配信者ごとの単一 `mp4_dir` に**同居する**(layout)。そこで
`_bulk_fs_facts_batch()` が母集合を **dir単位で1回ずつ `os.scandir`** し、名前→sizeの一覧を作って
存在と容量を引く。録画数ぶんの `stat`(1本あたり元mp4・焼き込み・Up出力で数回)が、配信者数ぶんの
readdir へ畳まれる(数千本規模で効く)。判定するfileの集合は個別stat版と同一 — `_output_done` /
`upscale_done` と**同じヘルパ**(`overlay_paths` / `upscale_output_path` / `upscale_input_path`)で
pathを組み、`.is_file()` の代わりに一覧への membership に置き換えるだけ(ファイル名規則を二重に
持たない)。dirが読めなければ空=そのdirの録画は全て未存在、という正しい解釈で、fallbackではない。
`status`/`recordings`/`plan` はこのbatchを通す。単発の `_recording_fs_facts()` は据え置き(session
一覧やreprocessの遅延has_hlsが使う)。`_recording_output_state()`(session一覧)は別cacheのまま。

path を持たない録画(録画中/finalize前)は互いにpathを共有するので、keyにするとfactを取り違える。
cacheはpathを持つ録画に限り、それ以外は都度算出する(件数が少なく安い)。

### .ts走査(`has_hls`)は再mp4化を見るときだけ

`has_hls`(=`_find_hls_root` の `_has_usable_media`)は **reprocess の判定にしか要らない**のに、全録画
ぶんを他種別の集計でも回すと無駄が大きい。そこで `_recording_fs_facts()` は has_hls を **含めず**、
reprocess判定に入ったときだけ `_recording_has_hls()` が遅延で引いて facts dict へ書き戻す(同TTL窓は
1回)。`glob` は `any(...)` で最初のセグメントで打ち切るので、走査する場合も全.tsの列挙にはならない。

`GET /api/bulk/status` は `kinds` で集計種別を絞れる。**既定は reprocess を除いた
`_BULK_STATUS_DEFAULT_KINDS`(overlay/upscale/audionorm)** で、tabを開くだけ・焼き込み等を見るだけの
間は .ts走査が**一切走らない**。画面の種別既定も焼き込み(`bulk-kind` の先頭 `selected`)にしてある。
再mp4化を選んだときだけ画面が `?kinds=reprocess` を要求し、その1回で走査してcacheする(以降は即時)。
statusのcacheは要求種別の組をkeyにし、file変化(job完了)・投入時に `_bulk_status_cache.clear()`。

reprocessを集計するときも、has_hlsを録画ごとの `is_dir` で見るのではなく `_bulk_hls_batch()` が
**配信者ごとの `ts/` を1回scandir**して stem dir の有無で足切りし、実在する dir だけ
`_has_usable_media()`(素材と再生listの両方)で中身を確認する(`_find_hls_root` と厳密に等価)。
retentionで.tsが消えた録画は
親一覧だけで即決し、録画ごとのstatを起こさない。`status` は種別に関わらず必ず呼ぶ — 実体の有無
(`playable`)がこの走査でしか出せず、要求種別によって `has_hls` が埋まったり埋まらなかったり
すると、同じ配信者が要求の仕方で「実体なし」と名乗ったり名乗らなかったりする。単発の
`_recording_has_hls()` は据え置き(facts未充填のとき遅延)。

集計は数秒かかり得るので、画面側は待つ間 `loadBulk()` が先に「集計中…」を出し、cellを開いて
録画一覧を引く間は明細行に「録画を読み込み中…」を出す。古い/空の表を無反応で残さない。
`recordings` / `estimate` は開いたcellの種別だけを見るので、そのまま on-demand で走査する。

## 文字起こし(`transcribe`)

対象の選び方は同じ `_bulk_plan` を通し、投入は `_enqueue_stt_jobs` が media_job_queue へ
**kind=stt** の行として載せる(`POST /api/bulk/queue` が kind で振り分けるため
`BULK_QUEUE_KINDS` には入らないが、台帳は同じ)。GPUは直列に1本ずつ使う。

台帳が同じなので、進捗も取り消しも再実行もJob画面が持つ。画面の語(「文字起こし」)は
`ops_labels` の訳語と揃える — 同じ行を2つの名前で呼ばない。

| 項目 | 他の種別との違い |
| --- | --- |
| 済み判定 | `transcripts` 表の有無だけ。文字起こしはfileを作らないのでfilesystemからは判別できない |
| 入力 | mp4でも素材(.ts)でもよい(`hls_source` 経由)。両方無いときだけ `no_source` |
| 二重投入 | 照合先は台帳の `pending_media_job_keys()` の kind=stt。画面のkind名(`transcribe`)へ読み替えて照合する |
| 所要の実測比 | 他の種別と同じく台帳の実測から出る(kind=stt の完了実績) |
| 同時実行数 | 常に1。STTは `transcription._transcribe_lock` で完全に直列化されている |
| 空き容量 | 見ない。書くのはtranscript行だけで、中間fileも出力fileも作らない |

「出力済みも作り直す」は伏せない。model を替えたときや時刻mapの版が上がったとき
(既存transcriptのseekがずれる)は文字起こしをやり直すしかないため。済み判定は `transcripts` 表なので、
redoは他の種別と同じく `_bulk_plan` が `done` を対象へ戻すだけでよい(台帳へは新しい行を
積む)。伏せるのは `pack` と `delete_mp4` だけ — 前者は冪等、後者は一方通行で、どちらも
`redo` を効かせると画面の本数だけが実際より多くなる。

## ts結合(`pack`)

素材の`.ts`を解像度の切れ目ごとに1 fileへ束ね直す(実体は `tictok/record/hls_pack.py`、設計は
そのmodule docstring)。**再encodeしないbyte連結**なので、映像も再生も再mp4化の結果も変わらず、
file数だけが減る。2秒ごとに刻まれたsegmentが1録画で数千本あり、走査・backup・移送のすべてが
file数に比例して重くなるのを畳むための処理である(2026-07-25実測: 対象128本で seg 286,211 file)。

対象は **素材があって、まだ束ねていない録画**。素材の有無は他の種別と同じ `_has_usable_media`
(素材と再生listの両方)で、束ね済みかは `hls_pack.is_packed()` — 束ねたfileの実在だけが根拠で、
DBには印を持たない(外で消えたり戻ったりする)。**mp4の有無は問わない**: 束ねるのは素材そのもの
なので、mp4を消した録画も対象であり続ける(`_bulk_classify` は `has_file` の手前で答える)。

束ね済みは `skipped.packed`(「結合済み」)として返し、画面の「済」件数にも数える
(`_BULK_DONE_REASONS`)。作り直す余地が無いので「出力済みも作り直す」は伏せる — 束ね済みへ
投げても `already_packed` で何もしない冪等な操作で、押せる状態で残すと投入本数の見え方だけが
狂う。

| 前提 | 扱い |
| --- | --- |
| 素材の在るvolumeの空きが素材と同じだけ無い | 507で止める。元segmentは3段の検証を全て通るまで消さないので、束ねる間は2本分が同時に存在する |
| 同じ録画を他のjobが掴んでいる | `JobDeferred` で待つ。再mp4化は素材をplaylist順に読んでいる最中で、その足元でsegmentを消すと読み手が壊れる |
| 既に束ね済み | 何もせず `already_packed` を返す(冪等) |
| `pack_session` が失敗 | `reason` をそのままjobのerrorに出す。失敗しても元は一切触られない(束ねたfileを捨てて元を残す)ので復旧手順は無い |

取り消しは**進捗callbackの位置でしか効かない**。`pack_session` はcancel tokenを持たないので、
server側は `on_progress` で `cancel.check_cancelled()` を呼ぶ。実測した刻みは
`(5%, 束ねたfile 0本) → (60%, 0本) → (100%, 1本)` で、5%と60%は**まだ何も書いていない**時点、
100%は元segmentの削除まで終わった後。よって100%では中断しない(済んだ作業を取り消し扱いに
してしまう)。時間の大半を占めるsegmentごとのffprobe(`_resolutions_for`)の最中には
callbackが無いため、その間の取り消しは60%の地点まで待つことになる。

## 元mp4の削除(`delete_mp4`)

再mp4化は元mp4を退避してから作り直すので、実行中は一時的に2本分の容量が要る。空きが無い
diskではそれが通らないため、**先に元mp4を消してから作り直す**経路を用意する。

対象は **`.ts`が残っている録画だけ**。同じ材料から作り直せることが、消してよい唯一の根拠で
ある。`.ts`が残っていない録画のmp4は唯一の再取得不能資産なので、対象から外し、見積りの
`skipped.no_hls` として返す。画面はそれを内訳の1行ではなく**警告**として名指しで出す
(「⚠ .tsが残っていない録画がN本あります。これらのmp4は作り直せないため削除しません」)。
警告だけで、実行そのものは止めない — 消せるぶんは消せる。

消すのは **DB行が名指ししているfile 1本だけ**。焼き込み(`.overlay.mp4`)・Up出力(`.up.mp4`)・
手で名前を変えたfileは、この録画から派生した**別の成果物**であって作り直しの対象ではない。
「stemで始まるmp4」を消しに行くとそれらを巻き込むので、`recordings.filename` と一致する
file以外は触らない。

保護flagの立った録画(`protected`)と、job/文字起こしが掴んでいる録画(`busy_recording_ids`)は
対象外。後者は実行の直前にもう一度確認する — planを組んでからの間に投入された焼き込みは、
元mp4を読みながら走っている。

削除後は、その録画についての主張を落とす:

| 列 | 理由 |
| --- | --- |
| `bytes` → 0 | 実体が無いのにsizeが残ると、容量集計がその分だけ嘘になる |
| `reprocessed_at` → NULL | 「作り直し済み」はこのfileについての主張。消した以上、一括再mp4化の対象へ戻すのが正しい |
| `audio_normalized_at` → NULL | 同上 |

queueには載せない。fileを1本消すだけでffmpegを起こさないので、実行時間0のjob行が録画数ぶん
台帳に並ぶだけになる(`BULK_QUEUE_KINDS` から外し、専用APIで即時に実行する)。取り消せない
操作なので、確認行に加えて確認dialogをもう一段挟む。
