import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// Job一覧の行の組み立て。session一括はgroupの合成行と明細行の両方が台帳に載るので、
// 畳み方を誤ると**filterに一致したjobが一覧から消える**。行が出ないだけなので、
// 「そんなjobは無かった」と読まれて終わる。
describe("jobs.js の行の組み立て", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "jobs", url: "http://localhost:8520/jobs" });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  function seed(list) {
    page.set("jobs", list);
  }
  function setFilter({ state = "all", kind = "all" } = {}) {
    doc.getElementById("job-flt-state").value = state;
    doc.getElementById("job-flt-kind").value = kind;
  }
  function expand(...groupIds) {
    page.run(`expandedGroups.clear(); ${groupIds.map((g) => `expandedGroups.add(${JSON.stringify(g)})`).join("; ")}`);
  }
  const rowIds = () => win.visibleRows().map((r) => r.job.job_id);

  const GROUP = [
    { job_id: "g1", group_id: "g1", state: "running", domain: "overlay", started_at: 100 },
    { job_id: "m1", group_id: "g1", state: "running", domain: "overlay", started_at: 101 },
    { job_id: "m2", group_id: "g1", state: "pending", domain: "overlay", queued_at: 102 },
    { job_id: "solo", state: "completed", domain: "stt", finished_at: 90 },
  ];

  describe("groupの畳み込み", () => {
    it("既定ではgroupの明細を出さず、合成行だけを出す", () => {
      seed(GROUP);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["g1", "solo"]);
    });

    it("合成行には畳んでいる明細の件数を持たせる", () => {
      seed(GROUP);
      setFilter();
      expand();
      const rows = win.visibleRows();
      expect(rows.find((r) => r.job.job_id === "g1").members).toBe(2);
      expect(rows.find((r) => r.job.job_id === "solo").members).toBe(0);
    });

    it("開いたgroupは合成行の直後へ明細を差し込む", () => {
      seed(GROUP);
      setFilter();
      expand("g1");
      expect(rowIds()).toEqual(["g1", "m1", "m2", "solo"]);
    });

    it("差し込んだ明細はsub行として印を持つ", () => {
      seed(GROUP);
      setFilter();
      expand("g1");
      const rows = win.visibleRows();
      expect(rows.map((r) => Boolean(r.sub))).toEqual([false, true, true, false]);
    });
  });

  // ここが本題。filterでgroupの合成行が落ちたとき、明細を畳んだまま隠すと
  // 「filterに一致しているのに一覧に出ないjob」ができる。
  describe("groupの合成行がfilterで落ちたとき", () => {
    it("明細を単独行として出す(消さない)", () => {
      seed([
        { job_id: "g1", group_id: "g1", state: "completed", domain: "overlay", finished_at: 50 },
        { job_id: "m1", group_id: "g1", state: "running", domain: "overlay", started_at: 101 },
      ]);
      setFilter({ state: "active" });
      expand();
      // 合成行(completed)はfilterから外れるが、実行中の明細は出す。
      expect(rowIds()).toEqual(["m1"]);
    });

    it("種別filterで合成行が落ちた場合も同じ", () => {
      seed([
        { job_id: "g1", group_id: "g1", state: "running", domain: "session_overlay", started_at: 100 },
        { job_id: "m1", group_id: "g1", state: "running", domain: "overlay", started_at: 101 },
      ]);
      setFilter({ kind: "overlay" });
      expand();
      expect(rowIds()).toEqual(["m1"]);
    });
  });

  describe("filter", () => {
    // domain は 種別select の option value と同じ語を使う(選べない種別で絞ると
    // 一致0件になるため、実際に選べる値でしかこの経路は再現できない)。
    const LIST = [
      { job_id: "a", state: "running", domain: "overlay", started_at: 10 },
      { job_id: "b", state: "pending", domain: "overlay", queued_at: 11 },
      { job_id: "c", state: "completed", domain: "upscale", finished_at: 12 },
      { job_id: "d", state: "failed", domain: "upscale", finished_at: 13 },
      { job_id: "e", state: "interrupted", domain: "reprocess", finished_at: 14 },
      { job_id: "f", state: "cancelled", domain: "reprocess", finished_at: 15 },
    ];

    it("active は実行中と待機中だけ", () => {
      seed(LIST);
      setFilter({ state: "active" });
      expand();
      expect(rowIds().sort()).toEqual(["a", "b"]);
    });

    it("failed は失敗と中断だけ(取り消しは混ぜない)", () => {
      seed(LIST);
      setFilter({ state: "failed" });
      expand();
      expect(rowIds().sort()).toEqual(["d", "e"]);
    });

    it("all は全部", () => {
      seed(LIST);
      setFilter({ state: "all" });
      expand();
      expect(rowIds()).toHaveLength(6);
    });

    it("種別は domain で絞る", () => {
      seed(LIST);
      setFilter({ kind: "upscale" });
      expand();
      expect(rowIds().sort()).toEqual(["c", "d"]);
    });

    it("状態と種別は同時に効く", () => {
      seed(LIST);
      setFilter({ state: "failed", kind: "upscale" });
      expand();
      expect(rowIds()).toEqual(["d"]);
    });
  });

  // 動いているjobを過去のjobの下に埋めない。
  describe("並び", () => {
    it("実行中 → 待機中 → 終わったもの の順に置く", () => {
      seed([
        { job_id: "done", state: "completed", finished_at: 999 },
        { job_id: "wait", state: "pending", queued_at: 1 },
        { job_id: "run", state: "running", started_at: 2 },
      ]);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["run", "wait", "done"]);
    });

    it("同じ状態どうしは新しいものが上", () => {
      seed([
        { job_id: "old", state: "completed", finished_at: 100 },
        { job_id: "new", state: "completed", finished_at: 200 },
      ]);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["new", "old"]);
    });

    it("時刻はfinished→started→queuedの順に見る", () => {
      seed([
        { job_id: "q", state: "completed", queued_at: 500 },
        { job_id: "s", state: "completed", started_at: 300, queued_at: 1 },
      ]);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["q", "s"]);
    });

    it("元の配列を並べ替えない(台帳の順序を壊さない)", () => {
      const list = [
        { job_id: "done", state: "completed", finished_at: 999 },
        { job_id: "run", state: "running", started_at: 2 },
      ];
      seed(list);
      setFilter();
      expand();
      win.visibleRows();
      expect(page.get("jobs").map((j) => j.job_id)).toEqual(["done", "run"]);
    });
  });

  describe("状態badge", () => {
    it("未知の状態でも行を落とさず、その状態名をそのまま出す", () => {
      const cell = win.stateCell({ state: "なにか未知" });
      expect(cell.textContent).toBe("なにか未知");
    });

    it("対象なし(skipped)は失敗色にしない", () => {
      expect(win.stateCell({ state: "skipped" }).className).toBe("badge badge-idle");
      expect(win.stateCell({ state: "failed" }).className).toBe("badge badge-error");
    });

    it("前提の復帰待ちは順番待ちと区別して名乗る", () => {
      const future = { state: "pending", not_before: Date.now() / 1000 + 600, stage: "K:の復帰待ち" };
      const cell = win.stateCell(future);
      expect(cell.textContent).toBe("復帰待ち");
      expect(cell.title).toBe("K:の復帰待ち");
    });

    it("待ち時刻を過ぎた待機は通常の待機中に戻る", () => {
      const past = { state: "pending", not_before: Date.now() / 1000 - 600 };
      expect(win.stateCell(past).textContent).toBe("待機中");
    });
  });
});
