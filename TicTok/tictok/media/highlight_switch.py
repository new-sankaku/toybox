"""highlightの繋ぎ目で、**映像がいつ切り替わり始まり、いつ切り替わり終わるか**を測る。

なぜ要るのか
------------
gift演出の境目(``highlight_segments.start``)は**音**で決めている(:func:`highlight_match._boundary`
がhashの帰属の入れ替わる点を採る)。ところがTikTokのmontageは、音を一瞬で切り替える一方で
**映像には切り替わりの演出を掛ける**。前の場面が縮んで退く・複数の板が滑る、といった動きで
ある。その間、画面に映っているのは**前のgiftの場面**である。

演出は境目を**跨ぐ**。だからgift演出1つの綺麗な映像は「音の境目から音の境目まで」ではなく、
**手前の切り替わりが終わってから、次の切り替わりが始まるまで**である。両端とも測る:

- 頭(:func:`switch_span` の後半) …… 前のgiftの場面が退き切る秒。ここより手前を切ると、
  出力の頭に前のgiftが映る。
- 尻(:func:`switch_span` の前半) …… 次のgiftの場面が現れ始める秒。ここより後ろまで切ると、
  出力の終わりに**次のgiftの演出と場面**が映る —— 実測(視聴者A🐢💤 / Strong Finish の窓)で、
  音の境目 43.750秒に対し次の場面は 42.833秒から現れ、43.4秒には全画面になっていた。窓の
  最後の0.92秒が次のgiftである。1本の中で「2人目のgiftの終わりに3人目のgiftが少し映る」
  形になり、**誰のgiftなのかを誤認させる**。

実測(実物7本・境目29箇所、2026-09-02): 映像が落ち着くのは音の境目より **中央値0.60秒
あと**、範囲は 0.00〜1.47秒。目でも確かめてある ―― ``v1c43ag5000cdab7s000g65hl0000002.mp4``
の 14.512秒(Guardian's Pledge 4999💎)は、+0.45秒まで前の場面(アニメの立ち絵)が縮みながら
退き、板が組み上がるのは +0.9〜1.05秒である。

演出の**始まり**の側は境目を跨ぐ。同じ素材の境目30箇所で、次の場面が音の境目より手前から
現れていたのは3箇所(0.42/0.62/0.92秒手前)で、残りは境目以降だった。少数だが、当たった
3箇所のうち2箇所は6000💎のgiftの窓である。

container側のずれではない。両fileともffprobeで video/audio とも ``start_time=0.000000`` で、
**中身の作りがそうなっている**。

ずれは一定ではない(同じfileの中で +0.07 と +1.47 が同居する)ので、**定数を引いてはいけない**。
境目ごとに測る。

測り方
------
落ち着いた区間の frame の**時間中央値**を「場面の下地」に置き、各frameがその下地にどれだけ
似ているかの曲線を作る。切替の最中は別の絵が映っているので曲線は谷になる。境目1つにつき
下地を2つ採り、**同じ1回の読み出し**から両端を出す:

- 終わり(:func:`_switch_end`) …… 後の場面の下地。**最後に谷から出た点**を答えとする。
  最初に閾値を超えた点ではない。演出は境目の手前から始まることも後から始まることもあり
  (実物にどちらも在る)、最初の交差は「まだ演出が始まっていないだけ」の frame を拾う。
- 始まり(:func:`_switch_start`) …… **同じ後の場面の下地**を使い、落ち着いた所から手前へ
  辿って、似方が「前の内容の水準」まで落ちる点を答えとする。つまり**後の場面が画面に現れ
  始めた点**である。

物差しを2つとも「後の場面」にするのが要点である。前の場面を下地にすると測れない ――
gift演出の中で映っている物はgiftのアニメと無関係に変わるからで、実測(``…95ed0.mp4`` の 0.0〜5.782秒)
では giftのアニメが4.7秒で終わって生の画面に戻り、前の場面を下地にした測りはそこを
切り替わりの始まりと答えた(実際は5.8秒の絞り)。そのgiftの見せ場を0.9秒ぶん捨てることに
なる。後の場面の下地なら、その場面が現れ始めた点を直接指す。

下地に1枚のframeを使ってはいけない。場面自体が動くので物差しが揺れる ―― 1枚基準では
相関の落ち着き先が0.62までしか上がらないgift演出が在り、閾値が甘くなって0.4秒ぶん早い答えを
返した。中央値なら動きは均され、実測で落ち着き先は 0.83〜0.99 になる。

**採らなかった測り方**(どれも実測で外れた):

- frame間差分の高い区間の終わり …… 生放送の動きに埋もれる。29箇所のうち十数箇所で
  探索区間が丸ごと「動いている」と判定された。
- 黒い余白が消える点 …… 縮小の演出では効くが、全画面どうしの溶暗・滑りでは黒が出ない。
  29箇所のうち12箇所で「演出なし」と答え、そのうち複数は目で見て演出が在った。
- 前の場面の下地から離れる点 …… 上記のとおり、gift演出の中の場面替わりを拾う。
"""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

logger = logging.getLogger("tictok.media")

# 採取の解像度。実測の最短の切替が0.2秒なので、30fps(33ms)でようやく形が見える。
# 縦横は :mod:`highlight_match` の差分scanと揃える(highlightは720x1280の縦)。
PROBE_FPS = 30
PROBE_WIDTH = 96
PROBE_HEIGHT = 171

# 境目の手前と後ろをどれだけ見るか。後ろは実測の最大(1.47秒)に下地を採る余裕を足した長さ。
#
# 手前は2つの測りで要る長さが違う。**終わり**を測るには「演出が境目より先に始まっている」
# 場合を掴めればよいので短くてよい(:data:`PROBE_LEAD`)。**始まり**を測るには、前の場面の
# 下地を演出の手前で採り切る必要があるので、実測の最大(境目の1.30秒手前から始まっていた)に
# 下地の長さを足した分が要る(:data:`PROBE_HEAD`)。
PROBE_LEAD = 0.5
PROBE_HEAD = 2.4
PROBE_TAIL = 2.2

# 「後の場面の下地」を採る末尾の長さ。短いと動きが均されず、長いと切替そのものを
# 下地に混ぜてしまう。
PLATE_SECONDS = 0.6

# 下地との相関がこの高さまで上がらないgift演出は、**落ち着いた場面がそもそも無い**。
# 物差しが作れないので測れなかったこととして扱う(それらしい数字を返さない)。
PLATE_MIN_LEVEL = 0.5

# 谷の深さがこれ未満なら「切替の演出は無い」。境目をそのまま映像の頭とする。
DIP_MIN_DEPTH = 0.05

# 谷から下地までの何割を超えたら「戻った」とみなすか。
DIP_CROSS = 0.6

# 「前の内容の水準」から下地までの何割を超えたら、**後の場面が見え始めた**とみなすか。
# :data:`DIP_CROSS` より遥かに小さいのは、測る物が違うからである —— あちらは「切り替わり
# 終わったか」で、こちらは「次のgiftが画面に出ているか」である。少しでも出ていたら、それは
# もう次のgiftの絵で、通しで観ている人はそう読む。
APPEAR_CROSS = 0.15


class SwitchProbeError(RuntimeError):
    """frameが読めなかった。呼び出し側は「測れなかった」として扱う。"""


def _frames(path: Path, start: float, seconds: float) -> np.ndarray:
    args = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(start, 0.0):.3f}",
            "-i", str(path), "-t", f"{seconds:.3f}",
            "-vf", f"fps={PROBE_FPS},scale={PROBE_WIDTH}:{PROBE_HEIGHT},format=gray",
            "-f", "rawvideo", "-"]
    try:
        out = subprocess.run(args, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SwitchProbeError(f"frameが読めませんでした: {path.name} {start:.3f}秒") from exc
    size = PROBE_WIDTH * PROBE_HEIGHT
    count = len(out) // size
    if count == 0:
        raise SwitchProbeError(f"frameが0枚でした: {path.name} {start:.3f}秒")
    return np.frombuffer(out[:count * size], dtype=np.uint8) \
        .reshape(count, PROBE_HEIGHT, PROBE_WIDTH).astype(np.float32)


def _normalized(frame: np.ndarray) -> np.ndarray:
    flat = frame.ravel() - frame.mean()
    spread = float(flat.std())
    return flat / spread if spread > 1e-6 else flat


def _curve(frames: np.ndarray, plate_mask: np.ndarray) -> Optional[np.ndarray]:
    """``plate_mask`` の区間を下地にした、frameごとの似ている度合い。下地が採れなければ None。"""
    if int(plate_mask.sum()) < 3:
        return None
    plate = _normalized(np.median(frames[plate_mask], axis=0))
    size = plate.size
    return np.array([float(np.dot(_normalized(frame), plate)) / size for frame in frames])


def _dip(curve: np.ndarray, plate_mask: np.ndarray, zone: np.ndarray) -> Optional[tuple]:
    """谷の形。``(下地の高さ, 底のindex, 閾値)``。下地が信用できなければ None。

    ``level`` は下地の区間の下側四分位。**平均ではない** —— 場面は動くので、たまたま大きく
    外れたframeに物差しごと引っ張られない値が要る。
    """
    level = float(np.percentile(curve[plate_mask], 25))
    if level < PLATE_MIN_LEVEL:
        # 下地の区間が落ち着いていない。物差しが無いので答えを作らない。
        return None
    if zone.size == 0:
        return None
    bottom = int(zone[int(np.argmin(curve[zone]))])
    floor = float(curve[bottom])
    if level - floor < DIP_MIN_DEPTH:
        return level, bottom, None
    return level, bottom, floor + DIP_CROSS * (level - floor)


def switch_span(path: Path, boundary: float, *, head: float,
                tail: float) -> tuple:
    """境目1つの ``(切り替わりが始まる秒, 切り替わり終わる秒)``。測れなければそれぞれ None。

    **frameの読み出しは1回である。** 両端は同じ区間の同じ frame から、下地を前後で採り分けて
    出す —— 別々に読むと、同じ境目を2度decodeすることになる。

    ``head``/``tail`` は境目の前後に使ってよい長さ(呼び出し側が隣のgift演出との距離から決める)。
    始まりは必ず ``boundary`` 以下、終わりは必ず ``boundary`` 以上で、``boundary`` そのものは
    どちらも「その側に切替の演出は無い」を意味する。
    """
    head = max(min(float(head), PROBE_HEAD), 0.0)
    tail = min(float(tail), PROBE_TAIL)
    if tail < PLATE_SECONDS + 0.4:
        # 下地を採る余裕と、その手前に見る区間が取れない。gift演出が短すぎる。
        return None, None
    # 読み出しの頭をframeの刻みへ丸める。**どこから読み始めたかで答えが動かないため**で、
    # 丸めないと同じ境目を lead 0.5秒で読んだときと head 2.4秒で読んだときに、標本の時刻が
    # 刻みの半分ずれて1frame違う答えが出る(呼び出し側が隣のgift演出との距離から head を決める
    # 以上、これは「隣のgift演出の長さで答えが変わる」ということである)。
    origin = max(math.floor((boundary - head) * PROBE_FPS) / PROBE_FPS, 0.0)
    frames = _frames(path, origin, (boundary + tail) - origin)
    times = origin + np.arange(len(frames)) / PROBE_FPS
    head = boundary - origin
    return (_switch_start(frames, times, boundary, head),
            _switch_end(frames, times, boundary))


def switch_end(path: Path, boundary: float, *, lead: float,
               tail: float) -> Optional[float]:
    """``boundary`` で始まるgift演出の、**映像が落ち着く秒**。測れなければ None。

    境目の**終わりだけ**が要る場所のための入口(:func:`switch_span` の後半)。手前は演出が
    境目より先に始まっている場合を掴めればよいので、:data:`PROBE_LEAD` までで足りる。
    """
    return switch_span(path, boundary,
                       head=min(float(lead), PROBE_LEAD), tail=tail)[1]


def _switch_end(frames: np.ndarray, times: np.ndarray,
                boundary: float) -> Optional[float]:
    """後の場面の下地へ**戻る**点。:func:`switch_span` の後半。"""
    plate_mask = times >= times[-1] - PLATE_SECONDS
    curve = _curve(frames, plate_mask)
    if curve is None:
        return None
    zone = np.where((times >= boundary) & ~plate_mask)[0]
    dip = _dip(curve, plate_mask, zone)
    if dip is None:
        return None
    _level, _bottom, threshold = dip
    if threshold is None:
        return float(boundary)
    below = zone[curve[zone] < threshold]
    if below.size == 0:
        return float(boundary)
    return round(float(times[int(below[-1]) + 1]), 3)


def _switch_start(frames: np.ndarray, times: np.ndarray, boundary: float,
                  head: float) -> Optional[float]:
    """**後の場面が見え始める**点。:func:`switch_span` の前半。

    物差しは終わりと同じ「後の場面の下地」1つである。**前の場面を物差しにしてはいけない。**
    gift演出の中で映っている物はアニメと無関係に変わる —— 実測(``…95ed0.mp4`` の 0.0〜5.782秒)で
    giftのアニメが 4.7秒で終わって生の画面へ戻り、前の場面を下地にした測りはそこを切り替わり
    の始まりと答えた(実際の切り替わりは5.8秒の絞りである)。0.9秒ぶん、そのgiftの見せ場を
    捨てることになる。

    後の場面の下地なら、**その場面が画面に現れ始めた点**を直接指す。窓の尻をここで止めれば、
    次のgiftの絵は1frameも入らない。

    落ち着いた区間から手前へ辿り、下地との似方が「前の内容の水準」まで落ちる点を採る。
    その水準(``base``)は境目のずっと手前から採る —— 演出の始まる前の、前の内容が後の場面に
    どれだけ似ているかである。
    """
    if head < PLATE_SECONDS + 0.6:
        # 演出の手前に「前の内容の水準」を採る余裕が無い。前のgift演出が短いときに起きる。
        return None
    plate_mask = times >= times[-1] - PLATE_SECONDS
    curve = _curve(frames, plate_mask)
    if curve is None:
        return None
    zone = np.where(~plate_mask)[0]
    dip = _dip(curve, plate_mask, zone)
    if dip is None:
        return None
    level, _bottom, threshold = dip
    if threshold is None:
        return float(boundary)
    head_mask = times <= times[0] + PLATE_SECONDS
    if int(head_mask.sum()) < 3:
        return None
    base = float(np.percentile(curve[head_mask], 75))
    if level - base < DIP_MIN_DEPTH:
        # 前の内容が後の場面と見分けられない。**それらしい秒を返さない** ―― 見分けられない
        # のだから、どこで切っても「次のgiftが映っている」ことを否定できない。
        return None
    rise = base + APPEAR_CROSS * (level - base)
    index = int(np.argmax(plate_mask))
    while index - 1 >= 0 and curve[index - 1] > rise:
        index -= 1
    # 演出が境目より後ろで始まっていれば、このgift演出の映像は境目まで綺麗である。
    return round(min(float(times[max(index - 1, 0)]), float(boundary)), 3)


def video_spans(path: Path, spans: Sequence[Sequence[float]], *, on_done=None) -> list:
    """gift演出ごとの ``(映像の頭, 映像の尻)``。``spans`` は ``(start, end)`` を並び順に並べたもの。

    境目1つの測定が、**手前のgift演出の尻と後ろのgift演出の頭の両方**になる。だから測るのは境目の
    数だけで、gift演出の数ではない。

    先頭のgift演出の頭と最後のgift演出の尻は、fileの端そのものである。退場していく前の場面も、
    入ってくる次の場面も無い ―― **測らずに端を返す**(測れなかったのとは別のこと。切る場所を
    動かす理由が無い、が正しい)。

    1つ測れなくても残りは返す。境目ごとに独立した測定なので、片方の失敗を全体の失敗へ
    広げる理由が無い。``on_done`` は境目1つが終わるごとに呼ばれる(進み具合の報告用)。

    手前をどこまで見てよいかは、**前のgift演出の映像の頭**までである。そこより手前は前の境目の
    演出なので、下地に混ぜると物差しが壊れる。並びの手前から測るので、その値は既に出ている。
    """
    rows = [[float(span[0]), float(span[1])] for span in spans]
    out: list = [[row[0], row[1]] for row in rows]
    for index in range(1, len(rows)):
        boundary = rows[index][0]
        # 前のgift演出の綺麗な映像が始まる秒。測れていなければ音の境目まで。
        floor = out[index - 1][0]
        if floor is None:
            floor = rows[index - 1][0]
        try:
            began, ended = switch_span(Path(path), boundary,
                                       head=boundary - floor - 0.05,
                                       tail=rows[index][1] - boundary - 0.05)
        except SwitchProbeError:
            logger.warning("境目 %d の映像の切り替わりが測れませんでした（%s）", index, path,
                           exc_info=True,
                           extra={"event": "highlight.switch_probe_failed",
                                  "ctx": {"path": str(path), "idx": index,
                                          "start": boundary}})
            began, ended = None, None
        out[index - 1][1] = began
        out[index][0] = ended
        if on_done:
            on_done()
    return [tuple(row) for row in out]
