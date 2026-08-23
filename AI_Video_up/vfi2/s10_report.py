"""doc/高速化.md の表を results.jsonl から起こす。

手で写すと数字がずれるので、表は必ずここから出す。
"""
import sys
from collections import OrderedDict

import lib

CLIPS = ["A_op", "B_talk", "C_act"]

# 1章の stage 実測から出した GPU 上の下限 (1 frame あたり ms)。
# 補間する frame: pack 0.248 + 推論 5.322 + unpack 0.183 + nv12 0.348 + D2H 0.239
# 写す frame  : nv12 0.348 + D2H 0.239
MS_MODEL, MS_COPY = 6.34, 0.587


def floor_sec(calls, planned):
    return (calls * MS_MODEL + (planned - calls) * MS_COPY) / 1000.0


def _t(head, rows):
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if x is None else str(x) for x in r) + " |")
    return "\n".join(out)


def latest(kind, key):
    """同じ key の記録が複数あれば最後の物を採る。"""
    d = OrderedDict()
    for r in lib.read_records(kind):
        d[tuple(r.get(k) for k in key)] = r
    return d


def best(kind, key, field="sec"):
    """同じ key を繰り返し測ってあれば一番速い物を採る。

    他 process の干渉は必ず「遅くする」向きにしか働かない (sgpu.canary_ms
    と同じ理屈)。平均や最後の値を採ると干渉がそのまま残る。
    """
    d = OrderedDict()
    for r in lib.read_records(kind):
        k = tuple(r.get(x) for x in key)
        if k not in d or r[field] < d[k][field]:
            d[k] = r
    return d


def samples(kind, key, field="sec"):
    d = OrderedDict()
    for r in lib.read_records(kind):
        d.setdefault(tuple(r.get(x) for x in key), []).append(r[field])
    return d


# ---------------------------------------------------------------- 3章

def gpuio():
    r = lib.read_records("gpuio")[-1]
    rows = [
        ["decode", "ffmpeg CPU + pipe + H2D (現行)", r["pipe_decode_h2d_fps"], "—"],
        ["decode", "ffmpeg NVDEC (画素は取り出さない)", r["ffmpeg_nvdec_fps"],
         "pipe で受ける口が無い"],
        ["decode", "PyNvVideoCodec (GPU 直・採用)", r["pynv_decode_fps"], "—"],
        ["decode", "対照: ffmpeg CPU decode のみ", r["ffmpeg_cpu_null_fps"], "—"],
        ["encode", "D2H + pipe + hevc_nvenc (現行)", r["pipe_encode_d2h_fps"], "—"],
        ["encode", "PyNvVideoCodec (GPU 直)", None,
         r.get("pynv_encode_error", "")],
    ]
    return _t(["stage", "手段", "fps", "備考"], rows)


def nvdec_check():
    rows = [[r["clip"], r["n"], r["psnr_min"], r["psnr_mean"], r["psnr_max"]]
            for r in lib.read_records("nvdec_check")]
    return _t(["clip", "枚", "PSNR 最小", "平均", "最大"], rows)


# ---------------------------------------------------------------- 6章

def e2e(plan, fps_kind):
    """fps_kind: 'x2' か '60'。"""
    d = best("e2e2", ("clip", "out_fps", "plan", "decode", "impl", "scale"))
    # 旧実装は s11_oldbase.py で測り直した render2 を基準にする
    # (kind="render" は GPU の空き待ちと canary を取っていない)
    old = best("render2", ("clip", "cond"))
    oldcond = "x2絵" if fps_kind == "x2" else "60絵"
    rows = []
    for c in CLIPS:
        got = {k: v for k, v in d.items()
               if k[0] == c and k[2] == plan and k[4] == "v2" and k[5] == 1.0
               # 丸めた 47.952 の記録と、ちょうど2倍の記録を混ぜない
               and (abs(k[1] - 2 * lib.FPS) < 1e-9 if fps_kind == "x2"
                    else abs(k[1] - 60.0) < 1e-9)}
        o = old.get((c, oldcond))
        pipe = next((v for k, v in got.items() if k[3] == "pipe"), None)
        nvd = next((v for k, v in got.items() if k[3] == "nvdec"), None)
        if pipe is None:
            continue
        row = [c, pipe["planned"], pipe["calls"]]
        if plan == "retime" and o is not None:
            row += [f'{o["sec"]}秒 / {o["realtime_x"]}倍']
        else:
            row += ["—"]
        row += [f'{pipe["sec"]}秒 / {pipe["realtime_x"]}倍']
        row += [f'{nvd["sec"]}秒 / {nvd["realtime_x"]}倍' if nvd else "—"]
        if plan == "retime" and o is not None and nvd is not None:
            row += [round(o["sec"] / nvd["sec"], 2)]
        else:
            row += ["—"]
        fl = floor_sec(pipe["calls"], pipe["planned"])
        row += [f'{fl:.2f}秒', round(nvd["sec"] / fl, 2) if nvd else "—"]
        row += ["OK" if pipe.get("verify_ok") and (nvd is None or nvd.get("verify_ok"))
                else "NG"]
        rows.append(row)
    return _t(["clip", "出力frame", "model呼び出し", "旧 r5_render(再測)",
               "新 pipe", "新 NVDEC", "旧比", "GPU 下限", "下限比", "検算"], rows)


def ab():
    """交互に測った新旧。巡ごとに並べる (別々の時間帯の値を並べない)。"""
    rows = []
    seen = {}
    for r in lib.read_records("ab"):
        # s12_ab.py は 1巡ずつ呼ぶので payload の round は常に 0。
        # 同じ (clip, 条件) が現れた順で数え直す
        k = (r["clip"], r["cond"])
        seen[k] = seen.get(k, 0) + 1
        rows.append([r["clip"], r["cond"], seen[k], r["calls"],
                     r["old_sec"], r["pipe_sec"], r["nvdec_sec"],
                     r["pipe_vs_old"], r["nvdec_vs_old"], r["nvdec_vs_pipe"],
                     "OK" if r["verify_ok"] else "NG"])
    return _t(["clip", "条件", "巡", "呼び出し", "旧 秒", "新pipe 秒",
               "新NVDEC 秒", "pipe/旧", "NVDEC/旧", "NVDEC/pipe", "検算"], rows)


def ab_best():
    """巡ごとの比のうち、旧が一番速かった巡を採る (新に有利な巡を選ばない)。"""
    d = OrderedDict()
    for r in lib.read_records("ab"):
        k = (r["clip"], r["cond"])
        if k not in d or r["old_sec"] < d[k]["old_sec"]:
            d[k] = r
    rows = []
    for (c, cond), r in d.items():
        rows.append([c, cond, r["calls"], r["old_sec"], r["pipe_sec"],
                     r["nvdec_sec"], r["pipe_vs_old"], r["nvdec_vs_old"],
                     r["nvdec_vs_pipe"],
                     round(len(lib.load(c)) / lib.FPS / r["nvdec_sec"], 2)])
    return _t(["clip", "条件", "呼び出し", "旧 秒", "新pipe 秒", "新NVDEC 秒",
               "pipe/旧", "NVDEC/旧", "NVDEC/pipe", "NVDEC 実時間倍"], rows)


def repeats():
    """繰り返し測った物のばらつき。表の値は最小 (干渉は遅くする向きにしか働かない)。"""
    rows = []
    for (c, cond), v in samples("render2", ("clip", "cond")).items():
        rows.append(["旧 r5_render", c, cond, len(v), min(v), max(v),
                     round(max(v) / min(v), 3)])
    for k, v in samples(
            "e2e2", ("clip", "out_fps", "plan", "decode", "impl", "scale")).items():
        c, f, pl, de, im, sc = k
        if pl != "retime" or im != "v2" or len(v) < 2:
            continue
        lab = "x2" if abs(f - 2 * lib.FPS) < 1e-9 else str(round(f))
        rows.append([f"新 {de}", c, lab, len(v), min(v), max(v),
                     round(max(v) / min(v), 3)])
    return _t(["実装", "clip", "条件", "回数", "最小 秒", "最大 秒", "幅"], rows)


def oldbase():
    """旧実装を新実装と同じ関門で測り直した結果と、最初の記録の差。"""
    a = latest("render", ("clip", "cond"))
    b = latest("render2", ("clip", "cond"))
    rows = []
    for (c, cond), v in b.items():
        o = a.get((c, cond))
        rows.append([c, cond, v["out_frames"], v["calls"],
                     o["sec"] if o else "—", v["sec"],
                     round(o["sec"] / v["sec"], 3) if o else "—",
                     v.get("canary_ms"), v.get("clean"),
                     "OK" if v.get("verify_ok") else "NG"])
    return _t(["clip", "条件", "出力frame", "呼び出し", "最初の記録 秒",
               "再測 秒", "比", "canary ms", "clean", "検算"], rows)


def e2e_detail():
    d = latest("e2e2", ("clip", "out_fps", "plan", "decode", "impl", "scale"))
    rows = []
    for (c, f, pl, de, im, sc), v in d.items():
        if pl is None:
            continue                  # plan/decode を持たない最初の試し撃ち
        rows.append([c, round(f, 6), pl, de, f"{im} s{sc}", v["planned"],
                     v["calls"], v["sec"], v["out_fps_eff"], v["realtime_x"],
                     v.get("ms_per_call"), v.get("canary_ms"), v.get("clean"),
                     "OK" if v.get("verify_ok") else "NG"])
    return _t(["clip", "目標fps", "plan", "decode", "実装", "出力frame",
               "呼び出し", "秒", "出力fps", "実時間倍", "ms/呼び出し",
               "canary ms", "clean", "検算"], rows)


def scale_e2e():
    """flow scale を端から端まで繋いだ時の実効速度 (60fps・retime・NVDEC)。"""
    d = latest("e2e2", ("clip", "out_fps", "plan", "decode", "impl", "scale"))
    q = latest("scalequal", ("model", "scale", "clip"))
    rows = []
    for s in (1.0, 0.5, 0.25):
        for c in CLIPS:
            v = d.get((c, 60.0, "retime", "nvdec", "v1", s))
            base = d.get((c, 60.0, "retime", "nvdec", "v1", 1.0))
            if v is None:
                continue
            qq = q.get(("v4.6", s, c))
            rows.append([c, s, v["calls"], v["sec"], v["realtime_x"],
                         round(base["sec"] / v["sec"], 2) if base else "—",
                         f'{qq["lpips"]:.4f}' if qq else "—",
                         f'{qq["gmsd"]:.4f}' if qq else "—",
                         "OK" if v.get("verify_ok") else "NG"])
    return _t(["clip", "scale", "呼び出し", "秒", "実時間倍", "s1.0比",
               "LPIPS", "GMSD", "検算"], rows)


# ---------------------------------------------------------------- 4章

def flowscale():
    sp = latest("flowscale", ("model", "scale"))
    q = latest("scalequal", ("model", "scale", "clip"))
    rows = []
    for (mo, s), v in sp.items():
        row = [s, v["pad"], v["infer_ms"], v["fps"], v["speedup"]]
        for c in CLIPS:
            qq = q.get((mo, s, c))
            row.append(f'{qq["lpips"]:.4f} / {qq["gmsd"]:.4f}' if qq else "—")
        rows.append(row)
    return _t(["scale", "pad", "推論 ms", "fps", "速度比"]
              + [f"{c} LPIPS/GMSD" for c in CLIPS], rows)


BIN_LABELS = ["0-4", "4-8", "8-16", "16-32", "32-64", "64-128", "128-"]


def flowscale_bins():
    q = latest("scalequal", ("model", "scale", "clip"))
    rows = []
    for (mo, s, c), v in q.items():
        rows.append([c, mo, s] + [v.get(f"lpips_b{b}", "—") for b in range(7)]
                    + [v["psnr"], v["lpips_worst"]])
    return _t(["clip", "model", "scale"] + [f"LPIPS {x}px" for x in BIN_LABELS]
              + ["PSNR(重み)", "LPIPS 最悪"], rows)


# ---------------------------------------------------------------- 4章 (帯別対照)
#
# 「scale を下げると model が扱える変位の上限が上がるか」を見る表。
# 対照の hold / blend が同じ表に無いと判断できない (model 同士で改善しても
# blend に負けたままなら、関門は動かせない)。
#
# hold / blend は m3_bench.py が測った quality2 の記録をそのまま使う。
# 試験集合 (results/testset_<clip>.npy) は scalequal と同一なので、同じ組を
# 見ている。ただし **実装は違う**: scalequal は v1実装 (rifev1)、quality2 の
# model 側は vfimodels 経由。hold と blend は実装に依存しない。

def _bin_rows(clip, field):
    """(名前, 帯ごとの値の列) を返す。対照 → v4.6 → v4.26_heavy の順。"""
    q2 = latest("quality2", ("key", "clip"))
    sq = latest("scalequal", ("model", "scale", "clip"))
    out = []
    for key, label in (("hold", "hold (何もしない)"), ("blend", "blend (単純合成)")):
        r = q2.get((key, clip))
        if r:
            out.append((label, r))
    for model in ("v4.6", "v4.26_heavy"):
        for s in (1.0, 0.5, 0.25):
            r = sq.get((model, s, clip))
            if r:
                out.append((f"RIFE {model} scale={s}", r))
    ref = q2.get(("rife426heavy_trt", clip))
    if ref:
        out.append(("参考: v4.26_heavy v2実装 (scale不可)", ref))
    return [[name] + [r.get(f"{field}_b{b}", "—") for b in range(7)]
            for name, r in out]


def bins_lpips_A_op():
    return _t(["手段"] + [f"{x}px" for x in BIN_LABELS], _bin_rows("A_op", "lpips"))


def bins_lpips_B_talk():
    return _t(["手段"] + [f"{x}px" for x in BIN_LABELS], _bin_rows("B_talk", "lpips"))


def bins_lpips_C_act():
    return _t(["手段"] + [f"{x}px" for x in BIN_LABELS], _bin_rows("C_act", "lpips"))


def bins_gmsd_A_op():
    return _t(["手段"] + [f"{x}px" for x in BIN_LABELS], _bin_rows("A_op", "gmsd"))


def bins_gmsd_B_talk():
    return _t(["手段"] + [f"{x}px" for x in BIN_LABELS], _bin_rows("B_talk", "gmsd"))


def bins_gmsd_C_act():
    return _t(["手段"] + [f"{x}px" for x in BIN_LABELS], _bin_rows("C_act", "gmsd"))


def bins_n():
    """帯ごとの組数。母数0の帯を「勝った」と読まないため。"""
    q2 = latest("quality2", ("key", "clip"))
    rows = []
    for c in CLIPS:
        r = q2.get(("hold", c))
        if r:
            rows.append([c, r["n"]] + [r.get(f"n_b{b}", 0) for b in range(7)])
    return _t(["clip", "全体"] + [f"{x}px" for x in BIN_LABELS], rows)


def wall64():
    """64px の壁が動いたか。64-128px と 128-px だけを抜き出す。"""
    rows = []
    for c in CLIPS:
        got = {r[0]: r[1:] for r in _bin_rows(c, "lpips")}
        for b, lab in ((5, "64-128"), (6, "128-")):
            vals = {n: v[b] for n, v in got.items() if v[b] != "—"}
            if not vals:
                continue
            ref = min((v for n, v in vals.items()
                       if n.startswith(("hold", "blend"))), default=None)
            best = min((v for n, v in vals.items() if n.startswith("RIFE")),
                       default=None)
            rows.append([c, f"{lab}px"]
                        + [vals.get(n, "—") for n in
                           ("hold (何もしない)", "blend (単純合成)",
                            "RIFE v4.6 scale=1.0", "RIFE v4.6 scale=0.5",
                            "RIFE v4.6 scale=0.25",
                            "RIFE v4.26_heavy scale=1.0",
                            "RIFE v4.26_heavy scale=0.5",
                            "RIFE v4.26_heavy scale=0.25")]
                        + ["model" if (best is not None and ref is not None
                                       and best < ref) else "対照"])
    return _t(["clip", "帯", "hold", "blend", "v4.6 s1.0", "v4.6 s0.5",
               "v4.6 s0.25", "heavy s1.0", "heavy s0.5", "heavy s0.25",
               "勝者"], rows)


# ---------------------------------------------------------------- 5章

def cudagraph():
    rows = [[r["model"], r["eager_gpu_ms"], r["graph_gpu_ms"], r["speedup"],
             r.get("clean"), r.get("canary_ms")]
            for r in lib.read_records("cudagraph")]
    return _t(["model", "eager GPU ms", "graph GPU ms", "速度比", "clean",
               "canary ms"], rows)


def nvenc():
    rows = [[r["at"][11:], r["encoder"], r["infer_ms"], r["ratio_vs_idle"],
             r.get("util_before")]
            for r in lib.read_records("nvenc_contention")]
    return _t(["時刻", "encoder", "推論 ms", "空き時比", "計測前 GPU%"], rows)


SECTIONS = OrderedDict([
    ("gpuio", gpuio), ("nvdec_check", nvdec_check),
    ("e2e_x2", lambda: e2e("retime", "x2")),
    ("e2e_60", lambda: e2e("retime", "60")),
    ("e2e_uni_x2", lambda: e2e("uniform", "x2")),
    ("e2e_uni_60", lambda: e2e("uniform", "60")),
    ("ab", ab), ("ab_best", ab_best),
    ("e2e_detail", e2e_detail), ("oldbase", oldbase), ("repeats", repeats),
    ("flowscale", flowscale), ("flowscale_bins", flowscale_bins),
    ("scale_e2e", scale_e2e),
    ("bins_n", bins_n), ("wall64", wall64),
    ("bins_lpips_A_op", bins_lpips_A_op),
    ("bins_lpips_B_talk", bins_lpips_B_talk),
    ("bins_lpips_C_act", bins_lpips_C_act),
    ("bins_gmsd_A_op", bins_gmsd_A_op),
    ("bins_gmsd_B_talk", bins_gmsd_B_talk),
    ("bins_gmsd_C_act", bins_gmsd_C_act),
    ("cudagraph", cudagraph), ("nvenc", nvenc),
])


if __name__ == "__main__":
    for name in (sys.argv[1:] or list(SECTIONS)):
        print(f"\n### {name}\n")
        print(SECTIONS[name]())
