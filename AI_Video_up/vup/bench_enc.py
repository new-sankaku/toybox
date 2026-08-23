# 出力解像度別のencode上限(raw pipe -> nvenc / svtav1)を測る
import subprocess, time, numpy as np, sys
def bench(w,h,n,args,tag):
    cmd=["ffmpeg","-v","error","-f","rawvideo","-pix_fmt","bgr24","-s",f"{w}x{h}","-r","24","-i","-"]+args+["-y",r"C:\Users\sanka\AppData\Local\Temp\claude\C--01-work-00-Git-toybox-AI-Video-up\4638d1bb-d7d6-4ec3-9566-a51ecfe82ba4\scratchpad\enc.mp4"]
    frame=np.random.randint(0,255,(h,w,3),np.uint8).tobytes()
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    t=time.time()
    for _ in range(n): p.stdin.write(frame)
    p.stdin.close(); p.wait(); el=time.time()-t
    print(f"{tag:34s} {w}x{h}: {n/el:6.1f} fps")
N=100
for (w,h) in ((1440,960),(2880,1920)):
    bench(w,h,N,["-c:v","hevc_nvenc","-preset","p5","-cq","24","-pix_fmt","yuv420p"],"hevc_nvenc p5")
    bench(w,h,N,["-c:v","hevc_nvenc","-preset","p1","-cq","24","-pix_fmt","yuv420p"],"hevc_nvenc p1")
    bench(w,h,N,["-c:v","libsvtav1","-crf","20","-preset","6","-pix_fmt","yuv420p"],"libsvtav1 preset6")
    bench(w,h,N,["-c:v","libx264","-crf","18","-preset","veryfast","-pix_fmt","yuv420p"],"libx264 veryfast")
