(function (PF) {
'use strict';
const { GENRES } = PF;

function collect() {
  const src = PF.GENRE_TEXT;
  if (!src) { throw new Error('惹句bankが未読込です: GENRE_TEXT (register.<genre>.js)'); }
  const out = {};
  for (let i = 0; i < GENRES.length; i++) {
    const g = GENRES[i];
    const entry = src[g];
    if (!entry || !entry.register) { throw new Error('惹句bankが未読込です: GENRE_TEXT.' + g + '.register'); }
    out[g] = entry.register;
  }
  return out;
}

const REGISTER = collect();

const LEN_ORDER = { short: 0, mid: 1, long: 2 };
const PLACEHOLDER_RE = /\[([ABCNSL])\]/g;

const BANK_OF = { A: 'clauseA', B: 'clauseB', C: 'connective', N: 'nominal', S: 'scale', L: 'nominal' };

function pickFresh(rng, pool, used) {
  let v = rng.pick(pool);
  for (let i = 0; i < 5; i++) {
    if (!used[v]) { break; }
    v = rng.pick(pool);
  }
  used[v] = 1;
  return v;
}

function headWord(text, n) {
  return text.slice(0, n);
}

function hasAdjacentEcho(pattern) {
  const units = pattern.split(/[。、！？]|——/);
  for (let i = 0; i < units.length - 1; i++) {
    const a = units[i];
    const b = units[i + 1];
    if (!a || !b) { continue; }
    for (let n = 4; n >= 2; n--) {
      if (a.length >= n && b.length >= n && headWord(a, n) === headWord(b, n)) { return true; }
    }
  }
  return false;
}

function buildFromForm(rng, reg, form, used) {
  return form.t.replace(PLACEHOLDER_RE, (m, key) => pickFresh(rng, reg[BANK_OF[key]], used));
}

function buildCatchPattern(rng, genre, opts) {
  const reg = REGISTER[genre];
  if (!reg) { throw new Error('unknown genre: ' + genre); }
  const o = opts || {};
  const budget = typeof o.lenBudget === 'string' ? LEN_ORDER[o.lenBudget] : 2;
  const allowed = reg.forms.filter((f) => LEN_ORDER[f.len] <= budget);
  const pool = allowed.length > 0 ? allowed : reg.forms;
  const form = rng.weighted(pool.map((f) => ({ v: f, w: f.w })));

  let pattern = buildFromForm(rng, reg, form, Object.create(null));
  for (let i = 0; i < 4 && hasAdjacentEcho(pattern); i++) {
    pattern = buildFromForm(rng, reg, form, Object.create(null));
  }

  return {
    pattern: pattern,
    axes: ['register:' + reg.person, 'form:' + form.id, 'len:' + form.len]
  };
}

function buildQuoteOnce(rng, reg) {
  const used = Object.create(null);
  const a = pickFresh(rng, reg.clauseA, used);
  const b = pickFresh(rng, reg.clauseB, used);
  const c = pickFresh(rng, reg.connective, used);
  return rng.weighted([
    { v: a + '。' + c + '、' + b + '。', w: 4 },
    { v: a + '——' + b + '。', w: 3 },
    { v: b + '。', w: 2 },
    { v: pickFresh(rng, reg.scale, used) + '。', w: 3 }
  ]);
}

function buildQuotePattern(rng, genre) {
  const reg = REGISTER[genre];
  if (!reg) { throw new Error('unknown genre: ' + genre); }
  let out = buildQuoteOnce(rng, reg);
  for (let i = 0; i < 4 && hasAdjacentEcho(out); i++) {
    out = buildQuoteOnce(rng, reg);
  }
  return out;
}

Object.assign(PF, { REGISTER, buildCatchPattern, buildQuotePattern });
})(window.PF = window.PF || {});
