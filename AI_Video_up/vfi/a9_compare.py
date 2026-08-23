"""品質を目で確かめるための出力を作る。数字ではなく絵と動画を出す。

作る物 (すべて out/ へ):
  1. <素材>_x2_<model>.mp4        …… 等倍。そのまま再生して滑らかさを見る
  2. <素材>_比較_4分の1速.mp4      …… 左=元(補間なし) 右=x2。1/4速で並べる
  3. <素材>_model比較_4分の1速.mp4 …… 元 / 速い / 良い / 重い を2x2で並べる
  4. <素材>_静止比較_<場面>.png    …… 同じ瞬間を横に並べた原寸の切り出し

1/4速にするのは、47.952fps のままだと人の目では差が判らないため。
左の「元」は frame を複製して尺を合わせるので、**補間しない場合そのもの**が映る。
"""
import shutil
import subprocess
import sys

import numpy as np

import vfilib as V

OUT = V.ROOT / "out"
OUT.mkdir(exist_ok=True)
FPS = "48000/1001"
SLOW = 4          # 1/4 速
# Windows の ffmpeg は fontconfig を持たないので font file を直に指す。
# drive letter を書くと filter の option 区切りの ':' と衝突して
# 「No option name near ...」で落ちるので、drive を省いた形にする。
LABEL_FONT = ("fontfile=/Windows/Fonts/arial.ttf:fontsize=34:fontcolor=white"
              ":box=1:boxcolor=black@0.6:boxborderw=8")


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])


def pick_window(clip, lo, hi, seconds=6.0, by="flow"):
    """窓を選ぶ。

    by="flow"  隣接変位の中央値が [lo, hi) に入る、一番動いている窓
    by="count" 絵の変わる回数が一番多い窓(限定animationはflowの中央値が0になる)
    """
    cad = np.load(V.RESULTS / f"cadence_{clip}.npy")
    scd = np.load(V.RESULTS / f"scd_{clip}.npy")
    n = int(round(seconds * V.FPS_NUM / V.FPS_DEN))
    best, best_i = -1, None
    for i in range(0, len(cad) - n, 4):
        if (scd[i:i + n] >= 10.0).sum() > max(2, n // 4):   # cut だらけの窓は避ける
            continue
        if by == "count":
            score = float((cad["box4"][i:i + n] >= 16).sum())
        else:
            med = float(np.median(cad["mv_p95"][i:i + n]))
            if not (lo <= med < hi):
                continue
            score = med
        if score > best:
            best, best_i = score, i
    if best_i is None:
        return None, None
    return best_i, best


def label(text):
    return f"drawtext=text='{text}':{LABEL_FONT}:x=16:y=16"


def side_by_side(clip, model, start_f, seconds, tag):
    """左=元(補間なし) 右=x2。どちらも 1/4速。"""
    src = V.WORK / f"{clip}.mkv"
    x2 = V.WORK / f"{clip}_x2_{model}.mp4"
    ss = start_f * V.FPS_DEN / V.FPS_NUM
    dst = OUT / f"{clip}_比較_4分の1速_{tag}.mp4"
    run(["ffmpeg", "-v", "error", "-y",
         "-ss", f"{ss:.3f}", "-t", f"{seconds}", "-i", str(src),
         "-ss", f"{ss:.3f}", "-t", f"{seconds}", "-i", str(x2),
         "-filter_complex",
         f"[0:v]setpts={SLOW}*PTS,fps={FPS},{label('moto 23.976fps (hokan nashi)')}[l];"
         f"[1:v]setpts={SLOW}*PTS,fps={FPS},{label('x2 47.952fps ' + model)}[r];"
         f"[l][r]hstack=inputs=2,scale=1920:-2[v]",
         "-map", "[v]", "-r", FPS, "-c:v", "hevc_nvenc", "-preset", "p4",
         "-cq", "22", "-pix_fmt", "yuv420p", str(dst)])
    return dst


def grid4(clip, models, start_f, seconds, tag):
    """元 + model 3つを 2x2 で。1/4速。"""
    src = V.WORK / f"{clip}.mkv"
    ss = start_f * V.FPS_DEN / V.FPS_NUM
    ins = ["-ss", f"{ss:.3f}", "-t", f"{seconds}", "-i", str(src)]
    for m in models:
        ins += ["-ss", f"{ss:.3f}", "-t", f"{seconds}", "-i",
                str(V.WORK / f"{clip}_x2_{m}.mp4")]
    names = ["moto (hokan nashi)"] + models
    fc = []
    for i, nm in enumerate(names):
        fc.append(f"[{i}:v]setpts={SLOW}*PTS,fps={FPS},scale=960:-2,"
                  f"{label(nm)}[v{i}]")
    fc.append("[v0][v1]hstack=inputs=2[top];[v2][v3]hstack=inputs=2[bot];"
              "[top][bot]vstack=inputs=2[v]")
    dst = OUT / f"{clip}_model比較_4分の1速_{tag}.mp4"
    run(["ffmpeg", "-v", "error", "-y"] + ins
        + ["-filter_complex", ";".join(fc), "-map", "[v]", "-r", FPS,
           "-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "22",
           "-pix_fmt", "yuv420p", str(dst)])
    return dst


def stills(clip, models, start_f, tag, n=4):
    """同じ補間frameを、元の前後と一緒に原寸で並べる。"""
    import cv2
    a = V.load(clip)
    imgs = {}
    # x2 出力の frame 番号は 偶数=source そのまま / **奇数=補間**。
    # ここを間違えると source を並べて「崩れていない」と誤読する
    lo, hi = start_f * 2 + 1, start_f * 2 + 2 * n - 1
    for m in models:
        p = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(V.WORK / f"{clip}_x2_{m}.mp4"),
             "-vf", f"select='between(n\\,{lo}\\,{hi})*mod(n\\,2)'",
             "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-"], capture_output=True)
        imgs[m] = np.frombuffer(p.stdout, np.uint8).reshape(-1, V.H, V.W, 3)
    n = min([n] + [len(imgs[m]) for m in models])
    rows = []
    C = 420
    for k in range(n):
        i = start_f + k
        d = cv2.absdiff(a[i], a[i + 1]).max(axis=2)
        d = cv2.boxFilter(d.astype(np.float32), -1, (121, 121))
        _, _, _, mx = cv2.minMaxLoc(d)
        x = int(np.clip(mx[0] - C // 2, 0, V.W - C))
        y = int(np.clip(mx[1] - C // 2, 0, V.H - C))
        tiles = [(f"moto {i}", a[i]), (f"moto {i+1}", a[i + 1])]
        for m in models:
            if k < len(imgs[m]):
                tiles.append((f"{m} (kan)", imgs[m][k]))
        out = []
        for nm, im in tiles:
            t = im[y:y + C, x:x + C].copy()
            cv2.rectangle(t, (0, 0), (C, 26), (0, 0, 0), -1)
            cv2.putText(t, nm, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 255, 255) if nm.startswith("moto") else (0, 190, 255),
                        1, cv2.LINE_AA)
            out.append(t)
        rows.append(np.hstack(out))
    p = OUT / f"{clip}_静止比較_{tag}.png"
    # cv2.imwrite は非ASCIIのpathに書けない(黙って False を返す)
    ok, buf = cv2.imencode(".png", np.vstack(rows))
    if not ok:
        raise RuntimeError("png の encode に失敗しました")
    p.write_bytes(buf.tobytes())
    return p


MODELS = ["v4.6", "v4.25_lite", "v4.26_heavy"]

if __name__ == "__main__":
    made = []
    # 等倍の出力をそのまま置く
    for clip in ("B_talk", "A_op"):
        for m in MODELS:
            src = V.WORK / f"{clip}_x2_{m}.mp4"
            if src.exists():
                dst = OUT / f"{clip}_x2_{m}_等倍.mp4"
                shutil.copy(src, dst)
                made.append(dst)
        shutil.copy(V.WORK / f"{clip}.mkv", OUT / f"{clip}_元.mkv")

    # 素材ごとに、補間が効く窓と効かない窓を選ぶ
    plan = [("B_talk", 0, 1e9, "動く所", "count", 6.0),
            ("A_op", 8, 32, "変位小", "flow", 6.0),
            ("A_op", 64, 1e9, "変位大", "flow", 3.0)]
    for clip, lo, hi, tag, by, secs in plan:
        i, med = pick_window(clip, lo, hi, secs, by)
        if i is None:
            V.log(f"  {clip} {tag}: 条件に合う窓がありません")
            continue
        V.log(f"  {clip} {tag}: frame {i} から{secs}秒 "
              f"({'絵の変化 ' + str(int(med)) + '回' if by == 'count' else '隣接変位 中央 ' + format(med, '.1f') + 'px'})")
        made.append(side_by_side(clip, "v4.6", i, secs, tag))
        made.append(grid4(clip, MODELS, i, secs, tag))
        made.append(stills(clip, MODELS, i + 10, tag))
        V.record("compare", dict(clip=clip, tag=tag, start_frame=int(i),
                                 mv_median=round(float(med), 1), seconds=secs))
    for p in made:
        V.log(f"  {p.relative_to(V.ROOT)}  {p.stat().st_size/1e6:.1f} MB")
