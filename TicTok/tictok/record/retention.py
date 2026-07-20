"""保持policy(retention)の候補選定。実際の削除は行わず、何をどの順で消せるかだけを組む。

削除順序は固定で (1)孤児transient → (2)再生成可能な派生物 → (3)生録画 とする。source mp4 は
唯一の再取得不能資産で、overlay / up / cfrbase / comments.mov は source と収集eventから
作り直せる派生物にすぎない。source を先に消すと reprocess・再output・transcribe・clip・heat が
まとめて復旧不能になるため、この順序を崩してはならない。

「転写済みで再利用予定が薄い」といった主観scoreは持たない(根拠の無い順位付けは捏造に近い)。
並べ替えは最終更新の古い順のみで、同点はpathで決める。
"""
import logging
import os
from pathlib import Path

from tictok.core import layout
from tictok.record.recorder import (
    FFMPEG_LOG_SUFFIX,
    NORMALIZE_TMP_SUFFIX,
    SIDECAR_DIRNAME,
)
from tictok.record.upscale import upscale_artifact_paths
from tictok.record.video_overlay import (
    CFR_BASE_SUFFIX,
    CFR_SUFFIX,
    COMMENT_LAYER_SUFFIX,
    PREVIEW_ASS_SUFFIX,
    PREVIEW_CLIP_BASE_SUFFIX,
    PREVIEW_LAYER_SUFFIX,
    PREVIEW_RAW_SUFFIX,
    overlay_artifact_paths,
    overlay_transient_paths,
)

logger = logging.getLogger("tictok.retention")

PHASE_TRANSIENT = "transient"
PHASE_DERIVED = "derived"
PHASE_SOURCE = "source"

# 実行順そのもの。画面はこの順でそのまま並べる。
PHASE_ORDER = (PHASE_TRANSIENT, PHASE_DERIVED, PHASE_SOURCE)
PHASE_LABELS = {
    PHASE_TRANSIENT: "① 中断したrenderが残した中間file",
    PHASE_DERIVED: "② 作り直せる派生物(焼き込み・AI高画質化)",
    PHASE_SOURCE: "③ 生録画(mp4本体・再取得不能)",
}

# transient と判定するsuffix。すべて .sidecars 配下に書かれるので、走査もそこだけで足りる。
_TRANSIENT_SUFFIXES = (CFR_BASE_SUFFIX, CFR_SUFFIX, COMMENT_LAYER_SUFFIX,
                       PREVIEW_CLIP_BASE_SUFFIX, PREVIEW_LAYER_SUFFIX,
                       PREVIEW_RAW_SUFFIX, PREVIEW_ASS_SUFFIX)

_HOUR_SECONDS = 3600.0
_DAY_SECONDS = 86400.0


def _stat(path: Path):
    try:
        info = path.stat()
    except OSError:
        return None
    return info


def _existing(paths) -> list:
    """(path, bytes, mtime) of the files that actually exist."""
    found = []
    for path in paths:
        info = _stat(Path(path))
        if info is not None:
            found.append((Path(path), info.st_size, info.st_mtime))
    return found


def artifact_bytes(paths) -> int:
    """実在するfileだけのbytes合計。存在しないpathは0として足さない(捏造しない)。"""
    return sum(size for _, size, _ in _existing(paths))


def transient_candidates(roots, recordings, resolve_path,
                         min_age_seconds: float, now: float) -> list:
    """中断したrender/再encodeが残した中間file。

    焼き込みの中間(.cfrbase.mp4 / .comments.mov / 旧.cfr.mp4)は必ず .sidecars 配下に、
    混在解像度normalizeの中間(.mp4.norm.tmp)はmp4の隣に落ちるため、前者はdirectory走査、
    後者は録画行から引いた決め打ちのpathで拾う。実行中のfileを巻き込まないよう、
    ``min_age_seconds`` より新しいものは必ず除外する。"""
    items = []
    seen: set = set()
    for recording in recordings:
        if recording.get("status") == "recording":
            continue
        src = resolve_path(recording)
        if src is None:
            continue
        # normalizeは録画完了時(=まだwork dir側)に走り、その後mp4だけがfinal dirへ移る。
        # DBのpathは移動後を指すので、残骸を拾うには両rootのmp4置き場を見る必要がある。
        # 中断録画のpathはmp4ではなくrecord dirを指すことがあるので、stemはfilename優先で取る。
        stem = Path(recording.get("filename") or src.name).stem
        for root in roots:
            mp4 = layout.mp4_path(root, stem)
            tmp = mp4.with_suffix(mp4.suffix + NORMALIZE_TMP_SUFFIX)
            for path in (tmp, tmp.with_name(tmp.name + FFMPEG_LOG_SUFFIX)):
                info = _stat(path)
                if info is None or path in seen:
                    continue
                age = now - info.st_mtime
                if age < min_age_seconds:
                    continue
                seen.add(path)
                items.append({
                    "path": str(path),
                    "name": path.name,
                    "bytes": info.st_size,
                    "mtime": info.st_mtime,
                    "age_hours": round(age / _HOUR_SECONDS, 1),
                    "recording_id": recording["id"],
                })
    for raw in roots:
        sidecars = Path(raw).resolve() / SIDECAR_DIRNAME
        if not sidecars.is_dir():
            continue
        try:
            entries = list(os.scandir(sidecars))
        except OSError:
            logger.warning(
                "could not read %s while planning retention", sidecars,
                extra={"event": "retention.scan_failed", "ctx": {"path": str(sidecars)}},
                exc_info=True,
            )
            continue
        for entry in entries:
            if not entry.name.endswith(_TRANSIENT_SUFFIXES):
                continue
            path = Path(entry.path)
            if path in seen:
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            age = now - info.st_mtime
            if age < min_age_seconds:
                continue
            seen.add(path)
            items.append({
                "path": str(path),
                "name": entry.name,
                "bytes": info.st_size,
                "mtime": info.st_mtime,
                "age_hours": round(age / _HOUR_SECONDS, 1),
                "recording_id": None,
            })
    items.sort(key=lambda item: (item["mtime"], item["path"]))
    return items


def derived_candidates(recordings, resolve_path, min_age_seconds: float, now: float) -> list:
    """焼き込み/AI高画質化の出力とそのmeta。保護flagの立った録画は対象外。

    経過time刻は派生物自身の最終更新で測る(元録画の日付ではない)。作り直した直後の出力を
    「古い録画だから」で消してしまうのを避けるため。"""
    items = []
    for recording in recordings:
        if recording.get("protected"):
            continue
        if recording.get("status") == "recording":
            continue
        src = resolve_path(recording)
        if src is None or not src.is_file():
            # 元mp4が無い派生物は「作り直せる」派生物ではなく最後の1本なので、この段階では
            # 消さない(回収したい場合は録画行ごと削除するUIが同じfileを消す)。
            continue
        found = _existing(overlay_artifact_paths(src) + upscale_artifact_paths(src))
        if not found:
            continue
        newest = max(mtime for _, _, mtime in found)
        age = now - newest
        if age < min_age_seconds:
            continue
        items.append({
            "recording_id": recording["id"],
            "filename": recording.get("filename") or src.name,
            "unique_id": recording.get("unique_id") or "",
            "path": str(src),
            "bytes": sum(size for _, size, _ in found),
            "files": len(found),
            "mtime": newest,
            "age_days": round(age / _DAY_SECONDS, 1),
        })
    items.sort(key=lambda item: (item["mtime"], item["path"]))
    return items


def source_candidates(recordings, resolve_path, min_age_seconds: float, now: float) -> list:
    """生録画本体。ここに載ることと消してよいことは別で、実行するかどうかは設定の明示的な
    有効化と operator の確認に委ねる(既定はOFF)。"""
    items = []
    for recording in recordings:
        if recording.get("protected"):
            continue
        if recording.get("status") == "recording":
            continue
        src = resolve_path(recording)
        if src is None or not src.is_file():
            # 中断録画のpathはmp4ではなくrecord dir自体を指すことがある。実fileでない行を
            # 候補にすると、消えていない録画のDB行だけが落ちる。
            continue
        info = _stat(src)
        if info is None:
            continue
        # 完了time刻が無い録画(中断など)は本体のmtimeで測る。存在しない値を0で埋めると
        # 「無限に古い」扱いになり、最優先で消える側に回ってしまう。
        finished = recording.get("ended_at") or info.st_mtime
        age = now - finished
        if age < min_age_seconds:
            continue
        artifacts = _existing(
            overlay_artifact_paths(src) + overlay_transient_paths(src)
            + upscale_artifact_paths(src)
        )
        items.append({
            "recording_id": recording["id"],
            "filename": recording.get("filename") or src.name,
            "unique_id": recording.get("unique_id") or "",
            "path": str(src),
            "bytes": info.st_size + sum(size for _, size, _ in artifacts),
            "files": 1 + len(artifacts),
            "mtime": finished,
            "age_days": round(age / _DAY_SECONDS, 1),
            "has_transcript": bool(recording.get("has_transcript")),
        })
    items.sort(key=lambda item: (item["mtime"], item["path"]))
    return items


def build_plan(recordings, roots, resolve_path, rules: dict, now: float) -> dict:
    """3 phaseの削除候補を実行順で返す。``rules`` は server が設定から組む
    {transient_hours, derived_days, source_days, source_enabled} 。

    値が 0(=無効)の phase は候補を作らず ``enabled: false`` と理由を返す。無効を空list
    として返すと「対象が無い」と区別が付かず、設定を直せば消せるのか判断できなくなる。"""
    phases = []

    transient_hours = float(rules.get("transient_hours") or 0)
    if transient_hours > 0:
        items = transient_candidates(roots, recordings, resolve_path,
                                     transient_hours * _HOUR_SECONDS, now)
        phases.append(_phase(PHASE_TRANSIENT, True, "", items))
    else:
        phases.append(_phase(PHASE_TRANSIENT, False,
                             "「中間fileを削除するまでの経過時間（時間）」が0のため実行しません。", []))

    derived_days = float(rules.get("derived_days") or 0)
    if derived_days > 0:
        items = derived_candidates(recordings, resolve_path, derived_days * _DAY_SECONDS, now)
        phases.append(_phase(PHASE_DERIVED, True, "", items))
    else:
        phases.append(_phase(PHASE_DERIVED, False,
                             "「派生物を削除するまでの日数」が0のため実行しません。", []))

    source_days = float(rules.get("source_days") or 0)
    if not rules.get("source_enabled"):
        phases.append(_phase(PHASE_SOURCE, False,
                             "「生録画の自動削除」が無効のため実行しません（既定は無効です）。", []))
    elif source_days <= 0:
        phases.append(_phase(PHASE_SOURCE, False,
                             "「生録画を削除するまでの日数」が0のため実行しません。", []))
    else:
        items = source_candidates(recordings, resolve_path, source_days * _DAY_SECONDS, now)
        phases.append(_phase(PHASE_SOURCE, True, "", items))

    return {
        "phases": phases,
        "total_bytes": sum(phase["bytes"] for phase in phases),
        "total_items": sum(len(phase["items"]) for phase in phases),
    }


def _phase(key: str, enabled: bool, reason: str, items: list) -> dict:
    return {
        "phase": key,
        "label": PHASE_LABELS[key],
        "enabled": enabled,
        "reason": reason,
        "items": items,
        "bytes": sum(item["bytes"] for item in items),
    }
