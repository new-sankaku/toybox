document.addEventListener('DOMContentLoaded',()=>{
const dropZone=document.getElementById('dropZone');
const fileInput=document.getElementById('fileInput');
const canvasContainer=document.getElementById('canvasContainer');
const inputCanvas=document.getElementById('inputCanvas');
const outputCanvas=document.getElementById('outputCanvas');
const generateBtn=document.getElementById('generateBtn');
const downloadBtn=document.getElementById('downloadBtn');
const progressContainer=document.getElementById('progressContainer');
const progressFill=document.getElementById('progressFill');
const progressText=document.getElementById('progressText');
const params={
kernelLength:document.getElementById('kernelLength'),
noiseScale:document.getElementById('noiseScale'),
strokeDirection:document.getElementById('strokeDirection'),
brightness:document.getElementById('brightness'),
useSegmentation:document.getElementById('useSegmentation'),
blockSize:document.getElementById('blockSize'),
mergeThreshold:document.getElementById('mergeThreshold'),
minRegionSize:document.getElementById('minRegionSize'),
drawBoundaries:document.getElementById('drawBoundaries'),
textureWindowSize:document.getElementById('textureWindowSize'),
directionThreshold:document.getElementById('directionThreshold'),
edgeStrength:document.getElementById('edgeStrength'),
edgeMode:document.getElementById('edgeMode'),
paperStrength:document.getElementById('paperStrength')
};
const valueDisplays={
kernelLength:document.getElementById('kernelLengthValue'),
noiseScale:document.getElementById('noiseScaleValue'),
brightness:document.getElementById('brightnessValue'),
blockSize:document.getElementById('blockSizeValue'),
mergeThreshold:document.getElementById('mergeThresholdValue'),
minRegionSize:document.getElementById('minRegionSizeValue'),
textureWindowSize:document.getElementById('textureWindowSizeValue'),
directionThreshold:document.getElementById('directionThresholdValue'),
edgeStrength:document.getElementById('edgeStrengthValue'),
paperStrength:document.getElementById('paperStrengthValue')
};
const inputCtx=inputCanvas.getContext('2d');
const outputCtx=outputCanvas.getContext('2d');
const licProcessor=new LICPencilDrawing();
let currentImageData=null;
function updateParamDisplays(){
for(const[key,display]of Object.entries(valueDisplays)){
if(display&&params[key])display.textContent=params[key].value;
}
}
function setupParamListeners(){
const rangeInputs=['kernelLength','noiseScale','brightness','blockSize','mergeThreshold','minRegionSize','textureWindowSize','directionThreshold','edgeStrength','paperStrength'];
rangeInputs.forEach(key=>{
if(params[key])params[key].addEventListener('input',updateParamDisplays);
});
}
function getParams(){
return{
kernelLength:parseInt(params.kernelLength.value),
noiseScale:parseInt(params.noiseScale.value),
strokeDirection:params.strokeDirection.value,
brightness:parseFloat(params.brightness.value),
useSegmentation:params.useSegmentation.checked,
blockSize:parseInt(params.blockSize.value),
mergeThreshold:parseFloat(params.mergeThreshold.value),
minRegionSize:parseInt(params.minRegionSize.value),
drawBoundaries:params.drawBoundaries.checked,
textureWindowSize:parseInt(params.textureWindowSize.value),
directionThreshold:parseFloat(params.directionThreshold.value),
edgeStrength:parseFloat(params.edgeStrength.value),
edgeMode:params.edgeMode.value,
paperStrength:parseFloat(params.paperStrength.value),
uniformAngle:Math.PI/4
};
}
dropZone.addEventListener('click',()=>fileInput.click());
dropZone.addEventListener('dragover',(e)=>{
e.preventDefault();
dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave',()=>{
dropZone.classList.remove('drag-over');
});
dropZone.addEventListener('drop',(e)=>{
e.preventDefault();
dropZone.classList.remove('drag-over');
const files=e.dataTransfer.files;
if(files.length>0&&files[0].type.startsWith('image/')){
loadImage(files[0]);
}
});
fileInput.addEventListener('change',(e)=>{
if(e.target.files.length>0)loadImage(e.target.files[0]);
});
function loadImage(file){
const reader=new FileReader();
reader.onload=(e)=>{
const img=new Image();
img.onload=()=>{
const maxSize=800;
let width=img.width;
let height=img.height;
if(width>maxSize||height>maxSize){
if(width>height){
height=Math.round(height*maxSize/width);
width=maxSize;
}else{
width=Math.round(width*maxSize/height);
height=maxSize;
}
}
inputCanvas.width=width;
inputCanvas.height=height;
outputCanvas.width=width;
outputCanvas.height=height;
inputCtx.drawImage(img,0,0,width,height);
currentImageData=inputCtx.getImageData(0,0,width,height);
canvasContainer.classList.add('visible');
generateBtn.disabled=false;
downloadBtn.disabled=true;
outputCtx.fillStyle='#f0f0f0';
outputCtx.fillRect(0,0,width,height);
outputCtx.fillStyle='#999';
outputCtx.font='16px sans-serif';
outputCtx.textAlign='center';
outputCtx.fillText('「鉛筆画を生成」をクリック',width/2,height/2);
};
img.src=e.target.result;
};
reader.readAsDataURL(file);
}
function updateProgress(percent,text){
progressFill.style.width=`${percent}%`;
progressText.textContent=text;
}
async function generatePencilDrawing(){
if(!currentImageData)return;
generateBtn.disabled=true;
downloadBtn.disabled=true;
progressContainer.classList.add('visible');
updateProgress(0,'処理開始...');
const currentParams=getParams();
licProcessor.setParams(currentParams);
licProcessor.setProgressCallback(updateProgress);
try{
const outputImageData=await licProcessor.generate(currentImageData);
outputCtx.putImageData(outputImageData,0,0);
if(currentParams.strokeDirection==='crosshatch'){
await applyCrosshatchSecondPass();
}
downloadBtn.disabled=false;
}catch(error){
console.error('Error:',error);
alert('処理中にエラーが発生しました: '+error.message);
}finally{
generateBtn.disabled=false;
setTimeout(()=>{
progressContainer.classList.remove('visible');
},1000);
}
}
async function applyCrosshatchSecondPass(){
updateProgress(50,'クロスハッチング2パス目...');
const secondProcessor=new LICPencilDrawing();
secondProcessor.setParams({
kernelLength:parseInt(params.kernelLength.value),
noiseScale:parseInt(params.noiseScale.value),
strokeDirection:'uniform',
brightness:parseFloat(params.brightness.value)*0.8,
useSegmentation:false,
drawBoundaries:false,
textureWindowSize:parseInt(params.textureWindowSize.value),
directionThreshold:parseFloat(params.directionThreshold.value),
edgeStrength:0,
edgeMode:'fixed',
paperStrength:0,
uniformAngle:-Math.PI/4
});
secondProcessor.setProgressCallback((p,t)=>{
updateProgress(50+p*0.5,t);
});
const secondPass=await secondProcessor.generate(currentImageData);
const currentOutput=outputCtx.getImageData(0,0,outputCanvas.width,outputCanvas.height);
// 元画像のグレースケール値を取得（クロスハッチングの強度決定に使用）
const width=currentOutput.width;
const height=currentOutput.height;
for(let y=0;y<height;y++){
for(let x=0;x<width;x++){
const i=(y*width+x)*4;
// 元画像の輝度（暗いほど値が小さい）
const originalLuminance=(0.299*currentImageData.data[i]+0.587*currentImageData.data[i+1]+0.114*currentImageData.data[i+2])/255;
// クロスハッチング強度：暗い部分ほど強く適用（1-luminanceで反転）
// 閾値を設けて、明るい部分にはほとんど適用しない
const darkness=1-originalLuminance;
// 暗さが0.3以下の部分にはクロスハッチングをほぼ適用しない
// 暗さが0.7以上の部分には完全に適用
const crosshatchStrength=Math.max(0,Math.min(1,(darkness-0.3)/0.4));
const v1=currentOutput.data[i]/255;  // 1回目パス結果
const v2=secondPass.data[i]/255;     // 2回目パス結果
// 強度に応じてブレンド：strength=0なら1回目のみ、strength=1なら乗算
const blended=Math.floor((v1*(1-crosshatchStrength)+v1*v2*crosshatchStrength)*255);
currentOutput.data[i]=blended;
currentOutput.data[i+1]=blended;
currentOutput.data[i+2]=blended;
}
}
outputCtx.putImageData(currentOutput,0,0);
}
function downloadImage(){
const link=document.createElement('a');
link.download='pencil-drawing.png';
link.href=outputCanvas.toDataURL('image/png');
link.click();
}
generateBtn.addEventListener('click',generatePencilDrawing);
downloadBtn.addEventListener('click',downloadImage);
setupParamListeners();
updateParamDisplays();
});
