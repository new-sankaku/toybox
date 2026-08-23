"""m3_bench.py を model ごとに別 process で回す。

同じ process へ2つ載せると repo 同士の package 名が衝突するため。
落ちた model は記録に error として残し、次へ進む。
"""
import subprocess
import sys

import lib

ORDER = ["hold", "blend",
         "rife426heavy_trt", "rife425lite_trt", "rife426heavy_t",
         "ifrnet_gopro", "film", "emavfi_t", "emavfi_small_t",
         "gmfss_fortuna_b", "gmfss_union", "gimmvfi_r_p", "gimmvfi_f_p"]


def main(keys):
    for k in keys:
        p = subprocess.run([sys.executable, "m3_bench.py", k],
                           cwd=str(lib.ROOT))
        if p.returncode != 0:
            lib.record("speed2", dict(key=k, model=k,
                                      error=f"m3_bench.py が rc={p.returncode} で落ちました"))
            lib.log(f"{k}: 失敗 rc={p.returncode}")


if __name__ == "__main__":
    main(sys.argv[1:] or ORDER)
