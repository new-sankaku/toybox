import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// シーン検索の録画一覧のメモ。行から直に書く欄なので、(1)行clickの「この録画を開く」を
// 巻き込まないこと、(2)保存できなかった値を欄に残さないこと、(3)1行=1シーンの検索hitでは
// 出さないこと(同じ録画の行が何行も並び、同じ値の欄が縦に重複する)をDOMで確かめる。
describe("videos.js の録画メモ", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  const RECORDINGS = [
    { recording_id: 1, unique_id: "alice", started_at: 100, filename: "a.mp4",
      media: ["ts"], duration_seconds: 60, memo: "音ズレあり", review_state: "unchecked" },
    { recording_id: 2, unique_id: "alice", started_at: 200, filename: "b.mp4",
      media: ["ts"], duration_seconds: 30, memo: "", review_state: "unchecked" },
  ];
  const HITS = [
    { id: 1, source: "stt", recording_id: 1, unique_id: "alice", started_at: 100,
      video_time: 10, snippet: "1件目" },
  ];

  async function open(overrides = {}) {
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: {
        "/api/groups": { items: [] },
        "/api/bookmarks": { items: [] },
        "PATCH /api/recordings/1/memo": { recording_id: 1, memo: "書き換え" },
        "PATCH /api/recordings/2/memo": { recording_id: 2, memo: "使える" },
        ...overrides,
      },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  }

  async function renderBrowse() {
    page.set("state.browsing", true);
    page.set("state.hits", RECORDINGS);
    await page.run("renderHits()");
  }

  const rows = () => Array.from(doc.getElementById("hit-rows").children);
  const memoInputs = () =>
    rows().map((tr) => tr.querySelector("input.vd-memo"));

  beforeEach(async () => {
    await open();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  it("録画一覧の行はメモ欄を持ち、保存済みの値を出す", async () => {
    await renderBrowse();
    expect(memoInputs().map((el) => el && el.value)).toEqual(["音ズレあり", ""]);
    expect(doc.getElementById("hit-memo-th").classList.contains("hidden")).toBe(false);
  });

  // 1行=1シーンのhitでは同じ録画の行が何行も並ぶ。同じ値の欄が縦に重複して並ぶだけになる。
  it("検索hitではメモ列を出さない", async () => {
    page.set("state.browsing", false);
    page.set("state.hits", HITS);
    await page.run("renderHits()");
    expect(doc.getElementById("hit-memo-th").classList.contains("hidden")).toBe(true);
    expect(memoInputs()).toEqual([null]);
  });

  it("欄から離れたときだけPATCHで確定し、前後の空白は落とす", async () => {
    await renderBrowse();
    const before = page.calls.fetches.length;
    const patches = () =>
      page.calls.fetches.slice(before).filter((f) => f.method === "PATCH");
    const input = memoInputs()[1];
    input.value = "  使える  ";
    input.dispatchEvent(new win.Event("change", { bubbles: true }));
    await page.settle();

    expect(patches()).toHaveLength(1);
    expect(patches()[0].url).toBe("/api/recordings/2/memo");
    expect(JSON.parse(patches()[0].body)).toEqual({ memo: "使える" });
    // 保存後の値は行のdataへ戻す。戻さないと、次に離れたとき同じ値をもう一度投げる。
    input.dispatchEvent(new win.Event("change", { bubbles: true }));
    await page.settle();
    expect(patches()).toHaveLength(1);
  });

  it("保存できなかったら欄を保存済みの値へ戻す(書けたものとして次へ進ませない)", async () => {
    await renderBrowse();
    const input = memoInputs()[0];
    win.fetch = async () =>
      new Response(JSON.stringify({ detail: "書けません" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      });
    input.value = "書き換え";
    input.dispatchEvent(new win.Event("change", { bubbles: true }));
    await page.settle();
    expect(input.value).toBe("音ズレあり");
  });

  // 行clickは「この録画を開く」操作。欄の操作がそこへ伝播すると、メモを直すたびに
  // 再生が始まって位置を失う。
  it("メモ欄のclickは行を開かない", async () => {
    await renderBrowse();
    const opened = [];
    rows()[0].addEventListener("click", () => opened.push(true));
    memoInputs()[0].dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    expect(opened).toEqual([]);
  });
});
