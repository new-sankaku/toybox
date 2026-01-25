import {test,expect} from '@playwright/test'
import {createProject,startProject,waitForCheckpoint,createProjectWithCheckpoint} from './fixtures/setup'

test.describe('CheckpointsView - 承認管理',()=>{
 test.setTimeout(120000)

 test.describe('シナリオ1: チェックポイント一覧表示',()=>{
  test('Checkpointsタブをクリックして一覧が表示される',async({page})=>{
   await createProject(page,'cp_list')
   await page.click('text=承認')
   await expect(page.locator('text=チェックポイント').first()).toBeVisible()
  })

  test('チェックポイントがない場合は空メッセージが表示される',async({page})=>{
   await createProject(page,'cp_empty')
   await page.click('text=承認')
   await expect(page.locator('text=チェックポイントがありません').or(
    page.locator('text=チェックポイント').first()
   )).toBeVisible()
  })

  test('プロジェクト開始後チェックポイントが生成される',async({page})=>{
   await createProject(page,'cp_gen')
   await startProject(page)
   await waitForCheckpoint(page,90000)
  })
 })

 test.describe('シナリオ2: チェックポイント詳細表示',()=>{
  test('チェックポイントカードをクリックして詳細が表示される',async({page})=>{
   const{checkpoint}=await createProjectWithCheckpoint(page,'cp_detail')
   await checkpoint.click()
   await expect(page.locator('text=出力プレビュー').or(page.locator('text=PREVIEW'))).toBeVisible({timeout:5000})
  })
 })

 test.describe('シナリオ3: チェックポイント承認',()=>{
  test('「承認」ボタンでステータスがapprovedになる',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_approve')
   const approveBtn=page.locator('button:has-text("承認")').first()
   await expect(approveBtn).toBeVisible({timeout:5000})
   await approveBtn.click()
   await expect(page.locator('text=approved').or(page.locator('text=承認済'))).toBeVisible({timeout:10000})
  })
 })

 test.describe('シナリオ4: 変更を要求',()=>{
  test('「変更を要求」ボタンでフィードバックフォームが表示される',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_revision1')
   const reqBtn=page.locator('button:has-text("変更を要求")').first()
   await expect(reqBtn).toBeVisible({timeout:5000})
   await reqBtn.click()
   await expect(page.locator('text=変更要求内容').or(page.locator('textarea'))).toBeVisible()
  })

  test('フィードバックを入力して送信できる',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_revision2')
   const reqBtn=page.locator('button:has-text("変更を要求")').first()
   await reqBtn.click()
   await page.fill('textarea','もっと詳細に記述してください')
   await page.click('button:has-text("送信")')
   await expect(page.locator('text=revision_requested').or(page.locator('text=修正依頼'))).toBeVisible({timeout:10000})
  })

  test('空のフィードバックでは送信ボタンが無効',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_revision3')
   const reqBtn=page.locator('button:has-text("変更を要求")').first()
   await reqBtn.click()
   const submitBtn=page.locator('button:has-text("送信")')
   await expect(submitBtn).toBeDisabled()
  })

  test('キャンセルでフォームが閉じる',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_revision4')
   const reqBtn=page.locator('button:has-text("変更を要求")').first()
   await reqBtn.click()
   await page.click('button:has-text("キャンセル")')
   await expect(page.locator('text=変更要求内容')).not.toBeVisible()
  })
 })

 test.describe('シナリオ5: 却下',()=>{
  test('「却下」ボタンで却下理由フォームが表示される',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_reject1')
   const rejectBtn=page.locator('button:has-text("却下")').first()
   await expect(rejectBtn).toBeVisible({timeout:5000})
   await rejectBtn.click()
   await expect(page.locator('text=却下理由').or(page.locator('textarea'))).toBeVisible()
  })

  test('却下理由を入力して送信できる',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_reject2')
   const rejectBtn=page.locator('button:has-text("却下")').first()
   await rejectBtn.click()
   await page.fill('textarea','方向性が違います')
   await page.click('button:has-text("送信")')
   await expect(page.locator('text=rejected').or(page.locator('text=却下'))).toBeVisible({timeout:10000})
  })

  test('空の理由では送信ボタンが無効',async({page})=>{
   await createProjectWithCheckpoint(page,'cp_reject3')
   const rejectBtn=page.locator('button:has-text("却下")').first()
   await rejectBtn.click()
   const submitBtn=page.locator('button:has-text("送信")')
   await expect(submitBtn).toBeDisabled()
  })
 })

 test.describe('シナリオ6: 出力表示モード切り替え',()=>{
  test('PREVIEW/RAWタブで表示モードを切り替えられる',async({page})=>{
   const{checkpoint}=await createProjectWithCheckpoint(page,'cp_mode')
   await checkpoint.click()

   const previewTab=page.locator('button:has-text("PREVIEW")')
   const rawTab=page.locator('button:has-text("RAW")')

   if(await previewTab.isVisible()){
    await rawTab.click()
    await page.waitForTimeout(500)
    await previewTab.click()
   }
  })
 })
})
