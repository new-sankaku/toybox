import torch, time, sys
sys.path.insert(0, r"C:\01_work\00_Git\toybox\AI_Video_up\vup")
from srvgg import load
m, up = load(r"C:\01_work\00_Git\toybox\AI_Video_up\vup\models\realesr-animevideov3.pth")
print("upscale =", up)
for bs in (1,2,4,8):
    x = torch.randn(bs,3,480,720, device='cuda', dtype=torch.half)
    with torch.no_grad():
        for _ in range(3): m(x)
        torch.cuda.synchronize(); t=time.time()
        n=10
        for _ in range(n): y=m(x)
        torch.cuda.synchronize(); el=time.time()-t
    print(f"batch={bs}: {bs*n/el:6.2f} fps  out={tuple(y.shape)}  vram={torch.cuda.max_memory_allocated()/2**20:.0f}MB")
