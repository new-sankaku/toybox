import torch, torch.nn as nn, torch.nn.functional as F

class SRVGGNetCompact(nn.Module):
    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=16, upscale=4):
        super().__init__()
        self.upscale = upscale
        body = [nn.Conv2d(num_in_ch, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        for _ in range(num_conv):
            body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
            body.append(nn.PReLU(num_parameters=num_feat))
        body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
        self.body = nn.Sequential(*body)
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = self.body(x)
        out = self.upsampler(out)
        base = F.interpolate(x, scale_factor=self.upscale, mode='nearest')
        return out + base

def load(path, device='cuda', half=True):
    sd = torch.load(path, map_location='cpu')
    sd = sd.get('params', sd)
    last = sd['body.34.weight'].shape[0]
    up = int((last // 3) ** 0.5)
    n_conv = (len([k for k in sd if k.startswith('body') and k.endswith('.weight') and sd[k].dim() == 4]) - 2)
    m = SRVGGNetCompact(num_feat=sd['body.0.weight'].shape[0], num_conv=n_conv, upscale=up)
    m.load_state_dict(sd, strict=True)
    m.eval().to(device)
    if half: m.half()
    return m, up
