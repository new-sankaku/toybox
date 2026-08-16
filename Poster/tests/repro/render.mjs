// specs/*.json を読み、decor.js + text.js で再現描画して out/<id>.png を書き出す。
// 使い方: node tests/repro/render.mjs [id ...]     (id 省略で全件)
import { chromium } from 'playwright-core';
import { pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..', '..');
const specDir = resolve(here, 'specs');
const cropDir = resolve(here, 'crops');
const outDir = resolve(here, 'out');
mkdirSync(outDir, { recursive: true });

function findChromium() {
  if (process.env.CHROMIUM_PATH) { return process.env.CHROMIUM_PATH; }
  const cands = [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium'
  ].filter((p) => existsSync(p));
  if (cands.length === 0) { throw new Error('chromiumが見つかりません。CHROMIUM_PATHで指定してください'); }
  return cands[0];
}

const want = process.argv.slice(2);
const ids = readdirSync(specDir)
  .filter((n) => n.endsWith('.json'))
  .map((n) => n.replace(/\.json$/, ''))
  .filter((id) => want.length === 0 || want.includes(id));

if (ids.length === 0) { console.log('対象なし'); process.exit(0); }

const browser = await chromium.launch({ executablePath: findChromium() });
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 1 });
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
page.on('console', (m) => { if (m.type() === 'error') { console.log('CONSOLE', m.text()); } });
await page.goto(pathToFileURL(resolve(here, 'page.html')).href, { waitUntil: 'load' });
await page.waitForFunction('window.reproReady === true');
await page.evaluate(() => document.fonts.ready);

let fail = 0;
for (const id of ids) {
  const job = JSON.parse(readFileSync(resolve(specDir, id + '.json'), 'utf8'));
  // bg 省略時は同名の下地画像を敷く（文字装飾だけを比較するため）
  if (!job.bg) {
    const b = resolve(cropDir, id + '.bg.png');
    const c = resolve(cropDir, id + '.png');
    if (existsSync(b)) { job.bg = { url: pathToFileURL(b).href }; }
    else if (existsSync(c)) { job.bg = { url: pathToFileURL(c).href }; }
  } else if (job.bg.file) {
    job.bg = { url: pathToFileURL(resolve(root, job.bg.file)).href };
  }
  try {
    const info = await page.evaluate((j) => window.renderTarget(j), job);
    await page.locator('#stage').screenshot({ path: resolve(outDir, id + '.png') });
    const s = info.map((r) => (r
      ? Math.round(r.size) + 'px/' + (r.regions ? r.regions.line + '行' : '?') + (r.truncated ? '(切詰)' : '')
      : 'null')).join(' ');
    console.log(`OK   ${id}  ${job.W}x${job.H}  [${s}]`);
  } catch (e) {
    fail++;
    console.log(`NG   ${id}  ${e.message}`);
  }
}
await browser.close();
process.exit(fail > 0 ? 1 : 0);
