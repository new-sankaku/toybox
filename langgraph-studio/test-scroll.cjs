const puppeteer = require('puppeteer')

async function testScroll() {
  const browser = await puppeteer.launch({ headless: false })
  const page = await browser.newPage()
  await page.setViewport({ width: 1280, height: 720 })

  try {
    await page.goto('http://localhost:5173', { waitUntil: 'networkidle2', timeout: 30000 })
    await page.waitForTimeout(2000)

    // 設定タブをクリック
    const configTab = await page.$('text=設定')
    if (configTab) {
      await configTab.click()
      await page.waitForTimeout(1000)
    } else {
      // ナビゲーションを探す
      const navItems = await page.$$('nav button, nav a, [role="tab"]')
      console.log('ナビ要素数:', navItems.length)
      for (const item of navItems) {
        const text = await item.evaluate(el => el.textContent)
        console.log('ナビ:', text)
        if (text && text.includes('設定')) {
          await item.click()
          await page.waitForTimeout(1000)
          break
        }
      }
    }

    // コスト設定ボタンをクリック
    const buttons = await page.$$('button')
    for (const btn of buttons) {
      const text = await btn.evaluate(el => el.textContent)
      if (text && text.includes('コスト設定')) {
        await btn.click()
        await page.waitForTimeout(1000)
        break
      }
    }

    // 右パネルのスクロール確認
    const rightPanel = await page.$('.overflow-y-auto')
    if (rightPanel) {
      const scrollInfo = await rightPanel.evaluate(el => ({
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        canScroll: el.scrollHeight > el.clientHeight,
        overflow: getComputedStyle(el).overflowY
      }))
      console.log('スクロール情報:', JSON.stringify(scrollInfo, null, 2))

      if (scrollInfo.canScroll) {
        console.log('✓ スクロール可能です')
        // 実際にスクロールしてみる
        await rightPanel.evaluate(el => el.scrollTop = 100)
        const newScrollTop = await rightPanel.evaluate(el => el.scrollTop)
        console.log('スクロール後の位置:', newScrollTop)
        if (newScrollTop > 0) {
          console.log('✓ スクロールが正常に動作しています')
        }
      } else {
        console.log('✗ スクロールできません - scrollHeight:', scrollInfo.scrollHeight, 'clientHeight:', scrollInfo.clientHeight)
      }
    } else {
      console.log('右パネルが見つかりません')
    }

    await page.screenshot({ path: 'scroll-test.png' })
    console.log('スクリーンショット保存: scroll-test.png')

  } catch (e) {
    console.error('エラー:', e.message)
  }

  await browser.close()
}

testScroll()
