import subprocess, time, numpy as np
SRC=r"C:\01_work\00_Git\toybox\AI_Video_up\サンプル.mp4"
W,H=720,480; N=W*H*3
def frames(ss=300,sec=60):
    p=subprocess.Popen(["ffmpeg","-v","error","-ss",str(ss),"-i",SRC,"-t",str(sec),
        "-f","rawvideo","-pix_fmt","bgr24","-"],stdout=subprocess.PIPE,bufsize=N*8)
    while True:
        b=p.stdout.read(N)
        if len(b)<N: break
        yield b
    p.stdout.close(); p.wait()

# 1) pipe read only
t=time.time(); c=0
for b in frames(): c+=1
print(f"read only            : {c/(time.time()-t):7.1f} fps")

# 2) read + full numpy array_equal
t=time.time(); c=0; prev=None
for b in frames():
    f=np.frombuffer(b,np.uint8); c+=1
    if prev is not None: np.array_equal(prev,f)
    prev=f
print(f"read + full compare  : {c/(time.time()-t):7.1f} fps")

# 3) read + strided subsample compare (every 8th pixel row/col)
t=time.time(); c=0; prev=None; same=0
for b in frames():
    f=np.frombuffer(b,np.uint8).reshape(H,W,3)[::8,::8,1]  # G channel, 60x90
    c+=1
    if prev is not None and np.array_equal(prev,f): same+=1
    prev=f
print(f"read + strided cmp   : {c/(time.time()-t):7.1f} fps   同一判定 {same}/{c}")

# 4) hash of raw bytes (blake2b on subsample)
import hashlib
t=time.time(); c=0; prev=None; same=0
for b in frames():
    h=hashlib.blake2b(b,digest_size=16).digest(); c+=1
    if prev==h: same+=1
    prev=h
print(f"read + blake2b(full) : {c/(time.time()-t):7.1f} fps   同一判定 {same}/{c}")
