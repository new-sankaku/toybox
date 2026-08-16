import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 1つの配信からは検索hitも見どころも何行も出る。行ごとに配信者と配信日を
// 繰り返すと、読みたい差分(位置・内容)が同じ文字列の柱に埋もれる。畳む単位が日付に
// 化けると同じ日の別配信が1つに見え、隣接判定を失うと離れた同じ配信まで名乗らなくなる
// ため、どの表でも「先頭だけが名乗る・別配信は必ず名乗る」をDOMで確かめる。
describe("videos.js の同じ配信の畳み込み", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  // 録画1が2件続き、録画2へ移り、また録画1へ戻る並び。日付は全て同じにして、
  // 「日付が同じ」ではなく「録画が同じ」で畳んでいることを検出できるようにする。
  const MARKS = [
    { id: 10, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 10, end: 20, memo: "1本目", group_id: null, position: null,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 11, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 30, end: 40, memo: "2本目", group_id: null, position: null,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 12, recording_id: 2, unique_id: "alice", recording_started_at: 100,
      start: 50, end: 60, memo: "別配信", group_id: null, position: null,
      origin: "manual", pts_mapped: 1, filename: "b.mp4" },
    { id: 13, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 70, end: 80, memo: "戻り", group_id: null, position: null,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
  ];
  const HITS = [
    { id: 1, source: "stt", recording_id: 1, unique_id: "alice", started_at: 100,
      video_time: 10, snippet: "1件目" },
    { id: 2, source: "stt", recording_id: 1, unique_id: "alice", started_at: 100,
      video_time: 30, snippet: "2件目" },
    { id: 3, source: "stt", recording_id: 2, unique_id: "alice", started_at: 100,
      video_time: 50, snippet: "別配信" },
  ];

  async function open(overrides = {}) {
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: {
        "/api/groups": { items: [] },
        "/api/bookmarks": { items: MARKS },
        ...overrides,
      },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  }

  beforeEach(async () => {
    await open();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const rowsOf = (id) => Array.from(doc.querySelectorAll(`#${id} tr`));
  // 身元2列の中身。畳まれた行は「〃」になる。
  const identityOf = (tr, first) =>
    [tr.children[first].textContent, tr.children[first + 1].textContent];

  // 身元2列は 配信者(4)・配信日(5)。列は 視聴・選択・順・出所・配信者・配信日… の並び。
  describe("見どころ", () => {
    // グループを選んでいない間の並びは配信日→録画→開始位置なので、同じ録画の行は必ず
    // 隣り合う(録画1の3件が先に並び、録画2が続く)。
    it("同じ配信が続く間は先頭行だけが配信者と配信日を名乗る", () => {
      const rows = rowsOf("mark-rows");
      expect(rows).toHaveLength(4);
      expect(identityOf(rows[0], 4)).toEqual(["alice", win.fmtYmd(100)]);
      expect(identityOf(rows[1], 4)).toEqual(["〃", "〃"]);
      expect(identityOf(rows[2], 4)).toEqual(["〃", "〃"]);
    });

    it("別の配信へ移ったら必ず名乗り直す(日付が同じでも畳まない)", () => {
      expect(identityOf(rowsOf("mark-rows")[3], 4)).toEqual(["alice", win.fmtYmd(100)]);
    });

    it("畳んだ行も実際の値をtitleで引ける(行だけを読んでも身元が辿れる)", () => {
      const cell = rowsOf("mark-rows")[1].children[5].firstChild;
      expect(cell.className).toBe("vd-ditto");
      expect(cell.title).toBe(win.fmtYmd(100));
    });

    it("続きの行は塊として読めるようにclassを持つ(先頭行は持たない)", () => {
      const rows = rowsOf("mark-rows");
      expect(rows.map((tr) => tr.classList.contains("vd-cont")))
        .toEqual([false, true, true, false]);
    });

    // グループを選んでいる間の並びは人が決めた書き出し順なので、同じ録画の行が離れて
    // 並び得る。隣接ではなく日付で畳む退行は、この並びでしか落ちない。
    describe("書き出し順に並べたとき", () => {
      const GROUPED = MARKS.map((mark, index) => ({
        ...mark, group_id: 1, position: [0, 2, 1, 3][index],
      }));

      beforeEach(async () => {
        await page.close();
        await open({
          "/api/groups": { items: [{ id: 1, name: "神回", memo: "", created_at: 1 }] },
          "/api/bookmarks": { items: GROUPED },
        });
        doc.getElementById("marks-groups").querySelectorAll(".vd-group-pick")[2].click();
      });

      it("離れた場所の同じ録画は隣が別配信なので改めて名乗る", () => {
        const rows = rowsOf("mark-rows");
        // 録画1 → 録画2 → 録画1 → 録画1 の順。3行目は同じ録画だが隣が別配信である。
        expect(rows.map((tr) => tr.classList.contains("vd-cont")))
          .toEqual([false, false, false, true]);
        expect(identityOf(rows[2], 4)).toEqual(["alice", win.fmtYmd(100)]);
      });
    });
  });

  describe("シーン検索のhit", () => {
    it("同じ録画の別のシーンが続く間は先頭行だけが名乗る", async () => {
      page.set("state.browsing", false);
      page.set("state.hits", HITS);
      await page.run("renderHits()");
      const rows = rowsOf("hit-rows");
      expect(rows).toHaveLength(3);
      expect(identityOf(rows[0], 1)).toEqual(["alice", win.fmtYmd(100)]);
      expect(identityOf(rows[1], 1)).toEqual(["〃", "〃"]);
      expect(identityOf(rows[2], 1)).toEqual(["alice", win.fmtYmd(100)]);
    });

    // 録画一覧は1行=1録画。身元を持たない行が並んでも全部が同じ配信に化けないこと。
    it("録画一覧(browse)では畳まない", async () => {
      page.set("state.browsing", true);
      page.set("state.hits", [
        { unique_id: "alice", started_at: 100, filename: "a.mp4", media: ["ts"] },
        { unique_id: "alice", started_at: 100, filename: "b.mp4", media: ["ts"] },
      ]);
      await page.run("renderHits()");
      const rows = rowsOf("hit-rows");
      // 録画一覧の列は 配信者・配信日・尺 の3つ(種別と内容は隠す)。
      expect(rows.map((tr) => tr.children[1].textContent))
        .toEqual([win.fmtYmd(100), win.fmtYmd(100)]);
      expect(rows.some((tr) => tr.classList.contains("vd-cont"))).toBe(false);
    });
  });
});
