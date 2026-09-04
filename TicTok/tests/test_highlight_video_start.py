"""切り出しの窓を「映像が綺麗な区間」へ合わせる経路のtest。

なぜ要るのか
------------
gift演出の境目(``highlight_segments.start``)は**音**で決めている。TikTokのmontageは音を一瞬で
切り替えながら、映像には切り替わりの演出を掛ける ―― 実測(実物7本・境目29箇所、2026-09-02)
で映像が落ち着くのは音の境目より**中央値0.60秒あと**、範囲は0.00〜1.47秒である。目でも
確認済みで、``…savog65hl0000002.mp4`` の14.512秒(Guardian's Pledge 4999💎)は +0.45秒まで
前の場面が縮みながら退き、板が組み上がるのは +0.9〜1.05秒である。

**演出は境目を跨ぐ。** だから窓は両端とも動く:

* 頭(``video_start``)を境目のままにすると、全部の切り出しの頭に前のgiftの場面が残る。
* 尻(``video_end``)を境目のままにすると、切り出しの終わりに**次のgiftが映る**。同じfileの
  43.750秒の境目では、次の場面が 42.817秒から現れて 43.283秒には全画面になっており、窓は
  最後の0.93秒が次のgiftだった —— 通しで観ると「2人目のgiftの終わりに3人目のgiftが少し
  映る」形になり、誰のgiftなのかを誤認させる。

ずれは一定ではない(同じfileの中で +0.07 と +1.47 が同居する)ので、定数を引いてはいけない
―― 境目ごとに測る。

確かめること
------------
1. 検出そのもの(合成した切り替わりを実際に測れるか)。両端とも。
2. ``video_start``/``video_end`` が既定の窓になること。**人が詰めた窓には効かない**こと
3. 測っていないことと、測って決まらなかったことが区別されること
4. 再照合で、測った値が黙って消えないこと
5. 書き出しがその窓で切ること・古い下見が検証で止まること
6. 照合をやり直さずに測り直す道(``update_highlight_switches``)
"""

import shutil
import subprocess

import pytest

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, make_srv_recording, server,
)
from tests.test_highlight_api import (  # noqa: F401  (fixtureとして使う)
    clean_highlights, highlight_roots, matched_highlight,
    _fake_result, _gift, _segment,
)

from tests.test_highlight_coverage import (  # noqa: F401  (fixtureとして使う)
    week, _highlight as _cov_highlight, _segment as _cov_segment,
)

from tictok.media import highlight_export, highlight_switch
from tictok.store.highlights import default_cut, gift_cut


def _cov_hit(result: dict, event_id: int) -> dict:
    """俯瞰の応答から、そのgiftの当たり1件を取り出す。"""
    item = next(row for row in result["items"] if row["event_id"] == event_id)
    assert item["hits"], "当たりが1件も無い"
    return item["hits"][0]


def _with_video(segment: dict, video_start, video_end=None):
    """照合結果のgift演出へ「測った映像の両端」を載せる。

    keyが在ること自体が「測った」の合図なので(``_highlight_segment_values``)、None を
    載せる形も要る —— 測って決まらなかったことを保存する経路である。"""
    return {**segment, "video_start": video_start, "video_end": video_end}


def _segment_of(client, highlight_id, index=0):
    return client.get(f"/api/highlights/{highlight_id}").json()["segments"][index]


# ===== 検出そのもの =====

@pytest.mark.requires_ffmpeg
@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="needs a real ffmpeg/ffprobe on PATH")
def test_合成した切り替わりの終わりを測れる(tmp_path):
    """1.7秒から0.5秒かけて滑る切り替わりを作り、終わり(2.2秒)が出ることを見る。

    実物の演出も「前の場面が縮んで退く・板が滑る」形で、音はその頭で切り替わっている。
    ここで確かめるのは**遅れの向きと大きさ**であって、frame単位の一致ではない。"""
    src = tmp_path / "switch.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=2.2",
         "-f", "lavfi", "-i", "smptebars=s=180x320:r=30:d=3",
         "-filter_complex",
         "[0][1]xfade=transition=slideleft:duration=0.5:offset=1.7",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(src)],
        check=True)
    at = highlight_switch.switch_end(src, 1.7, lead=0.5, tail=2.4)
    assert at is not None
    # 演出の終わり(2.2秒)の前後2frame以内。**音の境目(1.7)より必ず後ろ**である。
    assert 1.7 < at
    assert abs(at - 2.2) <= 0.10

    # 並びで呼ぶと、境目1つの測定が**手前のgift演出の尻と後ろのgift演出の頭の両方**になる。
    # fileの両端(先頭の頭・末尾の尻)は測らずに端をそのまま返す ―― 退場していく前の場面も
    # 入ってくる次の場面も無く、切る場所を動かす理由が無い。
    spans = highlight_switch.video_spans(src, [(0.0, 1.7), (1.7, 4.7)])
    assert [span[0] for span in spans] == [0.0, at]
    assert spans[1][1] == 4.7
    # 手前のgift演出の尻は、次の場面が現れ始める秒。**演出の頭(1.7)以下**で、境目は越えない。
    began = spans[0][1]
    assert began is not None
    assert began <= 1.7


@pytest.mark.requires_ffmpeg
@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="needs a real ffmpeg/ffprobe on PATH")
def test_切り替わりの無い境目では境目そのものを返す(tmp_path):
    """演出が無ければ頭は動かさない。**0.0秒ずらす**のと「測れなかった」は別である。"""
    src = tmp_path / "flat.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "smptebars=s=180x320:r=30:d=5",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(src)],
        check=True)
    assert highlight_switch.switch_end(src, 2.0, lead=0.5, tail=2.2) == 2.0


@pytest.mark.requires_ffmpeg
@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="needs a real ffmpeg/ffprobe on PATH")
def test_短すぎるgift演出は測れなかったとして返す(tmp_path):
    """下地を採る余裕が取れないgift演出では**答えを作らない**。それらしい秒を返すと、
    画面はそれを測った値として名乗る。"""
    src = tmp_path / "flat.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "smptebars=s=180x320:r=30:d=5",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(src)],
        check=True)
    assert highlight_switch.switch_end(src, 2.0, lead=0.5, tail=0.5) is None


def test_frameが読めなければ測れなかったとして残りを続ける(tmp_path):
    """1つの境目の失敗を全体の失敗へ広げない。境目ごとに独立した測定である。"""
    missing = tmp_path / "nope.mp4"
    assert highlight_switch.video_spans(missing, [(0.0, 3.0), (3.0, 9.0)]) == [
        (0.0, None), (None, 9.0)]


# ===== 既定の窓 =====

def test_既定の窓は映像の綺麗な区間になる():
    """両端とも動く。演出は音の境目を跨ぐので、尻をgift演出の終わりに置くと次のgiftが映る。"""
    assert default_cut(10.0, 16.0, 10.6, 15.2) == (10.6, 15.2)
    assert default_cut(10.0, 16.0, 10.6) == (10.6, 16.0)
    assert default_cut(10.0, 16.0, None, 15.2) == (10.0, 15.2)
    assert default_cut(10.0, 16.0, None) == (10.0, 16.0)


def test_測れなかった端は動かさない():
    """**推測で埋めない。** 測れなかった境目で「たぶんこのくらい」を引くと、そのgift演出だけ
    理由の無い秒が切り落とされる。"""
    assert default_cut(10.0, 16.0, 10.6, None) == (10.6, 16.0)
    assert default_cut(10.0, 16.0, None, None) == (10.0, 16.0)


def test_gift演出の外を指す映像の端は使わない():
    """人がgift演出の端を動かした後に起きる形。映像の側は動いていないので、どちらが正しいとも
    言えない ―― 人の端を採る。"""
    assert default_cut(11.0, 16.0, 10.6) == (11.0, 16.0)
    assert default_cut(10.0, 16.0, 16.5) == (10.0, 16.0)
    assert default_cut(10.0, 16.0, None, 16.5) == (10.0, 16.0)
    assert default_cut(10.0, 16.0, None, 9.5) == (10.0, 16.0)


def test_人が詰めた窓は映像の端に上書きされない():
    """``cut_start``/``cut_end`` を持つ行は、その値がそのまま切り出す範囲である。"""
    gift = {"cut_start": 12.0, "cut_end": 15.0}
    assert gift_cut(10.0, 16.0, gift, 10.6, 15.2) == (12.0, 15.0)


# ===== 見せ場 =====

def test_見せ場が測れているgiftはその見せ場が既定の窓になる():
    """1つのgift演出に順番待ちで並んだ演出のうち、そのgiftのものが映っている区間である。

    実測(hl12 / 14.74〜35.69秒)で4件のgiftの演出が順に並んでおり、gift演出の窓をそのまま
    渡すと**主の1本に他人の見せ場が3つ続いた**。"""
    gift = {"show_start": 15.067, "show_end": 21.345}
    assert default_cut(14.745, 35.689, 15.067, None, gift) == (15.067, 21.345)
    assert gift_cut(14.745, 35.689, gift, 15.067, None) == (15.067, 21.345)


def test_見せ場は人が詰めた窓に負ける():
    """人の窓の方が後に置かれた判断である。"""
    gift = {"show_start": 15.067, "show_end": 21.345, "cut_start": 16.0, "cut_end": 20.0}
    assert gift_cut(14.745, 35.689, gift, 15.067, None) == (16.0, 20.0)


def test_見せ場が片方だけの行は使わない():
    """DBを直に触られた行で、片側だけの値が「窓が在る」と読まれないようにする。"""
    assert default_cut(10.0, 16.0, 10.6, 15.2, {"show_start": 12.0}) == (10.6, 15.2)
    assert default_cut(10.0, 16.0, 10.6, 15.2, {"show_end": 15.0}) == (10.6, 15.2)
    assert default_cut(10.0, 16.0, 10.6, 15.2, {}) == (10.6, 15.2)


# ===== 台帳 =====

def test_保存した映像の頭が既定の窓として返る(client, matched_highlight,
                                              make_srv_recording):
    """触っていないgiftの ``cut_start`` が、gift演出の頭ではなく映像の頭になること。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _with_video(_segment(0, 10.0, 16.0, recording_id=recording_id,
                             media_start=100.0, gifts=[_gift(event_id=111,
                                                             media_time=101.2)]),
                    10.62),
    ]))
    segment = _segment_of(client, highlight_id)
    assert segment["video_start"] == 10.62
    assert segment["video_probed"] is True
    gift = segment["gifts"][0]
    assert (gift["cut_start"], gift["cut_end"]) == (10.62, 16.0)
    # **持ち物ではない。** 人が触っていないことは変わらないので、cut_own は偽のままである。
    assert gift["cut_own"] is False


def test_測っていないことと決まらなかったことを言い分ける(client, matched_highlight,
                                                        make_srv_recording):
    """どちらも ``video_start`` は NULL だが、意味が違う ―― 前者は操作の話(押せばよい)、
    後者は素材の話(押しても変わらない)。画面が同じ文言を出すと、決まらないgift演出で人が
    同じbuttonを押し続ける。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        # keyそのものが無い = 一度も測っていない。
        _segment(0, 0.0, 6.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
        # key在り・値なし = 測ったが決まらなかった。
        _with_video(_segment(1, 6.0, 12.0, recording_id=recording_id,
                             media_start=200.0,
                             gifts=[_gift(event_id=222, media_time=201.0)]), None),
    ]))
    segments = client.get(f"/api/highlights/{highlight_id}").json()["segments"]
    assert (segments[0]["video_start"], segments[0]["video_probed"]) == (None, False)
    assert (segments[1]["video_start"], segments[1]["video_probed"]) == (None, True)
    # どちらも切り出しの頭は音の境目のまま。**推測で埋めない。**
    assert segments[0]["gifts"][0]["cut_start"] == 0.0
    assert segments[1]["gifts"][0]["cut_start"] == 6.0


def test_映像を測らない照合は前に測った値を消さない(client, matched_highlight,
                                                  make_srv_recording):
    """照合結果が ``video_start`` を名乗らなければ、列は動かさない。

    測る仕組みを持たない経路(古いjobの再実行・testのstub)が0や NULL を書くと、測って
    あったgift演出の頭が黙って音の境目へ戻る ―― 出力の頭に前の場面が戻るのに、画面には
    何も出ない。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _with_video(_segment(0, 10.0, 16.0, recording_id=recording_id,
                             media_start=100.0,
                             gifts=[_gift(event_id=111, media_time=101.2)]), 10.62),
    ]))
    # 同じgift演出を、映像を名乗らない結果で保存し直す。
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    segment = _segment_of(client, highlight_id)
    assert segment["video_start"] == 10.62
    assert segment["video_probed"] is True


def test_俯瞰の行も映像の頭を名乗る(tmp_db, week):
    """検証の面(週のgift × ハイライト)にも同じ値が要る ―― 区間を詰める操作はあの面で
    行うので、頭がどこから来たのかをあの面が言えないと理由が読めない。"""
    goal = week["ids"]["Goal Highlight"]
    on_air = week["ids"]["LIVE On Air"]
    highlight_id = _cov_highlight(tmp_db, "streamer_a", "hl1.mp4")
    _cov_segment(tmp_db, highlight_id, 0, gift_event_id=goal,
                 start=10.0, end=16.0, gift_media_time=101.2)
    _cov_segment(tmp_db, highlight_id, 1, gift_event_id=on_air,
                 start=20.0, end=26.0, gift_media_time=101.2, video_start=20.62)

    result = tmp_db.highlight_coverage("streamer_a", "", 0)
    # 測っていないgift演出の頭は音の境目のまま。**推測で埋めない。**
    unmeasured = _cov_hit(result, goal)
    assert (unmeasured["video_start"], unmeasured["video_probed"]) == (None, False)
    assert (unmeasured["cut_start"], unmeasured["cut_end"]) == (10.0, 16.0)

    measured = _cov_hit(result, on_air)
    assert measured["video_start"] == 20.62
    assert measured["video_probed"] is True
    assert (measured["cut_start"], measured["cut_end"]) == (20.62, 26.0)


# ===== 書き出し =====

def test_書き出しは映像の綺麗な区間を切る():
    """``_expand_row`` が渡す ``start``/``end`` が既定の窓になること。"""
    row = highlight_export._expand_row(
        {"unique_id": "u", "filename": "a.mp4", "path": "a.mp4"},
        {"id": 3, "highlight_id": 1, "idx": 0, "start": 10.0, "end": 16.0,
         "video_start": 10.62, "video_end": 15.08, "recording_id": 7,
         "media_start": 100.0, "confidence": "high", "effect": []},
        {"id": 9, "gift_event_id": 111, "diamonds": 6000, "cut_start": None,
         "cut_end": None, "cut_own": False})
    assert (row["start"], row["end"]) == (10.62, 15.08)
    # gift演出の窓そのものは別に残る(切った後の照合が突き合わせる相手)。
    assert (row["segment_start"], row["segment_end"]) == (10.0, 16.0)
    assert (row["video_start"], row["video_end"]) == (10.62, 15.08)


# ===== 照合をやり直さずに測り直す =====

def test_映像の切り替わりだけを測り直せる(client, matched_highlight,
                                          make_srv_recording):
    """``update_highlight_switches`` は両端だけを書く。

    照合(音の指紋)は録画を1週間ぶん読み直す重い段で、**切り替わりの測り方が変わっただけで
    走らせる理由が無い**。gift演出の境目にも人の入力にも触らないこと。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
        _segment(1, 16.0, 24.0, recording_id=recording_id, media_start=200.0,
                 gifts=[_gift(event_id=222, media_time=201.0)]),
    ]))
    segments = client.get(f"/api/highlights/{highlight_id}").json()["segments"]
    assert [s["video_probed"] for s in segments] == [False, False]

    written = storage.update_highlight_switches(
        highlight_id, [(10.0, 15.08), (16.62, 24.0)])
    assert written == 2

    segments = client.get(f"/api/highlights/{highlight_id}").json()["segments"]
    # gift演出の境目は動かない。動かすのは切り出しの窓だけである。
    assert [(s["start"], s["end"]) for s in segments] == [(10.0, 16.0), (16.0, 24.0)]
    assert [(s["video_start"], s["video_end"]) for s in segments] == [
        (10.0, 15.08), (16.62, 24.0)]
    assert [s["video_probed"] for s in segments] == [True, True]
    assert segments[0]["gifts"][0]["cut_end"] == 15.08
    assert segments[1]["gifts"][0]["cut_start"] == 16.62


def test_gift演出の数が合わなければ測り直しは書かない(client, matched_highlight,
                                                  make_srv_recording):
    """並びでしか結び付けられない値である。ずれた行へ書くと、**どのgift演出も自分のものでない
    秒を持つ**(数字は出るので画面には正しく見える)。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    with pytest.raises(RuntimeError) as err:
        storage.update_highlight_switches(highlight_id, [(10.0, 15.0), (16.0, 24.0)])
    assert "gift演出の数" in str(err.value)
    segment = _segment_of(client, highlight_id)
    assert (segment["video_start"], segment["video_probed"]) == (None, False)


def test_映像の頭が動いた後の古い下見は検証で止まる(client, matched_highlight,
                                                  make_srv_recording):
    """下見を作った後に測り直すと、切り出す窓が変わる。**そのまま切らせない** ――
    file名と中身が食い違うのはこの経路が防ぐべき唯一の事故である。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    rows = highlight_export._fetch_segments(storage, [highlight_id])
    item = highlight_export._item(rows[0], 0.0, 0.0)
    assert item["gift_cut_start"] == 10.0
    # この時点では区間の食い違いは無い(先へ進んで、実在しないgift eventで止まる)。
    with pytest.raises(highlight_export.NotVerified) as before:
        highlight_export.verify_item(storage, item, item["identity_key"])
    assert "区間" not in str(before.value)

    # 測り直した照合を保存し直す(切り出す窓が動く)。
    storage.save_highlight_match(highlight_id, _fake_result([
        _with_video(_segment(0, 10.0, 16.0, recording_id=recording_id,
                             media_start=100.0,
                             gifts=[_gift(event_id=111, media_time=101.2)]), 10.62),
    ]))
    with pytest.raises(highlight_export.NotVerified) as err:
        highlight_export.verify_item(storage, item, item["identity_key"])
    assert "区間" in str(err.value)
