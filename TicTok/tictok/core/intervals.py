"""時間区間(wall-clock)の集合演算。

Battle窓・コラボ窓のように「重なり得る区間の集まり」から実時間を出す処理は、解析
(analytics)と配信者profile(storage)の両方に要る。二重に持つと片方だけ直った時に
同じ画面の数字が食い違うため、pureな1箇所へ寄せる。

区間は (start, end) のtupleで、端は [start, end) の半開区間として扱う。
"""


def merge_intervals(intervals: list) -> list:
    """[(start,end),...] を重なり/隣接を統合してソート済み非重複区間へ。"""
    clean = [(a, b) for a, b in intervals if b > a]
    if not clean:
        return []
    clean.sort()
    merged = [list(clean[0])]
    for a, b in clean[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def subtract_intervals(base: list, cut: list) -> list:
    """base区間群から cut区間群を差し引く(base, cut は非重複ソート済み前提でなくてよい)。"""
    base = merge_intervals(base)
    cut = merge_intervals(cut)
    result = []
    for a, b in base:
        segments = [(a, b)]
        for ca, cb in cut:
            next_segments = []
            for sa, sb in segments:
                if cb <= sa or ca >= sb:
                    next_segments.append((sa, sb))
                    continue
                if ca > sa:
                    next_segments.append((sa, min(ca, sb)))
                if cb < sb:
                    next_segments.append((max(cb, sa), sb))
            segments = next_segments
        result.extend(s for s in segments if s[1] > s[0])
    return result


def in_intervals(t: float, intervals: list) -> bool:
    """t が非重複ソート済み区間群のいずれかに入るか(端は[start,end))。"""
    for a, b in intervals:
        if a <= t < b:
            return True
        if a > t:
            break
    return False


def total_span(intervals: list) -> float:
    return sum(b - a for a, b in intervals)
