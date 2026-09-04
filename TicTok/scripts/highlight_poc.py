"""TikTok本体のhighlightを録画へ突き合わせ、そのgiftを投げた人を割り出す実証。

やりたいことは「TikTokが毎日出すhighlight(切り抜き)を集め、gifter単位・高額順に並べて
1本へ繋ぐ」である。highlight自体は「誰が投げたか」を持たないが、こちらは同じ配信を録画し、
gift eventをuser付きでDBに持っている。**highlightが録画のどこから来たのかさえ判れば、
その区間のgift eventを引くだけでgifterが決まる。**

**突き合わせの本体は :mod:`tictok.media.highlight_match` へ移した。** 実物のhighlightが
montage(2.5〜8秒のgift演出を10個ほど繋いだもの)であることが判り、clip全体を1つのoffsetへ
当てる作りが原理的に当たらなくなったためである。ここに残っているのは実証のための2つ:

  - ``synth``  録画のgift地点から窓を切り出し、再encode・拡大・合成演出を掛けた
    **合成highlight**を作る。真値(位置・演出区間・gifter)をJSONに残すので、突き合わせの
    出力を機械的に照合できる。実物のhighlightと違ってgift演出は1つなので、segmentが1本に
    まとまるかどうかもここで確かめられる。
  - ``montage`` **複数の録画**のgift演出を繋いだ合成highlightを作る。実物と同じmontage構造で、
    gift演出の出所を1つのLIVE roomの**別々のsession**へ散らせる。候補をsessionで絞る作りと
    room(``sessions.room_id``)で絞る作りの差は、ここでしか測れない。
  - ``run``    突き合わせを通しで実行し、segmentごとの位置・gift・演出区間を出す。
    真値があれば照合し、合否をexit codeで返す。

置き場は ``<一時保存先>/<配信者>/highlights/``(:func:`tictok.core.layout.highlight_dir`)。
実物は利用者の置き場(``<録画root>/<配信者>/LiveHightlite/``)からそのまま渡せばよい。

使い方::

    python scripts/highlight_poc.py synth --recording 1153
    python scripts/highlight_poc.py index --streamer streamer_a --days 14
    python scripts/highlight_poc.py run --streamer streamer_a --highlight <path> --scope gift
"""

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tictok.core import config, layout  # noqa: E402
from tictok.media import highlight_match as hm  # noqa: E402

logger = logging.getLogger("highlight_poc")

# 合成highlightの作り。実物のhighlightに寄せて、再encode・縮小・音声の作り直しを通す。
SYNTH_WIDTH = 720
SYNTH_LEAD = 12.0           # giftの手前
SYNTH_TAIL = 26.0           # giftの後ろ
SYNTH_EFFECT_LEAD = 1.5     # gift eventからどれだけ遅れて演出が出るか(合成の設定値)
SYNTH_EFFECT_SECONDS = 6.0


# ===== DB =====

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{config.get_db_path()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _recording(conn: sqlite3.Connection, recording_id: int) -> dict:
    row = conn.execute("select * from recordings where id=?", (recording_id,)).fetchone()
    if row is None:
        raise SystemExit(f"録画 id={recording_id} がDBにありません。")
    return dict(row)


def _source_path(recording: dict) -> Path:
    src = hm._source_path(recording)
    if src is None:
        raise SystemExit(f"録画 id={recording['id']} の素材がありません: {recording['path']}")
    return src


# ===== 合成highlight =====

def _effect_filters(at: float, seconds: float) -> str:
    """演出に見立てた重畳。半透明で動く箱を重ねる。

    ``at`` は**入力(録画)の時刻**で渡す。出力側 ``-ss`` で窓を切っても filter が見る ``t``
    は入力のPTSのままなので、切り出しの先頭を0とみなして書くと、演出は録画の頭の方で発火して
    そのまま捨てられる ―― 差分の立たない合成highlightが黙って出来上がる(実際に踏んだ)。

    実物の演出は半透明の絵と加算合成の粒子で、静止した不透明矩形とは差分の出方が違う。
    差分scanの実力を測るのが目的なので、易しすぎる的にはしない。"""
    # 位置は drawbox の入力寸法(iw/ih)で書く。``W``/``H`` は drawbox には無い
    # (``w``/``h`` は箱自身の寸法)ので、式ごと評価に失敗して出力が1 frameも出ない。
    end = at + seconds
    boxes = [
        ("(iw-0.62*iw)/2+0.06*iw*sin(2*PI*(t-%.2f)/2.5)" % at, "(ih-0.62*iw)/2",
         "0.62*iw", "0.62*iw", "gold@0.30"),
        ("0.10*iw", "0.20*ih+0.10*ih*sin(2*PI*(t-%.2f)/1.7)" % at, "0.14*iw", "0.14*iw",
         "white@0.45"),
        ("0.74*iw", "0.30*ih+0.12*ih*cos(2*PI*(t-%.2f)/2.1)" % at, "0.12*iw", "0.12*iw",
         "deepskyblue@0.40"),
        ("0.30*iw+0.30*iw*sin(2*PI*(t-%.2f)/3.3)" % at, "0.70*ih", "0.10*iw", "0.10*iw",
         "magenta@0.35"),
        ("0", "0.86*ih", "iw", "0.14*ih", "black@0.55"),
    ]
    return ",".join(
        f"drawbox=x='{x}':y='{y}':w='{w}':h='{h}':color={c}:t=fill"
        f":enable='between(t,{at:.2f},{end:.2f})'" for x, y, w, h, c in boxes)


def synth(conn: sqlite3.Connection, recording_id: int, rank: int, out_dir: Path) -> Path:
    """録画のgift地点から合成highlightを作り、真値をJSONへ残す。"""
    recording = _recording(conn, recording_id)
    src = _source_path(recording)
    # **giftは録画自身の窓で絞る。** :func:`highlight_match.gifts_of` がその規則を持っている。
    span = recording["duration_seconds"] or 0.0
    gifts = [g for g in hm.gifts_of(conn, recording, src)
             if SYNTH_LEAD < g["media_time"] < span - SYNTH_TAIL]
    gifts.sort(key=lambda g: -(g["diamonds"] or 0))
    if len(gifts) <= rank:
        raise SystemExit(f"録画 id={recording_id} に切り出せるgiftが {len(gifts)} 件しか"
                         "ありません（録画の端に寄りすぎたgiftは除いています）。")
    gift = gifts[rank]
    at = gift["media_time"]
    start = max(0.0, at - SYNTH_LEAD)
    seconds = SYNTH_LEAD + SYNTH_TAIL
    effect_at = at - start + SYNTH_EFFECT_LEAD      # 切り出しの先頭からの秒

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"synth_{recording_id}_{rank}.mp4"
    # 原本へ直接 ``-ss`` を渡すと、出力側seekは要求位置まで復号し続けるので開始位置に比例して
    # 遅い(7,312秒地点で2分超)。差分scanと同じく粗い中間を1つ挟む。
    rough = out.with_suffix(".rough.ts")
    base = hm.rough_cut(src, start, seconds, rough)
    try:
        args = ["ffmpeg", "-v", "error", "-y",
                "-ss", f"{start - base:.3f}", "-i", str(rough), "-t", f"{seconds:.3f}",
                "-vf", f"scale={SYNTH_WIDTH}:-2,"
                + _effect_filters(effect_at, SYNTH_EFFECT_SECONDS),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-c:a", "aac", "-b:a", "64k", "-ar", "44100", "-ac", "2",
                "-map_metadata", "-1", str(out)]
        subprocess.run(args, check=True)
    finally:
        rough.unlink(missing_ok=True)

    truth = {"recording_id": recording_id, "session_id": recording["session_id"],
             "streamer": recording["unique_id"], "media_start": start, "seconds": seconds,
             "effect_start": effect_at, "effect_end": effect_at + SYNTH_EFFECT_SECONDS,
             "gift": {k: gift[k] for k in ("gift_name", "diamonds", "user_nickname",
                                           "user_unique_id", "identity_key", "time")},
             "gift_media": at}
    truth_path = out_dir.parent / "_poc_truth" / (out.stem + ".json")
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("合成highlight %s（%s / %s💎）", out.name, gift["gift_name"], gift["diamonds"])
    return out


# ===== 合成montage(複数の録画からgift演出を繋ぐ) =====

MONTAGE_SECONDS = 6.0       # gift演出1つの長さ。実物のgift演出は2.5〜8.3秒、平均5.5秒。
MONTAGE_LEAD = 1.5          # gift演出の先頭からgift eventまでの秒


def _montage_piece(conn: sqlite3.Connection, recording_id: int, rank: int,
                   scratch: Path, index: int, taken: dict) -> tuple:
    """録画1本からgift演出を1つ切り出す。返り値は (piece path, 真値dict)。

    ``taken`` は録画ごとに既に使ったmedia範囲。**重なる場所を2度採らない。** 高額順に採ると
    近接したgiftが選ばれ、2つのgift演出が同じ場面から出る ―― そうなると突き合わせの側は
    「同じ音が2か所にある」montageを見ることになり、gift演出が1つに畳まれて真値と合わなくなる
    (実際に踏んだ: Galaxy 1000💎 と Fireworks 1088💎 が同じ数秒の中にあった)。"""
    recording = _recording(conn, recording_id)
    src = _source_path(recording)
    span = recording["duration_seconds"] or 0.0
    used = taken.setdefault(recording_id, [])
    gifts = [g for g in hm.gifts_of(conn, recording, src)
             if MONTAGE_LEAD < g["media_time"] < span - MONTAGE_SECONDS
             and not any(lo < g["media_time"] - MONTAGE_LEAD + MONTAGE_SECONDS
                         and g["media_time"] - MONTAGE_LEAD < hi for lo, hi in used)]
    gifts.sort(key=lambda g: -(g["diamonds"] or 0))
    if len(gifts) <= rank:
        raise SystemExit(f"録画 id={recording_id} に切り出せるgiftが {len(gifts)} 件しか"
                         "ありません（既に使った場所と重なるgiftは除いています）。")
    gift = gifts[rank]
    start = gift["media_time"] - MONTAGE_LEAD
    used.append((start, start + MONTAGE_SECONDS))
    piece = scratch / f"piece_{index:02d}.mp4"
    rough = scratch / f"piece_{index:02d}.rough.ts"
    base = hm.rough_cut(src, start, MONTAGE_SECONDS, rough)
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{start - base:.3f}", "-i", str(rough),
             "-t", f"{MONTAGE_SECONDS:.3f}", "-vf", f"scale={SYNTH_WIDTH}:-2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
             "-c:a", "aac", "-b:a", "64k", "-ar", "44100", "-ac", "2",
             "-map_metadata", "-1", str(piece)], check=True)
    finally:
        rough.unlink(missing_ok=True)
    return piece, {"recording_id": recording_id, "session_id": recording["session_id"],
                   "media_start": start, "gift_media": gift["media_time"],
                   "gift_name": gift["gift_name"], "diamonds": gift["diamonds"],
                   "user_nickname": gift["user_nickname"],
                   "user_unique_id": gift["user_unique_id"]}


def montage(conn: sqlite3.Connection, picks: list, out_dir: Path, name: str) -> Path:
    """**複数の録画**の gift 地点からgift演出を切り出し、1本へ繋いだ合成highlightを作る。

    ``synth`` がgift演出1つなのに対し、こちらは実物のhighlightと同じ montage 構造を作る。
    ここでしか測れないのが**候補をどの塊で絞るか**である ―― gift演出の出所を1つのLIVE room内の
    **別々のsession**に散らせば、session単位で絞る作りは片側のsessionを候補から落とし、
    そのgift演出が丸ごと消える。room単位なら両方残る。

    演出の重畳はしない。測りたいのは候補の絞り込みであって差分scanではなく、drawboxは音を
    変えないので指紋にも効かない。

    ``picks`` は ``[(recording_id, rank), ...]``。``rank`` はその録画で何番目に高額なgiftか。"""
    scratch = out_dir / "_montage_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    pieces, fragments, taken = [], [], {}
    try:
        for i, (recording_id, rank) in enumerate(picks):
            piece, truth = _montage_piece(conn, recording_id, rank, scratch, i, taken)
            truth["start"] = i * MONTAGE_SECONDS
            truth["end"] = (i + 1) * MONTAGE_SECONDS
            pieces.append(piece)
            fragments.append(truth)
        listing = scratch / "list.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces),
                           encoding="utf-8")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{name}.mp4"
        # gift演出ごとに符号化しているので、繋ぎ目のtimestampを揃えるために通しで作り直す。
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
             "-c:a", "aac", "-b:a", "64k", "-ar", "44100", "-ac", "2",
             "-map_metadata", "-1", str(out)], check=True)
    finally:
        for piece in pieces:
            piece.unlink(missing_ok=True)
        (scratch / "list.txt").unlink(missing_ok=True)
        scratch.rmdir()

    streamer = _recording(conn, picks[0][0])["unique_id"]
    truth = {"streamer": streamer, "seconds": len(picks) * MONTAGE_SECONDS,
             "fragments": fragments}
    truth_path = out_dir.parent / "_poc_truth" / (out.stem + ".json")
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("合成montage %s（%dgift演出 / session %s）", out.name, len(fragments),
                sorted({f["session_id"] for f in fragments}))
    return out


# ===== 通し =====

def run(conn: sqlite3.Connection, highlight: Path, streamer: str, **kwargs) -> dict:
    """突き合わせを通しで実行し、真値があれば併せて返す。"""
    truth_path = highlight.parent.parent / "_poc_truth" / (highlight.stem + ".json")
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.is_file() else None
    result = hm.match_highlight(conn, highlight, streamer, **kwargs)
    result["truth"] = truth
    result["highlight"] = highlight
    return result


def report(result: dict) -> int:
    """結果を出す。真値があれば照合し、合否をexit codeで返す。

    合成highlightはgift演出が1つなので、真値との照合は**最も長いsegment**を相手に行う。実物の
    highlightはmontageで真値が無いため、そこは一覧を出すだけである。"""
    room = result["room"]
    lines = [
        "",
        f"== {Path(result['highlight']).name} / {result['seconds']:.1f}秒 ==",
        f"  候補        {result['pool']}本 / {result['pool_hours']:.1f}時間"
        f"  scope={result['scope']['scope']}"
        f"  指紋 {result['scope']['indexed_seconds'] / 3600.0:.1f}時間ぶん",
        f"  room        {room['label']}  得票 {room['votes']}"
        f"（2位 {room['runner_up']}）  録画 {room['recordings']}"
        + ("" if room["narrowed"] else f"  ← 絞れず: {room['reason']}"),
        f"  所要        {result['elapsed']:.1f}秒"
        f"（粗い走査 {result['timings']['coarse']:.1f}秒 / 細かい走査"
        f" {result['timings']['fine']:.1f}秒）",
        "",
        "== segment ==",
    ]
    for s in result["segments"]:
        rid = str(s.recording_id) if s.recording_id is not None else "-"
        media = f"{s.media_start:10.3f}s" if s.media_start is not None else " " * 11
        lines.append(f"  #{s.index:<2} {s.start:6.2f}-{s.end:6.2f}s ({s.seconds:5.2f}s)"
                     f"  録画 {rid:>5}  media {media}"
                     f"  votes {s.votes:>4} ratio {s.ratio:5.1f}"
                     f" 相関 {s.corr:+.2f}  {s.confidence}")
        for g in s.gifts:
            lines.append(f"       {'主' if g['primary'] else '  '}"
                         f"{'内' if g['inside'] else '手前'}"
                         f" {g['gift_name']} {g['diamonds'] or 0}💎"
                         f"  by {g['user_nickname']}（{g['user_unique_id']}）"
                         f"  highlight {g['at']:.2f}s / media {g['media_time']:.2f}s")
        if s.effect:
            lines.append("       演出 "
                         + str([(round(a, 2), round(b, 2)) for a, b in s.effect]))

    failed = []
    truth = result["truth"]
    if truth and truth.get("fragments"):
        # montage の真値。gift演出ごとに録画とgifterが判っているので、**並び順込み**で照合する。
        # 落ちたgift演出をここで見逃さないことが目的なので、件数の食い違いも失格にする。
        got = [(next((g for g in s.gifts if g["primary"]), None), s)
               for s in result["segments"] if s.gifts]
        lines += ["", "== 真値との照合（montage） =="]
        want = truth["fragments"]
        for i in range(max(len(got), len(want))):
            a = got[i][0] if i < len(got) else None
            b = want[i] if i < len(want) else None
            ok = (a is not None and b is not None
                  and got[i][1].recording_id == b["recording_id"]
                  and a["gift_name"] == b["gift_name"]
                  and a["user_nickname"] == b["user_nickname"])
            lines.append(
                f"  #{i} {'一致' if ok else '不一致'}"
                f"  出力 {a and (got[i][1].recording_id, a['gift_name'], a['user_nickname'])}"
                f"  真値 {b and (b['recording_id'], b['gift_name'], b['user_nickname'])}")
            if not ok:
                failed.append(f"#{i} が真値と食い違う")
        lines += ["", ("判定: 不合格 — " + " / ".join(failed)) if failed else "判定: 合格"]
    elif truth:
        located = [s for s in result["segments"] if s.recording_id is not None]
        # 合成highlightはgift演出が1つなので、最も長いsegmentの**主**のgiftと照合する。
        best = max(located, key=lambda s: s.seconds) if located else None
        lines += ["", "== 真値との照合 =="]
        if best is None:
            failed.append("どのsegmentも録画へ落ちなかった")
        else:
            drift = best.media_start - (truth["media_start"] + best.start)
            lines.append(f"  offset誤差  {drift * 1000:+.0f}ms"
                         f"（segment #{best.index} / {best.seconds:.1f}秒）")
            if abs(drift) > 0.5:
                failed.append(f"offsetが{drift:+.2f}sずれている")
            if best.recording_id != truth["recording_id"]:
                failed.append(f"録画を取り違えた（{best.recording_id}"
                              f" != {truth['recording_id']}）")
            if best.ratio < hm.MIN_RATIO:
                failed.append(f"山が立っていない（ratio {best.ratio:.1f} < {hm.MIN_RATIO}）")
            if best.corr < hm.MIN_CORR:
                failed.append(f"追い込みが効かなかった（相関 {best.corr:.2f} < {hm.MIN_CORR}）")
            want = truth["gift"]
            got = next((g for g in best.gifts if g["primary"]), None)
            lines.append(f"  gifter      出力 {got and got['user_nickname']}"
                         f"  真値 {want['user_nickname']}")
            if not got or got["user_nickname"] != want["user_nickname"]:
                failed.append("gifterが一致しない")
            span = max(best.effect, key=lambda s: s[1] - s[0]) if best.effect else None
            lines.append(f"  演出区間    出力 {span}  真値 "
                         f"({truth['effect_start']:.2f}, {truth['effect_end']:.2f})")
            if span is None or abs(span[0] - truth["effect_start"]) > 1.0:
                failed.append("演出の始点が1秒以上ずれている")
        lines += ["", ("判定: 不合格 — " + " / ".join(failed)) if failed else "判定: 合格"]
    lines.append("")
    logger.info("\n".join(lines))
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("synth", help="録画のgift地点から合成highlightを作る")
    p.add_argument("--recording", type=int, required=True)
    p.add_argument("--rank", type=int, default=0, help="その録画で何番目に高額なgiftか")

    p = sub.add_parser("montage", help="複数の録画のgift演出を繋いだ合成highlightを作る")
    p.add_argument("--picks", required=True,
                   help="「録画id:rank」をcommaで並べる（例 1054:0,1057:0,1054:1）")
    p.add_argument("--name", default="montage", help="出力fileの名前（拡張子なし）")

    p = sub.add_parser("index", help="録画の指紋を作ってcacheする")
    p.add_argument("--streamer", default="", help="省略すると全配信者")
    p.add_argument("--days", type=float, default=hm.DEFAULT_DAYS)
    p.add_argument("--refresh", action="store_true")

    p = sub.add_parser("run", help="突き合わせ→segment→gifter→演出区間を通しで実行する")
    p.add_argument("--highlight", required=True)
    p.add_argument("--streamer", default="", help="省略すると全配信者を候補にする")
    p.add_argument("--days", type=float, default=hm.DEFAULT_DAYS)
    p.add_argument("--scope", default=hm.DEFAULT_SCOPE, choices=list(hm.SCOPES))
    p.add_argument("--gift-lead", type=float, default=hm.GIFT_LEAD)
    p.add_argument("--gift-tail", type=float, default=hm.GIFT_TAIL)
    # 既定は**書かない**。``None`` のまま渡すと ``match_highlight`` が設定値
    # (:func:`config.get_highlight_effect_coin_floor`)を引く。ここに数字を置くと、設定画面で
    # 変えた値をこのscriptだけが素通りする。
    p.add_argument("--min-diamonds", type=int, default=None)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = _connect()

    if args.cmd == "synth":
        streamer = _recording(conn, args.recording)["unique_id"]
        synth(conn, args.recording, args.rank, layout.highlight_dir(streamer))
        return 0

    if args.cmd == "montage":
        picks = [(int(a), int(b)) for a, _, b in
                 (item.partition(":") for item in args.picks.split(","))]
        streamer = _recording(conn, picks[0][0])["unique_id"]
        montage(conn, picks, layout.highlight_dir(streamer), args.name)
        return 0

    if args.cmd == "index":
        rows = hm.candidates(conn, args.streamer, args.days)
        started, hours, size = time.time(), 0.0, 0
        for row in rows:
            src = _source_path(row)
            hm.fingerprint_of(src, args.refresh)
            hours += (row["duration_seconds"] or 0) / 3600.0
            size += hm.fingerprint_path(src).stat().st_size
        spent = time.time() - started
        logger.info("%d本 / %.1f時間 の指紋を %.1f秒で用意しました"
                    "（実時間の%.0f倍速 / cache %.1fMB）",
                    len(rows), hours, spent, hours * 3600 / max(spent, 1e-9), size / 1e6)
        return 0

    return report(run(conn, Path(args.highlight), args.streamer, days=args.days,
                      scope=args.scope, gift_lead=args.gift_lead, gift_tail=args.gift_tail,
                      min_diamonds=args.min_diamonds))


if __name__ == "__main__":
    raise SystemExit(main())
