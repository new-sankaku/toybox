"""再生中に飛ばす無音区間 — 「誰も喋っていない時間」をそのまま飛び先にする。

== 音量では答えられない問いだった ==

前の版は録画自身のlevel分布から閾値を決めて無音を探していた。実録画5本で測ると、飛ばせたのは
尺の1.1〜13.8%で、そのうち2本は**飛ばした時間の3.0〜9.7%が実際には声**だった。同じ5本で誰も
喋っていない時間は45〜59%ある。

音量ではこの問いに答えられない。配信はBGMとゲーム音が鳴り続けるので、話が止まっても音量は
下がらない。閾値を録画ごとに決めても、文字起こしの語で削っても、測っているものが違う限り
当たらない。**計器が違った。**

いまは ``media/voice.py``(Silero VAD)が答える。0.1秒刻みの声確率で、文字起こしを必要としない。

== 文字起こしは使わない ==

語の時刻は根拠にしない。時刻を合わせて突き合わせると VAD と語はよく一致する(実録画5本で
不一致0.0〜0.8%)が、その「時刻を合わせて」が保証できない — 実録画1本(rid=1018)は文字起こし
全体が**4.9秒ずれて**おり、語の時刻を+4.9秒すると不一致が276秒から0秒へ落ちた。飛ばす判定に
ずれた時刻を混ぜると、声の在る所を無音と呼ぶ。

== 手前を厚く残す ==

内容は声を前後へ広げて作る。広げ方は前後で違い、**手前(``guard``)が厚い**。飛ばした先が声の
頭に着地すると語頭が消え、消えたこと自体が画面に残らない — 聞き手が気付けない唯一の失敗で
ある。後ろ(``lead``)は遅れて飛ぶだけなので薄くてよい。

``guard`` は「測ってから聞こえるまで」を全部覆う: 32msのVAD frameを0.1秒格子へ畳んだ分、VAD
自身が語頭で外す分、そしてseekの着地でdecoderが要する分。

== 跳べない所では跳ばない ==

飛び先がbufferに無いときに跳ぶかどうかは画面側が決める(``static/videos.js``)。実測でbuffer内の
seekは0.07秒、buffer外は0.67〜259秒かかり予測できないため、buffer外へは跳ばない。ここは計画の
話ではなく再生の話なので、この module は「飛ばしてよい区間」だけを答える。
"""
from typing import Optional

from tictok.core.config import (
    get_skip_guard_seconds,
    get_skip_lead_seconds,
    get_skip_min_gap_seconds,
    get_skip_min_jump_seconds,
    get_skip_voice_threshold,
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


def skip_plan(duration_seconds: float, speech: Optional[list],
              reactions: Optional[list] = None) -> dict:
    """飛ばしてよい無音区間と、その判定に使った値を返す。

    ``speech`` は ``voice.speech_spans`` の戻り、``reactions`` は
    ``laugh_audio.reaction_spans`` の戻り(どちらも ``{"start", "end"}`` の列)。

    反応(笑い・叫び・息を呑む音・拍手)を内容へ入れるのは、それが語にならないためである。
    VADも拾えないことがあり、飛ばす方式では**その瞬間だけが黙って消える**。

    戻り値の ``spans`` は飛び先そのもので、画面は区間に入ったら ``end`` へ跳ぶ。端の余裕は
    ここで既に引いてあるので、画面側で足し引きしない(2箇所で余裕を持つと、どちらがどれだけ
    残しているのか誰にも分からなくなる)。
    """
    guard = get_skip_guard_seconds()
    lead = get_skip_lead_seconds()
    min_gap = get_skip_min_gap_seconds()
    plan = {
        "spans": [],
        "skip_seconds": 0.0,
        "duration_seconds": round(float(duration_seconds or 0.0), 3),
        "guard_seconds": round(guard, 3),
        "lead_seconds": round(lead, 3),
        "min_gap_seconds": round(min_gap, 3),
        "min_jump_seconds": round(get_skip_min_jump_seconds(), 3),
        "voice_threshold": round(get_skip_voice_threshold(), 3),
        "speech_spans": 0,
        "reaction_spans": 0,
        "has_reactions": bool(reactions),
    }
    duration = float(duration_seconds or 0.0)
    if duration <= 0 or not speech:
        return plan
    plan["speech_spans"] = len(speech)

    content = [[max(0.0, float(s["start"]) - guard), float(s["end"]) + lead]
               for s in speech]
    if reactions:
        plan["reaction_spans"] = len(reactions)
        content += [[max(0.0, float(s["start"]) - guard), float(s["end"]) + lead]
                    for s in reactions]
    content = _merge(content)

    cursor = 0.0
    for start, end in content:
        if start - cursor >= min_gap:
            plan["spans"].append({"start": round(cursor, 2), "end": round(start, 2)})
        cursor = max(cursor, end)
    if duration - cursor >= min_gap:
        plan["spans"].append({"start": round(cursor, 2), "end": round(duration, 2)})

    plan["skip_seconds"] = round(sum(s["end"] - s["start"] for s in plan["spans"]), 2)
    return plan


def effective_rate(plan: dict, content_rate: float) -> Optional[float]:
    """``content_rate`` で観たときに録画1本が縮む倍率。飛ばす区間が無ければNone。

    画面が「どれだけ短くなるか」を先に名乗れないと、利用者はONにしてから実測するしかない。
    跳躍そのものの停止(実測0.07秒)は数えない — 1分あたり0.5秒程度で、倍率の桁に効かない。
    """
    duration = plan.get("duration_seconds") or 0.0
    skip = plan.get("skip_seconds") or 0.0
    if duration <= 0 or not plan.get("spans") or content_rate <= 0:
        return None
    spent = (duration - skip) / content_rate
    return round(duration / spent, 2) if spent > 0 else None
