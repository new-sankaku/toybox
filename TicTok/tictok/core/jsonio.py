"""JSON serialization boundary for the HTTP/WebSocket API.

JavaScriptのNumberはIEEE754 doubleなので、2^53を超える整数はJSON.parseの時点で丸められる
(7664176088063052545 → 7664176088063053000)。TikTokのroom_id/battle_id/team_id/user_idは
全てint64で日常的にこの範囲を超えるため、JSON数値のまま送ると画面に出たIDが実IDと別物になり、
IDでの突合・検索が静かに壊れる。

対策はserializeの境界で桁を保てる文字列へ寄せることに一本化する。個々のendpointでstr()を
書き足す方式にしないのは、

* ops_eventsのdetailは任意のdictをそのまま貯めたblobで、どのkeyにIDが入るか事前に分からない。
  既に数値で保存済みの過去分もここを通れば同じ規則で直り、DBの書き換え(破壊的移行)が要らない。
* 新しいendpointやfieldが増えたときに書き漏らすと、また静かに桁が落ちる。

ため。DB側は記録時の値をそのまま残す(logした事実を後から書き換えない)。

2^53以下の整数はJSONの数値のままなので、件数・コイン数のような集計値の型は変わらない。
"""

from typing import Any

from fastapi.responses import JSONResponse

# Number.MAX_SAFE_INTEGER。これを超える整数はJS側で別の値になる。
JS_MAX_SAFE_INTEGER = 2 ** 53 - 1


def js_safe(value: Any) -> Any:
    """JSで桁落ちする整数だけを文字列へ寄せた同型の値を返す。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value) if abs(value) > JS_MAX_SAFE_INTEGER else value
    if isinstance(value, dict):
        return {key: js_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [js_safe(item) for item in value]
    return value


class JsSafeJSONResponse(JSONResponse):
    """既定のresponse class。FastAPIがjsonable_encoderを通した後の内容を受けるので、
    endpointの戻り値の形に依らずここが最後の関門になる。"""

    def render(self, content: Any) -> bytes:
        return super().render(js_safe(content))
