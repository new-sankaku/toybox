"""旧版の時刻mapで作られたtranscriptを選別する起動時migration。

``TIMEMAP_VERSION`` を2へ上げた時点で、既存のtranscriptはすべて版1を名乗る。だが版1の
母集団は2つに分かれている:

  * 幻のtimestamp jumpを踏んだもの … 版2の ``_rebase_phantom_jumps`` が畳むので出力が変わる。
    実測(録画00126)は2時間51分の素材に対し文字起こしの終端が10時間43分で、字幕は録画の外側を指す。
  * 踏まなかったもの … 畳む対象が無く、版2で復号しても**同じ時刻が出る**。

全部を版1のまま残すと、後者まで「古い時刻map」として扱われ、字幕焼き込みもAI章立ても
一律に拒否される。逆に全部を昇格させると、前者が現行版を名乗ったまま残り、版を上げた意味が
無くなる。そこで素材の実尺で選別する — 文字起こしの尺が素材に収まっていれば畳む対象は無かった
のだから昇格させ、食い違うものだけ版1のまま残して「要再文字起こし」を名乗らせる。

物差しは焼き込みの関門と同じ ``video_overlay.material_media_seconds`` と
``subtitles.axis_matches_media`` を使う。ここで判定を書き写すと、同じ文字起こしが経路によって
合格したり弾かれたりする。

実尺が測れない録画(素材が消えた旧録画)は昇格させる。``axis_matches_media`` と同じ立場で、
降格は「ズレている証拠がある」ときにだけ行う — 根拠が無いまま版1へ据え置くと、正しい文字起こし
まで焼き込めなくなる。

版そのものが無い(NULL)transcriptは対象外。map以前に作られたもので、媒体軸に載っている
保証がそもそも無く、昇格の根拠にできる証拠が何も無い。

処理後は選別済みのものが現行版を名乗るので冪等。据え置いたぶんは毎起動で再判定するが、
読むのは録画ごとのtiming.json 1本だけである。
"""
import logging
from pathlib import Path

from tictok.record import subtitles
from tictok.record.transcription import TIMEMAP_VERSION

logger = logging.getLogger("tictok.timemap_migration")

# 選別ruleの版。走らせるかどうかの判断はこの値で行う(db_maintenanceへ刻む)。据え置いた行は
# 版1のまま残るので、素直に毎起動で走らせると同じ母集合を測り直し続けることになり、物差しは
# 1件あたり採用集合のplaylist解析かffprobeを要する。**選別の根拠を変えたらここを上げる** —
# 上げないと、新しい物差しなら合格するはずの文字起こしが古い判定のまま据え置かれる。
#
# 1: timing.json の media_duration で測っていた版。
# 2: 下流が実際に読む素材(採用集合 / mp4)で測る版。1では、素材が消えてmp4だけが残った録画
#    に対し、もう存在しない .ts の尺を突きつけて弾いていた(実測9件が誤って据え置かれた)。
SELECTION_VERSION = 2


def material_span(path) -> float:
    """録画pathから素材の実尺(media軸の終端)を引く。測れなければNone。

    importが関数内なのは、storageのimport時にvideo_overlay一式(PIL・ffmpeg周り)を
    引き込まないため。"""
    from tictok.record.video_overlay import material_media_seconds

    return material_media_seconds(Path(path))


def migrate_timemap_version(conn, span_of) -> dict:
    """版1のtranscriptを素材の実尺で選別し、収まっているものだけ現行版へ上げる。

    ``span_of`` は録画pathから素材の実尺を返す関数(測れなければNone)。呼び出し側が渡すのは
    副作用をthreadやfilesystemから切り離してtestできるようにするためで、本番の実体は
    ``material_span`` である。

    ``(検査数, 昇格数, 据え置き数)`` を返す。"""
    rows = conn.execute(
        "SELECT t.recording_id, t.duration, r.path"
        " FROM transcripts t JOIN recordings r ON r.id = t.recording_id"
        " WHERE t.timemap_version IS NOT NULL AND t.timemap_version < ?",
        (TIMEMAP_VERSION,),
    ).fetchall()
    promoted = []
    kept = []
    for recording_id, duration, path in rows:
        span = span_of(path)
        if subtitles.axis_matches_media({"duration": duration}, span):
            promoted.append(recording_id)
        else:
            kept.append((recording_id, duration, span))
    if promoted:
        conn.executemany(
            "UPDATE transcripts SET timemap_version = ? WHERE recording_id = ?",
            [(TIMEMAP_VERSION, recording_id) for recording_id in promoted],
        )
    for recording_id, duration, span in kept:
        logger.warning(
            "録画 %d の文字起こしは素材と時間軸が違うため版%dのまま据え置きます"
            "（文字起こし %.1f秒 / 素材 %.1f秒）。やり直しが必要です",
            recording_id, TIMEMAP_VERSION - 1, float(duration or 0.0), float(span or 0.0),
            extra={"event": "stt.timemap_stale_kept",
                   "ctx": {"recording_id": recording_id,
                           "transcript_seconds": duration,
                           "material_seconds": span,
                           "timemap_version": TIMEMAP_VERSION}},
        )
    return {"checked": len(rows), "promoted": len(promoted), "kept": len(kept)}
