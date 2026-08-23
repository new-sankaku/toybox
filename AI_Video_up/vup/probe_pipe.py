"""pipeline骨組みの実測: decode -> (SR無し) -> encode の上限速度と、dedup率を同時に測る"""
import subprocess, sys, time, hashlib
import numpy as np

SRC = r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W, H = 720, 480
SEC = 60
SS = 300

def decode_iter(ss, sec):
    cmd = ["ffmpeg","-v","error","-ss",str(ss),"-i",SRC,"-t",str(sec),
           "-f","rawvideo","-pix_fmt","bgr24","-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
    n = W*H*3
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n: break
        yield np.frombuffer(buf, np.uint8).reshape(H,W,3)
    p.stdout.close(); p.wait()

t0=time.time(); cnt=0
prev=None; exact=0; near=0
runs=[]; cur=1
for f in decode_iter(SS, SEC):
    cnt+=1
    if prev is not None:
        if np.array_equal(prev,f):
            exact+=1; cur+=1
        else:
            d = np.abs(prev.astype(np.int16)-f.astype(np.int16))
            mad = d.mean()
            if mad < 0.5: near+=1; cur+=1
            else:
                runs.append(cur); cur=1
    prev=f
runs.append(cur)
el=time.time()-t0
import collections
print(f"decode+差分: {cnt} frames / {el:.2f}s = {cnt/el:.1f} fps")
print(f"厳密同一: {exact} ({exact/cnt*100:.1f}%)  準同一(MAD<0.5): {near} ({near/cnt*100:.1f}%)")
uniq = len(runs)
print(f"unique frame: {uniq} / {cnt} = {uniq/cnt*100:.1f}%  -> 削減 {cnt/uniq:.2f}倍")
print("連続長 histogram:", dict(sorted(collections.Counter(runs).items())[:8]))
