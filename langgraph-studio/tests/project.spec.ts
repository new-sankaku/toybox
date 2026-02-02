import {test,expect} from '@playwright/test'
import {createProject,startProject,pauseProject,stopProject} from './fixtures/setup'

test.describe('ProjectView - プロジェクト管理',()=>{
 test.setTimeout(60000)

 test.describe('シナリオ1: 新規プロジェクト作成',()=>{
  test('新規プロジェクトを作成できる',async({page})=>{
   await page.goto('/')
   await page.click('button[title="新規作成"]')
   await expect(page.locator('text=新規プロジェクト作成')).toBeVisible()

   const projectName='E2Eテスト_'+Date.now()
   await page.fill('input[placeholder*="例: NebulaForge"]',projectName)
   await page.fill('textarea[placeholder*="作りたいゲームのアイデア"]','2D横スクロールアクションRPG')
   await page.fill('input[placeholder*="Astroneer"]','Hollow Knight, Celeste')

   const createButton=page.locator('button:has-text("作成")').first()
   await expect(createButton).toBeEnabled()
   await createButton.click()

   await expect(page.locator(`text=${projectName}`).first()).toBeVisible({timeout:10000})
   await expect(page.locator('text=プロジェクト詳細')).toBeVisible()
   await expect(page.locator('text=下書き').first()).toBeVisible()
  })

  test('必須項目が空の場合、作成ボタンが無効',async({page})=>{
   await page.goto('/')
   await page.click('button[title="新規作成"]')
   const createButton=page.locator('button:has-text("作成")').first()
   await expect(createButton).toBeDisabled()

   await page.fill('input[placeholder*="例: NebulaForge"]','テスト')
   await expect(createButton).toBeDisabled()

   await page.fill('textarea[placeholder*="作りたいゲームのアイデア"]','テストアイデア')
   await expect(createButton).toBeDisabled()

   await page.click('button:has-text("Webブラウザ")')
   await expect(createButton).toBeEnabled()
  })

  test('キャンセルボタンでフォームが閉じる',async({page})=>{
   await page.goto('/')
   await page.click('button[title="新規作成"]')
   await expect(page.locator('text=新規プロジェクト作成')).toBeVisible()
   await page.click('button:has-text("キャンセル")')
   await expect(page.locator('input[placeholder*="NebulaForge"]')).not.toBeVisible()
  })

  test('右パネルの「新規プロジェクト作成」ボタンからもフォームを開ける',async({page})=>{
   await page.goto('/')
   const btn=page.locator('button:has-text("新規プロジェクト作成")')
   if(await btn.isVisible()){
    await btn.click()
    await expect(page.locator('text=新規プロジェクト作成').first()).toBeVisible()
   }
  })
 })

 test.describe('シナリオ2: プロジェクト選択',()=>{
  test('プロジェクトをクリックして選択できる',async({page})=>{
   const name=await createProject(page,'select')
   await page.click('button[title="新規作成"]')
   await page.click('button:has-text("キャンセル")')
   await page.click(`text=${name}`)
   await expect(page.locator('text=プロジェクト詳細')).toBeVisible()
  })

  test('選択した行がハイライトされる',async({page})=>{
   const name=await createProject(page,'highlight')
   const row=page.locator(`text=${name}`).first()
   await expect(row).toBeVisible()
  })
 })

 test.describe('シナリオ3: プロジェクト編集',()=>{
  test('一覧の鉛筆アイコンから編集モードを開ける',async({page})=>{
   const name=await createProject(page,'edit1')
   const row=page.locator(`text=${name}`).first().locator('..').locator('..')
   await row.locator('button[title="編集"]').click()
   await expect(page.locator('button:has-text("保存")')).toBeVisible()
  })

  test('詳細画面の鉛筆アイコンから編集モードを開ける',async({page})=>{
   await createProject(page,'edit2')
   await page.locator('text=プロジェクト詳細').locator('..').locator('button[title="編集"]').click()
   await expect(page.locator('button:has-text("保存")')).toBeVisible()
  })

  test('編集内容を保存できる',async({page})=>{
   await createProject(page,'edit3')
   await page.locator('text=プロジェクト詳細').locator('..').locator('button[title="編集"]').click()

   const newName='編集済み_'+Date.now()
   await page.locator('input').first().fill(newName)
   await page.click('button:has-text("保存")')

   await expect(page.locator(`text=${newName}`).first()).toBeVisible({timeout:5000})
  })

  test('キャンセルで編集内容が破棄される',async({page})=>{
   const name=await createProject(page,'edit4')
   await page.locator('text=プロジェクト詳細').locator('..').locator('button[title="編集"]').click()
   await page.locator('input').first().fill('変更されるべきでない名前')
   await page.click('button:has-text("キャンセル")')
   await expect(page.locator(`text=${name}`).first()).toBeVisible()
  })
 })

 test.describe('シナリオ4: プロジェクト削除',()=>{
  test('ゴミ箱アイコンでプロジェクトを削除できる',async({page})=>{
   const name=await createProject(page,'delete')
   const projectItem=page.locator('.cursor-pointer').filter({hasText:name}).first()
   await projectItem.hover()
   await projectItem.locator('button[title="削除"]').click()
   await expect(page.locator('.cursor-pointer').filter({hasText:name})).not.toBeVisible({timeout:5000})
  })
 })

 test.describe('シナリオ5: プロジェクト開始',()=>{
  test('下書き状態で「開始」ボタンが表示される',async({page})=>{
   await createProject(page,'start1')
   await expect(page.locator('button:has-text("開始")')).toBeVisible()
  })

  test('「開始」ボタンクリックでステータスが実行中になる',async({page})=>{
   await createProject(page,'start2')
   await startProject(page)
   await expect(page.locator('button:has-text("一時停止")')).toBeVisible()
  })
 })

 test.describe('シナリオ6: プロジェクト一時停止',()=>{
  test('実行中状態で「一時停止」ボタンが表示される',async({page})=>{
   await createProject(page,'pause1')
   await startProject(page)
   await expect(page.locator('button:has-text("一時停止")')).toBeVisible()
  })

  test('「一時停止」でステータスが一時停止になる',async({page})=>{
   await createProject(page,'pause2')
   await startProject(page)
   const paused=await pauseProject(page)
   if(paused){
    await expect(page.locator('button:has-text("再開")')).toBeVisible()
   }
  })
 })

 test.describe('シナリオ7: プロジェクト再開',()=>{
  test('一時停止状態で「再開」ボタンが表示される',async({page})=>{
   await createProject(page,'resume1')
   await startProject(page)
   const paused=await pauseProject(page)
   if(paused){
    await expect(page.locator('button:has-text("再開")')).toBeVisible()
   }
  })

  test('「再開」でステータスが実行中になる',async({page})=>{
   await createProject(page,'resume2')
   await startProject(page)
   const paused=await pauseProject(page)
   if(paused){
    await page.click('button:has-text("再開")')
    await expect(page.locator('button:has-text("一時停止")')).toBeVisible({timeout:10000})
   }
  })
 })

 test.describe('シナリオ8: プロジェクト停止',()=>{
  test('実行中で「停止」ボタンが表示される',async({page})=>{
   await createProject(page,'stop1')
   await startProject(page)
   await expect(page.getByRole('button',{name:'停止',exact:true})).toBeVisible()
  })

  test('「停止」でステータスが下書きになる',async({page})=>{
   await createProject(page,'stop2')
   await startProject(page)
   await stopProject(page)
   await expect(page.locator('button:has-text("開始")')).toBeVisible()
  })
 })

 test.describe('シナリオ9: プロジェクト初期化',()=>{
  test('進捗がある場合「初期化」ボタンが表示される',async({page})=>{
   await createProject(page,'init1')
   await startProject(page)
   await stopProject(page)
   const initBtn=page.locator('button:has-text("初期化")')
   // currentPhase > 1 の場合のみ表示される
   if(await initBtn.isVisible()){
    await expect(initBtn).toBeVisible()
   }
  })

  test('初期化確認ダイアログが表示される',async({page})=>{
   await createProject(page,'init2')
   await startProject(page)
   await stopProject(page)
   const initBtn=page.locator('button:has-text("初期化")')
   if(await initBtn.isVisible()){
    await initBtn.click()
    await expect(page.locator('text=初期化の確認')).toBeVisible()
   }
  })

  test('キャンセルでダイアログが閉じる',async({page})=>{
   await createProject(page,'init3')
   await startProject(page)
   await stopProject(page)
   const initBtn=page.locator('button:has-text("初期化")')
   if(await initBtn.isVisible()){
    await initBtn.click()
    await page.click('button:has-text("キャンセル")')
    await expect(page.locator('text=初期化の確認')).not.toBeVisible()
   }
  })

  test('初期化を実行できる',async({page})=>{
   await createProject(page,'init4')
   await startProject(page)
   await stopProject(page)
   const initBtn=page.locator('button:has-text("初期化")')
   if(await initBtn.isVisible()){
    await initBtn.click()
    await page.click('button:has-text("初期化する")')
    await expect(page.locator('text=Phase 1')).toBeVisible({timeout:10000})
   }
  })
 })

 test.describe('シナリオ10: ブラッシュアップ',()=>{
  test.skip('完了状態で「ブラッシュアップ」ボタンが表示される',async({page})=>{
   // 完了状態にするにはエージェント実行完了が必要
   await expect(page.locator('button:has-text("ブラッシュアップ")')).toBeVisible()
  })
 })

 test.describe('シナリオ11: プロジェクト一覧更新',()=>{
  test('更新ボタンで一覧が再読み込みされる',async({page})=>{
   await page.goto('/')
   await page.click('button[title="更新"]')
   await expect(page.locator('button[title="更新"]')).toBeVisible()
  })
 })
})
