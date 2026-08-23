import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 「その区間はもう見どころへ採ってある」を時間軸の上で言えているか。ここが落ちても画面は
// それらしく描かれる(帯が出ないだけ)ので、同じ場面を二度切り出すまで気付けない。
describe("videos.js の見どころ区間の面", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "videos", url: "http://localhost:8520/videos" });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const state = () => page.get("state");

  /** jsdom は layout を持たないので、canvas の実寸は test が与える。 */
  function sizeCanvas(id, width, height) {
    const canvas = doc.getElementById(id);
    Object.defineProperty(canvas, "clientWidth", { configurable: true, get: () => width });
    Object.defineProperty(canvas, "clientHeight", { configurable: true, get: () => height });
    return canvas;
  }

  /** fillRect は色を context の property から採る。命令と一緒に色を残さないと、
   *  「描いたが見えない色だった」を test が通してしまう。 */
  function recordFills(canvas) {
    const ctx = canvas.getContext("2d");
    const fills = [];
    ctx.fillRect = (x, y, w, h) => fills.push({ x, y, w, h, style: ctx.fillStyle });
    return fills;
  }

  function setDuration(seconds) {
    Object.defineProperty(doc.getElementById("video"), "duration", {
      configurable: true, get: () => seconds,
    });
  }
  function setCurrentTime(seconds) {
    Object.defineProperty(doc.getElementById("video"), "currentTime", {
      configurable: true, writable: true, value: seconds,
    });
  }

  // --ramp は :root の token。色を書き写すと palette を変えたときに test だけが旧色で残る。
  const rampAlpha = (alpha) => win.cssTokenAlpha("--ramp", alpha);
  // top-level の const は window の property にならないので、realm の中から読む。
  const px = (name) => page.get(name);

  beforeEach(() => {
    setDuration(100);
    setCurrentTime(0);
    state().heat = null;
    state().wave = null;
    state().silences = [];
    state().bookmarks = [
      { id: 1, start: 10, end: 20 },
      { id: 2, start: 50, end: null },
    ];
  });

  describe("全尺bar", () => {
    it("尺のある見どころを面で敷く(点には面を与えない)", () => {
      const canvas = sizeCanvas("heat", 200, 60);
      const fills = recordFills(canvas);
      win.drawHeat();
      const bands = fills.filter((f) => f.style === rampAlpha(0.1));
      expect(bands).toHaveLength(1);
      // 10-20秒 / 尺100秒 / 幅200px。
      expect(bands[0].x).toBe(20);
      expect(bands[0].w).toBe(20);
    });

    it("面は波形とheatの帯だけを覆う(handle laneとmarker laneへは掛けない)", () => {
      const canvas = sizeCanvas("heat", 200, 60);
      const fills = recordFills(canvas);
      win.drawHeat();
      const band = fills.find((f) => f.style === rampAlpha(0.1));
      expect(band.y).toBe(px("RANGE_LANE_PX"));
      expect(band.y + band.h).toBe(60 - px("BOOKMARK_LANE_PX"));
    });
  });

  describe("拡大窓", () => {
    beforeEach(() => {
      // 窓を0-100秒(全尺)に固定する。
      page.run("state.zoomStart = 0");
      state().zoomSpan = 100;
    });

    it("窓に掛かる範囲を面・縁・下端の帯で名乗る", () => {
      const canvas = sizeCanvas("zoom", 200, 80);
      const fills = recordFills(canvas);
      win.drawZoom();
      const band = fills.filter((f) => f.style === rampAlpha(0.16));
      expect(band).toHaveLength(1);
      expect(band[0].x).toBe(20);
      expect(band[0].w).toBe(20);
      // 縁はIN側とOUT側の2本。
      const edges = fills.filter((f) => f.style === rampAlpha(0.9));
      expect(edges.map((f) => f.x)).toEqual([19, 39]);
      // 下端の帯(範囲)と細い柱(点)。
      const lane = fills.filter((f) => f.style === rampAlpha(0.85));
      expect(lane).toHaveLength(2);
      expect(lane[0].w).toBe(20);
      expect(lane[1].x).toBe(99);
      expect(lane[1].w).toBe(2);
    });

    it("手前で始まった長い範囲も窓へ描く(開始位置での頭出しで取りこぼさない)", () => {
      state().bookmarks = [{ id: 1, start: 5, end: 95 }];
      page.run("state.zoomStart = 40");
      state().zoomSpan = 20;
      const canvas = sizeCanvas("zoom", 200, 80);
      const fills = recordFills(canvas);
      win.drawZoom();
      const band = fills.filter((f) => f.style === rampAlpha(0.16));
      expect(band).toHaveLength(1);
      expect(band[0].x).toBe(0);
      expect(band[0].w).toBe(200);
    });

    it("窓の外へ出ている端には縁を引かない(そこが切れ目だと読まれる)", () => {
      state().bookmarks = [{ id: 1, start: 5, end: 95 }];
      page.run("state.zoomStart = 40");
      state().zoomSpan = 20;
      const canvas = sizeCanvas("zoom", 200, 80);
      const fills = recordFills(canvas);
      win.drawZoom();
      expect(fills.filter((f) => f.style === rampAlpha(0.9))).toHaveLength(0);
    });

    it("波形は見どころlaneを最初から空けて描く(見どころを足しても形が変わらない)", () => {
      state().wave = new Array(1000).fill(1);
      state().waveBucketSeconds = 0.1;
      const canvas = sizeCanvas("zoom", 200, 80);
      const fills = recordFills(canvas);
      win.drawZoom();
      const waveH = 80 - px("RULER_LANE_PX") - px("BOOKMARK_LANE_PX") - px("RANGE_LANE_PX");
      const bars = fills.filter((f) => f.w === 1 && f.h === waveH);
      expect(bars.length).toBeGreaterThan(0);
    });
  });
});
