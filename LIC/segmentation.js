class ImageSegmentation{
constructor(blockSize=5,histogramBins=32,mergeThreshold=0.3,minRegionSize=100){
this.blockSize=blockSize;
this.histogramBins=histogramBins;
this.mergeThreshold=mergeThreshold;
this.minRegionSize=minRegionSize;
}
segment(grayscale,width,height){
const blockLabels=this.createInitialBlocks(width,height);
const numBlocksX=Math.ceil(width/this.blockSize);
const numBlocksY=Math.ceil(height/this.blockSize);
const numInitialBlocks=numBlocksX*numBlocksY;
const histograms=this.computeBlockHistograms(grayscale,width,height,numBlocksX,numBlocksY);
const parent=new Int32Array(numInitialBlocks);
const rank=new Int32Array(numInitialBlocks);
for(let i=0;i<numInitialBlocks;i++){
parent[i]=i;
rank[i]=0;
}
this.mergeSimularBlocks(histograms,numBlocksX,numBlocksY,parent,rank);
let labels=this.createPixelLabels(blockLabels,parent,width,height,numBlocksX);
labels=this.mergeSmallRegions(labels,grayscale,width,height);
return this.relabelRegions(labels,width,height);
}
createInitialBlocks(width,height){
const numBlocksX=Math.ceil(width/this.blockSize);
const labels=new Int32Array(width*height);
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const bx=Math.floor(x/this.blockSize);
const by=Math.floor(y/this.blockSize);
labels[y*width+x]=by*numBlocksX+bx;
}
}
return labels;
}
computeBlockHistograms(grayscale,width,height,numBlocksX,numBlocksY){
const numBlocks=numBlocksX*numBlocksY;
const histograms=[];
for(let i=0;i<numBlocks;i++){
histograms.push(new Float32Array(this.histogramBins));
}
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const bx=Math.floor(x/this.blockSize);
const by=Math.floor(y/this.blockSize);
const blockIdx=by*numBlocksX+bx;
const intensity=grayscale[y*width+x];
const bin=Math.min(Math.floor(intensity/256*this.histogramBins),this.histogramBins-1);
histograms[blockIdx][bin]++;
}
}
for(let i=0;i<numBlocks;i++){
let sum=0;
for(let j=0;j<this.histogramBins;j++){
sum+=histograms[i][j];
}
if(sum>0){
for(let j=0;j<this.histogramBins;j++){
histograms[i][j]/=sum;
}
}
}
return histograms;
}
histogramDistance(hist1,hist2){
let distance=0;
for(let i=0;i<this.histogramBins;i++){
distance+=Math.abs(hist1[i]-hist2[i]);
}
return distance;
}
find(parent,i){
if(parent[i]!==i){
parent[i]=this.find(parent,parent[i]);
}
return parent[i];
}
union(parent,rank,i,j){
const rootI=this.find(parent,i);
const rootJ=this.find(parent,j);
if(rootI!==rootJ){
if(rank[rootI]<rank[rootJ]){
parent[rootI]=rootJ;
}else if(rank[rootI]>rank[rootJ]){
parent[rootJ]=rootI;
}else{
parent[rootJ]=rootI;
rank[rootI]++;
}
}
}
mergeSimularBlocks(histograms,numBlocksX,numBlocksY,parent,rank){
const directions=[[1,0],[0,1],[1,1],[-1,1]];
let merged=true;
while(merged){
merged=false;
for(let by=0;by<numBlocksY;by++){
for(let bx=0;bx<numBlocksX;bx++){
const blockIdx=by*numBlocksX+bx;
const root1=this.find(parent,blockIdx);
for(const[dx,dy]of directions){
const nbx=bx+dx;
const nby=by+dy;
if(nbx>=0&&nbx<numBlocksX&&nby>=0&&nby<numBlocksY){
const neighborIdx=nby*numBlocksX+nbx;
const root2=this.find(parent,neighborIdx);
if(root1!==root2){
const distance=this.histogramDistance(histograms[blockIdx],histograms[neighborIdx]);
if(distance<this.mergeThreshold){
this.union(parent,rank,root1,root2);
merged=true;
}
}
}
}
}
}
}
}
createPixelLabels(blockLabels,parent,width,height,numBlocksX){
const labels=new Int32Array(width*height);
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const blockIdx=blockLabels[y*width+x];
labels[y*width+x]=this.find(parent,blockIdx);
}
}
return labels;
}
mergeSmallRegions(labels,grayscale,width,height){
const regionSizes=new Map();
const regionSums=new Map();
for(let i=0;i<width*height;i++){
const label=labels[i];
regionSizes.set(label,(regionSizes.get(label)||0)+1);
regionSums.set(label,(regionSums.get(label)||0)+grayscale[i]);
}
const regionMeans=new Map();
for(const[label,size]of regionSizes){
regionMeans.set(label,regionSums.get(label)/size);
}
const labelMapping=new Map();
for(const[label,size]of regionSizes){
if(size<this.minRegionSize){
const neighbors=this.findNeighborRegions(labels,label,width,height);
let bestNeighbor=-1;
let bestDiff=Infinity;
const currentMean=regionMeans.get(label);
for(const neighbor of neighbors){
if(regionSizes.get(neighbor)>=this.minRegionSize){
const neighborMean=regionMeans.get(neighbor);
const diff=Math.abs(currentMean-neighborMean);
if(diff<bestDiff){
bestDiff=diff;
bestNeighbor=neighbor;
}
}
}
if(bestNeighbor!==-1){
labelMapping.set(label,bestNeighbor);
}
}
}
const result=new Int32Array(width*height);
for(let i=0;i<width*height;i++){
let label=labels[i];
while(labelMapping.has(label)){
label=labelMapping.get(label);
}
result[i]=label;
}
return result;
}
findNeighborRegions(labels,targetLabel,width,height){
const neighbors=new Set();
const directions=[[-1,0],[1,0],[0,-1],[0,1]];
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
if(labels[y*width+x]===targetLabel){
for(const[dx,dy]of directions){
const nx=x+dx;
const ny=y+dy;
if(nx>=0&&nx<width&&ny>=0&&ny<height){
const neighborLabel=labels[ny*width+nx];
if(neighborLabel!==targetLabel){
neighbors.add(neighborLabel);
}
}
}
}
}
}
return neighbors;
}
relabelRegions(labels,width,height){
const labelSet=new Set();
for(let i=0;i<width*height;i++){
labelSet.add(labels[i]);
}
const labelArray=Array.from(labelSet).sort((a,b)=>a-b);
const labelMap=new Map();
for(let i=0;i<labelArray.length;i++){
labelMap.set(labelArray[i],i);
}
const newLabels=new Int32Array(width*height);
for(let i=0;i<width*height;i++){
newLabels[i]=labelMap.get(labels[i]);
}
const numRegions=labelArray.length;
const regionInfo=[];
for(let r=0;r<numRegions;r++){
let minX=width,minY=height,maxX=0,maxY=0;
let count=0;
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
if(newLabels[y*width+x]===r){
minX=Math.min(minX,x);
minY=Math.min(minY,y);
maxX=Math.max(maxX,x);
maxY=Math.max(maxY,y);
count++;
}
}
}
regionInfo.push({id:r,bounds:{minX,minY,maxX,maxY},size:count,strokeAngle:null});
}
return{labels:newLabels,numRegions:numRegions,regionInfo:regionInfo};
}
extractBoundaries(labels,width,height){
const boundaries=new Float32Array(width*height);
for(let y=1;y<height-1;y++){
for(let x=1;x<width-1;x++){
const center=labels[y*width+x];
let isBoundary=false;
if(labels[y*width+(x-1)]!==center||labels[y*width+(x+1)]!==center||labels[(y-1)*width+x]!==center||labels[(y+1)*width+x]!==center){
isBoundary=true;
}
boundaries[y*width+x]=isBoundary?255:0;
}
}
return boundaries;
}
}
window.ImageSegmentation=ImageSegmentation;
