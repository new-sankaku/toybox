import { chromium } from 'playwright-core';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const pageUrl = pathToFileURL(resolve(process.env.PAGE || resolve(root, 'index.html'))).href;
const GENRES = ['cinema', 'gravure', 'novel', 'asmr', 'game', 'adult'];
const SEEDS_PER_GENRE = Number(process.env.SEEDS || 24);
const CHROMA_MIN = 0.05;
const outDir = process.env.OUT_DIR || resolve(here, 'shots', 'decor');

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

// PF は各moduleが読込時に分割代入で掴むため、後からの差し替えでは届かない。
// window.PF を先に置き、drawSlot への代入を accessor で捕まえて包む。
function installHook() {
  const PF = {};
  window.PF = PF;
  let real = null;
  const cap = {
    on: false, want: null, genre: '', seed: 0, slotIdx: 0,
    meta: [], tiles: []
  };
  window.__cap = cap;

  function hex(rgb) {
    const v = (n) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
    return '#' + v(rgb[0]) + v(rgb[1]) + v(rgb[2]);
  }
  function luma(rgb) {
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  }
  // (max-min)/max は暗色で不安定（#0c0a0a が 0.167 になる）ため知覚的な OKLCh chroma で測る
  function sat(rgb) {
    return window.PF.srgbToOklch(rgb)[1];
  }
  function inkOf(spec) {
    if (spec.fill && spec.fill.stops && spec.fill.stops.length > 0) { return spec.fill.stops[0].rgb; }
    if (spec.strokes && spec.strokes.length > 0) { return spec.strokes[0].rgb; }
    return [0, 0, 0];
  }

  function wrapped(ctx, args) {
    const res = real(ctx, args);
    if (!cap.on || !res || !args || !args.decor) { return res; }
    const idx = cap.slotIdx++;
    const spec = args.decor;
    const ink = inkOf(spec);
    const ids = spec.axes.map((a) => a.split(':')[0]);
    const key = cap.genre + '|' + cap.seed + '|' + idx;
    cap.meta.push({
      key: key, genre: cap.genre, seed: cap.seed, idx: idx,
      role: args.slot.role, level: args.slot.decor || 'accent',
      big: !!args.slot.big, vertical: !!args.slot.vertical,
      axes: spec.axes.slice(), ids: ids,
      ink: hex(ink), inkLuma: luma(ink), inkSat: sat(ink),
      bg: hex(spec.effectiveBg), bgLuma: luma(spec.effectiveBg),
      plate: spec.plate ? hex(spec.plate.rgb) : null,
      strokes: (spec.strokes || []).map((s) => hex(s.rgb)),
      text: String(args.text).slice(0, 24)
    });
    if (cap.want && cap.want[key]) {
      const src = ctx.canvas;
      const pad = Math.max(res.size * 0.42, 14);
      const o = res.outer;
      let x = Math.max(0, Math.floor(o.x - pad));
      let y = Math.max(0, Math.floor(o.y - pad));
      let w = Math.min(src.width - x, Math.ceil(o.w + pad * 2));
      let h = Math.min(src.height - y, Math.ceil(o.h + pad * 2));
      if (w > 4 && h > 4) {
        const k = Math.min(1, 560 / w, 400 / h);
        const cv = document.createElement('canvas');
        cv.width = Math.max(4, Math.round(w * k));
        cv.height = Math.max(4, Math.round(h * k));
        cv.getContext('2d').drawImage(src, x, y, w, h, 0, 0, cv.width, cv.height);
        cap.tiles.push({ key: key, canvas: cv });
      }
    }
    return res;
  }

  Object.defineProperty(PF, 'drawSlot', {
    configurable: true, enumerable: true,
    get() { return real ? wrapped : undefined; },
    set(fn) { real = fn; }
  });
}

async function run() {
  const browser = await chromium.launch({ executablePath: findChromium() });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') { errors.push('console: ' + m.text()); } });

  await page.addInitScript(installHook);
  await page.goto(pageUrl, { waitUntil: 'load' });
  await page.waitForFunction('typeof window.posterForge === "object"', null, { timeout: 15000 });
  await page.setInputFiles('#file', resolve(here, 'sample.jpg'));
  await page.waitForFunction('window.posterForge.state.bitmap !== null', null, { timeout: 30000 });

  await page.exposeFunction('__progress', (msg) => console.log(msg));

  // pass 1: 全seedを回して意匠の出現をmetaだけ集める
  const meta = await page.evaluate(async ({ genres, n }) => {
    const cap = window.__cap;
    cap.on = true;
    cap.want = null;
    const bmp = window.posterForge.state.bitmap;
    for (const g of genres) {
      for (let s = 0; s < n; s++) {
        cap.genre = g;
        cap.seed = 1000 + s * 7919;
        cap.slotIdx = 0;
        await window.posterForge.generate({
          bitmap: bmp, canvas: document.createElement('canvas'), genre: g, seed: cap.seed,
          density: 1, intensity: 0.65, decorIntensity: 0.8, avoidFace: true,
          cutoutMode: 'auto', gradeMode: 'auto', glitchMode: 'auto', debug: false
        });
      }
      window.__progress('  収集 ' + g + ' 完了 (' + cap.meta.length + ' slot)');
    }
    cap.on = false;
    return cap.meta;
  }, { genres: GENRES, n: SEEDS_PER_GENRE });

  console.log(`\n収集: ${meta.length} slot / ${GENRES.length} genre × ${SEEDS_PER_GENRE} seed`);
  if (errors.length > 0) { console.error('page error:\n' + errors.join('\n')); }

  // 個別axisの代表と、genreごとの組み合わせ代表を選ぶ
  const axisCand = new Map();
  const comboCount = new Map();
  const comboRep = new Map();
  for (const m of meta) {
    const sig = m.ids.slice().sort().join('+');
    const ck = m.genre + '||' + sig;
    comboCount.set(ck, (comboCount.get(ck) || 0) + 1);
    const prev = comboRep.get(ck);
    if (!prev || score(m) > score(prev)) { comboRep.set(ck, m); }
    for (const id of m.ids) {
      const list = axisCand.get(id) || [];
      list.push(m);
      axisCand.set(id, list);
    }
  }
  function score(m) {
    // 単独で読み取りやすい見本を優先: 大きい / 装飾数が少ない
    return (m.big ? 40 : 0) + (m.level === 'title' ? 20 : 0) - m.ids.length * 3;
  }

  const axisPick = new Map();
  for (const [id, list] of axisCand) {
    list.sort((a, b) => score(b) - score(a));
    axisPick.set(id, list[0]);
  }

  const want = {};
  for (const m of axisPick.values()) { want[m.key] = true; }
  const combosByGenre = new Map();
  for (const [ck, m] of comboRep) {
    const g = ck.split('||')[0];
    const arr = combosByGenre.get(g) || [];
    arr.push({ m: m, n: comboCount.get(ck), sig: ck.split('||')[1] });
    combosByGenre.set(g, arr);
  }
  for (const [g, arr] of combosByGenre) {
    arr.sort((a, b) => b.n - a.n);
    const keep = arr.slice(0, 24);
    combosByGenre.set(g, keep);
    for (const e of keep) { want[e.m.key] = true; }
  }

  // pass 2: 必要なseedだけ描き直して該当slotを切り出す
  const needSeeds = new Map();
  for (const k of Object.keys(want)) {
    const [g, s] = k.split('|');
    const set = needSeeds.get(g) || new Set();
    set.add(Number(s));
    needSeeds.set(g, set);
  }
  const plan = [...needSeeds].map(([g, set]) => ({ genre: g, seeds: [...set] }));
  console.log(`切り出し対象: ${Object.keys(want).length} tile / 再生成 ${plan.reduce((a, p) => a + p.seeds.length, 0)} seed`);

  await page.evaluate(async ({ plan, want }) => {
    const cap = window.__cap;
    cap.on = true;
    cap.want = want;
    const bmp = window.posterForge.state.bitmap;
    for (const p of plan) {
      for (const seed of p.seeds) {
        cap.genre = p.genre;
        cap.seed = seed;
        cap.slotIdx = 0;
        await window.posterForge.generate({
          bitmap: bmp, canvas: document.createElement('canvas'), genre: p.genre, seed: seed,
          density: 1, intensity: 0.65, decorIntensity: 0.8, avoidFace: true,
          cutoutMode: 'auto', gradeMode: 'auto', glitchMode: 'auto', debug: false
        });
      }
      window.__progress('  切出 ' + p.genre + ' 完了 (' + cap.tiles.length + ' tile)');
    }
    cap.on = false;
  }, { plan: plan, want: want });

  mkdirSync(outDir, { recursive: true });

  // sheet 1: axis別一覧
  const axisRows = [...axisPick.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([id, m]) => ({
      key: m.key,
      title: id,
      sub: m.genre + ' / ' + m.level + '  ink ' + m.ink + '  bg ' + m.bg,
      note: m.axes.join(' + '),
      n: axisCand.get(id).length
    }));
  await saveSheet(page, outDir, 'catalog-axis.png',
    '文字装飾 axis 一覧 / ' + axisRows.length + '種', axisRows, 5);

  // sheet 2..: genreごとの実出現組み合わせ
  for (const g of GENRES) {
    const arr = combosByGenre.get(g) || [];
    const rows = arr.map((e) => ({
      key: e.m.key,
      title: e.n + '回  ' + e.m.role,
      sub: 'ink ' + e.m.ink + '  bg ' + e.m.bg + (e.m.plate ? '  plate ' + e.m.plate : ''),
      note: e.m.axes.join(' + ')
    }));
    await saveSheet(page, outDir, 'catalog-' + g + '.png',
      g + ' / 実際に出た組み合わせ 上位' + rows.length, rows, 4);
  }

  report(meta, axisCand);

  await browser.close();
}

async function saveSheet(page, dir, name, heading, rows, cols) {
  const dataUrl = await page.evaluate(({ heading, rows, cols }) => {
    const cap = window.__cap;
    const byKey = new Map(cap.tiles.map((t) => [t.key, t.canvas]));
    const CELL_W = 400;
    const IMG_H = 260;
    const CAP_H = 96;
    const GAP = 16;
    const PAD = 28;
    const HEAD = 74;
    const CELL_H = IMG_H + CAP_H;
    const use = rows.filter((r) => byKey.has(r.key));
    const n = Math.max(1, use.length);
    const rowCount = Math.ceil(n / cols);
    const W = PAD * 2 + cols * CELL_W + (cols - 1) * GAP;
    const H = HEAD + PAD * 2 + rowCount * CELL_H + (rowCount - 1) * GAP;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const c = cv.getContext('2d');
    c.fillStyle = '#14161a';
    c.fillRect(0, 0, W, H);
    c.fillStyle = '#f2f4f8';
    c.font = '600 30px "Yu Gothic UI","Noto Sans JP",sans-serif';
    c.textBaseline = 'alphabetic';
    c.fillText(heading, PAD, PAD + 34);
    c.fillStyle = '#5c6470';
    c.fillRect(PAD, HEAD - 8, W - PAD * 2, 2);

    function clip(text, max) {
      let t = text;
      if (c.measureText(t).width <= max) { return t; }
      while (t.length > 1 && c.measureText(t + '…').width > max) { t = t.slice(0, -1); }
      return t + '…';
    }
    function wrap(text, max, maxLines) {
      const words = text.split(' ');
      const out = [];
      let line = '';
      for (const w of words) {
        const t = line ? line + ' ' + w : w;
        if (c.measureText(t).width > max && line) { out.push(line); line = w; } else { line = t; }
        if (out.length === maxLines) { break; }
      }
      if (out.length < maxLines && line) { out.push(line); }
      if (out.length === maxLines) { out[maxLines - 1] = clip(out[maxLines - 1], max); }
      return out;
    }

    for (let i = 0; i < use.length; i++) {
      const r = use[i];
      const cx = PAD + (i % cols) * (CELL_W + GAP);
      const cy = HEAD + PAD + Math.floor(i / cols) * (CELL_H + GAP);
      c.fillStyle = '#1c1f25';
      c.fillRect(cx, cy, CELL_W, CELL_H);
      const tile = byKey.get(r.key);
      const k = Math.min((CELL_W - 16) / tile.width, (IMG_H - 16) / tile.height);
      const dw = tile.width * k;
      const dh = tile.height * k;
      c.drawImage(tile, cx + (CELL_W - dw) / 2, cy + (IMG_H - dh) / 2, dw, dh);
      c.strokeStyle = '#333941';
      c.lineWidth = 1;
      c.strokeRect(cx + 0.5, cy + 0.5, CELL_W - 1, IMG_H - 1);

      let ty = cy + IMG_H + 24;
      c.fillStyle = '#ffd98a';
      c.font = '600 17px Consolas,"Courier New",monospace';
      c.fillText(clip(r.title, CELL_W - 20), cx + 10, ty);
      ty += 20;
      c.fillStyle = '#9aa4b2';
      c.font = '400 14px Consolas,"Courier New",monospace';
      c.fillText(clip(r.sub, CELL_W - 20), cx + 10, ty);
      ty += 18;
      c.fillStyle = '#7f8998';
      c.font = '400 13px Consolas,"Courier New",monospace';
      for (const line of wrap(r.note, CELL_W - 20, 2)) {
        c.fillText(line, cx + 10, ty);
        ty += 16;
      }
    }
    return cv.toDataURL('image/png');
  }, { heading, rows, cols });

  const b64 = dataUrl.split(',')[1];
  const path = resolve(dir, name);
  writeFileSync(path, Buffer.from(b64, 'base64'));
  console.log('  出力 ' + path);
}

function report(meta, axisCand) {
  const buckets = [0, 0, 0, 0, 0];
  let gray = 0;
  for (const m of meta) {
    const i = Math.min(4, Math.floor(m.inkLuma * 5));
    buckets[i]++;
    if (m.inkSat < CHROMA_MIN) { gray++; }
  }
  const n = meta.length;
  const pct = (v) => (v * 100 / n).toFixed(1).padStart(5) + '%';
  console.log('\n=== 文字色の分布 (' + n + ' slot) ===');
  const labels = ['明度 0.0-0.2 (ほぼ黒)', '明度 0.2-0.4', '明度 0.4-0.6', '明度 0.6-0.8', '明度 0.8-1.0 (ほぼ白)'];
  for (let i = 0; i < 5; i++) { console.log('  ' + labels[i].padEnd(24) + pct(buckets[i]) + '  ' + buckets[i]); }
  console.log('  chroma<' + CHROMA_MIN + ' (無彩色)          ' + pct(gray) + '  ' + gray);

  console.log('\n=== genre別 文字色 ===');
  console.log('  genre     slot   有彩色  平均chroma  ほぼ黒   ほぼ白');
  for (const g of GENRES) {
    const list = meta.filter((m) => m.genre === g);
    if (list.length === 0) { continue; }
    const chroma = list.filter((m) => m.inkSat >= CHROMA_MIN).length;
    const mean = list.reduce((a, m) => a + m.inkSat, 0) / list.length;
    const blk = list.filter((m) => m.inkLuma < 0.2).length;
    const wht = list.filter((m) => m.inkLuma >= 0.8).length;
    console.log('  ' + g.padEnd(9)
      + String(list.length).padStart(5)
      + (chroma * 100 / list.length).toFixed(1).padStart(8) + '%'
      + mean.toFixed(3).padStart(9)
      + (blk * 100 / list.length).toFixed(1).padStart(8) + '%'
      + (wht * 100 / list.length).toFixed(1).padStart(7) + '%');
  }

  const top = [...axisCand.entries()].sort((a, b) => b[1].length - a[1].length);
  console.log('\n=== axis 出現数 上位15 ===');
  for (const [id, list] of top.slice(0, 15)) {
    console.log('  ' + id.padEnd(20) + String(list.length).padStart(5) + '  ' + (list.length * 100 / n).toFixed(1) + '%');
  }
  const src = readFileSync(resolve(root, 'js/render/decor.js'), 'utf8');
  const all = [...src.matchAll(/\{ id: '([a-z]+\.[A-Za-z]+)', group:/g)].map((m) => m[1]);
  const missing = all.filter((id) => !axisCand.has(id));
  console.log('\n=== 定義 ' + all.length + ' axis 中 出現 ' + (all.length - missing.length) + ' / 未出現 ' + missing.length + ' ===');
  console.log('  ' + (missing.length === 0 ? '(なし)' : missing.join(', ')));
}

run().catch((e) => { console.error(e); process.exit(1); });
