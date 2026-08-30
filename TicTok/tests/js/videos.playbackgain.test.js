import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 再生音量の均し。録画のfileは書き換えないので、揃うかどうかは「曲線を正しく引けるか」と
// 「引けなかったことを名乗るか」の2点だけで決まる。黙って素の音を流すと、揃っていない音を
// 揃ったものとして聞かせることになるので、失敗を名乗る側を重点的に見る。
describe("videos.js の再生音量の均し", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  const CURVE = {
    recording_id: 1,
    enabled: true,
    step_seconds: 0.1,
    duration_seconds: 0.5,
    gains: [0, 2, 4, 6, 6],
    target_lufs: -14,
    ceiling_dbfs: -1.5,
  };

  async function open(routes = {}) {
    page = loadPage({ page: "videos", url: "http://localhost:8520/videos", routes });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
    page.set("state.current", { recording_id: 1 });
  }

  afterEach(async () => {
    if (errorSpy) errorSpy.mockRestore();
    if (page) await page.close();
    page = null;
  });

  describe("曲線の引き方", () => {
    beforeEach(() => open());

    it("刻みで割った位置の値を返す", () => {
      page.set("state.gain", CURVE);
      expect(win.gainDbAt(0)).toBe(0);
      expect(win.gainDbAt(0.25)).toBe(4);
      expect(win.gainDbAt(0.3)).toBe(6);
    });

    it("尺の外は端の値で伸ばす(再生位置は尺を僅かに超え得る)", () => {
      page.set("state.gain", CURVE);
      expect(win.gainDbAt(99)).toBe(6);
      expect(win.gainDbAt(-5)).toBe(0);
    });

    it("曲線が無い録画は0 dB(素の音)", () => {
      page.set("state.gain", null);
      expect(win.gainDbAt(3)).toBe(0);
    });
  });

  describe("揃えられないときの名乗り", () => {
    it("Web Audioが無いBrowserでは理由を出し、曲線を採用しない", async () => {
      // jsdomにAudioContextは無い。実際に古いBrowserで踏む経路と同じ。
      await open({ "/api/recordings/1/gain": CURVE });
      doc.getElementById("playback-gain").checked = true;
      await win.loadGainCurve(1);
      expect(doc.getElementById("gain-note").textContent).toContain("Web Audio");
      expect(page.get("state.gain")).toBe(null);
    });

    it("設定で無効なら、そう名乗る(0 dBの曲線として飲み込まない)", async () => {
      await open({ "/api/recordings/1/gain": { recording_id: 1, enabled: false } });
      doc.getElementById("playback-gain").checked = true;
      await win.loadGainCurve(1);
      expect(doc.getElementById("gain-note").textContent).toContain("無効");
      expect(page.get("state.gain")).toBe(null);
    });

    it("取得に失敗したら理由を出す(0件として黙らない)", async () => {
      await open({});
      doc.getElementById("playback-gain").checked = true;
      await win.loadGainCurve(1);
      expect(doc.getElementById("gain-note").textContent).not.toBe("");
      expect(page.get("state.gain")).toBe(null);
    });

    it("checkboxを切ってあるときは要求しない", async () => {
      await open({ "/api/recordings/1/gain": CURVE });
      doc.getElementById("playback-gain").checked = false;
      await win.loadGainCurve(1);
      expect(page.calls.fetches.some((f) => f.url.includes("/gain"))).toBe(false);
      expect(page.get("state.gain")).toBe(null);
      expect(doc.getElementById("gain-note").textContent).toBe("");
    });
  });

  describe("GainNodeへの適用", () => {
    // Web Audioの実体はjsdomに無いので、graphだけを最小限に模す。見たいのは
    // 「再生位置から引いた値をlinear倍率にして当てるか」の1点。
    // top-levelの`let`はwindowのpropertyにならないので、realm内で書き換える。
    function fakeGraph() {
      page.run(`
        window.__gainApplied = [];
        gainCtx = { currentTime: 0, state: "running", resume: () => Promise.resolve() };
        gainNode = { gain: { setTargetAtTime: (v) => window.__gainApplied.push(v) } };
      `);
      return win.__gainApplied;
    }

    beforeEach(() => open());

    it("dBをlinear倍率にして当てる", () => {
      const applied = fakeGraph();
      page.set("state.gain", CURVE);
      doc.getElementById("playback-gain").checked = true;
      const video = doc.getElementById("video");
      Object.defineProperty(video, "currentTime", { configurable: true, get: () => 0.35 });
      win.applyGainNow();
      // 0.35秒 -> index 3 -> 6 dB -> 10^(6/20)
      expect(applied.at(-1)).toBeCloseTo(Math.pow(10, 6 / 20), 6);
    });

    it("checkboxを切ったらその場で素の音(1.0倍)へ戻す", () => {
      const applied = fakeGraph();
      page.set("state.gain", CURVE);
      doc.getElementById("playback-gain").checked = false;
      win.applyGainNow();
      expect(applied.at(-1)).toBe(1);
    });
  });
});
