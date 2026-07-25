"""差し替え操作が残す退避mp4(``<root>/_backup/``)の後始末。

再mp4化・音量正規化は元mp4を退避してから差し替える。退避は失敗を巻き戻すためのもので、
**成功が確かめられた時点で役目を終える**。ところが消す経路がどこにも無かったため、成功
1回につき元mp4が1本ずつ永久に積み上がっていた(2026-07-25実測: 84本ぶん107 file 304GB。
その91%が1世代目 = 繰り返し実行のせいではなく、単に誰も消していないぶん)。

消してよいかの判定は1箇所に置く。判定を持つ場所が増えると、片方だけが厳しくなって
「scriptは残すのにserverは消す」という最悪の食い違いになる。基準はvideo frame数で、
尺(container duration)は使わない — 旧経路のmp4は幻の音声穴でtimestampが伸びており、
同じ内容を作り直すと尺だけが数%縮むため、尺で見ると正常な作り直しが「短くなった」と読める
(実測 4151.0秒 -> 4000.3秒 / frame数は87652で同一)。
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from tictok.core import layout

logger = logging.getLogger("tictok.backups")

BACKUP_DIRNAME = "_backup"

# 現行mp4のframeが退避より少なくてよい割合。結合し直し(再mp4化)も映像stream copy
# (音量正規化)もframeを落とさないので、本来は同数。
FRAME_TOLERANCE = 0.001
# frameが読めない場合に限って尺で見るときの許容。旧経路のmux inflation(実測最大4%)ぶん。
DURATION_TOLERANCE = 0.05

KEEP_UNREADABLE_CURRENT = "現行mp4を読めない"
KEEP_UNREADABLE_BACKUP = "退避を読めない"
KEEP_SHORTER = "現行mp4が退避より欠けている"
KEEP_FRAMES_ONLY = "frameのみ不足(尺は一致 = CFR→VFRの可能性)"


def backup_dir(root) -> Path:
    return Path(root) / BACKUP_DIRNAME


def backups_for(stem: str, roots) -> list:
    """この録画の退避file(``<stem>.mp4`` と ``<stem>.<n>.mp4``)を全rootから集める。"""
    found = []
    for root in roots:
        directory = backup_dir(root)
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"{stem}*.mp4")):
            owner, _streamer = layout.artifact_owner(path.name)
            if owner == stem:
                found.append(path)
    return found


async def probe_frames_seconds(path: Path) -> tuple:
    """(video frame数, 尺秒)。frame数はmp4のindexにあるheader値なので、復号せずに読める
    (数十GBでも一瞬)。読めなければ (None, None)。"""
    args = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames:format=duration",
        "-of", "default=noprint_wrappers=1", str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except OSError:
        return None, None
    frames = seconds = None
    for line in out.decode("ascii", "replace").splitlines():
        key, _, value = line.partition("=")
        try:
            if key == "nb_frames":
                frames = int(value)
            elif key == "duration":
                seconds = float(value)
        except ValueError:
            continue
    return frames, seconds


async def supersedes(current: Path, backup: Path) -> tuple:
    """現行mp4が退避を置き換え切っているか。(判定, 理由) を返す。

    「置き換え切っている」= 退避が持っていた中身を現行が全部持っている、という意味で、
    退避を消してよい唯一の条件である。fileの有無やsizeでは判定できない(再encodeでsizeは
    平気で2倍にも1/5にもなる)。"""
    if not current.is_file() or current.stat().st_size <= 0:
        return False, KEEP_UNREADABLE_CURRENT
    current_frames, current_seconds = await probe_frames_seconds(current)
    backup_frames, backup_seconds = await probe_frames_seconds(backup)
    if not backup_frames and not backup_seconds:
        return False, KEEP_UNREADABLE_BACKUP
    if not current_frames and not current_seconds:
        return False, KEEP_UNREADABLE_CURRENT
    if current_frames and backup_frames:
        if current_frames >= backup_frames * (1.0 - FRAME_TOLERANCE):
            return True, ""
        # 尺が保たれていれば切れてはいない。旧mp4がCFR化でframeを水増ししていると起きる
        # 形で、内容欠落とは別物。ただし尺だけでは中身が薄くなっていないと言い切れないので、
        # 自動では消さない。
        if current_seconds and backup_seconds and \
                current_seconds >= backup_seconds * (1.0 - DURATION_TOLERANCE):
            return False, (f"{KEEP_FRAMES_ONLY}"
                           f"({current_frames} < {backup_frames} frame)")
        return False, f"{KEEP_SHORTER}({current_frames} < {backup_frames} frame)"
    # frame数を読めないcontainerだけ尺で見る。判定材料が1つ落ちるので許容も広く取る。
    if current_seconds and backup_seconds:
        if current_seconds >= backup_seconds * (1.0 - DURATION_TOLERANCE):
            return True, ""
        return False, (f"{KEEP_SHORTER}"
                       f"({current_seconds / 60:.1f}分 < {backup_seconds / 60:.1f}分)")
    return False, KEEP_UNREADABLE_BACKUP


async def sweep_recording_backups(stem: str, current: Path, roots, keep_seconds: float,
                                  now: float) -> dict:
    """この録画の退避を掃く。``{"deleted": n, "bytes": n, "kept": {理由: 件数}}``。

    差し替えたjobの直後に、その録画ぶんだけを掃くために使う(録画1本につきffprobeは数回)。
    ``keep_seconds`` を過ぎていない退避は、判定の結果に関わらず残す — 尺やframeでは
    見えない不具合(コメントのズレ・音の異常)に人が気付くまでの猶予である。"""
    deleted = 0
    freed = 0
    kept: dict = {}
    for path in backups_for(stem, roots):
        try:
            info = path.stat()
        except OSError:
            continue
        if keep_seconds > 0 and now - info.st_mtime < keep_seconds:
            kept["保持期間内"] = kept.get("保持期間内", 0) + 1
            continue
        ok, reason = await supersedes(current, path)
        if not ok:
            kept[reason] = kept.get(reason, 0) + 1
            continue
        try:
            path.unlink()
        except OSError as exc:
            logger.warning(
                "could not delete the superseded backup %s: %s", path, exc,
                extra={"event": "backup.delete_failed",
                       "ctx": {"stem": stem, "path": str(path)}},
            )
            kept["削除できない"] = kept.get("削除できない", 0) + 1
            continue
        deleted += 1
        freed += info.st_size
    if deleted or kept:
        logger.info(
            "swept backups for %s: deleted %d (%.2fGB), kept %d", stem, deleted,
            freed / 1024 ** 3, sum(kept.values()),
            extra={"event": "backup.swept",
                   "ctx": {"stem": stem, "deleted": deleted, "freed_bytes": freed,
                           "kept": kept}},
        )
    return {"deleted": deleted, "bytes": freed, "kept": kept}
