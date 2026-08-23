"""results.jsonl から markdown の表を組み立てる。手で数字を写さない。"""
import numpy as np

import vfilib as V

OUT = V.ROOT.parent / "doc" / "フレーム補完_計測結果.md"


def tbl(rows, cols, heads=None):
    heads = heads or cols
    out = ["| " + " | ".join(heads) + " |",
           "|" + "|".join("---" for _ in heads) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def section_speed():
    rows = [r for r in V.read_records("speed") if "error" not in r]
    rows.sort(key=lambda r: r["gpu_ms"])
    for r in rows:
        r["model_"] = f"`{r['model']}`"
        r["gpu"] = f"{r['gpu_ms']:.2f}"
        r["fps"] = f"**{r['gpu_fps']:.1f}**"
        r["e2e"] = f"{r['e2e_fps']:.1f}"
    for r in rows:
        r["e2ems"] = f"{r['e2e_ms']:.2f}"
    return tbl(rows, ["model_", "gpu", "e2ems"],
               ["model", "補間1枚 ms (engineのみ)", "補間1枚 ms (前後処理込み)"])


def section_quality(clip):
    base = {r["model"]: r for r in V.read_records("baseline") if r["clip"] == clip}
    q = [r for r in V.read_records("quality") if r["clip"] == clip]
    speed = {r["model"]: r for r in V.read_records("speed") if "error" not in r}
    speed.update({r["model"]: r for r in V.read_records("speed_other")})
    rows = []
    for name in ("hold", "blend"):
        if name in base:
            r = dict(base[name])
            r["model_"] = f"({name})"
            r["fps_"] = "—"
            rows.append(r)
    for r in sorted(q, key=lambda x: x["lpips"]):
        r = dict(r)
        r["model_"] = f"`{r['model']}`"
        r["fps_"] = f"{speed[r['model']]['gpu_fps']:.0f}" if r["model"] in speed else "—"
        rows.append(r)
    for r in rows:
        r["psnr_"] = f"{r['psnr']:.2f}"
        r["lpips_"] = f"{r['lpips']:.4f}"
        r["gmsd_"] = f"{r['gmsd']:.4f}"
        for t in (0, 1, 2):
            r[f"l{t}"] = f"{r.get(f'lpips_t{t}', 0):.4f}"
    return tbl(rows, ["model_", "fps_", "psnr_", "lpips_", "l0", "l1", "l2", "gmsd_"],
               ["model", "fps", "PSNR", "LPIPS", "LPIPS 小", "LPIPS 中",
                "LPIPS 大", "GMSD"])


def section_lpips_vs_motion(clip, models):
    """跨ぎ幅で刻んだ LPIPS。x2 本番の変位に読み替えるための表。"""
    bins = [0, 4, 8, 16, 32, 64, 128, 10 ** 9]
    names = ["0-4", "4-8", "8-16", "16-32", "32-64", "64-128", "128-"]
    span = np.load(V.RESULTS / f"spanmv_{clip}.npy")
    rows = []
    for name in models:
        p = V.RESULTS / f"q_{name}_{clip}.npy"
        if not p.exists():
            continue
        arr = np.load(p).copy()
        arr["mv"] = span
        r = {"model_": f"`{name}`" if name not in ("hold", "blend") else f"({name})"}
        for k in range(len(names)):
            s = arr[(arr["mv"] >= bins[k]) & (arr["mv"] < bins[k + 1])]
            r[names[k]] = f"{s['lpips'].mean():.4f}({len(s)})" if len(s) else "-"
        rows.append(r)
    return tbl(rows, ["model_"] + names, ["model"] + [f"{n} px" for n in names])


def section_gate():
    out = []
    for r in V.read_records("gate_count"):
        out.append(f"\n**{r['clip']}** (出力 {r['out_frames']} frame / "
                   f"補間対象 {r['frames']-1} / cut {r['cuts']})\n")
        rows = [dict(t=x["thresh"], c=x["calls"],
                     p=f"{x['call_pct_of_out']}%", s=x["skip_static"],
                     u=f"{x['speedup_vs_nogate']}倍") for x in r["rows"]]
        out.append(tbl(rows, ["t", "c", "p", "s", "u"],
                       ["box4 閾値", "model を呼ぶ回数", "出力frameに対する割合",
                        "静止で省いた数", "省かない場合との比"]))
    err = V.read_records("gate_error")
    if err:
        out.append("\n省いた組で「model を呼んだ絵」と「写した絵」の差:\n")
        rows = [dict(clip=r["clip"], t=r["thresh"], n=r["n"],
                     b=f"{r['box4_med']} / {r['box4_max']}",
                     x=f"{r['bad_med']} / {r['bad_max']}",
                     p=f"{r['psnr_min']:.1f}") for r in err]
        out.append(tbl(rows, ["clip", "t", "n", "b", "x", "p"],
                       ["素材", "閾値", "組数", "box4 中央/最大",
                        "\|d\|>48画素 中央/最大", "PSNR 最小"]))
    return "\n".join(out)


def section_encoder():
    rows = [r for r in V.read_records("encoder") if "error" not in r]
    for r in rows:
        r["res"] = f"{r['w']}x{r['h']}"
        r["fps_"] = f"**{r['fps']:.1f}**"
    return tbl(rows, ["res", "case", "fps_"], ["解像度", "条件", "fps"])


def section_scale():
    rows = [r for r in V.read_records("scale") if "error" not in r]
    for r in rows:
        r["res"] = f"{r['w']}x{r['h']}"
        r["ms"] = f"{r['ms_per_frame']:.2f}"
        r["fps_"] = f"{r['fps']:.1f}"
        r["mpx"] = f"{r['ms_per_mpx']:.2f}"
    return tbl(rows, ["res", "bs", "ms", "mpx"],
               ["解像度", "batch", "補間1枚 ms", "ms/Mpx"])


def section_cadence():
    rows = []
    for r in V.read_records("cadence"):
        clip = r["clip"]
        # 同じ clip の記録が複数ある場合は最後(=現在の作り方)を採る
        ts = [x for x in V.read_records("testset") if x["clip"] == clip]
        t = ts[-1] if ts else {}
        cu = [x for x in V.read_records("cuts") if x["clip"] == clip]
        cad = np.load(V.RESULTS / f"cadence_{clip}.npy")
        scd = np.load(V.RESULTS / f"scd_{clip}.npy")
        mv = cad["mv_p95"][scd[:len(cad)] < 10.0]
        rows.append(dict(clip=clip, f=r["frames"],
                         d=t.get("drawings", ""),
                         fd=t.get("frames_per_drawing", ""),
                         c=cu[-1]["n_cut"] if cu else "",
                         st=f"{t.get('static_pct','')}%",
                         mv=f"{np.median(mv):.1f}",
                         mv9=f"{np.percentile(mv, 90):.1f}"))
    return tbl(rows, ["clip", "f", "d", "fd", "c", "st", "mv", "mv9"],
               ["素材", "frame", "絵の枚数", "1枚あたりframe", "cut",
                "静止pairの割合", "隣接変位 中央(px)", "同 p90(px)"])


def section_prec():
    rows = [dict(m=f"`{r['model']}`", clip=r["clip"], p=r["prec"],
                 ms=f"{r['gpu_ms']:.2f}",
                 psnr=f"{r['psnr']:.3f}", lpips=f"{r['lpips']:.5f}")
            for r in V.read_records("precision")]
    out = [tbl(rows, ["m", "clip", "p", "ms", "psnr", "lpips"],
               ["model", "素材", "精度", "補間1枚 ms", "PSNR", "LPIPS"])]
    d = V.read_records("precision_diff")
    if d:
        out.append("\nfp16 と fp32 の出力を直接ぶつけた差:\n")
        out.append(tbl([dict(m=f"`{r['model']}`", clip=r["clip"], n=r["n"],
                             p=f"{r['psnr_med']:.1f} / {r['psnr_min']:.1f}",
                             b=f"{r['box4_med']} / {r['box4_max']}",
                             x=f"{r['bad_med']} / {r['bad_max']}") for r in d],
                       ["m", "clip", "n", "p", "b", "x"],
                       ["model", "素材", "組数", "PSNR 中央/最小",
                        "box4 中央/最大", "\|d\|>48画素 中央/最大"]))
    return "\n".join(out)


def section_e2e(after_fix=True):
    """pipe読みの bufsize を直す前の測定は捨てる(素材ではなく実装の数字)。"""
    rs = [r for r in V.read_records("e2e")
          if (r["sec"] < 20) == after_fix]
    rows = [dict(src=r["src"].split("/")[-1].split("\\")[-1].replace(".mkv", ""),
                 m=r["model"], n=r["out_frames"],
                 c=r["calls"], s=r["skip_static"], k=r["skip_cut"],
                 t=f"{r['sec']:.1f}", f=f"**{r['out_fps']:.1f}**",
                 x=f"{r['out_fps']/47.952:.1f}倍")
            for r in rs]
    return tbl(rows, ["src", "m", "n", "c", "s", "k", "t", "f", "x"],
               ["素材", "model", "出力frame", "model呼び出し",
                "静止で省略", "cutで省略", "秒", "出力fps", "実時間比"])


def section_other():
    """RIFE 以外。速度は torch(TensorRT に載せていない)ことを明記する。"""
    rows = []
    for r in V.read_records("speed_other"):
        q = {x["clip"]: x for x in V.read_records("quality")
             if x["model"] == r["model"]}
        for clip, x in q.items():
            rows.append(dict(m=f"`{r['model']}`", impl=r["impl"],
                             ms=f"{r['gpu_ms']:.1f}", fps=f"{r['gpu_fps']:.1f}",
                             re=(f"{r['reuse_ms']:.1f}" if r.get("reuse_ms")
                                 else "—"), clip=clip,
                             l=f"{x['lpips']:.4f}", g=f"{x['gmsd']:.4f}"))
    return tbl(rows, ["m", "impl", "ms", "re", "clip", "l", "g"],
               ["model", "実装", "補間1枚 ms (前後処理込み)",
                "flow使い回し時 ms", "素材", "LPIPS", "GMSD"])


def section_capacity():
    rows = [dict(clip=r["clip"], n=r["positions"],
                 fz=f"{r['frozen']} ({r['frozen_pct']}%)", mv=r["movable"],
                 p=f"{r['ratio_p10']} / {r['ratio_p50']} / {r['ratio_p90']}",
                 sm=f"{r['src_med']:,}", om=f"{r['out_med']:,}")
            for r in V.read_records("capacity")]
    return tbl(rows, ["clip", "n", "fz", "mv", "p", "sm", "om"],
               ["素材", "補間位置(cut除く)", "元の2枚が同じ絵",
                "動かせる位置", "動かした割合 p10/中央/p90 (%)",
                "元の違う画素 中央", "動かした画素 中央"])


def section_diffreport():
    out = []
    for r in V.read_records("diffreport"):
        out.append("")
        out.append("**{}** — 補間位置 {} 箇所（うち cut {}）".format(
            r["clip"], r["pairs"], r["cuts"]))
        out.append("")
        rows = [dict(s=x["src_box4"], n=x["n"], p="{}%".format(x["pct"]),
                     ob=x["out_box4_med"], bm="{:,}".format(x["out_bad_med"]),
                     b9="{:,}".format(x["out_bad_p90"]), v=x["visible"])
                for x in r["rows"]]
        out.append(tbl(rows, ["s", "n", "p", "ob", "bm", "b9", "v"],
                       ["元の2枚の差 box4", "箇所", "割合",
                        "補間と複製の差 box4 中央", "\|d\|>48画素 中央",
                        "同 p90", "目に見える枚数"]))
        out.append("")
        out.append("目に見える差（\|d\|>48 が1万画素超）: **{} / {} ({}%)**".format(
            r["visible_total"], r["pairs"], r["visible_pct"]))
    return chr(10).join(out)



def section_pipe():
    rows = [dict(res=f"{r['w']}x{r['h']}", case=r["case"],
                 fps=f"**{r['fps']:.1f}**", mb=f"{r['mbps']:.0f}")
            for r in V.read_records("pipe_read")]
    return tbl(rows, ["res", "case", "fps", "mb"],
               ["解像度", "読み方", "fps", "MB/s"])


def section_scale05():
    rows = []
    for r in V.read_records("scale05"):
        if "error" in r:
            continue
        rows.append(dict(s=r["scale"], pad=r["pad"], clip=r["clip"],
                         ms=f"{r['gpu_ms']:.2f}", fps=f"{r['gpu_fps']:.1f}",
                         l=f"{r['lpips']:.5f}",
                         l2=f"{r.get('lpips_t2', 0):.5f}"))
    seen = set()
    out = []
    for r in rows:                      # 同じ条件の重複は最後の1件だけ残す
        k = (r["s"], r["clip"])
        if k in seen:
            out = [x for x in out if (x["s"], x["clip"]) != k]
        seen.add(k)
        out.append(r)
    return tbl(out, ["s", "pad", "clip", "ms", "l", "l2"],
               ["scale", "pad", "素材", "補間1枚 ms", "LPIPS", "LPIPS 大"])


if __name__ == "__main__":
    print(section_speed())
