"""metric を GPU で計算する。CPU 版と同じ値を返すことを検算してから使う。

1080p では CPU 版が 1枚あたり 220ms 掛かり、model の 5.7ms の 39倍だった。
評価の待ち時間のほとんどが metric の計算という状態だったので GPU へ移す。

  CPU 実測 (1920x1080, 1枚あたり)
    psnr(float64)  68.4ms / bad_pixels 70.8ms / gmsd 67.6ms / box4 13.6ms
"""
import numpy as np
import torch
import torch.nn.functional as F

_KX = None


def to_gpu(a):
    if torch.is_tensor(a):
        return a
    return torch.from_numpy(np.ascontiguousarray(a)).cuda()


def _f(a):
    """uint8 HWC(cuda) -> float32 CHW(1,3,H,W)"""
    t = to_gpu(a)
    if t.dtype != torch.float32:
        t = t.float()
    return t.permute(2, 0, 1).unsqueeze(0)


def psnr(a, b):
    x, y = _f(a), _f(b)
    mse = (x - y).pow_(2).mean()
    if float(mse) <= 0:
        return 100.0
    return float(10.0 * torch.log10(torch.tensor(255.0 ** 2, device=mse.device) / mse))


def box4_max(a, b):
    """|diff| を 4x4 box平均へ畳んでから最大。

    cv2 は uint8 の absdiff を INTER_AREA で縮小し、結果を uint8 へ丸める。
    丸めを入れないと 0.25 ずれる(実測)ので、同じ所で round する。
    """
    d = (_f(a) - _f(b)).abs_()
    return float(F.avg_pool2d(d, 4).round_().amax())


def bad_pixels(a, b, thresh=48):
    d = (_f(a) - _f(b)).abs_()
    return int((d.amax(dim=1) > thresh).sum())


def _kernels(device):
    global _KX
    if _KX is None or _KX[0].device != device:
        kx = torch.tensor([[1., 0., -1.], [1., 0., -1.], [1., 0., -1.]],
                          device=device).div_(3.0).view(1, 1, 3, 3)
        _KX = (kx, kx.transpose(2, 3).contiguous())
    return _KX


def gmsd(a, b):
    """cv2.cvtColor(BGR2GRAY) + filter2D と同じ式。"""
    x, y = _f(a), _f(b)
    # cv2.cvtColor は uint8 へ丸めるので、そこも合わせる
    w = torch.tensor([0.114, 0.587, 0.299], device=x.device).view(1, 3, 1, 1)
    ga = (x * w).sum(1, keepdim=True).round_()
    gb = (y * w).sum(1, keepdim=True).round_()
    kx, ky = _kernels(x.device)

    def grad(g):
        # cv2.filter2D は相関(correlation)で、境界は BORDER_REFLECT_101
        g = F.pad(g, (1, 1, 1, 1), mode="reflect")
        return (F.conv2d(g, kx) ** 2 + F.conv2d(g, ky) ** 2).sqrt_()

    ma, mb = grad(ga), grad(gb)
    c = 170.0
    gms = (2 * ma * mb + c) / (ma ** 2 + mb ** 2 + c)
    return float(gms.std(unbiased=False))
