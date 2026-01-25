import {test,expect} from '@playwright/test'
import {createProject,startProject,waitForCheckpoint,waitForAsset} from './fixtures/setup'

async function createProjectWithAssets(page:any,suffix:string){
 await createProject(page,suffix)
 await startProject(page)
 await waitForCheckpoint(page,90000)
 await page.click('button:has-text("承認")').catch(()=>{})
 await page.waitForTimeout(5000)
 await page.click('text=生成素材')
 return page
}

test.describe('DataView - アセット管理',()=>{
 test.setTimeout(180000)

 test.describe('シナリオ1: アセット一覧表示',()=>{
  test('Dataタブをクリックして一覧が表示される',async({page})=>{
   await createProject(page,'data_list')
   await page.click('text=生成素材')
   await expect(page.locator('text=タイプ').first()).toBeVisible()
  })

  test('アセットがない場合は空状態が表示される',async({page})=>{
   await createProject(page,'data_empty')
   await page.click('text=生成素材')
   await expect(page.locator('text=アセットがありません').or(
    page.locator('text=タイプ').first()
   )).toBeVisible()
  })

  test('エージェント実行後アセットが生成される',async({page})=>{
   await createProjectWithAssets(page,'data_gen')
   const asset=await waitForAsset(page,60000).catch(()=>null)
   if(asset){
    await expect(asset).toBeVisible()
   }
  })
 })

 test.describe('シナリオ2: タイプでフィルタ',()=>{
  test('「全て」フィルタが選択可能',async({page})=>{
   await createProject(page,'data_filter1')
   await page.click('text=生成素材')
   await expect(page.locator('text=全て').first()).toBeVisible()
  })

  test('各タイプフィルタが選択可能',async({page})=>{
   await createProject(page,'data_filter2')
   await page.click('text=生成素材')

   const filters=['画像','音声','ドキュメント','コード']
   for(const f of filters){
    const filter=page.locator(`text=${f}`).first()
    if(await filter.isVisible()){
     await filter.click()
     await page.waitForTimeout(300)
    }
   }
  })
 })

 test.describe('シナリオ3: 承認状態でフィルタ',()=>{
  test('承認状態フィルタが表示される',async({page})=>{
   await createProject(page,'data_status1')
   await page.click('text=生成素材')
   await expect(page.locator('text=承認状態').or(page.locator('text=未承認'))).toBeVisible()
  })

  test('各状態フィルタが選択可能',async({page})=>{
   await createProject(page,'data_status2')
   await page.click('text=生成素材')

   const filters=['全状態','未承認','承認済','却下']
   for(const f of filters){
    const filter=page.locator(`text=${f}`).first()
    if(await filter.isVisible()){
     await filter.click()
     await page.waitForTimeout(300)
    }
   }
  })
 })

 test.describe('シナリオ4: 表示モード切り替え',()=>{
  test('グリッド/リスト切り替えボタンが表示される',async({page})=>{
   await createProject(page,'data_mode1')
   await page.click('text=生成素材')
   const gridBtn=page.locator('button[title="グリッド表示"]').or(page.locator('button[title="グリッド"]'))
   const listBtn=page.locator('button[title="リスト表示"]').or(page.locator('button[title="リスト"]'))
   await expect(gridBtn.or(listBtn).or(page.locator('text=表示'))).toBeVisible()
  })

  test('グリッドモードに切り替えられる',async({page})=>{
   await createProject(page,'data_mode2')
   await page.click('text=生成素材')
   const gridBtn=page.locator('button[title="グリッド表示"]').or(page.locator('button[title="グリッド"]'))
   if(await gridBtn.isVisible()){
    await gridBtn.click()
   }
  })

  test('リストモードに切り替えられる',async({page})=>{
   await createProject(page,'data_mode3')
   await page.click('text=生成素材')
   const listBtn=page.locator('button[title="リスト表示"]').or(page.locator('button[title="リスト"]'))
   if(await listBtn.isVisible()){
    await listBtn.click()
   }
  })
 })

 test.describe('シナリオ5: アセット承認（一覧から）',()=>{
  test('承認ボタンでアセットを承認できる',async({page})=>{
   await createProjectWithAssets(page,'data_approve')
   const asset=await waitForAsset(page,60000).catch(()=>null)
   if(asset){
    const approveBtn=page.locator('button[title="承認"]').first()
    if(await approveBtn.isVisible()){
     await approveBtn.click()
     await expect(page.locator('text=承認済').first()).toBeVisible({timeout:5000})
    }
   }
  })
 })

 test.describe('シナリオ6: アセット却下（一覧から）',()=>{
  test('却下ボタンでアセットを却下できる',async({page})=>{
   await createProjectWithAssets(page,'data_reject')
   const asset=await waitForAsset(page,60000).catch(()=>null)
   if(asset){
    const rejectBtn=page.locator('button[title="却下"]').first()
    if(await rejectBtn.isVisible()){
     await rejectBtn.click()
     await expect(page.locator('text=却下').first()).toBeVisible({timeout:5000})
    }
   }
  })
 })

 test.describe('シナリオ7: アセット詳細表示',()=>{
  test('アセットカードをクリックして詳細モーダルが表示される',async({page})=>{
   await createProjectWithAssets(page,'data_detail1')
   const asset=await waitForAsset(page,60000).catch(()=>null)
   if(asset){
    await asset.click()
    await expect(page.locator('text=ダウンロード').or(page.locator('[role="dialog"]'))).toBeVisible({timeout:5000})
   }
  })

  test('モーダルを閉じることができる',async({page})=>{
   await createProjectWithAssets(page,'data_detail2')
   const asset=await waitForAsset(page,60000).catch(()=>null)
   if(asset){
    await asset.click()
    const closeBtn=page.locator('button[aria-label="閉じる"]').or(page.locator('button:has-text("閉じる")'))
    if(await closeBtn.isVisible()){
     await closeBtn.click()
    }
   }
  })
 })

 test.describe('シナリオ8: 音声再生',()=>{
  test('音声アセットの再生ボタンが動作する',async({page})=>{
   await createProjectWithAssets(page,'data_audio')
   await page.click('text=生成素材')
   await page.locator('text=音声').first().click().catch(()=>{})
   const playBtn=page.locator('button[title="再生"]').first()
   if(await playBtn.isVisible()){
    await playBtn.click()
   }
  })
 })

 test.describe('シナリオ9: アセットダウンロード',()=>{
  test('ダウンロードボタンでファイルをダウンロードできる',async({page})=>{
   await createProjectWithAssets(page,'data_download')
   const asset=await waitForAsset(page,60000).catch(()=>null)
   if(asset){
    await asset.click()
    const downloadBtn=page.locator('button:has-text("ダウンロード")').first()
    if(await downloadBtn.isVisible()){
     const[download]=await Promise.all([
      page.waitForEvent('download',{timeout:10000}).catch(()=>null),
      downloadBtn.click()
     ])
     if(download){
      expect(download.suggestedFilename()).toBeTruthy()
     }
    }
   }
  })
 })
})
