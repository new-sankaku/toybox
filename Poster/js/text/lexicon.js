(function (PF) {
'use strict';

const GENRES = ['cinema', 'gravure', 'novel', 'asmr', 'game', 'adult'];

function requireSource(value, label) {
  if (!value) { throw new Error('lexicon源が未読込です: ' + label); }
  return value;
}

function mergeCommon() {
  const a = requireSource(PF.COMMON_A, 'COMMON_A (lexicon.common.a.js)');
  const b = requireSource(PF.COMMON_B, 'COMMON_B (lexicon.common.b.js)');
  const out = {};
  const srcs = [a, b];
  for (let i = 0; i < srcs.length; i++) {
    const keys = Object.keys(srcs[i]);
    for (let k = 0; k < keys.length; k++) {
      const key = keys[k];
      if (out[key]) { throw new Error('共通poolのkeyが重複しています: ' + key); }
      out[key] = srcs[i][key];
    }
  }
  return out;
}

function collectGenrePools() {
  const src = requireSource(PF.GENRE_POOLS, 'GENRE_POOLS (lexicon.<genre>.js)');
  const out = {};
  for (let i = 0; i < GENRES.length; i++) {
    const g = GENRES[i];
    out[g] = requireSource(src[g], 'GENRE_POOLS.' + g);
  }
  const words = requireSource(PF.ADULT_WORDS, 'ADULT_WORDS (lexicon.adult.words.js)');
  const keys = Object.keys(words);
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    if (out.adult[k]) { throw new Error('adult語彙のkeyが本体と重複しています: ' + k); }
    out.adult[k] = words[k];
  }
  return out;
}

const COMMON = mergeCommon();
const LEXICON = collectGenrePools();

Object.assign(PF, { COMMON, LEXICON, GENRES });
})(window.PF = window.PF || {});
