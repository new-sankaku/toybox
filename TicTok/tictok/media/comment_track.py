"""録画窓のcommentを字幕・表計算向けの形へ書き出す。

入力はsearch_hits(source=comment)の行で、video_timeはindex時に元録画mp4のPTSへ変換済み。
焼き込み・検索hit・comment panelと同じ軸なので、ここで時刻変換は挟まない。書き出した
timecodeが合うのは**元録画mp4**とそこからのstream copy切り抜きに対してだけで、焼き込み
出力・Up出力は再encodeで尺が動き得るため保証しない(subtitlesと同じ制約)。

== cueの長さと重なり ==

commentは投稿時刻だけを持つ点event(尺が無い)ので、cueの長さはこちら側で決めるほかない。
既定はconfigのTICTOK_COMMENT_SUBTITLE_SECONDSで、次のcueが開く時刻で打ち切るため実際には
上限として働く。

開いているcueの最中に届いたcommentは、重なるcueを新しく開かずに同じcueへ行として足す。
SRTのcueは本来前後しない前提で、重なると読み手(playerやNLE)によって片方が消えたり順が
入れ替わったりする。1 cueへ束ねる件数はTICTOK_COMMENT_SUBTITLE_MAX_LINESで頭打ちにし、
弾幕のような密度でcueが画面を埋めるのを防ぐ。ただし**同時刻**のcommentだけは上限を
超えても同じcueへ入れる。時刻が同じものは時間軸で分けようがなく、cueを閉じると長さ0の
cueになって内容ごと落ちるため。
"""

import csv
import io
import json
import logging

from tictok.core import config
from tictok.record import subtitles

logger = logging.getLogger("tictok.comment_track")

# 書き出せる形式: format -> (拡張子, media type, 文字encode)。csvはBOM付きutf-8で、
# Excelが既定のlocaleで開いても日本語が化けないようにする。
EXPORT_FORMATS = {
    "srt": (".comments.srt", "application/x-subrip; charset=utf-8", "utf-8"),
    "csv": (".comments.csv", "text/csv; charset=utf-8", "utf-8-sig"),
    "json": (".comments.json", "application/json; charset=utf-8", "utf-8"),
}

CSV_COLUMNS = ("time_seconds", "timecode", "nickname", "body")


def usable_comments(comments, start=None, end=None, origin=None) -> list:
    """書き出せるcommentだけを時間順で返す。

    video_timeが無いものと本文が空のものは落とす(時刻を推測して埋めない)。start/endを
    渡すとその窓で絞り、originを0点として相対時刻へ写す。切り抜きのsidecarでは
    clipper.make_clipのactual_start_secondsをoriginに渡すこと。要求のstartを0点にすると、
    stream copyがkeyframeまで手前へ伸びたぶん(実測2.1秒〜37.6秒)だけ字幕が後ろへずれる。"""
    origin = 0.0 if origin is None else float(origin)
    items = []
    for row in comments or []:
        at = row.get("video_time")
        body = (row.get("body") or "").strip()
        if at is None or not body:
            continue
        at = float(at)
        if start is not None and at < float(start):
            continue
        if end is not None and at >= float(end):
            continue
        items.append({"t": max(0.0, at - origin),
                      "nickname": (row.get("nickname") or "").strip(),
                      "body": body})
    items.sort(key=lambda c: c["t"])
    dropped = len(comments or []) - len(items)
    if dropped:
        logger.info(
            "comment export dropped %d unusable comment(s) of %d",
            dropped, len(comments or []),
            extra={"event": "comment_track.dropped",
                   "ctx": {"dropped": dropped, "total": len(comments or [])}},
        )
    return items


def _line(comment: dict) -> str:
    return f"[{comment['nickname']}] {comment['body']}" if comment["nickname"] \
        else comment["body"]


def to_segments(comments, media_duration=None, cue_seconds=None, max_lines=None) -> list:
    """commentをsubtitlesが書き出せるsegment(start/end/text)へ畳む。

    既にusable_comments済みのlistを渡すこと(窓取りと相対化はそちらの責務)。"""
    cue_seconds = config.get_comment_subtitle_seconds() if cue_seconds is None \
        else float(cue_seconds)
    max_lines = config.get_comment_subtitle_max_lines() if max_lines is None \
        else int(max_lines)
    items = list(comments or [])
    segments = []
    index = 0
    while index < len(items):
        opened = items[index]["t"]
        group = [items[index]]
        cursor = index + 1
        while cursor < len(items) and len(group) < max_lines \
                and items[cursor]["t"] < opened + cue_seconds:
            group.append(items[cursor])
            cursor += 1
        # 上限を超えても同時刻ぶんは同じcueへ入れる(分けるとcueが長さ0になり内容が落ちる)。
        while cursor < len(items) and items[cursor]["t"] <= opened:
            group.append(items[cursor])
            cursor += 1
        end = opened + cue_seconds
        if cursor < len(items):
            end = min(end, items[cursor]["t"])
        if media_duration is not None:
            end = min(end, float(media_duration))
        if end > opened:
            segments.append({"start": opened, "end": end,
                             "text": "\n".join(_line(c) for c in group)})
        index = cursor
    return segments


def to_srt(comments, media_duration=None, cue_seconds=None, max_lines=None) -> str:
    return subtitles.to_srt(
        to_segments(comments, media_duration, cue_seconds, max_lines), media_duration)


def to_csv(comments) -> str:
    """表計算・script向けの1行1comment。時刻は秒とtimecodeの両方を出す(秒は並べ替えと
    差分計算に、timecodeはNLEへ打ち込むために要る)。

    timecodeのmillis区切りはSRTのカンマではなくpointにする。CSVでカンマを使うと毎行が
    引用符付きになり、目でもscriptでも読みにくい。"""
    buffer = io.StringIO(newline="")
    # Excelが既定で読む改行はCRLF。lineterminatorを既定のままにすると、環境によって
    # 1 cellへ全行が入る。
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for comment in comments or []:
        writer.writerow([f"{comment['t']:.3f}", subtitles.clock(comment["t"], "."),
                         comment["nickname"], comment["body"]])
    return buffer.getvalue()


def to_json(comments) -> str:
    return json.dumps(
        {"items": [{"t": round(c["t"], 3), "nickname": c["nickname"], "body": c["body"]}
                   for c in comments or []]},
        ensure_ascii=False, indent=2,
    ) + "\n"


def render(fmt: str, comments, media_duration=None) -> str:
    if fmt == "srt":
        return to_srt(comments, media_duration)
    if fmt == "csv":
        return to_csv(comments)
    if fmt == "json":
        return to_json(comments)
    raise ValueError(f"unknown comment export format: {fmt}")
