(function (PF) {
'use strict';
const { GENRES } = PF;

function collect() {
  const src = PF.GENRE_TEXT;
  if (!src) { throw new Error('文言templateが未読込です: GENRE_TEXT (register.<genre>.js)'); }
  const out = {};
  for (let i = 0; i < GENRES.length; i++) {
    const g = GENRES[i];
    const entry = src[g];
    if (!entry || !entry.patterns) { throw new Error('文言templateが未読込です: GENRE_TEXT.' + g + '.patterns'); }
    out[g] = entry.patterns;
  }
  return out;
}

const PATTERNS = collect();

Object.assign(PF, { PATTERNS });
})(window.PF = window.PF || {});
