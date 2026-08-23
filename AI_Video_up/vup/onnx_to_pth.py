"""SRVGGNetCompact の ONNX を torch の state_dict へ変換する

AnimeJaNai SD V1 は ONNX でしか配布されていないが、中身は SRVGGNetCompact
（realesr-animevideov3 と同一構成の x2 版）なので、重みを移せば既存の
torch fp16 + channels_last + torch.compile の経路にそのまま載る。
onnxruntime を挟むより速く、compile も効く。

使い方: python onnx_to_pth.py <in.onnx> <out.pth>
"""
import sys
from collections import OrderedDict

import numpy as np
import onnx
import torch
from onnx import numpy_helper


def convert(onnx_path, pth_path):
    model = onnx.load(onnx_path)
    inits = {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}

    sd = OrderedDict()
    prelu_idx = []
    for node in model.graph.node:
        if node.op_type == "Conv":
            w, b = node.input[1], node.input[2] if len(node.input) > 2 else None
            if not w.startswith("body."):
                raise SystemExit(f"想定外のconv重み名です: {w}")
            sd[w] = torch.from_numpy(inits[w].astype(np.float32))
            if b:
                sd[b] = torch.from_numpy(inits[b].astype(np.float32))
        elif node.op_type == "PRelu":
            prelu_idx.append(node.input[1])

    # PReLUの傾きは body.1 / body.3 / ... に入る（convは body.0 / body.2 / ...）
    conv_ids = sorted({int(k.split(".")[1]) for k in sd})
    slope_targets = [i + 1 for i in conv_ids[:-1]]
    if len(slope_targets) != len(prelu_idx):
        raise SystemExit(f"PReLUの数が合いません: conv {len(conv_ids)} / prelu {len(prelu_idx)}")
    for tgt, name in zip(slope_targets, prelu_idx):
        arr = inits[name].astype(np.float32).reshape(-1)
        sd[f"body.{tgt}.weight"] = torch.from_numpy(arr)

    last = sd[f"body.{conv_ids[-1]}.weight"].shape[0]
    scale = int(round((last / 3) ** 0.5))
    if scale * scale * 3 != last:
        raise SystemExit(f"倍率を判定できません: 最終conv出力 {last}ch")

    ordered = OrderedDict(
        sorted(sd.items(), key=lambda kv: (int(kv[0].split(".")[1]),
                                           kv[0].endswith("bias"))))
    torch.save({"params": ordered}, pth_path)
    print(f"変換しました: {pth_path}")
    print(f"  arch SRVGGNetCompact  num_feat={ordered['body.0.weight'].shape[0]}"
          f"  num_conv={len(conv_ids) - 2}  upscale=x{scale}"
          f"  param {sum(v.numel() for v in ordered.values()) / 1e6:.2f}M")
    return pth_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("使い方: python onnx_to_pth.py <in.onnx> <out.pth>")
    convert(sys.argv[1], sys.argv[2])
