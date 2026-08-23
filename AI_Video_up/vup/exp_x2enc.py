"""exp_x2enc - x4 で判った「nvenc preset が SR の GPU 時間を奪う」が
x2 出力 (1440x960) でも起きるか。私の以前の x2 推奨 (p5+split3) を検証し直す。
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\sanka\AppData\Local\Temp\claude"
                   r"\C--01-work-00-Git-toybox-AI-Video-up"
                   r"\a69516b7-fb23-4024-ad85-73e2610bad30\scratchpad")
from gpulock import gpu_lock  # noqa: E402

HERE = Path(__file__).resolve().parent
PY = str(HERE / "venv/Scripts/python.exe")
SRC = HERE.parent / "サンプル.mp4"
LIMIT = 40
CFG = [
    ("p7 cq24 (現行既定)", "-preset p7 -cq 24"),
    ("p5 cq24 + split3 (私の旧推奨)", "-preset p5 -cq 24 -split_encode_mode 3"),
    ("p4 cq24", "-preset p4 -cq 24"),
    ("p4 cq24 + split3", "-preset p4 -cq 24 -split_encode_mode 3"),
    ("p7 cq24 -tune ll", "-preset p7 -cq 24 -tune ll"),
]


def run(label, ea):
    t0 = time.perf_counter()
    r = subprocess.run([PY, str(HERE / "vup.py"), str(SRC), "--model", "anime",
                        "--scale", "2", "--limit", str(LIMIT),
                        "--suffix", "_x2t", "--encoder-args", ea],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    el = time.perf_counter() - t0
    if r.returncode != 0:
        print(f"{label:32s} FAILED {r.stdout[-200:]}")
        return
    g = lambda p: (re.search(p, r.stdout) or [None, "nan"])[1]  # noqa: E731
    print(f"{label:32s} 総{el:6.1f}s  処理{g(r'処理 ([0-9.]+)s'):>6s}s  "
          f"SR {g(r'SR ([0-9.]+) fps'):>6s}fps  "
          f"pipe書込{g(r'pipe書込 ([0-9.]+)s'):>5s}s", flush=True)


if __name__ == "__main__":
    with gpu_lock("io-pipeline", "x2 encoder preset 追試", timeout=3600):
        print(f"=== x2 1440x960 (source {LIMIT}秒) ===")
        for r_ in range(2):
            print(f"-- round {r_ + 1}")
            for l_, e_ in CFG:
                run(l_, e_)
    (HERE.parent / "サンプル_x2t.mp4").unlink(missing_ok=True)
