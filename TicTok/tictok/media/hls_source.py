"""録画1本をffmpegの入力へ解く共通層。

録画の原本は .ts のHLSになり、mp4はそこから作る派生物になった。下流(転写・切抜き・
sprite・波形・Up出力)はどれもmp4 pathを受け取る作りのままなので、そのmp4がもう無い
録画では素材ごと失われたように見える。ここが両者の差を吸収する: **mp4が在ればそのまま、
無ければ同じ録画の .ts を入力にする**。

判断を「mp4が在るか」だけに掛けるのは意図的である。派生物(<stem>.overlay.mp4 等)が
無いときに原本の .ts へ落ちると、焼き込んだはずの出力の代わりに素の映像が黙って出てくる。
落とすのはその録画自身のmp4(``<stem>.mp4``)のときだけに限る。

== HLSを入力にするときの決まり ==

**captureの ``index.m3u8`` を直接ffmpegへ渡してはいけない。** 源のtimestampが壊れて
EXTINFだけが巨大化したsegmentが残っており(実測1本が28,287秒=7.8時間)、2.9時間の録画が
10.7時間として読まれる。終端tagも付かない(停止時のffmpegは強制終了される)ので、live
streamと見なされて待ち続ける。採用集合だけを指す終端済みVOD playlistを
``recorder.write_curated_playlist`` に書かせ、それを ``-i`` に渡す。

そのplaylistはsegmentを**相対名**で指すので、録画のsession dirの中に置く以外に無い。
使い終わったら消す必要があるため、このmoduleの入口は context manager になっている。
"""
from __future__ import annotations

import contextlib
import fnmatch
import logging
import os
import uuid
from pathlib import Path
from typing import NamedTuple, Optional

from tictok.core import ffprobe
from tictok.core import layout
from tictok.record import recorder as rec

logger = logging.getLogger(__name__)

# 上限の実体は core.ffprobe。既存の公開名は呼び出し側のために残す。
PROBE_TIMEOUT_SECONDS = ffprobe.DEFAULT_TIMEOUT_SECONDS

# 一時playlistの名前。session dirへ置くので、録画実体のglob(seg*.ts / pack*.ts)にも
# capture index にも束ねのsnapshotにも当たらない綴りにする。
CURATED_PREFIX = ".hlsin-"
CURATED_SUFFIX = ".m3u8"


class SourceMissing(RuntimeError):
    """その録画の素材が1つも無い(mp4も.tsも)。"""

    def __init__(self, message: str = "録画fileが存在しません。") -> None:
        super().__init__(message)


class Source(NamedTuple):
    """ffmpegへ渡す入力1つ。

    ``input_args`` は ``-i`` の**前**に置くdemuxer option。HLSのときだけ中身があるので、
    呼び出し側は常に ``[*source.input_args, "-i", str(source.path)]`` と書けばよい。"""

    path: Path
    input_args: tuple
    is_hls: bool
    # 入力のcontainer start_time(秒)。HLSのsegmentは0始まりではない(実測1.402s)。
    #
    # ``-copyts`` を**付けない**経路ではffmpegが先頭を0へ寄せるので、filterが見る時刻は
    # media軸そのものになる(実測: 1枚目が pts_time:0)。何もしなくてよい。
    #
    # ``-copyts`` を**付ける**経路(焼き込みプレビューの窓)だけは、filterが絶対時刻を見る
    # ためこの値ぶんずれる。打ち消すには入力側へ ``-itsoffset -media_offset`` を併記し、
    # さらに ``-ss`` へはこの値を足し戻す(``-ss`` は itsoffset より前の時刻で解釈される)。
    # **``-itsoffset`` を ``input_args`` へ混ぜてはいけない** — ffprobeにこのoptionは無く、
    # "Option not found" で終了コード1を返して何も出力しない(実測)。probeが黙って空を
    # 返すと解像度も尺も既定値へ落ちるため、失敗が非常に見えにくい。
    media_offset: float = 0.0


def _session_dir_for(src, predicate) -> Optional[Path]:
    """``src`` の録画のsession dirのうち ``predicate`` を満たすもの。無ければNone。

    ``src`` はその録画自身のmp4でなければならない。派生物のsuffix(.overlay/.up)が付いた
    pathを渡してもNoneを返す — 派生物の代わりに原本を差し出さないための線引きである。"""
    src = Path(src)
    stem, streamer = layout.artifact_owner(src.name)
    if not stem or src.name != stem + src.suffix or src.suffix != ".mp4":
        return None
    # mp4自身のrootを最優先で見る。ただしそこで終わらせない: 移送は素材とmp4をまとめて
    # 動かすが途中で失敗すると片方だけが移り、実測でDBの331件中28件がその状態だった。
    # mp4のrootだけを見ると、その28件は「素材が無い」ことになる — mp4が原本だった頃は
    # 成果物が残るので露見しにくかったが、素材が原本になった今は録画が丸ごと消える。
    roots = [layout.record_root_of(src)]
    roots += [r for r in layout.record_roots() if r not in roots]
    for root in roots:
        session = layout.session_dir(root, stem, streamer)
        if predicate(session):
            return session
    return None


def session_dir_for(src) -> Optional[Path]:
    """``src`` の録画のHLS session dir。規約外・素材無しならNone。"""
    return _session_dir_for(src, layout.has_media)


def playback_session_dir(src) -> Optional[Path]:
    """この録画が**HLSで再生される**session dir。再生listまで揃っているものに限る。

    素材の有無(``session_dir_for``)より条件が厳しい。時間軸の判断はこちらで行うこと:
    再生がHLSならplayerの秒はmedia軸、mp4ならPTS軸で、DBへ焼き付ける秒はplayerと同じ
    軸でなければならない。再生経路(server._recording_media_dirs)と同じ事実を見る。"""
    return _session_dir_for(src, layout.has_playable_media)


def plays_from_hls(src) -> bool:
    """この録画の再生がHLS(=media軸)になるか。"""
    return playback_session_dir(src) is not None


def has_hls_source(src) -> bool:
    """mp4が無くてもこの録画をHLSから読めるか。"""
    return session_dir_for(src) is not None


def available(src) -> bool:
    """この録画に読める素材が在るか(mp4でも.tsでも)。"""
    return Path(src).is_file() or has_hls_source(src)


@contextlib.contextmanager
def ffmpeg_source(src, prefer_hls: bool = False):
    """``src`` をffmpegの入力として使える形で貸し出す。素材が無ければ SourceMissing。

    mp4が在ればそれをそのまま指す。無ければ採用集合だけのVOD playlistをsession dirへ
    書き出して指し、抜けるときに必ず消す(例外で抜けても消す)。

    ``prefer_hls`` はmp4が在っても .ts を優先する。焼き込みだけがこれを使う: 焼き込みは
    入力を再encodeするので、mp4を経由すると「配信→mp4→焼き込み」で再圧縮が2世代重なる
    (解像度が変わった録画では正規化のre-encodeが挟まるため実際に2回になる)。原本から
    1 passで焼けば1世代で済む。読むだけの下流(文字起こし・切抜き等)には差が無いので、
    余計なplaylist生成を避けて既定はFalseのままにする。"""
    src = Path(src)
    if src.is_file() and not (prefer_hls and has_hls_source(src)):
        yield Source(src, (), False, 0.0)
        return
    session = session_dir_for(src)
    if session is None:
        raise SourceMissing()
    # 同じ録画に別のjobが同時に入ることがあるので、名前は都度ユニークにする。
    playlist = session / (CURATED_PREFIX + uuid.uuid4().hex[:12] + CURATED_SUFFIX)
    written = None
    try:
        written = rec.write_curated_playlist(session, playlist,
                                             layout.streamer_of(session.name) or "")
        if written is None:
            raise SourceMissing()
        logger.info(
            "%s をHLS segmentから読み取ります（%s）", session.name,
            "mp4より優先" if src.is_file() else "mp4がdiskにありません",
            extra={"event": "media.hls_source_used",
                   "ctx": {"src": str(src), "session": str(session),
                           "playlist": str(playlist), "prefer_hls": prefer_hls}},
        )
        yield Source(playlist, tuple(rec.HLS_INPUT_ARGS), True,
                     _container_start_time(playlist))
    finally:
        if written is not None or playlist.exists():
            try:
                playlist.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "一時playlist %s を削除できませんでした", playlist.name,
                    extra={"event": "media.hls_playlist_orphaned",
                           "ctx": {"path": str(playlist)}},
                    exc_info=True,
                )


def _container_start_time(playlist: Path) -> float:
    """playlistを開いたときのcontainer start_time(秒)。読めなければ0。

    5,628 segmentの録画で0.06秒。leaseごとに1回払っても無視できる。"""
    try:
        completed = ffprobe.run_sync(
            ["ffprobe", "-v", "error", *rec.HLS_INPUT_ARGS, "-show_entries",
             "format=start_time", "-of", "default=nk=1:nw=1", str(playlist)],
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        value = float(completed.stdout.strip())
    except (OSError, ValueError):
        logger.warning(
            "%s のcontainer start timeを読み取れないため0として扱います",
            playlist.name,
            extra={"event": "media.hls_start_time_unreadable",
                   "ctx": {"playlist": str(playlist)}},
            exc_info=True,
        )
        return 0.0
    return value if value > 0 else 0.0


def _media_totals(session: Path) -> tuple[int, int, float]:
    """(本数, 合計byte, 最新mtime)。scandirで1度に読む — 束ねる前は1録画5,000本を超える。"""
    count = 0
    total = 0
    newest = 0.0
    with os.scandir(session) as entries:
        for entry in entries:
            if not any(fnmatch.fnmatch(entry.name, pattern)
                       for pattern in layout.MEDIA_GLOBS):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            count += 1
            total += stat.st_size
            newest = max(newest, stat.st_mtime)
    return count, total, newest


def fingerprint(src, prefer_hls: bool = False) -> dict:
    """cacheの鍵に使う素材の指紋。素材が無ければ SourceMissing。

    mp4に対しては ``{"mtime", "size"}`` を、今までの ``src.stat()`` と同じ値で返す
    (既存cacheを無効化しないため)。HLSに対しては ``segments`` を足した3項を返す。

    ``prefer_hls`` は ``ffmpeg_source`` と同じ意味で、**必ず同じ値を渡すこと**。
    実際に読んだ素材と違う方の指紋を鍵にすると、素材が変わっても当たり続ける
    (あるいはその逆で毎回外れる)。

    **playlistのstatでは足りない。** playlistのmtimeはsegmentの入れ替わりを映さないので、
    素材が変わったのに当たり続ける。逆にplaylistの中身だけを鍵にすると、束ね直しで
    毎回外れる。素材そのもの(本数・合計byte・最新mtime)を数えるのが唯一ずれない。
    束ね直しはこの3つを全部動かすので、束ねた直後に1度だけ作り直しになる — 中身は
    byte単位で同じなので無駄な1回だが、逆に取りこぼす側へ倒すよりは安い。"""
    src = Path(src)
    try:
        stat = src.stat()
    except OSError:
        stat = None
    session = session_dir_for(src)
    if stat is not None and not (prefer_hls and session is not None):
        return {"mtime": stat.st_mtime, "size": stat.st_size}
    if session is None:
        raise SourceMissing()
    count, total, newest = _media_totals(session)
    if not count:
        raise SourceMissing()
    return {"mtime": newest, "size": total, "segments": count}


async def resolutions(source: Source) -> set:
    """その録画に現れる ``(w, h)`` の全種類。走査できなければ空。

    keyframeだけを読む走査で、解像度の変更は必ず新しいSPS(=keyframe)を伴うので取りこぼ
    さない。``stream=width,height`` を1組読む書き方をしてはいけない — 混在解像度の録画
    では、その1組は開いた所の値でしかなく全編を代表しない。"""
    return await rec.probe_mp4_resolutions(source.path, tuple(source.input_args))


def resolutions_sync(source: Source) -> set:
    """``resolutions`` の同期版。GPUに張り付いたblocking経路(Up出力)から使う。

    ``recorder.probe_mp4_resolutions`` と同じ走査だが、あちらはasync専用で、workerthread
    から ``asyncio.run`` で呼ぶとplatformごとにsubprocessの起こし方が変わる。走査そのもの
    はffprobeを1本起こすだけなので、bridgeを挟むより同期で書く方が壊れにくい。

    失敗した回の結果を採らないのは本家と同じ理由: keyframe decodeは混んだdiskや壊れた
    frameで途中終了することがあり、その部分listは**単一解像度に見える**ので、そのまま
    採ると混在の録画を均一と誤判定する。"""
    args = ffprobe.keyframe_resolution_args(source.path, source.input_args)
    best: set = set()
    for _ in range(3):
        try:
            completed = ffprobe.run_sync(args, timeout=PROBE_TIMEOUT_SECONDS)
        except OSError:
            logger.warning(
                "%s のkeyframe解像度の走査を実行できませんでした", source.path.name,
                extra={"event": "media.resolution_probe_failed",
                       "ctx": {"src": str(source.path)}},
                exc_info=True,
            )
            return best
        seen = set(ffprobe.parse_resolution_csv(completed.stdout))
        if len(seen) > len(best):
            best = seen
        if completed.ok:
            return seen
        # timeoutを再試行すると待ちが3倍になる。返ってこない入力は3回やっても返らない。
        if completed.timed_out:
            return best
    return best


async def widest_resolution(source: Source) -> Optional[tuple]:
    """その録画に現れる解像度の、幅と高さそれぞれの最大。1つも取れなければNone。

    幅と高さを独立に採るのは、切替でaspectまで変わる録画があるため(実測: 720x1280 と
    432x864 と 320x640 が同居)。どちらか一方の組を出力枠にすると、もう一方は必ずはみ出す
    か余る。両者を包む枠にしておけば、frame側のscale/padで歪みなく収まる。
    ``video_overlay._widest_resolution`` と同じ方針。"""
    found = await resolutions(source)
    if not found:
        return None
    return max(w for w, _ in found), max(h for _, h in found)
