class FFT{
static fft1d(real,imag,inverse=false){
const n=real.length;
if(n<=1)return;
let j=0;
for(let i=0;i<n-1;i++){
if(i<j){
[real[i],real[j]]=[real[j],real[i]];
[imag[i],imag[j]]=[imag[j],imag[i]];
}
let k=n>>1;
while(k<=j){j-=k;k>>=1;}
j+=k;
}
const dir=inverse?1:-1;
for(let len=2;len<=n;len<<=1){
const halfLen=len>>1;
const angle=dir*2*Math.PI/len;
const wReal=Math.cos(angle);
const wImag=Math.sin(angle);
for(let i=0;i<n;i+=len){
let curReal=1;
let curImag=0;
for(let k=0;k<halfLen;k++){
const evenIdx=i+k;
const oddIdx=i+k+halfLen;
const tReal=curReal*real[oddIdx]-curImag*imag[oddIdx];
const tImag=curReal*imag[oddIdx]+curImag*real[oddIdx];
real[oddIdx]=real[evenIdx]-tReal;
imag[oddIdx]=imag[evenIdx]-tImag;
real[evenIdx]=real[evenIdx]+tReal;
imag[evenIdx]=imag[evenIdx]+tImag;
const tmpReal=curReal*wReal-curImag*wImag;
curImag=curReal*wImag+curImag*wReal;
curReal=tmpReal;
}
}
}
if(inverse){
for(let i=0;i<n;i++){
real[i]/=n;
imag[i]/=n;
}
}
}
static fft2d(real,imag,width,height,inverse=false){
const rowReal=new Float32Array(width);
const rowImag=new Float32Array(width);
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
rowReal[x]=real[y*width+x];
rowImag[x]=imag[y*width+x];
}
this.fft1d(rowReal,rowImag,inverse);
for(let x=0;x<width;x++){
real[y*width+x]=rowReal[x];
imag[y*width+x]=rowImag[x];
}
}
const colReal=new Float32Array(height);
const colImag=new Float32Array(height);
for(let x=0;x<width;x++){
for(let y=0;y<height;y++){
colReal[y]=real[y*width+x];
colImag[y]=imag[y*width+x];
}
this.fft1d(colReal,colImag,inverse);
for(let y=0;y<height;y++){
real[y*width+x]=colReal[y];
imag[y*width+x]=colImag[y];
}
}
}
static powerSpectrum(real,imag){
const n=real.length;
const power=new Float32Array(n);
for(let i=0;i<n;i++){
power[i]=real[i]*real[i]+imag[i]*imag[i];
}
return power;
}
static nextPowerOf2(n){
let p=1;
while(p<n)p<<=1;
return p;
}
}

class TextureAnalyzer{
constructor(windowSize=18,numSectors=36,threshold=1.5){
this.windowSize=windowSize;
this.numSectors=numSectors;
this.threshold=threshold;
this.fftSize=FFT.nextPowerOf2(windowSize);
}
analyzeLocalDirection(grayscale,width,height,cx,cy){
const winSize=this.windowSize;
const fftSize=this.fftSize;
const half=Math.floor(winSize/2);
const real=new Float32Array(fftSize*fftSize);
const imag=new Float32Array(fftSize*fftSize);
let mean=0;
let count=0;
for(let wy=0;wy<winSize;wy++){
for(let wx=0;wx<winSize;wx++){
const sx=Math.min(Math.max(cx-half+wx,0),width-1);
const sy=Math.min(Math.max(cy-half+wy,0),height-1);
mean+=grayscale[sy*width+sx];
count++;
}
}
mean/=count;
for(let wy=0;wy<winSize;wy++){
for(let wx=0;wx<winSize;wx++){
const sx=Math.min(Math.max(cx-half+wx,0),width-1);
const sy=Math.min(Math.max(cy-half+wy,0),height-1);
real[wy*fftSize+wx]=grayscale[sy*width+sx]-mean;
}
}
for(let wy=0;wy<winSize;wy++){
for(let wx=0;wx<winSize;wx++){
const windowX=0.5*(1-Math.cos(2*Math.PI*wx/(winSize-1)));
const windowY=0.5*(1-Math.cos(2*Math.PI*wy/(winSize-1)));
real[wy*fftSize+wx]*=windowX*windowY;
}
}
FFT.fft2d(real,imag,fftSize,fftSize,false);
const power=FFT.powerSpectrum(real,imag);
const sectorPower=new Float32Array(this.numSectors);
const centerX=Math.floor(fftSize/2);
const centerY=Math.floor(fftSize/2);
for(let y=0;y<fftSize;y++){
for(let x=0;x<fftSize;x++){
const shiftX=(x+centerX)%fftSize;
const shiftY=(y+centerY)%fftSize;
const dx=shiftX-centerX;
const dy=shiftY-centerY;
const dist=Math.sqrt(dx*dx+dy*dy);
if(dist<1||dist>fftSize/4)continue;
let angle=Math.atan2(dy,dx);
if(angle<0)angle+=Math.PI*2;
const sectorIdx=Math.floor(angle/(Math.PI*2)*this.numSectors)%this.numSectors;
sectorPower[sectorIdx]+=power[y*fftSize+x];
}
}
let maxPower=0;
let maxSector=0;
let totalPower=0;
for(let i=0;i<this.numSectors;i++){
totalPower+=sectorPower[i];
if(sectorPower[i]>maxPower){
maxPower=sectorPower[i];
maxSector=i;
}
}
const avgPower=totalPower/this.numSectors;
const hasDirection=avgPower>0&&(maxPower/avgPower)>=this.threshold;
let textureAngle=(maxSector/this.numSectors)*Math.PI*2;
textureAngle+=Math.PI/2;
return{
angle:textureAngle,
hasDirection:hasDirection,
strength:avgPower>0?maxPower/avgPower:0
};
}
}
window.FFT=FFT;
window.TextureAnalyzer=TextureAnalyzer;
