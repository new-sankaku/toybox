"""再生の速度計画 — 誰も喋っていない時間を速く流すための区間表。

== 声が在るかは、声の計器で測る ==

最初の版は「誰か喋っているか」を文字起こしの語の時刻で代用していた。実録画4本で測ると
**速い区間の4.4〜43.8%が実際には声**で、発声の入りが中央値0.29〜0.62秒(最大7.2秒)ぶん
速いまま流れていた。語の時刻はVADより +0.22〜+0.30秒 遅れており、前後に置いた0.1〜0.2秒の
余裕では構造的に足りない。語の時刻は「何と言ったか」を解くmodelの副産物であって、
「声が在るか」の測定ではない。

いまは ``media/voice.py``(Silero VAD)が答える。同じ4本で**声の食い込みは0%**になり、倍率は
落ちなかった(語ベース2.16〜2.64x に対し 2.05〜2.55x)。文字起こしも要らなくなった — 語の時刻を
持つのは387件中209件しか無く、語ベースの版はそれ以外で何もできなかった。

音量で測る道を採らない理由は[SILENCE_SKIP]と同じで、配信はBGMとゲーム音で静かではない。
実測1本では静かな時間が尺の3.3%しか無い一方、誰も喋っていない時間は50.3%あった。無音skipも
同じVADへ移ったので、いま2つを分けているのは「飛ばすか速度を変えるか」だけである(同時には
使わない)。

== 飛ばさない ==

区間は飛び先ではなく**速度**である。seekしないので decoder flush が起きず、0.5秒級の
切り替えでも音が途切れない。そして判定が外していた場所は「速く流れる」だけで、失われない。

== 反応は内容として扱う ==

VADは声しか見ない。笑い・叫び・息を呑む音・拍手は語にも声にもならないことがあり、実測では
反応132〜143秒のうち74〜121秒をVADが拾えていなかった。そこを ``laugh_audio.reaction_spans``
で補う。広げる代償はほぼ無い(class listを笑いだけから17 classへ広げても倍率は0.03〜0.08しか
動かない)ので、class listは狭くではなく広く取る。

== 判定できない録画では計画を出さない ==

声profileが無ければ空の計画を返す。それらしい計画を出すより、画面が理由を名乗れる空の方が良い。
"""
from typing import Optional

from tictok.core.config import (
    get_pace_fast_rate,
    get_pace_onset_guard_seconds,
    get_pace_fast_volume,
    get_pace_lead_seconds,
    get_pace_min_fast_seconds,
)


def _merge(spans: list) -> list:
    """開始順に並べ、重なり・隣接を束ねる。"""
    merged: list = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def pace_plan(duration_seconds: float, speech: Optional[list],
              reactions: Optional[list] = None) -> dict:
    """速く流してよい区間と、その計画に使った値を返す。

    ``speech`` は ``voice.speech_spans`` の戻り、``reactions`` は
    ``laugh_audio.reaction_spans`` の戻り(どちらも ``{"start", "end"}`` の列)。

    戻り値の ``fast`` は「内容を前後へ広げた区間」の**隙間**で、
    広げ方は前後で違う。声の**手前**は ``onset_guard`` 秒、後ろは ``lead`` 秒で、手前が厚い
    — 速度を上げるのが遅れるのは一瞬を損するだけだが、下げるのが遅れると語頭が速い速度で
    流れ、それは聞き手が戻らないと取り返せない(最初の版で実際に報告された症状である)。

    ``min_fast`` 秒に満たない隙間は落とす。落とすのは速度の往復そのものが目に付くためで、
    実測では最短0.3秒と1.0秒で総速度差は0.1倍未満、切り替え回数だけが毎分26回と17回に
    分かれた。取れない時間ではなく、要らない切り替えを削っている。
    """
    lead = get_pace_lead_seconds()
    guard = get_pace_onset_guard_seconds()
    min_fast = get_pace_min_fast_seconds()
    plan = {
        "fast": [],
        "fast_seconds": 0.0,
        "content_seconds": 0.0,
        "duration_seconds": round(float(duration_seconds or 0.0), 3),
        "fast_rate": round(get_pace_fast_rate(), 3),
        "fast_volume": round(get_pace_fast_volume(), 3),
        "lead_seconds": round(lead, 3),
        "onset_guard_seconds": round(guard, 3),
        "min_fast_seconds": round(min_fast, 3),
        "reaction_spans": 0,
        "speech_spans": 0,
    }
    duration = float(duration_seconds or 0.0)
    if duration <= 0 or not speech:
        return plan
    plan["speech_spans"] = len(speech)

    # 前後は非対称に広げる。声の**手前**(=速い区間の終わり)が語頭を食う側で、こちらだけ厚い。
    content = [[max(0.0, float(s["start"]) - guard), float(s["end"]) + lead]
               for s in speech]
    if reactions:
        plan["reaction_spans"] = len(reactions)
        content += [[max(0.0, float(s["start"]) - guard), float(s["end"]) + lead]
                    for s in reactions]
    content = _merge(content)

    cursor = 0.0
    for start, end in content:
        if start - cursor >= min_fast:
            plan["fast"].append({"start": round(cursor, 2), "end": round(start, 2)})
        cursor = max(cursor, end)
    if duration - cursor >= min_fast:
        plan["fast"].append({"start": round(cursor, 2), "end": round(duration, 2)})

    plan["fast_seconds"] = round(sum(s["end"] - s["start"] for s in plan["fast"]), 2)
    plan["content_seconds"] = round(max(0.0, duration - plan["fast_seconds"]), 2)
    return plan


def effective_rate(plan: dict, content_rate: float) -> Optional[float]:
    """``content_rate`` で観たときに録画1本が縮む倍率。計画が空ならNone。

    画面が「どれだけ速くなるか」を先に名乗れないと、利用者はONにしてから実測するしかない。
    """
    duration = plan.get("duration_seconds") or 0.0
    fast = plan.get("fast_seconds") or 0.0
    rate = plan.get("fast_rate") or 0.0
    if duration <= 0 or not plan.get("fast") or content_rate <= 0 or rate <= 0:
        return None
    spent = (duration - fast) / content_rate + fast / rate
    return round(duration / spent, 2) if spent > 0 else None
