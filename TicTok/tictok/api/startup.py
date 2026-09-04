"""起動時にだけ走る処理と、lifespan。

中断jobの後始末 -> 孤児中間物の掃除 -> queue起動 -> 各background task、という順序は
lifespanのcommentが理由を持っている。派生物のsweepが「finalizeでやると落ちたときに誰も
再開しない」の答えとして置かれていることも同様(``_run_sweep`` / ``_sweep_loop_bg`` 参照)。

依存は runtime / files / fsfacts / disk / media_jobs / routes.search(意味検索indexの構築)。
"""

import asyncio
import json
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from tictok.core.config import (get_db_backup_on_recording_finished, get_db_path,
    get_media_job_auto_requeue_limit, get_media_job_history_days,
    get_media_queue_sweep_concurrency, get_no_restore,
    get_record_backup_min_interval_minutes, get_record_backup_quiet_minutes,
    record_backup_dir_from_db)
from tictok.core import perf
from tictok.core import layout
from tictok.core import orphan_capture
from tictok.core import sweep_signal
from tictok.core import dbmaint, settings_export, tables_export
from tictok.store._common import OPS_ERROR, OPS_INFO, OPS_WARNING
from tictok.record import primary_backup
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
# 意味検索indexの構築を起こすため。routes.searchはstartupをimportしないので循環しない。
from tictok.api.routes import search as routes_search


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
    **fsfacts.SIDECAR_SWEEP_SETTINGS,
}

# 自動では積み直さないstate。理由はstorage.media_job_recording_ids_in_statesを参照。
SWEEP_BLOCKING_STATES = ("failed", "skipped", "cancelled")

# 候補を探す走査範囲。全録画を毎回見に行かないための上限で、limit件が埋まればここまで
# 読まずに切り上げる。
SWEEP_SCAN_LIMIT = 5000

# 定期sweepを止めている(間隔0)あいだ、設定を読み直す間隔。設定は画面から変えられるので、
# taskは畳まず待つだけにする(畳むと、有効へ戻しても次の起動まで繰り返しが復活しない)。
SWEEP_IDLE_POLL_SECONDS = 60.0

# 確定した録画の合図(``core.sweep_signal``)を見に行く間隔。待つのは分単位で、費やすのは
# timer 1本ぶんである。asyncio.Eventで起こさないのは、module levelのEventが最初に使われた
# loopへ束縛され(3.10の_LoopBoundMixin)、loopを作り直すtestで使えなくなるため。
SWEEP_SIGNAL_POLL_SECONDS = 30.0

# 静穏待ちが明ける時刻に対して置く余裕。``_sidecar_sweep_ready`` の判定は「終了時刻が
# now - 静穏 以前」なので、境界ちょうどに起きると読みの誤差で1回空振りする。
SWEEP_SIGNAL_MARGIN_SECONDS = 5.0


def _pack_sweep_ready(row: dict, quiet: float) -> bool:
    """ts結合の候補か。**束ね済み**と**素材の無い録画**、そして**直近に書き込みのあったdir**を
    外す。最後のものは、捕捉中のffmpegがindex.m3u8を書き続けるため、その最中に束ねると
    playlistを差し替えた直後に上書きされ、消したsegmentを指すplaylistが残るから(実際に1本
    やってしまった)。素材そのものを書き換える種別なので、判定はDBの状態ではなくfileの
    更新時刻で行う。"""
    dirs = files._recording_media_dirs(row)
    if not dirs or hls_pack.is_packed(dirs[0]):
        return False
    # serverが自分で捕捉ffmpegの終了を見届けた録画は、そのdirへ書く者が居ないと分かって
    # いるので静穏待ちを飛ばす。静穏待ちは「まだ書いている者が居ないか」をfileの更新時刻から
    # 推定する代理にすぎず、確定直後に束ねてしまえば、userが開く5〜15分より前に
    # ts結合とsidecar(pack後に積む)が揃う。それまでは開いた時点でその場生成(1〜3分待ち)
    # になり、その成果物は15分後の結合で丸ごと作り直しになっていた(2026-09-03の監査)。
    # crash後の復旧・中断録画はこの合図を持たないので、従来どおり静穏待ちで判定する。
    if sweep_signal.is_clean(dirs[0]):
        return True
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


async def _sweep_semantic_index() -> None:
    """意味検索indexの未反映ぶんを、この周期で埋め込ませる。

    波形やサムネと違い、この派生物は**素材ではなく他の派生物の上に建つ**。材料は
    search_hits(文字起こしとcommentのindexが書く)なので、録画が確定した時点ではまだ
    文字起こしが無く、確定を合図に起こしても大半のgroupは取り残される。周期のsweepなら、
    文字起こしが終わった次の回で自然に拾える — 「finalizeでやると落ちたときに誰も
    再開しない」に対する答えは、ここでも同じである。

    起こすだけで自分では走らせない(``routes_search.start_build_if_pending``)。構築は
    数十万passageで数時間に及ぶことがあり、待つとその間ずっと次のsweep(波形・文字起こし)が
    止まる。

    失敗しても他の種別の投入は続ける。indexの都合(埋め込みserverが落ちている、sidecarの
    sqliteが読めない)で波形もサムネも積まれなくなるのは、原因と被害が釣り合わない。"""
    if not int(runtime.settings.get("semantic_sweep_enabled")):
        return
    try:
        pending = await routes_search.start_build_if_pending()
    except Exception:
        runtime.logger.exception(
            "意味検索indexの自動構築を起こせませんでした（未indexはそのまま残ります）",
            extra={"event": "search.semantic_sweep_failed", "ctx": {}},
        )
        return
    if pending:
        runtime.logger.info(
            "意味検索indexの構築を開始しました（未反映 %d group）", pending,
            extra={"event": "search.semantic_sweep_started",
                   "ctx": {"pending_groups": pending}},
        )


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
        # 意味検索indexは文字起こし・commentのindexの上に建つので、今積んだ文字起こしは
        # まだ材料になっていない。ここで埋めるのは前回までに揃ったぶんで、今積んだぶんは
        # 次の周期が拾う。
        await _sweep_semantic_index()
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


async def _wait_next_sweep(minutes: int) -> None:
    """次のsweepまで待つ。定期の間隔と、確定した録画が候補に入る時刻の**早い方**で起きる。

    合図が無ければ従来どおり間隔ぶん眠るだけである。合図があるときに縮めるのは、確定から
    候補になるまでが静穏待ち(既定15分)なのに対し、それを拾う周期が既定30分あって、待ち時間の
    大半が「候補なのに誰も見に来ていない時間」だったため。

    目標時刻は寝ている最中に**早くなる**(録画は待っている間にも終わる)ので、一度計算して
    そこまで眠るのではなく、数十秒ごとに引き直す。

    起きたら、静穏待ちの明けた合図だけを捨てる。1回のsweepで全部捨てると、まだ静穏中の
    録画が「早く起きる」対象から外れ、合図を置いた意味がそこで消える。"""
    period = minutes * 60 if minutes > 0 else SWEEP_IDLE_POLL_SECONDS
    deadline = time.time() + period
    while True:
        quiet = int(runtime.settings.get("pack_sweep_quiet_minutes")) * 60
        finished = sweep_signal.earliest()
        # 綺麗に終わった(serverがffmpegの終了を見届けた)録画は静穏待ちを飛ばして起こす。
        # 候補判定(_pack_sweep_ready)も同じ合図を見る。
        clean = sweep_signal.earliest_clean_unwoken()
        target = deadline
        if finished is not None:
            target = min(target, finished + quiet + SWEEP_SIGNAL_MARGIN_SECONDS)
        if clean is not None:
            target = min(target, clean + SWEEP_SIGNAL_MARGIN_SECONDS)
        remaining = target - time.time()
        if remaining <= 0:
            now = time.time()
            sweep_signal.consume(now - quiet)
            # 起こし済みの印を付けるだけで捨てない(この回でpackを積めなくても次の回で
            # 拾えるように)。捨てるのは静穏待ちが明けたぶん — その先は従来の規則で同じ答え。
            sweep_signal.mark_clean_woken(now - SWEEP_SIGNAL_MARGIN_SECONDS)
            sweep_signal.prune_clean(now - quiet)
            return
        await asyncio.sleep(min(remaining, SWEEP_SIGNAL_POLL_SECONDS))


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

    確定callbackが行うのは**この周期を早く起こすこと**だけで(``core.sweep_signal``)、
    積むかどうかは上の規則がそのまま決める。合図が届かなくても定期の周期が同じ結果へ収束
    する — 早い経路を足しても、遅い経路が唯一の正解のまま残る。

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
        await _wait_next_sweep(minutes)


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


# ---- 録画の確定を合図にした退避 ------------------------------------------------------
# DBのsnapshot・設定値の書き出し・一次保存のbackupは、録画が確定して落ち着いたことを合図に
# 走らせる。
#
# **「配信が終わった」を全体の状態として扱わない。** 配信者を複数監視していれば、ある録画が
# 終わった瞬間に他が走っているのが普通である。実測(2026-09-02、確定録画529本・76日)では
# 終了の29.5%がそれに当たり、同時録画は最大5本だった。最初に書いた「最後の終了から静穏時間
# だけ待つ」という全体gateを同じ実測へ当てると、走った回の**65.4%が他の録画の進行中**で、
# 書き込み中の.tsを写しに行っていた。
#
# しかもその形は**監視数が増えるほど成立しなくなる**。同じ実測を多重化して測ると、
# 「最後の終了から15分静か」が成立する時間は 4人で94.1% / 20人で74.2% / 80人で30.6% まで
# 落ち、成立しない区間は最長3.1時間に伸びる。全体の静けさに依存する条件は、監視数という
# 外から決まる量に振り回される。
#
# 代わりに、**周期は固定**(監視数に一切依らない)・**録画1本ずつを見て落ち着いた物だけを写す**
# 形にする。落ち着いていない録画は写す対象から外すだけで、待たない。
#
# I/Oの奪い合いは実測の結果、設計要因から外した。録画の書き込みは1本 0.10 MB/s(実測: 452本
# 259GB / 総尺)で、1人1日あたり0.85GB。80人へ増えても1日68GBで、逐次149.5MB/s(実測D:)なら
# **1日8分**の書き込みでしかない。周期を静けさに合わせる価値より、監視数に依らないことの方が
# 大きい。
#
# 合図を ``core.sweep_signal`` から取らないのは、あれが**再起動で消える**揮発の仕組みで、
# consumeを持つ利用者が2つになると片方が捨てた合図をもう片方が永久に見られなくなるためである
# (sweep_signalのdocstring)。DBに残る終了時刻なら、録画の直後にserverを落としても起動後の
# 最初の周期がそのまま拾う。
BACKUP_TICK_SECONDS = 60.0
# 失敗した退避を再試行する間隔の上限。間隔は失敗のたびに倍にして(60秒→2分→…)ここで
# 頭打ちにする。退避が失敗する理由はほぼ「退避先のdriveが外れた・満杯」で、60秒後に直って
# いることは無い。上限を置かないと、driveが外れている1日のあいだにDBのsnapshot(1.65GB・
# 実測 K:で約40秒)を860回、1.4TBぶん書いて消すことになる ―― K:のようなSMR driveは
# その繰り返しで20〜30MB/sまで落ち、同じdriveの移送とfile backupを道連れにする。
BACKUP_RETRY_MAX_SECONDS = 3600.0

# 「どの録画まで退避したか」の記録key。**退避ごとに別のkey**を持つ ―― 1つの印で3つを
# まとめると、1つが失敗した周期にDBのsnapshotまで取り直すことになる(印は3つとも済んで
# からしか進められない)。DBに置くのは、これが**予定の記録**であって守るべきdataではない
# からである(失っても、次の周期が同じ録画をもう一度退避するだけで済む)。行数の見張りの
# 台帳は逆にDBの外へ置く —— あちらはDBが壊れた瞬間に一緒に失われては困る。
BACKUP_STEP_DB = "db"
BACKUP_STEP_SETTINGS = "settings"
BACKUP_STEP_FILES = "files"
_BACKUP_MARK_KEYS = {
    BACKUP_STEP_DB: "backup_db_after_recording_at",
    BACKUP_STEP_SETTINGS: "backup_settings_after_recording_at",
    BACKUP_STEP_FILES: "backup_files_after_recording_at",
}
# 退避ごとの再試行の状態(``{"failures": 回数, "until": monotonic秒}``)。processの中だけで
# 持つ ―― 再起動は人が何かを直した合図で、そこから数え直してよい。
_backup_retry: dict = {}
# 一次保存のbackup先の識別子の控え(``db_maintenance``)。値は ``{"dir": 設定値, "id": 識別子}``
# のJSON。保存先の文字列と組で持つので、設定画面で保存先を変えれば控えは自動的に「無い」
# 扱いになり、新しい先の識別子を採用し直す(``primary_backup._verify_root_identity``)。
_RECORD_BACKUP_ROOT_KEY = "record_backup_root"
# 下限間隔で見送ったことを記録した合図。見送りは印を進めないので、間隔が明けるまで毎周期
# 同じ判断になる。1周期ごとに同じ行を出すと、1時間で60行の「見送り」が並ぶ。
_backup_skip_logged: dict = {}


def _backup_retry_delay(failures: int) -> float:
    """``failures`` 回目の失敗のあと、次に試すまでの秒数(指数backoff、上限あり)。"""
    return min(BACKUP_TICK_SECONDS * (2 ** max(0, failures - 1)), BACKUP_RETRY_MAX_SECONDS)


def _backup_retry_pending(step: str, now: float) -> bool:
    state = _backup_retry.get(step)
    return bool(state) and now < float(state["until"])


def _backup_step_failed(step: str, now: float) -> float:
    """失敗を数え、次に試す時刻を決めて返す(次回までの秒数)。"""
    failures = int((_backup_retry.get(step) or {}).get("failures", 0)) + 1
    delay = _backup_retry_delay(failures)
    _backup_retry[step] = {"failures": failures, "until": now + delay}
    return delay


def _reset_backup_state() -> None:
    """再試行と見送りの記録を捨てる(testが周期をまたいで状態を持ち越さないため)。"""
    _backup_retry.clear()
    _backup_skip_logged.clear()


def _backup_recording_split(rows: list, quiet_seconds: float, now: float) -> tuple:
    """録画を「落ち着いた(写してよい)」と「まだ動いている(写してはならない)」に分ける。

    動いている条件は4つで、どれか1つでも当たれば除外する:

    1. まだ終わっていない(``ended_at`` が無い / status が完了でない)
    2. 確定処理の最中(``recorder.is_finalizing``)
    3. 派生物のjobが控えている・実行中(ts結合・波形・サムネ・文字起こし)
    4. 終わってから静穏時間が経っていない

    3を見るのは、確定の直後に ts結合が.tsを束ね直し、波形とサムネが同じfileを読み書き
    するためである(``_sweep_candidates``)。その最中に写すと控えに途中の姿が残るうえ、
    同じdiskを奪い合って両方が遅くなる。判定の3条件は最終保存先への移送
    (``api.disk._run_relocation``)と同じ物を使う —— 素材を触る操作が2つあって片方だけ
    条件が緩いと、移送では触らない録画をbackupが触る。

    戻り値は ``(写す対象の行, 除外する行)``。除外は「まだ見ていない」であって「消えた」
    ではないので、呼ぶ側は削除の伝播からも外すこと。"""
    from tictok.record.recorder import is_finalizing

    busy_ids = {rid for _kind, rid in runtime.storage.pending_media_job_keys()}
    ready, held = [], []
    for row in rows:
        ended = row.get("ended_at")
        settled = (
            ended
            and row.get("status") in ("completed", "interrupted")
            and (now - float(ended)) >= quiet_seconds
            and not is_finalizing(row.get("id"))
            and row.get("id") not in busy_ids
        )
        (ready if settled else held).append(row)
    return ready, held


def _backup_exclusions(rows: list) -> set:
    """写してはならない録画の、一次保存先からの相対path接頭辞。

    1本の録画は3箇所に散るので、stemを含む接頭辞を3つ返す:

    - ``<配信者>/ts/<stem>``      … HLSの素材(録画中はここへ書き込まれ続ける)
    - ``<配信者>/mp4/<stem>``     … 完成mp4(ts結合が書く)
    - ``.sidecars/<stem>``        … 時刻map・波形・サムネ。**root直下**で配信者別ではない
      (``recorder.sidecar_dir`` = ``record_root_of(src) / .sidecars``)

    path componentの境目で照合する前提の値である ―― 単純な前方一致だと ``<stem>`` の
    除外が ``<stem>2`` まで巻き込む。mp4とsidecarに拡張子を付けないのは、1つのstemから
    ``.overlay.mp4`` ``.up.mp4`` ``.waveform.json`` のように複数の派生が出るためで、
    接頭辞のまま渡してそれら全部を覆う。"""
    from tictok.record.recorder import SIDECAR_DIRNAME

    rels = set()
    for row in rows:
        raw = row.get("filename") or Path(row.get("path") or "").name
        stem = Path(raw).stem if raw else ""
        streamer = layout.streamer_of(stem) if stem else None
        if not stem:
            continue
        rels.add(f"{SIDECAR_DIRNAME}/{stem}")
        if streamer:
            rels.add(f"{streamer}/{layout.TS_DIRNAME}/{stem}")
            rels.add(f"{streamer}/{layout.MP4_DIRNAME}/{stem}")
    return rels


async def _backup_db_snapshot(ended_at: float) -> None:
    """稼働したままDBのsnapshotを1世代取る(reason=scheduled)。

    ここで ``flush`` を先に呼ぶのは、退避がbatch writerのbufferに残った行を含んだ像で
    あるべきだからである。手動の退避(``routes.system``)と同じ順序にしておかないと、
    自動と手動で「どこまで入っているか」が違う退避が並ぶ。"""
    # 手動の保守(VACUUM・checkpoint)と同じlock。snapshotは読み transaction を数十秒握る
    # ので、その最中にVACUUMが走り出すと書き込みを止めた上で失敗する。
    async with runtime.maintenance_lock:
        async with runtime._tracked_job("maintenance", "DB退避（配信終了後）") as job_id:
            await asyncio.to_thread(runtime.storage.flush)
            result = await asyncio.to_thread(
                dbmaint.create_backup, get_db_path(), reason=dbmaint.REASON_SCHEDULED)
            # 完了は手動の退避と同じkindで残す。自動の世代が取れているかは、この行が
            # 一定の間隔で並んでいるかでしか後から読めない。
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "maintenance.backup_completed",
                "配信終了後のDB退避を書き出しました: {name}（{gb:.2f}GB）".format(
                    name=result["name"], gb=result["bytes"] / (1024 ** 3)),
                job_id=job_id,
                duration_ms=result["duration_ms"],
                detail={"path": result["path"], "bytes": result["bytes"],
                        "reason": result["reason"], "pruned": result["pruned"],
                        "ended_at": ended_at},
            )
            # 行数の見張り(凍結・急減の検知)の記録は create_backup が返す。運用logへ載せる
            # 口をdbmaint側の1関数に集めてあるので、画面・migration前・ここのどれから呼んでも
            # 同じ行が残る。
            await asyncio.to_thread(
                dbmaint.record_backup_ops_events, runtime.storage, runtime.logger,
                result, job_id=job_id)


async def _backup_settings_export() -> None:
    """設定値と手入力データを、一次保存先と全ての最終保存先へ人が読めるJSONで書き出す。

    移送と違い、書けない保存先が在っても書ける保存先には書く —— 元を消さない写しで、
    fileに時刻が入っているので、読む人は新しい方を採れる。

    運用logは ``settings_export`` / ``tables_export`` 自身が残す(書けた先・書けなかった先・
    severityの決め方をそちらが持っている)。ここで重ねて記録しない —— 同じeventが2行出ると、
    どちらが実際の結果なのか後から読めない。

    2つは同じ退避の印(``BACKUP_STEP_SETTINGS``)で進む。設定値が書けて表が書けなかった回は
    印が進まず次の周期で両方をやり直すが、設定値の方は中身が同じなら世代を作らないので
    重ねて書くことはない。"""
    roots = [runtime.RECORD_DIR, *runtime.FINAL_DIRS]
    await asyncio.to_thread(
        settings_export.export_settings, runtime.settings, roots, get_db_path())
    await asyncio.to_thread(
        tables_export.export_tables, runtime.storage, roots, get_db_path())


async def _backup_primary_files(exclude) -> None:
    """一次保存先をbackup先へ写す。進捗はjob台帳へ載せる(数分かかるため)。

    ``exclude`` はまだ動いている録画の相対path接頭辞(``_backup_exclusions``)。写す側は
    走査・copy・削除の伝播のすべてからこれを外す。"""
    async with runtime._tracked_job("record_backup", "一次保存のbackup") as job_id:
        loop = asyncio.get_running_loop()

        def _on_progress(done: int, total: int, current) -> None:
            pct = int(done * 100 / total) if total else 100
            label = f"{done:,}/{total:,}件" + (f"  {current}" if current else "")
            asyncio.run_coroutine_threadsafe(
                runtime.jobs.progress(job_id, pct, stage=label), loop)

        configured = record_backup_dir_from_db(get_db_path())
        expected = await asyncio.to_thread(_expected_record_backup_root_id, configured)
        result = await primary_backup.run_backup(
            _on_progress, exclude_rels=exclude, expected_root_id=expected)
        if result["root_id_adopted"]:
            await asyncio.to_thread(
                runtime.storage.set_maintenance_value, _RECORD_BACKUP_ROOT_KEY,
                json.dumps({"dir": configured, "id": result["root_id"]}))
        summary = {
            "copied": result["copied"], "copied_bytes": result["copied_bytes"],
            "skipped": result["skipped"], "failed": result["failed"],
            "deleted": result["deleted"], "excluded": result["excluded"],
            "seconds": round(result["seconds"], 1), "stopped": result["stopped"],
            "remaining": result["remaining"],
        }
        if result["stopped"]:
            # 途中で止めた回。失敗ではないが、次回が続きを写すまで控えは古いままなので、
            # 人が気付ける行として残す(通知の対象にもなる)。
            await asyncio.to_thread(
                runtime.storage.record_ops_event, runtime.logger,
                "record_backup.stopped",
                "一次保存のbackupを中断しました: {reason}（残り {remaining:,} 件）".format(
                    reason=result["stopped"], remaining=result["remaining"]),
                severity=OPS_WARNING, job_id=job_id,
                duration_ms=result["seconds"] * 1000.0, detail=summary,
            )
            return
        await asyncio.to_thread(
            runtime.storage.record_ops_event, runtime.logger,
            "record_backup.job_completed",
            "一次保存のbackupが完了しました: 写した {copied:,} 件（{gb:.2f}GB）/ "
            "失敗 {failed:,} 件".format(
                copied=result["copied"], gb=result["copied_bytes"] / (1024 ** 3),
                failed=result["failed"]),
            severity=OPS_WARNING if result["failed"] else OPS_INFO, job_id=job_id,
            duration_ms=result["seconds"] * 1000.0, detail=summary,
        )


def _expected_record_backup_root_id(configured: str):
    """DBに控えた backup先の識別子。控えが無い・別の保存先の物なら None(=採用し直す)。"""
    raw = runtime.storage.get_maintenance_value(_RECORD_BACKUP_ROOT_KEY)
    if not raw:
        return None
    try:
        stored = json.loads(raw)
    except ValueError:
        runtime.logger.warning(
            "一次保存のbackup先の識別子の控えを読めないため、backup先の識別子を採用し直します",
            extra={"event": "record_backup.root_record_unreadable", "ctx": {"raw": raw[:200]}},
        )
        return None
    if not isinstance(stored, dict) or stored.get("dir") != configured:
        return None
    return stored.get("id") or None


def _backup_enabled_steps() -> list:
    """この周期で走らせる退避。設定で止めた物・写す先が無い物は数えない ―― 数えると
    その印が永久に進まず、``since`` が動かなくなる。"""
    steps = []
    if get_db_backup_on_recording_finished():
        steps.append(BACKUP_STEP_DB)
    steps.append(BACKUP_STEP_SETTINGS)
    if primary_backup.is_configured():
        steps.append(BACKUP_STEP_FILES)
    return steps


async def _backup_run_step(step: str, ended_at: float, exclude) -> bool:
    """退避1つを走らせる。戻り値は「印を進めてよいか」。

    file backupの下限間隔での見送りだけが False を返す。見送りは失敗ではないが済んでも
    いない ―― 印を進めると、その録画は次の録画が終わるまで控えに入らない。進めなければ
    間隔が明けた最初の周期で写す。"""
    if step == BACKUP_STEP_DB:
        await _backup_db_snapshot(ended_at)
        return True
    if step == BACKUP_STEP_SETTINGS:
        await _backup_settings_export()
        return True
    last = await asyncio.to_thread(primary_backup.last_run)
    interval = get_record_backup_min_interval_minutes() * 60.0
    since_last = time.time() - float((last or {}).get("started_at") or 0.0)
    if last and since_last < interval:
        # 短い配信が続く日に、1本ごとに全体を舐め直さない。見送ったことは記録する ――
        # 黙ると「backupが走らない」理由を後から追えない。同じ録画については1度だけ。
        if _backup_skip_logged.get(step) != ended_at:
            _backup_skip_logged[step] = ended_at
            runtime.logger.info(
                "一次保存のbackupを見送りました（前回から %.0f 分・下限 %.0f 分）",
                since_last / 60.0, interval / 60.0,
                extra={"event": "backup.skipped",
                       "ctx": {"since_seconds": since_last, "min_interval_seconds": interval}},
            )
        return False
    await _backup_primary_files(exclude)
    return True


_BACKUP_FAILURE_EVENTS = {
    BACKUP_STEP_DB: ("maintenance.backup_failed", "配信終了後のDB退避に失敗しました"),
    BACKUP_STEP_SETTINGS: ("backup.settings_export_failed", "設定値・手入力データのバックアップに失敗しました"),
    BACKUP_STEP_FILES: ("record_backup.job_failed", "一次保存のbackupに失敗しました"),
}


async def _backup_tick() -> None:
    """1周期ぶん。落ち着いた録画が在れば、それだけを対象に退避する。

    **全体が静かになるのを待たない。** 待つ形は監視数が増えるほど成立しなくなる(module
    冒頭の実測)。ここが見るのは「まだ退避していない録画のうち、落ち着いた物が在るか」だけで、
    他の配信が録画中かどうかは**発火の条件にしない** —— 動いている録画は写す対象から外す
    ことで、走ってよいかではなく何を写すかの問題にしている。

    3つの退避は**独立して失敗させ、独立して印を進める**。DBのsnapshotが空き不足で落ちても
    設定値の書き出しは走るべきで、まとめてtryで包むと最初の失敗が残り2つを黙って飛ばす。
    印が1つだと「3つとも済んでから進める」しかなく、file backupが落ちた周期にDBの
    snapshot(1.65GB)まで取り直す。失敗した退避は次の周期からbackoffで再試行し、済んだ
    退避はその録画については二度と走らない。

    失敗はops_eventsへ残す(通知の対象になる)。textのlogだけでは、退避先が外れたまま
    何週間も失敗し続けていることに誰も気付かない ―― backupが黙って止まるのは、backupの
    事故のうち最もよくある形である。"""
    steps = _backup_enabled_steps()
    marks = {}
    for step in steps:
        raw = await asyncio.to_thread(
            runtime.storage.get_maintenance_value, _BACKUP_MARK_KEYS[step])
        marks[step] = float(raw) if raw else 0.0
    since = min(marks.values())
    rows = await asyncio.to_thread(runtime.storage.recordings_for_backup, since)
    quiet = get_record_backup_quiet_minutes() * 60.0
    ready, held = await asyncio.to_thread(
        _backup_recording_split, rows, quiet, time.time())
    # 落ち着いた録画のうち、まだ退避していない物。動いている録画(held)はここに数えない ——
    # 数えると、録画が1本でも走っているあいだ毎周期走り続ける。
    fresh = [row for row in ready if float(row["ended_at"]) > since]
    if not fresh:
        return
    ended_at = max(float(row["ended_at"]) for row in fresh)
    # 動いている録画は写す対象から外す。除外は「まだ見ていない」であって「消えた」では
    # ないので、削除の伝播からも外れる(``primary_backup.run_backup`` の約束)。
    exclude = _backup_exclusions(held)

    for step in steps:
        if marks[step] >= ended_at:
            # この退避はこの録画まで済んでいる(前の周期で他の退避だけが落ちた)。
            continue
        now = time.monotonic()
        if _backup_retry_pending(step, now):
            continue
        try:
            done = await _backup_run_step(step, ended_at, exclude)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = _backup_step_failed(step, now)
            kind, label = _BACKUP_FAILURE_EVENTS[step]
            await asyncio.to_thread(
                runtime.storage.record_ops_event, runtime.logger, kind,
                f"{label}: {exc}（次は {delay / 60.0:.0f} 分後に再試行）",
                severity=OPS_ERROR,
                detail={"error": type(exc).__name__, "ended_at": ended_at,
                        "failures": _backup_retry[step]["failures"],
                        "retry_in_seconds": delay},
                exc_info=True,
            )
            continue
        _backup_retry.pop(step, None)
        if not done:
            continue
        await asyncio.to_thread(
            runtime.storage.set_maintenance_value, _BACKUP_MARK_KEYS[step],
            repr(float(ended_at)))


async def backup_schedule_status() -> dict:
    """退避3つの「どこまで済んだか」「あと何本控えているか」「次はいつ試すか」。

    画面のためだけの関数だが、置き場所はここしかない —— 走らせる条件(印・落ち着いた録画の
    判定・失敗のbackoff・下限間隔)はこのmoduleの中にしか無く、書き写せば周期の条件を直した
    ときに画面だけが古い判定を出し続ける。**新しい判定は1つも作らない**。``_backup_tick``
    が使うのと同じ関数を同じ順で呼び、その材料を数えて返すだけである。

    「遅れている」の物差しだけは退避ごとに変える。file backupは下限間隔ぶん待つのが正常な
    状態で、他と同じ猶予を当てると正常な待機が毎周期その1つだけを赤く見せる。"""
    enabled = set(_backup_enabled_steps())
    marks = {}
    for step, key in _BACKUP_MARK_KEYS.items():
        raw = await asyncio.to_thread(runtime.storage.get_maintenance_value, key)
        marks[step] = float(raw) if raw else 0.0
    # ``since`` の決め方は _backup_tick と同じ。有効な退避の印だけを見る —— 止めてある退避の
    # 印は進まないので、混ぜると走査の起点が永久に過去へ張り付く。
    since = min((marks[step] for step in enabled), default=0.0)
    rows = await asyncio.to_thread(runtime.storage.recordings_for_backup, since)
    quiet = get_record_backup_quiet_minutes() * 60.0
    wall = time.time()
    ready, held = await asyncio.to_thread(_backup_recording_split, rows, quiet, wall)
    interval = get_record_backup_min_interval_minutes() * 60.0
    last_files = (await asyncio.to_thread(primary_backup.last_run)
                  if BACKUP_STEP_FILES in enabled else None)
    now = time.monotonic()
    steps = {}
    for step in _BACKUP_MARK_KEYS:
        pending = [row for row in ready if float(row["ended_at"]) > marks[step]]
        oldest = min((float(row["ended_at"]) for row in pending), default=None)
        retry = _backup_retry.get(step)
        grace = quiet + BACKUP_TICK_SECONDS * 5
        if step == BACKUP_STEP_FILES:
            grace += interval
        steps[step] = {
            "enabled": step in enabled,
            "mark_at": marks[step] or None,
            "pending": len(pending),
            "pending_oldest_at": oldest,
            "grace_seconds": grace,
            # 止めてある退避は印が進まないので、控えはいくらでも溜まる。それを遅れと呼ぶと
            # 「止めた」という設定どおりの状態が障害に見える。
            "overdue": bool(step in enabled and oldest is not None
                            and wall - oldest > grace),
            "failures": int(retry["failures"]) if retry else 0,
            "retry_in_seconds": max(0.0, float(retry["until"]) - now) if retry else 0.0,
        }
    return {
        "tick_seconds": BACKUP_TICK_SECONDS,
        "quiet_seconds": quiet,
        "min_interval_seconds": interval,
        # まだ動いている録画。写す対象から外れているだけで、失敗でも遅れでもない。
        "holding": len(held),
        "last_files_run_at": float((last_files or {}).get("started_at") or 0.0) or None,
        "steps": steps,
    }


async def _backup_loop_bg(after=None):
    """配信終了を合図にした退避のloop。

    起動直後に1度見るのは、前回の録画が終わった直後にserverが落ちていた場合の取りこぼしを
    拾うためである(印はDBに在るので、既に退避済みなら何も走らない)。"""
    if after is not None:
        try:
            await after
        except Exception:
            # 待っていたtaskの失敗はそちらが記録している。退避は独立して回す。
            pass
    while True:
        try:
            await _backup_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            runtime.logger.exception(
                "配信終了後の退避で予期しない失敗が起きました",
                extra={"event": "backup.tick_failed", "ctx": {}},
            )
        await asyncio.sleep(BACKUP_TICK_SECONDS)


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
    # 配信の終わりを合図にした退避(DBのsnapshot・設定値・一次保存のbackup)。sweepの後に
    # 置くのは、写す対象がsweepの作る派生物を含むためで、静穏時間はそれらが片付くのを待つ。
    # 中断録画の復旧を待つのはsweepと同じ理由 —— 復旧が書き換える前の姿を写さない。
    backup_task = asyncio.create_task(_backup_loop_bg(recovery_task))
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
    backup_task.cancel()
    try:
        await backup_task
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
