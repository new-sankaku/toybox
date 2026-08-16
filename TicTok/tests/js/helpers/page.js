import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const PROJECT_ROOT = path.resolve(HERE, "..", "..", "..");
export const STATIC_DIR = path.join(PROJECT_ROOT, "static");

// canvas(chart・timeline)の色は CSS の token(:root)を読んで決まる。本番の page は必ず
// style.css を link しているので、token の定義が無い document で script を評価すると
// test だけが「色の無い世界」になり、色を持たない不具合を見逃す。
// 値を test 側へ書き写すと二重定義になるため、定義は実 file の :root から切り出して使う。
// 全文を食わせないのは、4000行超の CSS を document ごとに parse させないため。
const ROOT_TOKENS_CSS = (() => {
  const css = readFileSync(path.join(STATIC_DIR, "style.css"), "utf8");
  const m = css.match(/^:root\s*\{[\s\S]*?\n\}/m);
  if (!m) throw new Error("style.css の :root block が見つかりません");
  return m[0];
})();

// static/ の JS は ES module ではなく classic script。HTML の <script src> がそのまま
// global scope へ流し込む読み方なので、test も同じ読み方を再現する。個別に import できる
// 形へ書き換えると、本番が読んでいる物と test が読んでいる物が別になる。
//
// 読み込む script は HTML 自身の <script src> から取る。test 側に一覧を持たせると、
// page へ script を足したときに test だけ古いままになる。
function scriptSrcList(document) {
  return Array.from(document.querySelectorAll("script[src]")).map((el) =>
    el.getAttribute("src"),
  );
}

function staticPathOf(src) {
  const rel = src.replace(/^\/static\//, "");
  return path.join(STATIC_DIR, rel);
}

// vendor(hls.js / chart.js)は本物を読まない。test の対象は static/ の自前 code であり、
// 描画library の中身まで jsdom 上で動かす必要がない。代わりに呼ばれ方を記録する stub を置く。
function installVendorStubs(win, calls) {
  class ChartStub {
    constructor(ctx, config) {
      this.ctx = ctx;
      this.config = config;
      this.data = (config && config.data) || { labels: [], datasets: [] };
      this.options = (config && config.options) || {};
      this.canvas = ctx && ctx.canvas ? ctx.canvas : ctx;
      calls.charts.push(this);
    }
    update() {}
    destroy() {}
    resize() {}
    getDatasetMeta() {
      return { data: [], hidden: false };
    }
  }
  ChartStub.register = () => {};
  ChartStub.defaults = { font: {}, plugins: { legend: {} } };
  win.Chart = ChartStub;

  class HlsStub {
    static isSupported() {
      return false;
    }
    constructor(config) {
      this.config = config;
      calls.hls.push(this);
    }
    loadSource() {}
    attachMedia() {}
    on() {}
    off() {}
    destroy() {}
    startLoad() {}
    stopLoad() {}
  }
  HlsStub.Events = {
    MANIFEST_PARSED: "hlsManifestParsed",
    ERROR: "hlsError",
    LEVEL_SWITCHED: "hlsLevelSwitched",
    FRAG_CHANGED: "hlsFragChanged",
  };
  HlsStub.ErrorTypes = {
    NETWORK_ERROR: "networkError",
    MEDIA_ERROR: "mediaError",
    OTHER_ERROR: "otherError",
  };
  win.Hls = HlsStub;
}

// jsdom が持たない browser API のうち、static/ の code が実際に触る物だけを補う。
// 網羅的な polyfill は入れない — 触っていない API を勝手に生やすと、本番に無い前提の上で
// test が通ってしまう。
function installBrowserStubs(win, calls) {
  win.WebSocket = class WebSocketStub {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      this.onerror = null;
      calls.sockets.push(this);
    }
    send(data) {
      calls.sent.push(data);
    }
    close() {
      this.readyState = 3;
    }
    // test から server push を模す。
    emit(payload) {
      if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
    }
  };
  win.WebSocket.CONNECTING = 0;
  win.WebSocket.OPEN = 1;
  win.WebSocket.CLOSING = 2;
  win.WebSocket.CLOSED = 3;

  // jsdom は layout を持たないので scrollIntoView が未実装。一覧の選択追従が呼ぶ。
  win.Element.prototype.scrollIntoView = function scrollIntoView(arg) {
    calls.scrolledIntoView.push([this, arg]);
  };

  win.IntersectionObserver = class IntersectionObserverStub {
    constructor(cb) {
      this.cb = cb;
      calls.observers.push(this);
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  };

  // <canvas> の 2D context。jsdom は canvas package 無しだと getContext が null を返し、
  // 描画 code が TypeError で落ちる。呼ばれた命令を記録するだけの context を返す。
  const ctxMethods = [
    "beginPath", "closePath", "moveTo", "lineTo", "arc", "rect", "fill",
    "stroke", "fillRect", "clearRect", "strokeRect", "fillText", "strokeText",
    "save", "restore", "translate", "scale", "rotate", "setLineDash",
    "drawImage", "quadraticCurveTo", "bezierCurveTo", "roundRect", "clip",
  ];
  win.HTMLCanvasElement.prototype.getContext = function getContext(kind) {
    if (kind !== "2d") return null;
    if (!this.__ctx) {
      const ctx = { canvas: this, __ops: [] };
      ctxMethods.forEach((name) => {
        ctx[name] = (...args) => ctx.__ops.push([name, ...args]);
      });
      ctx.measureText = (text) => ({ width: String(text).length * 6 });
      ctx.createLinearGradient = () => ({ addColorStop() {} });
      ctx.getImageData = () => ({ data: new Uint8ClampedArray(4) });
      this.__ctx = ctx;
    }
    return this.__ctx;
  };

  // jsdom の HTMLMediaElement は play/load/pause が "Not implemented" を投げる。
  win.HTMLMediaElement.prototype.play = function play() {
    calls.mediaPlays.push(this);
    return Promise.resolve();
  };
  win.HTMLMediaElement.prototype.pause = function pause() {};
  win.HTMLMediaElement.prototype.load = function load() {};

  if (!win.navigator.clipboard) {
    Object.defineProperty(win.navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: (text) => {
          calls.clipboard.push(text);
          return Promise.resolve();
        },
      },
    });
  }
}

// API の応答は test が routes で明示した物だけを返す。未指定の path は 404 にして、
// app 自身の error 経路(「取得できていない」表示)を通す。未知の path へ空 data を
// 与えると、実際には壊れている画面が test では正常に見えてしまう。
function installFetch(win, routes, calls) {
  win.fetch = (input, init) => {
    const url = String(typeof input === "string" ? input : input.url);
    const method = ((init && init.method) || "GET").toUpperCase();
    calls.fetches.push({ url, method, body: init && init.body });
    const key = `${method} ${url}`;
    const handler =
      Object.prototype.hasOwnProperty.call(routes, key) ? routes[key]
      : Object.prototype.hasOwnProperty.call(routes, url) ? routes[url]
      : null;
    if (handler === null) {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: `no stub route: ${key}` }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    const body = typeof handler === "function" ? handler({ url, method, init }) : handler;
    if (body instanceof Response) return Promise.resolve(body);
    return Promise.resolve(
      new Response(JSON.stringify(body === undefined ? {} : body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  };
}

/**
 * static/*.html を jsdom へ読み込み、その HTML が <script src> で指している static/*.js を
 * classic script として順に評価する。
 *
 * @param {object} opts
 * @param {string} [opts.page]    static/ 配下の HTML 名 ("analytics" / "videos.html")。
 * @param {string} [opts.html]    page の代わりに直接与える HTML。
 * @param {string} [opts.url]     document の URL。既定は page 名から引いた path。
 * @param {string[]} [opts.scripts] HTML の <script src> の代わりに読む static/ 配下の JS 名。
 * @param {object} [opts.routes]  fetch の応答表。"GET /api/x" か "/api/x" を key にする。
 * @param {(win:Window)=>void} [opts.before] script 評価の直前に呼ぶ (追加 stub 用)。
 */
export function loadPage(opts = {}) {
  const {
    page,
    html: rawHtml,
    url,
    scripts: scriptOverride,
    routes = {},
    before,
  } = opts;

  const htmlFile = page
    ? path.join(STATIC_DIR, page.endsWith(".html") ? page : `${page}.html`)
    : null;
  const html = rawHtml ?? (htmlFile ? readFileSync(htmlFile, "utf8") : "<!doctype html><html><body></body></html>");
  const pageUrl =
    url ??
    (page ? `http://localhost:8520/${page.replace(/\.html$/, "").replace(/^index$/, "")}` : "http://localhost:8520/");

  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => errors.push(err));
  virtualConsole.on("error", (...args) => errors.push(new Error(args.join(" "))));

  const dom = new JSDOM(html, {
    url: pageUrl,
    // inline <script> を実行させる。static/*.js は先頭が "use strict" のため、
    // eval で流し込むと strict eval 独自の scope に閉じて global へ関数が生えない。
    // 本番と同じく script 要素として食わせるのが唯一の正しい読み方。
    // HTML 側の <script src> は resources を指定していないので jsdom は取得しない
    // (test が読む file は下で明示的に inline 化する)。
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole,
  });
  const win = dom.window;
  const calls = {
    fetches: [],
    sockets: [],
    sent: [],
    charts: [],
    hls: [],
    observers: [],
    mediaPlays: [],
    clipboard: [],
    scrolledIntoView: [],
  };

  const tokenStyle = win.document.createElement("style");
  tokenStyle.textContent = ROOT_TOKENS_CSS;
  win.document.head.appendChild(tokenStyle);

  installVendorStubs(win, calls);
  installBrowserStubs(win, calls);
  installFetch(win, routes, calls);
  if (before) before(win);

  const sources =
    scriptOverride ??
    scriptSrcList(win.document).filter((src) => !src.includes("/vendor/"));
  const loaded = [];
  sources.forEach((src) => {
    const file = src.startsWith("/static/") ? staticPathOf(src) : path.join(STATIC_DIR, src);
    const code = readFileSync(file, "utf8");
    const before = errors.length;
    const el = win.document.createElement("script");
    // sourceURL が無いと、jsdom が組み立てた無名 script として扱われ、stack trace が
    // 読めず coverage も元 file へ結び付かない。
    el.textContent = `${code}\n//# sourceURL=${pathToFileURL(file).href}\n`;
    win.document.head.appendChild(el);
    if (errors.length > before) {
      const err = errors[before];
      throw new Error(
        `${path.basename(file)} の評価に失敗しました: ${err && err.stack ? err.stack : err}`,
      );
    }
    loaded.push(path.basename(file));
  });

  return {
    dom,
    win,
    document: win.document,
    calls,
    errors,
    loaded,
    // classic script の top-level `const`/`let` は window の property にならない
    // (global lexical scope へ入る)。indirect eval だけがそこへ届く。
    // `function` 宣言は win.<name> でそのまま読める。
    get(name) {
      return win.eval(name);
    },
    /** realm 内で任意の式を評価する。 */
    run(code) {
      return win.eval(code);
    },
    // top-level の `let` へ書く。realm 内で literal から組み直すので、
    // test 側(Node realm)の配列が jsdom realm へ持ち込まれることはない。
    set(name, value) {
      return win.eval(`${name} = ${JSON.stringify(value)}`);
    },
    /** DOMContentLoaded を待つ code のために fire する。 */
    fireReady() {
      win.document.dispatchEvent(new win.Event("DOMContentLoaded", { bubbles: true }));
      win.dispatchEvent(new win.Event("load"));
    },
    /** 保留中の task (bootstrap の fetch 連鎖) を吐き出させる。 */
    async settle(times = 8) {
      for (let i = 0; i < times; i += 1) {
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setImmediate(r));
      }
    },
    // bootstrap の非同期処理が走り切る前に window を閉じると、続きの callback が
    // 消えた document を触って unhandled rejection になる。close は必ず drain の後。
    async close() {
      await this.settle();
      win.close();
    },
  };
}

/** common.js だけを最小 DOM の上へ読む。純粋関数の test 用。 */
export function loadCommon(opts = {}) {
  return loadPage({
    html: opts.html ?? "<!doctype html><html><body></body></html>",
    url: opts.url ?? "http://localhost:8520/",
    scripts: ["common.js"],
    routes: opts.routes ?? {},
    before: opts.before,
  });
}
