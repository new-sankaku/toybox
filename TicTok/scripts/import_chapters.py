"""外で書いた章立てを、この app の章立て(ai_analysis)と切り抜き候補(見どころ)へ入れる。

置き場は2つに分かれる。どちらも既にあるもので、この script は入口を足すだけである。

* **章立て** … ``ai_analysis`` の kind=chapters。録画1本に対する目次で、再生画面の章panel・
  VTT/説明欄用の書き出し・切り出し範囲の章clampがすべてここを読む。
* **切り抜き候補** … ``bookmarks`` の origin=pick。目次のうち「切り出す素材にする」と決めた
  範囲だけが入り、一覧で色が変わり、mp4の書き出し対象になる。

行の形は::

    [{"recording_id": 1120, "start": 0.0, "title": "オープニング"},
     {"recording_id": 1120, "start": 2632.0, "end": 2856.0, "title": "…", "pick": true}]

``start``/``end`` は**その録画のmedia軸の秒**である。配信が複数の録画に分かれていれば、
2本目の値は通し時刻ではなく2本目の先頭を0とした秒で書くこと。章立てを録画ごとに分けるのも
同じ理由で、通し時刻の目次を1本作ると2本目の章が全部その録画の尺の外を指す。

``end`` は切り抜き候補の終端にだけ使う。章の終端は書かない ―― 目次の章は次章の開始までを
覆うものなので、ここで別に持つと2つの終端が食い違う(``ai_analysis.analyze_chapters`` の
``_finalize`` と同じ決め方をこの script も使う)。

``--model`` はその目次を誰が書いたかで、再生画面の章panelにそのまま出る。既定を置かないのは、
「いつ・どのmodelで作った目次か」が分からない状態で表題を事実として読ませないためである。

使い方::

    python -m scripts.import_chapters <chapters.json> --model <名前> [--replace] [--apply]

``--apply`` を付けるまでは検査だけで書き込まない。既に章立てがある録画は既定で何もせず
終わる ―― ``--replace`` を付けるとその録画の章立てと切り抜き候補だけを入れ替える
(人が付けた見どころ origin=manual と自動生成 origin=auto には触らない)。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json  # noqa: E402

from tictok.ai import ai_analysis  # noqa: E402
from tictok.core.config import get_db_path  # noqa: E402
from tictok.storage import Storage  # noqa: E402

# この script が入れ替えてよい見どころ。人が押した印と自動生成には手を触れない。
MANAGED_ORIGIN = "pick"


def load(path: Path) -> list:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit(f"{path}: 配列を書いてください。")
    for number, row in enumerate(rows, start=1):
        missing = [k for k in ("recording_id", "start", "title") if k not in row]
        if missing:
            raise SystemExit(f"{path}[{number}] に {missing} がありません")
        if row.get("end") is not None and not row.get("pick"):
            raise SystemExit(f"{path}[{number}]: endは切り抜き候補(pick)にだけ書けます")
        if row.get("pick") and row.get("end") is None:
            raise SystemExit(f"{path}[{number}]: 切り抜き候補には終端(end)が要ります")
    return rows


def verify(storage: Storage, rows: list) -> list:
    """尺と範囲の整合を全件見て、通らない行を返す。

    録画の尺を唯一の物差しにする。通し時刻のまま書かれた行はここで全部落ちるので、軸の
    取り違えが半分だけ入った状態にはならない。"""
    bad = []
    durations: dict = {}
    for row in rows:
        rec_id = int(row["recording_id"])
        if rec_id not in durations:
            recording = storage.get_recording(rec_id)
            durations[rec_id] = None if recording is None else recording["duration_seconds"]
        duration = durations[rec_id]
        if duration is None:
            bad.append((row, f"録画 {rec_id} が無いか尺が未確定です"))
            continue
        start = float(row["start"])
        end = row.get("end")
        if not 0 <= start < duration:
            bad.append((row, f"開始 {start:.1f}s が尺 {duration:.1f}s の外です"))
        elif end is not None and not start < float(end) <= duration:
            bad.append((row, f"終了 {float(end):.1f}s が開始〜尺 {duration:.1f}s に収まりません"))
    seen: dict = {}
    for row in rows:
        key = (int(row["recording_id"]), round(float(row["start"]), 2))
        if key in seen:
            bad.append((row, f"開始位置が {seen[key]!r} と重複しています"))
        else:
            seen[key] = row["title"]
    return bad


def _quote_at(segments: list, start: float) -> str:
    """その章の位置で実際に喋っている一文。章panelが表題の下に併記して、表題が外れて
    いないかをseekせずに確かめるための根拠にする。掛かるsegmentが無ければ空にする
    (近い発話を拾って埋めると、根拠のふりをした別の位置の文になる)。"""
    for seg in segments or []:
        if float(seg["end"]) > start:
            return (seg.get("text") or "").strip()
    return ""


def build_chapters(storage: Storage, rows: list, recording_id: int) -> list:
    """1録画ぶんの章list。終端は次章の開始、最後の章は実尺 ―― analyze_chaptersの
    ``_finalize`` と同じ決め方にする(生成経路と取り込み経路で章の形を変えない)。"""
    mine = sorted((r for r in rows if int(r["recording_id"]) == recording_id),
                  key=lambda r: float(r["start"]))
    duration = float(storage.get_recording(recording_id)["duration_seconds"])
    transcript = storage.get_transcript(recording_id) or {}
    segments = transcript.get("segments") or []
    out = []
    for index, row in enumerate(mine):
        start = float(row["start"])
        end = float(mine[index + 1]["start"]) if index + 1 < len(mine) else duration
        if end <= start:
            continue
        out.append({"start": round(start, 3), "end": round(end, 3),
                    "title": row["title"], "quote": _quote_at(segments, start)})
    return out


def existing_picks(storage: Storage, recording_ids: list) -> list:
    rows = []
    for rec_id in recording_ids:
        rows.extend(mark for mark in storage.list_bookmarks(rec_id)
                    if mark.get("origin") == MANAGED_ORIGIN)
    return rows


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description="章立てと切り抜き候補を取り込む")
    parser.add_argument("path", type=Path)
    parser.add_argument("--model", required=True,
                        help="その目次を書いたmodel名。章panelにそのまま出る")
    parser.add_argument("--replace", action="store_true",
                        help="対象録画の既存の章立て・切り抜き候補を入れ替える")
    parser.add_argument("--apply", action="store_true", help="実際に書き込む")
    args = parser.parse_args(argv[1:])

    rows = load(args.path)
    recording_ids = sorted({int(r["recording_id"]) for r in rows})
    storage = Storage(get_db_path())
    try:
        bad = verify(storage, rows)
        if bad:
            print(f"★ {len(bad)} 件が通りません。何も書き込みません。")
            for row, why in bad[:20]:
                print(f"  rec {row['recording_id']} {float(row['start']):>9.1f}s "
                      f"{row['title']!r}: {why}")
            return 1
        picks = [r for r in rows if r.get("pick")]
        print(f"検査: {len(rows)} 件（章 {len(rows)} / うち切り抜き候補 {len(picks)}）"
              f" 全件が録画の尺に収まりました。")

        already = [rec_id for rec_id in recording_ids
                   if storage.get_ai_analysis(ai_analysis.KIND_CHAPTERS,
                                              ai_analysis.TARGET_RECORDING, str(rec_id))]
        already_picks = existing_picks(storage, recording_ids)
        if (already or already_picks) and not args.replace:
            print(f"★ 既に章立てのある録画が {len(already)} 本、"
                  f"切り抜き候補が {len(already_picks)} 件あります。"
                  " --replace を付けると入れ替えます。")
            return 1

        if not args.apply:
            print("\n--apply を付けると書き込みます。")
            return 0

        if already_picks:
            removed = storage.delete_bookmarks([m["id"] for m in already_picks])
            print(f"  既存の切り抜き候補を {removed} 件消しました。")
        for rec_id in recording_ids:
            chapters = build_chapters(storage, rows, rec_id)
            recording = storage.get_recording(rec_id)
            # 指紋は生成経路(POST /chapters)と同じ形で入れる。同じ文字起こしのまま
            # 「章立てを作る」を押したときに、modelが違うので必ず作り直しになる。
            signature = ai_analysis.input_signature(
                {"segments": (storage.get_transcript(rec_id) or {}).get("segments"),
                 "duration": recording["duration_seconds"]})
            storage.save_ai_analysis(
                ai_analysis.KIND_CHAPTERS, ai_analysis.TARGET_RECORDING, str(rec_id),
                session_id=recording.get("session_id"), model=args.model,
                prompt_version=ai_analysis.CHAPTERS_PROMPT_VERSION,
                input_signature=signature,
                payload={"chapters": chapters, "segment_count": len(chapters)})
            print(f"  recording {rec_id}: 章 {len(chapters)} 件")
        for row in picks:
            recording = storage.get_recording(int(row["recording_id"]))
            storage.add_bookmark(
                int(row["recording_id"]), recording["unique_id"], float(row["start"]),
                float(row["end"]), row["title"], origin=MANAGED_ORIGIN)
        print(f"\n取り込み完了: 章立て {len(recording_ids)} 録画 / "
              f"切り抜き候補 {len(picks)} 件（一覧で色が変わって出ます）")
        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
