"""録画1行(recordings表のdict)から実体を引く層。

path解決・素材(.ts)とmp4の実在判定・削除の道連れ範囲・再生variantが集まっている。
「この録画に手を出せるか」を決める唯一の場所なので、判定を各routeへ散らさないこと
(``_recording_source_exists`` のdocstring参照)。

依存は runtime だけ。
"""

import os
import shutil
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from tictok.core import perf
from tictok.core import layout
from tictok.record.recorder import (Recorder, render_vod_playlist, session_prefix,
    SESSION_PREFIX_WIDTH)
from tictok.media.thumbnails import thumbnail_artifact_paths
from tictok.media.waveform import waveform_artifact_paths
from tictok.record.upscale import (cleanup_upscale_files, upscale_artifact_paths,
    upscale_input_path, upscale_output_path)
from tictok.record.video_overlay import (cleanup_overlay_files, overlay_artifact_paths,
    overlay_paths, overlay_transient_paths, timing_path)
from tictok.api import runtime


def _safe_recording_path(raw_path: str) -> Path:
    """Resolve a stored recording path and ensure it stays under an allowed record root
    (the working dir or the final dir). Recordings live in the working dir while in
    progress / interrupted and in the final dir once completed and relocated."""
    path = Path(raw_path).resolve()
    for root in runtime._RECORD_ROOTS:
        if path == root or root in path.parents:
            return path
    raise HTTPException(status_code=400, detail="不正な録画pathです。")


def _recording_cache_paths(path: Path) -> tuple:
    """srcから作られる持続cache(timing map・sprite・波形)のpath一式。

    どれもsrcが消えれば二度と参照されない。cacheの寿命はsrcの実在ではなくmtime+sizeの
    指紋で決まるため(thumbnails._signature / waveform._source_key)、srcを消しただけでは
    無効化されず`.sidecars/`に残り続ける。srcを消す経路は必ずここを通す。"""
    return (timing_path(path), *thumbnail_artifact_paths(path), *waveform_artifact_paths(path))


def _recording_derived_paths(path: Path) -> tuple:
    """srcから作られるfile全部(焼き込み・Up出力・renderの中間・持続cache)。

    srcを消すときの道連れ範囲であり、容量表示の内訳でもある。二箇所で別々に数えると
    「消えるはずのfileが表示に出ない」ずれが起きるので、定義はここだけに置く。
    /derivedの削除範囲にcacheを足したものになる。"""
    return (*overlay_artifact_paths(path), *overlay_transient_paths(path),
            *upscale_artifact_paths(path), *_recording_cache_paths(path))


def _unlink_quietly(paths) -> int:
    """実在するfileだけを消し、消せたbytesを返す。1件のOSErrorで一括処理を止めない。"""
    freed = 0
    for path in paths:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        try:
            path.unlink()
        except OSError:
            runtime.logger.warning("fileの削除に失敗しました: %s", path, exc_info=True)
            continue
        freed += size
    return freed


def _remove_recording_files(recording: dict) -> None:
    """Best-effort removal of a recording's video file and its sidecars (overlay,
    timing, sprite, waveform) from disk. Used by session/bulk deletes where one file
    error must not abort the whole operation and where leaving the .mp4 behind would
    orphan it."""
    try:
        path = _safe_recording_path(recording["path"])
    except HTTPException:
        return
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        runtime.logger.warning("recordingのfileの削除に失敗しました: %s", path, exc_info=True)
    cleanup_overlay_files(path)
    cleanup_upscale_files(path)
    _unlink_quietly(_recording_cache_paths(path))


def _remove_recording_derived(recording: dict) -> None:
    """録画の派生物(焼き込み・Up出力・cache)だけを消す。原本(mp4/.ts)には触らない。"""
    try:
        path = _safe_recording_path(recording["path"])
    except HTTPException:
        return
    cleanup_overlay_files(path)
    cleanup_upscale_files(path)
    _unlink_quietly(_recording_cache_paths(path))


def _delete_session_recording(recording: dict) -> str:
    """session削除に伴う録画の後始末。行った扱いを返す。

    session削除は「収集したdataを消す」操作であって「録画の原本を捨てる」操作ではない。
    素材(.ts)は`_remove_recording_ts`のdocstringどおり、userが明示的にこの録画の素材を
    捨てると決めたときだけ消す口を通す — ここは通さない。

    問題はmp4で、**素材を持たない録画ではmp4が唯一の実体**である(旧録画flow由来の録画が
    実在する)。従来はここで無条件にmp4を消していたため、そういう録画はsessionごと消すと
    復元不能になっていた。素材の有無で扱いを分ける:

    - 素材あり : mp4と派生物を消す(素材から作り直せる)。録画行は残す — 素材が在る以上、
                 この録画は今も再生・切り出しができる
    - 素材なし : mp4は**残す**(原本のため)。派生物だけ消す。録画行も残す
    - 実体なし : 派生物を掃除して録画行を落とす。指す先が無い行を残す理由が無い
    """
    has_ts = bool(_recording_ts_dirs(recording))
    if has_ts:
        _remove_recording_files(recording)
        return "kept_ts"
    try:
        mp4 = _safe_recording_path(recording["path"])
    except HTTPException:
        mp4 = None
    if mp4 is not None and mp4.is_file():
        _remove_recording_derived(recording)
        return "kept_source_mp4"
    _remove_recording_derived(recording)
    runtime.storage.delete_recording(recording["id"])
    return "removed_row"


def _recording_stem(recording: dict) -> str:
    """録画のstem(``00042_user_20250101_120000``)。

    filenameを優先するのは、中断録画のpathがmp4ではなくrecord dirを指すことがあるため
    (retention.transient_candidatesと同じ理由)。"""
    raw = recording.get("filename") or Path(recording.get("path") or "").name
    return Path(raw).stem


def _recording_no(recording: dict) -> str:
    """画面・log・job titleに出す録画の番号(``#00339``)。

    番号はfile名の先頭に載るSession番号へ一本化する。recordings.idを混ぜると、同じ録画が
    disk上の ``00339_…`` と画面の ``#705`` という別々の名前で呼ばれることになる。file名を
    session_idより先に見るのは、session削除後も残る録画(実測136件)がsession_id=NULLでも
    file名の番号は生きているため。どちらも引けなければ空を返す。"""
    head = _recording_stem(recording).split("_", 1)[0]
    if head.isdigit() and len(head) >= SESSION_PREFIX_WIDTH:
        return f"#{head}"
    session_id = recording.get("session_id")
    return f"#{session_prefix(session_id)}" if session_id is not None else ""


def _recording_label(recording: dict) -> str:
    """録画の名乗り(job title・ops event・error文言)。

    file名が規約どおり(先頭に番号)ならstem自体が番号を名乗っているのでそのまま、外れて
    いる録画(中断時のindex.m3u8・命名規約前の旧録画)だけ番号を前に補う。"""
    stem = _recording_stem(recording)
    head = stem.split("_", 1)[0]
    if head.isdigit() and len(head) >= SESSION_PREFIX_WIDTH:
        return stem
    no = _recording_no(recording)
    if not stem:
        return no
    return f"{no} {stem}".strip()


def _recording_ts_dirs(recording: dict) -> list:
    """この録画のHLS(seg*.ts)directoryのうち実在するもの。

    両rootを見るのは、mp4だけがfinal dirへ移りHLSはwork dirに残る経路があるため
    (_find_hls_rootと同じ事情)。layout経由で組み立てたpathだけを返し、DBのpathからは
    作らない — 後述の削除がdirectory丸ごとのrmtreeであり、規約外のpathを掴ませない。"""
    stem = _recording_stem(recording)
    if not stem or not layout.streamer_of(stem):
        return []
    dirs = []
    for root in runtime._RECORD_ROOTS:
        seg_dir = layout.session_dir(root, stem).resolve()
        # 組み立て元がrootでも、stemに区切りが混ざればrootの外へ出られる。
        if root not in seg_dir.parents or seg_dir.parent.name != layout.TS_DIRNAME:
            continue
        if seg_dir.is_dir():
            dirs.append(seg_dir)
    return dirs


def _recording_media_dirs(recording: dict) -> list:
    """この録画の素材が「使える状態で」在るsession dir。

    ``_recording_ts_dirs`` が返すdirのうち、素材と再生listが揃っているものだけを残す
    (判定は `_has_usable_media` に一本化)。再生経路の選択と、retentionでmp4を派生物として
    扱ってよいかの判断が、同じ事実を見るようにするための入口。"""
    return [seg_dir for seg_dir in _recording_ts_dirs(recording) if _has_usable_media(seg_dir)]


def _recording_media_kinds(recording: dict) -> list:
    """この録画の実体の種別。``["ts"]`` / ``["mp4"]`` / ``["ts", "mp4"]`` / ``[]``。

    録画の身元(``filename``)は今も ``<stem>.mp4`` だが、finalizeはmp4を作らなくなり、原本は
    .ts になった。名前だけを見せると「mp4というfileが在る」と読めてしまうので、一覧・詳細で
    実体が何であるかを名乗らせる。判定は ``_recording_source_exists`` と同じ事実を見る。"""
    kinds = []
    if _recording_media_dirs(recording):
        kinds.append("ts")
    try:
        path = _safe_recording_path(recording.get("path") or "")
    except HTTPException:
        path = None
    if path is not None and path.is_file():
        kinds.append("mp4")
    return kinds


def _recording_source_exists(recording: dict) -> bool:
    """この録画に手を出せるか。mp4の有無**ではない**。

    finalizeはmp4を作らなくなり、原本は .ts になった。焼き込み・切り出し・波形・thumbnail・
    転写はいずれもhls_source経由で .ts を読むので、mp4だけを見て断ると新しい録画が1本も
    通らない。「mp4 or 使える素材のどちらかが在る」がこの録画を扱える唯一の条件で、
    判定はここへ一本化する(mp4を実際に要求する操作 — 音量正規化・元mp4の削除 — だけは
    別に ``_existing_recording_file`` を使う)。"""
    return bool(_recording_media_kinds(recording))


def _dir_bytes(path: Path) -> int:
    """directory配下の実bytes合計。読めないentryは0として飛ばす(存在しない容量を数えない)。

    走査は ``_dir_usage`` に任せる。rglobはentry 1件につきis_fileとstatを別々に呼ぶため、
    束ね前のsession dir(実測で最大11,285 entries)では同じ答えに3倍の呼び出しを払う。"""
    return _dir_usage(path)[0]


def _dir_usage(path: Path) -> tuple:
    """directory配下の (bytes, file数, 最終更新)。読めないentryは数えない。

    走査は ``scandir`` で行う。session dirは束ね前で数千のsegmentを抱えるため、rglob+statの
    ようにfileごとのstatを起こすと1録画の見積りだけで数千の呼び出しになる。DirEntryのstatは
    Windowsでは一覧の時点で得た値をそのまま使う(追加の呼び出しが要らない)。"""
    total = files = 0
    newest = 0.0
    stack = [path]
    with perf.phase("fs.walk"):
        while stack:
            try:
                with os.scandir(stack.pop()) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                                continue
                            info = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        total += info.st_size
                        files += 1
                        newest = max(newest, info.st_mtime)
            except OSError:
                continue
    return total, files, newest


def _remove_recording_ts(recording: dict) -> int:
    """この録画のHLS directoryを消し、解放bytesを返す。

    HLSは録画の原本であってfinalizeでは消えない(recorder._finalize)。ここはuserが
    明示的に「この録画の素材を捨てる」と決めたときだけ通る口である。"""
    freed = 0
    for seg_dir in _recording_ts_dirs(recording):
        size = _dir_bytes(seg_dir)
        try:
            shutil.rmtree(seg_dir)
        except OSError:
            runtime.logger.warning("HLS directoryの削除に失敗しました: %s", seg_dir, exc_info=True)
            continue
        freed += size
    return freed


_HLS_PLAYLIST_NAME = layout.PLAYLIST_NAME


def _has_usable_media(seg_dir: Path) -> bool:
    """そのsession dirに、この録画を作り直せる/再生できる材料が揃っているか。

    素材(.ts)と再生list(index.m3u8)の**両方**を要求する。再mp4化も再生もplaylistのEXTINF順に
    segmentを読むので、listの無いsegmentの山からは何も組み立てられない。「.tsが在る」だけを
    根拠にすると、mp4を作り直せない録画のmp4を派生物と見なして消しにいくことになる。

    実体は ``layout.has_playable_media``。検索indexの時間軸も同じ判定を見る必要がある
    (再生経路が軸を決める)ため、条件はlayoutに置いてここは入口だけを残す。"""
    return layout.has_playable_media(seg_dir)


def _find_hls_root(stem: str) -> Path | None:
    """The record root actually holding this recording's HLS material
    (<root>/<streamer>/ts/<stem>/), or None. Both roots are searched because a
    manual move can leave the DB path stale."""
    for root in runtime._RECORD_ROOTS:
        seg_dir = layout.session_dir(root, stem)
        if seg_dir.is_dir() and _has_usable_media(seg_dir):
            return root
    return None


def _existing_recording_mp4(stem: str) -> Path | None:
    """The recording's current mp4 across either record root, or None."""
    for root in runtime._RECORD_ROOTS:
        cand = layout.mp4_path(root, stem)
        if cand.is_file():
            return cand
    return None


def _existing_recording_file(recording: dict) -> Optional[Path]:
    """録画行が指す実在のmp4。path不正・削除済み・finalize未完(録画dirのまま)ならNone。"""
    try:
        path = _safe_recording_path(recording.get("path") or "")
    except HTTPException:
        return None
    return path if path.is_file() else None


def _recording_seconds(recording: dict) -> float:
    """録画の尺(秒)。測っていない行は0として扱う。

    出所はffprobeで測ったduration_secondsだけ。ended_at - started_atは壁時計で、捕捉の
    停滞ぶんも再接続の待ちも載る(実測で1.6倍)。見積り(所要時間・容量)も一括画面の並びも
    動画そのものの長さで決まるので、壁時計へ落とすと数字が静かに膨らむ。未測定は
    scripts/repair_recording_durations.py が実fileから埋める。"""
    seconds = recording.get("duration_seconds")
    return float(seconds) if seconds and seconds > 0 else 0.0


def _delete_source_mp4(recording: dict) -> tuple[int, str]:
    """録画本体のmp4だけを消す。(消したbytes, 失敗理由) を返す。

    消すのは**DB行が名指ししているfileそのもの1本**に限る。焼き込み(.overlay.mp4)・
    Up出力(.up.mp4)・手で名前を変えたfileは、この録画から派生した別の成果物であって
    作り直しの対象ではない。「stemで始まるmp4」を消しに行くと、それらを巻き込む。"""
    path = _existing_recording_file(recording)
    if path is None:
        return 0, "no_file"
    if path.name != (recording.get("filename") or ""):
        # 行のpathとfilenameが食い違う録画。どちらが本体か決められないので触らない。
        return 0, "name_mismatch"
    size = path.stat().st_size
    try:
        path.unlink()
    except OSError:
        runtime.logger.exception(
            "recording %s の元mp4を削除できません", recording["id"],
            extra={"event": "recording.source_delete_failed",
                   "ctx": {"recording_id": recording["id"], "path": str(path)}},
        )
        return 0, "unlink_failed"
    # 消したmp4に紐づく事実を落とす。「作り直し済み」「正規化済み」はどちらもこのfileに
    # ついての主張で、fileが無くなった以上そのまま残すと嘘になる(再mp4化の対象からも
    # 外れたままになる)。
    runtime.storage.update_recording_bytes(recording["id"], 0)
    runtime.storage.set_recording_reprocessed(recording["id"], None)
    runtime.storage.set_recording_audio_normalized(recording["id"], None, None)
    return size, ""


def _recording_hls_dir(recording: dict) -> Optional[Path]:
    """この録画をHLSで再生できるsession dir。素材(.ts)か再生listが欠けていればNone。"""
    dirs = _recording_media_dirs(recording)
    return dirs[0] if dirs else None


def _hls_member(hls_dir: Path, filename: str) -> Optional[Path]:
    """browserへ返してよいHLS file(playlistとsegmentだけ、そのdirの直下に限る)。
    live録画の ``Recorder.live_file`` と同じ防御を、確定録画側へ置いたもの。"""
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    if not (filename.endswith(".m3u8") or filename.endswith(".ts")):
        return None
    candidate = (hls_dir / filename).resolve()
    if hls_dir.resolve() not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def _terminated_playlist(text: str) -> str:
    """録画停止時のffmpegは強制終了(WindowsのSIGTERMはTerminateProcess)なので、captureの
    index.m3u8には ``#EXT-X-ENDLIST`` が付かないまま残る。それをそのまま返すとhls.jsはlive
    streamと見なし、末尾から再生を始めて頭へseekできない。録画が終わっていることは事実なので
    終端tagだけを補う(束ね済みのplaylistは既に終端済みで、そのまま通る)。

    録画中のplaylistにだけ使う。確定録画は ``_finalized_playlist`` が採用集合から描き直す。"""
    if "#EXT-X-ENDLIST" in text:
        return text
    body = text if text.endswith("\n") else text + "\n"
    return body + "#EXT-X-ENDLIST\n"


def _finalized_playlist(recording: dict, hls_dir: Path) -> Optional[str]:
    """確定録画の再生用playlistを、finalizeが採ったのと同じ集合から描く。読めなければNone。

    captureのindex.m3u8をそのまま返してはならない。``_playlist_segments`` は源のtimestampが
    壊れてEXTINFだけが巨大になったsegmentを落としてからmp4を作っており、生のindexを再生に
    出すとその幻の時間が再生の時間軸にだけ戻る。実測で132録画中6件が該当し、落とされた1本の
    EXTINFは 2156s / 3760s / 28287s(7.8時間) だった。mp4の秒(video_time)と再生の秒を一致
    させるため、両者は同じ集合を見る。"""
    stem = Path(recording.get("filename") or "").stem or hls_dir.name
    recorder = Recorder(recording.get("unique_id") or stem,
                        str(layout.record_root_of(hls_dir.parent)),
                        recording.get("session_id"))
    recorder.hls_dir = hls_dir
    recorder.playlist = hls_dir / "index.m3u8"
    recorder.base = stem
    kept = recorder._playlist_segments()
    return render_vod_playlist(kept) if kept else None


def _resolved_recording_path(recording: dict) -> Path:
    """録画の現在のmp4 path。完了録画はfinal dirへ移動するので、DBのpathが実体を指さない
    ことがある。両rootを探して実在する方を返す(見つからなければDBのpathをそのまま返す)。"""
    path = _safe_recording_path(recording["path"])
    if path.is_file():
        return path
    found = _existing_recording_mp4(Path(recording["filename"]).stem)
    return found if found is not None else path


CLIP_VARIANTS = ("source", "overlay", "upscaled")
CLIP_VARIANT_LABELS = {"source": "元録画", "overlay": "焼き込み出力", "upscaled": "Up出力"}


def _variant_paths(path: Path, recording: Optional[dict] = None) -> dict:
    """録画1本ぶんの素材版 → path。存在するものだけを返す(存在しない版は作らない)。

    sourceの実体はmp4とは限らない。mp4が無くても素材(.ts)が在れば、下流(切り出しはclipper、
    焼き込みはvideo_overlay)がhls_source経由で読めるので、身元のmp4 pathをそのまま入力
    として返す。ここで ``is_file()`` だけを見ると、engineが読める録画をAPIの手前で断って
    しまう(切り出しが404になっていた原因)。"""
    found = ({"source": path}
             if path.is_file() or (recording is not None and _recording_media_dirs(recording))
             else {})
    overlay_mp4 = overlay_paths(path)[0]
    if overlay_mp4.is_file():
        found["overlay"] = overlay_mp4
    upscaled = upscale_output_path(upscale_input_path(path))
    if upscaled.is_file():
        found["upscaled"] = upscaled
    return found


def _clip_route(recording: dict, variant: str) -> str:
    """その範囲でその素材を得る経路。``"copy"`` か ``"render"``。

    variantの意味を「既にある成果物を切る」から「**この範囲でその素材を得る**」へ変えている。
    全尺の焼き込み出力が在ればそこから stream copy し(数秒・keyframe前置きあり)、無ければ
    その範囲だけを焼く(GPU・frame精度)。どちらも「その範囲の焼き込み済み素材」を返すので
    fallbackではない。唯一の差(前置きとencode世代)は応答で必ず名乗る。

    従来は全尺出力が無ければ404で断っていた。3時間の録画を丸ごと焼くのは実質不可能なので、
    それは「焼き込み済みの切り抜きは作れない」と同義だった。
    """
    if variant not in CLIP_VARIANTS:
        raise HTTPException(status_code=400, detail=f"未知の素材版です: {variant}")
    if variant == "source":
        return "copy"
    found = _variant_paths(_resolved_recording_path(recording), recording)
    return "copy" if variant in found else "render"


def _clip_source(recording: dict, variant: str) -> Path:
    """切り出しの入力。無い版を黙ってsourceへ落とすと、利用者は焼き込み済みを頼んだのに
    素のclipを受け取ることになるので、無ければ拒否する。"""
    if variant not in CLIP_VARIANTS:
        raise HTTPException(status_code=400, detail=f"未知の素材版です: {variant}")
    found = _variant_paths(_resolved_recording_path(recording), recording)
    if variant not in found:
        raise HTTPException(
            status_code=404,
            detail=f"この録画の{CLIP_VARIANT_LABELS[variant]}がありません。先に出力してください。",
        )
    return found[variant]
