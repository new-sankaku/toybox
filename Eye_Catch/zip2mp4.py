#!/usr/bin/env python3
"""PNG連番 zip を mp4 に変換する。

zip に audio.wav が入っていれば音として重ねる（--no-audio で無視）。

  python zip2mp4.py                     # cwd の *.zip をすべて変換
  python zip2mp4.py a.zip b.zip         # 指定した zip だけ
  python zip2mp4.py a.zip --fps 30 --crf 16 --outdir out
  python zip2mp4.py a.zip --codec nvenc # GPU encode
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

FPS_IN_NAME = re.compile(r"_(?:png)?(\d+)fps", re.IGNORECASE)
FRAME_NAME = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)\.png$", re.IGNORECASE)


def detect_fps(zip_path, fallback):
    m = FPS_IN_NAME.search(os.path.basename(zip_path))
    return int(m.group(1)) if m else fallback


def scan_audio(names):
    """同梱された音（生成器が入れる audio.wav）を1つだけ拾う。"""
    wavs = [n for n in names
            if n.lower().endswith(".wav") and not os.path.basename(n).startswith(".")]
    if not wavs:
        return None
    if len(wavs) > 1:
        raise SystemExit("音の file が複数あります: %s" % sorted(wavs))
    return wavs[0]


def scan_frames(names):
    frames = []
    for n in names:
        base = os.path.basename(n)
        if n.endswith("/") or base.startswith("."):
            continue
        m = FRAME_NAME.match(base)
        if m:
            frames.append((m.group("prefix"), len(m.group("num")), int(m.group("num")), n))
    if not frames:
        raise SystemExit("PNG連番が見つかりません")
    prefixes = {(f[0], f[1]) for f in frames}
    if len(prefixes) != 1:
        raise SystemExit("連番の書式が混在しています: %s" % sorted(prefixes))
    prefix, width = prefixes.pop()
    nums = sorted(f[2] for f in frames)
    if nums != list(range(nums[0], nums[0] + len(nums))):
        raise SystemExit("連番に欠番があります（%d コマ / %d〜%d）" % (len(nums), nums[0], nums[-1]))
    return prefix, width, nums[0], len(nums), [f[3] for f in frames]


def video_args(codec, crf):
    if codec == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq",
                "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    if codec == "x265":
        return ["-c:v", "libx265", "-crf", str(crf), "-preset", "slow",
                "-tag:v", "hvc1"]
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", "slow"]


def convert(zip_path, args, ffmpeg):
    fps = args.fps or detect_fps(zip_path, 60)
    outdir = args.outdir or os.path.dirname(os.path.abspath(zip_path))
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, os.path.splitext(os.path.basename(zip_path))[0] + ".mp4")
    if os.path.exists(out) and not args.force:
        print("skip (既に存在): %s" % out)
        return True

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        prefix, width, start, count, members = scan_frames(names)
        wav = None if args.no_audio else scan_audio(names)
        tmp = tempfile.mkdtemp(prefix=".zip2mp4_", dir=args.tmp or outdir)
        try:
            print("%s: %d コマ / %d fps%s -> %s" % (
                os.path.basename(zip_path), count, fps,
                " / 音あり" if wav else "", os.path.basename(out)))
            for m in members:
                with z.open(m) as src, open(os.path.join(tmp, os.path.basename(m)), "wb") as dst:
                    shutil.copyfileobj(src, dst)
            pattern = os.path.join(tmp, "%s%%0%dd.png" % (prefix, width))
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y",
                   "-framerate", str(fps), "-start_number", str(start), "-i", pattern]
            if wav:
                audio_path = os.path.join(tmp, os.path.basename(wav))
                with z.open(wav) as src, open(audio_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                cmd += ["-i", audio_path]
            cmd += video_args(args.codec, args.crf)
            cmd += ["-pix_fmt", "yuv420p",
                    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-movflags", "+faststart"]
            # -shortest は端数で1コマ削ることがあるので使わない
            cmd += ["-c:a", "aac", "-b:a", "192k"] if wav else ["-an"]
            cmd += [out]
            rc = subprocess.run(cmd).returncode
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if rc != 0:
        print("失敗: %s (ffmpeg rc=%d)" % (zip_path, rc), file=sys.stderr)
        return False

    probe = shutil.which("ffprobe")
    if probe:
        info = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_packets", "-count_packets",
             "-of", "default=nk=1:nw=1", out],
            capture_output=True, text=True)
        got = info.stdout.strip()
        if got.isdigit() and int(got) != count:
            print("失敗: コマ数が一致しません（入力 %d / 出力 %s）: %s" % (count, got, out), file=sys.stderr)
            return False

    print("  完了 %.1f MB" % (os.path.getsize(out) / 1024 / 1024))
    return True


def main():
    p = argparse.ArgumentParser(description="PNG連番 zip を mp4 に変換する")
    p.add_argument("zips", nargs="*", help="変換する zip（省略時は cwd の *.zip すべて）")
    p.add_argument("--fps", type=int, help="既定は file 名の ...60fps から判定、無ければ 60")
    p.add_argument("--crf", type=int, default=12, help="画質。小さいほど高画質（既定 12）")
    p.add_argument("--codec", choices=["x264", "x265", "nvenc"], default="x264")
    p.add_argument("--outdir", help="出力先（既定は zip と同じ folder）")
    p.add_argument("--tmp", help="展開先の親 folder（既定は出力先）")
    p.add_argument("--force", action="store_true", help="既存 mp4 を上書きする")
    p.add_argument("--no-audio", action="store_true", help="同梱の wav を無視して無音にする")
    args = p.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg が PATH にありません")

    targets = args.zips or sorted(
        os.path.join(os.getcwd(), f) for f in os.listdir(os.getcwd()) if f.lower().endswith(".zip"))
    if not targets:
        raise SystemExit("変換する zip がありません")

    ok = True
    for z in targets:
        ok = convert(z, args, ffmpeg) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
