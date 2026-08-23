"""起動時にだけ走る処理と、lifespan。

中断jobの後始末 -> 孤児中間物の掃除 -> queue起動 -> 各background task、という順序は
lifespanのcommentが理由を持っている。派生物のsweepが「finalizeでやると落ちたときに誰も
再開しない」の答えとして置かれていることも同様(``_run_sweep`` / ``_sweep_loop_bg`` 参照)。

依存は runtime / files / fsfacts / disk / media_jobs。
"""

import asyncio
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from tictok.core.config import (get_media_job_auto_requeue_limit, get_media_job_history_days,
    get_media_queue_sweep_concurrency, get_no_restore)
from tictok.core import perf
from tictok.core import layout
from tictok.core import orphan_capture
from tictok.record.recorder import (ffmpeg_available, ffprobe_available,
    reclaim_pending_normalizations, recover_interrupted_recordings)
# 文字起こしは必ず別processで走らせる。serverでCTranslate2を読むと、torch(焼き込み・Up出力)
# と別versionのcuDNNが同じDLL名で同居し、processごと即死する(tictok.record.stt_worker参照)。
from tictok.record import stt_worker
from tictok.record import bgm_remove
# 笑い声検出をGPUで走らせるときも同じ理由で別processになる(cpu実行なら子は起きない)。
from tictok.media import laugh_worker
from tictok.collect.gifter_league import GifterLeagueWorker
from tictok.record.transcribe_queue import backfill_search_index
from tictok.record import hls_pack
from tictok.record.video_overlay import _duration_seconds, sweep_orphaned_transients
from tictok.api import disk
from tictok.api import files
from tictok.api import fsfacts
from tictok.api import media_jobs
from tictok.api import runtime


async def _restore_reprocess_backup(job: dict) -> Optional[str]:
    """中断した再mp4化・音量正規化の後始末。

    どちらも元mp4を _backup/ へ退避してから差し替えるので、その最中にprocessが死ぬと
    録画にmp4が無い状態のまま誰も復元しない。退避先はmove直後にjob行へ書いてあるため、ここで
    元へ戻せる。戻したpathを返す(戻す必要が無ければNone)。

    判定材料は「最終mp4が在るか」ではなく「**在るmp4が完成品か**」である。中断はほぼ必ず
    書きかけのmp4を残すので、存在だけで打ち切ると復元は永久に走らない。実測(2026-07-24
    02:03のserver再起動)では、62分と48分の録画が12分・11分の断片に置き換わったまま
    completedとして残り、原本は_backupに置き去りだった。
    """
    result = job.get("result") or {}
    backup = result.get("backup_path")
    final = result.get("final_path")
    if not backup or not final:
        return None
    backup_path, final_path = Path(backup), Path(final)
    if not backup_path.is_file():
        return None
    if final_path.is_file() and await _is_complete_mp4(final_path):
        # finalizeが完走していた。この退避fileは正常な世代管理なので残す。
        return None
    final_path.unlink(missing_ok=True)
    await asyncio.to_thread(shutil.move, str(backup_path), str(final_path))
    return str(final_path)


async def _is_complete_mp4(path: Path) -> bool:
    """再生できるmp4として完成しているか(復号可能なvideo streamと尺を持つか)。

    中断で残る断片はmoov atomを持たないため、ffprobeはそもそも中身を読めない。尺だけを
    見ると0byteのfileも「読めない」で同じ扱いになるが、どちらも完成品ではないので判定は
    1つでよい。"""
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    return bool(await _duration_seconds(path))


async def _recover_media_jobs() -> None:
    """起動時: 前回processで実行中だった映像jobを中断扱いにし、必要な後始末を行う。"""
    interrupted = runtime.storage.interrupt_running_media_jobs()
    for job in interrupted:
        restored = None
        if job["kind"] in ("reprocess", "audionorm"):
            try:
                restored = await _restore_reprocess_backup(job)
            except OSError:
                # 復元できなければ録画は退避先(_backup/)にしか無い。pathをlogへ必ず残す。
                runtime.logger.exception(
                    "中断した %s jobの退避fileを復元できません: job %s",
                    job["kind"], job["job_id"],
                    extra={"event": "media_queue.backup_restore_failed",
                           "ctx": {"job_id": job["job_id"],
                                   "recording_id": job.get("recording_id"),
                                   "result": job.get("result")}},
                )
        # 中断は「やらないことにした」ではなく「途中で止まった」。原状へ戻した以上、投入
        # された意図はまだ生きているので待機列へ戻す。ここを人手に委ねていたため、夜中に
        # 落ちた一括投入の残りが翌朝まで欠けたままになっていた。
        requeued = False
        limit = get_media_job_auto_requeue_limit()
        done = int((job.get("params") or {}).get("auto_requeues") or 0)
        if limit > 0 and done < limit:
            requeued = bool(runtime.storage.requeue_media_jobs([job["job_id"]], auto=True))
        runtime.storage.record_ops_event(
            runtime.logger, "media_queue.job_interrupted",
            f"{job['kind']}のjobがserverの再起動で中断しました"
            + ("。再度queueへ入れました" if requeued else ""),
            recording_id=job.get("recording_id"), session_id=job.get("session_id"),
            job_id=job["job_id"],
            detail={"kind": job["kind"], "pct": job.get("pct"),
                    "restored_path": restored, "requeued": requeued,
                    "auto_requeues": done + (1 if requeued else 0)},
        )
    pruned = runtime.storage.prune_media_jobs(get_media_job_history_days() * 86400.0)
    if interrupted or pruned:
        runtime.logger.info(
            "映像jobのqueue: %d件を中断扱いにし、古い %d件を削除しました",
            len(interrupted), pruned,
            extra={"event": "media_queue.recovered",
                   "ctx": {"interrupted": len(interrupted), "pruned": pruned}},
        )


async def _recover_interrupted_recordings_bg():
    # クラッシュで中断した録画のHLS segmentをmp4へ復元する(mark_stale_recordingsで
    # interrupted化された行を、捕捉済み映像が残っていれば再finalizeしてcompletedに戻す)。
    # 大容量録画のffmpeg remuxはstartup lifespanを塞ぐため、listen開始後にbackgroundで実行する。
    try:
        await recover_interrupted_recordings(runtime.storage, runtime.RECORD_DIR, final_dir=runtime.FINAL_DIR)
    except asyncio.CancelledError:
        raise
    except Exception:
        # The recording exists as HLS segments on disk but has no playable mp4, and
        # nothing retries after this point in the process's life.
        runtime.logger.exception(
            "中断した録画の復元に失敗しました",
            extra={"event": "recording.recovery_failed",
                   "ctx": {"path": str(runtime.RECORD_DIR)}},
        )


async def _reclaim_normalizations_bg():
    """差し替えが失敗して取り残された混在解像度normalizeの成果物を拾い直す。

    再encodeは終わっているのにos.replaceだけがlockで落ちると、混在解像度の元mp4が使われ
    続ける(=再生がカクつく)。lockは大抵再起動で解けるので、起動のたびにここで当て直す。
    録画復元と同じくlisten開始後のbackgroundで走らせる(ffprobeが録画数だけ走るため)。"""
    try:
        await reclaim_pending_normalizations(runtime.storage, runtime._RECORD_ROOTS)
    except asyncio.CancelledError:
        raise
    except Exception:
        runtime.logger.exception(
            "未完了の解像度normalizeの拾い直しに失敗しました（混在解像度の録画が"
            "残っている可能性があります）",
            extra={"event": "recording.normalize_reclaim_failed", "ctx": {}},
        )


# sweepが積む映像job。「素材を書き換えない」「消えても作り直せる」「無いと人がその場で
# 待たされる」を満たす種別だけを置く。焼き込み・Up出力・再mp4化・音量正規化を入れないのは、
# 不可逆な成果物を作るか元mp4を差し替える処理で、人が投げた覚えの無いまま自動で走って
# よい理由が無いため(文字起こしは同じ台帳だが本数で区切らないので_sweep_transcriptionsが持つ)。
SWEEP_LIMIT_SETTINGS = {
    "pack": "pack_sweep_per_start",
    "waveform": "waveform_sweep_per_start",
    "sprite": "sprite_sweep_per_start",
    "voice": "voice_sweep_per_start",
}

# 自動では積み直さないstate。理由はstorage.media_job_recording_ids_in_statesを参照。
SWEEP_BLOCKING_STATES = ("failed", "skipped", "cancelled")

# 候補を探す走査範囲。全録画を毎回見に行かないための上限で、limit件が埋まればここまで
# 読まずに切り上げる。
SWEEP_SCAN_LIMIT = 5000

# 定期sweepを止めている(間隔0)あいだ、設定を読み直す間隔。設定は画面から変えられるので、
# taskは畳まず待つだけにする(畳むと、有効へ戻しても次の起動まで繰り返しが復活しない)。
SWEEP_IDLE_POLL_SECONDS = 60.0


def _pack_sweep_ready(row: dict, quiet: float) -> bool:
    """ts結合の候補か。**束ね済み**と**素材の無い録画**、そして**直近に書き込みのあったdir**を
    外す。最後のものは、捕捉中のffmpegがindex.m3u8を書き続けるため、その最中に束ねると
    playlistを差し替えた直後に上書きされ、消したsegmentを指すplaylistが残るから(実際に1本
    やってしまった)。素材そのものを書き換える種別なので、判定はDBの状態ではなくfileの
    更新時刻で行う。"""
    dirs = files._recording_media_dirs(row)
    if not dirs or hls_pack.is_packed(dirs[0]):
        return False
    newest = 0.0
    for f in layout.media_files(dirs[0]):
        try:
            newest = max(newest, f.stat().st_mtime)
        except OSError:
            continue
    return newest <= quiet


def _recording_finished_at(row: dict) -> float:
    """録画が終わった時刻。確定していない行にはended_atが無いので開始時刻で代える。"""
    return float(row.get("ended_at") or row.get("started_at") or 0.0)


def _sidecar_sweep_ready(row: dict, fact: str, quiet: float, memo: dict) -> bool:
    """音声波形 / サムネ / 無音skipの解析の候補か。cacheが既に在るもの、素材もmp4も無いもの、
    終わったばかりの録画を外す。

    「終わったばかり」をpackのようなfileの更新時刻ではなく録画の終了時刻で見るのは、これらが
    素材を**読むだけ**の処理だから。早すぎた場合に出来るのは指紋の合わないcacheであって、
    壊れた素材ではない(作り直しは再生画面が要求した時点で生成側が判断する)。"""
    if _recording_finished_at(row) > quiet:
        return False
    if fsfacts._sidecar_done_in(row, fact, memo):
        return False
    return files._recording_source_exists(row)


def _awaiting_pack(row: dict, blocked_pack) -> bool:
    """この録画は、これからts結合で素材(.ts)を束ね直されるか。

    束ね直しは.tsの本数・合計byte・最新mtimeを変える。それは音声波形・サムネ・声profileの
    cache指紋そのもの(``waveform._source_key`` / ``hls_source.fingerprint``)なので、束ねる前に
    作ったsidecarはpackが終わった瞬間にまとめて無効になる。sweepの走査でpackを先に積んでも、
    同じ録画のsidecar jobが待機列に居るだけで ``_pack_recording`` は自分を保留にする
    (``pending_media_job_keys`` は待機中の行も返す)ため、実際の完了順は逆になる — 実測では
    保留の記録237件が**全てpack**(1回60秒 × 99 job = 待ち合計4.0時間)、台帳に残っている
    保留中の行76件も全てpack、packとsidecarの両方を完了した録画97本のうち**79本(81%)で
    packが後**に終わっており、その79本のsidecarは人が再生を押した時点で作り直しになっていた。

    順序は「積む順」ではなく「**同時に積まない**」で保つ。束ね待ちの録画にはsidecarを積まず、
    束ねた後の周期で積む。ts結合が二度と走らない録画(素材が無い / 前回failed・skipped・
    cancelled)は待っても束ねられないので、待たせずそのまま積む。"""
    if row["id"] in blocked_pack:
        return False
    dirs = files._recording_media_dirs(row)
    return bool(dirs) and not hls_pack.is_packed(dirs[0])


class _Candidates(dict):
    """``{種別: [録画, ...]}`` に「ts結合待ちで見送った件数」を添えたもの。

    dictのままなのは、呼び出し側も試験も種別で引くだけだから。``held`` をtupleの第2要素に
    しなかったのは、この形が既に ``[kind]`` として読まれているため(``fsfacts._BoundedCache``
    と同じ流儀 — 同じ形のまま性質を1つだけ足す)。"""

    held = 0


def _sweep_candidates(limits: dict, since: float = 0.0) -> _Candidates:
    """種別ごとの投入対象を、録画一覧の**1回の走査**でまとめて選ぶ。

    種別ごとに独立して走査すると、同じ録画のstat・dir一覧を種別の数だけ繰り返すことになる。
    どの種別もlimit件で満ちたところで打ち切る。

    古い順に見るのは、新しい録画ほど再生・焼き込みで触られる可能性が高いためで、触られにくい
    ものから片付ける。

    ``since`` を渡すと、それ以降に終わった録画だけを見る(定期sweepの2回目以降)。全件の走査は
    録画ごとにfileの確認を伴い、作り終えた後はlimitが埋まらないので毎回最後まで走ることに
    なる。絞るのは**費用が掛かる判定の手前**であって、上限や除外の規則は変わらない。

    ts結合待ちの録画にはsidecar(音声波形・サムネ・声profile)を積まない。理由と実測は
    ``_awaiting_pack``。見送った件数は ``held`` に残す — 見送った録画は次の周期で拾う必要が
    あるが、そのended_atは大抵 ``since`` の窓より古く、絞り込みのままでは二度と見に来ない。"""
    quiet = time.time() - int(runtime.settings.get("pack_sweep_quiet_minutes")) * 60
    blocked = runtime.storage.media_job_recording_ids_in_states(
        tuple(limits), SWEEP_BLOCKING_STATES)
    # packをsweepしない設定(上限0)なら束ね直しは自動では起きないので、待たせる相手が居ない。
    gate_on_pack = "pack" in limits
    memo: dict = {}
    out = _Candidates((kind, []) for kind in limits)
    # list_recordingsは新しい順。古い方から片付けるので並べ直す。
    rows = runtime.storage.list_recordings(limit=SWEEP_SCAN_LIMIT)
    rows.reverse()
    for row in rows:
        if all(len(out[kind]) >= limit for kind, limit in limits.items()):
            break
        if (row.get("status") or "") == "recording":
            continue
        if since and _recording_finished_at(row) < since:
            continue
        awaiting_pack = None  # 遅延評価。sidecarが要る録画でしか払わない。
        for kind, limit in limits.items():
            if len(out[kind]) >= limit or row["id"] in blocked.get(kind, ()):
                continue
            if kind == "pack":
                ready = _pack_sweep_ready(row, quiet)
            else:
                ready = _sidecar_sweep_ready(
                    row, fsfacts.SIDECAR_JOB_FACTS[kind], quiet, memo)
                if ready and gate_on_pack:
                    if awaiting_pack is None:
                        awaiting_pack = _awaiting_pack(row, blocked.get("pack", ()))
                    if awaiting_pack:
                        out.held += 1
                        continue
            if ready:
                out[kind].append(row)
    return out


async def _sweep_transcriptions(since: float = 0.0) -> dict:
    """文字起こしのない録画をまとめてqueueへ積む。積んだ件数と候補数を返す。

    本数で区切らないのは、GPUを1本ずつ直列に使い、再起動をまたいで残るため。全部積んでも
    同時に走るのは常に1本で、終わらなかったぶんは次のsweepでそのまま続く。文字起こし済みと
    待機/実行中は ``untranscribed_recordings`` と投入時の二重投入judgeで外れるので、積み直し
    にはならない。

    ``since`` は ``_sweep_candidates`` と同じ意味の絞り込み。投入側は録画ごとに素材のdir走査を
    行うので、既に見送った録画(素材が消えている等)を周期のたびに数え直さない。"""
    if not int(runtime.settings.get("transcribe_sweep_enabled")):
        return {"added": 0, "candidates": 0}
    rows = runtime.storage.untranscribed_recordings()
    if since:
        rows = [row for row in rows if _recording_finished_at(row) >= since]
    return await media_jobs._enqueue_stt_jobs(
        rows, priority=media_jobs.SWEEP_JOB_PRIORITY, sweep=True)


async def _run_sweep(after=None, since: float = 0.0) -> bool:
    """まだ作られていない派生物を少しずつqueueへ積む。上限まで積んだ種別があるか、ts結合待ちで
    sidecarを見送った録画があればTrueを返す。

    戻り値を使うのは呼び出し側(``_sweep_loop_bg``)だけで、「積み残しがある」の合図として
    次の周期を全件走査へ戻すために使う。

    ``after`` は中断録画の復旧task。**それが終わるまで積まない**: 復旧は録画をもう一度
    確定させる処理で、session dirの素材を最後まで読む。復旧の対象はDB上 interrupted
    であって「録画中」ではないため候補の除外を素通りし、束ねと確定が同じsegmentを
    奪い合う(実測2026-07-26 13:10、束ねが元segmentを消した直後に、それを読む側が
    FileNotFoundで落ちた)。sweepは急ぐ処理ではないので、ここは待てば済む。

    積む先は種別ごとに違うが、置き場所がここに揃っているのは同じ問いに答えるため —
    「finalizeでやると落ちたときに誰も再開しない」。sweepなら、失敗しても次の周期・次の起動で
    また積まれて自然に収束する。

    自分では処理せずqueueへ積む。既存のqueueが直列化・進捗・cancel・他の重いjobとの排他を
    すべて持っているので、二重に実装しない。sweepが積んだ行はpriorityを下げ(順番を人へ譲る)、
    同時実行本数も別枠で絞る(get_media_queue_sweep_concurrency)ので、人が投げたjobが
    sweepの後ろで待たされることはない。"""
    limits = {kind: int(runtime.settings.get(setting))
              for kind, setting in SWEEP_LIMIT_SETTINGS.items()}
    limits = {kind: limit for kind, limit in limits.items() if limit > 0}
    try:
        if after is not None:
            # 復旧側は自分で例外を吸うので、ここへ来るのは完了か取り消しだけ。
            await after
        # 文字起こしは映像jobと台帳もworkerも別なので、映像側の候補選びを待たせない。
        # to_threadへ逃がさない: enqueueはworkerを起こすasyncio.Eventを叩くので、別threadから
        # 呼ぶと起床が届かず、次のidle pollまで止まって見える(一括投入APIと同じ理由)。
        stt = await _sweep_transcriptions(since)
        if stt["added"]:
            runtime.logger.info(
                "音声の文字起こしに %d件の録画をqueueへ入れました（候補 %d件）",
                stt["added"], stt["candidates"],
                extra={"event": "stt.sweep_queued",
                       "ctx": {"queued": stt["added"], "candidates": stt["candidates"]}},
            )
        if not limits:
            return False
        candidates = await asyncio.to_thread(_sweep_candidates, limits, since)
        # 上限まで積んだ回に加え、ts結合待ちでsidecarを見送った回も次を全件走査へ戻す。
        # 見送った録画のended_atは大抵``since``の窓(既定45分)より古く、絞り込みのままだと
        # 束ね終わった後も二度と候補に上がらない。
        saturated = (any(len(rows) >= limits[kind] for kind, rows in candidates.items())
                     or candidates.held > 0)
        queued: dict = {}
        for kind, rows in candidates.items():
            for row in rows:
                try:
                    await media_jobs._enqueue_media_job(
                        kind, row["id"], recording=row, stem=files._recording_label(row),
                        priority=media_jobs.SWEEP_JOB_PRIORITY, sweep=True)
                except HTTPException:
                    continue  # 既にqueueに居る等。次のsweepで拾えばよい。
                queued[kind] = queued.get(kind, 0) + 1
        if not queued:
            return saturated
        runtime.logger.info(
            "sweepで %d件のjobをqueueへ入れました: %s",
            sum(queued.values()),
            ", ".join(f"{media_jobs.MEDIA_JOB_TITLES[k]} {n}" for k, n in queued.items()),
            extra={"event": "sweep.queued",
                   "ctx": {"queued": queued, "limits": limits, "since": since,
                           "candidates": {k: len(v) for k, v in candidates.items()},
                           "held_for_pack": candidates.held, "saturated": saturated,
                           "concurrency": get_media_queue_sweep_concurrency()}},
        )
        return saturated
    except asyncio.CancelledError:
        raise
    except Exception:
        runtime.logger.exception(
            "sweepがqueueへ入れられませんでした（未作成の派生物はそのまま残ります）",
            extra={"event": "sweep.failed", "ctx": {"since": since}},
        )
        # 途中で落ちた回は、どこまで見たのか分からない。次は全件から見直す。
        return True


async def _sweep_loop_bg(after=None):
    """起動後に1回、以降は設定した間隔で ``_run_sweep`` を回す。

    起動時にしか走らなかった頃は、serverを起動したまま録り続けると、新しい録画の音声波形も
    文字起こしも次の再起動まで作られなかった。commentの検索indexが同じ穴を持っていて、
    録画の確定時に張り直す修正が後から入っている(collector._index_recording_comments)。

    それでも確定callbackから直接積まずここで繰り返すのは3つの理由による。
      - ts結合(pack)が素材の.tsを束ね直すと、音声波形・サムネのcache指紋(.tsの本数・合計
        byte・最新mtime)が外れて作り直しになる。sweepは同じ走査で束ね待ちの録画を見分け、
        その録画のsidecarを**同じ回には積まない**ので「ts結合 -> 波形・サムネ」の順序が
        保たれる(``_awaiting_pack``)。
      - 静穏待ち(pack_sweep_quiet_minutes)や失敗録画の除外といった候補の規則が1箇所に残る。
      - 確定callbackは1回きりで、そこで落ちれば誰も再開しない。周期なら次で収束する。

    2回目以降は前回のsweep以降に終わった録画だけを見る(``since``)。全件走査は録画ごとに
    fileの確認を伴い、作り終えた後はlimitが埋まらないので毎回最後まで走ることになる。
    遡り幅に静穏待ちのぶんを足すのは、前回「終わったばかり」で見送った録画を落とさないため。
    上限まで積んだ回の次だけは、積み残しを拾うために全件へ戻す。"""
    since = 0.0
    first = True
    while True:
        minutes = int(runtime.settings.get("sweep_interval_minutes"))
        if first or minutes > 0:
            started = time.time()
            saturated = await _run_sweep(after if first else None, since=since)
            after, first = None, False
            quiet = int(runtime.settings.get("pack_sweep_quiet_minutes")) * 60
            since = 0.0 if saturated else started - quiet
        else:
            # 止めているあいだに終わった録画がある。再開するときは全件から見直す。
            since = 0.0
        await asyncio.sleep(minutes * 60 if minutes > 0 else SWEEP_IDLE_POLL_SECONDS)


async def _backfill_search_index_bg():
    """検索indexの未構築分(comment・既存transcript)を起動後に均す。GPUを使わずSTT queueとは独立。"""
    try:
        await backfill_search_index(runtime.storage, files._safe_recording_path)
    except asyncio.CancelledError:
        raise
    except Exception:
        runtime.logger.exception(
            "検索indexの補完に失敗しました",
            extra={"event": "search.backfill_failed", "ctx": {}},
        )


async def _capacity_sampler_bg():
    """容量snapshotを定期的に記録する。

    起動直後に1件採るのは、server再起動を繰り返す運用で1件も貯まらない事態を避けるため。
    間隔判定は「前回sampleからの経過」で行うので、再起動のたびに採ることにはならない。
    走査を伴わない軽い処理(実測48ms)なので、収集の邪魔にならない。
    """
    while True:
        try:
            interval_hours = float(runtime.settings.get("capacity_sample_interval_hours"))
            latest = await asyncio.to_thread(runtime.storage.latest_capacity_sample)
            due = (
                latest is None
                or (time.time() - latest["sampled_at"]) >= interval_hours * 3600
            )
            if due:
                payload = await asyncio.to_thread(disk._capacity_snapshot)
                await asyncio.to_thread(runtime.storage.add_capacity_sample, payload)
                report = await asyncio.to_thread(disk._capacity_report)
                await asyncio.to_thread(disk._capacity_alert_check, report)
                runtime.logger.info(
                    "容量のsampleを記録しました（volume %d件）",
                    len(payload["disk"]["volumes"]),
                    extra={"event": "capacity.sampled",
                           "ctx": {"volumes": list(payload["disk"]["volumes"]),
                                   "db_bytes": payload["db_files"]["db"],
                                   "backup_bytes": payload["backups"]["bytes"]}},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # 容量記録の失敗で収集を止める理由はないが、黙ると「予測が出ない」理由が
            # 追えなくなる。次の周期で再試行する。
            runtime.logger.exception(
                "容量のsample取得に失敗しました",
                extra={"event": "capacity.sample_failed", "ctx": {}},
            )
        await asyncio.sleep(runtime.CAPACITY_SAMPLER_TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 監視の復元より先に起こす。復元は数秒後に実配信へ接続してsessionを開始するので、後に
    # すると起動直後のLIVE開始通知だけが落ちる。
    runtime.notifier.start()
    # 監視の復元より先に起こす。復元した配信のeventが届き始めた時点でworkerが居ないと、
    # 署名URLが新鮮な最初の数秒ぶんのassetをqueueに積んだまま取り逃す。
    if runtime.asset_prefetch is not None:
        runtime.asset_prefetch.start()
    # 前回の実行が残した捕捉ffmpegを、**録画に触れる何よりも先に**止める。この後に来る
    # manager.restore()は実配信へ繋いで録画を始め、_recover_interrupted_recordings_bgは
    # 素材を見て中断録画を確定させる。孤児が書き続けたままそれをやると、確定した尺が直後
    # から嘘になり、同じdirを2つのffmpegが書く(実測: 録画行12.0秒に対しdirは16,861.8秒)。
    # resolverのbrowserは録画のfileに一切触らない(live URLの解決だけ)ので、孤児の掃除と
    # 同時に起こしてよい。順に待つと、冷えた起動では合計12.0秒になっていた(2026-08-21
    # 08:41: 掃除5.8s + browser 6.2s)。restore()の前に両方が終わっている点は変わらない。
    resolver_ready = asyncio.create_task(runtime.manager.startup())
    try:
        await asyncio.to_thread(orphan_capture.sweep, runtime._RECORD_ROOTS)
    finally:
        # 掃除が失敗しても、起こしかけたbrowserは必ず回収する(残すとprocessが浮く)。
        await resolver_ready
    no_restore = get_no_restore()
    if no_restore:
        # 監視の復元だけを止める。復元は起動数秒後に実配信へ接続して録画を開始するので、
        # 検証目的の起動が二重録画とdisk書き込みを伴わないようにするための唯一の入口。
        runtime.logger.warning(
            "監視の復元をskipしました（TICTOK_NO_RESTORE）",
            extra={"event": "process.monitor_restore_skipped",
                   "ctx": {"monitored": len(runtime.storage.list_monitored_targets())}},
        )
    else:
        await runtime.manager.restore()
    recovery_task = asyncio.create_task(_recover_interrupted_recordings_bg())
    # 中断jobの後始末はworkerを起こす前に済ませる。順序を逆にすると、退避したmp4を戻す前に
    # 同じ録画のjobが走り出す。
    await _recover_media_jobs()
    # 落ちたrenderが残した焼き込み中間物を掃く。_recover_media_jobsの後(実行中jobがすべて
    # interruptedへ倒れ、ここに在る中間物が定義上すべて孤児になった後)で、workerを起こす前。
    # 逆順にすると、走り出したjobが自分で書いている最中の中間物を消しかねない。
    await asyncio.to_thread(sweep_orphaned_transients, runtime._RECORD_ROOTS)
    media_jobs.media_job_queue.start()
    backfill_task = asyncio.create_task(_backfill_search_index_bg())
    reclaim_task = asyncio.create_task(_reclaim_normalizations_bg())
    capacity_task = asyncio.create_task(_capacity_sampler_bg())
    # ギフターのリーグ取得。待ち行列はDBに在るので、ここは流すだけ。収集本体とは別枠の
    # 外部アクセスなので、間隔は自前の設定(既定15秒/件)で持つ。
    gifter_league_worker = GifterLeagueWorker(runtime.storage, runtime.settings)
    gifter_league_task = asyncio.create_task(gifter_league_worker.run())
    # event loopの遅れを測る常駐probe。1本のcoroutineがloopを握ると全画面が同時に遅く
    # なるが、それはrequestごとの所要時間には「全員が少しずつ遅い」としか出ない。
    loop_lag_task = asyncio.create_task(perf.loop_lag_monitor())
    # まだ作られていない派生物(ts結合・音声波形・サムネ・文字起こし)をqueueへ積む。queueを
    # 起こした後に置くのは、積んだ瞬間から流れ始めてほしいため。1回目を積むのは中断録画の
    # 復旧が終わってから(``_run_sweep`` 参照)で、以降は設定間隔で繰り返す
    # (``_sweep_loop_bg`` 参照。起動したまま録り続けても新しい録画が置き去りにならない)。
    sweep_task = asyncio.create_task(_sweep_loop_bg(recovery_task))
    # ffmpeg/ffprobe are resolved from PATH at call time, so a missing binary surfaces
    # only when a recording fails to start. Stating it once at startup turns "no
    # recordings were produced last night" into a one-line answer.
    runtime.logger.info(
        "起動が完了しました: 監視 %d件を %.1fs で復元（ffmpeg=%s ffprobe=%s no_restore=%s）",
        len(runtime.manager.snapshots()), time.perf_counter() - runtime._startup_started,
        ffmpeg_available(), ffprobe_available(), no_restore,
        extra={"event": "process.startup_completed",
               "ctx": {"monitors": len(runtime.manager.snapshots()), "no_restore": no_restore,
                       "duration_ms": round((time.perf_counter() - runtime._startup_started) * 1000.0, 1),
                       "ffmpeg": ffmpeg_available(), "ffprobe": ffprobe_available()}},
    )
    yield
    runtime.logger.info(
        "終了処理を開始しました", extra={"event": "process.shutdown_started", "ctx": {}}
    )
    recovery_task.cancel()
    try:
        await recovery_task
    except asyncio.CancelledError:
        pass
    backfill_task.cancel()
    try:
        await backfill_task
    except asyncio.CancelledError:
        pass
    reclaim_task.cancel()
    try:
        await reclaim_task
    except asyncio.CancelledError:
        pass
    capacity_task.cancel()
    try:
        await capacity_task
    except asyncio.CancelledError:
        pass
    gifter_league_task.cancel()
    try:
        await gifter_league_task
    except asyncio.CancelledError:
        pass
    await gifter_league_worker.aclose()
    sweep_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass
    loop_lag_task.cancel()
    try:
        await loop_lag_task
    except asyncio.CancelledError:
        pass
    # 文字起こしはmedia_job_queueのkind=sttとして走る。子processだけは別に落とす必要が
    # ある(Windowsは親の終了で子を殺さない)。
    stt_worker.terminate_all()
    # 笑い声検出をGPUで走らせている場合も同じ形の子processが居る(cpu実行なら0件)。
    laugh_worker.terminate_all()
    # BGM除去も別venvのpythonを子として起こす(掛けていなければ0件)。
    bgm_remove.terminate_all()
    await media_jobs.media_job_queue.stop()
    await runtime.manager.stop_all()
    await runtime.manager.shutdown()
    # 監視を止めた後に止める。先に止めると停止処理そのものが出す状態遷移が通知されない。
    # storage.close()より前であることも必須で、送信失敗はops_eventsへ書く。
    await runtime.notifier.stop()
    # 先行取得のworkerは、それが叩くstore(httpx client)を閉じる前に止める。逆順にすると
    # 実行中のdownloadが閉じたclientへ落ちて、終了処理が例外で埋まる。
    if runtime.asset_prefetch is not None:
        await runtime.asset_prefetch.aclose()
    await runtime.avatar_proxy.aclose()
    await runtime.gift_icons.aclose()
    await runtime.avatar_pool.aclose()
    await runtime.emote_pool.aclose()
    runtime.storage.close()
    runtime.instance_lock.release()
