import { randomSeed } from './core/rng.js';
import { generatePoster } from './render/poster.js';

const els = {
  canvas: document.getElementById('poster'),
  placeholder: document.getElementById('placeholder'),
  file: document.getElementById('file'),
  drop: document.getElementById('drop'),
  log: document.getElementById('log'),
  genreList: document.getElementById('genreList'),
  btnShuffle: document.getElementById('btnShuffle'),
  btnRedraw: document.getElementById('btnRedraw'),
  btnSave: document.getElementById('btnSave'),
  optFace: document.getElementById('optFace'),
  optCutout: document.getElementById('optCutout'),
  optGrade: document.getElementById('optGrade'),
  optGlitch: document.getElementById('optGlitch'),
  optDensity: document.getElementById('optDensity'),
  optIntensity: document.getElementById('optIntensity'),
  optDebug: document.getElementById('optDebug')
};

const state = {
  bitmap: null,
  genre: 'cinema',
  seed: 1,
  busy: false
};

function log(html) {
  els.log.innerHTML = html;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

function reportInfo(info) {
  const face = info.faces.length > 0 ? (info.faces[0].src || 'detected') : 'none';
  const axes = info.copy && info.copy.__axes ? JSON.stringify(info.copy.__axes) : '-';
  log(
    'SEED <b>' + info.seed + '</b>　' + info.ms + 'ms\n' +
    'layout: ' + escapeHtml(info.layoutId) + '　fit: ' + escapeHtml(info.fit.kind) + '　crop: ' + escapeHtml(info.crop.mode) + '\n' +
    'filter: ' + escapeHtml(info.filterMode) + '　grade: ' + escapeHtml(info.gradeLook) + '\n' +
    'color: ' + escapeHtml(info.colorScheme) + '/' + escapeHtml(info.colorPolarity) +
      '　tint: ' + escapeHtml(info.tintStrategy) + '　colorfulness: ' + info.colorfulness.toFixed(2) + '\n' +
    'glitch: ' + escapeHtml(info.glitchOps.length ? info.glitchOps.join(',') : 'none') + '\n' +
    'face: ' + escapeHtml(face) + ' x' + info.faces.length +
      '　cutout: ' + (info.cutoutUsed ? 'on(' + Math.round(info.cutoutRatio * 100) + '%)' : 'off') + '\n' +
    'font: ' + escapeHtml(info.fonts.title.name + ' / ' + info.fonts.sub.name + ' / ' + info.fonts.latin.name) + '\n' +
    'text axes: ' + escapeHtml(axes)
  );
}

async function render() {
  if (!state.bitmap || state.busy) { return null; }
  state.busy = true;
  try {
    const info = await generatePoster({
      bitmap: state.bitmap,
      canvas: els.canvas,
      genre: state.genre,
      seed: state.seed,
      density: parseFloat(els.optDensity.value),
      intensity: parseInt(els.optIntensity.value, 10) / 100,
      avoidFace: els.optFace.checked,
      cutoutMode: els.optCutout.value,
      gradeMode: els.optGrade.value,
      glitchMode: els.optGlitch.value,
      debug: els.optDebug.checked
    });
    els.canvas.style.display = 'block';
    els.placeholder.style.display = 'none';
    els.btnSave.disabled = false;
    reportInfo(info);
    return info;
  } catch (err) {
    log('生成に失敗しました。\n' + escapeHtml(err && err.stack ? err.stack : String(err)));
    throw err;
  } finally {
    state.busy = false;
  }
}

function setGenre(genre) {
  state.genre = genre;
  const buttons = els.genreList.querySelectorAll('.genre');
  for (let i = 0; i < buttons.length; i++) {
    buttons[i].setAttribute('aria-pressed', buttons[i].dataset.genre === genre ? 'true' : 'false');
  }
}

async function loadBitmap(file) {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch (e) {
      return await createImageBitmap(file);
    }
  }
  return await new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('画像を読み込めません')); };
    img.src = url;
  });
}

async function acceptFile(file) {
  if (!file || file.type.indexOf('image/') !== 0) {
    log('画像ファイルを投入してください。');
    return;
  }
  log('読み込み中...');
  state.bitmap = await loadBitmap(file);
  els.btnShuffle.disabled = false;
  els.btnRedraw.disabled = false;
  state.seed = randomSeed();
  await render();
}

els.genreList.addEventListener('click', (ev) => {
  const btn = ev.target.closest('.genre');
  if (!btn) { return; }
  setGenre(btn.dataset.genre);
  if (state.bitmap) {
    state.seed = randomSeed();
    render();
  }
});

els.file.addEventListener('change', () => {
  if (els.file.files && els.file.files[0]) { acceptFile(els.file.files[0]); }
});

['dragenter', 'dragover'].forEach((name) => {
  els.drop.addEventListener(name, (ev) => {
    ev.preventDefault();
    els.drop.classList.add('hot');
  });
});
['dragleave', 'drop'].forEach((name) => {
  els.drop.addEventListener(name, (ev) => {
    ev.preventDefault();
    els.drop.classList.remove('hot');
  });
});
els.drop.addEventListener('drop', (ev) => {
  const dt = ev.dataTransfer;
  if (dt && dt.files && dt.files[0]) { acceptFile(dt.files[0]); }
});
window.addEventListener('dragover', (ev) => ev.preventDefault());
window.addEventListener('drop', (ev) => ev.preventDefault());

window.addEventListener('paste', (ev) => {
  const items = ev.clipboardData && ev.clipboardData.items;
  if (!items) { return; }
  for (let i = 0; i < items.length; i++) {
    if (items[i].type.indexOf('image/') === 0) {
      acceptFile(items[i].getAsFile());
      break;
    }
  }
});

els.btnShuffle.addEventListener('click', () => {
  state.seed = randomSeed();
  render();
});

els.btnRedraw.addEventListener('click', () => render());

els.btnSave.addEventListener('click', () => {
  els.canvas.toBlob((blob) => {
    if (!blob) { return; }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'poster_' + state.genre + '_' + state.seed + '.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }, 'image/png');
});

['optFace', 'optCutout', 'optGrade', 'optGlitch', 'optDensity', 'optIntensity', 'optDebug'].forEach((id) => {
  document.getElementById(id).addEventListener('change', () => {
    if (state.bitmap) { render(); }
  });
});

setGenre('cinema');

window.posterForge = {
  state: state,
  setGenre: setGenre,
  render: render,
  setBitmap: (bitmap) => { state.bitmap = bitmap; },
  setSeed: (seed) => { state.seed = seed >>> 0; },
  generate: generatePoster,
  canvas: els.canvas
};
