import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 無音skip再生。外すと声が丸ごと聞かれずに飛ぶ(しかも飛んだこと自体が画面に残らない)ので、
// 「飛ばさない」側の条件を1つずつ見る。判定はserverのVADで、ここが見るのは飛び方である。
describe("videos.js の無音skip再生", () => {
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
    page.set("state.current", { recording_id: 1 });
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const state = () => page.get("state");

  /**
   * jsdom の <video> は currentTime も paused も buffered も動かないので、test が中身を与える。
   * bufferedは既定で「全部読み込み済み」— buffer外を試す場合だけ ranges を渡す。
   */
  function fakeVideo({ time = 0, paused = false, ranges = [[0, 1e6]] } = {}) {
    const video = doc.getElementById("video");
    let current = time;
    Object.defineProperty(video, "currentTime", {
      configurable: true, get: () => current, set: (v) => { current = v; },
    });
    ["paused", "ended", "seeking"].forEach((name, index) => {
      const value = index === 0 ? paused : false;
      Object.defineProperty(video, name, { configurable: true, get: () => value });
    });
    Object.defineProperty(video, "buffered", {
      configurable: true,
      get: () => ({
        length: ranges.length,
        start: (i) => ranges[i][0],
        end: (i) => ranges[i][1],
      }),
    });
    return video;
  }

  function plan(spans, extra = {}) {
    const skipSeconds = spans.reduce((sum, s) => sum + (s.end - s.start), 0);
    page.set("state.skipPlan", {
      spans, skip_seconds: skipSeconds, duration_seconds: 100,
      guard_seconds: 0.45, lead_seconds: 0.1, min_gap_seconds: 0.5,
      min_jump_seconds: 0.3, voice_threshold: 0.1,
      speech_spans: 12, reaction_spans: 3, has_reactions: true, ...extra,
    });
  }

  it("飛び先はserverの計画をそのまま使う（端の余裕はserverが引いてある）", () => {
    plan([{ start: 3, end: 12 }]);
    win.rebuildSkipSpans();
    expect(state().skipSpans).toEqual([{ start: 3, end: 12 }]);
  });

  describe("飛ばし方", () => {
    beforeEach(() => {
      plan([{ start: 10, end: 20 }]);
      win.rebuildSkipSpans();
      doc.getElementById("skip-silence").checked = true;
    });

    it("再生中に無音へ入ったら、区間の終端へ跳ぶ", () => {
      const video = fakeVideo({ time: 12 });
      win.applySilenceSkip();
      expect(video.currentTime).toBeCloseTo(20, 3);
      expect(state().skippedSeconds).toBeCloseTo(8, 3);
    });

    it("止めている間は飛ばさない(置いた再生位置が勝手に動かない)", () => {
      const video = fakeVideo({ time: 12, paused: true });
      win.applySilenceSkip();
      expect(video.currentTime).toBe(12);
    });

    it("境界確認再生の間は飛ばさない(その無音を聞きに行く操作である)", () => {
      const video = fakeVideo({ time: 12 });
      page.set("previewStopAt", 21);
      win.applySilenceSkip();
      expect(video.currentTime).toBe(12);
    });

    it("J/K/Lのshuttle中は飛ばさない(その速度で送っている手応えが消える)", () => {
      const video = fakeVideo({ time: 12 });
      page.set("forwardStep", 2);
      win.applySilenceSkip();
      expect(video.currentTime).toBe(12);
    });

    it("切ってあれば飛ばさない", () => {
      doc.getElementById("skip-silence").checked = false;
      const video = fakeVideo({ time: 12 });
      win.applySilenceSkip();
      expect(video.currentTime).toBe(12);
    });

    it("無音の外では動かさない", () => {
      const video = fakeVideo({ time: 25 });
      win.applySilenceSkip();
      expect(video.currentTime).toBe(25);
    });

    it("IN/OUTのループ中はOUTを越えない", () => {
      doc.getElementById("loop-range").checked = true;
      page.set("state.cutIn", 5);
      page.set("state.cutOut", 15);
      const video = fakeVideo({ time: 12 });
      win.applySilenceSkip();
      expect(video.currentTime).toBe(15);
    });

    it("残りが跳躍に足りなければ動かさない", () => {
      const video = fakeVideo({ time: 19.9 });
      win.applySilenceSkip();
      expect(video.currentTime).toBe(19.9);
    });

    // buffer外へのseekは実測0.67〜259秒かかり、どちらになるか事前に分からない。
    // 跳ばずに等速で流し、読み込みが追い付いたら跳ぶ。
    it("読み込みが追い付いていない先へは跳ばない", () => {
      const video = fakeVideo({ time: 12, ranges: [[0, 15]] });
      win.applySilenceSkip();
      expect(video.currentTime).toBe(12);
      expect(state().skipDeferred).toBe(1);

      // 読み込みが進めば、その場で跳ぶ
      const ready = fakeVideo({ time: 12, ranges: [[0, 40]] });
      win.applySilenceSkip();
      expect(ready.currentTime).toBeCloseTo(20, 3);
    });

    it("buffer境界ぎりぎりの着地も跳ばない(着地してすぐ次のframeを出せない)", () => {
      const video = fakeVideo({ time: 12, ranges: [[0, 20.2]] });
      win.applySilenceSkip();
      expect(video.currentTime).toBe(12);
    });
  });

  describe("早送りとの排他", () => {
    it("両方入っていても、速度は乗せずに飛ばす方へ譲る", () => {
      doc.getElementById("skip-silence").checked = true;
      doc.getElementById("pace-talk").checked = true;
      page.set("state.pacePlan", {
        fast: [{ start: 10, end: 20 }], fast_rate: 6, fast_volume: 0.25,
        fast_seconds: 10, duration_seconds: 100,
      });
      const video = fakeVideo({ time: 12 });
      video.playbackRate = 1;
      win.applyTalkPace();
      expect(video.playbackRate).toBe(1);
    });
  });

  describe("名乗り", () => {
    it("飛ばす量と、それで何倍速になるかを名乗る", () => {
      doc.getElementById("skip-silence").checked = true;
      plan([{ start: 0, end: 40 }]);
      win.rebuildSkipSpans();
      const text = doc.getElementById("skip-note").textContent;
      expect(text).toContain("40%");
      expect(text).toContain("倍");
    });

    it("計画の待ちと、飛ばせる無音が無いのを言い分ける", () => {
      doc.getElementById("skip-silence").checked = true;
      page.set("state.skipPlan", null);
      win.rebuildSkipSpans();
      expect(doc.getElementById("skip-note").textContent).toContain("解析中");

      plan([]);
      win.rebuildSkipSpans();
      expect(doc.getElementById("skip-note").textContent).toBe("");
    });

    it("声が1つも取れなかった録画は、0件ではなくその旨を名乗る", () => {
      doc.getElementById("skip-silence").checked = true;
      plan([], { speech_spans: 0 });
      win.rebuildSkipSpans();
      expect(doc.getElementById("skip-note").textContent).toContain("声なし");
    });

    it("反応が未解析の録画はそう名乗る(叫びや拍手を飛ばしている可能性がある)", () => {
      doc.getElementById("skip-silence").checked = true;
      plan([{ start: 0, end: 20 }], { has_reactions: false });
      win.rebuildSkipSpans();
      expect(doc.getElementById("skip-note").textContent).toContain("反応未解析");
    });

    it("切っている間は何も名乗らない", () => {
      doc.getElementById("skip-silence").checked = false;
      plan([{ start: 0, end: 20 }]);
      win.rebuildSkipSpans();
      expect(doc.getElementById("skip-note").textContent).toBe("");
    });
  });
});
