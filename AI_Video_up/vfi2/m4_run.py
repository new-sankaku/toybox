"""m4_tau.py を model ごとに別 process で回す。"""
import subprocess
import sys

import lib

ORDER = ["rife426heavy_trt", "rife425lite_trt", "film", "emavfi_t",
         "gmfss_fortuna_b", "gmfss_union", "gimmvfi_r_p", "ifrnet_gopro",
         "blend"]


def main(keys):
    done = {r["key"] for r in lib.read_records("tau_sweep")}
    for k in keys:
        if k in done:
            lib.log(f"{k}: 済み")
            continue
        p = subprocess.run([sys.executable, "m4_tau.py", k], cwd=str(lib.ROOT))
        if p.returncode != 0:
            lib.record("tau_gain", dict(key=k, model=k,
                                        error=f"m4_tau.py が rc={p.returncode} で落ちました"))
            lib.log(f"{k}: 失敗 rc={p.returncode}")


if __name__ == "__main__":
    main(sys.argv[1:] or ORDER)
