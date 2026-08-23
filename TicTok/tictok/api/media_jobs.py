"""映像job(焼き込み・Up出力・再mp4化・音量正規化・ts結合・切り出し・文字起こし)の実体。

永続queue(``media_job_queue``)と、queueが呼び出すjob本体、投入の入口(``_enqueue_media_job``)
が同居する。queue側は種別を知らず、``_media_job_runner`` -> ``_run_media_job`` の2段で
分岐する(それぞれのdocstring参照)。

``_media_job_runner`` が ``_run_media_job`` を同じmoduleの名前として引くのは意図的で、
実体が下で定義されていてよいのは名前解決が呼び出し時だからである。

依存は runtime / files / fsfacts / disk。routeはこの層を呼ぶ側で、逆向きは無い。
"""

import asyncio
import json
import secrets
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from tictok.core import layout, ops_labels
from tictok.record.recorder import (disk_free_by_volume, ffmpeg_available, ffmpeg_ctx,
    ffprobe_available, is_finalizing, reclaim_normalized_mp4, Recorder, session_prefix)
from tictok.record.transcription import STTError, stt_available
from tictok.record.stt_worker import run_transcribe as stt_transcribe
from tictok.media import clip_range, clip_subtitles, hls_source
from tictok.media import laugh_audio
from tictok.media import short as short_media
from tictok.media import voice
from tictok.media import work as work_media
from tictok.media.clipper import clip_path, make_clip, still_path, STILL_VARIANT_SUFFIXES
from tictok.media.reel import make_reel
from tictok.media.still import capture_still
from tictok.media.thumbnails import ensure_sprite
from tictok.media.waveform import ensure_audio_profile, ensure_waveform, silence_spans
from tictok.ai import ai_analysis
from tictok.search import indexer
from tictok.record import audio_norm, backups, bgm_remove, hls_pack, subtitles
from tictok.record.media_queue import (db_kind_for_domain, JobDeferred, JobSkipped,
    MediaJobQueue)
from tictok.record.upscale import UpscaleError, ensure_upscaled
from tictok.core import cancel, config
from tictok.core.progress import (fmt_hms, IntervalGate, JobProgress, PACK_PHASES,
    pump_ffmpeg_progress, REPROCESS_PHASES)
from tictok.record.video_overlay import (_duration_seconds, material_media_seconds,
    codec_family, ensure_overlay, NothingToDrawError, overlay_enabled, preview_clip,
    render_clip_overlay, subtitles_enabled, video_encoder_name)
from tictok.api import candidates as api_candidates
from tictok.api import files as api_files
from tictok.api import disk
from tictok.api import fsfacts
from tictok.api import runtime


async def _media_job_runner(job: dict, report) -> dict:
    """queueからjobを受け取る入口。実処理はこのmoduleの既存helperなので、queue側は焼き込みも
    超解像も知らないままでいられる。名前解決は呼び出し時なので、実体が下で定義されていてよい。"""
    try:
        missing = await asyncio.to_thread(runtime._missing_record_roots)
        if missing:
            raise JobDeferred(f"保存先が見つかりません（{', '.join(missing)}）。")
        # 確定処理中の録画には触らない。確定はsession dirの素材を読んで時刻mapと検証を
        # 通すので、その最中に同じ素材を読み書きするとjobも確定も壊れる(実測2026-07-26
        # 13:10、起動時のts結合が復旧中の録画を束ね、その元segmentを掴んだ側が落ちた)。
        # 確定は分単位で終わるため、失敗ではなく保留にして待たせる。
        if is_finalizing(job.get("recording_id")):
            raise JobDeferred("この録画は確定処理中です。")
        try:
            return await _run_media_job(job, report)
        except (cancel.JobCancelled, JobSkipped, JobDeferred):
            raise
        except Exception:
            # 実行中に消えた場合は、失敗の中身を問わず保留へ倒す。volumeが無い状態で
            # 出す診断(「.tsが見つかりません」等)はどれも二次症状で、そのまま失敗として
            # 残すと原因の分からない失敗が一括の中に散らばる。
            missing = await asyncio.to_thread(runtime._missing_record_roots)
            if missing:
                raise JobDeferred(f"保存先が見つかりません（{', '.join(missing)}）。") from None
            raise
    finally:
        # jobが1本終わると出力fileの有無が変わる。出力状態はfilesystemが正なので、
        # 状態を引いているcacheをここで捨てる。完了通知の直後に画面が引き直したとき、
        # TTLが残っていると「まだ未出力」と読める古い集計が返る。
        fsfacts._fs_state_cache.clear()
        fsfacts._fs_bulk_cache.clear()
        fsfacts._bulk_status_cache.clear()
        fsfacts._hls_dir_cache.clear()


# 焼き込み/Up出力/再mp4化の永続queue。workerは1本で、投入内容はDBに残るためserverを再起動
# しても消えない(実行中だった行は起動時にinterruptedへ倒し、個別recoveryへ回す)。
media_job_queue = MediaJobQueue(runtime.storage, runtime.hub.broadcast, _media_job_runner)


def _job_snapshot(*, states=None, domains=None, job_id=None, limit: int = 200) -> list:
    """画面が見るjobの全体像: process内registry(容量scan・保持policy・文字起こし)と、DBの
    映像job queue(単体job + session一括のgroup)を1つのlistに畳む。

    ``states`` / ``domains`` / ``job_id`` はJob画面のfilter。台帳側はDBのWHEREで、registry側は
    processが持つ数十件なのでここで絞る。filterを画面へ任せると、条件に一致する古い行が
    limitの外に落ちたまま「該当なし」と断定されるため、絞る場所をserverへ寄せている。"""
    registry = runtime.jobs.snapshot()
    if states is not None:
        registry = [job for job in registry if job["state"] in states]
    if domains is not None:
        registry = [job for job in registry if job["domain"] in domains]
    if job_id:
        registry = [job for job in registry if job["job_id"] == job_id]
    kinds = None if domains is None else [db_kind_for_domain(d) for d in domains]
    return registry + media_job_queue.list_jobs(limit, states=states, kinds=kinds,
                                                job_id=job_id)


def _job_page(*, states=None, domains=None, job_id=None, limit: int = 200) -> tuple:
    """(表示するjob, filterに一致する台帳の全行数)。

    2つを1回のthread呼び出しで返すのは、この画面がWSの接続ごとに叩かれるため。件数を添える
    のは、limitで切った一覧を『これが全部』と読ませないため(0件の断定と、見えていないだけを
    画面が区別できる)。"""
    kinds = None if domains is None else [db_kind_for_domain(d) for d in domains]
    jobs = _job_snapshot(states=states, domains=domains, job_id=job_id, limit=limit)
    total = runtime.storage.count_media_jobs(states=states, kinds=kinds, job_id=job_id)
    return jobs, total


def _media_job_running() -> bool:
    """素材や中間fileを掴むjobが今この瞬間走っているか。file削除の可否判定に使う。

    ts結合を含めるのは、束ねている最中のsession dirを保持policyが消しにいくと、読み書き中の
    素材を足元から抜くことになるため(焼き込みのsidecarと同じ理由)。"""
    return any(job["state"] == "running" and job["domain"] in ("overlay", "upscale", "pack")
               for job in _job_snapshot())


def _pipe(stream: Optional[asyncio.StreamReader], name: str) -> asyncio.StreamReader:
    """PIPEで起こしたprocessの出力stream。

    ``Process.stdout`` / ``stderr`` は「PIPEを指定していなければNone」なので型はOptionalだが、
    ここで起こすffmpegは必ず両方をPIPEにしている。Noneが来るのはその前提が崩れたときだけで、
    そのまま進めても「読めないstreamを待ち続けて終わらないjob」になるだけなので、読む前に
    失敗させる。"""
    if stream is None:
        raise RuntimeError(f"ffmpegの{name}がPIPEで開かれていません")
    return stream


def _recording_for_output(recording_id: int) -> tuple[dict, Path]:
    recording = runtime.storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = api_files._safe_recording_path(recording["path"])
    # ``path`` は録画の身元(mp4 path)であって、実在するとは限らない。finalizeはmp4を
    # 作らなくなり、原本は .ts になった。焼き込みも下流も hls_source 経由で .ts を読む
    # ので、mp4の有無で断ってはいけない — 断ると新しい録画が1本も焼けなくなる。
    # 判定は「素材が1つでも残っているか」に置く。
    if not path.is_file() and not api_files._recording_media_dirs(recording):
        raise HTTPException(status_code=404, detail="録画fileが存在しません（削除済みか録画失敗）。")
    # Outputs (comment layer, CFR base, the rendered mp4, the upscaled mp4) are all
    # written beside the source, so that volume is the one that has to hold them.
    disk._require_disk_space([path.parent], "output", recording_id=recording_id)
    return recording, path


def _recording_media_seconds(recording: dict) -> Optional[float]:
    """この録画の素材の実尺。判定の実体はvideo_overlay側に1つだけ置く(焼き込みの最終関門と
    同じ物差しで測るため)。pathを解決できなければNone。"""
    try:
        return material_media_seconds(api_files._resolved_recording_path(recording))
    except HTTPException:
        return None


def _subtitle_transcript(recording_id: int, settings=None) -> Optional[dict]:
    """字幕焼き込みに使うtranscript。設定がOFFならNone。

    設定がONなのに文字起こしが無い / 時刻mapが現行版でない / **素材と時間軸が違う** / 出せる
    segmentが無い場合は、字幕なしで焼かずに拒否する。焼き込みは元に戻せない成果物なので、
    ズレた字幕や無言の欠落を作るより先に文字起こしをやり直させる方が安い(提案書②-4の必須条件(c))。

    ``settings`` はshortのように「字幕の有無を型が決める」経路のための差し替え口。判定の
    中身は同じで、どのsettingsを見るかだけが変わる(short用に別の判定を書くと、字幕が焼ける
    条件が2つに割れる)。"""
    if not subtitles_enabled(runtime.settings if settings is None else settings):
        return None
    transcript = runtime.storage.get_transcript(recording_id)
    if transcript is None:
        raise HTTPException(
            status_code=409,
            detail="字幕の焼き込みが有効ですが、この録画は文字起こしがありません。先に文字起こしを実行してください。",
        )
    if not subtitles.timemap_current(transcript.get("timemap_version")):
        raise HTTPException(
            status_code=409,
            detail="この録画の文字起こしは古い時刻mapで作られており、字幕が動画とズレます。文字起こしをやり直してから焼き込んでください。",
        )
    # 版が同じでも、作られたときの入力が別物なら時刻はずれる(実測で実尺+191秒/+28287秒)。
    # 版だけを見ていた頃はそれが素通りし、ズレた字幕が恒久的に焼き付いていた。
    recording = runtime.storage.get_recording(recording_id)
    media_seconds = _recording_media_seconds(recording) if recording else None
    if not subtitles.axis_matches_media(transcript, media_seconds):
        raise HTTPException(
            status_code=409,
            detail=(
                "この録画の文字起こしは素材と時間軸が違います"
                f"（文字起こし {float(transcript['duration']):.0f}秒 / 素材 {media_seconds:.0f}秒）。"
                "そのまま焼くと字幕が動画とズレます。文字起こしをやり直してから焼き込んでください。"
            ),
        )
    if not subtitles.usable_segments(transcript.get("segments")):
        raise HTTPException(
            status_code=409,
            detail="この録画の文字起こしに、字幕として焼き込めるsegmentがありません。",
        )
    return transcript


async def _burn_in_recording(recording: dict, path: Path, job_id: str,
                             on_stage_pct) -> dict:
    """Render one recording's burn-in, reporting stage progress to both the legacy
    per-recording websocket message (which the open page's row spinner reads) and the job
    registry (which survives a reload). Returns the ensure_overlay result, or an empty
    dict when the burn-in is off / the recording has no session to draw from."""
    recording_id = recording["id"]
    if not (overlay_enabled(runtime.settings) and recording.get("session_id") is not None):
        return {}
    # 焼き込みの入力を揃えるところは全てthreadへ出す。event loop上で引くとその間serverが
    # 止まる: iter_eventsはbufferのflushを待ってからsessionの全eventを読み(実測37,214件で
    # 372ms)、writer lockも同じだけ握るのでcollectorの書き出しまで巻き添えにする。
    # 文字起こし側はsegments_json(実測800KB級)の復号が載る。
    transcript = await asyncio.to_thread(_subtitle_transcript, recording_id)
    events = await asyncio.to_thread(
        runtime.storage.iter_events,
        recording["session_id"], recording["started_at"], recording.get("ended_at")
    )
    battles = await asyncio.to_thread(
        runtime.storage.battles_for_session, recording["session_id"])

    async def _emit_progress(pct: int, stage: str) -> None:
        await runtime.hub.broadcast(
            {"type": "output_progress", "recording_id": recording_id,
             "pct": pct, "stage": stage}
        )
        await on_stage_pct(stage, pct)

    try:
        async with runtime._job_ops("overlay", recording_id, stem=path.stem, events=len(events),
                            job_registry_id=job_id):
            return await ensure_overlay(
                str(path), recording["started_at"], recording.get("ended_at"),
                events, runtime.settings, battles=battles, on_progress=_emit_progress,
                transcript=transcript,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _overlay_payload(result: dict, path: Path) -> tuple[Path, dict]:
    """(rendered path, extra payload) for an ensure_overlay result."""
    rendered = path
    payload: dict = {}
    if result:
        rendered = api_files._safe_recording_path(str(result["a"]))
        # Mode B (source-clock timing) comparison output, present only when the
        # compare setting is on and the recording carried create_time to anchor on.
        out_b = result.get("b")
        if out_b is not None:
            rendered_b = api_files._safe_recording_path(str(out_b))
            payload["filename_b"] = rendered_b.name
            payload["output_path_b"] = str(rendered_b)
    return rendered, payload


def _preview_sources(recording_id: int) -> tuple:
    """プレビュー1回ぶんの入力 (recording, path, events, battles, transcript)。
    焼き込み本体(_burn_in_recording)と同じ源から、同じ窓で取る。ここが違うと
    プレビューと本出力で描くeventが変わり、確認の意味が消える。"""
    recording, path = _recording_for_output(recording_id)
    if not overlay_enabled(runtime.settings):
        raise HTTPException(
            status_code=409,
            detail="焼き込みの設定が全てOFFです。Comment/Gift/Battle/字幕のいずれかを有効にしてください。",
        )
    if recording.get("session_id") is None:
        raise HTTPException(
            status_code=409, detail="この録画にはSessionが紐づいておらず、焼き込むeventがありません。",
        )
    transcript = _subtitle_transcript(recording_id)
    events = runtime.storage.iter_events(
        recording["session_id"], recording["started_at"], recording.get("ended_at")
    )
    battles = runtime.storage.battles_for_session(recording["session_id"])
    return recording, path, events, battles, transcript


# DBのqueue(media_job_queue)に載るjobの種類。``_run_media_job`` が分岐できる全てであり、
# 取り消し・再実行が効くのもこの範囲そのものである(Job画面はこれをserverから受け取る)。
# 文字起こし・笑い声分析も同じ台帳で走る。別台帳だった頃はJob一覧に出ず、GPUを同じ枠で
# 取り合っているのに「動いているのにjobが無い」と読める状態だった。
MEDIA_JOB_KINDS = ("overlay", "upscale", "reprocess", "audionorm", "pack",
                   "waveform", "sprite", "voice", "overlay_preview", "clip_batch",
                   "reel", "clip_overlay", "short", "stt", "laugh", "still")

# 台帳に出る種別名。訳語の出所はops_labelsの1箇所だけにする(同じ語を2箇所に置くと、job
# titleと種別labelがずれる — ops_labelsのmodule docstringと同じ約束)。
MEDIA_JOB_TITLES = {kind: ops_labels.JOB_DOMAIN_LABELS[kind] for kind in MEDIA_JOB_KINDS}

# Job画面で取り消し・再実行のbuttonを出してよいdomain。台帳の種別に加えて、一括投入を
# 1行へ畳んだgroup行(group全体へ効く)を含む。画面側に同じ一覧を持たせていた頃は、台帳へ
# 種別が増えても画面が黙って古いままで、実際に文字起こしのjobだけbuttonが出なかった。
QUEUED_JOB_DOMAINS = MEDIA_JOB_KINDS + tuple(ops_labels.GROUP_DOMAIN_LABELS)

# 録画単位の二重投入judgeを通さないkind。reelは複数録画にまたがり、同じ先頭録画でも範囲listが
# 違えば別の成果物なので、(kind, recording_id)で弾くと2本目が永久に投げられない。stillも同じで、
# 位置が違えば別の1枚である(同じ録画から続けて撮る操作を弾いてはならない)。
_NO_PER_RECORDING_DEDUPE = ("reel", "still")

# スクショは人がその場で待っている1 clickの操作で、実処理は数秒のffmpeg 1本である。待機列の
# 末尾に付けると、長い焼き込みが数十本並んでいる間ずっと保存されない。順番だけを前へ出す
# (同時実行の枠は media_queue の instant lane が別に持つ)。
STILL_JOB_PRIORITY = 20

# sweepが積むjobのpriority。負にしておけば、sweepが数十本並んでいる最中に人が投げた
# jobが必ず先に始まる(待機列はpriority DESC, queued_atで並ぶ)。同時実行の本数を絞るのは
# 別の仕組み(media_job_queueのsweep列)で、こちらは順番だけを譲る。
SWEEP_JOB_PRIORITY = -10


async def _enqueue_media_job(kind: str, recording_id: int, *, group_id: str = "",
                             recording: Optional[dict] = None,
                             stem: str = "", params: Optional[dict] = None,
                             priority: int = 0, sweep: bool = False) -> dict:
    """映像jobを1件queueへ載せ、job_idを返す。

    実行はworkerが行うため、この応答に出力file名は含まれない(完了時のfile名はjobのresultと
    WSのjob_updateで届く)。同じ録画・同じ種別が既にqueueに居るときは二重投入を拒む: 同一
    出力pathへ2本走らせても片方の成果は必ず捨てられ、GPUを二重に占有するだけになる。

    ``sweep`` はsweepからの自動投入。人の投入と同じ台帳・同じworkerで走らせつつ、
    順番(priority)と同時実行本数だけを別枠にするための印。
    """
    if (kind not in _NO_PER_RECORDING_DEDUPE
            and media_job_queue.pending_for(kind, recording_id) is not None):
        raise HTTPException(
            status_code=409,
            detail=f"この録画の{MEDIA_JOB_TITLES[kind]}は既にqueueにあります（jobで確認できます）。",
        )
    if kind in ("overlay", "upscale", "overlay_preview", "clip_overlay"):
        # 字幕焼き込みが有効なら、文字起こしが揃っているかを投入時に確かめる。workerで初めて
        # 落とすと、GPUの順番を待った末に失敗することになる。
        _subtitle_transcript(recording_id)
    if kind == "short":
        # shortは字幕の有無を型が決めるので、その型の指定で同じ確認をする。
        preset = _short_preset(params or {})
        _subtitle_transcript(
            recording_id, short_media.ShortSettings(runtime.settings, preset))
    job_id = secrets.token_hex(4)
    row = await media_job_queue.enqueue(
        job_id, kind, recording_id,
        session_id=(recording or {}).get("session_id"), group_id=group_id,
        title=f"{MEDIA_JOB_TITLES[kind]} {stem}".strip(), params=params,
        priority=priority, sweep=sweep,
    )
    return {"job_id": job_id, "kind": kind, "recording_id": recording_id,
            "state": row["state"], "queued_at": row["queued_at"]}


CORRECTION_POLICIES = ("keep", "discard")


def _corrections_policy(params: Optional[dict]) -> str:
    """再文字起こし時に既存の訂正をどうするか。既定は引き継ぎ。

    未知の値は既定へ倒さず弾く。訂正を捨てるかどうかは取り返しの付き方が違う操作で、
    綴り違いを黙って「引き継ぎ」と読むと、破棄を指示したつもりの人に古い訂正が残る。"""
    value = (params or {}).get("corrections") or "keep"
    if value not in CORRECTION_POLICIES:
        raise HTTPException(
            status_code=400,
            detail=f"correctionsは {'/'.join(CORRECTION_POLICIES)} のいずれかです。")
    return value


async def _transcribe_into_storage(recording: dict, path: Path, on_progress,
                                   corrections: str = "keep") -> dict:
    """1本を文字起こしして保存し、検索indexへ反映する。

    復号は必ず ``stt_worker`` の子processで走る(serverでCTranslate2を読むと、torchと別version
    のcuDNNが同じDLL名で同居してprocessごと即死する)。GPU枠も子の生存期間ぶんそこで押さえる。

    ``corrections`` は既にある訂正の扱い。``keep`` は新しいsegmentへ貼り直し(当たらなければ
    保留)、``discard`` は捨てる(行は残す)。誤りを1件ずつ直した後なら前者、modelや時刻mapを
    変えたなら後者が正しく、どちらかに決め打てないので実行時に選ぶ。"""
    async with hls_source.ffmpeg_source_async(
            path, prefer_hls=hls_source.plays_from_hls(path)) as source:
        result = await asyncio.to_thread(stt_transcribe, str(source.path), on_progress)
    # 文字起こし1本ぶんのsegments_jsonは実測800KB級。event loop上で書くとその間serverが止まる
    # (単発API側の同じ保存は既にthreadへ出ている)。
    await asyncio.to_thread(runtime.storage.save_transcript, recording["id"], result,
                            corrections)
    # 保存と同時に検索indexへ反映する。ここを省くと文字起こし済みなのに検索へ出ない録画が残る。
    await asyncio.to_thread(indexer.index_transcript, runtime.storage, recording)
    return result


async def _run_stt_job(recording_id: int, report, params: Optional[dict] = None) -> dict:
    """文字起こしをqueueのworkerとして実行する。

    以前は専用台帳(transcribe_queue)で動いていた。分離の根拠だった「済み台帳を兼ねる」役割は
    transcriptsテーブルが持っており、GPU枠は元から共通なので、台帳を分ける理由が残っていない。
    同じ台帳に載せると、Job一覧・取り消し・中断復帰・一括投入が映像jobとそのまま同じになる。"""
    recording = runtime.storage.get_recording(recording_id)
    if recording is None:
        raise JobSkipped("録画が見つかりません（削除済み）。")
    if not stt_available():
        raise HTTPException(
            status_code=503,
            detail="STTが利用できません。faster-whisperのinstallとTICTOK_STT_ENABLEDを確認してください。")
    path = api_files._resolved_recording_path(recording)
    if not api_files._recording_source_exists(recording):
        # 実体が消えた録画は、何度積み直しても結果が変わらない。失敗ではなく素通りさせる。
        raise JobSkipped("録画fileが存在しません（削除済みか録画失敗）。")
    loop = asyncio.get_running_loop()

    async def _report(pct: int, detail: Optional[str] = None) -> None:
        # 録画詳細画面が見ているlegacy eventも従来どおり出す(Job一覧はreport側で更新される)。
        await runtime.hub.broadcast(
            {"type": "transcribe_progress", "recording_id": recording_id, "pct": pct})
        await report(f"文字起こし（{detail}）" if detail else "文字起こし", pct)

    def on_progress(done: float, total: float) -> None:
        pct = min(100, int(done / total * 100)) if total > 0 else 0
        # 子processが送る done/total は音声の秒数。%だけだと4時間の録画で1目盛が2.4分に
        # なるので、どこを聞いているかを併記する。
        detail = f"{fmt_hms(done)} / {fmt_hms(total)}" if total > 0 else None
        asyncio.run_coroutine_threadsafe(_report(pct, detail), loop)

    try:
        async with runtime._job_ops("stt", recording_id, stem=path.stem):
            result = await _transcribe_into_storage(
                recording, path, on_progress, _corrections_policy(params))
    except STTError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await _report(100)
    return {"recording_id": recording_id, "segments": len(result.get("segments") or []),
            "language": result.get("language"), "duration_seconds": result.get("duration")}


async def _enqueue_stt_jobs(recordings: list, priority: int = 0, sweep: bool = False,
                            corrections: str = "keep") -> dict:
    """文字起こしを録画ごとに1件ずつqueueへ載せる。投入できた数と内訳を返す。

    既にqueueに居る録画は数えて先へ進む(二重投入の判断は ``_enqueue_media_job`` と同じ
    ``pending_for``)。実体の無い録画は投入しない — 何度積んでも結果は変わらず、
    sweepのたびに同じ失敗が積み上がるだけになる(実測89件)。

    選別と投入を分けているのは、どちらもevent loopを塞ぐためである。選別は録画ごとに
    素材のdir走査とDB照会を行い、投入は1本ごとに待機列全件を引き直していた(N本でN²)。
    選別はthreadでまとめ、投入は ``enqueue_many`` の1回に畳む。"""
    def _classify() -> tuple:
        specs: list = []
        skipped_no_media = 0
        already = 0
        seen: set = set()
        for recording in recordings:
            if not api_files._recording_source_exists(recording):
                skipped_no_media += 1
                continue
            recording_id = recording["id"]
            # 同じ録画が母集合に2度現れた場合も「既にqueueにある」で数える。1件ずつ投入して
            # いた頃は2本目のpending_forが1本目を見つけて弾いていた。
            if (recording_id in seen
                    or media_job_queue.pending_for("stt", recording_id) is not None):
                already += 1
                continue
            seen.add(recording_id)
            stem = Path(recording.get("filename") or "").stem
            specs.append({
                "job_id": secrets.token_hex(4), "kind": "stt",
                "recording_id": recording_id,
                "session_id": recording.get("session_id"), "group_id": "",
                "title": f"{MEDIA_JOB_TITLES['stt']} {stem}".strip(),
                "params": {"corrections": corrections}, "priority": priority,
                "sweep": sweep,
            })
        return specs, already, skipped_no_media

    specs, already, skipped_no_media = await asyncio.to_thread(_classify)
    added = len(await media_job_queue.enqueue_many(specs))
    runtime.logger.info(
        "音声の文字起こしjobをqueueへ入れました: 追加=%d 既存=%d 素材なしでskip=%d", added, already,
        skipped_no_media,
        extra={"event": "stt.jobs_enqueued",
               "ctx": {"added": added, "already": already,
                       "skipped_no_media": skipped_no_media,
                       "candidates": len(recordings), "sweep": sweep}},
    )
    return {"added": added, "candidates": len(recordings), "already": already,
            "skipped_no_media": skipped_no_media}


async def _run_laugh_job(recording_id: int, report) -> dict:
    """笑い声分析をqueueのworkerとして実行し、結果を検索indexへ反映する。

    解析そのものは ``ensure_laugh_profile`` が持つ(sidecarが在れば読むだけ)。**indexへの
    投入は毎回行う**: sidecarだけ在ってindexが無い録画(解析だけ先に回した録画・閾値を
    変えた後)を、同じjobで拾い直せるようにするためである。cacheに当たる場合の解析は
    実測で数十msなので、毎回通しても損はしない。

    deviceがcudaのときは ``laugh_audio`` 側が別processへ出す(この関数はどちらでも同じ)。
    """
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise JobSkipped("録画が見つかりません（削除済み）。")
    if not api_files._recording_source_exists(recording):
        raise JobSkipped("録画fileが存在しません（削除済みか録画失敗）。")
    path = api_files._resolved_recording_path(recording)
    await report("笑い声分析", 0)
    loop = asyncio.get_running_loop()
    # 分母は録画の実測尺。解析側は復号し切るまで尺を知らないので、%を作れるのはここだけ
    # である。尺が記録されていない録画は%を動かさず位置だけを出す — 分母を推測すると、
    # 90%まで進んでから伸び続ける進捗になる。
    total_seconds = recording.get("duration_seconds") or 0.0
    # cpu実行は解析threadから1 chunkごとに直接届く(子processを挟む経路と違い、間引きが
    # まだ掛かっていない)。DB書き込みとbroadcastを伴うので、ここでも同じ間隔で絞る。
    gate = IntervalGate(config.get_job_progress_min_interval_seconds())

    def on_progress(seconds: float) -> None:
        if not gate.ready():
            return
        detail = (f"{fmt_hms(seconds)} / {fmt_hms(total_seconds)}" if total_seconds > 0
                  else fmt_hms(seconds))
        pct = min(89, int(seconds / total_seconds * 90)) if total_seconds > 0 else 0
        asyncio.run_coroutine_threadsafe(
            report(f"笑い声分析（{detail}）", pct), loop)

    try:
        async with runtime._job_ops("laugh", recording_id, stem=path.stem):
            profile = await laugh_audio.ensure_laugh_profile(path, on_progress)
    except hls_source.SourceMissing as exc:
        raise JobSkipped(str(exc) or "素材が見つかりません。")
    except laugh_audio.LaughAudioError as exc:
        # model未配置・engine無効は録画の問題ではない。積み直しても直らないので、
        # 失敗として理由ごと残す(JobSkippedにすると設定の不備が静かに流れる)。
        raise HTTPException(status_code=503, detail=str(exc))
    await report("検索indexへ登録", 90)
    # 共演中を外すための窓は、解析したのと同じ素材から時間軸を作る(pathを渡さないと
    # DBのmp4 pathを見に行き、実体の無い録画で軸が素のwall offsetへ縮退する)。
    windows = await asyncio.to_thread(
        indexer.index_laughter, runtime.storage, recording, profile, None, path)
    await report("笑い声分析", 100)
    return {"recording_id": recording_id, "windows": windows,
            "duration_seconds": profile.get("duration_seconds")}


async def _enqueue_laugh_jobs(recordings: list, priority: int = 0,
                              sweep: bool = False) -> dict:
    """笑い声分析を録画ごとに1件ずつqueueへ載せる。``_enqueue_stt_jobs`` と同じ形。"""
    def _classify() -> tuple:
        specs: list = []
        skipped_no_media = 0
        already = 0
        seen: set = set()
        for recording in recordings:
            if not api_files._recording_source_exists(recording):
                skipped_no_media += 1
                continue
            recording_id = recording["id"]
            if (recording_id in seen
                    or media_job_queue.pending_for("laugh", recording_id) is not None):
                already += 1
                continue
            seen.add(recording_id)
            stem = Path(recording.get("filename") or "").stem
            specs.append({
                "job_id": secrets.token_hex(4), "kind": "laugh",
                "recording_id": recording_id,
                "session_id": recording.get("session_id"), "group_id": "",
                "title": f"{MEDIA_JOB_TITLES['laugh']} {stem}".strip(),
                "params": {"corrections": corrections}, "priority": priority,
                "sweep": sweep,
            })
        return specs, already, skipped_no_media

    specs, already, skipped_no_media = await asyncio.to_thread(_classify)
    added = len(await media_job_queue.enqueue_many(specs))
    runtime.logger.info(
        "笑い声分析のjobをqueueへ入れました: 追加=%d 既存=%d 素材なしでskip=%d",
        added, already, skipped_no_media,
        extra={"event": "laugh.jobs_enqueued",
               "ctx": {"added": added, "already": already,
                       "skipped_no_media": skipped_no_media,
                       "candidates": len(recordings), "sweep": sweep}},
    )
    return {"added": added, "candidates": len(recordings), "already": already,
            "skipped_no_media": skipped_no_media}


async def _run_preview_clip_job(recording_id: int, report) -> dict:
    """動画プレビューをqueueのworkerとして実行する。焼き込み本体と違い成果物はsidecarの
    <name>.preview.mp4 だけで、本出力のmp4にもそのcache判定にも触れない。"""
    recording, path, events, battles, transcript = await asyncio.to_thread(_preview_sources, recording_id)

    async def _emit_progress(pct: int, stage: str) -> None:
        await report(stage, pct)

    try:
        async with runtime._job_ops("overlay_preview", recording_id, stem=path.stem,
                            events=len(events)):
            try:
                result = await preview_clip(
                    str(path), recording["started_at"], recording.get("ended_at"),
                    events, runtime.settings, battles=battles, transcript=transcript,
                    on_progress=_emit_progress,
                )
            except NothingToDrawError as exc:
                # 静止画側は409で返している同じ前提不成立。job経路はHTTP statusを持たない
                # ため、失敗ではなくskippedとして着地させる(RuntimeErrorの下で拾うと
                # 500→job failedになり、静止画と動画で結論が食い違う)。
                raise JobSkipped(str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    win_start, win_end = result["window"]
    return {
        "recording_id": recording_id,
        "filename": Path(result["path"]).name,
        "output_path": str(result["path"]),
        "window_start_seconds": round(win_start, 3),
        "window_end_seconds": round(win_end, 3),
        "window_auto": result["window_auto"],
        "cached": result["cached"],
        "url": f"/api/recordings/{recording_id}/preview/clip.mp4",
    }


async def _reel_items(ranges: list, variant: str) -> list:
    """範囲listを make_reel の items へ直す。素材が無ければ投入前に落とす。"""
    items = []
    for item in ranges:
        recording = runtime.storage.get_recording(int(item["recording_id"]))
        if recording is None:
            raise HTTPException(status_code=404, detail="録画が見つかりません。")
        items.append({"src": api_files._clip_source(recording, variant),
                      "start": float(item["start"]), "end": float(item["end"]),
                      "label": item.get("label") or ""})
    return items


async def _run_clip_overlay_job(job: dict, report) -> dict:
    """切り抜きの範囲だけを焼き込む。

    全尺の焼き込み出力を作ってから切り出す経路と違い、cost が尺に比例する(3時間の録画から
    60秒を得るのに3時間ぶん焼かない)。可逆中間がC:を192GB/時食う機構なので、この差が
    「長尺では実行できない」と「数分で終わる」の差になる。
    """
    recording_id = job["recording_id"]
    params = job.get("params") or {}
    recording, path, events, battles, transcript = await asyncio.to_thread(_preview_sources, recording_id)
    start, end = float(params["start"]), float(params["end"])
    out = clip_path(path, start, end, params.get("label"), suffix="overlay")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with runtime._job_ops("clip_overlay", recording_id, stem=path.stem,
                            job_registry_id=job["job_id"], start=start, end=end):
            result = await render_clip_overlay(
                str(path), recording["started_at"], recording.get("ended_at"),
                events, runtime.settings, str(out), start, end,
                battles=battles, on_progress=short_media._stage_adapter(report),
                transcript=transcript)
    except NothingToDrawError as exc:  # 字幕の前提不成立(subclass)も含む
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    size = out.stat().st_size if out.is_file() else 0
    return {
        "recording_id": recording_id,
        "filename": out.name,
        "output_path": str(out),
        "bytes": size,
        "start": start,
        "end": end,
        # 再encodeなのでframe精度で切れる。stream copyのkeyframe前置きは付かない。
        "keyframe_lead_seconds": 0.0,
        "actual_start_seconds": start,
        "cached": bool(result.get("cached")),
        "variant": "overlay",
    }


async def _run_reel_job(job: dict, report) -> dict:
    """見どころの範囲を1本のmp4へ連結する。

    素材の形式が揃わなければ make_reel が明示的に失敗する(黙って再encodeへ倒さない)。
    連結できる組み合わせかは投入前にも確かめているが、その間に素材が変わり得るので
    実行直前の照合は省かない。
    """
    params = job.get("params") or {}
    items = await _reel_items(params.get("ranges") or [], params.get("variant") or "source")
    try:
        result = await make_reel(items, label=params.get("label"), on_progress=report)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "recording_id": job["recording_id"],
        "filename": result["filename"],
        "output_path": result["path"],
        "bytes": result["bytes"],
        "parts": len(result["parts"]),
        # 要求した合計尺と、keyframe境界で前に付いた合計。実録画では30秒の範囲に37秒の
        # 前置きが付いた例があるので、「90秒のつもりが134秒」を画面が説明できるよう両方返す。
        "requested_seconds": result["requested_seconds"],
        "lead_seconds": result["lead_seconds"],
        "output_duration_seconds": result["output_duration_seconds"],
        "part_details": result["parts"],
    }


async def _run_clip_batch_job(job: dict, report) -> dict:
    """1録画ぶんの範囲listを順に切り出す。GPUは使わないがdiskは食うので、queueに載せて
    直列に流す(browserを閉じても続き、job画面から取り消せる)。"""
    recording_id = job["recording_id"]
    params = job.get("params") or {}
    ranges = params.get("ranges") or []
    recording = runtime.storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    src = api_files._clip_source(recording, params.get("variant") or "source")
    normalize = _clip_normalize(params.get("normalize_audio"))
    remove_bgm = _clip_remove_bgm(params.get("remove_bgm"))
    variant = params.get("variant") or "source"
    want_subtitles = _clip_subtitles(params.get("subtitles"))
    mode = _clip_mode(params.get("mode"), params.get("precise"))
    total = len(ranges)
    files = []
    paths = []
    subtitle_files: list = []
    subtitle_note = ""
    total_bytes = 0
    for index, item in enumerate(ranges):
        cancel.check_cancelled()
        # 件数は括弧に入れる。段階名の一部にすると、120件のbatchが120個の別々の段階として
        # 履歴に並ぶ(段階の履歴は括弧の中を落として同じ段階と見なす — media_queue.stage_phase)。
        await report(f"切り出し中（{index + 1} / {total}件）",
                     int(index * 100 / total) if total else 0)
        try:
            async with runtime._job_ops("clip", recording_id, stem=src.stem,
                                variant=params.get("variant") or "source",
                                job_registry_id=job["job_id"],
                                **audio_norm.describe(normalize),
                                **bgm_remove.describe(remove_bgm)):
                result = await make_clip(
                    src, float(item["start"]), float(item["end"]), item.get("label"),
                    precise=(mode == "precise"), normalize=normalize,
                    smart=(mode == "smart"), remove_bgm=remove_bgm)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        if want_subtitles:
            await _attach_clip_subtitles(result, recording_id, variant)
            subtitle_files.extend(result["subtitles"].get("files") or [])
            # 出せなかった理由は最後の1件ぶんを持つ。理由は範囲ではなく録画側の事情
            # (文字起こしの有無・時刻mapの版・素材版)で決まるので、全件で同じになる。
            subtitle_note = result["subtitles"].get("message") or subtitle_note
        files.append(result["filename"])
        paths.append(result["path"])
        total_bytes += result["bytes"]
        # 由来の見どころへ「いつ・どこへ出したか」を書き戻す。これが無いと、一覧は何度
        # 書き出しても同じ見た目のままで、どの行が成果物を持っているのか読み取れない。
        # 書き戻しに失敗してもmp4は出来ているので、切り出し自体は失敗にしない。
        if item.get("bookmark_id") is not None:
            try:
                await asyncio.to_thread(runtime.storage.mark_bookmark_exported,
                                        int(item["bookmark_id"]), result["path"])
            except Exception:
                runtime.logger.warning(
                    "見どころの書き出し記録に失敗しました（bookmark_id=%s）",
                    item.get("bookmark_id"), exc_info=True,
                    extra={"event": "clip.export_mark_failed",
                           "ctx": {"bookmark_id": item.get("bookmark_id"),
                                   "path": result["path"]}})
        # 完了ぶんを必ず報告する。開始時の報告だけだと1件のbatchは終始0%のままで、
        # 複数件でも最後の1本が丸ごと「進捗なし」の区間になる。
        await report(f"切り出し済み（{index + 1} / {total}件）",
                     int((index + 1) * 100 / total) if total else 100)
    # 出力先は結果の一部である。以前はfile名だけを返していたので、画面もlogも「どこに
    # 出来たか」を名乗れず、利用者は成果物を探せなかった(単発の切り出しだけがpathを返す
    # 非対称な状態だった)。dirは全件同じ(clip_pathは録画ごとに1つの置き場を決める)。
    output_dir = str(Path(paths[0]).parent) if paths else ""
    return {"recording_id": recording_id, "count": len(files), "files": files,
            "paths": paths, "output_dir": output_dir,
            "filename": files[0] if len(files) == 1 else "",
            "output_path": paths[0] if len(paths) == 1 else "",
            "bytes": total_bytes, "variant": variant,
            "normalized": bool(normalize), "mode": mode,
            # 添えた字幕fileは成果物なので件数を名乗る。要求したのに0件だったときは理由を
            # 添える(黙って出ていないと、利用者は切り出しごとやり直す)。
            "subtitle_files": subtitle_files,
            "subtitle_note": "" if subtitle_files else subtitle_note}


def _short_preset(params: dict) -> dict:
    """このjobが使う型。指定が無ければ並びの先頭。1件も無ければ**失敗させる**。

    既定値で埋めないのは、どの尺で作ったのかを誰も言えない成果物を出さないためである。"""
    preset_id = params.get("preset_id")
    preset = (runtime.storage.get_clip_preset(int(preset_id)) if preset_id
              else runtime.storage.default_clip_preset())
    if preset is None:
        raise HTTPException(
            status_code=409,
            detail="shortの型が1つもありません。設定でshortの型を作ってから実行してください。")
    return preset


def _short_boundaries(recording_id: int, path: Path, duration) -> dict:
    """範囲確定が使う観測(発話・章)を集める。取れないものは空のまま返す。

    章立ては**既にあるものだけ**を使い、ここで生成はしない。章の生成はLLMを長時間回す
    別の操作で、shortを作るついでに黙って走らせてよいものではない。
    """
    transcript = runtime.storage.get_transcript(recording_id)
    segments: list = []
    if transcript and subtitles.timemap_current(transcript.get("timemap_version")):
        # 古い時刻mapのtranscriptは端の吸着先として使えない(尺が伸びるほど後ろへずれる)。
        # 字幕を焼かない型でも同じで、ずれた境界へ吸着させれば範囲そのものがずれる。
        segments = subtitles.usable_segments(transcript.get("segments"), duration)
    cached = runtime.storage.get_ai_analysis(
        ai_analysis.KIND_CHAPTERS, ai_analysis.TARGET_RECORDING, str(recording_id))
    chapters = ((cached or {}).get("payload") or {}).get("chapters") or []
    return {"segments": segments, "chapters": chapters, "transcript": transcript}


def _short_taken_ranges(recording_id: int) -> list:
    """この録画で既に押さえてある範囲。同じ場面を二度出さないための入力。

    人が付けた見どころも機械が書き戻した行も等しく「押さえてある」。範囲を持つ行だけが
    素材なので、点(``end IS NULL``)はここに来ない。"""
    return [{"start": float(row["start"]), "end": float(row["end"])}
            for row in runtime.storage.list_bookmarks(recording_id)
            if row.get("end") is not None]


async def _short_meta(recording: dict, segments: list, item: dict) -> Optional[dict]:
    """範囲1つぶんの題名・説明・hashtag・表紙位置。cacheが効く。

    modelが変わればcacheは外れる(save_ai_analysisのkeyにmodel名とprompt版が入る)。ここで
    確かめるのは入力指紋の一致だけで、判定そのものは既存のcache機構と同じ約束に従う。
    """
    target_id = ai_analysis.clip_target_id(recording["id"], item["start"], item["end"])
    lines = ai_analysis.clip_lines(segments, item["start"], item["end"])
    signature = ai_analysis.input_signature(
        {"lines": [line["text"] for line in lines], "streamer": recording["unique_id"]})
    cached = runtime.storage.get_ai_analysis(
        ai_analysis.KIND_CLIP_META, ai_analysis.TARGET_CLIP, target_id)
    if (cached and cached.get("payload")
            and cached["input_signature"] == signature
            and cached["model"] == ai_analysis.get_ai_model()
            and cached["prompt_version"] == ai_analysis.CLIP_META_PROMPT_VERSION):
        return cached["payload"]
    payload = await ai_analysis.analyze_clip_meta(
        segments, item["start"], item["end"],
        {"streamer": recording["unique_id"], "reason": item.get("label") or ""})
    await asyncio.to_thread(
        runtime.storage.save_ai_analysis,
        ai_analysis.KIND_CLIP_META, ai_analysis.TARGET_CLIP, target_id,
        session_id=recording.get("session_id"), model=ai_analysis.get_ai_model(),
        prompt_version=ai_analysis.CLIP_META_PROMPT_VERSION,
        input_signature=signature, payload=payload)
    return payload


async def _plan_short_ranges(recording_id: int, path: Path, preset: dict,
                             params: dict) -> dict:
    """候補から範囲を確定する。範囲を明示指定されていればそれをそのまま使う。"""
    duration = await _duration_seconds(path)
    if duration is None:
        raise HTTPException(status_code=409, detail="録画の尺を測れないため範囲を決められません。")
    boundaries = await asyncio.to_thread(
        _short_boundaries, recording_id, path, duration)
    if params.get("ranges"):
        # 人が選んだ範囲。吸着も章の挟み込みも掛けない — 選んだ位置を動かさないのが
        # 手で指定するということの意味である。
        ranges = [{"start": float(item["start"]), "end": float(item["end"]),
                   "seconds": round(float(item["end"]) - float(item["start"]), 3),
                   "label": item.get("label") or "", "manual": True}
                  for item in params["ranges"]]
        return {"ranges": ranges, "rejected": [], **boundaries}
    found = await api_candidates.compute_clip_candidates(recording_id)
    silences: list = []
    if int(preset["snap_silence"]):
        try:
            silences = silence_spans(await ensure_audio_profile(path))
        except RuntimeError as exc:
            # 無音が測れないなら、その吸着だけが使えない。発話境界の吸着は残るので、
            # 範囲確定そのものは続けられる(何が使えなかったかはlogに残す)。
            runtime.logger.warning(
                "shortの範囲確定: 無音を測れないため無音への吸着を使いません（recording=%s）",
                recording_id, exc_info=True,
                extra={"event": "short.silence_unavailable",
                       "ctx": {"recording_id": recording_id, "error": str(exc)}})
    taken = await asyncio.to_thread(_short_taken_ranges, recording_id)
    limit = int(params.get("limit") or config.get_short_batch_limit())
    plan = clip_range.plan_ranges(
        found["candidates"], preset, duration=duration,
        segments=boundaries["segments"], silences=silences,
        chapters=boundaries["chapters"], limit=limit, taken=taken)
    for item in plan["ranges"]:
        item["label"] = (item.get("candidate") or {}).get("label") or ""
        item["manual"] = False
    return {**plan, **boundaries, "candidate_count": len(found["candidates"])}


def _write_short_sidecar(result: dict, meta: Optional[dict], recording: dict) -> str:
    """成果物の隣へ、題名・説明・hashtag・検品結果を書く。

    投稿するときに必要なものが1箇所に揃っていること、そして**検品に落ちた事実が成果物に
    貼り付いていること**が目的である。落ちたshortはfileとして残るので、印がfileの側に無いと
    どれが不合格だったのか分からなくなる。
    """
    path = short_media.sidecar_path(Path(result["path"]))
    payload = {
        "filename": result["filename"],
        "recording_id": recording["id"],
        "streamer": recording["unique_id"],
        "start_seconds": result["start"],
        "end_seconds": result["end"],
        "duration_seconds": result.get("output_duration_seconds"),
        "preset": {"id": result.get("preset_id"), "name": result.get("preset_name")},
        "title": (meta or {}).get("title") or "",
        "description": (meta or {}).get("description") or "",
        "hashtags": (meta or {}).get("hashtags") or [],
        "cover": result.get("cover"),
        "steps": result.get("steps") or [],
        "gate": {"ok": result["gate"]["ok"], "failures": result["gate"]["failures"]},
    }
    # 人が開いて読み、そのまま投稿欄へ貼るfileなので整形して書く(1行JSONにしない)。
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


async def _overlay_material(recording: dict, preset: dict) -> dict:
    """1つの録画から、焼き込みに渡す材料(設定・捕捉窓・event・battle・文字起こし)を集める。

    **録画単位で1回だけ集める。** 作品(work)は同じ録画から複数のシーンを採ることが多く、
    シーンごとに集めると3時間ぶんのevent読み出しをその回数だけ繰り返すことになる。
    """
    settings = short_media.ShortSettings(runtime.settings, preset)
    if recording.get("session_id") is None:
        raise HTTPException(
            status_code=409,
            detail="この録画にはSessionが紐づいておらず、焼き込むeventがありません。")
    transcript = await asyncio.to_thread(
        _subtitle_transcript, int(recording["id"]), settings)
    events = await asyncio.to_thread(
        runtime.storage.iter_events, recording["session_id"],
        recording["started_at"], recording.get("ended_at"))
    battles = await asyncio.to_thread(
        runtime.storage.battles_for_session, recording["session_id"])
    return {"settings": runtime.settings, "started_at": recording["started_at"],
            "ended_at": recording.get("ended_at"), "events": events,
            "battles": battles, "transcript": transcript}


async def _run_work_job(job: dict, report) -> dict:
    """グループ1件を作品1本にする。

    シーンの並びは ``bookmarks.position`` そのもの(=人が決めた書き出し順)で、ここでは
    並べ替えない。時刻順へ整えると、並びを決めた操作が無かったことになる。

    範囲を持たない見どころ(点)は素材にならないので外す。**黙って落とさず件数で名乗る** —
    グループに5件と数えたものが4シーンで出て、消えた1件の理由がどこにも無いのは事故である。

    1シーンの失敗で作品全体を失敗させる。shortの一括生成と違うのは、あちらが「N本のうち
    1本が落ちても残りは手に入る」のに対し、作品は**1本の成果物**だからである — 3シーン目が
    落ちた作品を「出来た」として渡す先が無い。
    """
    params = job.get("params") or {}
    group_id = int(params["group_id"])
    group = await asyncio.to_thread(runtime.storage.get_group, group_id)
    if group is None:
        raise JobSkipped("グループが見つかりません（削除済み）。")
    preset = await asyncio.to_thread(_short_preset, params)
    members = await asyncio.to_thread(runtime.storage.bookmarks_in_group, group_id)
    cuts = [row for row in members if row.get("end") is not None]
    if not cuts:
        raise JobSkipped(f"グループ「{group['name']}」に尺のある見どころが1件もありません。")
    skipped_points = len(members) - len(cuts)

    await report("素材を確かめています", 1)
    wants_overlay = short_media.draws_anything(preset)
    materials: dict = {}
    scenes = []
    for index, cut in enumerate(cuts):
        recording_id = int(cut["recording_id"])
        with _input_precondition():
            recording, path = _recording_for_output(recording_id)
        if wants_overlay and recording_id not in materials:
            materials[recording_id] = await _overlay_material(recording, preset)
        scenes.append({"src": path, "start": float(cut["start"]), "end": float(cut["end"]),
                       "label": cut["memo"] or "",
                       "overlay": materials.get(recording_id)})
        if index == 0:
            first_recording_id, first_stem = recording_id, path.stem

    try:
        async with runtime._job_ops("work", first_recording_id, stem=first_stem,
                                    job_registry_id=job["job_id"],
                                    group=group["name"], scenes=len(scenes)):
            result = await work_media.make_work(
                scenes, preset=preset, label=group["name"], on_progress=report)
    except NothingToDrawError as exc:  # 字幕の前提不成立(subclass)も含む
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # 使ったシーンに「書き出した」印を付ける。作品のfileはDBに行を持たないので、次に同じ
    # グループを見たときに何が出済みかを言えるのはこの列だけである。
    for cut in cuts:
        await asyncio.to_thread(
            runtime.storage.mark_bookmark_exported, int(cut["id"]), result["path"])
    return {
        "recording_id": first_recording_id,
        "group_id": group_id,
        "group": group["name"],
        "skipped_points": skipped_points,
        "filename": result["filename"],
        "output_path": result["path"],
        "bytes": result["bytes"],
        "scenes": result["scenes"],
        "requested_seconds": result["requested_seconds"],
        "tightened_seconds": result["tightened_seconds"],
        "output_duration_seconds": result["output_duration_seconds"],
        "preset_name": result["preset_name"],
        "gate_ok": result["gate"]["ok"],
        "gate_failures": [f["label"] for f in result["gate"]["failures"]],
    }


async def _run_short_job(job: dict, report) -> dict:
    """1録画から short を最大N本まで作る。

    候補の算出 -> 範囲の確定 -> 生成 -> 検品 -> metadata の書き出し、までを1 jobで通す。
    **1本の失敗で全体を止めない**: 検品に落ちた成果物はそのまま残し、結果へ理由を載せる。
    残りの範囲を作らずに終わると、落ちた1本を直すまで何も手に入らない。
    """
    recording_id = job["recording_id"]
    params = job.get("params") or {}
    preset = await asyncio.to_thread(_short_preset, params)
    recording, path = _recording_for_output(recording_id)
    want_ai = bool(params.get("ai"))
    if want_ai and not ai_analysis.ai_status()["configured"]:
        # 途中で気付くと、題名の無いshortが何本か出来た後で止まることになる。
        raise HTTPException(
            status_code=409,
            detail="題名の自動生成が指定されていますが、AIが未設定です。設定を確認してください。")

    await report("見どころを探しています", 2)
    plan = await _plan_short_ranges(recording_id, path, preset, params)
    ranges = plan["ranges"]
    if not ranges:
        raise JobSkipped(
            "この録画からは、型の条件を満たす範囲が1つも取れませんでした"
            f"（候補 {plan.get('candidate_count', 0)}件）。")

    overlay = (await _overlay_material(recording, preset)
               if short_media.draws_anything(preset) else None)

    total = len(ranges)
    made: list = []
    failed: list = []
    for index, item in enumerate(ranges):
        cancel.check_cancelled()
        base = int(index * 100 / total)
        span = int(100 / total)

        async def _step(stage: str, pct: int, _base=base, _span=span,
                        _index=index) -> None:
            # 件数は括弧に入れる。段階名に混ぜるとN本ぶんの別々の段階として履歴に並ぶ
            # (media_queue.stage_phase が括弧の中を落とす)。
            await report(f"{stage}（{_index + 1} / {total}本）",
                         min(100, _base + int(pct * _span / 100)))

        meta = None
        if want_ai:
            await _step("題名を作成中", 0)
            try:
                meta = await _short_meta(recording, plan["segments"], item)
            except ai_analysis.AIError as exc:
                # 題名が付かないことは成果物の欠陥ではない。生成は続け、理由を残す。
                runtime.logger.warning(
                    "shortの題名を作成できませんでした（recording=%s %.1f-%.1f）: %s",
                    recording_id, item["start"], item["end"], exc,
                    extra={"event": "short.meta_failed",
                           "ctx": {"recording_id": recording_id, "start": item["start"],
                                   "end": item["end"], "error": str(exc)}})
        label = (meta or {}).get("title") or item.get("label") or ""
        subtitle_lines = len(ai_analysis.clip_lines(
            plan["segments"], item["start"], item["end"]))
        try:
            async with runtime._job_ops("short", recording_id, stem=path.stem,
                                job_registry_id=job["job_id"],
                                start=item["start"], end=item["end"],
                                preset=preset["name"]):
                result = await short_media.make_short(
                    path, start=item["start"], end=item["end"], preset=preset,
                    label=label, overlay=overlay,
                    cover_seconds=(meta or {}).get("cover_seconds"),
                    subtitle_lines=subtitle_lines, on_progress=_step)
        except NothingToDrawError as exc:
            # 焼く物が無い範囲。成果物は出来ないが、他の範囲は作れる。
            failed.append({"start": item["start"], "end": item["end"],
                           "error": str(exc)})
            continue
        except RuntimeError as exc:
            failed.append({"start": item["start"], "end": item["end"],
                           "error": str(exc)})
            runtime.logger.warning(
                "shortの生成に失敗しました（recording=%s %.1f-%.1f）: %s",
                recording_id, item["start"], item["end"], exc, exc_info=True,
                extra={"event": "short.failed",
                       "ctx": {"recording_id": recording_id, "start": item["start"],
                               "end": item["end"]}})
            continue
        sidecar = await asyncio.to_thread(
            _write_short_sidecar, result, meta, recording)
        # 作った範囲を台帳へ残す。次に同じ録画で走らせたとき、同じ場面をもう一度出さない
        # ための唯一の手掛かりである(成果物のfileはDBに行を持たない)。
        await asyncio.to_thread(_record_short_cut, recording, item, result, label)
        made.append({**{k: v for k, v in result.items() if k != "gate"},
                     "sidecar_path": sidecar,
                     "title": (meta or {}).get("title") or "",
                     "gate_ok": result["gate"]["ok"],
                     "gate_failures": [f["code"] for f in result["gate"]["failures"]]})

    passed = [item for item in made if item["gate_ok"]]
    return {
        "recording_id": recording_id,
        "preset_id": preset["id"],
        "preset_name": preset["name"],
        "count": len(made),
        "passed": len(passed),
        "rejected_ranges": len(plan.get("rejected") or []),
        "failed": failed,
        "files": [item["filename"] for item in made],
        "paths": [item["path"] for item in made],
        "output_dir": str(Path(made[0]["path"]).parent) if made else "",
        "filename": made[0]["filename"] if len(made) == 1 else "",
        "output_path": made[0]["path"] if len(made) == 1 else "",
        "bytes": sum(item["bytes"] for item in made),
        "shorts": made,
    }


def _record_short_cut(recording: dict, item: dict, result: dict, label: str) -> None:
    """作ったshortを見どころとして1行残し、書き出し済みとして印を付ける。

    同じ範囲の行が既に在れば**新しい行を作らず、その行を書き出し済みにする**。同じ場面を
    二度出さないための ``taken`` は範囲を決める時に一度読むだけなので、同じ録画へshortの
    jobが重なると双方が空の台帳を見て同じ場面を作る。台帳へ書くこの1箇所が最後の関門で、
    ここを通さないと同じ範囲の行が何本も並び、行だけを読んでも区別が付かなくなる。

    新しく作る行は ``origin='auto'``(機械が決めた範囲)で入る。人が付けた見どころと混ぜて
    一覧へ並べると、自分が付けた覚えの無い行が画面を埋めるためで、画面は既定でこれを出さない。

    書き戻しに失敗してもmp4は出来ているので、shortそのものは失敗にしない(clip一括書き出しと
    同じ扱い)。"""
    try:
        cut = runtime.storage.add_bookmark_if_absent(
            recording["id"], recording["unique_id"], result["start"], result["end"],
            memo=label, origin="auto")
        runtime.storage.mark_bookmark_exported(cut["id"], result["path"])
    except Exception:
        runtime.logger.warning(
            "shortの台帳への記録に失敗しました（recording=%s %.1f-%.1f）",
            recording["id"], result["start"], result["end"], exc_info=True,
            extra={"event": "short.cut_record_failed",
                   "ctx": {"recording_id": recording["id"], "path": result["path"]}})


async def _run_sidecar_cache_job(kind: str, recording_id: int, report) -> dict:
    """再生画面が使うsidecar cache(音声波形 / サムネsprite / 無音skipの解析)を先に作っておくjob。

    どれも「無ければ最初に開いた人がその場で待つ」種類の生成物で、実測3.9時間の録画で
    波形が90秒級、spriteは映像をdecodeするぶんさらにかかる(声の解析は40〜84分の録画で
    6〜13秒)。作る中身も置き場も再生画面から呼ぶ経路と同一(ensure_waveform / ensure_sprite /
    ensure_voice_profile)で、ここでやっているのは呼ぶ時期を人より前へ倒すことだけ —
    別の作り方は持たない。

    進捗は段階だけを返す。生成側はffmpegを1本回して終わりでframe単位のcallbackを持たない。
    持っていない進捗を%として作れば、それは動いているように見えるだけの嘘になる。
    """
    recording = runtime.storage.get_recording(recording_id)
    if recording is None:
        raise JobSkipped("録画が見つかりません（削除済み）。")
    # 判定は素材(.ts)まで含める。mp4の有無で断ると、mp4を作らない今の録画が全部対象外になる。
    if not api_files._recording_source_exists(recording):
        raise JobSkipped("録画fileが存在しません。")
    path = api_files._resolved_recording_path(recording)
    await report(f"{MEDIA_JOB_TITLES[kind]}を生成中…", 0)
    try:
        if kind == "waveform":
            result = await ensure_waveform(path)
            # 表示用波形と絶対levelは1回のdecodeから両方作られ、両方cacheされる
            # (waveform._build)。この呼び出しは通常そのcacheの確認で終わる。
            await ensure_audio_profile(path)
            detail = {"buckets": result["buckets"],
                      "duration_seconds": result["duration_seconds"]}
        elif kind == "voice":
            # 声確率(0.1秒刻みの生確率)。無音skipと無言の早送りが同じsidecarを読む。
            profile = await voice.ensure_voice_profile(path)
            detail = {"points": len(profile.get("probs") or []),
                      "duration_seconds": profile.get("duration_seconds")}
        else:
            grid = await ensure_sprite(path)
            detail = {"columns": grid["columns"], "rows": grid["rows"],
                      "interval_seconds": grid["interval_seconds"]}
    except hls_source.SourceMissing as exc:
        raise JobSkipped(str(exc)) from exc
    except RuntimeError as exc:
        # voice.VoiceErrorもRuntimeError。ここで500へ寄せるのは、再実行で直る種類の失敗
        # (ffmpegが起動できない・modelが読めない)だからで、対象なしとは区別する。
        raise HTTPException(status_code=500, detail=str(exc))
    await report("完了", 100)
    return {"recording_id": recording_id, "kind": kind, **detail}


async def _run_still_job(job: dict, report) -> dict:
    """再生位置の1 frameをpngで残す。GPUもdiskもほとんど使わないが、台帳に載せるのは
    「押した後の結末(出力先・失敗の理由)」が他の成果物と同じ場所に出るようにするため。"""
    recording_id = job["recording_id"]
    params = job.get("params") or {}
    at = float(params.get("at") or 0.0)
    variant = params.get("variant") or "source"
    label = params.get("label") or ""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise JobSkipped("録画が見つかりません（削除済み）。")
    with _input_precondition():
        # 素材版が無い録画は404。積み直しても変わらないのでskipへ落ちる。
        src = api_files._clip_source(recording, variant)
    path = api_files._resolved_recording_path(recording)
    suffix = STILL_VARIANT_SUFFIXES.get(variant, "")
    out = still_path(path, at, label, suffix=suffix)
    await report("スクショを保存中", 0)
    try:
        async with runtime._job_ops("still", recording_id, stem=path.stem,
                                    variant=variant, at=round(at, 2)):
            result = await capture_still(
                src, at, out,
                prefer_hls=(variant == "source" and hls_source.plays_from_hls(path)))
    except hls_source.SourceMissing as exc:
        raise JobSkipped(str(exc) or "素材が見つかりません。")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    # file名は**実際に採れたframeの位置**で付け直す。要求どおりに撮れないことがあり
    # (素材の映像がそこから始まっていない等)、そのとき要求値のまま名乗ると、名前だけを
    # 見て中身を取り違える。
    final = still_path(path, result["at_seconds"], label, suffix=suffix)
    if final != out:
        out.replace(final)
    await report("完了", 100)
    return {"recording_id": recording_id, "filename": final.name,
            "output_path": str(final), "output_dir": str(final.parent),
            "bytes": result["bytes"], "at_seconds": result["at_seconds"],
            "requested_seconds": result["requested_seconds"],
            "variant": variant, "label": label}


@contextmanager
def _input_precondition():
    """job runner内で、入力側の前提不成立(404)を失敗ではなくskipへ落とす。

    録画行やfileが無いのは待っても変わらないので、media_queueのretryでbackoffを消費してから
    赤いfailedとして残すのは誤り。取り消しと同じ「正常な終わり方」へ畳む。"""
    try:
        yield
    except HTTPException as exc:
        if exc.status_code == 404:
            raise JobSkipped(str(exc.detail)) from exc
        raise


def _split_report(report, lo: int, hi: int):
    """report(stage, pct) の%を [lo, hi] の帯へ写す。

    1つのjobが2本の長い処理を順に走らせる場合(高画質化 = 焼き込み→超解像)、両方を同じ
    0-100へ流すと%が一度100近くまで行って0へ戻る。単体行はstage名で区別が付くが、
    group行のbarはmemberの%の合算なので、**目に見えて逆走する**。"""
    async def _scaled(stage: str, pct: int) -> None:
        await report(stage, lo + int(max(0, min(100, pct)) * (hi - lo) / 100))
    return _scaled


async def _run_media_job(job: dict, report) -> dict:
    """queueが1件を実行する本体。stage進捗は report(stage, pct) でqueueへ返す。"""
    kind = job["kind"]
    recording_id = job["recording_id"]
    job_id = job["job_id"]
    if kind in ("reprocess", "audionorm"):
        recording = runtime.storage.get_recording(recording_id)
        if recording is None:
            raise JobSkipped("録画が見つかりません（削除済み）。")
        with _input_precondition():
            if kind == "reprocess":
                return await _reprocess_recording(recording_id, recording, job_id, report)
            return await _audionorm_recording(recording_id, recording, job_id, report)
    if kind == "pack":
        recording = runtime.storage.get_recording(recording_id)
        if recording is None:
            raise JobSkipped("録画が見つかりません（削除済み）。")
        with _input_precondition():
            return await _pack_recording(recording_id, recording, report)
    if kind in ("waveform", "sprite", "voice"):
        return await _run_sidecar_cache_job(kind, recording_id, report)
    if kind == "stt":
        return await _run_stt_job(recording_id, report, job.get("params"))
    if kind == "laugh":
        return await _run_laugh_job(recording_id, report)
    if kind == "overlay_preview":
        return await _run_preview_clip_job(recording_id, report)
    if kind == "clip_batch":
        return await _run_clip_batch_job(job, report)
    if kind == "reel":
        return await _run_reel_job(job, report)
    if kind == "clip_overlay":
        return await _run_clip_overlay_job(job, report)
    if kind == "short":
        return await _run_short_job(job, report)
    if kind == "work":
        return await _run_work_job(job, report)
    if kind == "still":
        return await _run_still_job(job, report)
    if kind not in ("overlay", "upscale"):
        raise HTTPException(status_code=400, detail=f"未知のjob種別です: {kind}")
    with _input_precondition():
        recording, path = _recording_for_output(recording_id)
    # 焼き込みは元に戻せない成果物なので、入力が「差し替え待ちの混在解像度mp4」でないことを
    # ここで確かめる。正規化の再encodeは終わっているのに差し替えだけがlockで失敗していた場合、
    # 素通りさせると混在解像度のまま焼き込んでしまい、出力も同じくカクつく。この時点では
    # lockは大抵解けている(録画finalizeから時間が経っている)。
    if await reclaim_normalized_mp4(path) == "reclaimed":
        runtime.storage.update_recording_bytes(recording_id, path.stat().st_size)
    # 高画質化は焼き込みの後に超解像が続く2段構成。持ち分を半分ずつに切る。
    burn_report = _split_report(report, 0, 50) if kind == "upscale" else report
    result = await _burn_in_recording(recording, path, job_id, burn_report)
    rendered, payload = _overlay_payload(result, path)
    payload.update({
        "recording_id": recording_id,
        "filename": rendered.name,
        "output_path": str(rendered),
        "rendered": rendered != path,
    })
    if kind == "upscale":
        out = await _upscale_rendered(rendered, recording_id, job_id,
                                      _split_report(report, 50, 100))
        payload.update({"filename": out.name, "output_path": str(out),
                        "source": rendered.name})
    return payload


# 作り直したmp4が素材(.ts)の何割を含んでいれば完成と見なすか。実測では正常な作り直しは
# playlistの合計尺に対し 100.0-100.2% で一致する(旧mp4側が幻の音声穴で伸びているだけで、
# 素材と成果物はズレない)。途中で切れた例は 20% / 24% だった。
_REPROCESS_MIN_COVERAGE = 0.95


async def _sweep_backups(stem: str, current: Path) -> dict:
    """差し替えが完走した録画の退避を掃く。

    退避は失敗を巻き戻すためのもので、成功が確かめられた時点で役目を終える。消す経路が
    どこにも無かったため、成功1回につき元mp4が1本ずつ永久に残っていた(実測84本 304GB、
    その91%が1世代目 = 繰り返し実行ではなく単に誰も消していないぶん)。掃除に失敗しても
    jobは成功のまま返す — 退避が1本残ることは、作り直した成果を失敗として畳む理由にならない。"""
    keep_days = runtime.settings.get("backup_keep_days")
    try:
        return await backups.sweep_recording_backups(
            stem, current, runtime._RECORD_ROOTS, float(keep_days or 0) * 86400.0, time.time())
    except Exception:
        runtime.logger.exception(
            "%s の退避fileを整理できません", stem,
            extra={"event": "backup.sweep_failed", "ctx": {"stem": stem}},
        )
        return {"deleted": 0, "bytes": 0, "kept": {}}


def _hls_media_seconds(hls_dir: Path) -> Optional[float]:
    """HLS playlistのEXTINF合計 = この録画の素材が持つ実尺。読めなければNone。"""
    playlist = hls_dir / "index.m3u8"
    try:
        text = playlist.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    total = 0.0
    for line in text.splitlines():
        if not line.startswith("#EXTINF:"):
            continue
        try:
            total += float(line[len("#EXTINF:"):].split(",", 1)[0])
        except ValueError:
            continue
    return total or None


def _current_recording_mp4(recording: dict, stem: str) -> Path | None:
    """この録画の現在のmp4。DB行が指す実fileを最優先し、行が古い(手動で動かした)場合に
    備えてlayout上のpathも両rootで探す。旧命名(flat)の録画は行のpathでしか辿れず、
    layoutだけで探すと現物を見落とす。"""
    return api_files._existing_recording_file(recording) or api_files._existing_recording_mp4(stem)


def _recording_home_root(recording: dict, stem: str) -> Path:
    """この録画のmp4が住む record root。作り直した結果を書き戻す先。

    基準は**mp4の現在地**であって.tsの在り処ではない。両者は別rootになり得る:
    1次(work)で録画したmp4は完了時に2次(final)へ移送され得るが、.tsは1次に残る。
    .ts側を基準にすると、2次に置いた録画が再mp4化の
    たびに1次へ引っ越し(退避も1次の_backupへ落ち)、録画中の書き込み先である1次を
    黙って食い潰す。

    決め方は上から順に、実在のmp4(``_current_recording_mp4``) → 行が指していたroot
    (fileは消えている) → 完成mp4の既定の置き場である FINAL_DIR。"""
    current = _current_recording_mp4(recording, stem)
    if current is not None:
        return layout.record_root_of(current)
    try:
        stale = api_files._safe_recording_path(recording.get("path") or "")
    except HTTPException:
        stale = None
    # 録画dirを指したままの行(finalize途中で落ちた録画)はmp4ではないので、rootを引けない。
    if stale is not None and stale.suffix.lower() == ".mp4":
        return layout.record_root_of(stale)
    return runtime.FINAL_DIR


async def _reprocess_recording(recording_id: int, recording: dict, job_id: str,
                               on_stage_pct) -> dict:
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のため再mp4化できません。")
    if not (ffmpeg_available() and ffprobe_available()):
        raise HTTPException(status_code=503, detail="ffmpeg/ffprobeが利用できません。")
    stem = Path(recording.get("filename") or recording.get("path") or "").stem
    if not stem:
        raise HTTPException(status_code=400, detail="録画の識別子が不正です。")
    hls_root = api_files._find_hls_root(stem)
    if hls_root is None:
        raise HTTPException(
            status_code=409,
            detail="元の.tsセグメントが見つかりません（このファイルは再mp4化できません）。",
        )
    # 読む先(.ts)と書く先(mp4)は別rootであり得る。書く先はmp4の現在地に合わせる。
    home_root = _recording_home_root(recording, stem)
    final_mp4 = layout.mp4_path(home_root, stem)

    # Back up the current mp4 before finalize overwrites <stem>.mp4; keep it on success,
    # restore it if the re-finalize fails so the recording is never left without a file.
    backup_path: Path | None = None
    existing = _current_recording_mp4(recording, stem)
    if existing is not None:
        # 退避も出力と同じroot(=元mp4が居たroot)。音量正規化の退避先と同じ決め方で、
        # 「元のmp4はどこか」の答えが操作によって変わらないようにする。
        backup_dir = home_root / "_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{stem}.mp4"
        n = 1
        while backup_path.exists():
            backup_path = backup_dir / f"{stem}.{n}.mp4"
            n += 1
        # 退避先はmoveの「前」に記録する。moveの直後に落ちた場合、job行に退避先が無ければ
        # 起動時のrecoveryはmp4の在り処を知る手段が無く、録画がfileの無い状態で残る。
        runtime.storage.set_media_job_result(
            job_id, {"backup_path": str(backup_path), "final_path": str(final_mp4)})
        await asyncio.to_thread(shutil.move, str(existing), str(backup_path))

    async def _restore_backup() -> None:
        """押す前の状態へ戻す。**書きかけのmp4を先に捨ててから**戻すこと。

        ffmpegは走り出した瞬間に出力fileを作るので、失敗時にはほぼ必ず断片が残っている。
        「最終mp4が無いときだけ戻す」条件だけで守ると、その断片のせいで復元が素通りし、
        録画は断片を指したまま・原本は_backupに置き去りになる(実測: 3時間30分の録画が
        117MBのmoov無しfileに、62分が12分に置き換わった)。"""
        if backup_path is None:
            return
        final_mp4.unlink(missing_ok=True)
        if backup_path.is_file():
            await asyncio.to_thread(shutil.move, str(backup_path), str(final_mp4))

    async def _emit_progress(pct: int, stage: str) -> None:
        await runtime.hub.broadcast(
            {"type": "reprocess_progress", "recording_id": recording_id,
             "pct": pct, "stage": stage}
        )
        await on_stage_pct(stage, pct)

    progress = JobProgress(_emit_progress, REPROCESS_PHASES)
    await _emit_progress(0, "再mp4化の準備中")
    # 結合passはどのみち音声をAACへ再encodeするので、正規化を足しても追加passは要らない。
    # 設定がOFFなら素の音量で作り直すため、DBの「正規化済み」も後で必ず外す。
    normalize = _reprocess_normalize()
    # record_dir は.tsを読むroot、final_dir は書き戻すroot。final_dirを渡すのは、
    # 空き容量の記録に出力先のvolumeを含めるため。
    recorder = Recorder(
        recording.get("unique_id") or stem, str(hls_root),
        recording.get("session_id"), final_dir=str(home_root),
        storage=runtime.storage, normalize_audio=normalize,
    )
    try:
        # 明示的な「mp4化」なので、ここだけ結合passを走らせる。通常のfinalizeと復旧は
        # mp4を作らない(録画の実体は .ts で、焼き込みも下流もそちらを読む)。
        await recorder.finalize_recovered_hls(stem, progress=progress, mp4_root=home_root,
                                              build_mp4=True)
    except cancel.JobCancelled:
        # 取り消し: 書きかけのmp4を捨て、退避しておいた元のmp4を必ず戻す(押す前の状態)。
        # ここを通さないと、録画がfileの無い状態で残る。JobCancelledはBaseException
        # なので下のexcept Exceptionでは捕まらない。明示的に先へ置くこと。
        final_mp4.unlink(missing_ok=True)
        await _restore_backup()
        runtime.logger.info(
            "recording %s の再mp4化を取り消し、元のmp4を復元しました", recording_id,
            extra={"event": "reprocess.cancelled",
                   "ctx": {"recording_id": recording_id, "stem": stem,
                           "restored": backup_path is not None}},
        )
        raise
    except Exception as exc:
        runtime.logger.exception("recording %s の再mp4化に失敗しました", recording_id)
        await _restore_backup()
        raise HTTPException(status_code=500, detail=f"再mp4化に失敗しました: {exc}")

    await progress.finish("生成したmp4を確認中")
    snap = recorder.snapshot()
    out = recorder.output_path
    if out is None or not Path(out).is_file() or snap.get("bytes", 0) <= 0 \
            or recorder.state != "completed":
        await _restore_backup()
        raise HTTPException(
            status_code=500,
            detail="再mp4化が有効なmp4を生成できませんでした（元ファイルは復元しました）。",
        )
    # 出来たmp4が元の.tsを最後まで含んでいるか。recorderの検証は「video streamが1本ある」
    # までしか見ないので、途中で切れた結合も合格してしまう(実測: 62分の録画が12分のmp4に
    # 置き換わり、completedとして畳まれた)。尺の出所はplaylistのEXTINF合計 = 素材そのもの。
    source_seconds = await asyncio.to_thread(
        _hls_media_seconds, layout.session_dir(hls_root, stem))
    produced_seconds = await _duration_seconds(Path(out))
    if source_seconds and produced_seconds and \
            produced_seconds < source_seconds * _REPROCESS_MIN_COVERAGE:
        runtime.logger.error(
            "recording %s の再mp4化が途中までのmp4しか作れませんでした（%.0fs / %.0fs）",
            recording_id, produced_seconds, source_seconds,
            extra={"event": "reprocess.incomplete",
                   "ctx": {"recording_id": recording_id, "stem": stem,
                           "produced_seconds": round(produced_seconds, 1),
                           "source_seconds": round(source_seconds, 1),
                           "path": str(out)}},
        )
        await _restore_backup()
        raise HTTPException(
            status_code=500,
            detail="再mp4化が元の.tsの途中までしか作れませんでした"
                   f"（{produced_seconds / 60:.0f}分 / {source_seconds / 60:.0f}分）。"
                   "元ファイルは復元しました。",
        )
    # The regenerated mp4's path can differ from the (possibly stale) DB value, so update it.
    # ended_atは書き換えない。作り直しは中身を作り直すだけで、捕捉が終わった時刻を動かさない
    # (かつてrecorder.ended_at=作り直した時刻を書き込んでいたため、DBの尺が「録画開始〜再処理
    # 時刻」に化けていた)。尺の出所は測ったproduced_secondsで、これはrecording窓としてeventの
    # 絞り込みにも使われるended_atとは別物である。
    ended_at_if_missing = (
        recording["started_at"] + produced_seconds
        if recording.get("started_at") and produced_seconds else None
    )
    runtime.storage.update_rebuilt_recording(
        recording_id, recorder.state, str(out), Path(out).name,
        snap["bytes"], recorder.error,
        duration_seconds=produced_seconds, ended_at_if_missing=ended_at_if_missing,
    )
    # 中身は.tsから作り直された別のmp4なので、正規化の状態も作り直した内容に合わせる。
    # 正規化せずに作り直したのに以前の「済み」が残ると、一括画面がその録画を対象から外す。
    runtime.storage.set_recording_audio_normalized(
        recording_id, time.time() if normalize else None,
        normalize["target_lufs"] if normalize else None)
    # 作り直し済みの印。一括投入はこの列を見て対象から外す(「処理済みも作り直す」で戻せる)。
    # 印を付けるのは完走を確かめた後だけ — 失敗したものは次の一括で拾い直させる。
    runtime.storage.set_recording_reprocessed(recording_id, time.time())
    swept = await _sweep_backups(stem, Path(out))
    await _emit_progress(100, "再mp4化が完了しました")
    return {
        "recording_id": recording_id,
        "filename": Path(out).name,
        "output_path": str(out),
        "bytes": snap["bytes"],
        "normalized": bool(normalize),
        # 掃いた後に残っていれば退避先を返す。消したなら None(戻せる先が無いことを、
        # 存在しないpathで示さない)。
        "backup": (str(backup_path)
                   if backup_path is not None and backup_path.is_file() else None),
        "backups_deleted": swept["deleted"],
        "backups_freed_bytes": swept["bytes"],
    }


def _pack_headroom(hls_dir: Path) -> tuple:
    """(束ねるのに要る追加bytes, その volume の空き) 。

    束ねる間は元segmentと束ねたfileが**同時に**存在する(3段の検証を全て通るまで元を消さない)
    ので、必要な空きは素材と同じだけになる。"""
    needed, _files, _mtime = api_files._dir_usage(hls_dir)
    report = disk_free_by_volume([hls_dir])
    free = min((info["free_bytes"] for info in report.values()), default=0)
    return needed, free


async def _pack_recording(recording_id: int, recording: dict, report) -> dict:
    """ts結合jobの本体。実処理は hls_pack.pack_session で、ここは前提の確認と進捗の橋渡し。

    失敗しても元は一切触られない(束ねたfileを捨てて元segmentをそのまま残す)ので、復旧手順は
    無い。理由(``reason``)はそのままjobのerrorとして出す — 「束ねられなかった」とだけ出ると、
    容量なのか検証で弾かれたのかが読めない。"""
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のためts結合できません。")
    if not ffprobe_available():
        raise HTTPException(status_code=503, detail="ffprobeが利用できません。")
    dirs = api_files._recording_media_dirs(recording)
    if not dirs:
        raise HTTPException(status_code=409, detail="この録画は.tsが残っていません。")
    hls_dir = dirs[0]
    # 同じ録画を別のjobが掴んでいる間は束ね直さない。再mp4化は素材をplaylist順に読んでいる
    # 最中で、その足元でsegmentを消して名前を変えると読み手が壊れる。待てば解消するので
    # 失敗ではなく保留にする。
    busy = [kind for kind, rid in runtime.storage.pending_media_job_keys()
            if rid == recording_id and kind != "pack"]
    if busy:
        raise JobDeferred(f"この録画は他の処理が使用中です（{', '.join(sorted(set(busy)))}）。")
    if hls_pack.is_packed(hls_dir):
        # 冪等。既に束ねてある録画へ投げても何もせず、束ね直しもしない。
        return {"recording_id": recording_id, "packed": False, "reason": "already_packed",
                "segments": 0, "packs": 0, "freed_bytes": 0}
    needed, free = await asyncio.to_thread(_pack_headroom, hls_dir)
    floor = disk._disk_min_free_bytes()
    if free - needed < floor:
        raise HTTPException(
            status_code=507,
            detail=(f"ts結合には素材と同じだけの空きが要ります（必要 {needed / 1024 ** 3:.1f}GB / "
                    f"空き {free / 1024 ** 3:.1f}GB / 下限 {floor / 1024 ** 3:.0f}GB）。"
                    "元segmentは検証を全て通るまで消さないため、一時的に2本分の容量を使います。"),
        )

    # JobProgressのsinkは(pct, stage)、queueのreportは(stage, pct)。順序を合わせる。
    async def _emit_progress(pct: int, stage: str) -> None:
        await report(stage, pct)

    progress = JobProgress(_emit_progress, PACK_PHASES)

    async def _on_progress(key: str, frac: float, detail: Optional[str] = None) -> None:
        # 取り消しはここでも効かせる(pack_sessionはtokenを持たない)。commit段階に入った後は
        # 受けない: 元segmentを消し始めた後で止めると、完了した作業を取り消し扱いにした上に
        # 束ねたfileと元が半端に同居する。
        if key != "commit":
            cancel.check_cancelled()
        await progress.set(key, frac, detail)

    await report("ts結合の準備中", 0)
    async with runtime._job_ops("pack", recording_id, stem=hls_dir.name, path=str(hls_dir)):
        result = await hls_pack.pack_session(hls_dir, on_progress=_on_progress)
        # 束ねられなかったのは失敗。ops_eventsにも失敗として残す(この判定を外へ出すと、
        # 台帳には完了、jobには失敗という食い違った記録が残る)。
        if not result["packed"] and result["reason"] != "already_packed":
            raise HTTPException(status_code=500,
                                detail=f"ts結合できませんでした: {result['reason']}")
    return {"recording_id": recording_id, "path": str(hls_dir), **result,
            "freed_bytes": result.get("bytes", 0)}


async def _audionorm_recording(recording_id: int, recording: dict, job_id: str,
                               on_stage_pct) -> dict:
    """音量正規化jobの本体。映像はstream copyなので画質も、焼き込みが突き合わせる
    timestampも変わらない(コメントのズレを持ち込まない)。"""
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のため音量正規化できません。")
    if not (ffmpeg_available() and ffprobe_available()):
        raise HTTPException(status_code=503, detail="ffmpeg/ffprobeが利用できません。")
    src = api_files._existing_recording_file(recording)
    if src is None:
        raise HTTPException(status_code=404, detail="録画fileが存在しません（削除済みか録画失敗）。")
    normalize = audio_norm.targets(runtime.settings)

    async def _emit_progress(pct: int, stage: str) -> None:
        await runtime.hub.broadcast({"type": "audionorm_progress", "recording_id": recording_id,
                             "pct": pct, "stage": stage})
        await on_stage_pct(stage, pct)

    await _emit_progress(0, "音量正規化の準備中")
    # loudnormは入力に関わらず192kHzを出すので、sourceの実rateを測って戻す。
    rate = await asyncio.to_thread(audio_norm.probe_sample_rate, src)
    total_seconds = await _duration_seconds(src)
    # 拡張子を.mp4にしないのは、書きかけのtempが録画fileとして拾われるのを防ぐため。
    # 代わりにmuxerを-fで名指しする(拡張子から判別できないため)。
    tmp = Path(str(src) + ".audionorm.tmp")
    tmp.unlink(missing_ok=True)
    args = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-progress", "pipe:1", "-nostats",
        "-i", str(src),
        "-c:v", "copy",
        *audio_norm.encode_args(**normalize, sample_rate=rate),
        "-movflags", "+faststart", "-f", "mp4", str(tmp),
    ]
    async with runtime._job_ops("audionorm", recording_id, stem=src.stem,
                        job_registry_id=job_id, **audio_norm.describe(normalize)):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        cancel.register_process(proc)
        try:
            # stdout(-progress)とstderrは**どちらも必ず最後まで読む**。片方でも放置すると
            # pipe bufferが埋まった時点でffmpegが書き込みで止まり、jobが進捗0%のまま
            # 永久に終わらない。尺が測れず%を出せない場合でも読み捨てだけは続ける。
            stdout = _pipe(proc.stdout, "stdout")
            err_task = asyncio.create_task(_pipe(proc.stderr, "stderr").read())
            if total_seconds:
                async def _report(pct: int, _position: Optional[int]) -> None:
                    await _emit_progress(pct, "音量を正規化中")
                await pump_ffmpeg_progress(stdout, int(total_seconds * 1_000_000),
                                           _report)
            else:
                while await stdout.readline():
                    pass
            err = await err_task
            await proc.wait()
        finally:
            cancel.forget_process(proc)
        if cancel.is_cancelled():
            # killされたffmpegも非0で返る。取り消しをerrorとして残さないため先に判定する。
            tmp.unlink(missing_ok=True)
            cancel.check_cancelled()
        size = tmp.stat().st_size if tmp.is_file() else 0
        if proc.returncode != 0 or size <= 0:
            stderr_text = err.decode("utf-8", "replace")
            tmp.unlink(missing_ok=True)
            runtime.logger.error(
                "recording %s の音量の正規化に失敗しました", recording_id,
                extra={"event": "process.ffmpeg_failed",
                       "ctx": {"stage": "audionorm", "recording_id": recording_id,
                               "path": str(src), "size_bytes": size,
                               **audio_norm.describe(normalize),
                               **ffmpeg_ctx(args, proc.returncode,
                                            stderr_text=stderr_text)}},
            )
            raise HTTPException(status_code=500, detail="音量正規化に失敗しました。")

        # 差し替え: 元mp4を_backup/へ退避してから、正規化済みを元のpathへ置く。退避先は
        # moveの前にjob行へ書く(この間にprocessが落ちると、pathを知る手段が他に無い)。
        # 退避先は再mp4化と同じ record root 直下の _backup/。2つの操作で別の場所へ置くと、
        # 「元のmp4はどこか」の答えが操作によって変わる。
        backup_dir = layout.record_root_of(src) / "_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / src.name
        n = 1
        while backup_path.exists():
            backup_path = backup_dir / f"{src.stem}.{n}.mp4"
            n += 1
        runtime.storage.set_media_job_result(
            job_id, {"backup_path": str(backup_path), "final_path": str(src)})
        await asyncio.to_thread(shutil.move, str(src), str(backup_path))
        try:
            await asyncio.to_thread(shutil.move, str(tmp), str(src))
        except OSError:
            # 差し替えに失敗したら退避を戻す。ここを通さないと録画がfileの無い状態で残る。
            await asyncio.to_thread(shutil.move, str(backup_path), str(src))
            raise

    runtime.storage.update_recording_bytes(recording_id, size)
    runtime.storage.set_recording_audio_normalized(recording_id, time.time(),
                                           normalize["target_lufs"])
    # 映像はstream copyなのでframe数は退避と一致する。ここで一致しなければ差し替えが
    # 壊れているということで、そのときは掃除側が退避を残す。
    swept = await _sweep_backups(src.stem, src)
    await _emit_progress(100, "音量正規化が完了しました")
    runtime.logger.info(
        "recording %s の音量の正規化が完了しました", recording_id,
        extra={"event": "audionorm.completed",
               "ctx": {"recording_id": recording_id, "path": str(src),
                       "size_bytes": size, "backup_path": str(backup_path),
                       "backups_deleted": swept["deleted"],
                       **audio_norm.describe(normalize)}},
    )
    return {
        "recording_id": recording_id,
        "filename": src.name,
        "output_path": str(src),
        "bytes": size,
        "normalized": True,
        "backup": str(backup_path) if backup_path.is_file() else None,
        "backups_deleted": swept["deleted"],
        "backups_freed_bytes": swept["bytes"],
    }


async def _upscale_rendered(rendered: Path, recording_id: int, job_id: str,
                            on_stage_pct) -> Path:
    """Super-resolve an already-rendered video. The stage progress goes to the legacy
    per-recording message and to the job registry, same as the burn-in stage."""
    encoder = await video_encoder_name(codec_family(runtime.settings.get("video_overlay_codec")))
    loop = asyncio.get_running_loop()
    last_pct = -1
    # 超解像は実時間の数十倍かかる段階で、%は1目盛が数分になる。frame位置を添えないと
    # 「動いているか」の確認に使えない。%が動かない間の位置更新は時間で間引く(焼き込みの
    # 段階表示と同じ扱い)。
    gate = IntervalGate(config.get_job_progress_min_interval_seconds())

    def on_progress(done: float, total: float) -> None:
        nonlocal last_pct
        pct = min(100, int(done / total * 100)) if total > 0 else 0
        if pct == last_pct and not gate.ready():
            return
        last_pct = pct
        asyncio.run_coroutine_threadsafe(
            _report_upscale_pct(recording_id, pct, on_stage_pct,
                                detail=f"{int(done):,} / {int(total):,} frame"), loop,
        )

    try:
        async with runtime._job_ops("upscale", recording_id, stem=rendered.stem, encoder=encoder,
                            job_registry_id=job_id):
            out = await asyncio.to_thread(
                ensure_upscaled, str(rendered), encoder,
                int(runtime.settings.get("video_overlay_quality")), on_progress,
                _output_normalize(),
            )
    except UpscaleError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await _report_upscale_pct(recording_id, 100, on_stage_pct)
    return out


async def _report_upscale_pct(recording_id: int, pct: int, on_stage_pct,
                              detail: Optional[str] = None) -> None:
    await runtime.hub.broadcast(
        {"type": "upscale_progress", "recording_id": recording_id, "pct": pct}
    )
    # 詳細は括弧に入れる。段階の履歴はこの括弧を落とした名前で残るので、frame位置が
    # 動くたび「高画質化」が履歴へ積み増されることはない(media_queue.stage_phase)。
    await on_stage_pct(f"高画質化（{detail}）" if detail else "高画質化", pct)


def _session_output_targets(session_id: int) -> list:
    """Recordings of a session that can be output, in the order they were made.

    statusだけで選ぶと、fileが消えた/finalizeが完走しなかった行までqueueへ載り、workerが
    1件ずつ404で落ちる。単体の出力APIは投入時に実体の有無を見て弾いているので、session
    一括でも同じ条件で絞る — 条件は ``_recording_for_output`` と同じく「mp4 or 素材」で
    あって、mp4の有無ではない。mp4だけを見ていた頃は、素材が揃ったsessionが丸ごと
    「録画fileが残っていません」で断られていた(単体の焼き込みは通るのに)。"""
    if runtime.storage.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Sessionが見つかりません。")
    finished = [r for r in runtime.storage.recordings_for_session(session_id)
                if r.get("status") in ("completed", "interrupted")]
    targets = [r for r in finished if api_files._recording_source_exists(r)]
    if not targets:
        raise HTTPException(
            status_code=409,
            detail=("この Session の録画は素材もmp4も残っていません（削除済みか録画失敗）。"
                    if finished else "出力できる録画がありません。"),
        )
    return targets


async def _start_session_output(session_id: int, upscale: bool) -> dict:
    """Session内の録画を1本ずつqueueへ載せる。

    投入は録画ごとの行だが、履歴画面のSession行が見るのは1つの進捗なので、同じ group_id を
    振ってqueue側でsession単位のjobへ畳み直す(media_queue.group_payload)。行を分けるのは、
    再起動しても残りの録画が実行されること・1本だけ取り消せることの2点のためで、どちらも
    session全体を1 jobにすると実現できない。
    """
    targets = _session_output_targets(session_id)
    # 実行はworkerなので、投入時点で下限割れなら即答する(全件がworkerで失敗するより早い)。
    disk._require_disk_space(disk._disk_volume_paths(), "session_output", session_id=session_id)
    # 字幕焼き込みが有効な場合、1本でも文字起こしが欠けていれば Session 全体を止める。半分だけ
    # 字幕付きの出力が並ぶ状態は、どれが字幕付きか後から判別できず運用を壊す。
    if subtitles_enabled(runtime.settings):
        missing = [t for t in targets if runtime.storage.get_transcript(t["id"]) is None]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=(f"字幕の焼き込みが有効ですが、文字起こしが無い録画が{len(missing)}件あります"
                        "（録画 " + "、".join(api_files._recording_label(t) for t in missing[:5])
                        + ("…" if len(missing) > 5 else "")
                        + "）。先にSessionの文字起こしを実行してください。"),
            )
        for target in targets:
            _subtitle_transcript(target["id"])
    kind = "upscale" if upscale else "overlay"
    group_id = secrets.token_hex(4)
    title = ("Session Up出力" if upscale else "Session出力") + f" #{session_prefix(session_id)}"
    queued: list[str] = []
    skipped: list[int] = []
    for target in targets:
        if media_job_queue.pending_for(kind, target["id"]) is not None:
            skipped.append(target["id"])
            continue
        job_id = secrets.token_hex(4)
        await media_job_queue.enqueue(
            job_id, kind, target["id"], session_id=session_id, group_id=group_id,
            title=title,
        )
        queued.append(job_id)
    if not queued:
        raise HTTPException(
            status_code=409,
            detail="この Session の録画はすべて既にqueueにあります（jobで確認できます）。",
        )
    return {"job_id": group_id, "group_id": group_id, "session_id": session_id,
            "total": len(queued), "skipped_recording_ids": skipped,
            "recording_ids": [t["id"] for t in targets]}


CLIP_MODES = ("copy", "smart", "precise")


def _clip_mode(mode: Optional[str], precise: Optional[bool]) -> str:
    """切り出しの方式。``precise`` は保存済みjob paramとの互換のために読み替える。

    既定を ``copy`` のまま据え置くのは、clipper docstringの「素材用途では前後の余白はむしろ
    扱いやすい」という既存の判断を実測なしに覆さないため。設定keyにしてあるので、実運用で
    測ってから code 変更なしで倒せる。
    """
    if mode is None:
        # 旧形式(precise: bool)のjobがqueueに残っている。fallbackではなく保存済みdataの読み替え。
        return "precise" if precise else str(runtime.settings.get("clip_default_mode"))
    if mode not in CLIP_MODES:
        raise HTTPException(status_code=400, detail=f"未知の切り出し方式です: {mode}")
    return mode


def _clip_normalize(requested: Optional[bool]) -> Optional[dict]:
    """切り出しの音量正規化の目標値。Noneなら設定の既定に従う。"""
    enabled = (bool(int(runtime.settings.get("clip_normalize_audio")))
               if requested is None else bool(requested))
    return audio_norm.targets(runtime.settings) if enabled else None


def _clip_remove_bgm(requested: Optional[bool]) -> bool:
    """切り出しでBGM除去を掛けるか。Noneなら設定の既定に従う。

    使えない構成のときは**投入時に弾く**(workerで初めて落とすと、押した人は待った末に
    理由を知ることになる)。既定ONのまま環境が整っていない場合も同じで、黙って掛けずに
    出すことはしない — 名前が ``.nobgm`` を名乗る以上、掛かっていない出力は嘘になる。
    """
    enabled = (bool(int(runtime.settings.get("clip_remove_bgm")))
               if requested is None else bool(requested))
    if not enabled:
        return False
    reason = bgm_remove.unavailable_reason()
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    return True


def _clip_subtitles(requested: Optional[bool]) -> bool:
    """切り出しに字幕file(sidecar)を添えるか。Noneなら設定の既定に従う。"""
    return (clip_subtitles.enabled_by_settings(runtime.settings)
            if requested is None else bool(requested))


async def _attach_clip_subtitles(result: dict, recording_id: int, variant: str) -> dict:
    """出来上がった切り抜きの隣へ字幕fileを置き、結果へ書き加える。

    ここで失敗しても切り出しは失敗にしない — mp4は既に出来ており、それを消す理由が無い
    (見どころへの書き戻しと同じ扱い)。ただし黙って0件にはせず、理由を結果とlogへ
    残す。「出したはずの字幕が無い」を利用者が追える形にしておく。
    """
    try:
        result["subtitles"] = await clip_subtitles.write_for_clip(
            result,
            await asyncio.to_thread(runtime.storage.get_transcript, recording_id),
            runtime.settings,
            formats=clip_subtitles.formats_from_settings(runtime.settings),
            variant=variant)
    except Exception as exc:
        runtime.logger.warning(
            "切り抜きの字幕fileを書き出せませんでした: %s", result.get("path"),
            exc_info=True,
            extra={"event": "clip.subtitles_failed",
                   "ctx": {"output": result.get("path"), "recording_id": recording_id,
                           "variant": variant}})
        result["subtitles"] = {"written": [], "files": [], "segments": 0,
                               "reason": "error",
                               "message": f"字幕fileを書き出せませんでした: {exc}"}
    return result


def _output_normalize() -> Optional[dict]:
    """焼き込み出力・Up出力の音量正規化の目標値(無効ならNone)。"""
    if not int(runtime.settings.get("video_output_normalize_audio")):
        return None
    return audio_norm.targets(runtime.settings)


def _reprocess_normalize() -> Optional[dict]:
    """再mp4化のついでに録画本体へかける音量正規化の目標値(無効ならNone)。"""
    if not int(runtime.settings.get("reprocess_normalize_audio")):
        return None
    return audio_norm.targets(runtime.settings)
