"""配信者リーグ帯(A1/B3/D2 等)の解釈を1か所に置く。

D帯は1度配信しただけでも付くため、「配信者である」という情報を持たない。加えて、
無効なroom_idを渡したときにTikTokが返す値も D5 で、実在のD5と応答からは区別できない
(room_id無し・存在しないroom_idのいずれも D5 を返すことを実測で確認)。どちらの理由でも
表示する意味が無いので、D帯は「配信者ではない」として扱う。

生値は users.league にそのまま残す。解釈を変えたときに取り直さずに済ませるためで、
捨てるのは表示の段だけである。
"""

NON_BROADCASTER_PREFIX = "D"


def normalize_league(league) -> str:
    return str(league or "").strip().upper()


def is_broadcaster_league(league) -> bool:
    """このリーグ帯を「配信者」として見せてよいか。"""
    value = normalize_league(league)
    return bool(value) and not value.startswith(NON_BROADCASTER_PREFIX)


def display_league(league) -> str:
    """画面に出すリーグ帯。見せない場合は空文字(捏造せず、単に出さない)。"""
    value = normalize_league(league)
    return value if is_broadcaster_league(value) else ""


def display_league_sql(alias: str = "u") -> str:
    """表示用leagueを引くSQL片。Python側の display_league と同じ判定にすること。"""
    return (
        f"CASE WHEN UPPER(COALESCE({alias}.league, '')) LIKE '{NON_BROADCASTER_PREFIX}%'"
        f" THEN '' ELSE UPPER(COALESCE({alias}.league, '')) END"
    )
