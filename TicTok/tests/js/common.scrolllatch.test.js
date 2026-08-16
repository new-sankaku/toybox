import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

// 外側scroller(modal本文)の中に、内側scroller(表)と素の中身が並ぶ形。
const HTML = `<!doctype html><html><body>
  <div id="outer">
    <div id="plain">上の中身</div>
    <div id="inner"><div id="cell">行</div></div>
  </div>
</body></html>`;

// jsdomは layout を持たないので clientHeight/scrollHeight/scrollTop が常に0になる。
// latchの判定はこの3つだけを見るため、element ごとに実体を持たせて layout を模す。
function makeScroller(el, { view = 100, content = 1000, top = 0 } = {}) {
  el.style.overflowY = "auto";
  let scrollTop = top;
  let scrollLeft = 0;
  Object.defineProperties(el, {
    clientHeight: { value: view, configurable: true },
    scrollHeight: { value: content, configurable: true },
    clientWidth: { value: view, configurable: true },
    scrollWidth: { value: view, configurable: true },
    scrollTop: {
      configurable: true,
      get: () => scrollTop,
      set: (v) => { scrollTop = v; },
    },
    scrollLeft: {
      configurable: true,
      get: () => scrollLeft,
      set: (v) => { scrollLeft = v; },
    },
  });
}

describe("入れ子scrollのlatch", () => {
  let page;
  let win;
  let doc;
  let outer;
  let inner;
  let cell;

  const now = (ms) => { win.__now = ms; };
  const wheel = (target, deltaY) => {
    const ev = new win.WheelEvent("wheel", { deltaY, bubbles: true, cancelable: true });
    target.dispatchEvent(ev);
    return ev;
  };

  beforeEach(() => {
    page = loadCommon({
      html: HTML,
      before(w) {
        w.__now = 0;
        Object.defineProperty(w, "performance", {
          configurable: true,
          value: { now: () => w.__now },
        });
      },
    });
    win = page.win;
    doc = page.document;
    outer = doc.getElementById("outer");
    inner = doc.getElementById("inner");
    cell = doc.getElementById("cell");
    makeScroller(outer);
    makeScroller(inner);
  });
  afterEach(async () => page.close());

  it("外側を転がしている最中に内側へpointerが入っても外側が動き続ける", () => {
    wheel(doc.getElementById("plain"), 50); // 外側を掴む(既定動作のまま)
    now(100);
    const ev = wheel(cell, 50); // pointerが内側scrollerへ入った
    expect(ev.defaultPrevented).toBe(true);
    expect(outer.scrollTop).toBe(50);
    expect(inner.scrollTop).toBe(0);
  });

  it("手が止まればlatchは解けて内側が動く", () => {
    wheel(doc.getElementById("plain"), 50);
    now(1000);
    const ev = wheel(cell, 50);
    expect(ev.defaultPrevented).toBe(false);
    expect(outer.scrollTop).toBe(0);
  });

  it("内側から始めた場合はそのまま内側が動く(browserの既定に任せる)", () => {
    const ev = wheel(cell, 50);
    expect(ev.defaultPrevented).toBe(false);
    expect(outer.scrollTop).toBe(0);
    expect(inner.scrollTop).toBe(0);
  });

  it("latch先が下端まで来たら解除して内側へ渡す", () => {
    outer.scrollTop = 800; // 下端(scrollHeight - clientHeight = 900)の手前
    wheel(doc.getElementById("plain"), 50);
    now(50);
    expect(wheel(cell, 50).defaultPrevented).toBe(true);
    expect(outer.scrollTop).toBe(850);
    now(100);
    outer.scrollTop = 900; // 下端
    expect(wheel(cell, 50).defaultPrevented).toBe(false);
  });

  it("page固有のwheel処理(拡縮など)がpreventDefault済みなら手を出さない", () => {
    wheel(doc.getElementById("plain"), 50);
    now(100);
    cell.addEventListener("wheel", (ev) => ev.preventDefault());
    wheel(cell, 50);
    expect(outer.scrollTop).toBe(0);
  });

  it("Ctrl+wheel(拡大縮小)は横取りしない", () => {
    wheel(doc.getElementById("plain"), 50);
    now(100);
    const ev = new win.WheelEvent("wheel", {
      deltaY: 50, ctrlKey: true, bubbles: true, cancelable: true,
    });
    cell.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    expect(outer.scrollTop).toBe(0);
  });
});
