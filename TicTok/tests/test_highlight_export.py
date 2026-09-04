"""highlightの書き出しの「誰の何が、どの名前で、どの順に出るか」。

ffmpegを起こさずに確かめられるのはここまでで、実際にmp4が出来ることは実物での実測
(doc/HIGHLIGHT_MATCH.md)が受け持つ。見るのは7点。

(1) 出力に入らないgift演出が全部落ちること — 人が外した(``excluded``)、再照合で消えた
    (``dropped``)、gift地点ではない(``gift_event_id`` が無い)、下限に届かない。
(2) 同じgiftを指すgift演出が1つに畳まれること。TikTokは同じ瞬間を別のhighlightにも入れる
    ので、畳まないと同じ演出が2回流れる。
(3) **出力がgifterごとに1本**で、対象はその週の合計が ``post_min`` 以上の人だけであること。
    束ねる鍵は ``identity_key`` で、表示名ではないこと(名前を変えた1人が2本に割れない・
    同名の別人が1本に混ざらない)。
(4) gift 1件あたりの下限(``min_diamonds``)と、その人の週合計の下限(``post_min``)が
    **別々に効く**こと。99💎を1回だけ投げた人でも週合計が届いていれば出る。
(5) file名 ``<順位>_yymmdd-yymmdd_coin<週合計>_<表示名>_story.mp4`` が仕様どおりで、日付が
    **週の窓**であること(同じ週なら全fileが同じ範囲・gift演出の日付では動かない)。先頭の順位で
    **文字列順が週合計の高い順になる**こと —— coinは桁区切りを持たないので、名前だけでは
    額の順に並ばない。
(6) 表示名の扱い — 絵文字とZWJ結合は残す・file名に置けない文字は置換・空なら失敗させる
    (``unique_id`` へ差し替えない)・切り詰めたことが判る。
(7) 同名の別人が居てもfile名が衝突しないこと。
"""
from datetime import datetime

import pytest

from tictok.media import highlight_export as hx

# 実データに在る表示名。ZWJ結合(🐈‍⬛)と ZWJ+異体字選択子(🏌️‍♂️)を含む。
NICK_CAT = "ありしゃ🐈\u200d⬛🐾"
NICK_GOLF = "🟡むらたろう🍑🏌\ufe0f\u200d♂\ufe0f🍔"

# 2026-08-30 12:00 / 2026-09-01 03:00。日付の幅を見るために2日跨ぐ。**ローカル時刻で組む**
# —— file名の日付はローカル時刻で切るので、UTC固定で書くと実行環境のtzで境界testが崩れる。
DAY0 = datetime(2026, 8, 30, 12, 0).timestamp()
DAY2 = datetime(2026, 9, 1, 3, 0).timestamp()


def _row(idx, *, gift=1, diamonds=100, key="k1", started_at=DAY0, media_start=60.0,
         excluded=0, dropped=0, confidence="high", start=0.0, end=3.0,
         segment_id=None, gift_idx=0, gift_media_time=None, inside=True,
         is_primary=True, highlight_id=1, effect=(), cut=None, show=None,
         chosen=False):
    """``_fetch_segments`` が展開した1行 = **(gift演出, gift) 1組**。

    gift演出とgiftは別の表なので、行は両方の列を平らに持つ(``_expand_row``)。``idx`` はgift演出の
    並び、``gift_idx`` はそのgift演出の中のgiftの並びで、**2つとも要る** —— 連投はgift演出も💎も
    同じなので、後者が無いと並びが実行のたびに入れ替わる。

    ``start``/``end`` は**このgiftを切る窓**である。``cut`` を渡すとそちらが窓になり、
    ``start``/``end`` はgift演出の窓として残る —— 人がgift 1件だけ詰めた行がこの形になる。"""
    cut_start, cut_end = (cut if cut is not None else (start, end))
    if show is not None:
        cut_start, cut_end = show
    return {
        "show_start": None if show is None else show[0],
        "show_end": None if show is None else show[1],
        "highlight_id": highlight_id, "segment_idx": idx,
        "start": cut_start, "end": cut_end,
        "segment_start": start, "segment_end": end,
        "cut_own": cut is not None,
        "segment_id": segment_id if segment_id is not None else 100 + idx,
        "recording_id": 7, "media_start": media_start, "confidence": confidence,
        "gift_idx": gift_idx,
        "gift_event_id": gift, "gift_name": "g", "diamonds": diamonds,
        "gift_media_time": (gift_media_time if gift_media_time is not None
                            else media_start),
        "identity_key": key, "user_nickname": "照合時の古い名前",
        "inside": inside, "is_primary": is_primary, "manual": False,
        # 人がこのgiftの当たりとして選んだ1本か。重複排除が最初に読む列である。
        "chosen": chosen,
        # gift演出の中で検出した演出区間。診断用で、判断には使わない。
        "effect": list(effect),
        "excluded": excluded, "dropped": dropped,
        "segment_excluded": excluded, "gift_excluded": 0,
        "segment_dropped": dropped, "gift_dropped": 0,
        "unique_id": "pomiiiip", "filename": "hl.mp4", "path": "C:/hl.mp4",
        "highlight_duration_seconds": 60.0,
        "recording": None if started_at is None else {"id": 7, "started_at": started_at},
    }


def _mention(*gifters, post_min=1000):
    return {"week": "2026-08-29", "post_min": post_min,
            "start_label": "2026-08-29 07:00", "end_label": "2026-09-05 07:00",
            "gifters": [dict(g) for g in gifters]}


def _gifter(key, nickname, diamonds):
    return {"identity_key": key, "nickname": nickname, "unique_id": "",
            "diamonds": diamonds, "rank": 1}


@pytest.fixture(autouse=True)
def _no_disk(monkeypatch):
    """素材の実在確認とDB設定の参照を外す。

    計画の段はfileを1 byteも読まない。gift1件の下限の既定は設定(DB)から来るので、testが
    実行環境の設定値に左右されないようここで固定する ―― 既定そのものを見るtestだけが
    本物を呼ぶ。"""
    monkeypatch.setattr(hx, "_resolve_source", lambda row: hx.Path(row["path"]))
    monkeypatch.setattr(hx.config, "get_highlight_effect_coin_floor", lambda: 98)


# ===== gift演出の選び方 =====

def test_落とすgift演出の内訳を名乗る():
    rows = [
        _row(0, diamonds=5000),
        _row(1, gift=None, diamonds=None),   # gift地点ではない
        _row(2, gift=2, excluded=1),         # 人が外した
        _row(3, gift=3, dropped=1),          # 再照合で消えた
        _row(4, gift=4, diamonds=10),        # 下限に届かない
    ]
    chosen = hx.select_segments(rows, min_diamonds=100)
    assert chosen["counts"] == {"total": 5, "excluded": 2, "no_gift": 1,
                                "below_min_diamonds": 1, "other_owner": 0,
                                "duplicated": 0, "selected": 1}


def test_同じgiftは1つに畳む():
    rows = [_row(0, gift=7, confidence="low"), _row(1, gift=7, confidence="high"),
            _row(2, gift=7, confidence="none")]
    kept, dropped = hx.dedup_by_gift(rows)
    assert dropped == 2 and [row["segment_idx"] for row in kept] == [1]


def test_同点なら尺の長い方を残す():
    rows = [_row(0, gift=7, end=3.0), _row(1, gift=7, end=8.0)]
    kept, _ = hx.dedup_by_gift(rows)
    assert [row["segment_idx"] for row in kept] == [1]


def test_そのgift演出の主である方を尺より先に採る():
    """**同じ瞬間に複数人がgiftを投げると、TikTokはgift 1件につきgift演出を1つ作る。**

    帰属はどのgift演出にも「その窓に入った全員」を載せる(窓が重なるため)ので、そのgiftの演出が
    実際に映っているのはそのgift演出の主(``is_primary``)の1件だけである。尺で選ぶと**別人の演出が
    映っているgift演出**を掴む —— 実測で、おニャンコ🐢💤の Travel with You(999💎)が、あきと🐢💤の
    Strong Finish(6000💎)のgift演出(7.46秒)を掴んで、彼女のfileにF1の演出が入った。彼女自身の
    演出(黄色い車)は別のgift演出(6.17秒)に正しく在ったのに、短いという理由だけで落ちていた。
    """
    rows = [_row(0, gift=7, start=36.29, end=43.75, is_primary=False, highlight_id=8),
            _row(1, gift=7, start=11.87, end=18.03, is_primary=True, highlight_id=5)]
    kept, dropped = hx.dedup_by_gift(rows)
    assert dropped == 1
    assert [row["highlight_id"] for row in kept] == [5]


def test_主がどちらにも立たなければ範囲内の方を採る():
    """巻き添えでしか出ていないgift。**どこにも主が無いことを、主の代わりに埋めない** ――
    せめてそのgiftの瞬間が窓の中に在る方(``inside``)を採る。"""
    rows = [_row(0, gift=7, end=8.0, is_primary=False, inside=False, highlight_id=8),
            _row(1, gift=7, end=6.0, is_primary=False, inside=True, highlight_id=5)]
    kept, _ = hx.dedup_by_gift(rows)
    assert [row["highlight_id"] for row in kept] == [5]


def test_人が選んだ1本は機械のどの順位よりも先に来る():
    """**同じgiftは複数のhighlightに入る。** どれを使うかの順位(確からしさ→見せ場→主→
    inside→尺)はすべて「そのgiftのアニメが映っているのはどれか」を機械が当てる代用で、
    代用が外れる形は実測で出ている —— Whale diving 2,150💎(おニャンコ🐢💤)は3本に当たり、
    3本すべてで同席(``is_primary`` が偽)と判定された。本人のアニメが映っているのは11.1秒
    ある1本だけだったのに、代表は5.9秒の別の本だった。人が実物を観て選んだのなら、代用を
    先に立てる理由は無い。"""
    rows = [_row(0, gift=7, confidence="high", is_primary=True, end=9.0,
                 highlight_id=18),
            _row(1, gift=7, confidence="low", is_primary=False, end=3.0,
                 highlight_id=20, chosen=True)]
    kept, dropped = hx.dedup_by_gift(rows)
    assert dropped == 1
    assert [row["highlight_id"] for row in kept] == [20]


def test_言い切れているgift演出は主かどうかより先に来る():
    """``confidence`` が先。低いgift演出は**そもそもその瞬間だと言い切れていない**ので、そこで
    立った主も同じだけ疑わしい。"""
    rows = [_row(0, gift=7, confidence="high", is_primary=False, highlight_id=8),
            _row(1, gift=7, confidence="low", is_primary=True, highlight_id=5)]
    kept, _ = hx.dedup_by_gift(rows)
    assert [row["highlight_id"] for row in kept] == [8]


# ===== gifterごとに1本 =====

def test_出力はgifterごとに1本_週合計の下限で絞る():
    rows = [_row(0, gift=1, diamonds=6000, key="rich"),
            _row(1, gift=2, diamonds=5000, key="rich"),
            _row(2, gift=3, diamonds=6000, key="poor")]
    mention = _mention(_gifter("rich", "太郎", 5906), _gifter("poor", "次郎", 201))
    plan = hx.plan_exports(rows, mention)
    # 1発6000💎でも、週合計が1000に届かない人はfileにならない。
    assert [f["nickname"] for f in plan["files"]] == ["太郎"]
    assert plan["counts"]["off_target"] == 1
    assert [i["diamonds"] for i in plan["files"][0]["items"]] == [6000, 5000]


def test_週合計と1件あたりの下限は別々に効く():
    """99💎を1回だけの人でも、週合計が届いていればfileになる(逆も然り)。"""
    rows = [_row(0, gift=1, diamonds=99, key="a"),      # 1発は小さいが週合計は大きい
            _row(1, gift=2, diamonds=97, key="a")]      # gift1件の下限(98)に届かない
    mention = _mention(_gifter("a", "よい", 5401))
    plan = hx.plan_exports(rows, mention)
    assert plan["counts"]["below_min_diamonds"] == 1
    assert [i["diamonds"] for i in plan["files"][0]["items"]] == [99]


def test_まとめ投げは単価で切る_合計では通さない():
    """**30💎を9個(合計270💎)は載せない。** 画面に出るのは小さなbannerが9回で、切り抜きに
    載せる場面ではない —— 合計で判定していた頃は「270💎の見せ場」としてfileへ入っていた。

    合計と単価の両方を持たせるのは、その人が払った額(順位もfile名もそちら)と「その1発に
    演出が出るか」が別の値だからである。"""
    combo = _row(0, gift=1, diamonds=270, key="a")
    combo["gift_count"] = 9
    single = _row(1, gift=2, diamonds=199, key="a")
    chosen = hx.select_segments([combo, single], min_diamonds=98)
    assert [row["gift_event_id"] for row in chosen["rows"]] == [2]
    assert chosen["counts"]["below_min_diamonds"] == 1


def test_まとめ投げでも単価が下限を越えれば載る():
    """個数で一律に落とすのではない。199💎を6個投げた1件は、1発ごとに演出が出る。"""
    combo = _row(0, gift=1, diamonds=1194, key="a")
    combo["gift_count"] = 6
    chosen = hx.select_segments([combo], min_diamonds=98)
    assert [row["gift_event_id"] for row in chosen["rows"]] == [1]
    item = hx._item(combo, 0.0, 0.0)
    # 合計は払った額のまま。単価と個数を添えて、画面が読み解けるようにする。
    assert (item["diamonds"], item["unit_diamonds"], item["gift_count"]) == (1194, 199, 6)


def test_束ねる鍵はidentity_keyであって表示名ではない():
    """同名の別人が1本に混ざらず、名前を変えた1人が2本に割れないこと。"""
    from tictok.media import clipper

    rows = [_row(0, gift=1, diamonds=500, key="a"), _row(1, gift=2, diamonds=400, key="b")]
    # 表示名が同じ別人。identity_keyで束ねるので2本に分かれる。週合計まで同じにするのは、
    # file名がコイン数も日付も持つため、そこが違えば衝突自体が起きないからである
    # (=衝突するのは全部一致したときだけ、という設計の確認でもある)。
    mention = _mention(_gifter("a", "同名", 3000), _gifter("b", "同名", 3000))
    plan = hx.plan_exports(rows, mention)
    assert len(plan["files"]) == 2
    # file名が衝突しないよう、両方に識別子が付く(片方だけに付けない)。
    names = [f["filename"] for f in plan["files"]]
    assert len(set(names)) == 2, names
    assert all(f["mark"] for f in plan["files"])
    # 印は表示名の側に付く。順位のprefixは週ごとに動く数字で、人の区別にはならない。
    labels = [clipper.parse_clip_name(name)["label"] for name in names]
    assert all(label.startswith("同名-") for label in labels), labels
    assert len(set(labels)) == 2


def test_file名の表示名は週の一覧から採る():
    """照合した時点の ``user_nickname`` ではなく、いま画面に出ている名前を使う。"""
    rows = [_row(0, gift=1, diamonds=500, key="a")]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "いまの名前", 3000)))
    assert "いまの名前" in plan["files"][0]["filename"]
    assert "照合時の古い名前" not in plan["files"][0]["filename"]


def test_1本の中の並び():
    rows = [_row(0, gift=1, diamonds=500, media_start=10.0, key="a"),
            _row(1, gift=2, diamonds=9000, media_start=99.0, key="a")]
    mention = _mention(_gifter("a", "太郎", 3000))
    assert [i["diamonds"] for i in
            hx.plan_exports(rows, mention)["files"][0]["items"]] == [9000, 500]
    assert [i["media_start"] for i in
            hx.plan_exports(rows, mention, order="time")["files"][0]["items"]] == [10.0, 99.0]


def test_並びの綴り違いは弾く():
    with pytest.raises(RuntimeError):
        hx.plan_exports([_row(0)], _mention(_gifter("k1", "太郎", 3000)), order="gifter")


def test_録画が消えていても書き出せる():
    """file名は週の窓から作るので、gift演出の日付が出せなくても止まらない。

    出せない中身の幅は捏造せず ``None`` のまま残す(画面がそこを空欄にできる)。"""
    from tictok.media import clipper

    rows = [_row(0, gift=1, diamonds=500, key="a", started_at=None)]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000)))
    # 名前は位置で読まない。順位のprefixを剥がすのは読み手の責務なので、そちらへ通す。
    parsed = clipper.parse_clip_name(plan["files"][0]["filename"])
    assert parsed["week"] == "260829-260905" and parsed["coin"] == 3000
    assert plan["files"][0]["content_start"] is None


def test_0件は内訳を名乗って失敗する():
    with pytest.raises(hx.NoSegments) as excinfo:
        hx.plan_exports([_row(0, gift=None, diamonds=None)],
                        _mention(_gifter("k1", "太郎", 3000)))
    assert "gift無し 1件" in str(excinfo.value)


def test_余白はhighlightの端を越えない_上限を超える指定は弾く():
    rows = [_row(0, gift=1, diamonds=500, key="a", start=0.3, end=59.8)]
    mention = _mention(_gifter("a", "太郎", 3000))
    item = hx.plan_exports(rows, mention, pad_lead=1.0, pad_tail=1.0)["files"][0]["items"][0]
    assert (item["start"], item["end"]) == (0.0, 60.0)
    with pytest.raises(RuntimeError):
        hx.plan_exports(rows, mention, pad_tail=hx.MAX_PAD_SECONDS + 0.1)


# ===== 1本に載らなかったgift =====
#
# **無い物こそがこの列の要件である。** 照合結果だけを並べると、TikTokが選ばなかったgiftも
# 人が外したgiftも別のhighlightに在るだけのgiftも「画面に無い」で一括りになり、次に何を
# すればよいのかが判らない。出来上がるfileの中身は1frameも変わらない。

def _week_gift(event_id, key, diamonds, *, highlight_ids=(), name="g"):
    return {"gift_event_id": event_id, "identity_key": key, "time": DAY0,
            "label": "08/30 12:00", "gift_id": "5655", "gift_name": name,
            "gift_count": 1, "diamonds": diamonds, "unit_diamonds": diamonds,
            "gift_image": "", "user_nickname": "太郎", "user_unique_id": "",
            "highlight_ids": list(highlight_ids)}


def test_載らなかったgiftを理由つきで名乗る():
    """4つの「無い」を1種類に潰さない。次に打つ手がまるで違う。"""
    rows = [_row(0, gift=1, diamonds=500, key="a"),
            _row(1, gift=2, diamonds=500, key="a", excluded=1),
            _row(2, gift=3, diamonds=500, key="a", dropped=1)]
    week = [_week_gift(1, "a", 500), _week_gift(2, "a", 500), _week_gift(3, "a", 500),
            # 別のhighlight(今回は選んでいない)に在るだけ
            _week_gift(4, "a", 400, highlight_ids=[9]),
            # どのhighlightにも出ていない —— ここだけが照合の取りこぼしを疑う場面
            _week_gift(5, "a", 300)]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000)), week_gifts=week)
    entry = plan["files"][0]
    assert [g["gift_event_id"] for g in entry["missing"]] == [2, 3, 4, 5]
    assert [g["reason"] for g in entry["missing"]] == [
        hx.MISSING_EXCLUDED, hx.MISSING_DROPPED,
        hx.MISSING_UNSELECTED, hx.MISSING_UNMATCHED]
    assert (entry["missing_count"], entry["missing_diamonds"]) == (4, 1700)
    # **出来上がるfileの中身は変わらない。**
    assert [item["gift_event_id"] for item in entry["items"]] == [1]
    assert entry["count"] == 1


def test_載らなかったgiftを渡さなければ空のまま():
    """書き出しの実行経路は母集団を引かない(素性のJSONに書かない列である)。"""
    plan = hx.plan_exports([_row(0, gift=1, diamonds=500, key="a")],
                           _mention(_gifter("a", "太郎", 3000)))
    assert plan["files"][0]["missing"] == []
    assert plan["uncovered"] == []


def test_1件も出ていない対象gifterを名乗る():
    """週合計は下限を越えているのに1本も出来ない人。**黙って消すと誰も気付けない。**"""
    rows = [_row(0, gift=1, diamonds=500, key="a")]
    week = [_week_gift(1, "a", 500), _week_gift(7, "b", 1200)]
    plan = hx.plan_exports(
        rows, _mention(_gifter("a", "太郎", 3000), _gifter("b", "花子", 4200)),
        week_gifts=week)
    assert [entry["identity_key"] for entry in plan["files"]] == ["a"]
    assert len(plan["uncovered"]) == 1
    lost = plan["uncovered"][0]
    assert (lost["nickname"], lost["coin"], lost["missing_count"]) == ("花子", 4200, 1)
    assert lost["missing"][0]["reason"] == hx.MISSING_UNMATCHED
    assert plan["counts"]["uncovered"] == 1


def test_対象外のgifterのgiftは載らなかった一覧にも入れない():
    """週合計が下限に届かない人はそもそもfileにならない。並べると、出来ない理由が
    「取りこぼし」に見える。"""
    rows = [_row(0, gift=1, diamonds=500, key="a")]
    week = [_week_gift(1, "a", 500), _week_gift(9, "poor", 200)]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000),
                                          _gifter("poor", "貧者", 200)),
                           week_gifts=week)
    assert plan["uncovered"] == []
    assert plan["counts"]["missing"] == 0


# ===== file名 =====

def test_file名の形は週の窓():
    """日付は**週の窓**(土07:00〜次の土07:00)。末尾は終端そのものの日付で、1日引かない。

    先頭に付くのはその週の順位で、1人だけなら ``01_``(桁は週のfile数で決まる)。"""
    rows = [_row(0, gift=1, diamonds=500, key="a", started_at=DAY0),
            _row(1, gift=2, diamonds=400, key="a", started_at=DAY2)]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "セクハラ珍たん", 2088)))
    assert plan["files"][0]["filename"] == \
        "01_260829-260905_coin2088_セクハラ珍たん_story.mp4"


def test_日付はgift演出の位置で動かない():
    """同じ週なら**全fileが同じ日付範囲**。中身がいつの場面かはfile名では名乗らない。"""
    from tictok.media import clipper

    mention = _mention(_gifter("a", "太郎", 1000), _gifter("b", "次郎", 2000))
    rows = [_row(0, gift=1, diamonds=500, key="a", started_at=DAY0),
            _row(1, gift=2, diamonds=500, key="b", started_at=DAY2)]
    plan = hx.plan_exports(rows, mention)
    # 日付は名前の何文字目かではなく、読み手が読み戻した値で確かめる(先頭には順位が付く)。
    assert {clipper.parse_clip_name(f["filename"])["week"]
            for f in plan["files"]} == {"260829-260905"}
    # 中身の幅は別のfieldで名乗る(file名から落ちる情報を捨てない)。
    assert plan["files"][0]["content_start"] is not None


def test_名前を文字列順に並べると週合計の高い順になる():
    """coinは桁区切りを持たないので、名前の文字列順では額の順にならない
    (``coin14611`` が ``coin3092`` より前に来る)。folderを開いた人が並べ替えずに高い順で
    見られるのは、先頭の順位だけである。"""
    from tictok.media import clipper

    coins = {"a": 3092, "b": 14611, "c": 980, "d": 1000}
    mention = _mention(*[_gifter(key, f"gifter{key}", coin)
                         for key, coin in coins.items()])
    rows = [_row(n, gift=n + 1, diamonds=500, key=key)
            for n, key in enumerate(coins)]
    plan = hx.plan_exports(rows, mention)
    names = sorted(f["filename"] for f in plan["files"])
    # 980💎の人は週合計の下限(post_min=1000)に届かないので、そもそも1本にならない。
    assert [clipper.parse_clip_name(name)["coin"] for name in names] == [14611, 3092,
                                                                        1000]
    assert [clipper.parse_clip_name(name)["position"] for name in names] == [1, 2, 3]


def test_順位の桁は週のfile数で揃える():
    """週の中で桁が揃っていないと ``10_`` が ``2_`` より前に来て、prefixの意味が消える。

    揃えるのはその週の中だけでよい —— 週が違えば日付の部分が先に効く。"""
    assert hx.name_position(1, 9) == "01_"      # 1桁の週でも2桁は使う(見た目が揃う)
    assert hx.name_position(7, 120) == "007_"
    assert hx.name_position(120, 120) == "120_"
    # 渡さなければprefixは付かない。既に書き出したfileと同じ名前を出せる経路である。
    assert hx.name_position(None) == ""


def test_100本を超える週でも文字列順が崩れない():
    from tictok.media import clipper

    gifters = [_gifter(f"k{n:03d}", f"gifter{n:03d}", 1000 + n) for n in range(105)]
    rows = [_row(n, gift=n + 1, diamonds=500, key=f"k{n:03d}") for n in range(105)]
    plan = hx.plan_exports(rows, _mention(*gifters))
    names = sorted(f["filename"] for f in plan["files"])
    assert len(names) == 105 and names[0].startswith("001_")
    assert [clipper.parse_clip_name(name)["coin"] for name in names] == \
        sorted((1000 + n for n in range(105)), reverse=True)


def test_prefixを持たない古い名前も読み戻せる():
    """順位を刻む前に書き出したfileが、一覧から素性なしとして消えてはいけない。"""
    from tictok.media import clipper

    parsed = clipper.parse_clip_name("260829-260905_coin2088_セクハラ珍たん_story.mp4")
    assert parsed["kind"] == "highlight" and parsed["coin"] == 2088
    assert parsed["week"] == "260829-260905" and parsed["position"] is None


def test_コイン数は週合計で桁区切りを入れない():
    rows = [_row(0, gift=1, diamonds=99, key="a")]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 13803)))
    assert "_coin13803_" in plan["files"][0]["filename"]


@pytest.mark.parametrize("nickname,expected", [
    # 絵文字とZWJ結合はそのまま残す。落とすと別人に見える。
    (NICK_CAT, NICK_CAT),
    (NICK_GOLF, NICK_GOLF),
    ("よい🐢💤 ｻｲｺｳｯ!", "よい🐢💤 ｻｲｺｳｯ!"),
    # file名に置けない文字は落とさず置換する(消すと a/b と ab が同じ名前になる)。
    ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
    ("\x00\x1f\x7f制御", "_制御"),
    # 前後の空白は落とす。**ピリオドは落とさない**(file名の末尾には来ないため)。
    ("  太郎  ", "太郎"),
    ("末尾ドット...", "末尾ドット..."),
    # 旗は2つで1つ。奇数個で終わる切り詰めをしなければそのまま。
    ("🇯🇵🇺🇸旗", "🇯🇵🇺🇸旗"),
])
def test_表示名の置換規則(nickname, expected):
    assert hx.safe_display_name(nickname) == expected


@pytest.mark.parametrize("nickname", ["", "   ", None, "\u200d", "\u200d\u200d"])
def test_名乗れない表示名は失敗させる(nickname):
    """**``unique_id`` へ差し替えない。** 名前が出せないなら、なぜ出せないかを名乗る。"""
    with pytest.raises(hx.NoDisplayName):
        hx.safe_display_name(nickname)


def test_名乗れない人は見送り_他の人のfileは出る():
    rows = [_row(0, gift=1, diamonds=500, key="a"), _row(1, gift=2, diamonds=500, key="b")]
    mention = _mention(_gifter("a", "太郎", 3000), _gifter("b", "   ", 2000))
    plan = hx.plan_exports(rows, mention)
    assert [f["nickname"] for f in plan["files"]] == ["太郎"]
    assert len(plan["skipped"]) == 1


def test_切り詰めは印を残す_結合の途中で切らない():
    long_cat = NICK_CAT * 6
    out = hx.safe_display_name(long_cat, budget=10)
    assert out.endswith(hx.TRUNCATION_MARK)
    assert len(out) <= 10
    # ZWJで終わっていない(繋ぐ先の無い結合符号を残さない)。
    assert out[-2] != "\u200d"
    # 旗だけの名前を切り詰めても空にならない(片割れを1つ落とすだけ)。
    flags = hx.safe_display_name("🇯🇵🇺🇸🇬🇧🇫🇷🇩🇪🇮🇹旗", budget=9)
    assert flags and flags.endswith(hx.TRUNCATION_MARK)


def test_path長に収まらなければ失敗させる(tmp_path):
    plan = {"start_ts": DAY0, "end_ts": DAY2, "coin": 100, "nickname": "太郎", "mark": "",
            "verified": True}
    with pytest.raises(RuntimeError):
        hx._fit_path(tmp_path / ("あ" * 250), plan)


def test_既定値を名乗る口は1つ(monkeypatch):
    """route側や画面が数字を書き写さずに済むよう、Serverが名乗る。

    ``min_diamonds`` は設定値なので**呼ぶたびに引き直す** —— module levelのdictにすると、
    設定画面で変えた値がserverの再起動まで効かない。"""
    d = hx.defaults()
    assert d["order"] == hx.DEFAULT_ORDER and d["precise"] is hx.DEFAULT_PRECISE
    assert d["pad_lead"] == hx.DEFAULT_PAD_LEAD and d["pad_tail"] == hx.DEFAULT_PAD_TAIL
    assert d["order_choices"] == list(hx.ORDER_CHOICES)
    assert d["min_diamonds"] == 98
    monkeypatch.setattr(hx.config, "get_highlight_effect_coin_floor", lambda: 500)
    assert hx.defaults()["min_diamonds"] == 500
    # 週合計の下限は書き出しの引数ではない(streamer_mention_week の post_min が名乗る)。
    assert "post_min" not in d and "week" not in d


def test_進捗の段階名は人数ぶん増えない():
    """jobの段階履歴は括弧の中を落として段階名を作る。変わる値は全部括弧の中へ入れる。"""
    import asyncio

    from tictok.record import media_queue

    seen = []

    async def sink(message, percent):
        seen.append(message)

    async def go():
        for index, nickname in enumerate(["ぽみ（よい）", "太郎"]):
            report = hx._scoped_progress(sink, index, 2, nickname)
            await report("highlightを切り出し中（3 / 5件）", 40)

    asyncio.run(go())
    assert {media_queue.stage_phase(m) for m in seen} == {"highlightを書き出し中"}
    # 何本目かは見える形で残る(数十本を順に作る間の唯一の手掛かり)。
    assert "1 / 2本目" in seen[0] and "2 / 2本目" in seen[1]


# ===== 切り出し一覧が読み戻せること =====
#
# 出力は ``<配信者>/LiveHightlite_マージ済み`` に置かれ、そこは ``ARTIFACT_DIRNAMES`` に
# 入っている(一覧・移動・容量が必ず見る)。読み手が無いと、容量を食っているfileが素性なしの
# 行として並ぶ。**組み立て側と読み手は対で守る。**

@pytest.mark.parametrize("nickname", [
    "セクハラ珍たん",
    NICK_CAT,                 # ZWJ結合
    "ぽみ_切り抜き",           # 表示名に '_' が入る
    "映画_story",             # 表示名が '_story' で終わる
    "story",                  # 表示名がそのまま印と同じ綴り
    "coin999_太郎",           # 表示名が印と紛らわしい
    "末尾ドット...",
])
def test_出力名は一覧が読み戻せる(monkeypatch, tmp_path, nickname):
    from tictok.media import clipper

    monkeypatch.setattr(hx.layout, "clip_output_dir", lambda s=None: tmp_path)
    name = hx.export_filename(DAY0, DAY2, 5906, nickname)
    parsed = clipper.parse_clip_name(name)
    assert parsed is not None, name
    assert parsed["kind"] == "highlight"
    assert parsed["label"] == hx.safe_display_name(nickname)
    assert parsed["coin"] == 5906
    assert parsed["week"] == "260830-260901"
    # 順位のprefixを渡していない古い形。読み手はprefix無しも読めなければならない。
    assert parsed["position"] is None
    # 録画1本に属さないので、録画へは紐付かず範囲も持たない。
    assert parsed["stem"] == ""
    assert parsed["start"] is None and parsed["end"] is None


def test_衝突の印が付いた名前も読み戻せる(monkeypatch, tmp_path):
    from tictok.media import clipper

    monkeypatch.setattr(hx.layout, "clip_output_dir", lambda s=None: tmp_path)
    mark = hx._collision_mark("7594803955487917064")
    name = hx.export_filename(DAY0, DAY2, 100, "同名", mark=mark)
    parsed = clipper.parse_clip_name(name)
    assert parsed["label"] == f"同名-{mark}"


def test_検証用の出力は成果物として並べない(monkeypatch, tmp_path):
    """``..._story.検証用.mp4`` は読めない名前のまま並ぶ。**それが正しい。**

    検証用の経路(``export_highlights`` の ``verification_rows``)を通ったfileは、DBの実照合
    結果と突き合わせていない。成果物ではないので、成果物の顔で一覧に並ぶ方が悪い。"""
    from tictok.media import clipper

    monkeypatch.setattr(hx.layout, "clip_output_dir", lambda s=None: tmp_path)
    name = hx.export_filename(DAY0, DAY2, 100, "太郎", verified=False)
    assert hx.UNVERIFIED_MARK in name
    assert clipper.parse_clip_name(name) is None


def test_読めない名前は素性なしのまま並べる():
    """旧型・手で置かれたfileは推測せず None。隠さず「規約外」として並べる側の約束。"""
    from tictok.media import clipper

    assert clipper.parse_clip_name("highlights_pomiiiip_g7_d25898_diamonds.mp4") is None
    assert clipper.parse_clip_name("手で置いたfile.mp4") is None
    # 録画から切った成果物の読み取りは変わらない。
    clip = clipper.parse_clip_name("00588_pomiiiip_20260828_222036_024846-024858_ASMR.mp4")
    assert clip["kind"] == "clip" and clip["stem"] == "00588_pomiiiip_20260828_222036"


def test_gift演出は信用できるかを名乗る():
    """出力の中身が別人のgiftになっていた事故がある。押す前に気付ける材料を行に載せる。"""
    rows = [dict(_row(0, gift=1, diamonds=500, key="a", segment_id=4242),
                 approved=1, edited=0, confidence="low")]
    item = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000)))["files"][0]["items"][0]
    # idx は再照合で動くので、行からgift演出へ飛ぶ鍵は segment_id。
    assert item["segment_id"] == 4242
    assert item["approved"] == 1 and item["confidence"] == "low"


# ===== 連投は記録を落とさず、映像だけを畳む =====
#
# 実測: 60.8秒のhighlight 1本に gift が21件入っている(Hearts 199💎×6 / Swan 699💎×2 /
# Fireworks 1088💎×2 / Galaxy 1000💎×2)。連投は ``message_id`` が別の**別event**なので
# 重複ではない。素直に1 gift = 1切り出しにすると、Heartsの連投だけで同じ場面が6本並ぶ。

def test_連投は記録を6件残したまま映像は1つになる():
    """**記録は1件も落とさない。切り出しは1つの連続した映像にする。** 2つは別の話である。"""
    rows = [_row(0, gift=100 + n, diamonds=199, key="a", gift_idx=n,
                 gift_media_time=60.0 + n * 0.4) for n in range(6)]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "るきしろ", 2987)))
    entry = plan["files"][0]
    # giftの記録は6件。「Hearts ×6」と1行に潰さない。
    assert entry["count"] == 6 and len(entry["items"]) == 6
    assert [i["gift_event_id"] for i in entry["items"]] == [100 + n for n in range(6)]
    # 💎は6件ぶん。連投は「199💎を6回投げた = 1,194💎」である。
    assert entry["diamonds"] == 199 * 6
    # 映像は1つの連続したgift演出。同じ窓が6本並ばない。
    assert entry["cut_count"] == 1 and len(entry["cuts"]) == 1
    assert (entry["cuts"][0]["start"], entry["cuts"][0]["end"]) == (0.0, 3.0)
    assert entry["seconds"] == 3.0
    # 件数と尺は比例しない(畳んだため)。画面がそれを読めるように両方返す。
    assert len(entry["cuts"][0]["gifts"]) == 6


def test_同席しただけのgiftは別人のfileへ入らない():
    """**gift演出1つ = 見せ場1つ。** 同席しただけの人のfileへその場面を入れない。

    montageのgift演出は平均6秒あり、その間に別の人のgiftが何件も飛ぶ。実測で6.0秒のgift演出1つに
    Singing Mushroom 99💎・Strong Finish 6000💎・Travel with You 999💎の3件が載っていたが、
    画面に映っていたのは6000💎の演出**1つだけ**である。3人ぶんのfileへ入れていたので、
    99💎を投げた人の1本は正しいHeartsの窓のあとに他人の演出が2つ続いていた(利用者の指摘)。

    主(``is_primary``)は照合側がgift演出ごとに1件だけ立てる。"""
    rows = [_row(0, gift=1, diamonds=6000, key="a"),
            _row(0, gift=2, diamonds=399, key="b", gift_idx=1, is_primary=False)]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000),
                                          _gifter("b", "次郎", 3000)))
    assert [entry["identity_key"] for entry in plan["files"]] == ["a"]
    entry = plan["files"][0]
    assert entry["count"] == 1 and entry["cut_count"] == 1
    assert (entry["cuts"][0]["start"], entry["cuts"][0]["end"]) == (0.0, 3.0)


def test_見せ場を割れたgift演出では同席した全員が自分の窓で載る():
    """**割れたgift演出に主は要らない。** 行ごとに自分の見せ場の窓が在り、他人の演出は窓の外
    である。主を立てて他を落とすと、画面に映っている見せ場を持つ人が出力から消える ——
    実測(hl12 / 20.9秒)で4件のgiftの演出が順に並んでおり、主だけを残すと3人が消えた。"""
    rows = [_row(0, gift=1, diamonds=6599, key="a", start=14.745, end=35.689,
                 show=(15.067, 21.345)),
            _row(0, gift=2, diamonds=2000, key="b", start=14.745, end=35.689,
                 gift_idx=1, is_primary=False, show=(22.5, 26.345)),
            _row(0, gift=3, diamonds=1200, key="c", start=14.745, end=35.689,
                 gift_idx=2, is_primary=False, show=(27.467, 31.345))]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 6599),
                                          _gifter("b", "次郎", 2000),
                                          _gifter("c", "三郎", 1200)))
    assert sorted(entry["identity_key"] for entry in plan["files"]) == ["a", "b", "c"]
    windows = {entry["identity_key"]: (entry["cuts"][0]["start"], entry["cuts"][0]["end"])
               for entry in plan["files"]}
    assert windows["a"] == (15.067, 21.345)
    assert windows["b"] == (22.5, 26.345)
    assert windows["c"] == (27.467, 31.345)


def test_割れていないgift演出は今までどおり主だけが載る():
    """割る手掛かりが無いgift演出では、他人の演出が入る危険は消えていない。"""
    rows = [_row(0, gift=1, diamonds=6000, key="a"),
            _row(0, gift=2, diamonds=399, key="b", gift_idx=1, is_primary=False)]
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 6000),
                                          _gifter("b", "次郎", 3000)))
    assert [entry["identity_key"] for entry in plan["files"]] == ["a"]


def test_見せ場を持つ行は主より先に残す():
    """同じgiftが複数のhighlightに入ったとき。見せ場は「そのgiftの演出が映っている区間」
    そのもので、主は「そのgift演出で一番よく映っている人」という弱い代用である。"""
    rows = [_row(0, gift=7, is_primary=True, highlight_id=8),
            _row(1, gift=7, is_primary=False, highlight_id=5, show=(1.0, 4.0))]
    kept, dropped = hx.dedup_by_gift(rows)
    assert dropped == 1
    assert [row["highlight_id"] for row in kept] == [5]


def test_人が付け替えたgiftは主でなくても載る():
    """``manual`` は**人がこのgift演出はこのgiftだと決めた行**である。機械の主の判定より後に
    置かれた判断なので、同席の除外はここを通さない。"""
    rows = [_row(0, gift=1, diamonds=6000, key="a"),
            _row(0, gift=2, diamonds=399, key="b", gift_idx=1, is_primary=False)]
    rows[1]["manual"] = True
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000),
                                          _gifter("b", "次郎", 3000)))
    assert sorted(entry["identity_key"] for entry in plan["files"]) == ["a", "b"]


def test_giftごとに詰めた区間がそのまま切り出される():
    """**同じgift演出でも、gift 1件ずつ別の範囲を切れること。**

    出力はgifterごとに1本なので、切り出す範囲がgift演出単位だと、1人に合わせて詰めた値が同じ
    gift演出を持つ別のfileまで動かす。人が付け替えた行(``manual``)は主でなくても載るため、
    1つのgift演出が2人のfileへ入る形はいまも起きる。"""
    rows = [_row(0, gift=1, diamonds=6000, key="a", start=0.0, end=6.0, cut=(0.0, 2.5)),
            _row(0, gift=2, diamonds=99, key="b", start=0.0, end=6.0, gift_idx=1,
                 is_primary=False)]
    rows[1]["manual"] = True
    plan = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 6000),
                                          _gifter("b", "次郎", 3000)))
    spans = {entry["identity_key"]: (entry["cuts"][0]["start"], entry["cuts"][0]["end"])
             for entry in plan["files"]}
    # 詰めた側だけが短い。触っていない側はgift演出の窓のまま。
    assert spans == {"a": (0.0, 2.5), "b": (0.0, 6.0)}


def test_同じ人の2件でも別の区間なら別の窓になる():
    """畳む鍵は**窓**である(gift演出ではない)。

    以前は「同じgift演出」を鍵にしていたので、gift単位で詰めた2件が1つの窓へ畳まれて、詰めた
    意味が消えていた。重なっていれば今までどおり1つになる(:func:`_priority_cuts`)。"""
    rows = [_row(0, gift=1, diamonds=6000, key="a", start=0.0, end=6.0, cut=(0.0, 2.0)),
            _row(0, gift=2, diamonds=500, key="a", start=0.0, end=6.0, gift_idx=1,
                 cut=(4.0, 6.0))]
    entry = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 6000)))["files"][0]
    assert entry["cut_count"] == 2
    # 高額順。窓の値打ちは、その窓が含むgiftの最高額で決まる。
    assert [(c["start"], c["end"]) for c in entry["cuts"]] == [(0.0, 2.0), (4.0, 6.0)]
    assert entry["count"] == 2


def test_離れたgift演出は畳まない():
    """重ならない窓は別の切り出しのままにする(繋ぐ順は並びが決める)。"""
    rows = [_row(0, gift=1, diamonds=500, key="a", start=0.0, end=3.0),
            _row(1, gift=2, diamonds=900, key="a", start=10.0, end=14.0)]
    entry = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000)))["files"][0]
    assert entry["cut_count"] == 2
    # 高額順。窓の値打ちは、その窓が含むgiftの最高額で決まる。
    assert [c["start"] for c in entry["cuts"]] == [10.0, 0.0]
    assert entry["seconds"] == 7.0


def test_余白で重なった隣のgift演出_高額順は安い側を削り時系列順は畳む():
    """守るのは「同じ映像が2回入らない」ことで、「窓が1つになる」ことではない。

    余白を足すと隣のgift演出の窓へ食い込む。時系列順は畳んでも並びが変わらないので1つにするが、
    高額順で畳むと塊の中が時系列で流れ、安いgiftから始まる。よって高額順では**高額な側を
    丸ごと残し、安い側の重なった分だけを削って別の窓として後ろに置く**。"""
    rows = [_row(0, gift=1, diamonds=500, key="a", start=0.0, end=3.0),
            _row(1, gift=2, diamonds=900, key="a", start=3.5, end=6.0)]
    mention = _mention(_gifter("a", "太郎", 3000))
    entry = hx.plan_exports(rows, mention, pad_lead=1.0, pad_tail=1.0)["files"][0]
    assert entry["cut_count"] == 2
    # 900💎の窓(2.5〜7.0)が丸ごと先に来て、500💎は重なった0.5秒を削られて後ろに来る。
    assert [(c["start"], c["end"]) for c in entry["cuts"]] == [(2.5, 7.0), (0.0, 2.5)]
    assert [c["diamonds"] for c in entry["cuts"]] == [900, 500]
    hx._assert_no_overlap(entry["cuts"])

    ordered = hx.plan_exports(rows, mention, pad_lead=1.0, pad_tail=1.0,
                              order="time")["files"][0]
    assert ordered["cut_count"] == 1
    assert (ordered["cuts"][0]["start"], ordered["cuts"][0]["end"]) == (0.0, 7.0)


def test_接したgift演出は高額順では畳まない_高いgift演出から始まる():
    """実測の再現。よい🐢💤 ｻｲｺｳｯ! の1本は 99💎 → 4999💎 → 99💎 の3件のgift演出が接していたため、
    畳むと0.0〜17.79秒の1つの窓になり「高額順を指定したのに99💎から始まる1本」が出来た。

    接しているだけの別々のgift演出なので、高額順では畳まず**4999💎のgift演出から始める**。"""
    rows = [_row(0, gift=1, diamonds=99, key="a", start=0.0, end=5.41),
            _row(1, gift=2, diamonds=4999, key="a", start=5.41, end=11.45),
            _row(2, gift=3, diamonds=99, key="a", start=11.45, end=17.79)]
    mention = _mention(_gifter("a", "よい🐢💤 ｻｲｺｳｯ!", 5197))
    entry = hx.plan_exports(rows, mention)["files"][0]
    assert entry["cut_count"] == 3
    assert entry["cuts"][0]["diamonds"] == 4999
    assert (entry["cuts"][0]["start"], entry["cuts"][0]["end"]) == (5.41, 11.45)
    # 同額(99💎)はgift演出の並びで決まる。切る尺は畳んでも畳まなくても同じ。
    assert [(c["start"], c["end"]) for c in entry["cuts"][1:]] == [(0.0, 5.41),
                                                                  (11.45, 17.79)]
    assert entry["seconds"] == 17.79
    hx._assert_no_overlap(entry["cuts"])

    # 時系列順は従来どおり1つへ畳む —— 畳んでも並びは変わらず、繋ぎ目だけが減る。
    ordered = hx.plan_exports(rows, mention, order="time")["files"][0]
    assert ordered["cut_count"] == 1
    assert (ordered["cuts"][0]["start"], ordered["cuts"][0]["end"]) == (0.0, 17.79)
    hx._assert_no_overlap(ordered["cuts"])


def test_高額順でも連投は1つの窓へ畳む_件数は落ちない():
    """gift演出を跨いで畳まないだけで、**同じgift演出に乗った連投は高額順でも1つの窓**である。

    同じ窓を畳んでも並びは変わらない(💎もgift演出も同じ)。畳まないと同じ映像が投げた回数だけ
    並び、しかも ``_assert_no_overlap`` で止まる。"""
    rows = [_row(0, gift=100 + n, diamonds=199, key="a", gift_idx=n,
                 gift_media_time=60.0 + n * 0.4) for n in range(6)]
    entry = hx.plan_exports(rows, _mention(_gifter("a", "るきしろ", 2987)),
                            order="diamonds")["files"][0]
    assert entry["cut_count"] == 1
    assert (entry["cuts"][0]["start"], entry["cuts"][0]["end"]) == (0.0, 3.0)
    # giftの記録は6件のまま。畳むのは映像だけである。
    assert entry["count"] == 6 and len(entry["cuts"][0]["gifts"]) == 6
    assert entry["diamonds"] == 199 * 6
    hx._assert_no_overlap(entry["cuts"])


def test_丸ごと吸われた窓は落ちるがgiftの記録は吸った窓に残る():
    """高額な窓に丸ごと含まれた窓は切らない。**その分の記録は捨てない。**

    余白で重なると安い側には端切れ(ここでは0.2秒)しか残らず、それは場面として読めず繋ぎ目が
    増えるだけである(``MIN_CUT_SECONDS``)。だがそのgiftは残した窓に映っているので、記録は
    吸った窓の ``gifts`` へ移す —— 件数も💎も素性も落とさない。"""
    rows = [_row(0, gift=1, diamonds=900, key="a", start=0.0, end=5.0),
            _row(1, gift=2, diamonds=500, key="a", start=5.1, end=5.2)]
    entry = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000)),
                            pad_lead=1.0)["files"][0]
    assert entry["cut_count"] == 1
    assert (entry["cuts"][0]["start"], entry["cuts"][0]["end"]) == (0.0, 5.0)
    # 500💎は切られないが、記録は吸った窓に残る。
    assert entry["count"] == 2
    assert sorted(g["gift_event_id"] for g in entry["cuts"][0]["gifts"]) == [1, 2]
    assert entry["cuts"][0]["diamonds"] == 1400
    hx._assert_no_overlap(entry["cuts"])


def test_同じ映像が二度入る計画は失敗させる():
    """畳んだ後に重なりが残っていたら、切る前に止める。出来上がってからでは直せない。"""
    cuts = [{"src": hx.Path("C:/hl.mp4"), "start": 0.0, "end": 5.0},
            {"src": hx.Path("C:/hl.mp4"), "start": 4.0, "end": 8.0}]
    with pytest.raises(RuntimeError):
        hx._assert_no_overlap(cuts)


def test_演出が映っているかでは落とさない():
    """演出区間が1つも検出できなかったgift演出のgiftも、そのまま出力へ載る。

    照合側の ``has_effect`` は**契約から外れた** —— 実物7本のgift 47件で真は2件だけ、
    しかもどちらもTikTok自身のワイプで、gift演出に付いた真は0件だった。当たりが0件の
    信号で落とすと、良いgift(実測では Flying Jets 5000💎)が消える。"""
    rows = [_row(0, gift=1, diamonds=5000, key="a", effect=()),
            _row(1, gift=2, diamonds=699, key="a", effect=[(1.0, 2.0)])]
    entry = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000)))["files"][0]
    assert entry["count"] == 2
    # 印そのものを運ばない(常に偽の値を返すと「演出が無い」という嘘になる)。
    assert all("has_effect" not in item for item in entry["items"])


def test_gift1件を外してもgift演出ごとは落ちない():
    """人が外せるのはgift 1件である。gift演出単位で落とすと同じgift演出の他のgiftまで消える。"""
    rows = [_row(0, gift=1, diamonds=500, key="a", gift_idx=0),
            _row(0, gift=2, diamonds=400, key="a", gift_idx=1)]
    rows[0]["gift_excluded"] = True
    rows[0]["excluded"] = True     # 行はgift演出側とgift側の論理和を持つ
    entry = hx.plan_exports(rows, _mention(_gifter("a", "太郎", 3000)))["files"][0]
    assert [i["gift_event_id"] for i in entry["items"]] == [2]
    assert entry["cut_count"] == 1
