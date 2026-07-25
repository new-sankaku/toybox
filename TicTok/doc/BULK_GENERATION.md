# 配信者まるごとの一括処理

焼き込み(`overlay`) / Up出力(`upscale`) / 再mp4化(`reprocess`) / 音量正規化(`audionorm`) /
元mp4の削除(`delete_mp4`)を、Sessionではなく**配信者単位**(または全配信者、あるいは選んだ
録画だけ)で実行する。画面は配信者動画(`/videos`)の「一括処理」tab、API は
`GET /api/bulk/status`, `GET /api/bulk/estimate`, `GET /api/bulk/recordings`,
`POST /api/bulk/queue`, `POST /api/bulk/delete-mp4`。

「生成」ではなく「処理」なのは、作らずに**消す**種別を含むようになったため。

音量正規化そのものの設計(なぜone-pass loudnorm単体か)は [AUDIO_NORMALIZE.md](AUDIO_NORMALIZE.md)。

## なぜ配信者タブではなく配信者動画タブか

配信者(`/streamers`)は「1人を選んで全Sessionを集約分析する」画面で、次の2つを持っていない。

- **全配信者横断の投入**を表現する場所（構造上、1人ぶんしか出せない）
- **対象数の判定**（もう全部出力済みの配信者をdisableできない）

一方 `/videos` の「一括文字起こし」tabは既に *配信者別の表 + 行button + 全配信者button* という
形を持っており、一括生成はそこへ種別が増えるだけである。同tabのcomment(videos.html)にある
「toolbarにselect+buttonを重ねると、済んだ配信者も投入できてしまう劣った経路が並ぶだけだった」
という判断をそのまま引き継ぐため、**配信者画面には投入buttonを置かず、linkだけ**を出す
(`/videos?streamer=<unique_id>#bulk`)。

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
| 全配信者 | toolbarの「全配信者をまとめて」 | 表に出ている全配信者の未処理 |
| 配信者1人 | 行右端のbutton | その配信者の未処理すべて |
| 録画を選んで | 行左の ▶ で開き、checkboxで選んで「選んだN本を投入」 | 選んだ録画だけ |

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
正規化せずに作り直したら必ずこの列をNULLへ戻す。

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

この画面は進捗表を持たない。映像jobの台帳はJob画面(`/jobs`)が唯一の置き場で、縮小版を並べると
どちらが最新か分からなくなる(取消も向こうにしかない)。tabからはlinkだけを出す。

jobが1本終わると出力fileの有無が変わるため、`_media_job_runner` の `finally` で
`_fs_state_cache` / `_fs_bulk_cache` / `_bulk_status_cache` を捨てる。完了通知の直後に画面が
引き直したとき、TTLが残っていると「まだ未出力」と読める古い集計が返る。

## 集計コストとcache

対象判定 `_bulk_classify()` は録画1本ごとに **mp4の`stat()`・出力fileの`stat()`・HLS dirの
`glob("seg*.ts")`** を伴う。これを種別ごと(status は4種別)・呼び出しごとに繰り返すと、録画数が
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

`has_hls`(=`_find_hls_root` の `glob("seg*.ts")`)は **reprocess の判定にしか要らない**のに、全録画
ぶんを他種別の集計でも回すと無駄が大きい。そこで `_recording_fs_facts()` は has_hls を **含めず**、
reprocess判定に入ったときだけ `_recording_has_hls()` が遅延で引いて facts dict へ書き戻す(同TTL窓は
1回)。`glob` は `any(...)` で最初のセグメントで打ち切るので、走査する場合も全.tsの列挙にはならない。

`GET /api/bulk/status` は `kinds` で集計種別を絞れる。**既定は reprocess を除いた
`_BULK_STATUS_DEFAULT_KINDS`(overlay/upscale/audionorm)** で、tabを開くだけ・焼き込み等を見るだけの
間は .ts走査が**一切走らない**。画面の種別既定も焼き込み(`bulk-kind` の先頭 `selected`)にしてある。
再mp4化を選んだときだけ画面が `?kinds=reprocess` を要求し、その1回で走査してcacheする(以降は即時)。
statusのcacheは要求種別の組をkeyにし、file変化(job完了)・投入時に `_bulk_status_cache.clear()`。

reprocessを集計するときも、has_hlsを録画ごとの `is_dir` で見るのではなく `_bulk_hls_batch()` が
**配信者ごとの `ts/` を1回scandir**して stem dir の有無で足切りし、実在する dir だけ既存の
`glob("seg*.ts")` で中身を確認する(`_find_hls_root` と厳密に等価)。retentionで.tsが消えた録画は
親一覧だけで即決し、録画ごとのstatを起こさない。母集合単位の呼び出し(status/recordings/plan)が
kindにreprocessを含むときだけ呼ぶ。単発の `_recording_has_hls()` は据え置き(facts未充填のとき遅延)。

集計は数秒かかり得るので、画面側は待つ間 `loadBulk()` が先に「集計中…」を出し、種別/再出力を
変えて録画一覧を引き直す間は明細行に「録画を読み込み中…」を出す。古い/空の表を無反応で
残さない。`recordings` / `estimate` の reprocess判定は元々そのtabを見るとき限定なので、そのまま
on-demand で走査する。

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

保護flagの立った録画(`protected`)と、job/転写が掴んでいる録画(`busy_recording_ids`)は
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
