import { numeric } from './morphology.js';

const BRACKETS = {
  none: { open: '', close: '' },
  kagi: { open: '「', close: '」' },
  nijuukagi: { open: '『', close: '』' },
  paren: { open: '（', close: '）' },
  kaku: { open: '［', close: '］' },
  yama: { open: '〈', close: '〉' },
  nijuuyama: { open: '《', close: '》' },
  dash: { open: '――', close: '――' }
};

const BRACKET_WEIGHTS = {
  cinema: [
    { v: 'none', w: 90 }, { v: 'kagi', w: 2 }, { v: 'nijuukagi', w: 2 }, { v: 'paren', w: 0 },
    { v: 'kaku', w: 1 }, { v: 'yama', w: 1 }, { v: 'nijuuyama', w: 0 }, { v: 'dash', w: 4 }
  ],
  gravure: [
    { v: 'none', w: 82 }, { v: 'kagi', w: 8 }, { v: 'nijuukagi', w: 4 }, { v: 'paren', w: 3 },
    { v: 'kaku', w: 0 }, { v: 'yama', w: 1 }, { v: 'nijuuyama', w: 0 }, { v: 'dash', w: 2 }
  ],
  novel: [
    { v: 'none', w: 70 }, { v: 'kagi', w: 0 }, { v: 'nijuukagi', w: 30 }, { v: 'paren', w: 0 },
    { v: 'kaku', w: 0 }, { v: 'yama', w: 0 }, { v: 'nijuuyama', w: 0 }, { v: 'dash', w: 0 }
  ],
  asmr: [
    { v: 'none', w: 100 }, { v: 'kagi', w: 0 }, { v: 'nijuukagi', w: 0 }, { v: 'paren', w: 0 },
    { v: 'kaku', w: 0 }, { v: 'yama', w: 0 }, { v: 'nijuuyama', w: 0 }, { v: 'dash', w: 0 }
  ],
  game: [
    { v: 'none', w: 92 }, { v: 'kagi', w: 1 }, { v: 'nijuukagi', w: 0 }, { v: 'paren', w: 0 },
    { v: 'kaku', w: 3 }, { v: 'yama', w: 2 }, { v: 'nijuuyama', w: 2 }, { v: 'dash', w: 0 }
  ],
  adult: [
    { v: 'none', w: 80 }, { v: 'kagi', w: 5 }, { v: 'nijuukagi', w: 0 }, { v: 'paren', w: 0 },
    { v: 'kaku', w: 6 }, { v: 'yama', w: 3 }, { v: 'nijuuyama', w: 3 }, { v: 'dash', w: 3 }
  ]
};

const NUMERAL_FORMS = {
  cinema: [{ v: 'chapterHead', w: 4 }, { v: 'chapterTail', w: 3 }],
  gravure: [{ v: 'chapterTail', w: 3 }, { v: 'volTail', w: 4 }, { v: 'editionTail', w: 2 }],
  novel: [{ v: 'chapterHead', w: 3 }, { v: 'chapterTail', w: 2 }, { v: 'partTail', w: 6 }],
  asmr: [{ v: 'chapterHead', w: 2 }, { v: 'volTail', w: 5 }],
  game: [{ v: 'chapterTail', w: 3 }, { v: 'volTail', w: 4 }, { v: 'editionTail', w: 2 }],
  adult: [{ v: 'chapterTail', w: 3 }, { v: 'volTail', w: 4 }, { v: 'editionTail', w: 2 }]
};

const PUNCT_WEIGHTS = {
  cinema: [{ v: 'none', w: 62 }, { v: 'period', w: 14 }, { v: 'comma', w: 14 }, { v: 'nakaguro', w: 10 }],
  gravure: [{ v: 'none', w: 56 }, { v: 'period', w: 16 }, { v: 'comma', w: 18 }, { v: 'nakaguro', w: 10 }],
  novel: [{ v: 'none', w: 60 }, { v: 'period', w: 12 }, { v: 'comma', w: 18 }, { v: 'nakaguro', w: 10 }],
  asmr: [{ v: 'none', w: 52 }, { v: 'period', w: 12 }, { v: 'comma', w: 16 }, { v: 'nakaguro', w: 20 }],
  game: [{ v: 'none', w: 66 }, { v: 'period', w: 4 }, { v: 'comma', w: 8 }, { v: 'nakaguro', w: 22 }],
  adult: [{ v: 'none', w: 58 }, { v: 'period', w: 8 }, { v: 'comma', w: 12 }, { v: 'nakaguro', w: 22 }]
};

const ELLIPSIS_WEIGHTS = {
  cinema: [{ v: 'none', w: 78 }, { v: 'lead', w: 8 }, { v: 'trail', w: 14 }],
  gravure: [{ v: 'none', w: 70 }, { v: 'lead', w: 10 }, { v: 'trail', w: 20 }],
  novel: [{ v: 'none', w: 72 }, { v: 'lead', w: 10 }, { v: 'trail', w: 18 }],
  asmr: [{ v: 'none', w: 58 }, { v: 'lead', w: 14 }, { v: 'trail', w: 28 }],
  game: [{ v: 'none', w: 88 }, { v: 'lead', w: 4 }, { v: 'trail', w: 8 }],
  adult: [{ v: 'none', w: 74 }, { v: 'lead', w: 8 }, { v: 'trail', w: 18 }]
};

const EXCLAIM_WEIGHTS = {
  cinema: [{ v: 'none', w: 84 }, { v: 'bang', w: 6 }, { v: 'quest', w: 4 }, { v: 'both', w: 3 }, { v: 'double', w: 3 }],
  gravure: [{ v: 'none', w: 76 }, { v: 'bang', w: 12 }, { v: 'quest', w: 4 }, { v: 'both', w: 4 }, { v: 'double', w: 4 }],
  novel: [{ v: 'none', w: 90 }, { v: 'bang', w: 4 }, { v: 'quest', w: 4 }, { v: 'both', w: 1 }, { v: 'double', w: 1 }],
  asmr: [{ v: 'none', w: 82 }, { v: 'bang', w: 8 }, { v: 'quest', w: 5 }, { v: 'both', w: 3 }, { v: 'double', w: 2 }],
  game: [{ v: 'none', w: 66 }, { v: 'bang', w: 16 }, { v: 'quest', w: 4 }, { v: 'both', w: 6 }, { v: 'double', w: 8 }],
  adult: [{ v: 'none', w: 70 }, { v: 'bang', w: 14 }, { v: 'quest', w: 6 }, { v: 'both', w: 5 }, { v: 'double', w: 5 }]
};

const EXCLAIM_MARK = { bang: '！', quest: '？', both: '！？', double: '！！' };

const LATIN_WEIGHTS = {
  cinema: [{ v: 'none', w: 34 }, { v: 'below', w: 26 }, { v: 'slash', w: 16 }, { v: 'paren', w: 8 }, { v: 'separate', w: 16 }],
  gravure: [{ v: 'none', w: 46 }, { v: 'below', w: 18 }, { v: 'slash', w: 12 }, { v: 'paren', w: 10 }, { v: 'separate', w: 14 }],
  novel: [{ v: 'none', w: 56 }, { v: 'below', w: 14 }, { v: 'slash', w: 8 }, { v: 'paren', w: 10 }, { v: 'separate', w: 12 }],
  asmr: [{ v: 'none', w: 48 }, { v: 'below', w: 16 }, { v: 'slash', w: 14 }, { v: 'paren', w: 10 }, { v: 'separate', w: 12 }],
  game: [{ v: 'none', w: 22 }, { v: 'below', w: 30 }, { v: 'slash', w: 14 }, { v: 'paren', w: 8 }, { v: 'separate', w: 26 }],
  adult: [{ v: 'none', w: 52 }, { v: 'below', w: 12 }, { v: 'slash', w: 12 }, { v: 'paren', w: 10 }, { v: 'separate', w: 14 }]
};

const SPACING_CHANCE = {
  cinema: 0.16, gravure: 0.12, novel: 0.14, asmr: 0.1, game: 0.2, adult: 0.14
};

const NUMERIC_CHANCE = {
  cinema: 0.1, gravure: 0.08, novel: 0.14, asmr: 0.18, game: 0.2, adult: 0.16
};

const PLAIN_JA_RE = /^[぀-ゟ゠-ヿ々一-鿿]{2,6}$/;

function partsJa(core) {
  if (!core.parts || core.parts.length < 2) { return null; }
  const out = [];
  for (let i = 0; i < core.parts.length; i++) {
    const p = core.parts[i];
    const ja = typeof p === 'string' ? p : p.ja;
    if (ja) { out.push(ja); }
  }
  return out.length >= 2 ? out : null;
}

export function styleTitle(rng, core, opts) {
  const o = opts || {};
  const genre = o.genre;
  if (!BRACKET_WEIGHTS[genre]) { throw new Error('unknown genre: ' + genre); }
  const tags = Array.isArray(o.tags) ? o.tags : null;
  let tagCount = 0;
  if (tags && tags.length >= 2) {
    tagCount = Math.min(tags.length, 3);
  }
  const allowLatin = o.allowLatin !== false && !!core.en;
  const allowExclaim = o.allowExclaim !== false;
  const vertical = !!o.vertical;
  const axes = [];

  let bracket = rng.weighted(BRACKET_WEIGHTS[genre]);
  if (tagCount > 0 && rng.chance(0.72)) { bracket = 'none'; }

  let punct = rng.weighted(PUNCT_WEIGHTS[genre]);
  const seg = partsJa(core);
  if ((punct === 'comma' || punct === 'nakaguro') && !seg) { punct = 'none'; }

  let ellipsis = rng.weighted(ELLIPSIS_WEIGHTS[genre]);
  let exclaim = allowExclaim ? rng.weighted(EXCLAIM_WEIGHTS[genre]) : 'none';

  if (punct === 'period' && exclaim !== 'none') { punct = 'none'; }
  if (punct === 'period' && ellipsis === 'trail') { punct = 'none'; }
  if (ellipsis !== 'none' && exclaim !== 'none' && !rng.chance(0.15)) { ellipsis = 'none'; }

  let latinMode = allowLatin ? rng.weighted(LATIN_WEIGHTS[genre]) : 'none';
  if (latinMode === 'below' && vertical) {
    latinMode = rng.weighted([{ v: 'separate', w: 6 }, { v: 'slash', w: 3 }, { v: 'none', w: 3 }]);
  }
  if (latinMode === 'paren' && (bracket === 'paren' || bracket === 'kaku')) { latinMode = 'slash'; }
  if (latinMode === 'slash' && bracket === 'dash') { latinMode = 'separate'; }

  let body;
  if (punct === 'comma') { body = seg.join('、'); }
  else if (punct === 'nakaguro') { body = seg.join('・'); }
  else { body = core.ja; }
  body = body.replace(/[・、]+$/, '');

  let numeralUsed = 'none';
  if (rng.chance(NUMERIC_CHANCE[genre])) {
    const form = rng.weighted(NUMERAL_FORMS[genre]);
    if (form === 'chapterHead') { body = numeric(rng, 'chapter', genre) + '　' + body; }
    else if (form === 'chapterTail') { body = body + '　' + numeric(rng, 'chapter', genre); }
    else if (form === 'volTail') { body = body + ' Vol.' + numeric(rng, 'few', genre); }
    else if (form === 'partTail') { body = body + numeric(rng, 'part', genre); }
    else { body = body + '　' + numeric(rng, 'edition', genre); }
    numeralUsed = form;
  }

  let spacing = 'none';
  if (numeralUsed === 'none' && punct !== 'comma' && punct !== 'nakaguro' &&
      PLAIN_JA_RE.test(body) && rng.chance(SPACING_CHANCE[genre])) {
    body = body.split('').join('　');
    spacing = 'wide';
  }

  const last = body.slice(-1);
  if ('。！？'.indexOf(last) >= 0) {
    if (ellipsis === 'trail' || exclaim !== 'none' || punct === 'period') { body = body.slice(0, -1); }
    else { punct = 'inherited'; }
  }

  if (ellipsis === 'lead') { body = '……' + body; }
  else if (ellipsis === 'trail') { body = body + '……'; }

  if (exclaim !== 'none') { body = body + EXCLAIM_MARK[exclaim]; }
  else if (punct === 'period') { body = body + '。'; }

  const b = BRACKETS[bracket];
  let text = b.open + body + b.close;

  const latinText = core.en ? String(core.en).toUpperCase() : '';
  if (latinText.length > 30) { latinMode = 'none'; }
  if (tagCount > 0 && (latinMode === 'slash' || latinMode === 'paren')) { latinMode = 'separate'; }
  if (latinMode === 'slash' && text.length + latinText.length > 18) { latinMode = 'separate'; }
  if (latinMode === 'paren' && text.length + latinText.length > 26) { latinMode = 'separate'; }
  let latinOut = '';
  if (latinMode === 'below') { text = text + '\n' + latinText; }
  else if (latinMode === 'slash') { text = text + ' / ' + latinText; }
  else if (latinMode === 'paren') { text = text + '（' + latinText + '）'; }
  else if (latinMode === 'separate') { latinOut = latinText; }

  if (tagCount > 0) {
    let prefix = '';
    for (let i = 0; i < tagCount; i++) { prefix += '【' + tags[i] + '】'; }
    text = prefix + text;
  }

  axes.push('tagrow:' + tagCount);
  axes.push('bracket:' + bracket);
  axes.push('punct:' + punct);
  axes.push('ellipsis:' + ellipsis);
  axes.push('exclaim:' + exclaim);
  axes.push('latin:' + latinMode);
  axes.push('spacing:' + spacing);
  axes.push('numeral:' + numeralUsed);

  return { text: text, latin: latinOut, axes: axes };
}
