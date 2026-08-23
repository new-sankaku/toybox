import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 無言の早送り。飛ばさないので聞き逃しても跡が残らず、外れたことに気付けるのは違和感だけ。
// 「速くしてはいけない場面で速くしない」側と、「利用者の音量設定を壊さない」側を見る。
describe("videos.js の無言早送り", () => {
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

  /** jsdom の <video> は currentTime も paused も動かないので、test が中身を与える。 */
  function fakeVideo({ time = 0, paused = false, volume = 1 } = {}) {
    const video = doc.getElementById("video");
    let current = time;
    Object.defineProperty(video, "currentTime", {
      configurable: true, get: () => current, set: (v) => { current = v; },
    });
    ["paused", "ended", "seeking"].forEach((name, index) => {
      const value = index === 0 ? paused : false;
      Object.defineProperty(video, name, { configurable: true, get: () => value });
    });
    video.volume = volume;
    video.playbackRate = 1;
    return video;
  }

  function plan(fast, extra = {}) {
    page.set("state.pacePlan", {
      fast,
      fast_seconds: fast.reduce((sum, s) => sum + (s.end - s.start), 0),
      content_seconds: 10, duration_seconds: 100,
      fast_rate: 6, fast_volume: 0.25, lead_seconds: 0.2, min_fast_seconds: 0.5,
      speech_spans: 12, has_reactions: true, reaction_spans: 3, voice_threshold: 0.2,
      ...extra,
    });
    doc.getElementById("pace-talk").checked = true;
  }

  describe("速度の切り替え", () => {
    beforeEach(() => plan([{ start: 10, end: 20 }]));

    it("無言に入ったら速い速度になり、音量が下がる", () => {
      const video = fakeVideo({ time: 12, volume: 0.8 });
      win.applyTalkPace();
      expect(video.playbackRate).toBe(6);
      expect(video.volume).toBeCloseTo(0.2, 3);
    });

    it("無言を出たら速度も音量も元へ戻る", () => {
      const video = fakeVideo({ time: 12, volume: 0.8 });
      win.applyTalkPace();
      video.currentTime = 25;
      win.applyTalkPace();
      expect(video.volume).toBeCloseTo(0.8, 3);
      expect(video.playbackRate).toBe(Number(doc.getElementById("play-rate").value));
    });

    it("発話の中では速くしない", () => {
      const video = fakeVideo({ time: 5 });
      win.applyTalkPace();
      expect(video.playbackRate).toBe(1);
      expect(video.volume).toBe(1);
    });

    it("止めている間は速くしない", () => {
      const video = fakeVideo({ time: 12, paused: true });
      win.applyTalkPace();
      expect(video.playbackRate).toBe(1);
    });

    it("境界確認再生の間は速くしない(その場所を聞きに行く操作である)", () => {
      const video = fakeVideo({ time: 12 });
      page.set("previewStopAt", 21);
      win.applyTalkPace();
      expect(video.playbackRate).toBe(1);
    });

    it("切ってあれば速くしない", () => {
      doc.getElementById("pace-talk").checked = false;
      const video = fakeVideo({ time: 12 });
      win.applyTalkPace();
      expect(video.playbackRate).toBe(1);
    });

    it("shuttle中は割り込まないし、shuttleの速度も奪わない", () => {
      const video = fakeVideo({ time: 12, volume: 0.8 });
      win.applyTalkPace();               // 早送りに入る
      page.set("forwardStep", 2);        // その最中にJ/K/Lを押した
      video.playbackRate = 2;
      win.applyTalkPace();
      expect(video.playbackRate).toBe(2);
      expect(video.volume).toBeCloseTo(0.8, 3);   // 音量は戻す
    });

    it("計画が空なら何もしない(声の区間が取れなかった録画)", () => {
      plan([], { speech_spans: 0 });
      const video = fakeVideo({ time: 12 });
      win.applyTalkPace();
      expect(video.playbackRate).toBe(1);
      expect(video.volume).toBe(1);
    });
  });

  describe("利用者の音量設定", () => {
    beforeEach(() => plan([{ start: 10, end: 20 }]));

    it("早送り中の下げは設定として保存しない", () => {
      const video = fakeVideo({ time: 12, volume: 0.8 });
      win.applyTalkPace();
      win.syncVolumeUi();
      expect(doc.getElementById("volume").value).not.toBe("20");
    });

    it("早送り中に音量を動かしたら、それが戻り先になる", () => {
      const video = fakeVideo({ time: 12, volume: 0.8 });
      win.applyTalkPace();
      video.volume = 0.5;          // 早送り中に利用者が上げた
      win.applyTalkPace();
      video.currentTime = 25;
      win.applyTalkPace();
      expect(video.volume).toBeGreaterThan(0.8);
    });
  });

  describe("名乗り", () => {
    it("効く録画では飛ばす量と全体の倍率を名乗る", () => {
      plan([{ start: 10, end: 20 }]);
      win.renderPaceNote();
      expect(doc.getElementById("pace-note").textContent).toContain("6x");
      expect(doc.getElementById("pace-note").textContent).toContain("倍速");
    });

    it("声の区間が取れなければ、0件ではなく理由を名乗る", () => {
      plan([], { speech_spans: 0 });
      win.renderPaceNote();
      expect(doc.getElementById("pace-note").textContent).toContain("声の区間");
    });

    it("計画が届く前は解析中だと名乗る(初回は音声を読むので待つ)", () => {
      doc.getElementById("pace-talk").checked = true;
      page.set("state.pacePlan", null);
      win.renderPaceNote();
      expect(doc.getElementById("pace-note").textContent).toContain("解析中");
    });

    it("反応が未解析なら、そう名乗る(速く流れる笑い・叫びがある)", () => {
      plan([{ start: 10, end: 20 }], { has_reactions: false });
      win.renderPaceNote();
      expect(doc.getElementById("pace-note").textContent).toContain("反応は未解析");
    });
  });
});
