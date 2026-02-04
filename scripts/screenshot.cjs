const path=require('path')
const fs=require('fs')
const{chromium}=require(path.join(__dirname,'..','langgraph-studio','node_modules','playwright-core'))

const BASE_URL=process.env.APP_URL||'http://localhost:5173'
const OUTPUT_DIR=process.env.SCREENSHOT_DIR||path.join(__dirname,'..','screenshots')

const TABS=[
 {name:'プロジェクト',filename:'01_project'},
 {name:'ダッシュボード',filename:'02_dashboard'},
 {name:'承認',filename:'03_checkpoints'},
 {name:'連絡',filename:'04_intervention'},
 {name:'エージェント',filename:'05_agents'},
 {name:'生成素材',filename:'06_data'},
 {name:'コスト',filename:'07_cost'},
 {name:'ログ',filename:'08_logs'},
 {name:'プロジェクト設定',filename:'09_config'},
 {name:'共通設定',filename:'10_global_config'}
]

function findChrome(){
 const candidates=[
  '/usr/bin/google-chrome-stable',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
  '/opt/google/chrome/chrome',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
 ]
 for(const c of candidates){
  if(fs.existsSync(c))return c
 }
 return null
}

async function clickTab(page,tabName){
 const buttons=await page.$$('button')
 for(const btn of buttons){
  const text=await btn.textContent()
  if(text&&text.trim().includes(tabName)&&text.trim().length<tabName.length+10){
   const isDisabled=await btn.evaluate(el=>el.disabled)
   if(isDisabled){
    console.log(`  [SKIP] ${tabName} (disabled)`)
    return false
   }
   await btn.click()
   return true
  }
 }
 return false
}

async function clickFirstProject(page){
 const rows=await page.$$('[class*="cursor-pointer"]')
 for(const row of rows){
  const text=await row.textContent()
  if(text&&(text.includes('ゲーム')||text.includes('Phase'))&&!text.includes('プロジェクト一覧')){
   await row.click()
   return true
  }
 }
 return false
}

;(async()=>{
 const chrome=findChrome()
 if(!chrome){
  console.error('Chrome not found. Set APP_CHROME_PATH env or install Chrome.')
  process.exit(1)
 }

 fs.mkdirSync(OUTPUT_DIR,{recursive:true})

 const browser=await chromium.launch({
  executablePath:process.env.APP_CHROME_PATH||chrome,
  args:['--no-sandbox','--disable-setuid-sandbox'],
  headless:true
 })

 const context=await browser.newContext({viewport:{width:1440,height:900}})
 const page=await context.newPage()

 console.log(`Navigating to ${BASE_URL}...`)
 await page.goto(BASE_URL,{waitUntil:'networkidle',timeout:30000})
 await page.waitForTimeout(2000)

 await page.screenshot({path:path.join(OUTPUT_DIR,'00_initial.png'),fullPage:true})
 console.log('Captured: 00_initial.png')

 const selected=await clickFirstProject(page)
 if(selected){
  await page.waitForTimeout(2000)
  await page.screenshot({path:path.join(OUTPUT_DIR,'00_project_selected.png'),fullPage:true})
  console.log('Captured: 00_project_selected.png')
 }else{
  console.log('  [INFO] No project to select')
 }

 for(const tab of TABS){
  const clicked=await clickTab(page,tab.name)
  if(clicked){
   await page.waitForTimeout(1500)
   await page.screenshot({path:path.join(OUTPUT_DIR,`${tab.filename}.png`),fullPage:true})
   console.log(`Captured: ${tab.filename}.png`)
  }
 }

 await browser.close()
 console.log(`\nDone! Screenshots saved to ${OUTPUT_DIR}`)
})()
