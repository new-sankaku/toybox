"""再mp4化・焼き込みの各段階を実測するbench(本番のfileには一切触れない)。

最適化の前後で同じ録画・同じ出力先に対して走らせ、段階ごとの秒数を比べるために使う。
出力は --work で指定したdirへ書き、実際の録画mp4は置き換えない。

    python scripts/bench_pipeline.py --stem <録画stem> --work K:\\_bench --stage reprocess
    python scripts/bench_pipeline.py --stem <録画stem> --work K:\\_bench --stage overlay
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import config, layout
from tictok.record.recorder import (
    Recorder,
    probe_mp4_resolutions,
    reencode_single_resolution,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")

ROOTS = [Path(r"C:\01_work\00_Git\toybox\TicTok\recordings"), Path(r"K:\80_Tiktok")]


def find_hls_root(stem: str):
    for root in ROOTS:
        d = layout.session_dir(root, stem)
        if d.is_dir() and any(d.glob("seg*.ts")):
            return root
    return None


def find_mp4(stem: str):
    for root in ROOTS:
        p = layout.mp4_path(root, stem)
        if p.is_file():
            return p
    return None


class Timer:
    def __init__(self) -> None:
        self.marks: list = []

    def mark(self, label: str, seconds: float, extra: str = "") -> None:
        self.marks.append((label, seconds, extra))
        print(f"  {label:<18} {seconds:8.1f}s  {extra}", flush=True)

    def report(self, title: str) -> dict:
        total = sum(s for _, s, _ in self.marks)
        print(f"  {'TOTAL':<18} {total:8.1f}s")
        return {"title": title,
                "stages": [{"stage": k, "seconds": round(s, 2), "note": e}
                           for k, s, e in self.marks],
                "total_seconds": round(total, 2)}


async def bench_reprocess(stem: str, work: Path) -> dict:
    root = find_hls_root(stem)
    if root is None:
        raise SystemExit(f"HLS segments not found for {stem}")
    hls_dir = layout.session_dir(root, stem)
    segs = len(list(hls_dir.glob("seg*.ts")))
    src_bytes = sum(p.stat().st_size for p in hls_dir.glob("seg*.ts"))
    print(f"[reprocess] {stem}  segments={segs}  ts={src_bytes/1e6:.0f}MB  root={root}")

    work.mkdir(parents=True, exist_ok=True)
    out = work / f"{stem}.bench.mp4"
    out.unlink(missing_ok=True)

    rec = Recorder(stem, str(root), 0, keep_hls=True, final_dir=str(root))
    rec.base = stem
    rec.hls_dir = hls_dir
    rec.playlist = hls_dir / "index.m3u8"
    rec.started_at = time.time()

    t = Timer()
    started = time.monotonic()
    ok = await rec._concat_to_mp4(out)
    if not ok:
        raise SystemExit("concat failed")
    t.mark("concat", time.monotonic() - started, f"{out.stat().st_size/1e6:.0f}MB")

    # 本番と同じ順序: concatが並行走査を済ませていればそれを使い、無いときだけ読み直す。
    started = time.monotonic()
    distinct = rec._concat_resolutions
    reused = distinct is not None
    if distinct is None:
        distinct = await probe_mp4_resolutions(out)
    t.mark("probe", time.monotonic() - started,
           ("(concatと並行) " if reused else "")
           + ",".join(sorted(f"{w}x{h}" for w, h in distinct)))

    if len(distinct) > 1:
        tw = max(w for w, _ in distinct)
        th = max(h for _, h in distinct)
        tw += tw % 2
        th += th % 2
        tmp = work / f"{stem}.bench.norm.tmp"
        tmp.unlink(missing_ok=True)
        started = time.monotonic()
        mode = await reencode_single_resolution(
            out, tmp, tw, th, config.get_normalize_scale_mode(),
            config.get_normalize_codec(), config.get_normalize_quality(),
            audio_copy=True,
        )
        t.mark("normalize", time.monotonic() - started,
               f"{mode} {tmp.stat().st_size/1e6:.0f}MB" if tmp.is_file() else str(mode))
    return t.report(f"reprocess {stem}")


async def bench_overlay(stem: str, work: Path) -> dict:
    """焼き込みは ensure_overlay をそのまま呼ぶ。src mp4 は work へ複製し、成果物も
    work 配下にしか作らせない(本番の <stem>.overlay.mp4 を触らないため)。"""
    from tictok.core.settings import Settings
    from tictok.record import video_overlay
    from tictok.storage import Storage

    src = find_mp4(stem)
    if src is None:
        raise SystemExit(f"mp4 not found for {stem}")
    work.mkdir(parents=True, exist_ok=True)
    local = work / f"{stem}.mp4"
    if not local.is_file() or local.stat().st_size != src.stat().st_size:
        started = time.monotonic()
        shutil.copy2(src, local)
        print(f"  (copied source {src.stat().st_size/1e6:.0f}MB in "
              f"{time.monotonic()-started:.0f}s)", flush=True)
    for sidecar in (".timing.json",):
        s = src.with_suffix(sidecar) if src.suffix else None
    timing = src.parent / f"{src.stem}.mp4.timing.json"
    if timing.is_file():
        shutil.copy2(timing, work / timing.name)

    storage = Storage(config.get_db_path())
    row = None
    for r in storage.list_recordings(100000):
        if Path(r.get("filename") or "").stem == stem:
            row = r
            break
    if row is None:
        raise SystemExit(f"recording row not found for {stem}")
    events = storage.iter_events(row["session_id"], row["started_at"], row.get("ended_at"))
    battles = storage.battles_for_session(row["session_id"])
    settings = Settings(storage)
    print(f"[overlay] {stem}  events={len(events)}  src={local.stat().st_size/1e6:.0f}MB")

    stages: dict = {}
    order: list = []
    last = {"key": None, "at": time.monotonic()}

    async def progress(pct: int, stage: str) -> None:
        key = stage.split("/")[0].strip()
        now = time.monotonic()
        if key != last["key"]:
            if last["key"] is not None:
                stages[last["key"]] = stages.get(last["key"], 0.0) + now - last["at"]
            else:
                order.append("__start__")
            if key not in order:
                order.append(key)
            last["key"] = key
            last["at"] = now

    started = time.monotonic()
    await video_overlay.ensure_overlay(
        str(local), row["started_at"], row["ended_at"], events, settings,
        battles=battles, on_progress=progress,
    )
    total = time.monotonic() - started
    if last["key"] is not None:
        stages[last["key"]] = stages.get(last["key"], 0.0) + time.monotonic() - last["at"]
    t = Timer()
    for key in order:
        if key in stages:
            t.mark(key[:18], stages[key])
    print(f"  {'WALL':<18} {total:8.1f}s")
    result = t.report(f"overlay {stem}")
    result["wall_seconds"] = round(total, 2)
    out = video_overlay.overlay_paths(local)[0]
    result["output_bytes"] = out.stat().st_size if out.is_file() else 0
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stem", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--stage", choices=("reprocess", "overlay"), default="reprocess")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", help="結果JSONの追記先")
    args = parser.parse_args()

    work = Path(args.work)
    if args.stage == "reprocess":
        result = await bench_reprocess(args.stem, work)
    else:
        result = await bench_overlay(args.stem, work)
    result["label"] = args.label
    if args.out:
        with open(args.out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
