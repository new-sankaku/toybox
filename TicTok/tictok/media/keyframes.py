"""keyframe走査。smart cut(先頭GOPだけ再encodeして要求どおりのIN点で切る)の土台。

stream copyはkeyframeからしか始められない。どのkeyframeから始まるかを**事前に**知る手段が
無いままだと、切り出しは要求と無関係な位置から始まる(:mod:`tictok.media.clipper` の実測:
keyframe間隔は録画ごとに2.1秒〜37.6秒)。ここはその位置を事実として返すだけの層で、
どう切るかは呼び出し側が決める。

== 秒の10進表現を通さない ==

``pts_time`` の10進文字列も ``float`` も使わず、**整数ptsと ``Fraction(time_base)`` のまま**
持ち回る。:mod:`tictok.media.concat` の実測では、keyframe時刻を秒で持ち回ると
**0.0003秒の丸めで1 GOPぶん手前へ飛び、16.3秒の切り出しが33.9秒になる**。丸めが1回でも
入れば、その後どれだけ正確に計算しても位置は戻らない。

== 走査窓 ==

全編走査は高価なので ``-read_intervals`` で窓を切る(渡し方は :func:`video_keyframes` 参照 —
``%+<尺>`` 形式は実素材で空振りする)。窓は ``at`` から
**前向き**なので、狙点の**手前**のkeyframe(``seek_target`` がHLSで使う ``k_prev``)が要る
場合、呼び出し側が ``at`` を狙点より手前へ置く。窓の広さは引数で受け、設定化は
呼び出し側の責務にする。

戻り値を窓で切り直さないのは、ffprobeのseekが窓の外の packet も返すため。窓の先頭より手前の
keyframeが返ることがある(seekは直前のkeyframe近辺から読み始める)。事実なので黙って捨てず、
そのまま返す。窓内に1つもkeyframeが無ければ ``NoKeyframes`` を送出する(黙って窓を広げ続け
ない)。

窓が素材の終端より後ろだったときの出方はdemuxerで違う(いずれも実測):

- HLS playlist: ffprobeがseekに失敗し終了コード1を返す → ``RuntimeError``
- 生の .ts: seekが終端へ丸められ**末尾のpacket**が返る → 窓外のkeyframeがそのまま戻る

``NoKeyframes`` は ``RuntimeError`` を継承しているので、呼び出し側が「その窓では切れない」を
1つで捕まえたければ ``RuntimeError`` を見ればよい。

== pts が N/A のpacket ==

MPEG-TSのsegment境界直後など、``pts`` が ``N/A`` のpacketが**正常に**混ざる(実測で全packetの
約2.4%)。``float()`` に渡せば例外になり、走査そのものが失敗したように見える — この落とし穴で
実際に誤診が起きている。位置を決められないpacketなので、keyframeであっても除いて数えない。

== media軸 ==

``-read_intervals`` の絶対時刻も ``packet=pts`` も、入力container自身の軸で解釈・出力される。
HLSのsegmentは0始まりではない(``hls_source.Source.media_offset``、実測1.402秒)ので、窓の
指定には ``media_offset`` を**足し**、返す時刻からは**引く**。入出力はどちらもmedia軸で揃う。

== ``-ss`` の着地(合成clipでの実測) ==

keyframe2秒間隔・container start_time 1.4667秒の素材を作り、``-ss`` を12点sweepして着地を
測った(``-ss X -i src -to E -copyts -c copy``、ffmpeg 2026-06-10 build)。media軸のkeyframeは
0/2/4/6/8秒:

===================  ==================================================
入力の開き方         着地
===================  ==================================================
HLS playlist         ``X`` **未満**で最後のkeyframe。``-ss`` はmedia軸の秒
                     そのもの(ffmpegがcontainer start_timeを足すため)
mp4                  ``X`` 以下で最後のkeyframe
生の .ts を直接      ``X`` **より後ろ**のkeyframe(HLS経由より1 GOP遅い)
===================  ==================================================

ここから2つ:

- **keyframeちょうどを狙うと1 GOP手前へ落ちる**。``-ss 6.00``(keyframeそのもの)の着地は
  4.0秒だった。µs へ丸めた ``-ss`` とstream time_baseの端数が一致しないためで、
  ``concat`` が記録する「16.3秒が33.9秒になる」と同じ現象を合成clipでも再現できる。
  ``seek_target`` が半GOP内側を狙うのはこれを避けるため(``-ss 6.90`` / ``7.40`` はどちらも
  6.0秒に着地した)。
- 生の .ts を ``-i`` に渡すと着地が1 GOPずれる。:mod:`tictok.media.hls_source` は必ずHLS
  playlist経由で開くので、そこを迂回して .ts を直接読ませてはいけない。

== 着地の検証は必須 ==

``concat`` の実測では、HLS入力は要求より後ろのkeyframeへ飛んで内容を失うことがある
(実録画の密sweepで25点中3点=12%、最大1.789秒)。上の合成clip(segmentが2秒で揃い、各segmentが
keyframeで始まる)ではこの飛びは再現しなかったので、条件は実録画側にある。``first_packet`` は
出来たfileの先頭packetを返すだけの関数で、これを突き合わせずに成功と見なしてはいけない。
合わなければ**失敗させる**のは呼び出し側の責務で、ここは事実だけを返す(fallbackしない)。
"""

from __future__ import annotations

import bisect
import logging
from fractions import Fraction
from pathlib import Path
from typing import Optional

from tictok.core import cancel
from tictok.core import ffprobe

logger = logging.getLogger(__name__)

# packetとstreamを1回のffprobeで取る。csv=p=1 は section名を先頭に付けるので、混ざっても
# 行ごとに見分けられる(p=0 では見分けられない)。
PROBE_ENTRIES = "packet=pts,flags:stream=time_base"
PROBE_FORMAT = ("-of", "csv=p=1")


class NoKeyframes(RuntimeError):
    """走査窓にkeyframeが1つも無かった。"""


def _probe_command(input_args, path, extra: list) -> list:
    return [
        "ffprobe", "-v", "error", *input_args, "-select_streams", "v:0", *extra,
        "-show_entries", PROBE_ENTRIES, *PROBE_FORMAT, str(path),
    ]


async def _run_probe(cmd: list, path) -> str:
    """ffprobeを1本走らせて標準出力を返す。失敗はRuntimeErrorにする。"""
    result = await ffprobe.run(cmd)
    cancel.check_cancelled()
    if not result.ok:
        detail = result.stderr.strip()
        logger.error(
            "%s のkeyframeの走査に失敗しました", Path(path).name,
            extra={"event": "keyframes.probe_failed",
                   "ctx": {"src": str(path), "returncode": result.returncode,
                           "stderr": detail[:2000]}},
        )
        raise RuntimeError(f"keyframeを走査できませんでした（{Path(path).name}）: {detail[:300]}")
    return result.stdout


def _parse_probe(text: str) -> tuple[Optional[Fraction], list]:
    """``(time_base, [(pts, keyframeか), ...])``。``pts`` が読めない行は落とす。

    行は ``packet,<pts>,<flags>`` と ``stream,<time_base>``。実際のffprobeは
    MPEG-TSでは各行の末尾に空fieldを1つ足し、programを持つ入力では ``program,stream,...``
    も出す(いずれも実測)ので、field数ではなく先頭のsection名で判別する。"""
    time_base = None
    packets = []
    for line in text.splitlines():
        parts = line.strip().split(",")
        if parts[0] == "program" and len(parts) > 1 and parts[1] == "stream":
            parts = parts[1:]
        if parts[0] == "packet" and len(parts) >= 3:
            try:
                pts = int(parts[1])
            except ValueError:
                continue
            packets.append((pts, parts[2].startswith("K")))
        elif parts[0] == "stream" and len(parts) >= 2 and time_base is None:
            try:
                time_base = Fraction(parts[1])
            except (ValueError, ZeroDivisionError):
                continue
    return time_base, packets


async def video_keyframes(source, at: float, window: float) -> list:
    """``[at, at+window)`` を走査して得たkeyframe時刻(media軸・秒)のlist。

    ``source`` は :class:`tictok.media.hls_source.Source`。時刻は ``Fraction`` のままで、
    昇順・重複なし。1つも無ければ :class:`NoKeyframes`。

    packetはDTS順に出るのでptsは単調ではない(実測)。並べ替えてから返す。"""
    if window <= 0:
        raise ValueError("走査窓は正の秒数で指定してください。")
    offset = Fraction(source.media_offset)
    start = float(at) + float(source.media_offset)
    span = window if start >= 0 else window + start
    start = max(0.0, start)
    if span <= 0:
        raise ValueError("走査窓が入力の先頭より手前で終わっています。")

    # 窓は ``start%+span`` ではなく **絶対終端** ``start%end`` で渡す。実HLS録画での実測では、
    # seek直後の先頭packetの ``pts`` が ``N/A`` だと ``+span`` 形式は尺を決められず、その1
    # packetだけを返して読むのを止める(45秒窓でpacket 0本・keyframe 0本)。同じ窓を絶対終端で
    # 渡せば1,131 packet・keyframe 23本が返る。``pts=N/A`` はMPEG-TSのsegment境界で正常に
    # 混ざるものなので、``+span`` 形式は実素材では走査が丸ごと空振りする。
    text = await _run_probe(
        _probe_command(source.input_args, source.path,
                       ["-read_intervals", f"{start:.6f}%{start + span:.6f}"]),
        source.path,
    )
    time_base, packets = _parse_probe(text)
    if time_base is None:
        raise RuntimeError(f"time_baseを読めませんでした（{Path(source.path).name}）。")
    keys = sorted({pts * time_base - offset for pts, is_key in packets if is_key})
    if not keys:
        raise NoKeyframes(
            f"{at:.3f}秒から{window:.3f}秒の範囲にkeyframeがありません"
            f"（{Path(source.path).name}）。"
        )
    return keys


def first_at_or_after(keys: list, t) -> Optional[Fraction]:
    """``keys``(昇順)のうち ``t`` 以上で最初のもの。無ければNone。"""
    index = bisect.bisect_left(keys, t)
    return keys[index] if index < len(keys) else None


def exact_target(k, boundary) -> Fraction:
    """``k`` **ちょうど**から始めさせたいときに ``-ss`` へ渡す時刻。

    ``k`` と ``boundary`` の中点。``boundary`` は「``k`` の次のkeyframe」だが、そこまで走査
    していなければ「``k`` より後ろで、間にkeyframeが無いと分かっている時刻」でよい(切り出し
    範囲の終端など)。半GOP内側を狙う理由は :func:`seek_target` と同じで、境界ちょうどを渡すと
    1 GOP手前へ落ちる。

    smart cutの尾側はこれを使う。:func:`seek_target` のHLS分岐(``k_prev`` 側へ寄せる)は
    **使えない**: あちらは前置きを許して欠落を防ぐ形なので、通常は ``k_prev`` に着地し、
    再encodeしたhead部と内容が重複する。前へ落ちても後ろへ飛んでも壊れる用途なので、
    ここは中点を狙って**着地を実測で検証する**以外に無い(``concat`` の実測でHLSは12%の確率で
    後ろへ飛ぶ)。"""
    k, boundary = Fraction(k), Fraction(boundary)
    if boundary <= k:
        raise ValueError("境界が狙点以前にあります。")
    return (k + boundary) / 2


async def avg_frame_seconds(source) -> Fraction:
    """1 frameの秒数(``avg_frame_rate`` の逆数)。

    着地検証の許容差に使う。読めない・0のときは**例外**にする: 許容差を勝手に決めると、
    内容を失った出力を「1 frame以内」と言って通す側へ倒れる。"""
    text = await _run_probe(
        ["ffprobe", "-v", "error", *source.input_args, "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0", str(source.path)],
        source.path,
    )
    for line in text.splitlines():
        try:
            rate = Fraction(line.strip())
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            return 1 / rate
    raise RuntimeError(
        f"frame rateを読めなかったため着地を検証できません（{Path(source.path).name}）。")


def seek_target(k, k_prev, k_next, is_hls: bool) -> Fraction:
    """``k`` から始めさせたいときに ``-ss`` へ渡す時刻。

    **境界の際を狙わない**のが要点。``-ss T -i src`` のstream copyは「Tの直前のkeyframe」から
    始まるので、Tをkeyframeそのものに置くと、秒への丸め・container側の僅差・seekの実装差の
    どれか1つで1 GOPぶん手前(あるいは後ろ)へ落ちる。GOPの内側へ半GOPぶん寄せ、狙点と境界の
    距離を最大化する。

    - 通常入力: ``k`` と ``k_next`` の中点。手前へ落ちても後ろへ流れても ``k`` に留まる。
    - HLS入力: ``k_prev`` と ``k`` の中点。HLSは**要求より後ろのkeyframeへ飛ぶ**ことがある
      (``concat`` の実測で12%)。1つ手前の窓を狙っておけば、飛んだ先が ``k`` になる。

    HLS側は**内容を失わないことを、狙点の正確さより優先している**。合成clipで測った通常の
    着地は「要求未満で最後のkeyframe」なので、飛ばなかった回はこの中点は ``k_prev`` に着地する
    — ``k`` からは1 GOPぶん手前で、その差はstream copyでは元々避けられない前置き
    (``reel`` 参照)と同じものだが、smart cutでは**再encodeするGOPが1つ増える**(実録画の
    keyframe間隔は最大37.6秒)。前へ落ちるのは呼び出し側で詰められるが、後ろへ飛んだ分は
    取り戻せないので、高い方の代償を選んでいる。着地は ``first_packet`` で必ず確かめること。

    必要な隣が ``None`` のときは ``ValueError``。ここで ``k`` そのものへ倒すと、上の丸めに
    そのまま当たる — 窓を広げて隣を取るか、その境界を諦めるかは呼び出し側が決める。"""
    k = Fraction(k)
    if is_hls:
        if k_prev is None:
            raise ValueError("HLS入力では直前のkeyframeが要ります（走査窓を手前へ広げてください）。")
        k_prev = Fraction(k_prev)
        if k_prev >= k:
            raise ValueError("直前のkeyframeが狙点以降にあります。")
        return (k_prev + k) / 2
    if k_next is None:
        raise ValueError("直後のkeyframeが要ります（走査窓を後ろへ広げてください）。")
    return exact_target(k, k_next)


async def first_packet(path) -> tuple:
    """``path`` の先頭video packetの ``(pts秒, keyframeか)``。読めなければ ``(None, False)``。

    着地の検証専用。時刻はそのfile自身の軸で、media軸へは直さない(``-copyts`` を付けた出力は
    入力の絶対時刻を保つので、要求と突き合わせるならその分は呼び出し側が扱う)。**muxerが足す
    分も呼び出し側が見込むこと** — 合成clipでの実測で、mpegts muxerは出力ptsを既定で
    ちょうど+1.4秒ずらし(``-muxdelay 0 -muxpreload 0`` で消える)、mp4 muxerは出力の
    time_baseへ丸めた(7.466667秒→7.466秒)。``concat.cut_part`` の中間fileは ``-f mpegts``
    なので、前者はそのまま当たる。

    ``pts`` が ``N/A`` の先頭packetもあり得るので、``(None, ...)`` は「着地位置が不明」で
    あって「先頭がkeyframeでない」ではない。判定できないことを判定できたことにしない。"""
    text = await _run_probe(
        _probe_command((), path, ["-read_intervals", "%+#1"]), path)
    time_base, packets = _parse_probe(text)
    if time_base is None or not packets:
        return None, False
    pts, is_key = packets[0]
    return pts * time_base, is_key
