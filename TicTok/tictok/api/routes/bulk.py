"""一括生成: 種別ごとに「まだ作られていない録画」を選んでまとめてqueueへ積む。

対象の選別(``_bulk_classify``)がここに居るのは、除外理由の文言(``BULK_SKIP_LABELS``)と
一体で画面に出るため。判定の材料は ``fsfacts`` から一括で取る。
"""

import asyncio
import secrets
import time
from typing import Optional
from fastapi import HTTPException, Query
from pydantic import BaseModel
from tictok.core.config import get_laugh_index_exclude_coop, get_media_queue_workers
from tictok.record.transcription import TIMEMAP_VERSION, stt_available
from tictok.media import laugh_audio
from tictok.search import indexer
from tictok.storage import OPS_INFO, OPS_WARNING
from tictok.record.video_overlay import subtitles_enabled
from fastapi import APIRouter
from tictok.api import disk
from tictok.api import files
from tictok.api import fsfacts
from tictok.api import media_jobs
from tictok.api import runtime
from tictok.core import perf

router = APIRouter()


# ===== 配信者まるごとの一括生成 =====

# 一括投入を許すkind。任意のkindを通すと、preview等の一括に向かないjobまで配信者単位で
# 大量に積めてしまうので、ここに挙げたものだけを受け付ける。
BULK_KINDS = ("transcribe", "laugh", "voice", "gain", "overlay", "upscale", "reprocess",
              "audionorm", "pack", "delete_mp4")

# queueへ載る種別。delete_mp4はfileを1本消すだけでffmpegを起こさないため、jobにすると
# 実行時間0の行が録画数ぶん台帳へ並ぶだけになる。専用APIで即時に実行する。
# 文字起こしもここには入らない: 走る先は同じmedia_job_queue(kind=stt)だが、投入は
# _enqueue_stt_jobs が持つ(group_idを振らない)ため、同じ投入APIから種別で振り分ける。
BULK_QUEUE_KINDS = ("overlay", "upscale", "reprocess", "audionorm", "pack", "voice", "gain")

# 出力fileを作らない種別。残すのは録画1本あたり数百kB〜1MB程度のsidecarだけなので、投入前の
# 空き容量判定を通す(文字起こし・笑い声分析はそもそも別の投入口でこの判定を通らない)。
BULK_NO_OUTPUT_KINDS = ("voice", "gain")

# 対象判定に .ts の走査が要る種別。母集合単位の呼び出しは _bulk_hls_batch で先に埋める。
# 焼き込み・Up出力・文字起こしが入っているのは、mp4が無い録画でも素材から処理できるため —
# 素材の有無を見ずに判定すると、単体では処理できる録画が一括だけ弾かれる。
BULK_HLS_KINDS = ("transcribe", "laugh", "overlay", "upscale", "reprocess", "delete_mp4",
                  "pack", "waveform", "gain", "sprite", "voice")

# 対象判定に .sidecars の走査が要る種別。母集合単位の呼び出しは _bulk_sidecar_batch で
# 先に埋める(録画ごとのstatにすると数千本で効く)。
BULK_SIDECAR_KINDS = ("waveform", "gain", "sprite", "voice")

# 一括投入の種別名。映像jobの台帳に出る語(MEDIA_JOB_TITLES)と揃えるが、そこに無い種別
# (文字起こし・元mp4の削除)も画面と409本文で名乗る必要があるので、この画面の語彙として
# 別に持つ。MEDIA_JOB_TITLESへ足すと、media_job_queueに存在しないkindが混ざる。
BULK_KIND_TITLES = {**media_jobs.MEDIA_JOB_TITLES, "transcribe": "文字起こし",
                    "delete_mp4": "元mp4の削除"}
# 済み判定に検索indexを見る種別。sidecarの有無ではなくindexの有無で見るのは、解析だけ
# 済んでindexへ入っていない録画(先に解析を回した / 閾値を変えた)を拾い直せるようにする
# ため。解析済みならjobはcacheに当たって数十msで終わり、indexだけが埋まる。
BULK_SEARCH_INDEX_KINDS = ("laugh",)

# 対象外にした理由の表示名。画面と409本文で同じ語を使う。
BULK_SKIP_LABELS = {
    "recording": "録画中",
    # 実体が何も無い(素材もmp4も)場合と、mp4だけが無い場合は別物。前者はこの録画に
    # 手が出せない、後者は「mp4を要る操作」に限った不足で、素材から作り直せる。
    "no_source": "素材もmp4も無い",
    "no_file": "元mp4が無い",
    "no_hls": ".tsが残っていない",
    "packed": "結合済み",
    "protected": "保護されている",
    "busy": "処理中の録画",
    # 「出力済み」ではなく「処理済み」。音量正規化は出力を作らず元mp4を差し替えるので、
    # 種別をまたいで通じる語にする(画面のBULK_SKIP_LABELSと同じ語であること)。
    "done": "処理済み",
    "queued": "既にqueueにある",
}

# 「済」として数える対象外理由。ts結合の済みは作り直せる出力ではないので"done"とは別の理由に
# するが、画面の済み件数からは落とせない(結合済みが0本と出ると、進み具合が読めなくなる)。
_BULK_DONE_REASONS = ("done", "packed")

# statusの既定集計種別。全種別を一度に数える — 画面は種別を列に並べた1枚の表なので、
# 種別を選ぶたびに集計し直す形にすると、列が増えるほどrequestが増える。
# かつて reprocess だけを既定から外していたのは「対象判定に録画ごとの.ts走査を伴う」ため
# だったが、その走査(_bulk_hls_batch)は overlay/upscale の判定でも要るので既定でも走って
# いた。除外は集計costを何も減らしておらず、画面に「選ぶまで数字が出ない列」を作るだけ
# だった。全種別を足しても増えるのは判定loop(dict操作)とDB照会2本だけである。
_BULK_STATUS_DEFAULT_KINDS = BULK_KINDS


def _require_bulk_kind(kind: str) -> None:
    if kind not in BULK_KINDS:
        raise HTTPException(status_code=400, detail=f"一括生成できない種別です: {kind}")


def _parse_bulk_status_kinds(kinds: Optional[str]) -> tuple:
    """statusで集計する種別。未指定は軽い既定(reprocess除く)。BULK_KINDS外は弾く。"""
    if not kinds:
        return _BULK_STATUS_DEFAULT_KINDS
    requested = tuple(k for k in kinds.split(",") if k in BULK_KINDS)
    if not requested:
        raise HTTPException(status_code=400, detail=f"一括生成できない種別です: {kinds}")
    return requested


def _laugh_index_current(meta: Optional[dict]) -> bool:
    """この録画の笑い声indexが、今の条件で張られたものか。

    行の有無では見ない。共演中を外す設定(``TICTOK_LAUGH_INDEX_EXCLUDE_COOP``)やrule版を
    変えると、同じ行が別の意味を持つためで、古い条件のindexを済みのままにすると誰も
    張り直せない。条件を記録していない録画(この仕組みより前に張ったindex)も対象へ戻す。
    """
    if not meta:
        return False
    return (meta.get("version") == indexer.LAUGH_INDEX_VERSION
            and meta.get("mode") == get_laugh_index_exclude_coop())


def _bulk_classify(kind: str, recording: dict,
                   facts: Optional[dict] = None,
                   transcribed: Optional[set] = None,
                   indexed: Optional[dict] = None,
                   laugh_meta: Optional[dict] = None) -> tuple[bool, str]:
    """この録画がkindの投入対象か。(対象か, 対象外の理由) を返す。

    理由を数えて画面へ返すのは、「対象0本」とだけ出ると原因(fileが無いのか、既に出力済みか、
    .tsが残っていないのか)が分からず、押せない理由を探して回ることになるため。

    ``facts`` は_recording_fs_factsのcache済みfilesystem事実。呼び出し側が録画数ぶんの
    loopで1回だけ引いて渡すことで、種別ごと・呼び出しごとのstat/globの重複を無くす。

    ``transcribed`` は**字幕として使える**文字起こしを持つrecording_id集合(transcribeの済み判定)。
    facts と同じく母集合単位で1回だけ引いて渡す — 録画ごとにget_transcriptを叩くと、本文まで
    読んで捨てることになる。行の有無ではなく中身の版で引く理由は
    ``current_transcript_recording_ids`` を参照。

    ``indexed`` は ``storage.search_indexed_counts()``(recording_id -> source -> 件数)。
    コメント索引の本数に使う。

    ``laugh_meta`` は ``storage.laugh_index_meta_map()``(recording_id -> indexを張った
    条件)。笑い声分析の済み判定に使う。
    """
    if recording.get("status") not in ("completed", "interrupted"):
        return False, "recording"
    if facts is None:
        facts = fsfacts._recording_fs_facts(recording)
    if kind == "laugh":
        # 入力は素材(.ts)でもmp4でもよい(laugh_audioはhls_source経由で開く)。
        has_hls = facts.get("has_hls")
        if has_hls is None:
            has_hls = fsfacts._recording_has_hls(recording)
        if not facts["has_file"] and not has_hls:
            return False, "no_source"
        # 済み判定は**indexを張った条件**で見る。sidecar(確率列)だけ在ってindexが無い
        # 録画は「解析は済んだが検索に出ない」状態で、sidecarで済みにすると誰も拾い直せ
        # ない。jobは解析cacheに当たって数十msで終わり、indexだけを埋める。行の有無でも
        # 足りない: 共演中を外す設定を変えると同じ行が別の意味になり、外れていないindexが
        # 済みのまま残る。
        if laugh_meta is None:
            laugh_meta = runtime.storage.laugh_index_meta_map()
        done = _laugh_index_current(laugh_meta.get(recording["id"]))
        return (False, "done") if done else (True, "")
    if kind == "transcribe":
        # 入力は素材(.ts)でもmp4でもよい(文字起こしはhls_source経由で開く)。
        has_hls = facts.get("has_hls")
        if has_hls is None:
            has_hls = fsfacts._recording_has_hls(recording)
        if not facts["has_file"] and not has_hls:
            return False, "no_source"
        # 済み判定はDBのtranscripts表だけ。文字起こしはfileを作らないので、filesystemからは
        # 判別できない。行の有無では足りない: 語ごとの時刻を持たない文字起こしはcueを語の端で
        # 締められず、segmentの終端が次のsegmentの開始まで伸びたまま出る(実測: SRTが
        # timelineを覆う割合が中央値97.7%。実発話は約30%)。時刻mapの版が古いものも同様に
        # 再文字起こしでしか直らない。どちらも「済み」から外す(current_transcript_recording_ids)。
        if transcribed is not None:
            done = recording["id"] in transcribed
        else:
            stored = runtime.storage.get_transcript(recording["id"])
            done = bool(stored
                        and stored.get("timemap_version") == TIMEMAP_VERSION
                        and stored.get("word_times"))
        return (False, "done") if done else (True, "")
    if kind == "reprocess":
        # 済み判定はDBの列だけを見る。作り直したmp4は元と同じ名前・場所の別内容なので、
        # fileからは判別できない。印が無かった頃は、一括投入のたびに.tsが残る録画を全部
        # 作り直し、そのたび元mp4が_backupへ積まれていた(同一録画に3世代・退避307GB)。
        if recording.get("reprocessed_at"):
            return False, "done"
        # has_hls(.ts走査)はreprocess/削除を見るときだけ。母集合単位で呼ぶ側が
        # _bulk_hls_batchで先に埋めておく(dir単位)。単発呼び出し(facts未充填)は
        # _recording_has_hlsが遅延で引く。
        has_hls = facts.get("has_hls")
        if has_hls is None:
            has_hls = fsfacts._recording_has_hls(recording)
        return (True, "") if has_hls else (False, "no_hls")
    if kind == "pack":
        # 束ねるのは素材そのものなので、mp4の有無は問わない(has_fileの手前で答える)。
        # 済み判定はfilesystemが正 — 束ねたfileが在ることだけが「束ね済み」の根拠で、
        # DBには印を持たない(外で消えたり戻ったりする)。
        has_hls = facts.get("has_hls")
        if has_hls is None:
            has_hls = fsfacts._recording_has_hls(recording)
        if not has_hls:
            return False, "no_hls"
        packed = facts.get("packed")
        if packed is None:
            packed = fsfacts._recording_packed(recording)
        return (False, "packed") if packed else (True, "")
    if kind in fsfacts.SIDECAR_JOB_FACTS:
        # 入力は素材(.ts)でもmp4でもよい(生成側はhls_source経由で開く)。済み判定はcache
        # fileの実在だけを見る — 波形もspriteも声profileもDBに印を持たず、外で消えたり
        # 戻ったりする。
        has_hls = facts.get("has_hls")
        if has_hls is None:
            has_hls = fsfacts._recording_has_hls(recording)
        if not facts["has_file"] and not has_hls:
            return False, "no_source"
        fact = fsfacts.SIDECAR_JOB_FACTS[kind]
        done = facts[fact] if fact in facts else fsfacts._recording_sidecar_done(recording, fact)
        return (False, "done") if done else (True, "")
    if kind in ("overlay", "upscale"):
        # 入力は原本の .ts で足りる(焼き込みはvideo_overlay、Up出力はupscale、どちらも
        # hls_source経由)。mp4を要求すると、単体では焼ける録画が一括だけ「録画fileが無い」
        # で弾かれ、配信者の全録画が対象0本になる。
        has_hls = facts.get("has_hls")
        if has_hls is None:
            has_hls = fsfacts._recording_has_hls(recording)
        if not facts["has_file"] and not has_hls:
            return False, "no_source"
        done = facts["overlay_done"] if kind == "overlay" else facts["upscale_done"]
        return (False, "done") if done else (True, "")
    if not facts["has_file"]:
        return False, "no_file"
    if kind == "delete_mp4":
        # 元mp4を消してよいのは、同じ内容を作り直せる材料(.ts)が残っている場合だけ。
        # .tsが無い録画のmp4は唯一の再取得不能資産で、消せば復元手段が無い。
        if recording.get("protected"):
            return False, "protected"
        has_hls = facts.get("has_hls")
        if has_hls is None:
            has_hls = fsfacts._recording_has_hls(recording)
        return (True, "") if has_hls else (False, "no_hls")
    if kind == "audionorm":
        # 済み判定はDBの列だけを見る。mp4からは正規化の有無を判別できない(loudnormは
        # 痕跡を残さない)ため、file側から推測してはいけない。
        return (False, "done") if recording.get("audio_normalized_at") else (True, "")
    # BULK_KINDS は上で全て答えている。ここへ来るのは種別の追加漏れで、対象外の理由として
    # 黙って返すと画面には「対象0本」としか出ず原因が消える。
    raise HTTPException(status_code=400, detail=f"一括生成の判定に無い種別です: {kind}")


def _bulk_recordings(unique_id: Optional[str]) -> list:
    """一括生成の母集合。unique_id未指定なら全配信者。"""
    if unique_id:
        return runtime.storage.recordings_for_user(unique_id)
    return runtime.storage.list_recordings(100000)


def _bulk_plan(kind: str, unique_id: Optional[str], redo: bool,
               recording_ids: Optional[list] = None) -> dict:
    """投入対象と、対象外にした理由の内訳。実際の投入はこの結果だけを使う(estimateと
    queueで別々に絞ると、見せた本数と積んだ本数が食い違う)。

    ``recording_ids`` を渡すと、その録画だけを母集合にする(画面で選んだ分だけの投入)。
    選外の録画は「対象外」ではないので理由にも数えない — 内訳に混ぜると、選ばなかった
    ぶんが不具合で弾かれたように読める。
    """
    selected = set(recording_ids) if recording_ids is not None else None
    # 二重投入の判定は録画数ぶん引くと重い。待機/実行中の (kind, id) を1回で集合化して照合する。
    # 文字起こしも同じ台帳(kind=stt)なので、画面側のkind名"transcribe"へ読み替えるだけでよい。
    pending = runtime.storage.pending_media_job_keys()
    stt_pending = {rid for kind_, rid in pending if kind_ == "stt"}
    pending |= {("transcribe", rid) for rid in stt_pending}
    # 素材やmp4を掴んでいる録画。文字起こしもGPUの裏で元mp4/.tsを読み続けるので、映像jobと
    # 同じく「掴んでいる」側に数える(削除の実行直前に見るbusy_recording_idsと同じ集合)。
    busy_ids = {rid for _kind, rid in pending} | stt_pending
    recordings = _bulk_recordings(unique_id)
    transcribed = runtime.storage.current_transcript_recording_ids(TIMEMAP_VERSION) if kind == "transcribe" else None
    # 済み判定に検索indexを見る種別は、母集合単位で1回だけ引く(録画ごとに引くと
    # 録画表の集計が録画数ぶん走る)。
    laugh_meta = (runtime.storage.laugh_index_meta_map()
                  if kind in BULK_SEARCH_INDEX_KINDS else None)
    facts_by_id = fsfacts._bulk_fs_facts_batch(recordings)
    if kind in BULK_HLS_KINDS:
        fsfacts._bulk_hls_batch(recordings, facts_by_id)
    if kind in BULK_SIDECAR_KINDS:
        fsfacts._bulk_sidecar_batch(recordings, facts_by_id)
    targets: list = []
    skipped: dict = {}
    for recording in recordings:
        if selected is not None and recording["id"] not in selected:
            continue
        ok, reason = _bulk_classify(kind, recording, facts_by_id[recording["id"]],
                                    transcribed, None, laugh_meta)
        # 素材やmp4を置き換える種別は、他の何かがその録画を掴んでいる間は外す。焼き込みは
        # 実行中ずっと元mp4を読み、再mp4化は素材を読んでいるので、その足元で消す/束ね直すと
        # 道半ばで壊れたjobが残る。
        if ok and kind in ("delete_mp4", "pack") and recording["id"] in busy_ids:
            skipped["busy"] = skipped.get("busy", 0) + 1
            continue
        # 「済みも再出力」を選んでいるときだけ、出力済みを対象へ戻す。
        if not ok and not (redo and reason == "done"):
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        if (kind, recording["id"]) in pending:
            skipped["queued"] = skipped.get("queued", 0) + 1
            continue
        targets.append(recording)
    targets.sort(key=lambda r: r.get("started_at") or 0)
    return {"targets": targets, "skipped": skipped}


def _bulk_estimate(kind: str, targets: list) -> dict:
    """投入前に見せる規模。所要時間は過去の同種jobの実測比(中央値)からのみ出す。

    倍率を設定値や定数で持たないのは、GPU・model・解像度で数倍変わるため。実績が無ければ
    eta_secondsをNoneで返し、画面は「実績が無いため不明」と出す(それらしい数字を置くと、
    実測から出した数字と区別できなくなる)。
    """
    sizes: list = []
    for recording in targets:
        facts = fsfacts._recording_fs_facts(recording)
        if facts["has_file"]:
            sizes.append(facts["bytes"])
    # 実測比の出所は種別の走る台帳。文字起こしはmedia_job_queueに行が出ないので、そちらを見ても
    # 常に「実績なし」になる。
    # 文字起こしも同じ台帳で走るので、実測の出所はkind名の読み替えだけで済む。
    durations = runtime.storage.media_job_durations("stt" if kind == "transcribe" else kind)
    ratios = sorted(elapsed / source for elapsed, source in durations)
    seconds = sum(files._recording_seconds(r) for r in targets)
    median = ratios[len(ratios) // 2] if ratios else None
    # 同時実行数ぶんのjobが並ぶので、中間fileの山も本数ぶん重なる。1本ぶんで見せると、
    # workerを増やした環境で「入るはず」と示した直後に空き容量を割る。
    # 文字起こしはSTT側のlockで完全に直列化されており、workerを増やしても1本ずつしか進まない。
    # 笑い声分析も同じ: cudaならgpu_slot、cpuなら_infer_lockで、どちらも1本ずつになる。
    workers = 1 if kind in ("transcribe", "laugh") \
        else min(get_media_queue_workers(), len(sizes) or 1)
    return {
        "recordings": len(targets),
        "seconds": seconds,
        "source_bytes": sum(sizes),
        # 中間fileは作って消えるので、山になるのは合計ではなく同時に走る本数ぶん。
        "largest_source_bytes": sum(sorted(sizes, reverse=True)[:workers]) if sizes else 0,
        # 実測比は1本ぶんの所要時間から出ているので、同時実行数で割って詰まる。
        "eta_seconds": seconds * median / workers if median else None,
        "eta_samples": len(ratios),
    }


@router.get("/api/bulk/status")
async def bulk_status(kinds: Optional[str] = None) -> dict:
    """配信者ごとの、種別ごとの残り本数と出力済み本数。表示専用で投入はしない。

    ``kinds`` 未指定は全種別。集計は要求種別の組ごとにcacheする。

    実体の有無(``playable``)とコメント索引の本数(``comment_indexed``)も返す。どちらも投入
    対象の数ではないが、この一覧は画面の配信者選択そのものでもあるため: DB行だけを数えると、
    素材もmp4も残っていない配信者(retentionで消えた・外で消された)が「録画N本」を名乗って
    選択肢に出続ける。同じ走査を別endpointでもう一度やると、同じ画面に母集合の違う「録画」
    列が2つ並ぶことになる。"""
    requested = _parse_bulk_status_kinds(kinds)
    now = time.time()
    key = ",".join(sorted(requested))
    cached = fsfacts._bulk_status_cache.get(key)
    if cached is not None and cached[0] > now:
        return {**cached[1], "disk": disk._disk_report(),
                "stt_available": stt_available()}

    def _collect() -> list:
        # 内訳を phase で残す。cache miss 1回が約1秒で、DB(10ms)とfs走査(70ms)を引いた残り
        # 9割が /api/perf 上は "other" にしか出ず、どこが重いのか判断できなかった。
        with perf.phase("bulk.db"):
            recordings = runtime.storage.list_recordings(100000)
            transcribed = runtime.storage.current_transcript_recording_ids(TIMEMAP_VERSION) if "transcribe" in requested else None
            # 索引の件数はコメント索引の列に要る。種別に関係なく引くのはそのため(この一覧が
            # 検索側の配信者選択の出所でもある)。
            indexed = runtime.storage.search_indexed_counts()
            laugh_meta = runtime.storage.laugh_index_meta_map() if "laugh" in requested else None
        with perf.phase("bulk.facts"):
            facts_by_id = fsfacts._bulk_fs_facts_batch(recordings)
            # 種別に関わらず引く。実体の有無(playable)がこの走査でしか出せないためで、要求種別に
            # よって has_hls が埋まったり埋まらなかったりすると、同じ配信者が要求の仕方で
            # 「実体なし」と名乗ったり名乗らなかったりする。
            fsfacts._bulk_hls_batch(recordings, facts_by_id)
        with perf.phase("bulk.classify"):
            return _bulk_status_rows(recordings, requested, facts_by_id, transcribed,
                                     indexed, laugh_meta)

    payload = {"streamers": await asyncio.to_thread(_collect), "kinds": list(requested)}
    fsfacts._bulk_status_cache[key] = (now + fsfacts._BULK_STATUS_TTL_SECONDS, payload)
    # STTの可否はcacheへ入れない。設定で切り替わるものを20秒間そのままにすると、押せない
    # buttonが押せるままになる(押してから503で知ることになる)。
    return {**payload, "disk": disk._disk_report(), "stt_available": stt_available()}


def _bulk_status_rows(recordings: list, requested, facts_by_id: dict, transcribed,
                      indexed: dict, laugh_meta) -> list:
    """配信者ごとの残り本数と出力済み本数を数える。DBもfsも触らない純粋な集計。"""
    per: dict = {}
    for recording in recordings:
        entry = per.setdefault(recording["unique_id"], {
            "unique_id": recording["unique_id"],
            "recordings": 0,
            "playable": 0,
            "comment_indexed": 0,
            "seconds": 0.0,
            "targets": {kind: 0 for kind in requested},
            "done": {kind: 0 for kind in requested},
        })
        entry["recordings"] += 1
        entry["seconds"] += files._recording_seconds(recording)
        facts = facts_by_id[recording["id"]]
        if facts.get("has_hls") or facts.get("has_file"):
            entry["playable"] += 1
        if indexer.SOURCE_COMMENT in (indexed.get(recording["id"]) or {}):
            entry["comment_indexed"] += 1
        for kind in requested:
            ok, reason = _bulk_classify(kind, recording, facts, transcribed, indexed,
                                        laugh_meta)
            if ok:
                entry["targets"][kind] += 1
            elif reason in _BULK_DONE_REASONS:
                entry["done"][kind] += 1
    return sorted(per.values(), key=lambda e: -e["seconds"])


@router.get("/api/bulk/estimate")
async def bulk_estimate(kind: str, unique_id: Optional[str] = None,
                        redo: int = 0,
                        recording_id: Optional[list] = Query(default=None)) -> dict:
    """押す前に見せる見積り。配信者まるごとの焼き込みは数日走ることがあり、本数・尺・
    容量・所要を確認しないまま投入させてはならない。

    ``recording_id`` を複数渡すと、選んだ録画だけの見積りになる(投入と同じ絞り込み)。"""
    _require_bulk_kind(kind)
    ids = [int(value) for value in recording_id] if recording_id else None
    plan = await asyncio.to_thread(_bulk_plan, kind, unique_id, bool(redo), ids)
    estimate = await asyncio.to_thread(_bulk_estimate, kind, plan["targets"])
    return {"kind": kind, "unique_id": unique_id, "redo": bool(redo),
            "selected": len(ids) if ids is not None else None,
            "skipped": plan["skipped"], "disk": disk._disk_report(), **estimate}


@router.get("/api/bulk/recordings")
async def bulk_recordings(kind: str, unique_id: str, redo: int = 0) -> dict:
    """一括画面で配信者の行を開いたときに出す、録画1本ごとの投入可否。

    可否の判定は_bulk_classifyそのもので、画面側は理由を持たない(2箇所で判定すると
    「選べるのに投入されない録画」が出る)。"""
    _require_bulk_kind(kind)

    def _collect() -> list:
        pending = runtime.storage.pending_media_job_keys()
        pending |= {("transcribe", rid) for kind_, rid in pending if kind_ == "stt"}
        recordings = runtime.storage.recordings_for_user(unique_id)
        transcribed = runtime.storage.current_transcript_recording_ids(TIMEMAP_VERSION) if kind == "transcribe" else None
        laugh_meta = (runtime.storage.laugh_index_meta_map()
                      if kind in BULK_SEARCH_INDEX_KINDS else None)
        facts_by_id = fsfacts._bulk_fs_facts_batch(recordings)
        if kind in BULK_HLS_KINDS:
            fsfacts._bulk_hls_batch(recordings, facts_by_id)
        rows = []
        for recording in recordings:
            facts = facts_by_id[recording["id"]]
            ok, reason = _bulk_classify(kind, recording, facts, transcribed, None, laugh_meta)
            if not ok and redo and reason == "done":
                ok, reason = True, ""
            if ok and (kind, recording["id"]) in pending:
                ok, reason = False, "queued"
            rows.append({
                "id": recording["id"],
                "filename": recording.get("filename") or "",
                # 画面が名乗る番号はfile名の先頭のSession番号。file名が規約から外れた録画
                # (中断時のindex.m3u8など)はこちらから番号を引く。
                "session_id": recording.get("session_id"),
                "started_at": recording.get("started_at"),
                "seconds": files._recording_seconds(recording),
                "bytes": facts["bytes"],
                "eligible": ok,
                "reason": reason,
                "audio_normalized_at": recording.get("audio_normalized_at"),
            })
        return rows

    return {"kind": kind, "unique_id": unique_id, "redo": bool(redo),
            "recordings": await asyncio.to_thread(_collect)}


class BulkQueueRequest(BaseModel):
    kind: str
    # None: 全配信者。画面側は確認dialogを経由するが、APIとしても対象の広さは明示させる。
    unique_id: Optional[str] = None
    redo: bool = False
    # 画面で選んだ録画だけを投入する場合のid list。Noneなら絞り込まない(従来どおり)。
    recording_ids: Optional[list] = None


@router.post("/api/bulk/delete-mp4")
async def bulk_delete_mp4(payload: BulkQueueRequest) -> dict:
    """録画本体のmp4を、.tsが残っているものだけまとめて消す。

    再mp4化は元mp4を退避してから作り直すため、実行中は一時的に2本分の容量が要る。空きが
    無いdiskでは先に元を消しておきたい — .tsが残っていれば同じ内容を作り直せるので、その
    録画に限って安全にできる。**.tsが残っていない録画は対象にしない**(mp4が唯一の
    再取得不能資産で、消せば復元手段が無い)。判定は_bulk_classifyそのもので、画面側は
    持たない。

    queueには載せない。fileを1本消すだけでffmpegを起こさないので、実行時間0のjob行が
    録画数ぶん台帳へ並ぶだけになる。"""
    if payload.kind != "delete_mp4":
        raise HTTPException(status_code=400, detail=f"この経路で扱えない種別です: {payload.kind}")
    ids = [int(value) for value in payload.recording_ids] if payload.recording_ids else None
    plan = await asyncio.to_thread(_bulk_plan, "delete_mp4", payload.unique_id, False, ids)
    targets = plan["targets"]
    skipped = dict(plan["skipped"])
    if not targets:
        raise HTTPException(
            status_code=409,
            detail="削除できる録画がありません（内訳: "
                   + (", ".join(f"{BULK_SKIP_LABELS.get(k, k)} {v}本"
                                for k, v in skipped.items()) or "0本")
                   + "）。",
        )
    # 実行の直前にもう一度、実行中/待機中のjobが掴んでいる録画を外す。planを組んでから
    # ここまでの間に投入された焼き込みは、元mp4を読みながら走っている。
    busy = await asyncio.to_thread(runtime.storage.busy_recording_ids)
    deleted = 0
    freed = 0
    for recording in targets:
        if recording["id"] in busy:
            skipped["busy"] = skipped.get("busy", 0) + 1
            continue
        size, reason = await asyncio.to_thread(files._delete_source_mp4, recording)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        deleted += 1
        freed += size
    fsfacts._fs_state_cache.clear()
    fsfacts._fs_bulk_cache.clear()
    fsfacts._bulk_status_cache.clear()
    fsfacts._hls_dir_cache.clear()
    scope = f"@{payload.unique_id}" if payload.unique_id else "全配信者"
    await asyncio.to_thread(
        runtime.storage.record_ops_event, runtime.logger, "recording.sources_deleted",
        f"deleted {deleted} source mp4(s) ({freed / 1024 ** 3:.1f}GB) for {scope}",
        severity=OPS_WARNING if deleted else OPS_INFO,
        unique_id=payload.unique_id,
        detail={"deleted": deleted, "freed_bytes": freed, "skipped": skipped,
                "selected": len(ids) if ids is not None else None},
    )
    return {"kind": "delete_mp4", "unique_id": payload.unique_id, "deleted": deleted,
            "freed_bytes": freed, "skipped": skipped, "total": len(targets)}


def _bulk_skipped_detail(skipped: dict) -> str:
    """409本文に出す対象外の内訳。「対象0本」だけでは原因を探して回ることになる。"""
    return ", ".join(f"{BULK_SKIP_LABELS.get(k, k)} {v}本"
                     for k, v in skipped.items()) or "0本"


async def _bulk_queue_transcribe(payload: BulkQueueRequest) -> dict:
    """一括処理の文字起こし。対象の選び方は他の種別と同じ_bulk_planで、台帳も同じ
    media_job_queue(kind=stt)だが、投入の口だけ _enqueue_stt_jobs を通る。

    disk下限は見ない。文字起こしが書くのはDBのtranscript行だけで、映像jobのような中間fileも
    出力fileも作らないため、空きが細っている状況こそ先に回しておきたい処理である。
    """
    if not stt_available():
        raise HTTPException(
            status_code=503,
            detail="STTが利用できません。faster-whisperのinstallとTICTOK_STT_ENABLEDを確認してください。")
    ids = [int(value) for value in payload.recording_ids] if payload.recording_ids else None
    plan = await asyncio.to_thread(_bulk_plan, "transcribe", payload.unique_id,
                                   payload.redo, ids)
    targets = plan["targets"]
    if not targets:
        raise HTTPException(
            status_code=409,
            detail="文字起こしの対象になる録画がありません（内訳: "
                   + _bulk_skipped_detail(plan["skipped"]) + "）。",
        )
    # planの行をそのまま渡す。idから引き直していた頃は、対象1本につき1回の同期queryが
    # event loop上で走っていた(_bulk_planは既に同じ行を持っている)。
    added = await media_jobs._enqueue_stt_jobs(targets)
    # 投入で対象が消えるので、次のstatusは作り直す。
    fsfacts._bulk_status_cache.clear()
    scope = f"@{payload.unique_id}" if payload.unique_id else "全配信者"
    runtime.logger.info("一括投入: 音声の文字起こし %d件（%s）", added["added"], scope,
                extra={"event": "bulk.enqueued",
                       "ctx": {"kind": "transcribe", "unique_id": payload.unique_id,
                               "total": added["added"], "candidates": len(targets),
                               "selected": len(ids) if ids is not None else None,
                               "redo": payload.redo, "skipped": plan["skipped"]}})
    # totalは実際にqueueへ入った本数。planの本数をそのまま返すと、既にpending/runningで
    # 弾かれたぶんまで「入れました」と名乗ることになる。
    return {"kind": "transcribe", "unique_id": payload.unique_id, "total": added["added"],
            "skipped": plan["skipped"], "recording_ids": [t["id"] for t in targets]}


async def _bulk_queue_laugh(payload: BulkQueueRequest) -> dict:
    """一括処理の笑い声分析。対象の選び方は他の種別と同じ ``_bulk_plan``。

    disk下限は見ない。書くのは録画ごとの確率列sidecar(3時間で約100KB)と検索indexの行だけ
    で、映像jobのような中間fileも出力fileも作らない。

    engineが無効・model未配置ならここで断る。全件をqueueへ積んでから1本ずつ同じ理由で
    失敗させると、台帳が同じerrorで埋まるだけになる。
    """
    status = laugh_audio.laugh_status()
    if not status["configured"]:
        raise HTTPException(
            status_code=503,
            detail="笑い声検出が利用できません。TICTOK_LAUGH_AUDIO_ENABLED と "
                   "model/label fileの設定を確認してください（doc/LAUGH_AUDIO_MODEL.md）。")
    ids = [int(value) for value in payload.recording_ids] if payload.recording_ids else None
    plan = await asyncio.to_thread(_bulk_plan, "laugh", payload.unique_id,
                                   payload.redo, ids)
    targets = plan["targets"]
    if not targets:
        raise HTTPException(
            status_code=409,
            detail="笑い声分析の対象になる録画がありません（内訳: "
                   + _bulk_skipped_detail(plan["skipped"]) + "）。",
        )
    added = await media_jobs._enqueue_laugh_jobs(targets)
    fsfacts._bulk_status_cache.clear()
    scope = f"@{payload.unique_id}" if payload.unique_id else "全配信者"
    runtime.logger.info("一括投入: 笑い声分析 %d件（%s）", added["added"], scope,
                extra={"event": "bulk.enqueued",
                       "ctx": {"kind": "laugh", "unique_id": payload.unique_id,
                               "total": added["added"], "candidates": len(targets),
                               "selected": len(ids) if ids is not None else None,
                               "redo": payload.redo, "skipped": plan["skipped"]}})
    return {"kind": "laugh", "unique_id": payload.unique_id, "total": added["added"],
            "skipped": plan["skipped"], "recording_ids": [t["id"] for t in targets]}


@router.post("/api/bulk/queue")
async def bulk_queue(payload: BulkQueueRequest) -> dict:
    """配信者(未指定なら全配信者)の録画を1本ずつqueueへ載せる。

    session一括と同じく行は録画ごとに分ける(再起動しても残りが走る・1本だけ取り消せる)。
    同じ group_id を振るので、jobの取消APIにこのidを渡せば一括ぶんをまとめて取り消せる。

    文字起こしだけは投入の口が別(group_idを振らない_enqueue_stt_jobs)なので、対象の選び方
    (=_bulk_plan)を共有したまま投入先を分ける。画面から見た導線を種別ごとに割るより、ここで
    振り分けるほうが「見せた本数と積んだ本数が同じ」を保ちやすい。
    """
    kind = payload.kind
    _require_bulk_kind(kind)
    if kind == "transcribe":
        return await _bulk_queue_transcribe(payload)
    if kind == "laugh":
        return await _bulk_queue_laugh(payload)
    if kind not in BULK_QUEUE_KINDS:
        raise HTTPException(status_code=400,
                            detail=f"queueへ載せない種別です: {kind}（専用APIで実行します）")
    # 実行はworkerだが、下限割れなら投入前に断る(全件がworkerで失敗するより早い)。
    # 出力fileを作らない種別は通す — 無音skipの解析が残すのは録画1本あたり数百kBのsidecarで、
    # ここで断ると「空きが無いから声の解析もできない」という無関係な行き止まりになる。
    if kind not in BULK_NO_OUTPUT_KINDS:
        disk._require_disk_space(disk._disk_volume_paths(), "bulk_queue", kind=kind,
                            unique_id=payload.unique_id)
    ids = [int(value) for value in payload.recording_ids] if payload.recording_ids else None
    plan = await asyncio.to_thread(_bulk_plan, kind, payload.unique_id, payload.redo, ids)
    targets = plan["targets"]
    if not targets:
        raise HTTPException(
            status_code=409,
            detail=f"{BULK_KIND_TITLES[kind]}の対象になる録画がありません（内訳: "
                   + _bulk_skipped_detail(plan["skipped"]) + "）。",
        )
    # 字幕焼き込みが有効な場合、1本でも文字起こしが欠けていれば全体を止める。半分だけ字幕付きの
    # 出力が並ぶ状態は、どれが字幕付きか後から判別できず運用を壊す(session一括と同じ判断)。
    if kind in ("overlay", "upscale") and subtitles_enabled(runtime.settings):
        def _missing() -> list:
            return [t for t in targets if runtime.storage.get_transcript(t["id"]) is None]

        missing = await asyncio.to_thread(_missing)
        if missing:
            raise HTTPException(
                status_code=409,
                detail=(f"字幕の焼き込みが有効ですが、文字起こしが無い録画が{len(missing)}件あります"
                        "（録画 " + "、".join(files._recording_label(t) for t in missing[:5])
                        + ("…" if len(missing) > 5 else "")
                        + "）。先に一括文字起こしを実行してください。"),
            )
        # 1本ごとに文字起こしの読み出しとtiming.jsonのparseを行う検証。直上の_missingと同じく
        # threadで回す(loop上では対象数ぶんのDB読みとJSON parseがserverを止める)。
        def _verify() -> None:
            for target in targets:
                media_jobs._subtitle_transcript(target["id"])

        await asyncio.to_thread(_verify)
    group_id = secrets.token_hex(4)
    scope = f"@{payload.unique_id}" if payload.unique_id else "全配信者"
    # 選んで投入したときは、その旨をjob titleに残す。同じ配信者へ「まるごと」と「選択」を
    # 別々に積んだとき、Job画面でどちらのgroupか区別が付かなくなる。
    title = (f"{media_jobs.MEDIA_JOB_TITLES[kind]} 一括 {scope}"
             + (f" 選択{len(targets)}本" if ids is not None else ""))
    # まとめて積む。1本ずつenqueueすると、投入のたびに待機列全件とgroup全件を引き直すため
    # N本の投入がN²のqueryになり、その間event loopが空かない。
    await media_jobs.media_job_queue.enqueue_many([
        {
            "job_id": secrets.token_hex(4), "kind": kind, "recording_id": target["id"],
            "session_id": target.get("session_id"), "group_id": group_id, "title": title,
            # このgroupがsession一括ではないことの目印。queue側はこれを見てgroupの
            # domainを bulk_* にし、履歴画面のsession行へ誤って貼らないようにする。
            "params": {"bulk": True},
        }
        for target in targets
    ])
    # 投入で対象が消えるので、次のstatusは作り直す。
    fsfacts._bulk_status_cache.clear()
    runtime.logger.info("一括投入: %s %d件（%s）", kind, len(targets), scope,
                extra={"event": "bulk.enqueued",
                       "ctx": {"kind": kind, "unique_id": payload.unique_id,
                               "total": len(targets), "group_id": group_id,
                               "selected": len(ids) if ids is not None else None,
                               "redo": payload.redo, "skipped": plan["skipped"]}})
    return {"group_id": group_id, "kind": kind, "total": len(targets),
            "skipped": plan["skipped"],
            "recording_ids": [t["id"] for t in targets]}
