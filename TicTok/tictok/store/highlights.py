"""TikTok本体のhighlight(LIVE replayの切り抜き)の台帳と、突き合わせ結果の保存。

境界の理由: highlight 1本 = ``highlight_videos`` の1行、その中のgift演出 = ``highlight_segments``
の行、という2表を一組で扱う。走査(diskに在るものを行にする)・照合結果の保存・人の手直しの
3つが同じ2表の同じ不変条件(「人が直した内容は機械が消さない」)を共有するので、分けない。

lock契約: lock保持前提のmethodは無い。走査はdiskを歩いてからDBを触る(歩いている間lockを
握らない)。

置き場について
--------------
実体は複数の置き場に在り得る(2通り × work/final の両root ―― ``layout.highlight_dirs``)。行はそのうち**どこで見つけたか**
を必ず持つ(``root_key`` / ``source_dir``)—— 置き場が複数ある以上、画面がそれを名乗れなければ
利用者は自分が置いたfileへ戻れない(``tictok.api.routes.clips`` のmodule docstringと同じ約束)。

再照合で人の手直しを消さない
----------------------------
照合は何度でもやり直せる(候補の日数や設定を変えれば結果は変わる)。素朴に
DELETE→INSERT すると、そのたびに ``approved`` / ``edited`` / ``excluded`` / ``memo`` と、
人が手で差し替えたgiftが消える。**再照合のたびに人の作業が消える台帳は、二度と使われない。**

かといって ``idx`` で対応付けることもできない。gift演出の切り出しは音の指紋から出るので、窓や
hopを変えればgift演出の数も並びも変わる。3番目だったgift演出が4番目になったとき、``idx`` で突き
合わせれば人の確認は**別のgift演出へ移る** —— 消えるより悪い(間違った物が承認済みになる)。

対応付けの鍵は **highlight自身の時間軸の区間**(``start`` / ``end``)にする。highlightのfileは
変わらないので、同じ区間を覆うgift演出は同じgift演出である。実装は次のとおり:

* 新旧の区間の重なりを ``重なり / 短い方の長さ`` で測り、大きい順に1対1で結ぶ
  (:data:`SEGMENT_REUSE_MIN_OVERLAP` 未満は結ばない)。
* 結んだ行は**同じidのまま更新**する。機械の列(votes/ratio/corr/confidence/recording_id/
  media_start/effect)は新しい値で置き換え、人の列は残す。
* ``edited`` が立っている行は ``start`` / ``end`` とgift列も人のものを残す。media_startだけは
  新しい照合の**ずれ**を人のstartへ載せ直す(``新media_start + (人のstart - 新start)``)——
  録画の中の位置は照合が決めるもので、人が触ったのはhighlight側の端だからである。
* 新しいgift演出に相手が居なければ追加する。
* 古い行に相手が居ないとき、人の入力を持たない行は消す。持つ行は ``dropped`` を立てて残し、
  同時に ``excluded`` も立てる —— 今回の照合が指す場所を持たないgift演出なので、出力へ入れては
  ならない。人の入力そのものは1文字も書き換えない。

週ぜんたいの俯瞰(:meth:`HighlightsMixin.highlight_coverage`)
------------------------------------------------------------
1本ずつの照合結果は「このhighlightは何から出来ているか」しか言えない。照合が正しいかを
人が確かめるには**逆向き**の面が要る —— その週のgiftを全部並べ、highlightのどこに現れたかを
添える。**主語はgiftであってhighlightではない。** 並べるのは**対象gifter(週合計
``MENTION_POST_MIN``)のgiftだけ**である —— 確かめる相手はfileになる週の中身なので、
fileが作られない人のgiftは母集団に入れない。週の窓と対象gifterの規則は
``tictok.store.streamers`` のメンション一覧が唯一の持ち主で、ここは同じ経路を通すだけである。
"""
import dataclasses
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from tictok.core import config, ffprobe, layout
# gift演出の点(:func:`highlight_match.score_of`)は**保存しない**ので、読み出すたびにここで
# 出す。``highlight_match`` は store を一切import しないので循環しない。点の目盛りを
# 照合側と同じ1箇所から採るために、写し取らずにそのまま呼ぶ。
from tictok.media import highlight_match
# 週の窓と対象gifterの規則は**メンション一覧が唯一の持ち主**である(境界は土曜7時、
# 対象は週合計 ``MENTION_POST_MIN``)。ここで同じ規則を書き直すと、配信者画面と俯瞰の面で
# 数が食い違い、検証の道具として使えなくなる ―― 突き合わせの取りこぼしを疑うべき場面で、
# 人はまず「どちらの数が正しいのか」で止まる。
from tictok.store.streamers import (
    MENTION_POST_MIN, WEEK_SATURDAY, _period_bounds, _period_key, _post_range_label,
    _week_label,
)

logger = logging.getLogger("tictok.storage")

# 台帳に載せるhighlightの拡張子。TikTokが出すのはmp4だけで、置き場には落としたときの
# サムネやjsonが混ざる。
HIGHLIGHT_EXTENSIONS = (".mp4",)

# 行のstate。'missing' は走査でfileが見つからなかった行で、行そのものは消さない
# (segmentに人の手直しが貼り付いている)。fileが戻れば走査がstatusを戻す。
HIGHLIGHT_STATUS_NEW = "new"
HIGHLIGHT_STATUS_MATCHING = "matching"
HIGHLIGHT_STATUS_MATCHED = "matched"
HIGHLIGHT_STATUS_FAILED = "failed"
HIGHLIGHT_STATUS_MISSING = "missing"
HIGHLIGHT_STATUSES = (HIGHLIGHT_STATUS_NEW, HIGHLIGHT_STATUS_MATCHING,
                      HIGHLIGHT_STATUS_MATCHED, HIGHLIGHT_STATUS_FAILED,
                      HIGHLIGHT_STATUS_MISSING)

# 再照合で同じgift演出と見なす重なりの下限(重なり / 短い方の長さ)。
# gift演出は平均6秒・短いと2.5秒(doc/HIGHLIGHT_MATCH.md)なので、半分を超えて重なる別のgift演出は
# 現れない。ここを下げると隣り合うgift演出が結ばれ、人の確認が隣へ移る。
SEGMENT_REUSE_MIN_OVERLAP = 0.5

# gift演出の機械側の列。再照合はここだけを書き換える(人の列は :data:`_HUMAN_COLUMNS`)。
_MACHINE_COLUMNS = ("start", "end", "recording_id", "media_start", "votes", "ratio",
                    "corr", "confidence", "effect_json")
# 人の入力(gift演出)。ここが1つでも埋まっている行は、照合結果から消えても残す。
# ``edited`` は**gift演出の端を動かした**印だけを意味する。giftの差し替えは gift行の
# ``manual`` で、2つを1つにすると端の微調整だけで人のgift差し替えが守られる(逆も起きる)。
_HUMAN_COLUMNS = ("approved", "edited", "excluded", "memo")

# gift 1件の列。``highlight_segment_gifts`` の、eventから来る値。
_GIFT_EVENT_COLUMNS = ("gift_event_id", "gift_id", "gift_name", "diamonds", "gift_count",
                       "gift_image", "user_unique_id", "user_nickname", "user_id",
                       "identity_key", "gift_media_time")
# gift 1件の機械側の列。再照合はここを書き換える。
_GIFT_MACHINE_COLUMNS = ("idx", "inside", "is_primary", "show_start", "show_end")
# 人の入力(gift)。``manual`` は差し替え/追加、``excluded`` はこの1件だけを出力から外した印、
# ``cut_start``/``cut_end`` はこのgiftだけの切り出し範囲(NULLならgift演出の窓)、``chosen`` は
# 「このgiftはこの1本を使う」と人が選んだ印である。
_GIFT_HUMAN_COLUMNS = ("manual", "excluded", "cut_start", "cut_end", "chosen")


def _segment_dict(segment) -> dict:
    """``highlight_match`` が返すSegment(dataclass)もdictも同じ形で読む。

    照合側の型に台帳が縛られないようにするためで、値の意味づけはしない(欠けたkeyは
    欠けたまま扱う —— 既定値で埋めると、測れなかったことと0が区別できなくなる)。"""
    if dataclasses.is_dataclass(segment) and not isinstance(segment, type):
        return dataclasses.asdict(segment)
    return dict(segment)


def gift_unit_diamonds(diamonds, gift_count) -> int:
    """そのgift **1個あたり**の💎。下限の判定はこの値で行う。

    ``events.diamonds`` は**まとめ投げの合計**である(``diamonds_each × gift_count``)。
    30💎のgiftを9個まとめて投げると1 eventで270💎になり、合計で下限(98💎)を判定すると
    「演出が出る高額gift」として通ってしまう —— 実際に画面へ出るのは30💎の小さなbannerが
    9回で、切り抜きに載せる場面ではない。**個数で割った単価が「その1発に演出が出るか」の
    判定材料**であり、合計はその人が払った額でしかない(順位もfile名もそちらを使う)。

    ``gift_count`` が無い/0の行は1個として扱う。この列が無かった頃に書かれた行と、
    まとめ投げでないgiftを同じに読むためで、その場合は合計＝単価である。
    """
    if diamonds is None:
        return 0
    count = int(gift_count or 0)
    if count <= 1:
        return int(diamonds)
    # 端数は切り捨てない。単価は整数のはずだが、丸めで下限をまたぐ行を作らない。
    return int(int(diamonds) // count)


def gift_position(start, media_start, gift_media_time):
    """そのgiftが **highlight自身の時間軸**で何秒目か。出せなければ None。

    ``gift演出の頭 + (giftのmedia秒 - gift演出のmedia秒)``。**gift演出の頭ではない**。giftはその頭に
    在るとは限らず、実測で7312.50のgift演出に対しgiftは7313.67(1.2秒後ろ)だった。gift演出の頭を
    「giftの位置」として返すと、画面の飛び先も代表frameも毎回gift演出の頭になり、しかも
    「だいたい合っている」ので誰も気付かない。

    差ではなく ``gift_media_time``(絶対秒)から毎回引き直す。差で持つと、人がgift演出の端を
    1秒ずらした瞬間にgiftの位置まで1秒動く —— 動いていないのは録画の中のgiftの方である。

    録画が当たっていないgift演出では **None**。gift演出の頭で代用しない(位置が判っているように
    見える数字が出る)。読む側が ``start`` へ落とすかどうかは、読む側が決めること。"""
    if media_start is None or gift_media_time is None:
        return None
    return round(float(start) + float(gift_media_time) - float(media_start), 3)


def gift_cut(segment_start, segment_end, gift, video_start=None,
             video_end=None) -> tuple:
    """そのgiftを**実際に切り出す範囲** ``(頭, 尻)``。highlight自身の時間軸の秒。

    人が窓を持たせていなければ既定の窓を返す。``cut_start``/``cut_end`` が NULL で
    あることは「まだ触っていない」という意味であって、既定値ではない —— gift演出の値をDBへ
    copyして埋めると、再照合でgift演出が動いたときに、人が一度も触っていないgiftの窓だけが
    古い場所へ取り残される。

    **既定の窓はgift演出の窓ではなく、映像が綺麗な区間である。** gift演出の境目は**音**で決まって
    いて、TikTokのmontageは音を一瞬で切り替えながら映像には切り替わりの演出を掛ける
    (:mod:`tictok.media.highlight_switch`)。演出は境目を跨ぐので、両端とも動かす:

    - 頭は ``video_start``(前の場面が退き切る秒)。``segment_start`` のままにすると、
      **全部の切り出しの頭に前のgiftの場面と演出が残る**(実測29箇所で中央値0.60秒あと)。
    - 尻は ``video_end``(次の場面が現れ始める秒)。``segment_end`` のままにすると、
      **切り出しの終わりに次のgiftが映る**(実測で最大0.93秒手前から現れていた)。1本の中で
      「2人目のgiftの終わりに3人目のgiftが少し映る」形になり、誰のgiftかを誤認させる。

    ``video_start``/``video_end`` がgift演出の外を指すときは使わない。人がgift演出の端を動かした後に
    起こる形で、映像の側は動いていない以上どちらが正しいとも言えないためである(人の端を採る)。

    **片方だけ埋まっている行は無い**(:meth:`HighlightsMixin.update_highlight_segment_gift`
    が必ず2つ揃えて書く)。それでも両方を見てから返すのは、DBを直に触られた行で片側だけの
    値が「窓が在る」と読まれないようにするためである。

    範囲はgift演出の中へ丸めない。**丸めるとしたら書く側**で、読む側で黙って丸めると、外へ
    出た値が画面には正しく見えて出力だけ別の場所を切る形になる。"""
    start = _cut_value(gift, "cut_start")
    end = _cut_value(gift, "cut_end")
    if start is None or end is None:
        return default_cut(segment_start, segment_end, video_start, video_end, gift)
    return float(start), float(end)


def default_cut(segment_start, segment_end, video_start=None,
                video_end=None, gift=None) -> tuple:
    """人が触っていないgiftの既定の窓 ``(頭, 尻)``。計算はここ1箇所にする。

    画面(既定へ戻す操作)・書き出し・検証がそれぞれ「無ければgift演出の窓」を書くと、いつか
    どれか1つだけが取り残されて、詰めたはずの窓と別の場所が切り出される。

    **見せ場が測れているgiftは、その見せ場がそのまま既定の窓である。** TikTokのclientは
    全画面演出を順番待ちで1つずつ流すので、montageが切られずに繋がった1続きの場面には別人の
    演出が何本も並ぶ —— 実測(hl12 / 20.9秒)で4件のgiftの演出が順に並んでおり、gift演出の窓を
    そのまま渡すと**主の1本に他人の見せ場が3つ続いた**。見せ場は照合が測って
    ``show_start``/``show_end`` に置く(:func:`tictok.media.highlight_match._attach_shows`)。
    映像の切り替わりまで詰めた後の値なので、ここで ``video_start``/``video_end`` を重ねない。

    ``show_*`` がNULLなのは「そのgift演出を割っていない」ことで、**gift演出の窓と同じという
    意味ではない**。割れるのは演出の数と載ったgiftの数が一致したときだけなので、多くの行は
    NULLのままgift演出の窓を使う。

    測れていない端は動かさない。**推測で埋めない** ―― 測れなかった境目で「たぶんこのくらい」
    を引くと、そのgift演出だけ理由の無い秒が切り落とされる。"""
    show_start = _cut_value(gift, "show_start")
    show_end = _cut_value(gift, "show_end")
    if show_start is not None and show_end is not None:
        return float(show_start), float(show_end)
    low = float(segment_start)
    high = float(segment_end)
    if video_end is not None:
        at = float(video_end)
        if low < at <= high:
            high = at
    if video_start is not None:
        at = float(video_start)
        if low <= at < high:
            low = at
    return low, high


def _cut_value(gift, name):
    """gift行の列を1つ読む。dictでも ``sqlite3.Row`` でも、列が無くても None。

    ``sqlite3.Row`` は ``.get()`` を持たず、無い列で ``IndexError`` を投げる。読む側を
    dictへ変換させると、俯瞰(coverage)の数百行ぶん辞書が増える。"""
    if gift is None:
        return None
    try:
        return gift[name]
    except (KeyError, IndexError, TypeError):
        return None


def _overlap_ratio(a: tuple, b: tuple) -> float:
    """2つの区間の重なりを、短い方の長さで割った比。重ならなければ0。"""
    overlap = min(a[1], b[1]) - max(a[0], b[0])
    if overlap <= 0:
        return 0.0
    shortest = min(a[1] - a[0], b[1] - b[0])
    return overlap / shortest if shortest > 0 else 0.0


def _iter_highlight_files(base: Path):
    """置き場の下のhighlight fileを、**浅い方から**名前順に返す。

    subfolderまで辿るのは、利用者が置き場の下へ週ごとのfolder(``20260829-20260905``)を
    作って素材を仕分けるためである。直下しか見ない走査では、仕分けた瞬間に行が
    「fileが無い」へ倒れ、照合結果と人の手直しがそこへ道連れになる。

    浅い方から返すのは :meth:`HighlightsMixin.scan_highlights` の先勝ちに効く —— 同じ
    file名が置き場の直下とsubfolderの両方に在れば、直下の方を採る(仕分けの途中では
    両方に在り得る。実体は1本なので行も1本にする)。
    """
    for current, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(current) / name
            if path.suffix.lower() in HIGHLIGHT_EXTENSIONS:
                yield path


class HighlightsMixin:
    """highlightの台帳と突き合わせ結果。契約の詳細はmodule docstringを参照。"""

    # ===== 行 -> dict =====

    @staticmethod
    def _highlight_row(row) -> dict:
        item = dict(row)
        item["scope"] = json.loads(item.pop("scope_json", None) or "null")
        return item

    @staticmethod
    def _score_fields(row) -> dict:
        """gift演出の点(0〜100)と、**いま効いている条件**。

        点は列に持たない —— 元になる ``votes``/``ratio``/``corr`` は表に在るので、読むたびに
        出せばよい。列にすると、目盛りを直した日に古い行だけが古い目盛りの点を名乗る。

        録画が当たっていないgift演出(``confidence`` が "none")には点を付けない。0点は「合って
        いない」だが、**そもそも比べる相手が居ない**のは別のことである。"""
        if str(_cut_value(row, "confidence") or "") == "none":
            return {"score": None, "score_weakest": ""}
        found = highlight_match.score_of(_cut_value(row, "votes") or 0,
                                         _cut_value(row, "ratio") or 0.0,
                                         _cut_value(row, "corr") or 0.0)
        return {"score": found["score"], "score_weakest": found["weakest"]}

    @staticmethod
    def _highlight_segment_row(row, gifts=()) -> dict:
        """gift演出1行を画面の形へ。gift 1件ずつの ``at``(highlight内の秒)はここで足す。

        画面にも書き出しにも同じ秒が要る(飛び先・代表frame)ので、**計算する場所を1つに
        する**。読む側が ``start + (gift_media_time - media_start)`` を各自で書くと、
        いつか片方だけがgift演出の頭へ落ちて、それらしい別の場面が並ぶ。

        ``primary`` は「そのgift演出の主のgift」で、**1件しか無い前提で読んではいけない**。
        ここが空でもgift演出としては正しい(giftを持たないgift演出は実測で10個中3個ある)。"""
        item = dict(row)
        item["effect"] = json.loads(item.pop("effect_json", None) or "[]")
        start = item["start"]
        media_start = item.get("media_start")
        end = item["end"]
        # 映像の両端。**測っていないこと**(video_probed=0)と**測って決まらなかったこと**
        # (probed=1 かつ None)を画面が言い分けられるように、そのまま返す。
        video_start = item.get("video_start")
        video_end = item.get("video_end")
        item["video_probed"] = bool(item.get("video_probed"))

        def _gift(gift: dict) -> dict:
            cut_start, cut_end = gift_cut(start, end, gift, video_start, video_end)
            return {
                **gift,
                "inside": bool(gift["inside"]),
                "is_primary": bool(gift["is_primary"]),
                "manual": bool(gift["manual"]),
                "excluded": bool(gift["excluded"]),
                "dropped": bool(gift["dropped"]),
                # 人がこのgiftの当たりとして選んだ1本か。**同じgiftが複数のhighlightに
                # 入る**ので、どれを使うかは機械の順位ではなく人の選択が先に立つ。
                "chosen": bool(gift["chosen"]),
                # 実際に切り出す範囲。**窓を持たない行にも必ず入れる** —— 読む側が
                # 「無ければgift演出の窓」を各自で書くと、いつか片方だけがgift演出の窓のままに
                # なり、詰めたはずのgiftが元の長さで出力へ入る(数字は出るので気付かない)。
                "cut_start": cut_start,
                "cut_end": cut_end,
                # 人がこのgiftだけの窓を持たせているか。上の2つは「持っていなければgift演出の
                # 窓」なので、この真偽値が無いと画面が「触ったかどうか」を読めない。
                "cut_own": (_cut_value(gift, "cut_start") is not None
                            and _cut_value(gift, "cut_end") is not None),
                "at": gift_position(start, media_start, gift["gift_media_time"]),
            }

        item["gifts"] = [_gift(gift) for gift in gifts]
        item["primary"] = next(
            (gift for gift in item["gifts"] if gift["is_primary"]), None)
        item.update(HighlightsMixin._score_fields(row))
        return item

    # ===== 走査 =====

    def scan_highlights(self, unique_id: str = "") -> dict:
        """置き場を走査して行を作り直す。``{added, updated, missing, dirs}`` を返す。

        ``unique_id`` を省くと、置き場を持つ配信者すべて(``layout.highlight_streamers``)。

        置き場の**subfolderまで辿る**(``_iter_highlight_files``)。利用者は置き場の下へ週ごとの
        folderを作って素材を仕分けるので、直下しか見ないと仕分けた行が「fileが無い」へ倒れ、
        照合結果と人の手直しが道連れになる。行の ``source_dir`` は**fileを抱えているfolder**
        (置き場ではない)で、一覧はそれで畳んで出す。

        同じfile名が複数の置き場に在れば、``highlight_dirs`` の順で先に当たった方を採る
        (移行の途中では正規の置き場と現行の置き場の両方に同じ物が在る)。行は1本にして、
        見つけた場所を上書きする。

        尺(ffprobe)を引くのは**新しい行とbytesが変わった行だけ**。走査はfileを開かない前提の
        安い操作で、置き場の全fileを毎回probeすると押すたびに数秒かかる。
        """
        streamers = [unique_id] if unique_id else layout.highlight_streamers()
        found: dict = {}
        dirs: list = []
        for streamer in streamers:
            for base in layout.highlight_dirs(streamer):
                root_key = layout.root_key_of(base)
                dirs.append({"unique_id": streamer, "root_key": root_key,
                             "source_dir": layout.source_dir_of(base, root_key),
                             "path": str(base)})
                for path in _iter_highlight_files(base):
                    try:
                        stat = path.stat()
                    except OSError:
                        # 走査の途中で消えたfile。次の走査で missing として現れる。
                        continue
                    if not path.is_file():
                        continue
                    key = (streamer, path.name)
                    if key in found:
                        continue
                    found[key] = {
                        "path": str(path), "root_key": root_key,
                        # **fileを抱えているfolderを名乗る**(置き場ではない)。置き場の名前
                        # で揃えると、仕分けたsubfolderが台帳のどこにも残らない。
                        "source_dir": layout.source_dir_of(path.parent, root_key),
                        "bytes": stat.st_size,
                    }

        with self._lock:
            existing = {
                (row["unique_id"], row["filename"]): dict(row)
                for row in self._conn.execute(
                    "SELECT id, unique_id, filename, path, root_key, source_dir, bytes,"
                    " duration_seconds, status, matched_at FROM highlight_videos"
                    + (" WHERE unique_id = ?" if unique_id else ""),
                    (unique_id,) if unique_id else (),
                ).fetchall()
            }

        added = 0
        updated = 0
        now = time.time()
        for (streamer, filename), item in sorted(found.items()):
            row = existing.get((streamer, filename))
            if row is None:
                duration = ffprobe.duration_seconds_sync(
                    item["path"], timeout=ffprobe.SHORT_TIMEOUT_SECONDS)
                with self._lock:
                    self._conn.execute(
                        "INSERT INTO highlight_videos"
                        " (unique_id, filename, path, root_key, source_dir, bytes,"
                        "  duration_seconds, status, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (streamer, filename, item["path"], item["root_key"],
                         item["source_dir"], item["bytes"], duration,
                         HIGHLIGHT_STATUS_NEW, now),
                    )
                    self._conn.commit()
                added += 1
                continue
            # 実体が戻った / 置き場が変わった / 中身が差し替わった。statusは「照合が
            # 済んでいるか」なので、消えていた行はmatched_atの有無で元へ戻す(推測しない)。
            status = row["status"]
            if status == HIGHLIGHT_STATUS_MISSING:
                status = (HIGHLIGHT_STATUS_MATCHED if row["matched_at"]
                          else HIGHLIGHT_STATUS_NEW)
            duration = row["duration_seconds"]
            if row["bytes"] != item["bytes"] or duration is None:
                duration = ffprobe.duration_seconds_sync(
                    item["path"], timeout=ffprobe.SHORT_TIMEOUT_SECONDS)
            changed = (row["path"] != item["path"] or row["root_key"] != item["root_key"]
                       or row["source_dir"] != item["source_dir"]
                       or row["bytes"] != item["bytes"]
                       or row["duration_seconds"] != duration
                       or row["status"] != status)
            if not changed:
                continue
            with self._lock:
                self._conn.execute(
                    "UPDATE highlight_videos SET path = ?, root_key = ?, source_dir = ?,"
                    " bytes = ?, duration_seconds = ?, status = ? WHERE id = ?",
                    (item["path"], item["root_key"], item["source_dir"], item["bytes"],
                     duration, status, row["id"]),
                )
                self._conn.commit()
            updated += 1

        gone = [row for key, row in existing.items()
                if key not in found and row["status"] != HIGHLIGHT_STATUS_MISSING]
        if gone:
            with self._lock:
                self._conn.executemany(
                    "UPDATE highlight_videos SET status = ? WHERE id = ?",
                    [(HIGHLIGHT_STATUS_MISSING, row["id"]) for row in gone],
                )
                self._conn.commit()
        logger.info(
            "highlightの置き場を走査しました: 追加=%d 更新=%d 消失=%d（置き場 %d箇所）",
            added, updated, len(gone), len(dirs),
            extra={"event": "highlight.scanned",
                   "ctx": {"unique_id": unique_id, "added": added, "updated": updated,
                           "missing": len(gone), "dirs": [d["path"] for d in dirs]}},
        )
        return {"added": added, "updated": updated, "missing": len(gone), "dirs": dirs}

    # ===== 読む =====

    def list_highlights(self, unique_id: str = "", status: str = "") -> list:
        """台帳の行を、gift演出とgiftの集計を添えて新しい順に。

        集計を行ごとの追加queryにしないのは、一覧がhighlightの本数ぶんqueryを撃つことに
        なるため。除外したgift演出も除外したgiftも数に入れない —— 「出力に入るのは何件で
        幾らぶんか」が一覧の読みどころである。

        **giftがgift演出から別表へ出たとき、意味の変わる数は名前も変えた。**

        * ``gift_segment_count`` … giftを1件以上持つgift演出の数(旧 ``gift_count``)
        * ``gift_total_count``   … giftの件数。gift演出1つが複数のgiftを持つので別の数になる
        * ``gift_diamonds``      … 全giftの合計(旧 ``total_diamonds`` はgift演出ごと1件の合計)

        ``segment_count`` と ``top_diamonds`` は意味が変わらないので名前も据え置く。名前を
        残したまま数だけ変えると、画面はそれを読んでいるので**気付かないまま別の数を出す**。
        """
        where: list = []
        params: list = []
        if unique_id:
            where.append("h.unique_id = ?")
            params.append(unique_id)
        if status:
            where.append("h.status = ?")
            params.append(status)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self._lock:
            rows = self._conn.execute(
                "SELECT h.*,"
                " (SELECT COUNT(*) FROM highlight_segments s"
                "   WHERE s.highlight_id = h.id AND s.excluded = 0) AS segment_count,"
                " (SELECT COUNT(DISTINCT g.segment_id) FROM highlight_segment_gifts g"
                "   JOIN highlight_segments s ON s.id = g.segment_id"
                "   WHERE g.highlight_id = h.id AND s.excluded = 0"
                "     AND g.excluded = 0) AS gift_segment_count,"
                " (SELECT COUNT(*) FROM highlight_segment_gifts g"
                "   JOIN highlight_segments s ON s.id = g.segment_id"
                "   WHERE g.highlight_id = h.id AND s.excluded = 0"
                "     AND g.excluded = 0) AS gift_total_count,"
                " (SELECT MAX(g.diamonds) FROM highlight_segment_gifts g"
                "   JOIN highlight_segments s ON s.id = g.segment_id"
                "   WHERE g.highlight_id = h.id AND s.excluded = 0"
                "     AND g.excluded = 0) AS top_diamonds,"
                " (SELECT SUM(g.diamonds) FROM highlight_segment_gifts g"
                "   JOIN highlight_segments s ON s.id = g.segment_id"
                "   WHERE g.highlight_id = h.id AND s.excluded = 0"
                "     AND g.excluded = 0) AS gift_diamonds"
                " FROM highlight_videos h" + clause +
                " ORDER BY h.created_at DESC, h.id DESC",
                params,
            ).fetchall()
            weeks = self._highlight_week_index(self._conn, clause, params)
        items = []
        for row in rows:
            item = self._highlight_row(row)
            found = weeks.get(item["id"]) or {}
            item["week"] = found.get("week", "")
            item["week_label"] = found.get("week_label", "")
            item["weeks"] = found.get("weeks", [])
            items.append(item)
        return items

    def _highlight_week_index(self, conn, clause: str, params: list) -> dict:
        """``{highlight_id: {"week", "week_label", "weeks"}}``。素材がいつの週の物かを返す。

        **highlightは自分の時刻を持たない。** fileの日付は落とした日で配信の日ではなく、
        名前にも配信日は入っていない。「いつの素材か」を言えるのは**当たったgiftのeventの
        時刻**だけなので、週はそこから決める —— まだ照合していない本はどの週にも属さない
        (置き場に在るだけの素材を「この週の物」と名乗る根拠が無い。推測で埋めない)。

        週の区切りは :meth:`streamer_mention_week` と同じ土曜7時始まりで、keyの作り方も
        あちらの ``_period_key`` をそのまま通す —— ここで日付から組み直すと、出力の週選択と
        素材の週が別の境目で切られ、境目の配信だけが黙って外れる。

        ``weeks`` は**跨いだ週を全部**返す。1本のhighlightはLIVE replay 1本 = 配信1回から
        作られるので普通は1つだが、土曜7時を跨いだ配信では2つになる。多い方へ丸めて1つに
        すると、跨がれた側の週で「この週の素材が無い」と見える。``week`` はその中で最も
        giftの多い週(同数なら新しい方)で、一覧に1つだけ名乗るための代表である。
        """
        rows = conn.execute(
            "SELECT g.highlight_id AS highlight_id, e.time AS time"
            " FROM highlight_segment_gifts g"
            " JOIN highlight_segments s ON s.id = g.segment_id"
            " JOIN highlight_videos h ON h.id = g.highlight_id"
            " JOIN events e ON e.id = g.gift_event_id"
            " WHERE g.dropped = 0 AND s.dropped = 0"
            + (clause.replace(" WHERE ", " AND ") if clause else ""),
            params,
        ).fetchall()
        counts: dict = {}
        for row in rows:
            key = _period_key(row["time"], WEEK_SATURDAY)
            counts.setdefault(row["highlight_id"], {})
            counts[row["highlight_id"]][key] = counts[row["highlight_id"]].get(key, 0) + 1
        out: dict = {}
        for highlight_id, tally in counts.items():
            keys = sorted(tally)
            # 代表は件数の多い週。同数なら新しい方 —— 境目を跨いだ配信は後ろ側が本編である
            # ことが多く、どちらでも良い場合に古い方を名乗ると一覧が前の週へ寄る。
            week = max(keys, key=lambda k: (tally[k], k))
            out[highlight_id] = {
                "week": week,
                "week_label": _week_label(_period_bounds(week, WEEK_SATURDAY)[0]),
                "weeks": keys,
            }
        return out

    def get_highlight(self, highlight_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM highlight_videos WHERE id = ?", (highlight_id,)
            ).fetchone()
        return self._highlight_row(row) if row else None

    def highlight_segments(self, highlight_id: int) -> list:
        """その highlight のgift演出を並び順(idx)で。**giftの列と**当たった録画の身元を添える。

        録画は消え得るのでLEFT JOINで引く。消えた録画を指すgift演出は行としては正しい
        (「このgift演出はここから来た」という過去の照合結果である)ので、隠さない。

        ``gifts`` は**そのgift演出のgiftを時刻順に全部**。1件しか返さない形には戻さない ――
        segmentは最長8.3秒あり、その中に演出を持つgiftが複数入る。高額な1件だけを返すと、
        画面に映っている演出の主が落ちて**別人の名前が付く**(doc/HIGHLIGHT_MATCH.md)。

        読み出しの口はここ1つである(書き出しの :func:`highlight_export._fetch_segments` も
        通る)。SQLを外に書き下ろすと、表の変更に片方だけが追従して黙って食い違う。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.*, r.filename AS recording_filename,"
                " r.started_at AS recording_started_at"
                " FROM highlight_segments s"
                " LEFT JOIN recordings r ON r.id = s.recording_id"
                " WHERE s.highlight_id = ? ORDER BY s.idx, s.id",
                (highlight_id,),
            ).fetchall()
            gifts = self._conn.execute(
                "SELECT * FROM highlight_segment_gifts WHERE highlight_id = ?"
                " ORDER BY segment_id, idx, id", (highlight_id,)).fetchall()
        by_segment: dict = {}
        for row in gifts:
            by_segment.setdefault(row["segment_id"], []).append(dict(row))
        out: list = []
        for row in rows:
            item = self._highlight_segment_row(row, by_segment.get(row["id"], []))
            filename = item.pop("recording_filename", None)
            started_at = item.pop("recording_started_at", None)
            item["recording"] = (
                {"id": item["recording_id"], "filename": filename,
                 "started_at": started_at}
                if item["recording_id"] is not None and filename is not None else None)
            out.append(item)
        return out

    # ===== 照合の状態 =====

    def set_highlight_status(self, highlight_id: int, status: str, *,
                             error: Optional[str] = None,
                             scope: Optional[dict] = None) -> None:
        """照合の進み具合を行へ書く。``error`` は失敗の理由をそのまま残す。

        ``scope`` を渡した呼び出しだけが設定を上書きする。投入時に書いておくのは、実行が
        始まる前に取り消された行でも「何をやろうとしたか」が残るようにするためである。"""
        if status not in HIGHLIGHT_STATUSES:
            raise ValueError(f"未知のhighlight statusです: {status}")
        with self._lock:
            self._conn.execute(
                "UPDATE highlight_videos SET status = ?, error = ?,"
                " scope_json = COALESCE(?, scope_json) WHERE id = ?",
                (status, error,
                 json.dumps(scope, ensure_ascii=False) if scope is not None else None,
                 highlight_id),
            )
            self._conn.commit()

    def delete_highlight(self, highlight_id: int) -> bool:
        """台帳の行だけを消す(mp4には触らない)。gift演出はCASCADEで一緒に消える。

        mp4を消さないのは、これがこちらが作った成果物ではなく**外から来た素材**だからである。
        次に走査すれば同じfileが新しい行として戻る。"""
        with self._lock:
            # FK pragmaは有効なのでCASCADEが効くが、明示しておく方が読める。
            self._conn.execute(
                "DELETE FROM highlight_segments WHERE highlight_id = ?", (highlight_id,))
            cursor = self._conn.execute(
                "DELETE FROM highlight_videos WHERE id = ?", (highlight_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    # ===== 照合結果の保存 =====

    def save_highlight_match(self, highlight_id: int, result: dict) -> dict:
        """突き合わせ結果を保存する。``{kept, added, removed, dropped, gifts}`` を返す。

        人が直した内容を消さない保存の仕方はmodule docstringにある。ここでは対応付けの
        結果だけを数えて返す —— 何件が引き継がれ、何件が消え、何件が行き場を失ったかは、
        再照合を押した人が知りたい唯一の数字である。

        **対応付けは2段である。** 先にgift演出を highlight自身の時間軸の区間の重なりで結び、
        結んだgift演出の中で giftを ``gift_event_id`` で結ぶ。段を混ぜてはいけない ——
        重なり0.5という閾値はgift演出の尺(平均6秒・最短2.5秒)で決めた値で、**点であるgiftには
        意味が無い**。giftを時刻の近さで結ぶのも同じ理由で駄目で、それは「演出の直前の10💎が
        6000💎に勝つ」罠を対応付けの側で踏み直すことになる。
        """
        segments = [_segment_dict(seg) for seg in (result.get("segments") or [])]
        with self._lock:
            old = [dict(row) for row in self._conn.execute(
                "SELECT * FROM highlight_segments WHERE highlight_id = ? ORDER BY idx, id",
                (highlight_id,)).fetchall()]
            old_gifts: dict = {}
            for row in self._conn.execute(
                    "SELECT * FROM highlight_segment_gifts WHERE highlight_id = ?",
                    (highlight_id,)).fetchall():
                old_gifts.setdefault(row["segment_id"], []).append(dict(row))
        pairs = self._pair_highlight_segments(old, segments)
        matched_old_ids = set(pairs.values())

        kept = added = gift_total = 0
        now = time.time()
        with self._lock:
            for index, new in enumerate(segments):
                old_id = pairs.get(index)
                row = next((r for r in old if r["id"] == old_id), None)
                values = self._highlight_segment_values(new, row)
                if row is None:
                    cursor = self._conn.execute(
                        "INSERT INTO highlight_segments"
                        " (highlight_id, idx, start, end, recording_id, media_start,"
                        "  votes, ratio, corr, confidence, effect_json,"
                        "  video_start, video_end, video_probed)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (highlight_id, index, values["start"], values["end"],
                         values["recording_id"], values["media_start"], values["votes"],
                         values["ratio"], values["corr"], values["confidence"],
                         values["effect_json"], values["video_start"],
                         values["video_end"], values["video_probed"]),
                    )
                    segment_id = cursor.lastrowid
                    added += 1
                else:
                    self._conn.execute(
                        "UPDATE highlight_segments SET idx = ?, start = ?, end = ?,"
                        " recording_id = ?, media_start = ?, votes = ?, ratio = ?,"
                        " corr = ?, confidence = ?, effect_json = ?, video_start = ?,"
                        " video_end = ?, video_probed = ?, dropped = 0"
                        " WHERE id = ?",
                        (index, values["start"], values["end"], values["recording_id"],
                         values["media_start"], values["votes"], values["ratio"],
                         values["corr"], values["confidence"], values["effect_json"],
                         values["video_start"], values["video_end"],
                         values["video_probed"], row["id"]),
                    )
                    segment_id = row["id"]
                    kept += 1
                gift_total += self._save_highlight_segment_gifts(
                    highlight_id, segment_id, new.get("gifts") or [],
                    old_gifts.get(segment_id, []),
                    old_span=(None if row is None
                              else (float(row["start"]), float(row["end"]))),
                    new_span=(values["start"], values["end"]))

            # 相手の居ない古い行。人の入力を持たない行は消し、持つ行は印を付けて残す。
            orphans = [row for row in old if row["id"] not in matched_old_ids]
            removed = [row for row in orphans if not self._has_human_input(row)]
            dropped = [row for row in orphans if self._has_human_input(row)]
            if removed:
                # giftはON DELETE CASCADEで一緒に消える(gift演出が消えたのだから、そのgiftが
                # 指す場所も無い)。
                self._conn.executemany(
                    "DELETE FROM highlight_segments WHERE id = ?",
                    [(row["id"],) for row in removed])
            for offset, row in enumerate(dropped):
                # 並びの末尾へ寄せる。今回の照合が指す場所を持たないgift演出なので、
                # 出力からは外す(人が戻したければ excluded を落とせばよい)。
                self._conn.execute(
                    "UPDATE highlight_segments SET idx = ?, dropped = 1, excluded = 1"
                    " WHERE id = ?", (len(segments) + offset, row["id"]))
                # giftも道連れにする。gift演出が今回の照合の指す場所を持たない以上、その中の
                # giftも同じである(人の入力そのものは1文字も書き換えない)。
                self._conn.execute(
                    "UPDATE highlight_segment_gifts SET dropped = 1, excluded = 1,"
                    " is_primary = 0 WHERE segment_id = ?", (row["id"],))
            self._conn.execute(
                "UPDATE highlight_videos SET status = ?, error = NULL, matched_at = ?,"
                " scope_json = ?, duration_seconds = COALESCE(?, duration_seconds)"
                " WHERE id = ?",
                (HIGHLIGHT_STATUS_MATCHED, now,
                 json.dumps(result.get("scope") or {}, ensure_ascii=False),
                 result.get("seconds"), highlight_id),
            )
            self._conn.commit()
        stats = {"kept": kept, "added": added, "removed": len(removed),
                 "dropped": len(dropped), "gifts": gift_total}
        logger.info(
            "highlightの照合結果を保存しました（id=%s）: %s", highlight_id, stats,
            extra={"event": "highlight.match_saved",
                   "ctx": {"highlight_id": highlight_id, **stats,
                           "segments": len(segments)}},
        )
        return stats

    def update_highlight_switches(self, highlight_id: int, spans: list) -> int:
        """gift演出の**映像の切り替わり(頭と尻)だけ**を測り直した値で書き換える。書いた行数。

        ``spans`` は ``(映像の頭, 映像の尻)`` を **idxの順**に並べたもので、その
        highlightのgift演出の数と一致していなければならない。数が違うのはgift演出の側が動いて
        いるということなので、**書かずに失敗させる** —— 並びでしか結び付けられない値を
        ずれた行へ書くと、どのgift演出も自分のものでない秒を持つ。

        照合をやり直さずに済ませるための道である。音の指紋の突き合わせは録画を1週間ぶん
        読み直す重い段で、**切り替わりの測り方が変わっただけで走らせる理由が無い**。人の
        入力(approved/edited/memo/詰めた窓)にもgift演出の境目にも触らない。
        

        **見せ場(``highlight_segment_gifts.show_start``/``show_end``)はここでは測り直さない。**
        あちらは録画との差分から出る値で、この入口はhighlightのmp4しか読まない。gift演出の
        両端はここで動くが、割った見せ場の中身は前回の照合のままである ——見せ場を測り直す
        なら照合をやり直すこと。
        """
        with self._lock:
            rows = [dict(row) for row in self._conn.execute(
                "SELECT id FROM highlight_segments WHERE highlight_id = ?"
                " ORDER BY idx, id", (highlight_id,))]
            if len(rows) != len(spans):
                raise RuntimeError(
                    f"gift演出の数が合いません（id {highlight_id}: 台帳 {len(rows)}件 / "
                    f"測定 {len(spans)}件）。先に照合をやり直してください。")
            self._conn.executemany(
                "UPDATE highlight_segments SET video_start = ?, video_end = ?,"
                " video_probed = 1 WHERE id = ?",
                [(None if span[0] is None else float(span[0]),
                  None if span[1] is None else float(span[1]), row["id"])
                 for row, span in zip(rows, spans)])
            self._conn.commit()
        logger.info(
            "highlightの映像の切り替わりを保存しました（id=%s）: %d件", highlight_id,
            len(rows),
            extra={"event": "highlight.switches_saved",
                   "ctx": {"highlight_id": highlight_id, "segments": len(rows)}},
        )
        return len(rows)

    @staticmethod
    def _gift_has_human_input(row) -> bool:
        """そのgift行に人の手が入っているか(:data:`_GIFT_HUMAN_COLUMNS`)。

        窓(``cut_start``)は **0.0 を取り得る**ので、真偽では見ない —— 真偽で見ると、
        highlightの頭から始まる窓を持たせた行だけが「人の入力なし」と判定されて、
        次の再照合で黙って消える。"""
        if row["manual"] or row["excluded"] or row["chosen"]:
            return True
        return row["cut_start"] is not None or row["cut_end"] is not None

    # 再照合でgift演出が動いたとき、これより短くなったgiftの窓は残さない。切っても中身の無い
    # 窓を持たせておくと、書き出しがそこで空のpartを作って落ちる(:mod:`highlight_export` の
    # ``MIN_CUT_SECONDS`` と同じ床)。
    _GIFT_CUT_MIN_SECONDS = 0.25

    def _reanchor_gift_cut(self, row: dict, old_span, new_span) -> tuple:
        """再照合でgift演出が動いた後のgiftの窓 ``(頭, 尻)``。窓が残らなければ ``(None, None)``。

        窓はgift演出の頭と一緒に動かす。人が詰めたのは「gift演出のこの辺り」であって、highlightの
        絶対秒そのものではない —— 動いていないのは録画の中の映像の方で、gift演出の頭が0.3秒
        ずれたなら人の窓も0.3秒ずれた場所に在る(``_highlight_segment_values`` が
        ``media_start`` を同じ考えで載せ直しているのと同じ写像)。

        動かした後は新しいgift演出の中へ丸める。montageなのでgift演出の外に映像は無く、はみ出した
        ままにすると出力だけが無関係な場面を切る。丸めて床(:data:`_GIFT_CUT_MIN_SECONDS`)を
        割ったら**窓を捨ててgift演出の窓へ戻す** —— 人の手直しが失われる操作なので、黙って
        行わずlogに残す。"""
        if row.get("cut_start") is None or row.get("cut_end") is None:
            return None, None
        if old_span is None:
            # gift演出が新しく作られた行にはこの列が在り得ない(INSERTした直後である)。
            return None, None
        shift = float(new_span[0]) - float(old_span[0])
        start = max(float(new_span[0]), float(row["cut_start"]) + shift)
        end = min(float(new_span[1]), float(row["cut_end"]) + shift)
        if end - start >= self._GIFT_CUT_MIN_SECONDS:
            return round(start, 3), round(end, 3)
        logger.warning(
            "再照合でgift演出が動いたため、giftの区間をgift演出の窓へ戻しました"
            "（segment=%s gift=%s）", row.get("segment_id"), row.get("id"),
            extra={"event": "highlight.gift_cut_reset",
                   "ctx": {"segment_id": row.get("segment_id"), "gift_row_id": row.get("id"),
                           "old_span": list(old_span), "new_span": list(new_span),
                           "cut": [row.get("cut_start"), row.get("cut_end")]}},
        )
        return None, None

    def _save_highlight_segment_gifts(self, highlight_id: int, segment_id: int,
                                      gifts: list, old: list, *,
                                      old_span=None, new_span=None) -> int:
        """1つのgift演出のgiftを保存し直す。書いたgiftの件数を返す。lock保持前提。

        **対応付けの鍵は ``gift_event_id`` だけ**である。giftはhighlight内の1点なので区間の
        重なりでは結べないし、時刻の近さで結ぶと「演出の直前の10💎が6000💎に勝つ」罠を
        対応付けの側で踏み直すことになる。event idは同じgiftを指す唯一の不変な鍵である。

        人が触ったgift(``manual`` / ``excluded``)は残す。機械の列(idx / inside / is_primary /
        is_primary)は毎回置き換えるが、eventから来る値は ``manual`` の行では人のものを保つ
        —— 人が差し替えたのは「どのeventか」そのものだからである。

        今回の照合に現れなかった古いgiftは、人の入力を持たなければ消し、持てば ``dropped``
        を立てて残す(同時に ``excluded`` も立てる。今回の照合が指す場所を持たないgiftを
        出力へ入れてはならない)。**gift演出ごとではなくgift 1件だけを落とす** —— gift演出単位でしか
        外せないと、gift 1件が消えただけで同じgift演出の他のgiftまで巻き添えになる。
        """
        by_event = {row["gift_event_id"]: row for row in old}
        seen: set = set()
        for index, gift in enumerate(gifts):
            event_id = gift.get("event_id")
            if event_id is None:
                # eventのidを持たないgiftは保存しない。画面が選ぶのは「どのeventか」だけで、
                # idの無い行は後から誰とも突き合わせられない(検証の面も書き出しも死ぬ)。
                logger.warning(
                    "event idを持たないgiftを飛ばしました（highlight=%s segment=%s）",
                    highlight_id, segment_id,
                    extra={"event": "highlight.gift_without_event",
                           "ctx": {"highlight_id": highlight_id,
                                   "segment_id": segment_id, "gift": gift}},
                )
                continue
            seen.add(event_id)
            row = by_event.get(event_id)
            show = gift.get("show") or (None, None)
            machine = (index, 1 if gift.get("inside") else 0,
                       1 if gift.get("primary") else 0,
                       None if show[0] is None else float(show[0]),
                       None if show[1] is None else float(show[1]))
            values = self._highlight_gift_event_values(gift)
            if row is None:
                self._conn.execute(
                    "INSERT INTO highlight_segment_gifts"
                    " (segment_id, highlight_id, idx, gift_event_id, gift_id, gift_name,"
                    "  diamonds, gift_count, gift_image, user_unique_id, user_nickname,"
                    "  user_id, identity_key, gift_media_time, inside, is_primary,"
                    "  show_start, show_end)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (segment_id, highlight_id, machine[0], *values, *machine[1:]),
                )
                continue
            # 人が持たせた窓はgift演出の動きに合わせて載せ直す(手直しは残すが、gift演出の外へは
            # 出さない)。窓を持たない行では両方 None のままなので、列は動かない。
            cut = self._reanchor_gift_cut(row, old_span, new_span)
            if row["manual"]:
                # 人が差し替えた行。eventから来る値は人のものを保ち、機械の列だけ更新する。
                self._conn.execute(
                    "UPDATE highlight_segment_gifts SET idx = ?, inside = ?,"
                    " is_primary = ?, show_start = ?, show_end = ?,"
                    " cut_start = ?, cut_end = ?, dropped = 0"
                    " WHERE id = ?",
                    (*machine, *cut, row["id"]))
                continue
            self._conn.execute(
                "UPDATE highlight_segment_gifts SET idx = ?, gift_id = ?, gift_name = ?,"
                " diamonds = ?, gift_count = ?, gift_image = ?, user_unique_id = ?,"
                " user_nickname = ?,"
                " user_id = ?, identity_key = ?, gift_media_time = ?, inside = ?,"
                " is_primary = ?, show_start = ?, show_end = ?,"
                " cut_start = ?, cut_end = ?, dropped = 0 WHERE id = ?",
                (machine[0], *values[1:], *machine[1:], *cut, row["id"]),
            )
        for row in old:
            if row["gift_event_id"] in seen:
                continue
            if self._gift_has_human_input(row):
                self._conn.execute(
                    "UPDATE highlight_segment_gifts SET dropped = 1, excluded = 1,"
                    " is_primary = 0, show_start = NULL, show_end = NULL"
                    " WHERE id = ?", (row["id"],))
                continue
            self._conn.execute(
                "DELETE FROM highlight_segment_gifts WHERE id = ?", (row["id"],))
        return len(seen)

    @staticmethod
    def _highlight_gift_event_values(gift: dict) -> tuple:
        """gift 1件の、eventから来る列の値。並びは :data:`_GIFT_EVENT_COLUMNS`。

        ``gift_id`` だけTEXTへ寄せる。events.gift_id はINTEGERだが、SQLiteは型を強制しない
        ので混ぜると同じgiftが 1234 と '1234' の2通りで入り、突き合わせが黙って外れる。"""
        gift_id = gift.get("gift_id")
        return (
            gift.get("event_id"),
            str(gift_id) if gift_id is not None else None,
            gift.get("gift_name"),
            gift.get("diamonds"),
            gift.get("gift_count"),
            gift.get("gift_image"),
            gift.get("user_unique_id"),
            gift.get("user_nickname"),
            gift.get("user_id"),
            gift.get("identity_key"),
            gift.get("media_time"),
        )

    @staticmethod
    def _has_human_input(row: dict) -> bool:
        """その行に人の手が入っているか。1つでも埋まっていれば、機械は消さない。"""
        return bool(row.get("approved") or row.get("edited") or row.get("excluded")
                    or (row.get("memo") or "").strip())

    @classmethod
    def _pair_highlight_segments(cls, old: list, new: list) -> dict:
        """``{新しいgift演出のindex: 古い行のid}``。highlight自身の時間軸の重なりで結ぶ。

        重なりの大きい組から1対1で確定させる(貪欲)。同じ古い行を2つの新しいgift演出が取り合う
        場面は、窓を細かくして1つのgift演出が2つに割れたときに実際に起きる —— そのとき人の確認が
        両方に付くと、確認していないgift演出が承認済みになる。"""
        scored: list = []
        for index, item in enumerate(new):
            span = (float(item["start"]), float(item["end"]))
            for row in old:
                ratio = _overlap_ratio(span, (float(row["start"]), float(row["end"])))
                if ratio >= SEGMENT_REUSE_MIN_OVERLAP:
                    scored.append((ratio, index, row["id"]))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        pairs: dict = {}
        taken: set = set()
        for _ratio, index, row_id in scored:
            if index in pairs or row_id in taken:
                continue
            pairs[index] = row_id
            taken.add(row_id)
        return pairs

    @staticmethod
    def _highlight_segment_values(new: dict, row: Optional[dict]) -> dict:
        """1つのgift演出を書くときの列の値。``row`` が在れば人の列を優先して残す。

        **giftはここに居ない。** gift演出1つが持つgiftは複数あり得るので、別表
        (``highlight_segment_gifts``)へ分けてある。ここが扱うのはgift演出自身の列だけである。

        ``edited`` の行では ``start`` / ``end`` を人のものにする。``edited`` は
        **gift演出の端を動かした**という意味だけを持つ(giftの差し替えは gift行の ``manual``)——
        1つの印に2つの意味を持たせると、端を微調整しただけで人のgift差し替えが守られ、
        再照合が機械の答えで上書きすべき行を守ってしまう(逆も起きる)。

        media_startだけは新しい照合のずれを人のstartへ載せ直す —— 録画の中の位置を決めるのは
        照合で、人が触ったのはhighlight側の端だからである。新しい照合が録画を当てられなかった
        (media_startがNone)なら、前の値をそのまま残す(推測で埋めない)。"""
        values = {
            "start": float(new["start"]),
            "end": float(new["end"]),
            "recording_id": new.get("recording_id"),
            "media_start": new.get("media_start"),
            "votes": new.get("votes"),
            "ratio": new.get("ratio"),
            "corr": new.get("corr"),
            "confidence": new.get("confidence"),
            "effect_json": json.dumps([list(span) for span in (new.get("effect") or [])],
                                      ensure_ascii=False),
            # 映像の両端は**測った側が名乗ったときだけ**書き換える。keyが無い呼び出し
            # (映像を測らない経路)で 0 を書くと、前に測ってあった値が「未測定」へ戻る。
            # 両端は1回の測定で同時に出るので、名乗りの有無は頭の側だけで見る。
            "video_start": new.get("video_start"),
            "video_end": new.get("video_end"),
            "video_probed": 1 if "video_start" in new else 0,
        }
        if row is not None and not values["video_probed"]:
            values["video_start"] = row.get("video_start")
            values["video_end"] = row.get("video_end")
            values["video_probed"] = 1 if row.get("video_probed") else 0
        if row is None or not row.get("edited"):
            return values
        shift = float(row["start"]) - values["start"]
        if values["media_start"] is not None:
            values["media_start"] = float(values["media_start"]) + shift
        else:
            values["media_start"] = row["media_start"]
        values["start"] = float(row["start"])
        values["end"] = float(row["end"])
        return values

    # ===== 人の手直し =====

    def update_highlight_segment(self, highlight_id: int, segment_id: int,
                                 fields: dict) -> Optional[dict]:
        """gift演出を1件直す。直した行を返す(該当が無ければNone)。

        **giftはここでは触らない。** gift演出1つが複数のgiftを持つので、gift 1件の付け替え・
        除外は :meth:`add_highlight_segment_gift` / :meth:`update_highlight_segment_gift`
        が受ける。混ぜると「gift演出のgift」という単数の概念が戻ってきて、実測で別人の名前が
        付いた形(高額な1件が範囲内の1件を押しのける)へ戻る。

        ``edited`` は**gift演出の端を動かした**印だけを立てる。giftの差し替えは gift行の
        ``manual`` で、2つを1つにすると端の微調整だけで人のgift差し替えが守られる(逆も
        起きる) —— 再照合が機械の答えで上書きすべき行を守ってしまう。"""
        sets: list = []
        params: list = []
        for column in ("start", "end"):
            if column in fields and fields[column] is not None:
                sets.append(f"{column} = ?")
                params.append(float(fields[column]))
        for column in ("approved", "excluded"):
            if column in fields and fields[column] is not None:
                sets.append(f"{column} = ?")
                params.append(1 if fields[column] else 0)
        if "memo" in fields and fields["memo"] is not None:
            sets.append("memo = ?")
            params.append(str(fields["memo"]))
        if any(key in fields and fields[key] is not None for key in ("start", "end")):
            sets.append("edited = 1")
        if not sets:
            return self.get_highlight_segment(highlight_id, segment_id)
        params.extend([segment_id, highlight_id])
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE highlight_segments SET {', '.join(sets)}"
                " WHERE id = ? AND highlight_id = ?", params)
            self._conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_highlight_segment(highlight_id, segment_id)

    def add_highlight_segment_gift(self, highlight_id: int, segment_id: int,
                                   gift: dict) -> Optional[dict]:
        """gift演出へgiftを1件足す(既に在れば人のものとして戻す)。gift演出を返す。

        **解決済みのgift** を受け取る。eventのidから列を引くのは :meth:`highlight_gift_event`
        だが、``gift_media_time`` だけは録画の時間軸が要るのでここでは解決できない ——
        軸を持っているのは素材を開けるroute層である。引数で受け取る形にして、埋まらないまま
        書かれる道を残さない。画面から名前や💎を直接受け取らないのは、そこがDBのeventと
        食い違う口になるためで、**人が選ぶのは「どのeventか」だけ**にする。

        ``manual`` を立てるので、次の再照合はこの行のeventを機械の答えで置き換えない。
        既に在るgiftをもう一度指したときは ``excluded`` と ``dropped`` を落とす —— 人が
        外したものを人が戻す操作であり、新しい行を積む場面ではない。
        """
        with self._lock:
            segment = self._conn.execute(
                "SELECT id FROM highlight_segments WHERE id = ? AND highlight_id = ?",
                (segment_id, highlight_id)).fetchone()
            if segment is None:
                return None
            existing = self._conn.execute(
                "SELECT id FROM highlight_segment_gifts"
                " WHERE segment_id = ? AND gift_event_id = ?",
                (segment_id, gift["gift_event_id"])).fetchone()
            if existing is not None:
                self._conn.execute(
                    "UPDATE highlight_segment_gifts SET manual = 1, excluded = 0,"
                    " dropped = 0 WHERE id = ?", (existing["id"],))
            else:
                # 並びはこのgift演出の末尾。次の照合が時刻順へ振り直す(``idx`` は機械の列)。
                nxt = self._conn.execute(
                    "SELECT COALESCE(MAX(idx), -1) + 1 AS n FROM highlight_segment_gifts"
                    " WHERE segment_id = ?", (segment_id,)).fetchone()["n"]
                self._conn.execute(
                    "INSERT INTO highlight_segment_gifts"
                    " (segment_id, highlight_id, idx, gift_event_id, gift_id, gift_name,"
                    "  diamonds, gift_count, gift_image, user_unique_id, user_nickname,"
                    "  user_id, identity_key, gift_media_time, inside, is_primary, manual)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 1)",
                    (segment_id, highlight_id, nxt,
                     *(gift[column] for column in _GIFT_EVENT_COLUMNS)),
                )
            self._conn.commit()
        return self.get_highlight_segment(highlight_id, segment_id)

    def update_highlight_segment_gift(self, highlight_id: int, segment_id: int,
                                      gift_id: int, fields: dict) -> Optional[dict]:
        """gift 1件の人の印を直す(``excluded`` / ``is_primary``)。gift演出を返す。

        ``excluded`` は**このgift 1件だけ**を出力から外す。gift演出側の ``excluded`` と別に持つ
        のは、gift演出が残ったままgift 1件だけを落とす場面があるからで、gift演出単位でしか外せないと
        同じgift演出の他のgiftまで巻き添えになる。

        ``is_primary`` はgift演出の中で1件だけ立つ。人が主を指し直したら、同じgift演出の他の行から
        必ず落とす —— 2件が主を名乗るgift演出は、読む側のどちらが勝つかで表示が変わる。
        主の付け替えも人の手直しなので ``manual`` を立てる(そうしないと次の再照合が
        機械の主で上書きする)。

        ``chosen`` は「このgiftはこの1本を使う」という人の選択で、**同じ ``gift_event_id`` の
        中で1行だけ**立つ。落とす相手がhighlightを跨ぐ点だけが主と違う —— 主はgift演出の中の
        順位、こちらはhighlightどうしの選択である。``manual`` は立てない。差し替えたのは
        「どのeventか」ではなく「どの当たりを使うか」なので、eventから来る値は次の再照合が
        今までどおり更新してよい。

        ``cut_start``/``cut_end`` は**このgiftだけの切り出し範囲**で、**必ず2つ揃えて**
        書く。片方だけ動かせる口にすると、頭を詰めた行が「窓を持っている」と判定された
        まま尻はNULL、という読み手のいない状態が作れてしまう。両方に None を渡せば窓を
        捨ててgift演出の窓へ戻る(消す操作であって、既定値へ戻す操作ではない)。

        範囲がgift演出の外へ出ていないことは**呼び出し側が確かめる**(route層)。ここで黙って
        丸めると、画面には打った値が出て出力だけ別の場所を切る形になる。"""
        sets: list = []
        params: list = []
        if fields.get("excluded") is not None:
            sets.append("excluded = ?")
            params.append(1 if fields["excluded"] else 0)
        if fields.get("is_primary") is not None:
            sets.append("is_primary = ?")
            params.append(1 if fields["is_primary"] else 0)
            sets.append("manual = 1")
        if "cut_start" in fields or "cut_end" in fields:
            cut_start = fields.get("cut_start")
            cut_end = fields.get("cut_end")
            if (cut_start is None) != (cut_end is None):
                raise ValueError("giftの区間は頭と尻を揃えて指定してください。")
            sets.append("cut_start = ?")
            params.append(None if cut_start is None else float(cut_start))
            sets.append("cut_end = ?")
            params.append(None if cut_end is None else float(cut_end))
        if fields.get("chosen") is not None:
            sets.append("chosen = ?")
            params.append(1 if fields["chosen"] else 0)
        if not sets:
            return self.get_highlight_segment(highlight_id, segment_id)
        params.extend([gift_id, segment_id, highlight_id])
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE highlight_segment_gifts SET {', '.join(sets)}"
                " WHERE id = ? AND segment_id = ? AND highlight_id = ?", params)
            if cursor.rowcount == 0:
                self._conn.commit()
                return None
            if fields.get("is_primary"):
                self._conn.execute(
                    "UPDATE highlight_segment_gifts SET is_primary = 0"
                    " WHERE segment_id = ? AND id != ?", (segment_id, gift_id))
            if fields.get("chosen"):
                # **落とす相手はhighlightを跨ぐ。** 主(``is_primary``)は1つのgift演出の中の
                # 話だが、選んだ1本は「このgiftはどのhighlightを使うか」なので、同じ
                # ``gift_event_id`` を持つ行すべてから落とさないと2本が名乗る。
                self._conn.execute(
                    "UPDATE highlight_segment_gifts SET chosen = 0"
                    " WHERE gift_event_id = (SELECT gift_event_id"
                    "   FROM highlight_segment_gifts WHERE id = ?) AND id != ?",
                    (gift_id, gift_id))
            self._conn.commit()
        return self.get_highlight_segment(highlight_id, segment_id)

    def get_highlight_segment(self, highlight_id: int, segment_id: int) -> Optional[dict]:
        """gift演出1件を、そのgiftを添えて。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM highlight_segments WHERE id = ? AND highlight_id = ?",
                (segment_id, highlight_id)).fetchone()
            if row is None:
                return None
            gifts = self._conn.execute(
                "SELECT * FROM highlight_segment_gifts WHERE segment_id = ?"
                " ORDER BY idx, id", (segment_id,)).fetchall()
        return self._highlight_segment_row(row, [dict(g) for g in gifts])

    # ===== 差し替え候補のgift event =====

    _GIFT_EVENT_SELECT = (
        "SELECT e.id AS gift_event_id, e.time AS at,"
        " CAST(e.gift_id AS TEXT) AS gift_id, e.gift_name AS gift_name,"
        " e.diamonds AS diamonds, e.gift_count AS gift_count,"
        " e.gift_image AS gift_image,"
        " e.user_unique_id AS user_unique_id, e.user_nickname AS user_nickname,"
        " e.user_id AS user_id, e.identity_key AS identity_key"
        " FROM events e"
    )

    def highlight_gift_event(self, event_id: int) -> Optional[dict]:
        """gift event 1件を、gift演出のgift列と同じ形で引く。gift以外のeventはNoneを返す。

        ``gift_media_time`` はここでは埋まらない(録画のmedia軸へ載せるには素材が要る)。
        埋めるのは呼び出し側(route)で、時間軸の解決を持っている層である。"""
        with self._lock:
            row = self._conn.execute(
                self._GIFT_EVENT_SELECT + " WHERE e.id = ? AND e.kind = 'gift'",
                (event_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["gift_media_time"] = None
        return item

    def highlight_gift_events(self, session_id: int, start: float, end: float) -> list:
        """その配信のgift eventを壁時計の窓で。差し替え候補の母集団になる。

        窓は**録画自身の窓**で渡すこと。1つのsessionは録画を複数本束ねる(実測11本)ので、
        session全体から採ると別の録画のgiftが候補に混ざる(doc/HIGHLIGHT_MATCH.md)。"""
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                self._GIFT_EVENT_SELECT +
                " WHERE e.session_id = ? AND e.kind = 'gift'"
                " AND e.time >= ? AND e.time <= ? ORDER BY e.time",
                (session_id, start, end)).fetchall()
        return [dict(row) for row in rows]

    # ===== 週ぜんたいの俯瞰(検証) =====

    def highlight_coverage(self, unique_id: str, week: str, min_diamonds: int) -> dict:
        """その週のgiftを1件ずつ並べ、highlightのどこに現れたかを添えて返す。

        **主語はgiftであってhighlightではない。** 1本ずつの照合結果(:meth:`highlight_segments`)
        は「このhighlightは何から出来ているか」しか言えず、**TikTokが選ばなかったgift**が
        そこには現れない。突き合わせが取りこぼしたのか、そもそもhighlightに無いのかを人が
        確かめられるのは、週のgiftを全部並べて「1本も無い」行を見せる面だけである。

        ``hits`` が空の行は**必ず残す**。高額なのに1本も出てこないgiftこそがこの面の読み
        どころで、0件を隠せば「取りこぼしが無いように見える一覧」が出来上がる。逆に
        ``hits`` は複数にもなる(同じgiftが複数のhighlightへ入る)ので、listのまま返す ――
        件数を1へ丸めると重複排除が効いているかを確かめられない。

        突き合わせは **``gift_event_id`` の一致**だけで行う。時刻の近さで結んではいけない ――
        照合が正しいかを検証するための面が、照合とは別の(しかも緩い)規則で答えを作って
        しまうと、両方が間違っているときに一致して見える。

        週の窓と対象gifterは :meth:`streamer_mention_week` と同じ経路を通る
        (``_ranking_periods`` / ``_period_bounds`` / ``_gift_window_ranking``)。配信者画面と
        数が食い違えば、人はまず「どちらが正しいのか」で止まる。

        ``min_diamonds`` は **gift 1個あたりの単価**の下限で、呼び出し側が解決した値を
        受け取る(既定は設定の演出gift下限98💎)。**合計では判定しない** —— 30💎のgiftを
        9個まとめて投げた1 eventは合計270💎だが、画面に出るのは小さなbannerが9回で、
        切り抜きに載せる場面ではない(:func:`gift_unit_diamonds`)。落とした件数は
        ``totals.combo_below_min`` が名乗る。数字をここに書かないのは、設定画面で変えた値が
        素通りするためである。``0`` は「下限なし = 全gift」で、未指定とは別の意味を持つ。
        対象gifterの下限(週合計 :data:`MENTION_POST_MIN`)は指定させない —— メンション一覧が
        持つ規則で、画面からもここからも動かさない。**この面に並ぶのは対象gifterのgiftだけ**
        である(利用者の指定) —— 検証するのは「fileになる週」の中身なので、fileが作られない
        人のgiftが混ざると、確かめる相手が週の全gifterへ膨らむ。落とした件数は
        ``totals.offtarget`` が名乗る(黙って消すと数が合わない)。並んだ行はすべて
        ``target`` が真だが、fieldは残す —— 画面がこの規則を前提に描いているかを、
        応答だけで確かめられなくなる。

        ``totals`` の ``highlights`` / ``segments`` / ``unidentified`` は**その週の
        highlight**の内訳である。highlightを週へ割り当てる鍵はgiftで、1本のhighlightは
        LIVE replay 1本 = 配信1回から作られる(doc/HIGHLIGHT_MATCH.md)ので週は1つに定まる。
        まだ照合していないhighlightはどの週へも入らない —— 置き場に在るだけの素材を
        「この週の物」と名乗る根拠が無いためで、推測で埋めない。
        """
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
        # 週ぜんたいのgift eventを触るので、書き込み接続で流すとcollectorのevent書き出しが
        # その間待たされる(streamer_mention_week と同じ理由)。
        conn = self._read_connection()
        ph = ",".join("?" * len(handles))
        floor = int(min_diamonds)
        # 「そのgiftは演出を持つ階層か」の線。いまはcoinが代理指標で、gift_id別の実測へ
        # 移すのが宿題である(doc/HIGHLIGHT_MATCH.md)。``min_diamonds`` とは別に返す ——
        # 下限を0にして全giftを並べたときに、行ごとの判断がこの線を失ってはいけない。
        effect_floor = config.get_highlight_effect_coin_floor()
        empty_totals = {"gifts": 0, "matched": 0, "hits": 0, "diamonds": 0,
                        "matched_diamonds": 0, "gifters": 0, "target_gifters": 0,
                        "offtarget": 0,
                        "highlights": 0, "segments": 0, "unidentified": 0,
                        "effect_expected": 0, "effect_expected_matched": 0,
                        "combo_below_min": 0}
        empty = {"streamer": unique_id, "week": "", "prev_week": "", "next_week": "",
                 "start_label": "", "end_label": "", "post_label": "",
                 "post_min": MENTION_POST_MIN, "min_diamonds": floor,
                 "effect_floor": effect_floor,
                 "long_segment_seconds": highlight_match.LONG_SEGMENT_SECONDS,
                 "score_pass": int(highlight_match.SCORE_PASS),
                 "weeks": [], "items": [], "totals": empty_totals, "dropped_weeks": 0}
        keys, week_totals, dropped = self._ranking_periods(
            conn, unique_id, handles, ph, WEEK_SATURDAY)
        if not keys:
            return empty

        selected = week if week in set(keys) else keys[-1]
        index = keys.index(selected)
        start, end = _period_bounds(selected, WEEK_SATURDAY)
        everyone = self._gift_window_ranking(conn, handles, ph, start, end)
        # 身元は一覧と同じ解決(users表を主、未記入だけevent記録値で補う)を使い回す。
        # gift 1件ずつのevent記録値から名前を作ると、同じ人が行ごとに別の名前で並ぶ。
        people = {row["identity_key"]: row for row in everyone if row["identity_key"]}
        targets = {key for key, row in people.items()
                   if row["diamonds"] >= MENTION_POST_MIN}

        rows = conn.execute(
            "SELECT e.id AS event_id, e.time AS time, e.identity_key AS identity_key,"
            " e.gift_id AS gift_id, e.gift_name AS gift_name,"
            " e.gift_count AS gift_count, e.diamonds AS diamonds,"
            " e.gift_image AS gift_image"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
            " AND e.time >= ? AND e.time < ?"
            " ORDER BY e.time",
            (*handles, start, end),
        ).fetchall()
        # 下限で切る**前**の全件。highlightをこの週へ割り当てる鍵で、下限は「並べるgift」を
        # 決めるだけである(98💎未満のgiftで当たったhighlightも、この週の物には違いない)。
        week_events = {row["event_id"] for row in rows}

        hits, week_highlights, week_segments, unidentified = self._highlight_hit_index(
            conn, handles, ph, week_events)
        # 人が付けた「この行は見た」の印。**表ぜんたいを1回で読む** —— 週のevent idを
        # IN句へ並べると数百件のplaceholderになるうえ、絞り込みを変えるたびに形の違う
        # queryが増える。この表に在るのは人が押した数だけである。
        checked = {row["gift_event_id"] for row in conn.execute(
            "SELECT gift_event_id FROM highlight_gift_checks")}

        items = []
        combo_below = 0
        offtarget = 0
        for row in rows:
            diamonds = int(row["diamonds"] or 0)
            gift_count = int(row["gift_count"] or 1)
            # 下限は**1個あたりの単価**で判定する(:func:`gift_unit_diamonds`)。合計で
            # 判定すると「30💎を9個(270💎)」がここへ並び、演出の出ない場面を人が
            # 「出ていない = 取りこぼし」として追いかけることになる。
            unit = gift_unit_diamonds(diamonds, gift_count)
            if unit < floor:
                if gift_count > 1 and diamonds >= floor:
                    # まとめ投げの合計だけが下限を越えた行。**黙って消すと数が合わない**
                    # ので件数だけ名乗る(行は出さない)。
                    combo_below += 1
                continue
            key = row["identity_key"] or ""
            # 週合計が下限に届かない人のgiftは並べない(利用者の指定)。この面で検証するのは
            # 「fileになる週」の中身で、fileが作られない人のgiftは確かめる相手ではない ——
            # 混ぜると、週の全gifterぶんの行を人が1件ずつ読み下すことになる。**黙って消さ
            # ない**ので、下限を越えていたのに外れた件数は ``totals.offtarget`` が名乗る。
            if key not in targets:
                offtarget += 1
                continue
            person = people.get(key) or {}
            items.append({
                "event_id": row["event_id"],
                "time": row["time"],
                "label": datetime.fromtimestamp(row["time"]).strftime("%m/%d %H:%M"),
                "gift_id": int(row["gift_id"] or 0),
                "gift_name": row["gift_name"] or "",
                "gift_count": gift_count,
                "diamonds": diamonds,
                # まとめ投げを人が読み解けるように、単価も出す。合計しか出さないと
                # 「270💎なのに演出が出ていない」が謎のまま残る。
                "unit_diamonds": unit,
                # 生のCDN URLのまま返す。proxy URLへ解決するのはroute層で、そこが
                # gift iconのpoolを持っている(``runtime.gift_icon_url``)。
                "gift_image": row["gift_image"] or "",
                "identity_key": key,
                "user_nickname": person.get("nickname", ""),
                "user_unique_id": person.get("unique_id", ""),
                "week_diamonds": person.get("diamonds", 0),
                # 週合計が下限に届いた人か。届かない人の行も残して印だけ付ける ——
                # 落とすと「この面に出ていないgift」が2種類(下限未満と対象外)出来て、
                # 出てこない理由を人が切り分けられなくなる。
                "target": key in targets,
                # そのgiftが演出を持つ階層か。**coinを代理指標にした推定であって実測では
                # ない。** 出てこないgiftを「演出が無いので採られなくて当然」と「演出が
                # あるのに採られていない = 要調査」に切り分けるための線で、後者が人の
                # 一番の関心事である。gift_id別の実測へ移すのが宿題(doc/HIGHLIGHT_MATCH.md)。
                "effect_expected": unit >= effect_floor,
                # 人が「この行は見た」と付けた印。**当たりの有無とは独立**である ——
                # 出ていない行こそ人が判ずる相手なので、当たりが無い行にも付く。
                "checked": row["event_id"] in checked,
                "hits": hits.get(row["event_id"], []),
            })
        # 高額な順に並べる。この面の読みどころは「高額なのに1本も無い行」で、額の順に
        # 並んでいれば上から数行で当たり外れの傾向が読める。同額は時刻順。
        items.sort(key=lambda item: (-item["diamonds"], item["time"]))

        matched = [item for item in items if item["hits"]]
        return {
            "streamer": unique_id,
            "week": selected,
            "prev_week": keys[index - 1] if index > 0 else "",
            "next_week": keys[index + 1] if index + 1 < len(keys) else "",
            "start_label": _week_label(start),
            "end_label": _week_label(end),
            "post_label": _post_range_label(start, end),
            "post_min": MENTION_POST_MIN,
            "min_diamonds": floor,
            "effect_floor": effect_floor,
            # gift演出が長すぎると言う線(秒)と、点の合否の線。**数字を画面に書かない** ——
            # 書くと、照合側で線を動かした日に画面だけが古い線で警告を出す
            # (``min_diamonds`` と同じ規則)。
            "long_segment_seconds": highlight_match.LONG_SEGMENT_SECONDS,
            "score_pass": int(highlight_match.SCORE_PASS),
            "weeks": [
                {"key": k, "label": _week_label(_period_bounds(k, WEEK_SATURDAY)[0]),
                 "diamonds": week_totals.get(k, (0, 0))[0],
                 "gifts": week_totals.get(k, (0, 0))[1]}
                for k in keys
            ],
            "totals": {
                "gifts": len(items),
                "matched": len(matched),
                # 行の数ではなく当たりの数。同じgiftが複数のhighlightに入ると差が出る。
                "hits": sum(len(item["hits"]) for item in items),
                "diamonds": sum(item["diamonds"] for item in items),
                "matched_diamonds": sum(item["diamonds"] for item in matched),
                # **その週にgiftを投げた人の数**であって、表に並んだ人の数ではない ——
                # 表は対象gifterだけなので、items から数えると target_gifters と必ず
                # 同じ数になり、「何人のうち何人がfileになるのか」が読めなくなる。
                "gifters": len(people),
                "target_gifters": len(targets),
                "highlights": len(week_highlights),
                "segments": len(week_segments),
                # giftの付いていないgift演出。giftのアニメの音が配信の音を覆うと票が立たない区間が
                # 出る(実測で60.8秒のうち5.7秒)ので、0にはならないのが普通である。
                "unidentified": unidentified,
                # 演出を持つ階層(coin代理)のgiftと、そのうち当たった数。この2つの差が
                # 「演出があるのに1本も出てこないgift」の件数で、人が最初に見る数字である。
                "effect_expected": sum(1 for item in items if item["effect_expected"]),
                "effect_expected_matched": sum(
                    1 for item in matched if item["effect_expected"]),
                # 人が確認した行の数。**並べた行(items)が母数**で、確認の印そのものの
                # 総数ではない —— 下限で落ちた行や別の週の行まで数えると、この週を
                # どこまで見たのかが読めなくなる。
                "checked": sum(1 for item in items if item["checked"]),
                # まとめ投げの合計だけが下限を越えて、単価では届かなかったgift。
                "combo_below_min": combo_below,
                # 単価の下限は越えていたが、投げた人の週合計が下限に届かず表から外れた
                # gift。0件を隠さないのがこの面の約束なので、消した数だけは名乗る。
                "offtarget": offtarget,
            },
            "items": items,
            "dropped_weeks": dropped,
        }

    def set_highlight_gift_checks(self, gift_event_ids, checked: bool) -> list:
        """検証の面の「確認済み」の印を付ける/外す。**まとめて1回で書く。**

        **印はgift event 1件ごとで、gift演出にもgift行にも載せない。** highlightに1本も
        出ていないgift —— この面で人が一番確かめる相手 —— はgift演出もgift行も持たないため、
        そちら側に持たせると印を残せる行と残せない行ができる。

        複数を受けるのは、表の1行が複数のeventを畳むためである(同じ人が同じgiftを同じ
        gift演出へ連投した数件は1行になる)。1件ずつ往復させると**途中で失敗した行が
        「半分だけ確認済み」**という、checkboxで表せない状態になる。ここは1 transactionで
        全部書くか1件も書かないかにする。

        存在しないevent idも受け付ける。**押せるのは表に並んでいる行だけ**で、その行は
        こちらが返したeventそのものである。ここでeventの実在を引き直すと、印を付ける
        たびにeventsを引くことになる(表は数百行ある)。

        書いたevent idを返す(重複は畳む)。
        """
        ids = sorted({int(one) for one in gift_event_ids})
        if not ids:
            return []
        now = time.time()
        with self._lock:
            if checked:
                # 付け直しでは時刻だけが進む。**行を二重に積まない** —— gift_event_idが
                # 主keyなので、消してから入れ直す形にはしない。
                self._conn.executemany(
                    "INSERT INTO highlight_gift_checks(gift_event_id, checked_at)"
                    " VALUES(?, ?) ON CONFLICT(gift_event_id)"
                    " DO UPDATE SET checked_at = excluded.checked_at",
                    [(one, now) for one in ids])
            else:
                self._conn.executemany(
                    "DELETE FROM highlight_gift_checks WHERE gift_event_id = ?",
                    [(one,) for one in ids])
            self._conn.commit()
        return ids

    def highlight_week_gifts(self, unique_id: str, week: str,
                             min_diamonds: int) -> dict:
        """その週の**載るはずのgift全部**を、highlightに出ているかの印を添えて返す。

        書き出しの下見(``plan_exports``)が「出ていないgift」を名乗るための母集団である。
        照合結果だけを並べると、**そこに無いgiftは画面から消える** —— TikTokが選ばなかった
        のか、こちらの照合が取りこぼしたのか、そもそも投げられていないのかを人が区別
        できない。出来上がるfileの中身を確かめる面では、無い物こそが読みどころである。

        並べるのは :meth:`highlight_coverage` と**同じ規則**で選んだgiftである(週の窓・
        単価の下限)。2つの面で「載るはずのgift」が食い違うと、人はまずどちらが正しいのかで
        止まる。対象gifter(週合計)では絞らない —— 誰のfileを作るかを決めるのは
        ``plan_exports`` 側で、ここは母集団を渡すだけにする。

        ``highlight_ids`` はそのgiftが出ているhighlightのid(``dropped`` の行は読まない)。
        **選んだhighlightで絞らない** —— 「別のhighlightには在るが今回は選んでいない」と
        「どのhighlightにも無い」は人にとって別の話で、絞ると後者へ潰れる。
        """
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
        conn = self._read_connection()
        ph = ",".join("?" * len(handles))
        floor = int(min_diamonds)
        keys, _week_totals, _dropped = self._ranking_periods(
            conn, unique_id, handles, ph, WEEK_SATURDAY)
        if not keys:
            return {"week": "", "start": 0.0, "end": 0.0, "min_diamonds": floor,
                    "gifts": []}
        selected = week if week in set(keys) else keys[-1]
        start, end = _period_bounds(selected, WEEK_SATURDAY)
        rows = conn.execute(
            "SELECT e.id AS event_id, e.time AS time, e.identity_key AS identity_key,"
            " e.gift_id AS gift_id, e.gift_name AS gift_name,"
            " e.gift_count AS gift_count, e.diamonds AS diamonds,"
            " e.gift_image AS gift_image,"
            " e.user_nickname AS user_nickname, e.user_unique_id AS user_unique_id"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
            " AND e.time >= ? AND e.time < ?"
            " ORDER BY e.time",
            (*handles, start, end),
        ).fetchall()
        # そのgiftが出ているhighlight。**週で絞らない**(週の外のhighlightに入っていた事実も
        # 人が見たい情報である)のは ``_highlight_hit_index`` と同じ規則。
        placed: dict = {}
        for row in conn.execute(
            "SELECT g.gift_event_id AS gift_event_id, g.highlight_id AS highlight_id"
            " FROM highlight_segment_gifts g"
            " JOIN highlight_videos h ON h.id = g.highlight_id"
            f" WHERE h.unique_id IN ({ph}) AND g.dropped = 0",
            tuple(handles),
        ):
            placed.setdefault(row["gift_event_id"], []).append(row["highlight_id"])
        gifts = []
        for row in rows:
            diamonds = int(row["diamonds"] or 0)
            gift_count = int(row["gift_count"] or 1)
            unit = gift_unit_diamonds(diamonds, gift_count)
            if unit < floor:
                continue
            gifts.append({
                "gift_event_id": row["event_id"],
                "time": row["time"],
                # 週をまたぐ一覧なので日付まで出す(``highlight_coverage`` と同じ形)。
                "label": datetime.fromtimestamp(row["time"]).strftime("%m/%d %H:%M"),
                "identity_key": row["identity_key"] or "",
                "gift_id": row["gift_id"],
                "gift_name": row["gift_name"] or "",
                "gift_count": gift_count,
                "diamonds": diamonds,
                "unit_diamonds": unit,
                # 生のCDN URLのまま返す。proxy URLへ解決するのはroute層である
                # (``highlight_coverage`` と同じ規則)。
                "gift_image": row["gift_image"] or "",
                "user_nickname": row["user_nickname"] or "",
                "user_unique_id": row["user_unique_id"] or "",
                "highlight_ids": sorted(set(placed.get(row["event_id"], []))),
            })
        return {"week": selected, "start": start, "end": end,
                "min_diamonds": floor, "gifts": gifts}

    def _highlight_hit_index(self, conn, handles: list, ph: str,
                             week_events: set) -> tuple:
        """``({event_id: hits}, その週のhighlight id, その週のgift演出, gift無しのgift演出数)``。

        gift演出をtableから読む口をここ1つにしてある。1 segmentが複数のgiftを持つ形へ表が
        変わっても、直すのはこのmethodだけで済む。

        ``dropped`` の行は読まない。前回の照合には在ったが今回は出なくなったgift演出で、
        **今の照合が指す場所を持たない** —— 当たりとして並べると、既に否定された対応が
        検証の面で生き続ける。
        """
        rows = conn.execute(
            "SELECT s.id AS segment_id, s.highlight_id AS highlight_id, s.idx AS idx,"
            " s.start AS start, s.end AS end, s.recording_id AS recording_id,"
            " s.media_start AS media_start, s.votes AS votes,"
            " s.ratio AS ratio, s.corr AS corr, s.confidence AS confidence,"
            " s.effect_json AS effect_json, s.approved AS approved,"
            " s.video_start AS video_start, s.video_end AS video_end,"
            " s.video_probed AS video_probed,"
            " s.edited AS edited, s.excluded AS excluded, h.filename AS filename,"
            " g.id AS gift_row_id, g.gift_event_id AS gift_event_id,"
            " g.gift_media_time AS gift_media_time, g.inside AS inside,"
            " g.is_primary AS is_primary,"
            " g.manual AS manual, g.excluded AS gift_excluded, g.chosen AS chosen,"
            " g.cut_start AS cut_start, g.cut_end AS cut_end,"
            " g.show_start AS show_start, g.show_end AS show_end,"
            # そのgift演出に何人が載っているか。**人数であって件数ではない** —— 連投は同じ人が
            # 何件も出すので、件数で見ると1人しか居ないgift演出が「相席」に見える。区間はgift
            # ごとに持てるので詰めても相手は動かないが、gift演出ごと外すと相手の見せ場も消える。
            " (SELECT COUNT(DISTINCT g2.identity_key) FROM highlight_segment_gifts g2"
            "   WHERE g2.segment_id = s.id AND g2.dropped = 0) AS segment_gifters"
            " FROM highlight_segments s"
            " JOIN highlight_videos h ON h.id = s.highlight_id"
            # giftを持たないgift演出も残す。``unidentified`` はその数であり、LEFT JOINを
            # INNER にすると「giftの付いていないgift演出」が一覧からも数からも消える。
            " LEFT JOIN highlight_segment_gifts g"
            "   ON g.segment_id = s.id AND g.dropped = 0"
            f" WHERE h.unique_id IN ({ph}) AND s.dropped = 0"
            " ORDER BY s.highlight_id, s.idx, s.id, g.idx, g.id",
            tuple(handles),
        ).fetchall()
        # 当たりは**週で絞らずに**索引する。週の外のhighlightに入っていた場合でも、それは
        # 隠すべきことではなく人が見たい事実である(週の割り当てを疑う手掛かりになる)。
        hits: dict = {}
        for row in rows:
            event_id = row["gift_event_id"]
            if event_id is None:
                continue
            hits.setdefault(event_id, []).append(self._coverage_hit(row))
        # 同席しただけの当たり(``is_primary`` が偽)は後ろへ回す。**先頭の当たりがその行の
        # 代表**で、画面は区間・確信度・NGの対象をそこから採る。SQLの並び(highlight_id順)
        # のままでは代表が偶然で決まり、実測では1件のgift(6,000💎)が3本へ入って先頭だけが
        # 同席、残る2本がそのgifter自身の見せ場という行が「同席しただけ」として沈んでいた。
        # 手で結んだ当たり(``manual``)は人が選んだ対応なので代表の側に置く。sortは安定
        # なので、同じ側に居る当たりどうしの並び(highlight_id, idx)は崩れない。
        #
        # **人が選んだ1本(``chosen``)はそのどれよりも先**である。同席かどうかは「そのgift演出で
        # 一番よく映っている人は誰か」という機械の代用で、人が実物を観て選んだ答えがある
        # なら代用は要らない —— 実測(Whale diving 2,150💎)では3本すべてで同席と判定され、
        # 本人の演出が映っている11.1秒の1本も後ろへ回されていた。
        for hit_list in hits.values():
            hit_list.sort(key=lambda hit: (0 if hit["chosen"] else 1,
                                           0 if (hit["manual"] or hit["is_primary"])
                                           else 1))
        week_highlights = {row["highlight_id"] for row in rows
                           if row["gift_event_id"] in week_events}
        # gift演出は行ではなく**gift演出id**で数える。giftを複数持つとLEFT JOINで複数行になる
        # ので、行数をgift演出数として数えると持ちgiftの多いgift演出ほど水増しされる。
        week_segments = {row["segment_id"] for row in rows
                         if row["highlight_id"] in week_highlights}
        unidentified = len({row["segment_id"] for row in rows
                            if row["highlight_id"] in week_highlights
                            and row["gift_event_id"] is None})
        return hits, week_highlights, week_segments, unidentified

    @staticmethod
    def _coverage_hit(row) -> dict:
        """gift演出1行を「そのgiftがhighlightのどこに出たか」の形へ。

        ``at`` は **giftそのもの**がhighlight自身の時間軸で何秒目かで、画面はここへ飛び、
        代表frameもここで採る。``gift演出の頭 + (giftのmedia秒 - gift演出のmedia秒)`` である ——
        **gift演出の頭(``segment_start``)ではない。** giftはgift演出の頭に在るとは限らず(実測で
        7312.50のgift演出に対しgiftは7313.67、1.2秒後ろ)、gift演出の頭を返すと飛び先が毎回gift演出の
        頭になり、しかも「だいたい合っている」ので誰も気付かない。

        録画が当たっていないgift演出(``media_start`` が無い)では ``at`` は **None**。gift演出の頭で
        代用すると、位置が判っているように見える数字が出る。画面は ``segment_start`` へ
        落として飛べばよいが、**その選択は画面が意識してやること**である。

        差ではなく ``gift_media_time``(絶対秒)から毎回引き直しているのは、人がgift演出の端を
        動かしてもgiftは録画の中で動いていないからである。差で持つと、端を1秒ずらした瞬間に
        giftの位置まで1秒動く。
        """
        effect = json.loads(row["effect_json"] or "[]")
        start = float(row["start"])
        at = gift_position(start, row["media_start"], row["gift_media_time"])
        video_start = _cut_value(row, "video_start")
        video_end = _cut_value(row, "video_end")
        cut_start, cut_end = gift_cut(start, float(row["end"]), row, video_start,
                                      video_end)
        return {
            "highlight_id": row["highlight_id"],
            "filename": row["filename"],
            "segment_id": row["segment_id"],
            "idx": row["idx"],
            "at": at,
            "segment_start": round(start, 3),
            "segment_end": round(float(row["end"]), 3),
            # **このgiftを実際に切り出す範囲。** gift演出の窓と別に名乗る —— 1つのgift演出に別人の
            # giftが複数入るので(実測で6.0秒に3人)、gift演出の窓を「この行の区間」として出すと、
            # 1人の行で詰めた値が他の2人の行にも同じ数字で並ぶ。
            "cut_start": round(cut_start, 3),
            "cut_end": round(cut_end, 3),
            "cut_own": (_cut_value(row, "cut_start") is not None
                        and _cut_value(row, "cut_end") is not None),
            # 映像が切り替わり終わる秒と、それを測ったかどうか。**既定の頭がどこから来た
            # のか**を画面が名乗れないと、人は「なぜgift演出の頭とずれているのか」を追えない。
            "video_start": (None if video_start is None
                            else round(float(video_start), 3)),
            "video_end": (None if video_end is None
                          else round(float(video_end), 3)),
            "video_probed": bool(_cut_value(row, "video_probed")),
            # **そのgiftの見せ場**。1つのgift演出に順番待ちで並んだ演出のうち、このgiftのものが
            # 映っている区間で、既定の窓はここから来る。NULLは「そのgift演出を割っていない」で、
            # gift演出の窓と同じという意味ではない —— 画面は「区間の外はどこまで動かせるか」を
            # これで決める(割った行は自分の見せ場の外へは出せない)。
            "show_start": (None if _cut_value(row, "show_start") is None
                           else round(float(_cut_value(row, "show_start")), 3)),
            "show_end": (None if _cut_value(row, "show_end") is None
                         else round(float(_cut_value(row, "show_end")), 3)),
            # そのgift演出に載っているgifterの人数。1より大きい行は「相席」で、gift演出ごと外すと
            # 別の人の見せ場まで消える(画面がそれを押す前に名乗るための値)。
            "segment_gifters": _cut_value(row, "segment_gifters"),
            "recording_id": row["recording_id"],
            "media_start": row["media_start"],
            "votes": row["votes"],
            "ratio": row["ratio"],
            "corr": row["corr"],
            "confidence": row["confidence"],
            # gift演出の点(0〜100)。**「高/低」の2択では人が動けなかった**(利用者の指摘) ——
            # 低いgift演出が10件並んだとき、どれから観ればよいのかを語は答えない。点は
            # :func:`highlight_match.score_of` の1箇所で決まり、50が合否の線である。
            **HighlightsMixin._score_fields(row),
            "effect": effect,
            # 生の演出区間(gift演出の属性)。**「演出があるか」の真偽値は返さない** ——
            # 差分による検出は実測で両方向に無力で(7本のgift 47件で当たり0件)、真偽値を
            # 返せばいずれ誰かが信じる。区間そのものは診断用に残し、演出が映っているかは
            # 代表frameの2枚並べで人が見る。
            "gift_row_id": row["gift_row_id"],
            # segmentの範囲の中に居るか。Falseは gift_lead で手前へ伸ばした窓に入っただけで、
            # **highlightにはその手前の映像が無い**(別の時刻のgift演出が繋がっているだけ)。
            "inside": bool(row["inside"]),
            "is_primary": bool(row["is_primary"]),
            "manual": bool(row["manual"]),
            # 人がこのgiftの当たりとして選んだ1本か。同じgiftは複数のhighlightに入るので、
            # **どれを使うかは機械の順位ではなく人の選択が先**である(書き出しの重複排除も
            # この印を最優先に読む)。
            "chosen": bool(row["chosen"]),
            "approved": bool(row["approved"]),
            "edited": bool(row["edited"]),
            # gift演出ごと外したのか、このgift 1件だけを外したのかを分けて名乗る。
            "excluded": bool(row["excluded"]) or bool(row["gift_excluded"]),
            "segment_excluded": bool(row["excluded"]),
            "gift_excluded": bool(row["gift_excluded"]),
        }
