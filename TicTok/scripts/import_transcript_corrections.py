"""文字起こしの訂正をJSONLからDBへ取り込む。

行の形は ``{"recording_id", "start", "src", "dst", "origin", "conf", "why"}``。
``start`` と ``src`` の組がその発話の身元なので、**srcは実際のsegmentと一字一句同じ**で
なければならない。取り込み前に全件を実segmentと突き合わせ、1件でも合わなければ何も入れずに
終わる — 半分だけ入った訂正が字幕へ出る方が、入らないより悪い。

使い方:
    python -m scripts.import_transcript_corrections <corrections.jsonl> [--apply]

``--apply`` を付けるまでは検査だけで書き込まない。取り込み後は検索indexの張り直しが要る
(索引は本文を写し取った別の行で、読み出し時の重ね合わせを通らない)。
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tictok.core.config import get_db_path  # noqa: E402
from tictok.storage import Storage  # noqa: E402


def load(path: Path) -> list:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            missing = [k for k in ("recording_id", "start", "src", "dst") if k not in row]
            if missing:
                raise SystemExit(f"{path}:{number} に {missing} がありません")
            rows.append(row)
    return rows


def verify(storage: Storage, rows: list) -> list:
    """srcが実segmentと一致するかを全件検査し、合わない行を返す。"""
    bad = []
    for recording_id in sorted({int(r["recording_id"]) for r in rows}):
        transcript = storage.get_transcript(recording_id, raw=True)
        if transcript is None:
            bad.extend((r, "文字起こしがありません")
                       for r in rows if int(r["recording_id"]) == recording_id)
            continue
        by_start = {}
        for seg in transcript["segments"]:
            by_start.setdefault(round(float(seg["start"]), 2), []).append(seg["text"])
        for row in rows:
            if int(row["recording_id"]) != recording_id:
                continue
            texts = by_start.get(round(float(row["start"]), 2), [])
            if row["src"] not in texts:
                bad.append((row, f"srcが実segmentと不一致（実際: {texts}）"))
            elif row["src"] == row["dst"]:
                bad.append((row, "srcとdstが同じ（訂正になっていない）"))
    return bad


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--apply", action="store_true", help="実際に書き込む")
    args = parser.parse_args(argv[1:])

    rows = load(args.jsonl)
    print(f"読み込み: {len(rows)} 件 / 録画 {len({r['recording_id'] for r in rows})} 本")
    confidence = Counter(r.get("conf") or "-" for r in rows)
    print("信頼度:", dict(confidence))

    storage = Storage(get_db_path())
    try:
        bad = verify(storage, rows)
        if bad:
            print(f"\n★ {len(bad)} 件が実segmentと一致しません。何も書き込みません。")
            for row, why in bad[:20]:
                print(f"  {row['start']:>9.2f} {row['src']!r}: {why}")
            return 1
        print("検査: 全件が実segmentと一致しました。")
        if not args.apply:
            print("\n--apply を付けると書き込みます。")
            return 0

        total = {"received": 0, "added": 0, "updated": 0}
        for recording_id in sorted({int(r["recording_id"]) for r in rows}):
            payload = [{"start": float(r["start"]), "src": r["src"], "dst": r["dst"],
                        "origin": r.get("origin") or "ai",
                        "confidence": r.get("conf"), "note": r.get("why")}
                       for r in rows if int(r["recording_id"]) == recording_id]
            result = storage.upsert_corrections(recording_id, payload)
            for key in total:
                total[key] += result[key]
            applied = storage.get_transcript(recording_id)["corrections_applied"]
            print(f"  recording {recording_id}: 追加 {result['added']} / "
                  f"更新 {result['updated']} / 実際に効いた {applied}")
        print(f"\n取り込み完了: {total}")
        print("検索indexの張り直しが要ります（訂正は索引の行には届きません）。")
        return 0
    finally:
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
