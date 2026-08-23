import subprocess, numpy as np, sys, collections
W,H=480,270
def diffs(path):
    p=subprocess.Popen(["ffmpeg","-v","error","-i",path,"-fps_mode","passthrough",
        "-vf",f"scale={W}:{H}:flags=area,format=gray","-f","rawvideo","-pix_fmt","gray","-"],
        stdout=subprocess.PIPE)
    buf=bytearray(W*H); mv=memoryview(buf); prev=None; d=[]; n=0
    while p.stdout.readinto(mv)==W*H:
        f=np.frombuffer(bytes(buf),np.uint8).reshape(H,W).astype(np.int16)
        if prev is not None: d.append(float(np.abs(f-prev).max()))
        prev=f; n+=1
    p.wait(); return n,np.array(d)
for path,fps in [("vfi2/work/B_talk.mkv",23.976),("vfi/work/B_talk_x2_v4.6.mp4",47.952)]:
    n,d=diffs(path); th=6
    chg=np.where(d>=th)[0]+1
    bounds=np.concatenate(([0],chg,[n]))
    rl=np.diff(bounds)
    c=collections.Counter(rl.tolist())
    print(f"{path.split('/')[-1]}  fps={fps}  絵={len(rl)}  保持長の分布(frame:件数):")
    print("   ", dict(sorted(c.items())))
    ms=rl/fps*1000
    print(f"    保持時間 ms: p10={np.percentile(ms,10):.0f} p50={np.percentile(ms,50):.0f} p90={np.percentile(ms,90):.0f}  平均={ms.mean():.0f}")
    print()
