import logging

import betterproto
from TikTokLive.proto import User
from TikTokLive.proto.custom_proto import ExtendedUser

logger = logging.getLogger("tictok.collector")

# TikTokLive 6.6.5 の ExtendedUser.from_user は user.to_pydict() を casing 無しで呼ぶが、
# betterproto 2.0.0b7 の to_pydict は default が Casing.CAMEL。結果 nick_name が nickName
# として返り、それを dataclass の kwargs へ戻すため TypeError で落ちる。to_pydict は既定値
# の field を出さないので、TikTok側がその field を実際に埋めた瞬間から発症する。User の
# 88 field 中 79 が multi-word なので nick_name 以外でも同じ壊れ方をする。
# event.user を触る全 handler (comment/like/follow/share/join/gift) が例外になり、
# pyee の error event へ流れて当該 event が丸ごと欠測する。
_PATCHED = False


def _from_user(cls, user, **kwargs):
    if isinstance(user, ExtendedUser):
        return user
    kwargs.setdefault("casing", betterproto.Casing.SNAKE)
    try:
        return cls(**user.to_pydict(**kwargs))
    except AttributeError:
        # betterproto の optional field は未設定時に AttributeError を投げるため、
        # 上流と同じく実体側 (_field) から拾い直す。
        user_dict = {}
        for field in user.__class__.__dataclass_fields__:
            try:
                user_dict[field] = getattr(user, field)
            except AttributeError as exc:
                if "is set to None" not in str(exc):
                    raise
                user_dict[field] = getattr(user, f"_{field}", None)
        return cls(**user_dict)


def _from_user_is_broken() -> bool:
    try:
        ExtendedUser.from_user(User(id=1, nick_name="probe"))
    except TypeError:
        return True
    return False


def apply_ttlive_patches() -> None:
    """TikTokLive/betterproto の版ずれを起動時に1度だけ補正する。"""

    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    if not _from_user_is_broken():
        logger.debug("ExtendedUser.from_userは正常のためpatchを適用しません")
        return
    ExtendedUser.from_user = classmethod(_from_user)
    logger.info("ExtendedUser.from_userをsnake casing版へ差し替えました(TikTokLive版ずれの補正)")
