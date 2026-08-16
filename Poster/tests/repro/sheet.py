# -*- coding: utf-8 -*-
"""参考画像の切り出しと再現描画を並べて比較画像にする。

  python tests/repro/sheet.py            # 全件 -> compare/<id>.png と compare/_sheet.png
  python tests/repro/sheet.py --id x     # 個別
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CROP_DIR = os.path.join(HERE, "crops")
OUT_DIR = os.path.join(HERE, "out")
CMP_DIR = os.path.join(HERE, "compare")

BG = (26, 26, 28)
FG = (236, 236, 232)
DIM = (150, 150, 150)
PAD = 14
LABEL_H = 26
TITLE_H = 30
FONT_PATH = "C:/Windows/Fonts/meiryo.ttc"


def font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def load_targets():
    d = os.path.join(HERE, "targets")
    out = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                out.extend(json.load(f))
    return out


def pair_image(t, max_w=760):
    ref_p = os.path.join(CROP_DIR, t["id"] + ".png")
    rep_p = os.path.join(OUT_DIR, t["id"] + ".png")
    if not (os.path.exists(ref_p) and os.path.exists(rep_p)):
        return None
    ref = Image.open(ref_p).convert("RGB")
    rep = Image.open(rep_p).convert("RGB")
    if rep.size != ref.size:
        rep = rep.resize(ref.size, Image.LANCZOS)
    k = min(1.0, max_w / float(ref.width))
    if k < 1.0:
        size = (int(ref.width * k), int(ref.height * k))
        ref = ref.resize(size, Image.LANCZOS)
        rep = rep.resize(size, Image.LANCZOS)

    w = ref.width * 2 + PAD * 3
    h = TITLE_H + LABEL_H + ref.height + PAD * 2
    im = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(im)
    d.text((PAD, 6), "%s  /  %s" % (t["id"], t.get("note", "")), font=font(15), fill=FG)
    d.text((PAD, TITLE_H + 4), "参考画像", font=font(14), fill=DIM)
    d.text((PAD * 2 + ref.width, TITLE_H + 4), "再現", font=font(14), fill=DIM)
    y = TITLE_H + LABEL_H
    im.paste(ref, (PAD, y))
    im.paste(rep, (PAD * 2 + ref.width, y))
    d.rectangle([PAD - 1, y - 1, PAD + ref.width, y + ref.height], outline=(70, 70, 74))
    d.rectangle([PAD * 2 + ref.width - 1, y - 1, PAD * 2 + ref.width * 2, y + ref.height], outline=(70, 70, 74))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--out", default=os.path.join(CMP_DIR, "_sheet.png"))
    args = ap.parse_args()

    os.makedirs(CMP_DIR, exist_ok=True)
    tiles = []
    for t in load_targets():
        if args.id and t["id"] not in args.id:
            continue
        im = pair_image(t)
        if im is None:
            print("skip %s (画像不足)" % t["id"])
            continue
        im.save(os.path.join(CMP_DIR, t["id"] + ".png"))
        print("OK  %s" % t["id"])
        tiles.append(im)

    if not tiles:
        return
    w = max(t.width for t in tiles)
    h = sum(t.height for t in tiles) + PAD * (len(tiles) + 1)
    sheet = Image.new("RGB", (w, h), (16, 16, 18))
    y = PAD
    for t in tiles:
        sheet.paste(t, (0, y))
        y += t.height + PAD
    sheet.save(args.out)
    print("sheet -> %s (%dx%d)" % (args.out, sheet.width, sheet.height))


if __name__ == "__main__":
    main()
