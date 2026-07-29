"""betterproto message/enum を JSON化可能な plain object へ安全に変換する共通処理。

betterproto標準の Message.to_dict は、proto に未定義の enum 値(TikTok側の新種値)を
含む event で ValueError を投げる。to_dict が内部で enum_class(value) と再検証し、
未定義値では EnumType.__call__ が例外を送出するため。TikTok は予告なく新しい enum 値を
送ってくるので、この変換を生 to_dict に頼ると収集の各所で頻発する。

ここでは独自変換で未定義 enum を raw int として残し、default 値の field は省いて
実際に埋まった field だけを残す。全ての「proto event を辞書化したい」箇所はこの関数を
経由することで、未知 enum 値に強くする。"""

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("tictok.proto_dict")

try:
    from betterproto import Enum as _ProtoEnum, Message as _ProtoMessage
except Exception:  # betterproto未導入環境(simulation only)では proto event を扱わない
    _ProtoEnum = _ProtoMessage = ()


def to_plain(value: Any, depth: int = 0) -> Any:
    """betterproto message/enum を再帰的に plain object へ変換する。

    未定義 enum 値は name が None になるので、捨てずに raw int を残す。
    default 値の field は省き、実際に埋まった field だけを残す。"""
    if depth > 20:
        return "…"
    if isinstance(value, _ProtoEnum):
        # 未定義値は name が None。捨てずに raw int を残す。
        return value.name if value.name is not None else int(value)
    if isinstance(value, _ProtoMessage):
        out: dict = {}
        for field_name in value._betterproto.meta_by_field_name:
            try:
                child = getattr(value, field_name)
            except AttributeError:
                continue  # 未設定の oneof field
            try:
                if child == value._get_field_default(field_name):
                    continue  # default値は省く
            except Exception:
                # default比較に失敗したfieldは「default値ではない」とみなして残す。捨てないので
                # 収集への実害は無いが、無音だと出力が膨らんだ理由が追えないためDEBUGで残す。
                # per-field per-eventの最高頻度path なので level guard は必須。
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "proto fieldの既定値比較に失敗しました。field %s を残します", field_name,
                        exc_info=True,
                        extra={"event": "collector.proto_field_default_check_failed",
                               "ctx": {"field": field_name,
                                       "message_type": type(value).__name__}},
                    )
            out[field_name] = to_plain(child, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [to_plain(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): to_plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, bytes):
        return value.hex()
    return value


def safe_event_to_dict(event: Any) -> dict:
    """betterproto message を素の dict へ。未定義 enum 値でも例外を投げない。
    default 値は省いて実際に埋まった field だけ残す。失敗しても情報を捨てず repr で残す。"""
    try:
        result = to_plain(event)
        return result if isinstance(result, dict) else {"_value": result}
    except Exception:
        logger.exception("safe_event_to_dictが失敗しました")
        return {"_repr": repr(event)}
