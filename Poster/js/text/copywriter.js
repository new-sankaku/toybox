(function (PF) {
'use strict';
const { composeNoun, personName, numeric, poolsFor } = PF;
const { styleTitle } = PF;
const { PATTERNS } = PF;
const { buildCatchPattern, buildQuotePattern } = PF;

const MAX_DEPTH = 6;
const SLOT_RE = /\{([A-Za-z]+(?::[A-Za-z]+)?(?:\.en)?)\}/g;

function wordOf(entry, wantEn) {
  if (typeof entry === 'string') { return entry; }
  return wantEn ? entry.en : entry.ja;
}

function fresh(rng, state, produce) {
  for (let i = 0; i < 5; i++) {
    const v = produce();
    if (!state.seen[v]) { state.seen[v] = 1; return v; }
  }
  return produce();
}

function resolveSlot(rng, genre, key, bindings, state) {
  if (bindings && Object.prototype.hasOwnProperty.call(bindings, key)) { return bindings[key]; }

  let name = key;
  let wantEn = false;
  if (name.length > 3 && name.slice(-3) === '.en') {
    wantEn = true;
    name = name.slice(0, -3);
  }

  if (name.indexOf('n:') === 0) { return numeric(rng, name.slice(2), genre); }

  if (name === 'quote') { return buildQuotePattern(rng, genre); }
  if (name === 'catchline') { return buildCatchPattern(rng, genre, { lenBudget: 'short' }).pattern; }

  if (name === 'noun') {
    return fresh(rng, state, () => {
      const core = composeNoun(rng, genre, null);
      return wantEn ? core.en : core.ja;
    });
  }
  if (name === 'person') {
    return fresh(rng, state, () => {
      const p = personName(rng, genre);
      return wantEn ? p.en : p.ja;
    });
  }

  const pools = poolsFor(genre);
  if (name === 'head') { return fresh(rng, state, () => wordOf(rng.pick(pools.nounHead), wantEn)); }
  if (name === 'tail') { return fresh(rng, state, () => wordOf(rng.pick(pools.nounTail), wantEn)); }
  if (pools[name]) { return fresh(rng, state, () => wordOf(rng.pick(pools[name]), wantEn)); }

  const genrePatterns = PATTERNS[genre];
  if (genrePatterns && genrePatterns[name]) { return fresh(rng, state, () => rng.pick(genrePatterns[name])); }

  throw new Error('unknown slot: ' + key + ' (genre ' + genre + ')');
}

function expand(rng, genre, pattern, bindings, depth, state) {
  const d = depth === undefined ? 0 : depth;
  if (d > MAX_DEPTH) { throw new Error('slot expansion too deep: ' + pattern); }
  const st = state || { seen: Object.create(null) };
  const out = pattern.replace(SLOT_RE, (m, key) => resolveSlot(rng, genre, key, bindings, st));
  if (out.indexOf('{') >= 0) { return expand(rng, genre, out, bindings, d + 1, st); }
  return out;
}

const ROLE_PLAN = {
  cinema: {
    base: ['title', 'catch', 'name', 'tag', 'credit', 'release', 'badge'],
    rich: ['extra'],
    lean: ['title', 'catch', 'name', 'credit', 'release']
  },
  gravure: {
    base: ['title', 'name', 'catch', 'tag', 'badge', 'release', 'code'],
    rich: ['credit', 'extra'],
    lean: ['name', 'title', 'tag', 'release', 'code']
  },
  novel: {
    base: ['title', 'name', 'catch', 'tag', 'badge', 'release'],
    rich: ['credit', 'extra'],
    lean: ['title', 'name', 'tag', 'badge']
  },
  asmr: {
    base: ['title', 'catch', 'credit', 'name', 'tag'],
    rich: ['badge'],
    lean: ['title', 'catch', 'credit', 'name']
  },
  game: {
    base: ['title', 'catch', 'tag', 'badge', 'credit', 'release'],
    rich: ['extra'],
    lean: ['title', 'catch', 'tag', 'badge', 'release']
  },
  adult: {
    base: ['title', 'name', 'catch', 'tag', 'badge', 'credit', 'release', 'code'],
    rich: ['extra'],
    lean: ['title', 'name', 'catch', 'badge', 'release', 'code']
  }
};

const CATCH_LIMIT = { cinema: 28, gravure: 24, novel: 25, asmr: 18, game: 20, adult: 14 };
const CATCH_LINES = { cinema: 3, gravure: 2, novel: 3, asmr: 2, game: 2, adult: 2 };
const CATCH_BUDGET = { cinema: 'long', gravure: 'mid', novel: 'long', asmr: 'mid', game: 'mid', adult: 'mid' };
const TITLE_BODY_LIMIT = { cinema: 12, gravure: 18, novel: 16, asmr: 14, game: 16, adult: 16 };
const TITLE_FINAL_LIMIT = { cinema: 14, gravure: 24, novel: 22, asmr: 16, game: 22, adult: 18 };
const ROLE_LIMIT = { tag: 30, badge: 30, release: 40, extra: 30, sub: 34, cast: 44 };
const LATIN_TITLE = { cinema: true, gravure: true, novel: false, asmr: true, game: true, adult: false };
const MEGA_LINE = { sash: [8, 14], main: [10, 18], spec: [20, 30], tail: [14, 24] };

const TITLE_SKELETON_CHANCE = {
  cinema: 0.8, gravure: 0.85, novel: 0.8, asmr: 1, game: 0.95, adult: 1
};

function visibleLen(text) {
  let max = 0;
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].length > max) { max = lines[i].length; }
  }
  return max;
}

function totalLen(text) {
  return text.split('\n').join('').length;
}

function hasEcho(text) {
  const s = text.split('\n').join('');
  for (let n = 4; n >= 3; n--) {
    for (let i = 0; i + n <= s.length; i++) {
      if (s.indexOf(s.slice(i, i + n), i + n) >= 0) { return true; }
    }
  }
  return false;
}

function fitPattern(rng, genre, list, limit) {
  let best = null;
  for (let i = 0; i < 8; i++) {
    const text = expand(rng, genre, rng.pick(list), null, 0);
    const score = visibleLen(text) + (hasEcho(text) ? 1000 : 0);
    if (score <= limit) { return text; }
    if (!best || score < best.score) { best = { text: text, score: score }; }
  }
  return best.text;
}

function splitUnits(text) {
  const units = [];
  let cur = '';
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    cur += ch;
    if (ch === '。' || ch === '！' || ch === '？') { units.push(cur); cur = ''; continue; }
    if (ch === '—' && text[i + 1] === '—') { cur += '—'; i++; units.push(cur); cur = ''; }
  }
  if (cur) { units.push(cur); }
  return units;
}

function wrapCatch(text, limit, maxLines) {
  if (visibleLen(text) <= limit) { return text; }
  const units = splitUnits(text);
  if (units.length < 2) { return null; }
  const lines = [];
  let cur = '';
  for (let i = 0; i < units.length; i++) {
    if (!cur) { cur = units[i]; continue; }
    if (cur.length + units[i].length <= limit) { cur += units[i]; continue; }
    lines.push(cur);
    cur = units[i];
  }
  if (cur) { lines.push(cur); }
  if (lines.length > maxLines) { return null; }
  const out = lines.join('\n');
  return visibleLen(out) <= limit ? out : null;
}

function fitCatch(rng, genre, limit) {
  const maxLines = CATCH_LINES[genre];
  let best = null;
  let axes = null;
  for (let i = 0; i < 16; i++) {
    const budget = i < 10 ? CATCH_BUDGET[genre] : 'short';
    const built = buildCatchPattern(rng, genre, { lenBudget: budget });
    const raw = expand(rng, genre, built.pattern, null, 0);
    const wrapped = wrapCatch(raw, limit, maxLines);
    if (wrapped !== null && !hasEcho(wrapped)) { return { text: wrapped, axes: built.axes }; }
    const len = visibleLen(raw);
    if (!best || len < best.len) { best = { text: raw, len: len }; axes = built.axes; }
  }
  return { text: best.text, axes: axes };
}

function markComposed(state, c) {
  state.seen[c.ja] = 1;
  if (!c.parts) { return; }
  for (let i = 0; i < c.parts.length; i++) {
    const ja = typeof c.parts[i] === 'string' ? c.parts[i] : c.parts[i].ja;
    if (ja) { state.seen[ja] = 1; }
  }
}

function resolveTitlePair(rng, genre, key, bindings, state) {
  if (bindings && Object.prototype.hasOwnProperty.call(bindings, key)) {
    state.seen[bindings[key]] = 1;
    return { ja: bindings[key], en: bindings[key + '.en'] || '' };
  }
  if (key.indexOf('n:') === 0) { return { ja: numeric(rng, key.slice(2), genre), en: '' }; }
  if (key === 'noun') {
    let c = composeNoun(rng, genre, null);
    for (let i = 0; i < 4 && state.seen[c.ja]; i++) { c = composeNoun(rng, genre, null); }
    markComposed(state, c);
    return { ja: c.ja, en: c.en };
  }
  if (key === 'person') {
    const p = personName(rng, genre);
    return { ja: p.ja, en: p.en };
  }
  const pools = poolsFor(genre);
  const poolKey = key === 'head' ? 'nounHead' : (key === 'tail' ? 'nounTail' : key);
  if (pools[poolKey]) {
    let entry = rng.pick(pools[poolKey]);
    for (let i = 0; i < 4; i++) {
      const seenKey = typeof entry === 'string' ? entry : entry.ja;
      if (!state.seen[seenKey]) { state.seen[seenKey] = 1; break; }
      entry = rng.pick(pools[poolKey]);
    }
    if (typeof entry === 'string') { return { ja: entry, en: '' }; }
    return { ja: entry.ja, en: entry.en };
  }
  const genrePatterns = PATTERNS[genre];
  if (genrePatterns && genrePatterns[key]) { return { ja: rng.pick(genrePatterns[key]), en: '' }; }
  throw new Error('unknown slot: ' + key + ' (genre ' + genre + ')');
}

function expandTitleSkeleton(rng, genre, skeleton, core) {
  const state = { seen: Object.create(null) };
  markComposed(state, core);
  const bindings = { noun: core.ja, 'noun.en': core.en };
  const enParts = [];
  let ja = skeleton.replace(SLOT_RE, (m, key) => {
    const pair = resolveTitlePair(rng, genre, key, bindings, state);
    if (key === 'noun' || key === 'noun.en') {
      delete bindings.noun;
      delete bindings['noun.en'];
    }
    if (pair.en) { enParts.push(pair.en); }
    return pair.ja;
  });
  if (ja.indexOf('{') >= 0) { ja = expand(rng, genre, ja, null, 1, state); }
  return { ja: ja, en: enParts.join(' ') };
}

function buildCore(rng, genre) {
  const limit = TITLE_BODY_LIMIT[genre];
  let best = null;
  for (let i = 0; i < 6; i++) {
    const core = composeNoun(rng, genre, null);
    let ja = core.ja;
    let en = core.en;
    let parts = core.parts;
    let skeleton = 'core';
    if (rng.chance(TITLE_SKELETON_CHANCE[genre])) {
      skeleton = rng.pick(PATTERNS[genre].title);
      if (skeleton !== '{noun}') {
        const built = expandTitleSkeleton(rng, genre, skeleton, core);
        ja = built.ja;
        en = built.en;
        parts = null;
      }
    }
    const cand = { ja: ja, en: en, parts: parts, mode: core.mode, skeleton: skeleton };
    if (ja.length <= limit) { return cand; }
    if (!best || ja.length < best.ja.length) { best = cand; }
  }
  return best;
}

function styleOnce(rng, genre, o, attempt) {
  const core = buildCore(rng, genre);
  const styleOpts = {
    vertical: !!o.verticalTitle,
    genre: genre,
    allowLatin: o.allowLatin !== false && LATIN_TITLE[genre] && attempt < 4,
    allowExclaim: o.allowExclaim !== false
  };
  return {
    styled: styleTitle(rng, { ja: core.ja, en: core.en, parts: core.parts }, styleOpts),
    core: core
  };
}

function buildTitle(rng, genre, opts) {
  const o = opts || {};
  const limit = TITLE_FINAL_LIMIT[genre];
  let best = null;
  for (let attempt = 0; attempt < 8; attempt++) {
    const cand = styleOnce(rng, genre, o, attempt);
    const len = visibleLen(cand.styled.text);
    if (len <= limit) { return cand; }
    if (!best || len < visibleLen(best.styled.text)) { best = cand; }
  }
  return best;
}

function fitLine(rng, genre, list, min, max) {
  let best = null;
  for (let i = 0; i < 10; i++) {
    const text = expand(rng, genre, rng.pick(list), null, 0);
    if (text.length >= min && text.length <= max) { return text; }
    const dist = text.length < min ? min - text.length : text.length - max;
    if (!best || dist < best.dist) { best = { text: text, dist: dist }; }
  }
  return best.text;
}

function buildMegaTitle(rng, opts) {
  const genre = 'adult';
  const o = opts || {};
  const mid = (MEGA_LINE.main[0] + MEGA_LINE.main[1]) / 2;
  let main = null;
  for (let attempt = 0; attempt < 8; attempt++) {
    const core = buildCore(rng, genre);
    const styled = styleTitle(rng, { ja: core.ja, en: core.en, parts: null }, {
      vertical: !!o.verticalTitle,
      genre: genre,
      allowLatin: false,
      allowExclaim: true
    });
    const len = styled.text.length;
    const cand = { styled: styled, core: core };
    if (len >= MEGA_LINE.main[0] && len <= MEGA_LINE.main[1]) { main = cand; break; }
    if (!main || Math.abs(len - mid) < Math.abs(main.styled.text.length - mid)) { main = cand; }
  }
  const lines = [];
  lines.push(fitLine(rng, genre, poolsFor(genre).sashWord, MEGA_LINE.sash[0], MEGA_LINE.sash[1]));
  lines.push(main.styled.text);
  lines.push(fitLine(rng, genre, PATTERNS.adult.megaSpec, MEGA_LINE.spec[0], MEGA_LINE.spec[1]));
  let body = lines.join('').length;
  if (rng.chance(0.8) || body < 46) {
    lines.push(fitLine(rng, genre, PATTERNS.adult.megaTail, MEGA_LINE.tail[0], MEGA_LINE.tail[1]));
    body = lines.join('').length;
  }
  return {
    styled: { text: lines.join('\n'), latin: '', axes: main.styled.axes },
    core: main.core
  };
}

function fillName(rng, genre) {
  if (genre === 'cinema') { return fitPattern(rng, genre, PATTERNS.cinema.cast, ROLE_LIMIT.cast); }
  if (genre === 'asmr') { return rng.pick(poolsFor(genre).circleName); }
  return personName(rng, genre).ja;
}

function fillCredit(rng, genre, density) {
  if (genre === 'cinema') {
    const src = poolsFor(genre).billing;
    const lines = density < 0.8 ? 3 : (density > 1.2 ? src.length : 6);
    const out = [];
    for (let i = 0; i < Math.min(lines, src.length); i++) {
      out.push(expand(rng, genre, src[i], null, 0));
    }
    return out.join('\n');
  }
  const list = PATTERNS[genre].credit;
  const idx = density < 0.8 ? 0 : (density > 1.2 ? list.length - 1 : rng.int(0, list.length - 1));
  return expand(rng, genre, list[idx], null, 0);
}

function fillRole(rng, genre, role, density, ctx) {
  const p = PATTERNS[genre];
  if (role === 'catch') {
    const limit = ctx.catchLimit;
    if (limit <= 0) { return ''; }
    const built = fitCatch(rng, genre, limit);
    ctx.catchAxes = built.axes;
    let text = built.text;
    if (density > 1.2 && p.sub && rng.chance(0.5)) {
      text = text + '\n' + fitPattern(rng, genre, p.sub, ROLE_LIMIT.sub);
    }
    return text;
  }
  if (role === 'name') { return fillName(rng, genre); }
  if (role === 'credit') { return fillCredit(rng, genre, density); }
  if (role === 'tag') { return fitPattern(rng, genre, p.tag, ROLE_LIMIT.tag); }
  if (role === 'badge') { return fitPattern(rng, genre, p.badge, ROLE_LIMIT.badge); }
  if (role === 'release') { return fitPattern(rng, genre, p.release, ROLE_LIMIT.release); }
  if (role === 'code') { return numeric(rng, 'code', genre); }
  if (role === 'extra') {
    if (genre === 'cinema' && density >= 1 && rng.chance(0.45)) {
      return expand(rng, genre, rng.pick(p.recommend), null, 0);
    }
    return fitPattern(rng, genre, p.extra, ROLE_LIMIT.extra);
  }
  throw new Error('unknown role: ' + role);
}

function generateCopy(rng, genre, density, opts) {
  const plan = ROLE_PLAN[genre];
  if (!plan) { throw new Error('unknown genre: ' + genre); }
  const d = typeof density === 'number' ? density : 1;
  const o = opts || {};

  let roles = d < 0.8 ? plan.lean.slice() : plan.base.slice();
  if (d > 1.2) {
    for (let i = 0; i < plan.rich.length; i++) {
      if (roles.indexOf(plan.rich[i]) < 0) { roles.push(plan.rich[i]); }
    }
  } else if (d >= 0.8) {
    for (let i = 0; i < plan.rich.length; i++) {
      if (roles.indexOf(plan.rich[i]) < 0 && rng.chance(0.35)) { roles.push(plan.rich[i]); }
    }
  }

  const ctx = {
    catchLimit: typeof o.catchLimit === 'number' ? o.catchLimit : CATCH_LIMIT[genre],
    catchAxes: null
  };

  const built = genre === 'adult' ? buildMegaTitle(rng, o) : buildTitle(rng, genre, o);

  const copy = {
    title: built.styled.text,
    catch: '',
    name: '',
    tag: '',
    credit: '',
    release: '',
    badge: '',
    code: '',
    extra: ''
  };

  for (let i = 0; i < roles.length; i++) {
    const role = roles[i];
    if (role === 'title') { continue; }
    copy[role] = fillRole(rng, genre, role, d, ctx);
  }

  if (built.styled.latin && built.styled.latin.length <= ROLE_LIMIT.extra && !copy.extra) {
    copy.extra = built.styled.latin;
  }

  copy.__axes = {
    genre: genre,
    density: d,
    titleMode: built.core.mode,
    titleSkeleton: built.core.skeleton,
    orthography: built.styled.axes,
    register: ctx.catchAxes ? ctx.catchAxes : [],
    catchLimit: ctx.catchLimit,
    look: genre + '/' + built.core.mode,
    roles: roles.slice()
  };

  return copy;
}

Object.assign(PF, { expand, generateCopy });
})(window.PF = window.PF || {});
