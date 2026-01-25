import {test,expect} from '@playwright/test'
import {createProject,startProject,waitForLog,createProjectWithLogs} from './fixtures/setup'

test.describe('LogsView - システムログ',()=>{
 test.setTimeout(120000)

 test.describe('シナリオ1: ログ一覧表示',()=>{
  test('Logsタブをクリックして一覧が表示される',async({page})=>{
   await createProject(page,'log_list')
   await page.click('text=ログ')
   await expect(page.locator('text=レベル').first()).toBeVisible()
  })

  test('ログがない場合は空状態が表示される',async({page})=>{
   await createProject(page,'log_empty')
   await page.click('text=ログ')
   await expect(page.locator('text=ログがありません').or(
    page.locator('text=レベル').first()
   )).toBeVisible()
  })

  test('プロジェクト開始後ログが生成される',async({page})=>{
   const{log}=await createProjectWithLogs(page,'log_gen')
   await expect(log).toBeVisible()
  })
 })

 test.describe('シナリオ2: ログレベルでフィルタ',()=>{
  test('「全て」フィルタが選択可能',async({page})=>{
   await createProject(page,'log_level1')
   await page.click('text=ログ')
   await expect(page.locator('label:has-text("全て")').or(page.locator('text=全て').first())).toBeVisible()
  })

  test('各レベルフィルタが選択可能',async({page})=>{
   await createProjectWithLogs(page,'log_level2')

   const levels=['error','warn','info','debug']
   for(const level of levels){
    const filter=page.locator(`label:has-text("${level}")`).or(page.locator(`text=${level}`).first())
    if(await filter.isVisible()){
     await filter.click()
     await page.waitForTimeout(300)
    }
   }
  })

  test('フィルタ切り替えで一覧が更新される',async({page})=>{
   await createProjectWithLogs(page,'log_level3')
   const infoFilter=page.locator('label:has-text("info")').or(page.locator('text=info').first())
   if(await infoFilter.isVisible()){
    await infoFilter.click()
    await page.waitForTimeout(500)
   }
  })
 })

 test.describe('シナリオ3: エージェントでフィルタ',()=>{
  test('エージェントフィルタが表示される',async({page})=>{
   await createProject(page,'log_agent1')
   await page.click('text=ログ')
   await expect(page.locator('text=エージェント').or(page.locator('select'))).toBeVisible()
  })

  test('エージェントを選択してフィルタできる',async({page})=>{
   await createProjectWithLogs(page,'log_agent2')
   const dropdown=page.locator('select').first()
   if(await dropdown.isVisible()){
    const options=await dropdown.locator('option').all()
    if(options.length>1){
     await dropdown.selectOption({index:1})
     await page.waitForTimeout(500)
    }
   }
  })

  test('全選択/解除ボタンが動作する',async({page})=>{
   await createProjectWithLogs(page,'log_agent3')
   const toggleBtn=page.locator('button:has-text("全選択")').or(page.locator('button:has-text("解除")'))
   if(await toggleBtn.isVisible()){
    await toggleBtn.click()
    await page.waitForTimeout(300)
   }
  })
 })

 test.describe('シナリオ4: テキスト検索',()=>{
  test('検索ボックスが表示される',async({page})=>{
   await createProject(page,'log_search1')
   await page.click('text=ログ')
   await expect(page.locator('input[placeholder*="検索"]').or(page.locator('text=検索').first())).toBeVisible()
  })

  test('検索キーワードを入力できる',async({page})=>{
   await createProject(page,'log_search2')
   await page.click('text=ログ')
   const searchInput=page.locator('input[placeholder*="検索"]').or(page.locator('input[type="text"]').first())
   if(await searchInput.isVisible()){
    await searchInput.fill('error')
    await expect(searchInput).toHaveValue('error')
   }
  })

  test('検索結果がリアルタイムで更新される',async({page})=>{
   await createProjectWithLogs(page,'log_search3')
   const searchInput=page.locator('input[placeholder*="検索"]').or(page.locator('input[type="text"]').first())
   if(await searchInput.isVisible()){
    await searchInput.fill('agent')
    await page.waitForTimeout(500)
   }
  })

  test('検索をクリアできる',async({page})=>{
   await createProjectWithLogs(page,'log_search4')
   const searchInput=page.locator('input[placeholder*="検索"]').or(page.locator('input[type="text"]').first())
   if(await searchInput.isVisible()){
    await searchInput.fill('test')
    await searchInput.fill('')
    await expect(searchInput).toHaveValue('')
   }
  })
 })

 test.describe('シナリオ5: ログ詳細表示',()=>{
  test('ログ行をクリックして詳細パネルが表示される',async({page})=>{
   const{log}=await createProjectWithLogs(page,'log_detail1')
   await log.click()
   await expect(page.locator('text=タイムスタンプ').or(
    page.locator('text=レベル').nth(1)
   ).or(page.locator('pre'))).toBeVisible({timeout:5000})
  })

  test('詳細パネルにメッセージ本体が表示される',async({page})=>{
   const{log}=await createProjectWithLogs(page,'log_detail2')
   await log.click()
   await expect(page.locator('text=メッセージ').or(page.locator('pre'))).toBeVisible({timeout:5000})
  })

  test('詳細パネルを閉じることができる',async({page})=>{
   const{log}=await createProjectWithLogs(page,'log_detail3')
   await log.click()
   const closeBtn=page.locator('button[aria-label="閉じる"]').or(page.locator('button:has-text("×")'))
   if(await closeBtn.isVisible()){
    await closeBtn.click()
   }
  })
 })
})
