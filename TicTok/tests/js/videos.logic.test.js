import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 配信者動画画面。録画の実体(TS/MP4)の名乗り・確認状態の絞り込み・切り出し範囲・
// segment吸着など、秒数と実体の扱いを間違えると出力が壊れる箇所を見る。
describe("videos.js", () => {
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

  describe("mediaBadges", () => {
    it("素材(.ts)とmp4をそれぞれ名乗る", () => {
      const badges = win.mediaBadges(["ts", "mp4"]);
      expect(badges.map((b) => b.textContent)).toEqual(["TS", "MP4"]);
      expect(badges.map((b) => b.className)).toEqual(["vd-src vd-src-ts", "vd-src vd-src-mp4"]);
      expect(badges[0].title).toContain("原本の素材");
    });

    it("実体が1つも無い録画は「実体なし」と言い切る(file名のmp4を実体と読ませない)", () => {
      const badges = win.mediaBadges([]);
      expect(badges).toHaveLength(1);
      expect(badges[0].textContent).toBe("実体なし");
      expect(badges[0].title).toContain("再生できません");
      expect(win.mediaBadges(null)[0].textContent).toBe("実体なし");
    });

    it("未知の種別でも捨てずにそのまま名乗る", () => {
      expect(win.mediaBadges(["mkv"])[0].textContent).toBe("mkv");
    });
  });

  describe("reviewStateOf", () => {
    it("serverの3状態はそのまま通す", () => {
      expect(win.reviewStateOf({ review_state: "checking" })).toBe("checking");
      expect(win.reviewStateOf({ review_state: "checked" })).toBe("checked");
    });

    it("未設定・未知の値は未確認へ寄せる", () => {
      expect(win.reviewStateOf({})).toBe("unchecked");
      expect(win.reviewStateOf({ review_state: "なにか" })).toBe("unchecked");
      expect(win.reviewStateOf(null)).toBe("unchecked");
    });
  });

  describe("hitCutRange", () => {
    it("終了時刻があればIN/OUTの範囲を返す", () => {
      expect(win.hitCutRange({ video_time: 10, end_time: 25 })).toEqual([10, 25]);
    });

    it("終了時刻が無い・開始以前ならrangeを作らない(0秒の切り出しを作らない)", () => {
      expect(win.hitCutRange({ video_time: 10 })).toBeNull();
      expect(win.hitCutRange({ video_time: 10, end_time: 10 })).toBeNull();
      expect(win.hitCutRange({ video_time: 10, end_time: 5 })).toBeNull();
      expect(win.hitCutRange({ video_time: 10, end_time: "x" })).toBeNull();
    });
  });

  describe("snapToSegments", () => {
    beforeEach(() => {
      state().segments = [
        { start: 10.0, end: 20.0 },
        { start: 20.0, end: 31.2 },
      ];
    });

    it("吸着offなら秒をそのまま返す", () => {
      doc.getElementById("snap-seg").checked = false;
      expect(win.snapToSegments(20.4, "in")).toBe(20.4);
    });

    it("IN は segment の開始へ、OUT は終了へ吸着する", () => {
      doc.getElementById("snap-seg").checked = true;
      expect(win.snapToSegments(20.4, "in")).toBe(20.0);
      expect(win.snapToSegments(31.0, "out")).toBe(31.2);
    });

    it("窓(1.5秒)より遠い境界へは吸着しない", () => {
      doc.getElementById("snap-seg").checked = true;
      expect(win.snapToSegments(25.0, "in")).toBe(25.0);
    });

    it("segmentが未取得なら吸着しない(存在しない境界へ寄せない)", () => {
      doc.getElementById("snap-seg").checked = true;
      state().segments = [];
      expect(win.snapToSegments(20.4, "in")).toBe(20.4);
    });
  });

  describe("activeCommentIndex", () => {
    beforeEach(() => {
      state().comments = [{ t: 0 }, { t: 5 }, { t: 5 }, { t: 12 }, { t: 30 }];
    });

    it("再生位置以前の最後のcommentを指す", () => {
      expect(win.activeCommentIndex(0)).toBe(0);
      expect(win.activeCommentIndex(11.9)).toBe(2);
      expect(win.activeCommentIndex(12)).toBe(3);
      expect(win.activeCommentIndex(1000)).toBe(4);
    });

    it("最初のcommentより前は該当なし", () => {
      expect(win.activeCommentIndex(-1)).toBe(-1);
    });

    it("commentが無い録画でも落ちない", () => {
      state().comments = [];
      expect(win.activeCommentIndex(10)).toBe(-1);
    });
  });

  describe("selectedSources", () => {
    it("checkされたsourceだけを送る", () => {
      doc.getElementById("src-stt").checked = true;
      doc.getElementById("src-comment").checked = true;
      expect(win.selectedSources()).toEqual(["stt", "comment"]);
      doc.getElementById("src-comment").checked = false;
      expect(win.selectedSources()).toEqual(["stt"]);
      doc.getElementById("src-stt").checked = false;
      expect(win.selectedSources()).toEqual([]);
    });
  });

  describe("bulkTargetCount", () => {
    const streamer = { targets: { overlay: 3 }, done: { overlay: 7 } };

    it("既定は未処理ぶんだけを数える", () => {
      expect(win.bulkTargetCount(streamer, "overlay", false)).toBe(3);
    });

    it("作り直しなら処理済みも対象へ含める", () => {
      expect(win.bulkTargetCount(streamer, "overlay", true)).toBe(10);
    });

    it("その種別の集計が無ければ0", () => {
      expect(win.bulkTargetCount(streamer, "up", false)).toBe(0);
      expect(win.bulkTargetCount({}, "overlay", true)).toBe(0);
    });
  });

  describe("showView", () => {
    it("選んだviewだけを出し、tabのactiveを一致させる", () => {
      win.showView("cuts");
      expect(doc.getElementById("view-cuts").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(true);
      expect(doc.getElementById("tab-cuts").classList.contains("active")).toBe(true);
      expect(doc.getElementById("tab-search").classList.contains("active")).toBe(false);
    });
  });

  describe("確認状態での絞り込み", () => {
    beforeEach(() => {
      state().browseAll = [
        { recording_id: 1, review_state: "unchecked" },
        { recording_id: 2, review_state: "checked" },
        { recording_id: 3, review_state: "checking" },
        { recording_id: 4 },
      ];
      state().current = null;
      state().hitIndex = -1;
    });

    it("未選択なら全件を残す", () => {
      doc.getElementById("flt-review").value = "";
      win.applyBrowseFilter();
      expect(state().hits.map((r) => r.recording_id)).toEqual([1, 2, 3, 4]);
    });

    it("状態で絞り込み、印の無い録画は未確認として扱う", () => {
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(state().hits.map((r) => r.recording_id)).toEqual([1, 4]);
    });

    it("開いていた録画が一覧から外れたら選択なしへ戻す(別録画に枠を残さない)", () => {
      state().current = { recording_id: 2 };
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(state().hitIndex).toBe(-1);
    });

    it("開いていた録画が残るなら、絞り込み後の位置を追い直す", () => {
      state().current = { recording_id: 4 };
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(state().hitIndex).toBe(1);
    });

    it("0件でも「取得失敗」ではなく、その絞り込みに該当が無いことを名乗る", () => {
      state().browseAll = [{ recording_id: 1, review_state: "checked" }];
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      const empty = doc.getElementById("hit-empty");
      expect(empty.textContent).toBe("「未確認」の録画はありません。");
      expect(empty.classList.contains("list-failed")).toBe(false);
    });

    it("件数の要約に絞り込み後と全体の両方を出す", () => {
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(doc.getElementById("search-summary").textContent).toBe("未確認 2本 / 録画 4本");
    });
  });
});
