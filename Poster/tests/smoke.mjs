import { chromium } from 'playwright-core';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';
import { existsSync, mkdirSync, readdirSync } from 'node:fs';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const pageUrl = pathToFileURL(resolve(root, 'index.html')).href;
const GENRES = ['cinema', 'gravure', 'novel', 'asmr', 'game', 'adult'];
const SEEDS_PER_GENRE = Number(process.env.SEEDS || 4);
const shotDir = process.env.SHOT_DIR || resolve(here, 'shots');

function findPwBrowsers() {
  const base = '/opt/pw-browsers';
  if (!existsSync(base)) { return []; }
  return readdirSync(base)
    .filter((n) => n.startsWith('chromium-'))
    .map((n) => resolve(base, n, 'chrome-linux/chrome'));
}

function findChromium() {
  if (process.env.CHROMIUM_PATH) { return process.env.CHROMIUM_PATH; }
  const candidates = [
    ...findPwBrowsers(),
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  ].filter((p) => existsSync(p));
  if (candidates.length === 0) {
    throw new Error('chromium実行fileが見つかりません。CHROMIUM_PATH で指定してください');
  }
  return candidates[0];
}

let exitCode = 0;
let browser = null;

try {
  browser = await chromium.launch({ executablePath: findChromium() });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') { errors.push('console: ' + m.text()); } });

  await page.goto(pageUrl, { waitUntil: 'load' });
  await page.waitForFunction('typeof window.posterForge === "object"', null, { timeout: 15000 });

  if (errors.length > 0) {
    console.error('読込時にerror:\n' + errors.join('\n'));
    throw new Error('script読込に失敗');
  }

  await page.setInputFiles('#file', resolve(here, 'sample.jpg'));
  await page.waitForFunction('window.posterForge.state.bitmap !== null', null, { timeout: 30000 });
  const fileRoute = await page.evaluate(async () => {
    const cv = document.getElementById('poster');
    const px = cv.getContext('2d').getImageData(0, 0, 4, 4).data.length;
    const blob = await new Promise((r) => cv.toBlob(r, 'image/png'));
    return { bitmap: window.posterForge.state.bitmap.width, px: px, png: blob ? blob.size : 0 };
  });
  console.log(`file投入経路 OK  bitmap=${fileRoute.bitmap}px  getImageData=${fileRoute.px}bytes  PNG=${fileRoute.png}bytes`);

  mkdirSync(shotDir, { recursive: true });

  const results = await page.evaluate(async ({ genres, seedsPerGenre }) => {
    function makeTestImage(w, h, variant) {
      const cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      const c = cv.getContext('2d');
      const g = c.createLinearGradient(0, 0, w, h);
      const sets = [
        ['#20303f', '#c8a06a'],
        ['#f4f1ea', '#ffffff'],
        ['#101014', '#3a1d2e'],
        ['#dfe9f2', '#a8c8e8']
      ];
      const pair = sets[variant % sets.length];
      g.addColorStop(0, pair[0]);
      g.addColorStop(1, pair[1]);
      c.fillStyle = g;
      c.fillRect(0, 0, w, h);
      for (let i = 0; i < 40; i++) {
        c.fillStyle = 'rgba(' + ((i * 37) % 255) + ',' + ((i * 91) % 255) + ',' + ((i * 53) % 255) + ',0.28)';
        c.fillRect((i * 97) % w, (i * 61) % h, w * 0.08, h * 0.05);
      }
      c.fillStyle = '#e8b48c';
      c.beginPath();
      c.ellipse(w * 0.5, h * 0.3, w * 0.13, h * 0.16, 0, 0, Math.PI * 2);
      c.fill();
      c.fillStyle = '#3a2a20';
      c.beginPath();
      c.ellipse(w * 0.45, h * 0.27, w * 0.015, h * 0.012, 0, 0, Math.PI * 2);
      c.fill();
      c.beginPath();
      c.ellipse(w * 0.55, h * 0.27, w * 0.015, h * 0.012, 0, 0, Math.PI * 2);
      c.fill();
      return cv;
    }

    const shapes = [
      { w: 1200, h: 1600, label: 'portrait' },
      { w: 1600, h: 1200, label: 'landscape' },
      { w: 2400, h: 800, label: 'panorama' },
      { w: 700, h: 2100, label: 'tower' },
      { w: 1200, h: 1200, label: 'square' }
    ];
    const bitmaps = [];
    for (let i = 0; i < shapes.length; i++) {
      const cv = makeTestImage(shapes[i].w, shapes[i].h, i);
      bitmaps.push({ label: shapes[i].label, bitmap: await createImageBitmap(cv) });
    }

    const out = [];
    for (const genre of genres) {
      for (let s = 0; s < seedsPerGenre; s++) {
        const shape = bitmaps[s % bitmaps.length];
        const canvas = document.createElement('canvas');
        const record = { genre, shape: shape.label, seed: 1000 + s * 7919, ok: false };
        try {
          const info = await window.posterForge.generate({
            bitmap: shape.bitmap,
            canvas: canvas,
            genre: genre,
            seed: record.seed,
            density: 1,
            intensity: 0.65,
            decorIntensity: 0.8,
            avoidFace: true,
            cutoutMode: 'auto',
            gradeMode: 'auto',
            glitchMode: 'auto',
            debug: false
          });
          record.ok = true;
          record.ms = info.ms;
          record.layoutId = info.layoutId;
          record.gradeLook = info.gradeLook;
          record.cropMode = info.crop.mode;
          record.fit = info.fit.kind;
          record.glitch = info.glitchOps;
          record.title = info.copy.title;
          record.catch = info.copy['catch'];
          record.name = info.copy.name;
          record.code = info.copy.code;
          record.faces = info.faces.length;
        } catch (e) {
          record.error = String(e && e.stack ? e.stack : e);
        }
        out.push(record);
      }
    }
    return out;
  }, { genres: GENRES, seedsPerGenre: SEEDS_PER_GENRE });

  const failed = results.filter((r) => !r.ok);
  const times = results.filter((r) => r.ok).map((r) => r.ms);

  for (const r of results) {
    if (r.ok) {
      console.log(
        `[OK]   ${r.genre.padEnd(8)} ${String(r.ms).padStart(4)}ms  ${r.shape.padEnd(9)} ${r.fit.padEnd(9)} ` +
        `${r.layoutId.padEnd(20)} grade=${String(r.gradeLook).padEnd(16)} glitch=${(r.glitch || []).join('|')}`
      );
      console.log(`       title="${r.title}"  catch="${r.catch || ''}"  name="${r.name || ''}"  code="${r.code || ''}"`);
    } else {
      console.log(`[FAIL] ${r.genre} ${r.shape}\n${r.error}`);
    }
  }

  for (const genre of GENRES) {
    await page.evaluate(async (g) => {
      const cv = document.createElement('canvas');
      cv.width = 1400; cv.height = 1800;
      const c = cv.getContext('2d');
      const grad = c.createLinearGradient(0, 0, 1400, 1800);
      grad.addColorStop(0, '#1b2733');
      grad.addColorStop(1, '#d9c3a0');
      c.fillStyle = grad;
      c.fillRect(0, 0, 1400, 1800);
      c.fillStyle = '#e8b48c';
      c.beginPath();
      c.ellipse(700, 560, 200, 250, 0, 0, Math.PI * 2);
      c.fill();
      const bmp = await createImageBitmap(cv);
      window.posterForge.setBitmap(bmp);
      window.posterForge.setSeed(20260806);
      window.posterForge.setGenre(g);
      await window.posterForge.render();
    }, genre);
    await page.locator('#poster').screenshot({ path: resolve(shotDir, `${genre}.png`) });
  }

  const runtimeErrors = errors.filter((e) => !e.includes('favicon'));
  if (runtimeErrors.length > 0) {
    console.error('\n実行時error:\n' + runtimeErrors.join('\n'));
    exitCode = 1;
  }

  console.log(`\n成功 ${results.length - failed.length}/${results.length}　` +
    `中央値 ${times.sort((a, b) => a - b)[Math.floor(times.length / 2)]}ms　最大 ${Math.max(...times)}ms`);
  console.log('screenshot: ' + shotDir);
  if (failed.length > 0) { exitCode = 1; }
} catch (e) {
  console.error(e);
  exitCode = 1;
} finally {
  if (browser) { await browser.close(); }
}

process.exit(exitCode);
