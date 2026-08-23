import torch, time, sys
sys.path.insert(0, r"C:\01_work\00_Git\toybox\AI_Video_up\vup")
from srvgg import load
torch.backends.cudnn.benchmark=True
m, up = load(r"C:\01_work\00_Git\toybox\AI_Video_up\vup\models\realesr-animevideov3.pth")

def bench(mod, bs, tag, cl=False):
    x = torch.randn(bs,3,480,720, device='cuda', dtype=torch.half)
    if cl: x = x.contiguous(memory_format=torch.channels_last)
    with torch.no_grad():
        for _ in range(5): mod(x)
        torch.cuda.synchronize(); t=time.time(); n=15
        for _ in range(n): y=mod(x)
        torch.cuda.synchronize(); el=time.time()-t
    print(f"{tag:28s} batch={bs}: {bs*n/el:6.2f} fps")

for bs in (1,4,8):
    bench(m, bs, "fp16 contiguous")
mcl = m.to(memory_format=torch.channels_last)
for bs in (1,4,8):
    bench(mcl, bs, "fp16 channels_last", cl=True)
