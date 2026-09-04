"""書き出したmp4の中身が本当に合っているかを、**後から**DBで確かめる。

    venv/Scripts/python scripts/verify_highlight_export.py [--streamer pomiiiip] [--json]

事故があったので在るscriptである。`highlight_videos` が0行の状態で手で組んだ定義から7本の
mp4が出て、``あきと`` の名前を持つfileの中身は ``よい`` が投げた Guardian's Pledge だった。
**file名は誰の物かを名乗るが、名前の側に中身の保証は何も無い。**

いまは書き出しのたびに素性が隣へ残る(``<file名>.mp4.json``)。ここはそれを**信用せずに**
1件ずつDBへ引き直す —— 素性は書き出した側の言い分でしかないので、それだけを読んで「合って
いる」と言うなら、名前を読んで合っていると言うのと変わらない。

見るのは4つ。

1. mp4の隣に素性が在るか。**無いfileは中身の出所を辿れない**(事故で残った7本がこれだった)。
2. 素性がそのfileの物か(容量が一致するか)。
3. gift演出1件ずつが、DBの ``highlight_segments`` の行と ``events`` のgiftに突き当たるか。
4. **そのgiftを投げた人が、file名が名乗っている持ち主と同じ人か。** 事故の形はこれである。

judgeはDBを読むだけで、fileにもDBにも書かない。
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tictok.core import config, layout  # noqa: E402
from tictok.media import highlight_export as hx  # noqa: E402
from tictok.media.clipper import parse_clip_name  # noqa: E402

# 素性とDBを突き合わせる列。書き出し側(:func:`tictok.media.highlight_export.verify_item`)が
# 切る直前に見ているものと**同じ集合**にする。片方だけを増やすと、書き出しは通るのに後から
# 見ると落ちる(またはその逆)という状態が生まれる。
#
# gift演出とgiftは別の表である(``highlight_segments`` / ``highlight_segment_gifts``)。gift演出1つが
# 複数のgiftを持つので、位置(どこを切るか)はgift演出が、持ち主(誰のfileか)はgiftが決める。
SEGMENT_COLUMNS = ("recording_id", "media_start")
GIFT_COLUMNS = ("gift_event_id", "gift_id", "gift_name", "diamonds")


def _rows(conn, sql: str, params: tuple = ()) -> list:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _merged_dirs(streamer: str) -> list:
    """走査する置き場。``<root>/<配信者>/LiveHightlite_マージ済み`` を両rootぶん。

    出力を作るのは work root だけだが(``layout.merged_highlight_dir``)、成果物は最終保存先へ
    運ばれ得る。片方しか見ないjudgeは「運ばれた1本」を黙って見逃す。"""
    found = []
    for root in layout.record_roots():
        base = Path(root)
        streamers = ([streamer] if streamer else
                     sorted(p.name for p in base.iterdir() if p.is_dir())
                     if base.is_dir() else [])
        for name in streamers:
            target = base / name / layout.MERGED_HIGHLIGHT_DIRNAME
            if target.is_dir():
                found.append(target)
    return found


def _check_file(conn, path: Path) -> dict:
    """mp4 1本を確かめる。``{path, ok, problems[], segments}``。"""
    problems: list = []
    parsed = parse_clip_name(path.name) or {}
    side = hx.provenance_path(path)
    if not side.is_file():
        # 素性が無いfileは、この時点で「出所を辿れない」ことが確定する。中身の判定へは
        # 進めない —— どのgift演出から出来ているかを名乗るものが何も無いためである。
        return {"path": str(path), "ok": False, "segments": 0,
                "owner": parsed.get("label") or "",
                "problems": ["素性のJSONがありません（中身の出所を辿れません）"]}
    try:
        record = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"path": str(path), "ok": False, "segments": 0,
                "owner": parsed.get("label") or "",
                "problems": [f"素性のJSONを読めません: {exc}"]}

    if not record.get("verified"):
        problems.append("素性が verified=false です（検証用の出力）")
    size = path.stat().st_size
    if (record.get("output") or {}).get("bytes") not in (None, size):
        problems.append(
            f"素性が別のfileの物です（素性 {record['output']['bytes']} byte / "
            f"実物 {size} byte）")

    owner = (record.get("gifter") or {}).get("identity_key")
    nickname = (record.get("gifter") or {}).get("nickname") or ""
    if parsed and parsed.get("label") and parsed["label"] != nickname:
        # file名の表示名と素性の表示名が違う。名前を書き換えただけかもしれないが、
        # 中身と名前が食い違う可能性そのものが今回の事故なので黙らない。
        problems.append(
            f"file名の表示名と素性が違います（名前 {parsed['label']!r} / "
            f"素性 {nickname!r}）")

    segments = record.get("segments") or []
    if not segments:
        problems.append("素性がgift演出を1件も名乗っていません")
    for entry in segments:
        problems.extend(_check_segment(conn, entry, owner))
    return {"path": str(path), "ok": not problems, "problems": problems,
            "owner": nickname, "segments": len(segments)}


def _check_segment(conn, entry: dict, owner) -> list:
    """素性のgift演出1件をDBへ引き直す。問題の一覧を返す(無ければ空)。"""
    position = entry.get("position")
    segment_id = entry.get("segment_id")
    rows = _rows(conn, "SELECT * FROM highlight_segments WHERE id = ?", (segment_id,))
    if not rows:
        return [f"{position}件目: gift演出の行がありません（segment {segment_id}）"]
    segment = rows[0]
    problems = []
    if segment["highlight_id"] != entry.get("highlight_id"):
        problems.append(
            f"{position}件目: gift演出が別のhighlightの物です"
            f"（DB {segment['highlight_id']} / 素性 {entry.get('highlight_id')}）")
    for column in SEGMENT_COLUMNS:
        if not hx._same(segment.get(column), entry.get(column)):
            problems.append(
                f"{position}件目: {column} がDBと違います"
                f"（DB {segment.get(column)!r} / 素性 {entry.get(column)!r}）")
    if segment["excluded"] or segment["dropped"]:
        problems.append(f"{position}件目: いまは外されているgift演出です（segment {segment_id}）")

    # giftは**そのgift演出の持ち物の中から**引く。gift演出の外から持ってきたgiftを、gift演出の映像へ
    # 結び付けさせない(1つのgift演出が複数のgiftを持つので、event idだけで引くと別のgift演出の
    # giftでも当たってしまう)。
    gifts = _rows(conn,
                  "SELECT * FROM highlight_segment_gifts"
                  " WHERE segment_id = ? AND gift_event_id = ?",
                  (segment_id, entry.get("gift_event_id")))
    if not gifts:
        return problems + [
            f"{position}件目: そのgift演出はこのgiftを持っていません"
            f"（event {entry.get('gift_event_id')}）"]
    gift = gifts[0]
    for column in GIFT_COLUMNS:
        if not hx._same(gift.get(column), entry.get(column)):
            problems.append(
                f"{position}件目: {column} がDBと違います"
                f"（DB {gift.get(column)!r} / 素性 {entry.get(column)!r}）")
    if gift["excluded"] or gift["dropped"]:
        problems.append(f"{position}件目: いまは外されているgiftです（event {gift['gift_event_id']}）")

    events = _rows(conn, "SELECT * FROM events WHERE id = ? AND kind = 'gift'",
                   (gift["gift_event_id"],))
    if not events:
        return problems + [
            f"{position}件目: gift eventがありません（event {gift['gift_event_id']}）"]
    event = events[0]
    if not hx._same(event["diamonds"], gift["diamonds"]):
        problems.append(
            f"{position}件目: 💎がeventと違います"
            f"（event {event['diamonds']} / gift演出 {gift['diamonds']}）")
    if not hx._same(event["gift_name"], gift["gift_name"]):
        problems.append(
            f"{position}件目: gift名がeventと違います"
            f"（event {event['gift_name']!r} / gift演出 {gift['gift_name']!r}）")
    if not hx._same(event["identity_key"], owner):
        # **事故の形。** このfileの持ち主ではない人のgiftが入っている。
        problems.append(
            f"{position}件目: **別人のgiftです**（{event['user_nickname']!r} が投げた "
            f"{event['gift_name']} / event {event['id']}）")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--streamer", default="", help="配信者(unique_id)。既定は全員")
    parser.add_argument("--json", action="store_true", help="結果をJSONで出す")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{config.get_db_path()}?mode=ro", uri=True)
    try:
        results = [_check_file(conn, path)
                   for directory in _merged_dirs(args.streamer)
                   for path in sorted(directory.glob(f"*{hx.STORY_EXT}"))]
    finally:
        conn.close()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            head = "OK  " if item["ok"] else "NG  "
            print(f"{head}{Path(item['path']).name}"
                  f"（{item['owner']} / gift演出 {item['segments']}件）")
            for problem in item["problems"]:
                print(f"      - {problem}")
        bad = [item for item in results if not item["ok"]]
        print(f"\n{len(results)}本中 {len(results) - len(bad)}本が一致、{len(bad)}本に問題。")
    return 1 if any(not item["ok"] for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
