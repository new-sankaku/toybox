"""results.jsonl から doc 用の表(markdown)を作る。計算はしない。"""
import sys

import numpy as np

import lib

BIN_LABELS = ["0-4", "4-8", "8-16", "16-32", "32-64", "64-128", "128-"]
CLIPS = ["A_op", "B_talk", "C_act"]


def _latest(kind, keyfields):
    out = {}
    for r in lib.read_records(kind):
        out[tuple(r.get(k) for k in keyfields)] = r
    return out


def table_speed():
    rows = _latest("speed2", ("key",))
    order = sorted(rows.values(), key=lambda r: r.get("gpu_ms", 1e9))
    out = ["| model | 実装 | model本体 ms | 枚/秒 | 前後処理込み ms | VRAM 山 GB |",
           "|---|---|---:|---:|---:|---:|"]
    for r in order:
        if "error" in r:
            out.append(f"| {r['model']} | - | 失敗 | - | - | - |")
            continue
        out.append(f"| {r['model']} | {r['impl']} | {r['gpu_ms']:.2f} | "
                   f"{r['gpu_fps']:.1f} | {r['e2e_ms']:.2f} | {r['vram_peak_gb']:.2f} |")
    return "\n".join(out)


def table_quality(clip):
    rows = [r for r in _latest("quality2", ("key", "clip")).values()
            if r["clip"] == clip]
    rows.sort(key=lambda r: r["lpips"])
    out = [f"| model | LPIPS | GMSD | PSNR dB | \\|d\\|>48 画素 | LPIPS最悪 |",
           "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        out.append(f"| {r['model']} | {r['lpips']:.4f} | {r['gmsd']:.4f} | "
                   f"{r['psnr']:.2f} | {r['bad']:,} | {r['lpips_worst']:.3f} |")
    return "\n".join(out)


def table_bins(clip):
    rows = [r for r in _latest("quality2", ("key", "clip")).values()
            if r["clip"] == clip]
    rows.sort(key=lambda r: r["lpips"])
    ns = [rows[0].get(f"n_b{b}") for b in range(7)] if rows else []
    head = "| model | " + " | ".join(
        f"{BIN_LABELS[b]}<br>n={ns[b]}" for b in range(7) if ns[b]) + " |"
    sep = "|---|" + "---:|" * sum(1 for n in ns if n)
    out = [head, sep]
    for r in rows:
        cells = [f"{r[f'lpips_b{b}']:.4f}" for b in range(7) if ns[b]]
        out.append(f"| {r['model']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def table_bins_all():
    """3 clip を束ねた層別 LPIPS。層ごとの実測をすべて連結して平均する。"""
    keys = {r["key"]: r["model"] for r in lib.read_records("quality2")}
    out = ["| model | " + " | ".join(BIN_LABELS) + " | 全体(重み付き) |",
           "|---|" + "---:|" * 8]
    rank = []
    for key, name in keys.items():
        arrs = []
        for c in CLIPS:
            p = lib.RESULTS / f"q2_{key}_{c}.npy"
            if p.exists():
                arrs.append(np.load(p))
        if not arrs:
            continue
        a = np.concatenate(arrs)
        w = a["weight"] / a["weight"].sum()
        cells = []
        for b in range(7):
            s = a[a["bin"] == b]
            cells.append(f"{s['lpips'].mean():.4f}" if len(s) else "-")
        tot = float((a["lpips"] * w).sum())
        rank.append((tot, name, cells))
    rank.sort()
    for tot, name, cells in rank:
        out.append(f"| {name} | " + " | ".join(cells) + f" | {tot:.4f} |")
    return "\n".join(out)


def table_bin_counts():
    a = np.concatenate([np.load(lib.RESULTS / f"testset_{c}.npy") for c in CLIPS])
    out = ["| 層 | " + " | ".join(BIN_LABELS) + " |", "|---|" + "---:|" * 7,
           "| 試験の組数 | " + " | ".join(str(int((a["bin"] == b).sum()))
                                     for b in range(7)) + " |"]
    return "\n".join(out)


def table_tau():
    rows = _latest("tau_gain", ("key", "clip"))
    sw = _latest("tau_sweep", ("key",))
    keys = sorted({k[0] for k in rows})
    out = ["| model | tau応答 max\\|y(0)-y(1)\\| | max\\|y(.25)-y(.75)\\| | "
           "clip | 真tau LPIPS | 0.5固定 LPIPS | 利得 | 勝率 | 最良tau と真tau の相関 |",
           "|---|---:|---:|---|---:|---:|---:|---:|---:|"]
    for k in keys:
        for c in CLIPS:
            r = rows.get((k, c))
            if not r:
                continue
            s = sw.get(k, {})
            out.append(f"| {r['model']} | {r['d_tau0_tau1']:.1f} | "
                       f"{r['d_tau025_tau075']:.1f} | {c} | "
                       f"{r['lpips_true_tau']:.4f} | {r['lpips_tau_half']:.4f} | "
                       f"{r['lpips_gain']:+.4f} | {r['win_rate']:.2f} | "
                       f"{s.get('corr_argmin_vs_true', '-')} |")
    return "\n".join(out)


def main():
    print("### 速度 (1920x1080, 補間1枚あたり)\n")
    print(table_speed())
    print("\n### 層ごとの LPIPS (3 clip 束ね, 跨ぎ変位 px)\n")
    print(table_bin_counts())
    print()
    print(table_bins_all())
    for c in CLIPS:
        print(f"\n### {c}\n")
        print(table_quality(c))
        print()
        print(table_bins(c))
    print("\n### 任意 tau\n")
    print(table_tau())


if __name__ == "__main__":
    main()
