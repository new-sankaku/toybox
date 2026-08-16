# -*- coding: utf-8 -*-
"""targets.json の定義に従って参考画像から文字部分を切り出す。

targets.json:
[
  {"id": "adult-01", "src": "doc/reference/adult/AdultVideo1.webp",
   "box": [x, y, w, h], "text": "...", "note": "..."}
]
box は元画像のpixel座標。--id で個別実行できる。

crops/<id>.png   … 参考画像そのもの
crops/<id>.bg.png … 再現描画の下地。文字が写り込まない背景。
                    bgbox（元画像の文字が無い領域）があればそれを引き伸ばして使う。
                    無ければ crop を強くぼかして文字を消したものを使う。
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CROP_DIR = os.path.join(HERE, "crops")


def load_targets():
    """targets/*.json を全部読んで連結する。genreごとにfileを分けて衝突を避ける。"""
    d = os.path.join(HERE, "targets")
    out = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                out.extend(json.load(f))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--info", action="store_true", help="元画像の寸法だけ出す")
    args = ap.parse_args()

    targets = load_targets()
    os.makedirs(CROP_DIR, exist_ok=True)
    seen = set()
    for t in targets:
        if args.id and t["id"] not in args.id:
            continue
        src = os.path.join(ROOT, t["src"])
        if not os.path.exists(src):
            print("NG  元画像なし: %s" % src)
            sys.exit(1)
        im = Image.open(src).convert("RGB")
        if args.info:
            if t["src"] not in seen:
                seen.add(t["src"])
                print("%-52s %dx%d" % (t["src"], im.width, im.height))
            continue
        x, y, w, h = [int(v) for v in t["box"]]
        x = max(0, min(x, im.width - 1))
        y = max(0, min(y, im.height - 1))
        w = max(1, min(w, im.width - x))
        h = max(1, min(h, im.height - y))
        out = os.path.join(CROP_DIR, t["id"] + ".png")
        crop = im.crop((x, y, x + w, y + h))
        crop.save(out)

        if t.get("bgbox"):
            bx, by, bw, bh = [int(v) for v in t["bgbox"]]
            bg = im.crop((bx, by, bx + bw, by + bh)).resize((w, h), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(max(2, min(w, h) * 0.02)))
            src = "bgbox"
        else:
            bg = crop.filter(ImageFilter.GaussianBlur(max(8, min(w, h) * 0.45)))
            src = "blur"
        bg.save(os.path.join(CROP_DIR, t["id"] + ".bg.png"))
        print("OK  %-16s %dx%d  <- %s  (下地: %s)" % (t["id"], w, h, t["src"], src))


if __name__ == "__main__":
    main()
