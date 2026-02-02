import {Page,expect} from '@playwright/test'

export async function createProject(page:Page,suffix:string){
 await page.goto('/')
 await page.click('button[title="新規作成"]')
 const name=`E2E_${suffix}_${Date.now()}`
 await page.fill('input[placeholder*="例: NebulaForge"]',name)
 await page.fill('textarea[placeholder*="作りたいゲームのアイデア"]','シンプルな2Dアクションゲーム。プレイヤーはジャンプと攻撃ができる。')
 await page.locator('button:has-text("作成")').first().click()
 await expect(page.locator(`text=${name}`).first()).toBeVisible({timeout:10000})
 return name
}

export async function startProject(page:Page){
 await page.click('button:has-text("開始")')
 await expect(page.locator('button:has-text("一時停止")')).toBeVisible({timeout:10000})
}

export async function pauseProject(page:Page):Promise<boolean>{
 const pauseBtn=page.locator('button:has-text("一時停止")')
 if(await pauseBtn.isVisible({timeout:3000}).catch(()=>false)){
  await pauseBtn.click()
  const resumed=await page.locator('button:has-text("再開")').isVisible({timeout:10000}).catch(()=>false)
  return resumed
 }
 return false
}

export async function stopProject(page:Page){
 await page.getByRole('button',{name:'停止',exact:true}).click()
 await expect(page.locator('button:has-text("開始")')).toBeVisible({timeout:10000})
}

export async function waitForCheckpoint(page:Page,timeout=60000){
 await page.click('text=承認')
 const card=page.locator('[data-testid="checkpoint-card"]').or(
  page.locator('.cursor-pointer').filter({hasText:/pending|approved|承認待ち/})
 ).first()
 await expect(card).toBeVisible({timeout})
 return card
}

export async function waitForAsset(page:Page,timeout=60000){
 await page.click('text=生成素材')
 const card=page.locator('[data-testid="asset-card"]').or(
  page.locator('.border').filter({has:page.locator('img,svg')})
 ).first()
 await expect(card).toBeVisible({timeout})
 return card
}

export async function waitForLog(page:Page,timeout=30000){
 await page.click('text=ログ')
 const logRow=page.locator('[data-testid="log-row"]').or(
  page.locator('.cursor-pointer').filter({hasText:/info|error|warn|debug/})
 ).first()
 await expect(logRow).toBeVisible({timeout})
 return logRow
}

export async function createProjectWithCheckpoint(page:Page,suffix:string){
 const name=await createProject(page,suffix)
 await startProject(page)
 const checkpoint=await waitForCheckpoint(page)
 return {name,checkpoint}
}

export async function createProjectWithAsset(page:Page,suffix:string){
 const name=await createProject(page,suffix)
 await startProject(page)
 await waitForCheckpoint(page)
 await page.click('button:has-text("承認")')
 await page.waitForTimeout(5000)
 const asset=await waitForAsset(page)
 return {name,asset}
}

export async function createProjectWithLogs(page:Page,suffix:string){
 const name=await createProject(page,suffix)
 await startProject(page)
 await page.waitForTimeout(3000)
 const log=await waitForLog(page)
 return {name,log}
}
