"""接続の確認。engineが本当に正しく繋がっているかを、絵で検算する。

tau=0 なら frame0、tau=1 なら frame1 とほぼ一致するはず。channel順・crop位置・
正規化のどれを間違えてもここで落ちる。数値だけ見て先へ進まない。
"""
import sys

import cv2
import numpy as np
import torch

import rifelib as R
import vfilib as V

NAME = sys.argv[1] if len(sys.argv) > 1 else "v4.26"
W, H = (int(x) for x in (sys.argv[2].split("x") if len(sys.argv) > 2
                         else "640x360".split("x")))
FP16 = (sys.argv[3] != "fp32") if len(sys.argv) > 3 else True

a = V.load("B_talk")
# 実際に動いている pair を選ぶ
cad = np.load(V.RESULTS / "cadence_B_talk.npy")
i = int(cad["i"][np.argsort(cad["box4"])[-30]])
V.log(f"pair i={i} box4={cad['box4'][cad['i']==i][0]}")

f0 = cv2.resize(a[i], (W, H), interpolation=cv2.INTER_AREA)
f1 = cv2.resize(a[i + 1], (W, H), interpolation=cv2.INTER_AREA)
g0, g1 = R.to_gpu(f0), R.to_gpu(f1)

m = R.Rife(NAME, W, H, fp16=FP16)
V.log(f"engine out_shape={m.out_shape}  dtype={m.dtype}")

outs = {}
for tau in (0.0, 0.5, 1.0):
    R.pack(g0, g1, tau, m.dtype, out=m.dev_in)
    y = R.unpack(m.infer()).cpu().numpy()
    outs[tau] = y
    print(f"  tau={tau}: PSNR vs f0={V.psnr(y, f0):6.2f}  vs f1={V.psnr(y, f1):6.2f}")

sheet = np.vstack([np.hstack([f0, outs[0.0], outs[0.5]]),
                   np.hstack([f1, outs[1.0], cv2.addWeighted(f0, .5, f1, .5, 0)])])
cv2.imwrite(str(V.RESULTS / f"probe_{NAME}_{'fp16' if FP16 else 'fp32'}.png"), sheet)
V.log("上段 左:f0 中:tau=0 右:tau=0.5 / 下段 左:f1 中:tau=1 右:単純平均")
