import { composeNoun, personName, numeric, poolsFor } from './morphology.js';
import { styleTitle } from './orthography.js';
import { PATTERNS } from './patterns.js';

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

export function expand(rng, genre, pattern, bindings, depth, state) {
  const d = depth === undefined ? 0 : depth;
  if (d > MAX_DEPTH) { throw new Error('slot expansion too deep: ' + pattern); }
  const st = state || { seen: Object.create(null) };
  const out = pattern.replace(SLOT_RE, (m, key) => resolveSlot(rng, genre, key, bindings, st));
  if (out.indexOf('{') >= 0) { return expand(rng, genre, out, bindings, d + 1, st); }
  return out;
}

const ROLE_PLAN = {
  cinema: {
    base: ['title', 'catch', 'tag', 'credit', 'release'],
    rich: ['badge', 'extra'],
    lean: ['title', 'catch', 'credit']
  },
  gravure: {
    base: ['title', 'catch', 'name', 'tag', 'badge', 'release', 'code'],
    rich: ['credit', 'extra'],
    lean: ['title', 'name', 'tag', 'release']
  },
  novel: {
    base: ['title', 'catch', 'name', 'tag', 'badge', 'release'],
    rich: ['credit', 'extra'],
    lean: ['title', 'name', 'tag', 'badge']
  },
  asmr: {
    base: ['title', 'catch', 'name', 'tag', 'credit', 'release', 'badge'],
    rich: ['code', 'extra'],
    lean: ['title', 'name', 'credit', 'tag']
  },
  game: {
    base: ['title', 'catch', 'tag', 'badge', 'credit', 'release'],
    rich: ['code', 'extra'],
    lean: ['title', 'catch', 'tag', 'release']
  },
  adult: {
    base: ['title', 'catch', 'name', 'tag', 'badge', 'release', 'code'],
    rich: ['credit', 'extra'],
    lean: ['title', 'name', 'tag', 'badge']
  }
};

const TITLE_SKELETON_CHANCE = {
  cinema: 0.55, gravure: 0.65, novel: 0.55, asmr: 0.7, game: 0.5, adult: 0.6
};

function resolveTitlePair(rng, genre, key, bindings, state) {
  if (bindings && Object.prototype.hasOwnProperty.call(bindings, key)) {
    return { ja: bindings[key], en: bindings[key + '.en'] || '' };
  }
  if (key.indexOf('n:') === 0) {
    const v = numeric(rng, key.slice(2), genre);
    return { ja: v, en: '' };
  }
  if (key === 'noun') {
    const c = composeNoun(rng, genre, null);
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

function buildTitle(rng, genre, opts) {
  const core = composeNoun(rng, genre, null);
  let ja = core.ja;
  let en = core.en;
  let parts = core.parts;
  let skeleton = 'core';
  if (rng.chance(TITLE_SKELETON_CHANCE[genre])) {
    skeleton = rng.pick(PATTERNS[genre].title);
    if (skeleton !== '{noun}') {
      const state = { seen: Object.create(null) };
      const bindings = { noun: core.ja, 'noun.en': core.en };
      const enParts = [];
      ja = skeleton.replace(SLOT_RE, (m, key) => {
        const pair = resolveTitlePair(rng, genre, key, bindings, state);
        if (pair.en) { enParts.push(pair.en); }
        return pair.ja;
      });
      if (ja.indexOf('{') >= 0) { ja = expand(rng, genre, ja, null, 1, state); }
      en = enParts.join(' ');
      parts = null;
    }
  }
  const styled = styleTitle(rng, { ja: ja, en: en, parts: parts }, {
    vertical: !!(opts && opts.verticalTitle),
    genre: genre,
    allowLatin: !(opts && opts.allowLatin === false),
    allowExclaim: !(opts && opts.allowExclaim === false)
  });
  return { styled: styled, core: core, skeleton: skeleton };
}

function fillRole(rng, genre, role, density) {
  const p = PATTERNS[genre];
  if (role === 'catch') {
    let text = expand(rng, genre, rng.pick(p.catch), null, 0);
    if (density > 1.2 && p.sub && rng.chance(0.5)) {
      text = text + '\n' + expand(rng, genre, rng.pick(p.sub), null, 0);
    }
    return text;
  }
  if (role === 'name') { return personName(rng, genre).ja; }
  if (role === 'tag') { return expand(rng, genre, rng.pick(p.tag), null, 0); }
  if (role === 'badge') { return expand(rng, genre, rng.pick(p.badge), null, 0); }
  if (role === 'release') { return expand(rng, genre, rng.pick(p.release), null, 0); }
  if (role === 'extra') { return expand(rng, genre, rng.pick(p.extra), null, 0); }
  if (role === 'code') { return numeric(rng, 'code', genre); }
  if (role === 'credit') {
    const list = p.credit;
    const idx = density < 0.8
      ? 0
      : (density > 1.2 ? list.length - 1 : rng.int(0, list.length - 1));
    return expand(rng, genre, list[idx], null, 0);
  }
  throw new Error('unknown role: ' + role);
}

export function generateCopy(rng, genre, density, opts) {
  const plan = ROLE_PLAN[genre];
  if (!plan) { throw new Error('unknown genre: ' + genre); }
  const d = typeof density === 'number' ? density : 1;

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

  const built = buildTitle(rng, genre, opts);
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
    copy[role] = fillRole(rng, genre, role, d);
  }

  if (built.styled.latin && !copy.extra) { copy.extra = built.styled.latin; }

  copy.__axes = {
    genre: genre,
    density: d,
    titleMode: built.core.mode,
    titleSkeleton: built.skeleton,
    orthography: built.styled.axes,
    look: genre + '/' + built.core.mode + '/' + built.styled.axes[0].split(':')[1],
    roles: roles.slice()
  };

  return copy;
}
