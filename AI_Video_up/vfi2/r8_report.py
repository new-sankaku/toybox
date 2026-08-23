"""results.jsonl から doc の表を組み立てる。数値を手で写さないため。"""
import json
import sys

import numpy as np

import lib

CLIP_ORDER = ["A_op", "B_talk", "C_act"]
COND_ORDER = ["元", "x2素直", "x2絵", "60絵", "60均し", "120絵"]


def recs(kind):
    return lib.read_records(kind)


def last(kind, **match):
    out = [r for r in recs(kind)
           if all(r.get(k) == v for k, v in match.items())]
    return out[-1] if out else None


def table(head, rows):
    s = ["| " + " | ".join(head) + " |",
         "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        s.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(s)


def t_cadence():
    rows = []
    for c in CLIP_ORDER:
        r = last("retime_cadence", clip=c)
        if not r:
            continue
        rows.append([c, lib.CLIPS[c]["label"], r["frames"], r["drawings"],
                     r["hold_mean"], r["drawings_per_sec"], r["cut_pairs"],
                     f"{r['same_frame_pct']}%", r["mv_p50"], r["mv_p90"],
                     f"{r['mv_over64_pct']}%"])
    return table(["clip", "場面", "frame", "絵", "1枚あたりframe", "絵/秒",
                  "cut", "同じ絵の隣接pair", "絵間変位 p50 px",
                  "p90 px", "64px超"], rows)


def t_hold():
    rows = []
    for c in CLIP_ORDER:
        r = last("retime_cadence", clip=c)
        if not r:
            continue
        h = {int(k): v for k, v in r["hold_hist"].items()}
        tot = sum(h.values())
        long_n = sum(v for k, v in h.items() if k > 8)
        long_f = sum(k * v for k, v in h.items() if k > 8)
        rows.append([c, "/".join(f"{k}:{h.get(k,0)}" for k in (1, 2, 3, 4)),
                     sum(v for k, v in h.items() if 5 <= k <= 8), long_n,
                     f"{long_n/tot*100:.1f}%", long_f,
                     f"{long_f/r['frames']*100:.1f}%", r["hold_max"]])
    return table(["clip", "1/2/3/4 frame 保持の枚数", "5〜8", "9以上の枚数",
                  "同 割合", "9以上が占める frame", "同 尺の割合",
                  "最長 frame"], rows)


def t_anchor():
    rows = []
    for c in CLIP_ORDER:
        r = last("anchor", clip=c)
        if not r:
            continue
        rows.append([c, r["n"], r["n_split"],
                     f"{r['lp_head']:.5f}", f"{r['lp_center']:.5f}",
                     f"{r['lp_half']:.5f}",
                     f"{r['lp_head_split']:.5f}", f"{r['lp_center_split']:.5f}",
                     f"{r['lp_best']:.5f}"])
    return table(["clip", "3つ組", "うち head と center が割れる組",
                  "LPIPS head", "LPIPS center", "LPIPS tau=0.5 固定",
                  "割れる組だけ head", "割れる組だけ center",
                  "tau を振った最良"], rows)


def t_gate_mv():
    out = []
    for c in CLIP_ORDER:
        r = last("retime_gate", clip=c)
        if not r:
            continue
        rows = []
        for lab, v in r["by_mv"].items():
            rows.append([lab, v["n"], f"{v['model']:.5f}", f"{v['hold']:.5f}",
                         f"{v['blend']:.5f}",
                         "model" if v["model"] < min(v["hold"], v["blend"])
                         else ("hold" if v["hold"] <= v["blend"] else "blend")])
        cut = r.get("cut")
        out.append(f"**{c}**（cut を跨ぐ {r['n_cut']} 組: model "
                   f"{cut['model']:.5f} / hold {cut['hold']:.5f} / "
                   f"blend {cut['blend']:.5f}）\n\n"
                   + table(["跨ぐ変位 px", "組数", "model", "hold", "blend",
                            "勝ち"], rows))
    return "\n\n".join(out)


def t_recon():
    rows = []
    for c in CLIP_ORDER:
        b = last("recon_base", clip=c)
        if b:
            rows.append([c, "補間しない", "-", "-", "-",
                         f"{b['lpips_dropped']:.5f}", f"{b['gmsd_dropped']:.5f}",
                         f"{b['lpips_all']:.5f}", "-", "-"])
        for r in recs("recon"):
            if r["clip"] != c:
                continue
            rows.append([c, "張り直し", r["anchor"],
                         "なし" if r["mv_gate"] is None else f"{r['mv_gate']:g}px",
                         "する" if r["even"] else "しない",
                         f"{r['lpips_dropped']:.5f}", f"{r['gmsd_dropped']:.5f}",
                         f"{r['lpips_all']:.5f}",
                         r["calls"], f"{r['block_pct']}%"])
    return table(["clip", "処理", "代表時刻", "変位の関門", "コマ打ちを均す",
                  "落とした絵 LPIPS", "同 GMSD", "全出力 LPIPS", "model呼び出し",
                  "封じた pair"], rows)


def sched_stats(clip, cond):
    """schedule 側の数値はその場で組み直す(記録より新しい定義を使うため)。"""
    import r5_render as R5
    import retime
    if R5.CONDS[cond]["mode"] == "orig":
        n = len(lib.load(clip))
        runs = lib.drawing_runs(clip)
        return dict(out_frames=n, calls=0,
                    distinct_per_sec=round(len(runs) / (n / lib.FPS), 2),
                    dup_pct=round((n - len(runs)) / n * 100, 1))
    sch, _, fps_out = R5.schedule_for(clip, R5.CONDS[cond])
    st = retime.stats(sch, len(lib.load(clip)) / lib.FPS,
                      R5.ident_for(clip, R5.CONDS[cond]))
    return st


def t_render():
    rows = []
    for c in CLIP_ORDER:
        for cond in COND_ORDER:
            r = last("render", clip=c, cond=cond)
            if not r:
                continue
            st = sched_stats(c, cond)
            s = last("smooth", tag=f"retime/{c}/{cond}")
            rows.append([c, cond, r["fps_out"], r["out_frames"], r["calls"],
                         st["distinct_per_sec"], f"{st['dup_pct']}%",
                         s["drawing_rate"] if s else "-",
                         f"{100-s['new_pct']:.1f}%" if s else "-",
                         f"{s['lag_px']:.2f}" if s else "-",
                         f"{s['step_px']:.2f}" if s else "-",
                         r["sec"], r.get("realtime_x", "-")])
    return table(["clip", "条件", "出力fps", "出力frame", "model呼び出し",
                  "異なる絵/秒(schedule)", "複製の割合(schedule)",
                  "異なる絵/秒(実測)", "複製の割合(実測)",
                  "lag px", "step px", "処理 秒", "実時間比"], rows)


def t_block():
    """本番 schedule で関門がどれだけ発火したか。"""
    import r1_cadence as R1
    import r5_render as R5
    rows = []
    for c in CLIP_ORDER:
        p = R1.pairs(c)
        gap = p["gap"]
        cut = p["cut"]
        mv = p["mv"]
        hold = (~cut) & (gap > R5.HOLD_MAX)
        big = (~cut) & (gap <= R5.HOLD_MAX) & (mv > R5.MV_GATE)
        blk = cut | (gap > R5.HOLD_MAX) | (mv > R5.MV_GATE)
        n = len(p)
        frames = len(lib.load(c))
        # その pair が覆う出力時間の割合
        cov = lambda m: float(gap[m].sum()) / frames * 100
        rows.append([c, n, f"{cut.sum()} ({cut.mean()*100:.1f}%)",
                     f"{hold.sum()} ({hold.mean()*100:.1f}%)",
                     f"{big.sum()} ({big.mean()*100:.1f}%)",
                     f"{blk.sum()} ({blk.mean()*100:.1f}%)",
                     f"{cov(blk):.1f}%"])
    return table(["clip", "絵の pair", "cut", "意図的な静止(9 frame 以上)",
                  "大変位(64px 超)", "封じた pair 計", "封じた pair が占める尺"],
                 rows)


SECTIONS = dict(cadence=t_cadence, hold=t_hold, anchor=t_anchor,
                gate=t_gate_mv, recon=t_recon, render=t_render, block=t_block)

if __name__ == "__main__":
    for name in (sys.argv[1:] or list(SECTIONS)):
        print(f"\n## {name}\n")
        print(SECTIONS[name]())
