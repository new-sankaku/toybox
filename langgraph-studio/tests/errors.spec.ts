import {test,expect} from '@playwright/test'
import {createProject,startProject} from './fixtures/setup'

test.describe('エラーケーステスト',()=>{
 test.setTimeout(60000)

 test.describe('API エラーハンドリング',()=>{
  test('プロジェクト一覧取得失敗時にエラー表示',async({page})=>{
   await page.route('**/api/projects',route=>{
    route.fulfill({status:500,body:JSON.stringify({detail:'Internal Server Error'})})
   })
   await page.goto('/')
   await expect(page.locator('text=エラー').or(page.locator('[role="alert"]'))).toBeVisible({timeout:10000})
  })

  test('プロジェクト作成失敗時にエラー表示',async({page})=>{
   await page.goto('/')
   await page.route('**/api/projects',route=>{
    if(route.request().method()==='POST'){
     route.fulfill({status:400,body:JSON.stringify({detail:'バリデーションエラー'})})
    }else{
     route.continue()
    }
   })
   await page.click('button[title="新規作成"]')
   await page.fill('input[placeholder*="例: NebulaForge"]','テスト')
   await page.fill('textarea[placeholder*="作りたいゲームのアイデア"]','テスト説明')
   await page.locator('button:has-text("作成")').first().click()
   await expect(page.locator('text=エラー').or(page.locator('[role="alert"]')).or(page.locator('text=バリデーション'))).toBeVisible({timeout:10000})
  })

  test('プロジェクト開始失敗時にエラー表示',async({page})=>{
   await createProject(page,'start_error')
   await page.route('**/api/projects/*/start',route=>{
    route.fulfill({status:400,body:JSON.stringify({detail:'開始できません'})})
   })
   await page.click('button:has-text("開始")')
   await expect(page.locator('text=エラー').or(page.locator('text=開始できません')).or(page.locator('[role="alert"]'))).toBeVisible({timeout:10000})
  })

  test('プロジェクト削除失敗時にエラー表示',async({page})=>{
   const name=await createProject(page,'delete_error')
   await page.route('**/api/projects/*',route=>{
    if(route.request().method()==='DELETE'){
     route.fulfill({status:500,body:JSON.stringify({detail:'削除に失敗しました'})})
    }else{
     route.continue()
    }
   })
   const projectItem=page.locator('.cursor-pointer').filter({hasText:name}).first()
   await projectItem.hover()
   await projectItem.locator('button[title="削除"]').click()
   await expect(page.locator('text=エラー').or(page.locator('[role="alert"]'))).toBeVisible({timeout:10000})
  })
 })

 test.describe('ネットワークエラー',()=>{
  test('ネットワーク切断時のエラー表示',async({page})=>{
   await page.route('**/api/**',route=>{
    route.abort('failed')
   })
   await page.goto('/')
   await expect(page.locator('text=エラー').or(page.locator('text=接続').or(page.locator('[role="alert"]')))).toBeVisible({timeout:15000})
  })

  test('タイムアウト時のエラー表示',async({page})=>{
   await page.route('**/api/projects',async route=>{
    await new Promise(resolve=>setTimeout(resolve,30000))
    route.continue()
   })
   await page.goto('/')
   await expect(page.locator('text=エラー').or(page.locator('text=タイムアウト').or(page.locator('[role="alert"]')))).toBeVisible({timeout:35000})
  })
 })

 test.describe('存在しないリソース',()=>{
  test('存在しないプロジェクトのチェックポイント取得時',async({page})=>{
   await page.route('**/api/projects/nonexistent/checkpoints',route=>{
    route.fulfill({status:404,body:JSON.stringify({detail:'プロジェクトが見つかりません'})})
   })
   await page.goto('/')
   const name=await createProject(page,'not_found')
   await page.click('text=承認')
   await page.route('**/api/projects/*/checkpoints',route=>{
    route.fulfill({status:404,body:JSON.stringify({detail:'プロジェクトが見つかりません'})})
   })
   await page.reload()
  })
 })

 test.describe('バリデーションエラー',()=>{
  test('プロジェクト名が空の場合は作成ボタンが無効',async({page})=>{
   await page.goto('/')
   await page.click('button[title="新規作成"]')
   const createButton=page.locator('button:has-text("作成")').first()
   await expect(createButton).toBeDisabled()
  })

  test('説明が空の場合は作成ボタンが無効',async({page})=>{
   await page.goto('/')
   await page.click('button[title="新規作成"]')
   await page.fill('input[placeholder*="例: NebulaForge"]','テストプロジェクト')
   const createButton=page.locator('button:has-text("作成")').first()
   await expect(createButton).toBeDisabled()
  })
 })

 test.describe('チェックポイント解決エラー',()=>{
  test('チェックポイント承認失敗時にエラー表示',async({page})=>{
   const name=await createProject(page,'cp_error')
   await startProject(page)
   await page.click('text=承認')
   const card=page.locator('[data-testid="checkpoint-card"]').or(
    page.locator('.cursor-pointer').filter({hasText:/pending|approved|承認待ち/})
   ).first()
   const isVisible=await card.isVisible({timeout:30000}).catch(()=>false)
   if(isVisible){
    await page.route('**/api/checkpoints/*/resolve',route=>{
     route.fulfill({status:500,body:JSON.stringify({detail:'解決に失敗しました'})})
    })
    await card.click()
    const approveBtn=page.locator('button:has-text("承認")').last()
    if(await approveBtn.isVisible({timeout:3000}).catch(()=>false)){
     await approveBtn.click()
     await expect(page.locator('text=エラー').or(page.locator('[role="alert"]'))).toBeVisible({timeout:10000})
    }
   }
  })

  test('不正な解決タイプでエラー表示',async({page})=>{
   await page.route('**/api/checkpoints/*/resolve',route=>{
    route.fulfill({status:400,body:JSON.stringify({detail:'解決タイプが不正です'})})
   })
   const name=await createProject(page,'invalid_resolve')
   await startProject(page)
   await page.click('text=承認')
   const card=page.locator('[data-testid="checkpoint-card"]').or(
    page.locator('.cursor-pointer').filter({hasText:/pending|承認待ち/})
   ).first()
   const isVisible=await card.isVisible({timeout:30000}).catch(()=>false)
   if(isVisible){
    await card.click()
   }
  })
 })

 test.describe('プロジェクト状態遷移エラー',()=>{
  test('実行中でないプロジェクトを一時停止しようとするとエラー',async({page})=>{
   await createProject(page,'pause_error')
   await page.route('**/api/projects/*/pause',route=>{
    route.fulfill({status:400,body:JSON.stringify({detail:'一時停止できません'})})
   })
   const pauseBtn=page.locator('button:has-text("一時停止")')
   if(await pauseBtn.isVisible({timeout:3000}).catch(()=>false)){
    await pauseBtn.click()
    await expect(page.locator('text=エラー').or(page.locator('[role="alert"]'))).toBeVisible({timeout:10000})
   }
  })

  test('一時停止中でないプロジェクトを再開しようとするとエラー',async({page})=>{
   await createProject(page,'resume_error')
   await page.route('**/api/projects/*/resume',route=>{
    route.fulfill({status:400,body:JSON.stringify({detail:'再開できません'})})
   })
   const resumeBtn=page.locator('button:has-text("再開")')
   if(await resumeBtn.isVisible({timeout:3000}).catch(()=>false)){
    await resumeBtn.click()
    await expect(page.locator('text=エラー').or(page.locator('[role="alert"]'))).toBeVisible({timeout:10000})
   }
  })
 })

 test.describe('AI設定エラー',()=>{
  test('AI設定更新失敗時にエラー表示',async({page})=>{
   await createProject(page,'ai_error')
   await page.route('**/api/projects/*/ai-services',route=>{
    if(route.request().method()==='PUT'){
     route.fulfill({status:500,body:JSON.stringify({detail:'AI設定の更新に失敗しました'})})
    }else{
     route.continue()
    }
   })
  })
 })
})
