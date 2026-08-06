import { COMMON, LEXICON } from './lexicon.js';

const POOL_CACHE = {};

export function poolsFor(genre) {
  if (POOL_CACHE[genre]) { return POOL_CACHE[genre]; }
  const extra = LEXICON[genre];
  if (!extra) { throw new Error('unknown genre: ' + genre); }
  const merged = {};
  const keys = Object.keys(COMMON);
  for (let i = 0; i < keys.length; i++) {
    merged[keys[i]] = COMMON[keys[i]].slice();
  }
  const extKeys = Object.keys(extra);
  for (let i = 0; i < extKeys.length; i++) {
    const k = extKeys[i];
    if (merged[k]) { merged[k] = merged[k].concat(extra[k]); } else { merged[k] = extra[k].slice(); }
  }
  merged.__own = extra;
  POOL_CACHE[genre] = merged;
  return merged;
}

const GENRE_BIAS = 0.4;

function pickBiased(rng, pools, key) {
  const own = pools.__own[key];
  if (own && own.length > 0 && rng.chance(GENRE_BIAS)) { return rng.pick(own); }
  return rng.pick(pools[key]);
}

const MODE_WEIGHTS = {
  cinema: [
    { v: 'head', w: 6 }, { v: 'tail', w: 8 }, { v: 'compound', w: 20 },
    { v: 'genitive', w: 22 }, { v: 'pair', w: 10 }, { v: 'adjNoun', w: 22 }, { v: 'triple', w: 6 }
  ],
  gravure: [
    { v: 'head', w: 6 }, { v: 'tail', w: 12 }, { v: 'compound', w: 12 },
    { v: 'genitive', w: 26 }, { v: 'pair', w: 12 }, { v: 'adjNoun', w: 26 }, { v: 'triple', w: 4 }
  ],
  novel: [
    { v: 'head', w: 8 }, { v: 'tail', w: 10 }, { v: 'compound', w: 18 },
    { v: 'genitive', w: 24 }, { v: 'pair', w: 12 }, { v: 'adjNoun', w: 20 }, { v: 'triple', w: 8 }
  ],
  asmr: [
    { v: 'head', w: 8 }, { v: 'tail', w: 14 }, { v: 'compound', w: 14 },
    { v: 'genitive', w: 24 }, { v: 'pair', w: 14 }, { v: 'adjNoun', w: 22 }, { v: 'triple', w: 4 }
  ],
  game: [
    { v: 'head', w: 5 }, { v: 'tail', w: 8 }, { v: 'compound', w: 26 },
    { v: 'genitive', w: 20 }, { v: 'pair', w: 8 }, { v: 'adjNoun', w: 22 }, { v: 'triple', w: 11 }
  ],
  adult: [
    { v: 'head', w: 6 }, { v: 'tail', w: 12 }, { v: 'compound', w: 16 },
    { v: 'genitive', w: 28 }, { v: 'pair', w: 12 }, { v: 'adjNoun', w: 22 }, { v: 'triple', w: 4 }
  ]
};

function pickDistinct(rng, pool, taken) {
  for (let i = 0; i < 8; i++) {
    const w = rng.pick(pool);
    if (taken.indexOf(w.ja) < 0) { return w; }
  }
  return null;
}

export function composeNoun(rng, genre, opts) {
  const o = opts || {};
  const pools = poolsFor(genre);
  const modes = MODE_WEIGHTS[genre];
  if (!modes) { throw new Error('unknown genre: ' + genre); }
  const mode = o.mode ? o.mode : rng.weighted(modes);

  if (mode === 'head') {
    const h = pickBiased(rng, pools, 'nounHead');
    return { ja: h.ja, en: h.en, mode: mode, parts: [h] };
  }
  if (mode === 'tail') {
    const t = pickBiased(rng, pools, 'nounTail');
    return { ja: t.ja, en: t.en, mode: mode, parts: [t] };
  }
  if (mode === 'adjNoun') {
    const a = pickBiased(rng, pools, 'adj');
    const n = rng.chance(0.45) ? pickBiased(rng, pools, 'nounHead') : pickBiased(rng, pools, 'nounTail');
    return { ja: a.ja + n.ja, en: a.en + ' ' + n.en, mode: mode, parts: [a, n] };
  }

  const h = pickBiased(rng, pools, 'nounHead');
  const t = rng.chance(GENRE_BIAS) && pools.__own.nounTail
    ? pickDistinct(rng, pools.__own.nounTail, [h.ja])
    : pickDistinct(rng, pools.nounTail, [h.ja]);
  if (!t) { return composeNoun(rng, genre, { mode: 'adjNoun' }); }

  if (mode === 'compound') {
    return { ja: h.ja + t.ja, en: h.en + ' ' + t.en, mode: mode, parts: [h, t] };
  }
  if (mode === 'genitive') {
    return { ja: h.ja + 'の' + t.ja, en: t.en + ' OF ' + h.en, mode: mode, parts: [h, t] };
  }
  if (mode === 'pair') {
    return { ja: h.ja + 'と' + t.ja, en: h.en + ' AND ' + t.en, mode: mode, parts: [h, t] };
  }

  const h2 = pickDistinct(rng, pools.nounHead, [h.ja, t.ja]);
  if (!h2) { return { ja: h.ja + t.ja, en: h.en + ' ' + t.en, mode: 'compound', parts: [h, t] }; }
  const form = rng.weighted([{ v: 'flat', w: 5 }, { v: 'genPair', w: 3 }, { v: 'pairGen', w: 3 }]);
  if (form === 'flat') {
    return { ja: h.ja + h2.ja + t.ja, en: h.en + ' ' + h2.en + ' ' + t.en, mode: 'triple', parts: [h, h2, t] };
  }
  if (form === 'genPair') {
    return {
      ja: h.ja + 'の' + h2.ja + 'と' + t.ja,
      en: h2.en + ' OF ' + h.en + ' AND ' + t.en,
      mode: 'triple', parts: [h, h2, t]
    };
  }
  return {
    ja: h.ja + h2.ja + 'の' + t.ja,
    en: t.en + ' OF ' + h.en + ' ' + h2.en,
    mode: 'triple', parts: [h, h2, t]
  };
}

const NAME_STYLE = {
  cinema: { sep: '　', soft: 0.25, enOrder: 'giveFam' },
  gravure: { sep: '　', soft: 0.85, enOrder: 'giveFam' },
  novel: { sep: '　', soft: 0.35, enOrder: 'famGive' },
  asmr: { sep: '　', soft: 0.9, enOrder: 'giveFam' },
  game: { sep: '・', soft: 0.2, enOrder: 'famGive' },
  adult: { sep: '　', soft: 0.75, enOrder: 'giveFam' }
};

export function personName(rng, genre) {
  const pools = poolsFor(genre);
  const style = NAME_STYLE[genre];
  if (!style) { throw new Error('unknown genre: ' + genre); }
  const fam = rng.pick(pools.famName);
  let give;
  if (rng.chance(style.soft)) {
    const softs = pools.giveName.filter((g) => g.soft);
    give = rng.pick(softs);
  } else {
    const hards = pools.giveName.filter((g) => !g.soft);
    give = rng.pick(hards);
  }
  const ja = fam.ja + style.sep + give.ja;
  const en = style.enOrder === 'giveFam' ? give.en + ' ' + fam.en : fam.en + ' ' + give.en;
  return { ja: ja, en: en };
}

const CODE_FORMAT = {
  cinema: { letters: 3, digits: 4, sep: '-' },
  gravure: { letters: 3, digits: 3, sep: '-' },
  novel: { letters: 2, digits: 5, sep: '-' },
  asmr: { letters: 2, digits: 6, sep: '' },
  game: { letters: 4, digits: 5, sep: '-' },
  adult: { letters: 4, digits: 3, sep: '-' }
};

function letters(rng, n) {
  let s = '';
  for (let i = 0; i < n; i++) { s += String.fromCharCode(65 + rng.int(0, 25)); }
  return s;
}

function digits(rng, n) {
  let s = '';
  for (let i = 0; i < n; i++) { s += String(rng.int(0, 9)); }
  return s;
}

export function numeric(rng, kind, genre) {
  if (kind === 'volume') { return String(rng.int(2, 180)) + '万部'; }
  if (kind === 'week') { return String(rng.int(2, 14)) + '週連続'; }
  if (kind === 'minutes') { return String(rng.int(48, 186)) + '分'; }
  if (kind === 'track') { return '全' + String(rng.int(3, 18)) + 'トラック'; }
  if (kind === 'year') { return String(rng.int(1998, 2049)) + '年'; }
  if (kind === 'date') {
    const days = ['月', '火', '水', '木', '金', '土', '日'];
    return String(rng.int(1, 12)) + '月' + String(rng.int(1, 28)) + '日［' + rng.pick(days) + '］';
  }
  if (kind === 'price') {
    const yen = rng.int(6, 78) * 100 - 20;
    return '本体' + yen.toLocaleString('en-US') + '円＋税';
  }
  if (kind === 'code') {
    const f = CODE_FORMAT[genre];
    if (!f) { throw new Error('numeric code needs a known genre: ' + genre); }
    return letters(rng, f.letters) + f.sep + digits(rng, f.digits);
  }
  if (kind === 'rating') { return String(rng.int(35, 50) / 10) + '／5.0'; }
  if (kind === 'episode') { return '第' + String(rng.int(2, 24)) + '弾'; }
  if (kind === 'edition') {
    const form = rng.weighted([{ v: 'vol', w: 5 }, { v: 'ban', w: 4 }]);
    if (form === 'vol') { return 'Vol.' + String(rng.int(1, 12)); }
    return '第' + String(rng.int(2, 28)) + '版';
  }
  if (kind === 'chapter') { return '第' + String(rng.int(1, 24)) + '章'; }
  if (kind === 'count') { return String(rng.int(2, 99)); }
  if (kind === 'few') { return String(rng.int(2, 9)); }
  throw new Error('unknown numeric kind: ' + kind);
}
