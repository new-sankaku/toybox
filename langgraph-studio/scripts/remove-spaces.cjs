// TS/TSXファイルから不要なスペースとコメントを削除するスクリプト
// 使用方法: npm run format
//
// 削除対象:
// - 演算子周りのスペース
// - カンマ・セミコロン後のスペース
// - 括弧内側のスペース
// - インラインコメント（TODO/FIXME以外）
// - JSXコメント {/* comment */}（TODO/FIXME以外）
// - ブロックコメント /* comment */（TODO/FIXME以外）
//
// 保持対象:
// - 文字列リテラル内のスペース
// - TODO/FIXMEコメント
const fs=require('fs');
const path=require('path');
const excludeDirs=['node_modules','.git','dist','out'];

function removeSpacesAndComments(code){
 let preserved=[];
 let index=0;

 // 文字列とテンプレートリテラルを保護
 let result=code.replace(/(`(?:[^`\\]|\\.)*`|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g,(match)=>{
  preserved.push(match);
  return `__PRESERVED_${index++}__`;
 });

 // インラインコメント削除（TODO/FIXME以外）
 result=result.replace(/\/\/(?!.*(?:TODO|FIXME))[^\n]*/g,'');

 // JSXコメント削除 {/* ... */}（TODO/FIXME以外）
 result=result.replace(/\{\/\*(?![\s\S]*?(?:TODO|FIXME))[\s\S]*?\*\/\}/g,'');

 // ブロックコメント削除 /* ... */（TODO/FIXME以外）
 result=result.replace(/\/\*(?![\s\S]*?(?:TODO|FIXME))[\s\S]*?\*\//g,'');

 // 演算子周りのスペース削除
 result=result.replace(/([=!<>+\-*/%&|^])[ \t]+(?=\S)/g,'$1');
 result=result.replace(/(?<=\S)[ \t]+([=!<>+\-*/%&|^])/g,'$1');

 // カンマ・セミコロン後のスペース
 result=result.replace(/,[ \t]+/g,',');
 result=result.replace(/;[ \t]+/g,';');

 // 括弧内側のスペース
 result=result.replace(/\([ \t]+/g,'(');
 result=result.replace(/[ \t]+\)/g,')');
 result=result.replace(/\[[ \t]+/g,'[');
 result=result.replace(/[ \t]+\]/g,']');

 // 行末の空白削除
 result=result.replace(/[ \t]+$/gm,'');

 // 復元
 for(let i=0;i<preserved.length;i++){
  result=result.replace(`__PRESERVED_${i}__`,preserved[i]);
 }
 return result;
}

function processFile(filePath){
 try{
  const code=fs.readFileSync(filePath,'utf8');
  const processed=removeSpacesAndComments(code);
  if(code!==processed){
   fs.writeFileSync(filePath,processed,'utf8');
   console.log(`Processed: ${filePath}`);
   return true;
  }
  return false;
 }catch(err){
  console.error(`Error processing ${filePath}: ${err.message}`);
  return false;
 }
}

function walkDir(dir){
 let count=0;
 const files=fs.readdirSync(dir);
 for(const file of files){
  const fullPath=path.join(dir,file);
  const stat=fs.statSync(fullPath);
  if(stat.isDirectory()){
   if(!excludeDirs.includes(file)){
    count+=walkDir(fullPath);
   }
  }else if((file.endsWith('.ts')||file.endsWith('.tsx'))&&!file.endsWith('.d.ts')){
   if(processFile(fullPath)){
    count++;
   }
  }
 }
 return count;
}

const targetDir=path.join(__dirname,'..','src');
console.log(`Processing TS/TSX files in: ${targetDir}`);
console.log(`Excluding directories: ${excludeDirs.join(', ')}`);
console.log('');
const count=walkDir(targetDir);
console.log('');
console.log(`Done! ${count} files modified.`);
