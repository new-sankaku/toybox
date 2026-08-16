"""切り抜き候補の「点」から、short 1本ぶんの範囲を確定する。

盛り上がり検出(:mod:`tictok.core.spike`)が返すのは時刻であって範囲ではない。既存の候補APIは
そこへ設定の固定窓を被せているだけなので、出てくる範囲は**話の途中で始まり、話の途中で
終わる**。人が手で切るときに実際にやっているのは、その固定窓を発話や無音の切れ目まで
動かす作業で、この moduleはそれだけを行う。

入力は全て呼び出し側が集めた素の観測(発話segment・無音span・章)で、ここはI/Oを持たない。
判定を1箇所に閉じるためで、同じ範囲確定を画面のpreviewと一括生成の両方が使う。

## 確定の順序

1. **山を置く**。候補の中心を ``peak_position`` の位置へ据え、狙いの尺ぶんの窓を作る。
   中央に置かないのは、shortが「何が起きるか」を見せてから山へ入る必要があるためで、
   山が頭に来ると前置きの無い動画になる。
2. **章で挟む**。山を含む章の外へは出さない。跨いだ範囲は話題が2つ混ざったshortになる。
3. **端を吸着させる**。発話の切れ目・無音の切れ目のうち近い方へ寄せる。動かしてよい距離に
   上限を置き、それを超える吸着先しか無い端は**動かさない**。
4. **尺を検算する**。下限に届かない/上限を超える範囲は**捨てる**。縮めて無理やり通すと、
   話の途中で切れた物が「成功した成果物」として出てくる。

## 捨てた候補は捨てたと言う

各段で落ちた候補は理由つきで返す(:func:`plan_ranges` の ``rejected``)。黙って数が減ると、
「検出が弱いのか、範囲確定で落ちているのか」を後から切り分ける手段が無くなる。
"""

from typing import Optional

# 吸着先の種別。どれで寄せたかを成果物側へ残すため、名前を値として持つ。
SNAP_SPEECH = "speech"
SNAP_SILENCE = "silence"

# 範囲を捨てた理由。画面と log が同じ語で名乗れるよう定数にする。
REJECT_TOO_SHORT = "too_short"
REJECT_TOO_LONG = "too_long"
REJECT_OVERLAP = "overlap"
REJECT_NO_ROOM = "no_room"

REJECT_LABELS = {
    REJECT_TOO_SHORT: "尺が下限に届きません",
    REJECT_TOO_LONG: "尺が上限を超えます",
    REJECT_OVERLAP: "先に採った範囲と重なります",
    REJECT_NO_ROOM: "録画の端で狙いの尺を取れません",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def speech_boundaries(segments: list) -> tuple:
    """発話segmentから、頭出しに使える点と切り終わりに使える点を作る。

    戻り値は ``(開始に使える点, 終了に使える点)``。開始は各segmentの ``start``(そこから
    話し始める)、終了は各segmentの ``end``(そこで話し終える)である。両者を1つのlistに
    混ぜてはならない — segmentの ``end`` を開始位置に採ると、次の発話の途中から始まる。
    """
    starts = []
    ends = []
    for segment in segments or []:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        starts.append(start)
        ends.append(end)
    return sorted(starts), sorted(ends)


def silence_boundaries(spans: list) -> tuple:
    """無音spanから、頭出しに使える点と切り終わりに使える点を作る。

    無音が明けた瞬間(``end``)が開始の吸着先、無音が始まる瞬間(``start``)が終了の吸着先。
    発話segmentと逆向きになるのは、無音spanが「音の無い区間」を表しているためである。
    """
    starts = []
    ends = []
    for span in spans or []:
        try:
            start = float(span["start"])
            end = float(span["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        starts.append(end)
        ends.append(start)
    return sorted(starts), sorted(ends)


def _nearest(points: list, target: float, limit: float,
             low: float, high: float) -> Optional[float]:
    """``target`` に最も近い点。``limit`` より遠い点と、[low, high] の外は採らない。"""
    best = None
    best_distance = None
    for point in points:
        if point < low or point > high:
            continue
        distance = abs(point - target)
        if distance > limit:
            continue
        if best_distance is None or distance < best_distance:
            best, best_distance = point, distance
    return best


def _snap_edge(target: float, preset: dict, speech: list, silence: list,
               low: float, high: float) -> tuple:
    """端1つを吸着させる。戻り値は ``(位置, 吸着の種別 or None)``。

    両方の吸着先が有効なときは近い方を採る。種別ごとの優先順位は付けない — 発話境界と
    無音境界は同じ現象を別の観測で見ているだけで、どちらが正しいという関係に無い。
    """
    limit = float(preset["snap_max_shift_seconds"])
    if limit <= 0:
        return target, None
    picks = []
    if int(preset["snap_speech"]) and speech:
        point = _nearest(speech, target, limit, low, high)
        if point is not None:
            picks.append((abs(point - target), point, SNAP_SPEECH))
    if int(preset["snap_silence"]) and silence:
        point = _nearest(silence, target, limit, low, high)
        if point is not None:
            picks.append((abs(point - target), point, SNAP_SILENCE))
    if not picks:
        return target, None
    _, point, kind = min(picks, key=lambda item: item[0])
    return point, kind


def _chapter_bounds(chapters: list, peak: float) -> Optional[tuple]:
    """``peak`` を含む章の区間。章が無い/どの章にも入らないならNone。

    どの章にも入らないときに近い章へ寄せないのは、章立てが録画全体を覆う保証を持たない
    ためである(冒頭が章にならない録画が実在する)。根拠の無い挟み込みはしない。
    """
    for chapter in chapters or []:
        try:
            start = float(chapter["start"])
            end = float(chapter["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= peak < end:
            return start, end
    return None


def plan_range(candidate: dict, preset: dict, *, duration: float,
               segments: Optional[list] = None, silences: Optional[list] = None,
               chapters: Optional[list] = None) -> dict:
    """候補1件から short 1本ぶんの範囲を確定する。

    ``candidate`` は候補APIの1件(``start`` / ``end`` を持つ)。その中心を山とみなす —
    候補は移動窓を畳んだ区間で、畳んだ後に「どのbucketが最も外れていたか」は残っていない
    ためである。中心以外を山と呼ぶには、畳む前の窓を持ち回す必要がある。

    戻り値は範囲(``start`` / ``end``)と、確定の過程(``snapped`` / ``chapter`` /
    ``shift_seconds``)。確定できなかった場合は ``rejected`` に理由が入り、範囲は返らない。
    """
    peak = (float(candidate["start"]) + float(candidate["end"])) / 2.0
    target = float(preset["target_seconds"])
    minimum = float(preset["min_seconds"])
    maximum = float(preset["max_seconds"])
    position = float(preset["peak_position"])

    low, high = 0.0, float(duration)
    chapter = _chapter_bounds(chapters, peak) if int(preset["chapter_clamp"]) else None
    if chapter is not None:
        low, high = max(low, chapter[0]), min(high, chapter[1])
    if high - low < minimum:
        # 章が下限より短い、または録画の端。ここで伸ばすと章の外へ出るので伸ばさない。
        return {"rejected": REJECT_NO_ROOM, "peak": round(peak, 3),
                "room_seconds": round(max(0.0, high - low), 3)}

    start = peak - target * position
    end = start + target
    # 端に当たったぶんは反対側へ回す。窓を短くするのではなく位置をずらすのは、狙いの尺を
    # 保ったまま録画の端に収めるため(尺の判定は最後にまとめて行う)。
    if start < low:
        end += low - start
        start = low
    if end > high:
        start -= end - high
        end = high
    start = _clamp(start, low, high)
    end = _clamp(end, low, high)

    speech_starts, speech_ends = speech_boundaries(segments)
    silence_starts, silence_ends = silence_boundaries(silences)
    shift = float(preset["snap_max_shift_seconds"])
    # 吸着で山を範囲の外へ押し出さないよう、動ける範囲を山の手前/後ろで止める。
    snapped_start, start_kind = _snap_edge(
        start, preset, speech_starts, silence_starts, low, min(peak, high))
    snapped_end, end_kind = _snap_edge(
        end, preset, speech_ends, silence_ends, max(peak, low), high)

    length = snapped_end - snapped_start
    if length > maximum:
        # 吸着で上限を超えたら、遠くへ動いた側の吸着だけを取り消す。両方戻すと、吸着が
        # 効かない録画と区別が付かなくなる。
        start_moved = abs(snapped_start - start)
        end_moved = abs(snapped_end - end)
        if start_moved >= end_moved and start_kind is not None:
            snapped_start, start_kind = start, None
        elif end_kind is not None:
            snapped_end, end_kind = end, None
        length = snapped_end - snapped_start

    result = {
        "start": round(snapped_start, 3),
        "end": round(snapped_end, 3),
        "seconds": round(length, 3),
        "peak": round(peak, 3),
        "snapped": {"start": start_kind, "end": end_kind},
        "shift_seconds": {"start": round(snapped_start - start, 3),
                          "end": round(snapped_end - end, 3)},
        "snap_limit_seconds": shift,
        "chapter": None if chapter is None else {
            "start": round(chapter[0], 3), "end": round(chapter[1], 3)},
    }
    if length < minimum:
        return {**result, "rejected": REJECT_TOO_SHORT}
    if length > maximum:
        # 間の詰めで上限へ収める見込みがあるかは、実際に無音を測るまで判らない。ここでは
        # 「詰める設定なら通す」とはせず、詰めた後の尺で判定する側(tighten)へ委ねる。
        if not int(preset["tighten"]):
            return {**result, "rejected": REJECT_TOO_LONG}
        result["needs_tighten"] = True
    return result


def _overlap_seconds(a: dict, b: dict) -> float:
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def plan_ranges(candidates: list, preset: dict, *, duration: float,
                segments: Optional[list] = None, silences: Optional[list] = None,
                chapters: Optional[list] = None, limit: Optional[int] = None,
                taken: Optional[list] = None,
                max_overlap_ratio: float = 0.25) -> dict:
    """候補listを範囲listへ落とす。重なる範囲は強い方だけを残す。

    ``taken`` は既に存在する範囲(過去に作ったshortや、人が付けた見どころ)。同じ場面を
    二度出さないための入力で、ここへ渡された範囲は候補の重なり判定の相手にはなるが、
    戻り値には現れない。

    重なりの判定を「候補の点」ではなく**確定後の範囲**で行うのが要点である。候補どうしが
    離れていても、吸着と尺の付与で範囲は膨らむので、点で見て通した2件が同じ場面のshortに
    なることがある。
    """
    ordered = sorted(candidates or [],
                     key=lambda c: float(c.get("zscore") or 0.0), reverse=True)
    kept: list = []
    rejected: list = []
    existing = [dict(t) for t in (taken or [])]
    for candidate in ordered:
        plan = plan_range(candidate, preset, duration=duration, segments=segments,
                          silences=silences, chapters=chapters)
        plan["candidate"] = candidate
        if plan.get("rejected"):
            rejected.append(plan)
            continue
        clash = next(
            (other for other in kept + existing
             if _overlap_seconds(plan, other) > plan["seconds"] * max_overlap_ratio),
            None)
        if clash is not None:
            rejected.append({**plan, "rejected": REJECT_OVERLAP,
                             "overlaps": {"start": clash["start"], "end": clash["end"]}})
            continue
        kept.append(plan)
        if limit is not None and len(kept) >= limit:
            break
    kept.sort(key=lambda p: p["start"])
    return {"ranges": kept, "rejected": rejected}
