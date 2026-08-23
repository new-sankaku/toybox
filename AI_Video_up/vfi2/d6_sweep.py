"""素材 / 素直なx2 / 時刻張り直し(48・60・120fps)を全 clip ぶん測る。

済んだ物は results.jsonl と smooth/ の cache に残るので、途中で止めても
測り直しにはならない。
"""
import sys

import lib
import smooth
import d2_x2
import d4_retime

CLIPS = list(lib.CLIPS)
TARGETS = [(lib.FPS * 2, 0.0), (lib.FPS * 2, 32.0),
           (60.0, 32.0), (120.0, 32.0)]


def main():
    for c in CLIPS:
        smooth.measure(c, c, tag=f"src/{c}")
    for c in CLIPS:
        d2_x2.run(c)
    for fps, lim in TARGETS:
        for c in CLIPS:
            lib.log(f"retime {c} {fps:.0f}fps limit={lim:g}")
            d4_retime.run(c, fps, lim)


if __name__ == "__main__":
    main()
