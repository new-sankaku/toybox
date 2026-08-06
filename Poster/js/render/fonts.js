export const FONT_JP = [
  {
    name: 'mincho',
    kind: 'mincho',
    weight: '400',
    scaleHint: [0.94, 1.02],
    css: '"Hiragino Mincho ProN","Hiragino Mincho Pro","Yu Mincho",YuMincho,"YuMincho","Noto Serif JP","Source Han Serif JP","MS PMincho","Songti SC",serif'
  },
  {
    name: 'mincho-heavy',
    kind: 'mincho',
    weight: '700',
    scaleHint: [0.9, 1.0],
    css: '"Hiragino Mincho ProN","Yu Mincho Demibold","Yu Mincho",YuMincho,"Noto Serif JP","Source Han Serif JP","MS PMincho",serif'
  },
  {
    name: 'gothic',
    kind: 'gothic',
    weight: '500',
    scaleHint: [0.92, 1.04],
    css: '"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic UI","Yu Gothic",YuGothic,"Noto Sans JP","Source Han Sans JP","MS PGothic",sans-serif'
  },
  {
    name: 'gothic-heavy',
    kind: 'gothic-heavy',
    weight: '900',
    scaleHint: [0.82, 1.04],
    css: '"Hiragino Sans W8","Hiragino Kaku Gothic StdN W8","Hiragino Sans","Yu Gothic UI Semibold","Yu Gothic",YuGothic,"Noto Sans JP","Source Han Sans JP","Arial Black","MS PGothic",sans-serif'
  },
  {
    name: 'maru',
    kind: 'maru',
    weight: '700',
    scaleHint: [0.94, 1.08],
    css: '"Hiragino Maru Gothic ProN","Hiragino Maru Gothic Pro","Rounded Mplus 1c","Corporate Round","M PLUS Rounded 1c","Yu Gothic UI","Noto Sans JP",sans-serif'
  },
  {
    name: 'gothic-condensed',
    kind: 'condensed',
    weight: '700',
    scaleHint: [0.7, 0.88],
    css: '"Arial Narrow","Liberation Sans Narrow","Hiragino Sans","Yu Gothic UI","Noto Sans JP","MS PGothic",sans-serif'
  }
];

export const FONT_LATIN = [
  {
    name: 'latin-serif',
    kind: 'serif',
    weight: '400',
    scaleHint: [0.94, 1.04],
    css: '"Trajan Pro","Optima","Palatino Linotype","Book Antiqua",Palatino,Georgia,"Times New Roman",serif'
  },
  {
    name: 'latin-sans',
    kind: 'sans',
    weight: '600',
    scaleHint: [0.92, 1.06],
    css: '"Helvetica Neue",Helvetica,Arial,"Segoe UI","Noto Sans",sans-serif'
  },
  {
    name: 'latin-condensed',
    kind: 'condensed',
    weight: '600',
    scaleHint: [0.62, 0.86],
    css: '"Arial Narrow","Liberation Sans Narrow","Franklin Gothic Medium","Helvetica Neue",Arial,sans-serif'
  },
  {
    name: 'latin-display',
    kind: 'display',
    weight: '700',
    scaleHint: [0.78, 1.0],
    css: 'Impact,Haettenschweiler,"Arial Black","Franklin Gothic Heavy","Helvetica Neue",sans-serif'
  },
  {
    name: 'latin-mono',
    kind: 'mono',
    weight: '400',
    scaleHint: [0.9, 1.0],
    css: '"SFMono-Regular","SF Mono",Menlo,Consolas,"DejaVu Sans Mono","Courier New",monospace'
  }
];

export const PALETTES = {
  cinema: ['#ffffff', '#f2ece0', '#0d0c0a', '#d8c27a', '#b8b4ad', '#a8291f', '#1b2a3a', '#e6d8b8'],
  gravure: ['#ffffff', '#fff4f7', '#ff5f8f', '#ffd23f', '#2ec4d8', '#1a1a1a', '#ff7a3d', '#7d4bd8'],
  novel: ['#111111', '#ffffff', '#f5efe2', '#9b1b1b', '#1d3557', '#c8a24a', '#3b3027', '#7a2b3a'],
  asmr: ['#ffffff', '#fdf3fb', '#ffb7d5', '#c3aefc', '#9fe6dd', '#a7d3ff', '#4a3f55', '#ffe6a7'],
  game: ['#ffffff', '#e8f2ff', '#0a0a0c', '#e0b64a', '#c8ccd4', '#d4232a', '#2b8cf0', '#7a2ec8'],
  adult: ['#ffffff', '#0a0a0a', '#ff2d78', '#ffe600', '#ff3b1f', '#00e5ff', '#b026ff', '#ffd0e2']
};

const JP_WEIGHTS = {
  cinema: { title: { 'mincho-heavy': 3, mincho: 2, gothic: 2, 'gothic-condensed': 2, 'gothic-heavy': 1, maru: 0.2 },
            sub: { 'gothic-condensed': 3, gothic: 3, mincho: 2, 'mincho-heavy': 1, 'gothic-heavy': 0.6, maru: 0.2 } },
  gravure: { title: { maru: 3, 'gothic-heavy': 3, gothic: 2, 'mincho-heavy': 1, 'gothic-condensed': 0.6, mincho: 0.4 },
             sub: { gothic: 3, maru: 2, 'gothic-condensed': 1.5, 'gothic-heavy': 1, mincho: 0.6, 'mincho-heavy': 0.4 } },
  novel: { title: { 'mincho-heavy': 5, mincho: 3, gothic: 1, 'gothic-heavy': 0.6, 'gothic-condensed': 0.4, maru: 0.2 },
           sub: { mincho: 4, 'mincho-heavy': 2, gothic: 1.5, 'gothic-condensed': 1, 'gothic-heavy': 0.5, maru: 0.2 } },
  asmr: { title: { maru: 6, gothic: 2, 'gothic-heavy': 1.2, mincho: 0.8, 'mincho-heavy': 0.4, 'gothic-condensed': 0.3 },
          sub: { maru: 4, gothic: 2.5, 'gothic-condensed': 0.8, mincho: 0.8, 'gothic-heavy': 0.5, 'mincho-heavy': 0.3 } },
  game: { title: { 'gothic-heavy': 6, 'gothic-condensed': 2, gothic: 2, 'mincho-heavy': 1.2, maru: 0.4, mincho: 0.3 },
          sub: { 'gothic-condensed': 3, gothic: 3, 'gothic-heavy': 2, mincho: 0.8, 'mincho-heavy': 0.6, maru: 0.3 } },
  adult: { title: { 'gothic-heavy': 7, gothic: 2, 'gothic-condensed': 2, maru: 1, 'mincho-heavy': 1, mincho: 0.3 },
           sub: { 'gothic-heavy': 4, gothic: 3, 'gothic-condensed': 2, maru: 1, 'mincho-heavy': 0.6, mincho: 0.3 } }
};

const LATIN_WEIGHTS = {
  cinema: { 'latin-serif': 4, 'latin-condensed': 3, 'latin-sans': 2, 'latin-mono': 1, 'latin-display': 0.6 },
  gravure: { 'latin-sans': 3, 'latin-serif': 2, 'latin-condensed': 1.2, 'latin-display': 1, 'latin-mono': 0.5 },
  novel: { 'latin-serif': 4, 'latin-mono': 1.2, 'latin-sans': 1, 'latin-condensed': 0.8, 'latin-display': 0.3 },
  asmr: { 'latin-sans': 3, 'latin-serif': 1.2, 'latin-mono': 1, 'latin-condensed': 0.6, 'latin-display': 0.4 },
  game: { 'latin-display': 4, 'latin-condensed': 3, 'latin-sans': 2, 'latin-serif': 1, 'latin-mono': 0.8 },
  adult: { 'latin-display': 3, 'latin-sans': 2, 'latin-condensed': 2, 'latin-serif': 0.8, 'latin-mono': 0.6 }
};

function indexByName(list) {
  const map = {};
  for (let i = 0; i < list.length; i++) { map[list[i].name] = list[i]; }
  return map;
}

const JP_BY_NAME = indexByName(FONT_JP);
const LATIN_BY_NAME = indexByName(FONT_LATIN);

function toItems(table) {
  const items = [];
  const keys = Object.keys(table);
  for (let i = 0; i < keys.length; i++) { items.push({ v: keys[i], w: table[keys[i]] }); }
  return items;
}

function resolveGenre(table, genre) {
  return table[genre] ? genre : 'cinema';
}

export function pickFonts(rng, genre) {
  const jpKey = resolveGenre(JP_WEIGHTS, genre);
  const latinKey = resolveGenre(LATIN_WEIGHTS, genre);
  const title = JP_BY_NAME[rng.weighted(toItems(JP_WEIGHTS[jpKey].title))];
  let sub = JP_BY_NAME[rng.weighted(toItems(JP_WEIGHTS[jpKey].sub))];
  if (sub === title && rng.chance(0.6)) {
    sub = JP_BY_NAME[rng.weighted(toItems(JP_WEIGHTS[jpKey].sub))];
  }
  const latin = LATIN_BY_NAME[rng.weighted(toItems(LATIN_WEIGHTS[latinKey]))];
  return { title: title, sub: sub, latin: latin };
}
