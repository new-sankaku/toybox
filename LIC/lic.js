class LICPencilDrawing{
constructor(){
this.params={
kernelLength:20,
noiseScale:1,
brightness:0.7,
blockSize:5,
mergeThreshold:0.3,
minRegionSize:100,
textureWindowSize:18,
directionThreshold:1.5,
edgeStrength:0.5,
edgeMode:'adaptive',
paperStrength:0.3,
strokeDirection:'auto',
uniformAngle:Math.PI/4,
useSegmentation:true,
drawBoundaries:true
};
this.progressCallback=null;
this.segmentation=null;
this.textureAnalyzer=null;
}
setParams(params){Object.assign(this.params,params);}
setProgressCallback(callback){this.progressCallback=callback;}
updateProgress(progress,text){if(this.progressCallback)this.progressCallback(progress,text);}
sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms));}
async generate(inputImageData){
const width=inputImageData.width;
const height=inputImageData.height;
const inputData=inputImageData.data;
this.updateProgress(2,'グレースケール変換中...');
const grayscale=this.toGrayscale(inputData,width,height);
await this.sleep(10);
let segmentResult=null;
let regionBoundaries=null;
if(this.params.useSegmentation){
this.updateProgress(5,'領域分割中...');
this.segmentation=new ImageSegmentation(this.params.blockSize,32,this.params.mergeThreshold,this.params.minRegionSize);
segmentResult=await this.segmentImageAsync(grayscale,width,height);
this.updateProgress(15,'境界抽出中...');
regionBoundaries=this.segmentation.extractBoundaries(segmentResult.labels,width,height);
await this.sleep(10);
}
this.updateProgress(20,'ホワイトノイズ生成中...');
const noise=this.generateToneMatchedNoise(grayscale,width,height);
await this.sleep(10);
this.updateProgress(25,'ベクトル場生成中...');
const vectorField=await this.generateVectorField(grayscale,width,height,segmentResult);
this.updateProgress(40,'LIC計算中...');
const licResult=await this.computeLIC(noise,vectorField,width,height);
this.updateProgress(80,'エッジ検出中...');
const edges=this.detectEdgesSobel(grayscale,width,height);
this.updateProgress(85,'エッジ合成中...');
let result=this.blendEdges(licResult,edges,grayscale,width,height);
if(this.params.drawBoundaries&&regionBoundaries){
result=this.blendRegionBoundaries(result,regionBoundaries,width,height);
}
this.updateProgress(90,'紙テクスチャ合成中...');
const paperTexture=this.generatePaperTexture(width,height);
result=this.blendPaperTexture(result,paperTexture,width,height);
await this.sleep(10);
this.updateProgress(95,'出力画像作成中...');
const outputImageData=this.createOutputImageData(result,width,height);
this.updateProgress(100,'完了');
return outputImageData;
}
toGrayscale(data,width,height){
const grayscale=new Float32Array(width*height);
for(let i=0;i<width*height;i++){
grayscale[i]=0.299*data[i*4]+0.587*data[i*4+1]+0.114*data[i*4+2];
}
return grayscale;
}
async segmentImageAsync(grayscale,width,height){
const result=this.segmentation.segment(grayscale,width,height);
await this.sleep(10);
return result;
}
generateToneMatchedNoise(grayscale,width,height){
const noise=new Float32Array(width*height);
const k=this.params.brightness;
const scale=this.params.noiseScale;
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const i=y*width+x;
const intensity=grayscale[i];
const threshold=k*(1-intensity/255);
const sx=Math.floor(x/scale);
const sy=Math.floor(y/scale);
const seed=sx*73856093+sy*19349663+i*0.1;
const random=this.seededRandom(seed);
noise[i]=(random>=threshold)?255:0;
}
}
return noise;
}
seededRandom(seed){
const x=Math.sin(seed*12.9898+78.233)*43758.5453;
return x-Math.floor(x);
}
async generateVectorField(grayscale,width,height,segmentResult){
const vectorField=new Float32Array(width*height*2);
const direction=this.params.strokeDirection;
this.textureAnalyzer=new TextureAnalyzer(this.params.textureWindowSize,36,this.params.directionThreshold);
if(direction==='auto'||direction==='texture'){
await this.generateTextureBasedVectorField(vectorField,grayscale,width,height,segmentResult);
}else if(direction==='uniform'){
this.generateUniformVectorField(vectorField,width,height);
}else if(direction==='random'){
this.generateRandomVectorField(vectorField,width,height);
}else if(direction==='crosshatch'){
this.generateUniformVectorField(vectorField,width,height);
}
return this.smoothVectorField(vectorField,width,height);
}
async generateTextureBasedVectorField(vectorField,grayscale,width,height,segmentResult){
const stepSize=4;
const directions=new Float32Array(width*height*2);
const regionAngles=new Map();
if(segmentResult){
for(let r=0;r<segmentResult.numRegions;r++){
regionAngles.set(r,this.seededRandom(r*12345)*Math.PI);
}
}
for(let y=0;y<height;y+=stepSize){
if(y%20===0){
const progress=25+(y/height)*15;
this.updateProgress(progress,`テクスチャ解析中... ${Math.floor(y/height*100)}%`);
await this.sleep(0);
}
for(let x=0;x<width;x+=stepSize){
const result=this.textureAnalyzer.analyzeLocalDirection(grayscale,width,height,x,y);
let angle;
if(result.hasDirection){
angle=result.angle;
}else{
if(segmentResult){
const regionId=segmentResult.labels[y*width+x];
angle=regionAngles.get(regionId)||Math.PI/4;
}else{
angle=Math.PI/4;
}
}
for(let dy=0;dy<stepSize&&y+dy<height;dy++){
for(let dx=0;dx<stepSize&&x+dx<width;dx++){
const idx=((y+dy)*width+(x+dx))*2;
directions[idx]=Math.cos(angle);
directions[idx+1]=Math.sin(angle);
}
}
}
}
for(let i=0;i<vectorField.length;i++){
vectorField[i]=directions[i];
}
}
generateUniformVectorField(vectorField,width,height){
const angle=this.params.uniformAngle;
const vx=Math.cos(angle);
const vy=Math.sin(angle);
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const i=(y*width+x)*2;
vectorField[i]=vx;
vectorField[i+1]=vy;
}
}
}
generateRandomVectorField(vectorField,width,height){
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const i=(y*width+x)*2;
const angle=this.seededRandom(x+y*width)*Math.PI*2;
vectorField[i]=Math.cos(angle);
vectorField[i+1]=Math.sin(angle);
}
}
}
smoothVectorField(vectorField,width,height){
const smoothed=new Float32Array(width*height*2);
const kernelSize=5;
const half=Math.floor(kernelSize/2);
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
let sumX=0,sumY=0;
for(let ky=-half;ky<=half;ky++){
for(let kx=-half;kx<=half;kx++){
const nx=Math.min(Math.max(x+kx,0),width-1);
const ny=Math.min(Math.max(y+ky,0),height-1);
const ni=(ny*width+nx)*2;
sumX+=vectorField[ni];
sumY+=vectorField[ni+1];
}
}
const i=(y*width+x)*2;
const mag=Math.sqrt(sumX*sumX+sumY*sumY);
if(mag>0){
smoothed[i]=sumX/mag;
smoothed[i+1]=sumY/mag;
}else{
smoothed[i]=vectorField[i];
smoothed[i+1]=vectorField[i+1];
}
}
}
return smoothed;
}
async computeLIC(noise,vectorField,width,height){
const result=new Float32Array(width*height);
const L=this.params.kernelLength;
const halfL=Math.floor(L/2);
const kernel=new Float32Array(L);
for(let i=0;i<L;i++){
kernel[i]=1.0/L;
}
for(let y=0;y<height;y++){
if(y%10===0){
const progress=40+(y/height)*40;
this.updateProgress(progress,`LIC計算中... ${Math.floor(y/height*100)}%`);
await this.sleep(0);
}
for(let x=0;x<width;x++){
let sum=0;
let weightSum=0;
let px=x+0.5,py=y+0.5;
for(let k=0;k<halfL;k++){
const ix=Math.floor(px);
const iy=Math.floor(py);
if(ix<0||ix>=width||iy<0||iy>=height)break;
const ni=iy*width+ix;
const vi=ni*2;
const w=kernel[halfL+k];
sum+=noise[ni]*w;
weightSum+=w;
px+=vectorField[vi];
py+=vectorField[vi+1];
}
px=x+0.5;
py=y+0.5;
for(let k=1;k<=halfL;k++){
const vi=(Math.floor(py)*width+Math.floor(px))*2;
px-=vectorField[vi];
py-=vectorField[vi+1];
const ix=Math.floor(px);
const iy=Math.floor(py);
if(ix<0||ix>=width||iy<0||iy>=height)break;
const ni=iy*width+ix;
const w=kernel[halfL-k];
sum+=noise[ni]*w;
weightSum+=w;
}
const idx=y*width+x;
result[idx]=weightSum>0?sum/weightSum:noise[idx];
}
}
return result;
}
detectEdgesSobel(grayscale,width,height){
const edges=new Float32Array(width*height);
const sobelX=[-1,0,1,-2,0,2,-1,0,1];
const sobelY=[-1,-2,-1,0,0,0,1,2,1];
for(let y=1;y<height-1;y++){
for(let x=1;x<width-1;x++){
let gx=0,gy=0;
for(let ky=-1;ky<=1;ky++){
for(let kx=-1;kx<=1;kx++){
const idx=(y+ky)*width+(x+kx);
const ki=(ky+1)*3+(kx+1);
gx+=grayscale[idx]*sobelX[ki];
gy+=grayscale[idx]*sobelY[ki];
}
}
edges[y*width+x]=Math.sqrt(gx*gx+gy*gy);
}
}
return edges;
}
blendEdges(licResult,edges,grayscale,width,height){
const result=new Float32Array(width*height);
const strength=this.params.edgeStrength;
const mode=this.params.edgeMode;
let maxEdge=0;
for(let i=0;i<edges.length;i++){
maxEdge=Math.max(maxEdge,edges[i]);
}
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const i=y*width+x;
let edgeVal=edges[i];
if(mode==='adaptive'&&maxEdge>0){
const localMean=this.getLocalMean(grayscale,x,y,width,height,3);
const toneDiff=Math.abs(grayscale[i]-localMean);
const adaptiveStrength=strength*(1+(1-toneDiff/255)*0.5);
edgeVal=(edgeVal/maxEdge)*255*adaptiveStrength;
}else{
edgeVal=(maxEdge>0)?(edgeVal/maxEdge)*255*strength:0;
}
result[i]=Math.max(0,licResult[i]-edgeVal);
}
}
return result;
}
getLocalMean(data,cx,cy,width,height,radius){
let sum=0,count=0;
for(let dy=-radius;dy<=radius;dy++){
for(let dx=-radius;dx<=radius;dx++){
const x=Math.min(Math.max(cx+dx,0),width-1);
const y=Math.min(Math.max(cy+dy,0),height-1);
sum+=data[y*width+x];
count++;
}
}
return sum/count;
}
blendRegionBoundaries(image,boundaries,width,height){
const result=new Float32Array(width*height);
for(let i=0;i<width*height;i++){
if(boundaries[i]>0){
result[i]=Math.max(0,image[i]-boundaries[i]*0.3);
}else{
result[i]=image[i];
}
}
return result;
}
generatePaperTexture(width,height){
const texture=new Float32Array(width*height);
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
let val=128;
val+=(this.seededRandom(Math.floor(x/8)*127+Math.floor(y/8)*311)-0.5)*40;
val+=(this.seededRandom(Math.floor(x/3)*73+Math.floor(y/3)*179+10000)-0.5)*25;
val+=(this.seededRandom(x*37+y*89+50000)-0.5)*15;
texture[y*width+x]=val;
}
}
return texture;
}
blendPaperTexture(image,paperTexture,width,height){
const result=new Float32Array(width*height);
const strength=this.params.paperStrength;
for(let i=0;i<width*height;i++){
const paperEffect=(paperTexture[i]-128)*strength;
result[i]=image[i]-paperEffect;
result[i]=Math.max(0,Math.min(255,result[i]));
}
return result;
}
createOutputImageData(result,width,height){
const outputImageData=new ImageData(width,height);
for(let i=0;i<width*height;i++){
const val=Math.max(0,Math.min(255,Math.round(result[i])));
outputImageData.data[i*4]=val;
outputImageData.data[i*4+1]=val;
outputImageData.data[i*4+2]=val;
outputImageData.data[i*4+3]=255;
}
return outputImageData;
}
}
window.LICPencilDrawing=LICPencilDrawing;
