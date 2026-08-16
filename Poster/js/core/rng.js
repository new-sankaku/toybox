(function (PF) {
'use strict';

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function createRng(seed) {
  const next = mulberry32(seed);
  const api = {
    seed: seed,
    next: next,
    range: (a, b) => a + (b - a) * next(),
    int: (a, b) => Math.floor(a + (b - a + 1) * next()),
    chance: (p) => next() < p,
    pick: (arr) => arr[Math.floor(next() * arr.length)],
    weighted: (items) => {
      let total = 0;
      for (let i = 0; i < items.length; i++) { total += items[i].w; }
      let r = next() * total;
      for (let i = 0; i < items.length; i++) {
        r -= items[i].w;
        if (r <= 0) { return items[i].v; }
      }
      return items[items.length - 1].v;
    },
    shuffle: (arr) => {
      const a = arr.slice();
      for (let i = a.length - 1; i > 0; i--) {
        const j = Math.floor(next() * (i + 1));
        const t = a[i]; a[i] = a[j]; a[j] = t;
      }
      return a;
    },
    sample: (arr, n) => api.shuffle(arr).slice(0, Math.min(n, arr.length)),
    sign: () => (next() < 0.5 ? -1 : 1)
  };
  return api;
}

function randomSeed() {
  return (Math.random() * 0xffffffff) >>> 0;
}

Object.assign(PF, { mulberry32, createRng, randomSeed });
})(window.PF = window.PF || {});
