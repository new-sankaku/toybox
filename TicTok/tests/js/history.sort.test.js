import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 履歴の絞り込みと並び替え。並替selectと列headerのclickは同じsortStateを書き換える
// 作りなので、片方が実際の並びと違う指定を出したまま残ると、**表は正しく描かれているのに
// 見出しが嘘の順序を名乗る**。行が消えるbugと違って気付かれない。
describe("history.js の絞り込みと並び替え", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "history", url: "http://localhost:8520/history" });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const DAY = 86400;
  const NOW = Math.floor(Date.now() / 1000);

  // 期間filterに引っ掛からないよう、既定は「今」に十分近い時刻へ置く。
  const SESSIONS = [
    {
      id: 1, unique_id: "alpha", owner_nickname: "アルファ", note: "初回",
      started_at: NOW - 300, ended_at: NOW - 100, status: "ended",
      stats: { diamonds: 500, comments: 10 },
    },
    {
      id: 2, unique_id: "bravo", owner_nickname: "ブラボー", note: "",
      started_at: NOW - 200, ended_at: NOW - 50, status: "ended",
      stats: { diamonds: 1500, comments: 3 },
    },
    {
      id: 3, unique_id: "charlie", owner_nickname: "チャーリー", note: "PK多め",
      started_at: NOW - 100, ended_at: null, status: "live",
      stats: { diamonds: 100, comments: 40 },
    },
    {
      id: 4, unique_id: "delta", owner_nickname: "デルタ", note: "",
      started_at: NOW - 50, ended_at: NOW - 10, status: "restricted",
      stats: {},
    },
  ];

  function seed({ sessions = SESSIONS, active = [3] } = {}) {
    page.set("allSessions", sessions);
    page.run(`activeIds = new Set(${JSON.stringify(active)})`);
  }

  function setFilters({ search = "", period = "all", status = "all" } = {}) {
    doc.getElementById("flt-search").value = search;
    doc.getElementById("flt-period").value = period;
    doc.getElementById("flt-status").value = status;
  }

  function ids() {
    return win.filteredSessions().map((s) => s.id);
  }

  describe("periodStart", () => {
    it("all(未知の指定)は下限なし", () => {
      expect(win.periodStart("all")).toBe(0);
      expect(win.periodStart("")).toBe(0);
    });

    it("todayはその日の0時ちょうど", () => {
      const start = win.periodStart("today");
      const d = new Date(start * 1000);
      expect([d.getHours(), d.getMinutes(), d.getSeconds()]).toEqual([0, 0, 0]);
      const today = new Date();
      expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([
        today.getFullYear(), today.getMonth(), today.getDate(),
      ]);
    });

    it("weekは月曜始まり(日曜を週初めにしない)", () => {
      const start = win.periodStart("week");
      const d = new Date(start * 1000);
      expect(d.getDay()).toBe(1); // 1 = 月曜
      expect([d.getHours(), d.getMinutes(), d.getSeconds()]).toEqual([0, 0, 0]);
      const elapsed = Date.now() / 1000 - start;
      expect(elapsed).toBeGreaterThanOrEqual(0);
      expect(elapsed).toBeLessThan(7 * DAY);
    });

    it("monthはその月の1日0時", () => {
      const d = new Date(win.periodStart("month") * 1000);
      expect(d.getDate()).toBe(1);
      expect([d.getHours(), d.getMinutes(), d.getSeconds()]).toEqual([0, 0, 0]);
    });
  });

  describe("sessionStat", () => {
    it("集計が無いsessionは0(欠測を0件として描くが、行自体は残す)", () => {
      expect(win.sessionStat({}, "diamonds")).toBe(0);
      expect(win.sessionStat({ stats: {} }, "diamonds")).toBe(0);
      expect(win.sessionStat({ stats: { diamonds: 7 } }, "diamonds")).toBe(7);
    });
  });

  // 並替selectの文言。時刻は「新しい/古い」、文字は「昇順/降順」、長さは「長い/短い」、
  // 件数は「多い/少ない」。ここを取り違えると、selectが実際と逆の順序を名乗る。
  describe("sortOptionLabel", () => {
    it("時刻の列は新しい/古いで言う", () => {
      expect(win.sortOptionLabel("started_at", "desc")).toBe("開始(新しい順)");
      expect(win.sortOptionLabel("started_at", "asc")).toBe("開始(古い順)");
    });

    it("文字の列は昇順/降順で言う", () => {
      expect(win.sortOptionLabel("unique_id", "asc")).toBe("配信者(昇順)");
      expect(win.sortOptionLabel("unique_id", "desc")).toBe("配信者(降順)");
    });

    it("長さの列は長い/短いで言う", () => {
      expect(win.sortOptionLabel("duration", "desc")).toBe("時間 長い順");
      expect(win.sortOptionLabel("duration", "asc")).toBe("時間 短い順");
    });

    it("件数の列は多い/少ないで言う", () => {
      expect(win.sortOptionLabel("diamonds", "desc")).toBe("コイン 多い順");
      expect(win.sortOptionLabel("diamonds", "asc")).toBe("コイン 少ない順");
    });
  });

  describe("filteredSessions の絞り込み", () => {
    beforeEach(() => seed());

    it("既定(all)は全件", () => {
      setFilters();
      expect(ids().sort()).toEqual([1, 2, 3, 4]);
    });

    it("@idでも表示名でもMemoでも引ける(見えているのに絞り込めない状態を作らない)", () => {
      setFilters({ search: "charlie" });
      expect(ids()).toEqual([3]);
      setFilters({ search: "チャーリー" });
      expect(ids()).toEqual([3]);
      setFilters({ search: "PK多め" });
      expect(ids()).toEqual([3]);
    });

    it("検索は大小文字を無視する", () => {
      setFilters({ search: "ALPHA" });
      expect(ids()).toEqual([1]);
    });

    it("live は収集中のsessionだけ", () => {
      setFilters({ status: "live" });
      expect(ids()).toEqual([3]);
    });

    it("ended は収集中と制限付きのどちらも外す", () => {
      setFilters({ status: "ended" });
      expect(ids().sort()).toEqual([1, 2]);
    });

    it("restricted は制限付きだけ", () => {
      setFilters({ status: "restricted" });
      expect(ids()).toEqual([4]);
    });

    it("期間より前に始まったsessionは落とす", () => {
      page.set("allSessions", [
        { ...SESSIONS[0], id: 90, started_at: NOW - 400 * DAY },
        { ...SESSIONS[1], id: 91, started_at: NOW - 60 },
      ]);
      setFilters({ period: "today" });
      expect(ids()).toEqual([91]);
    });
  });

  describe("filteredSessions の並び", () => {
    beforeEach(() => seed());

    it("既定は開始の新しい順", () => {
      setFilters();
      expect(ids()).toEqual([4, 3, 2, 1]);
    });

    it("集計の列は値で並ぶ(欠測は0として末尾へ)", () => {
      setFilters();
      page.run(`sortState = { key: "diamonds", dir: "desc" }`);
      expect(ids()).toEqual([2, 1, 3, 4]);
      page.run(`sortState = { key: "diamonds", dir: "asc" }`);
      expect(ids()).toEqual([4, 3, 1, 2]);
    });

    it("文字の列は文字列比較で並ぶ", () => {
      setFilters();
      page.run(`sortState = { key: "unique_id", dir: "asc" }`);
      expect(ids()).toEqual([1, 2, 3, 4]);
      page.run(`sortState = { key: "unique_id", dir: "desc" }`);
      expect(ids()).toEqual([4, 3, 2, 1]);
    });

    it("同値の並びは開始時刻とidで必ず決まる(描画ごとに揺れない)", () => {
      page.set("allSessions", [
        { id: 10, unique_id: "x", started_at: NOW - 100, stats: { diamonds: 5 } },
        { id: 11, unique_id: "x", started_at: NOW - 100, stats: { diamonds: 5 } },
        { id: 12, unique_id: "x", started_at: NOW - 50, stats: { diamonds: 5 } },
      ]);
      page.run(`activeIds = new Set()`);
      setFilters();
      page.run(`sortState = { key: "diamonds", dir: "desc" }`);
      const first = ids();
      expect(first).toEqual([12, 11, 10]);
      expect(ids()).toEqual(first);
    });

    it("未知のsort keyでも落とさず開始時刻へ戻す", () => {
      setFilters();
      page.run(`sortState = { key: "なにか未知", dir: "desc" }`);
      expect(ids()).toEqual([4, 3, 2, 1]);
    });

    it("収集中sessionの長さは現時点までの経過で並べる(終了時刻が無いので)", () => {
      page.set("allSessions", [
        { id: 20, unique_id: "a", started_at: NOW - 60, ended_at: NOW - 30, stats: {} },
        { id: 21, unique_id: "b", started_at: NOW - 600, ended_at: null, stats: {} },
      ]);
      page.run(`activeIds = new Set([21])`);
      setFilters();
      page.run(`sortState = { key: "duration", dir: "desc" }`);
      expect(ids()).toEqual([21, 20]);
    });
  });

  // 列headerの見た目・aria-sortが実際のsortStateと一致していること。
  // ここがずれると、表は正しいのに見出しが逆の順序を名乗る。
  describe("列headerの表示と実際の並びの一致", () => {
    const headerState = () =>
      Array.from(doc.querySelectorAll("#session-table th[data-sort]")).map((th) => ({
        key: th.dataset.sort,
        sorted: th.classList.contains("sorted"),
        asc: th.classList.contains("sorted-asc"),
        aria: th.getAttribute("aria-sort"),
      }));

    it("並び中の列だけが sorted を名乗る", () => {
      page.run(`sortState = { key: "diamonds", dir: "desc" }`);
      win.syncSortHeaders();
      const rows = headerState();
      expect(rows.filter((r) => r.sorted).map((r) => r.key)).toEqual(["diamonds"]);
      expect(rows.filter((r) => !r.sorted).every((r) => r.aria === "none")).toBe(true);
    });

    it("aria-sort が実際の向きと一致する", () => {
      page.run(`sortState = { key: "diamonds", dir: "desc" }`);
      win.syncSortHeaders();
      expect(headerState().find((r) => r.key === "diamonds")).toMatchObject({
        asc: false, aria: "descending",
      });

      page.run(`sortState = { key: "diamonds", dir: "asc" }`);
      win.syncSortHeaders();
      expect(headerState().find((r) => r.key === "diamonds")).toMatchObject({
        asc: true, aria: "ascending",
      });
    });
  });

  // 操作列は2群(状態の右 = 詳細/焼き込み、数値の後ろ = AI高画質/字幕化/削除)に分かれ、
  // 各群の幅はheaderのcolspanでしか宣言されない。列数がずれると、表は描かれるのに
  // 見出しと値が1列ずつずれる — 行が消えるbugと違って気付かれない。
  describe("操作列の配置", () => {
    const headers = () =>
      Array.from(doc.querySelectorAll("#session-table thead th"));
    const labels = (tr) =>
      Array.from(tr.cells).map((td) => td.textContent.trim());

    function renderWith({ upscale = false, stt = false } = {}) {
      seed();
      setFilters();
      page.set("upscaleConfigured", upscale);
      page.set("sttConfigured", stt);
      win.renderTable();
      return doc.querySelectorAll("#session-rows tr");
    }

    it("headerのcolspan合計と行のcell数が一致する(設定で列が増減しても)", () => {
      [{}, { upscale: true }, { stt: true }, { upscale: true, stt: true }].forEach((opts) => {
        const rows = renderWith(opts);
        const declared = headers().reduce((sum, th) => sum + th.colSpan, 0);
        expect(rows.length).toBeGreaterThan(0);
        rows.forEach((tr) => expect(tr.cells.length).toBe(declared));
      });
    });

    it("詳細と焼き込みは配信者の左、残りの操作は数値の後ろ", () => {
      renderWith({ upscale: true, stt: true });
      // 終了済みで録画のあるsession(=全操作が活性)で並びを見る。
      page.set("allSessions", [{ ...SESSIONS[0], recording_count: 1 }]);
      win.renderTable();
      const cells = labels(doc.querySelector("#session-rows tr"));
      // 行頭はマージ選択のcheck(labelは空)、その次が # 。
      expect(cells[0]).toBe("");
      expect(cells[1]).toBe("#00001");
      // # の次が操作の先頭群で、その右に 配信者・開始・時間・状態 が並ぶ。
      expect(cells.slice(2, 4)).toEqual(["詳細", "焼き込み"]);
      // 状態の次からが数値列(コインが先頭)。
      expect(cells[8]).toBe("500");
      // 末尾はMemo(入力欄なので空文字)を挟んで残りの操作。
      expect(cells.slice(-3)).toEqual(["AI高画質", "字幕化", "削除"]);
    });
  });

  describe("applySort", () => {
    beforeEach(() => seed());

    it("別の列を押すとその列の既定の向きで並ぶ", () => {
      page.run(`sortState = { key: "started_at", dir: "desc" }`);
      win.applySort("diamonds");
      expect(page.get("sortState")).toEqual({ key: "diamonds", dir: "desc" });
      win.applySort("unique_id");
      expect(page.get("sortState")).toEqual({ key: "unique_id", dir: "asc" });
    });

    it("同じ列をもう一度押すと向きが入れ替わる", () => {
      win.applySort("diamonds");
      win.applySort("diamonds");
      expect(page.get("sortState")).toEqual({ key: "diamonds", dir: "asc" });
      win.applySort("diamonds");
      expect(page.get("sortState")).toEqual({ key: "diamonds", dir: "desc" });
    });

    it("知らない列は何も変えない", () => {
      page.run(`sortState = { key: "started_at", dir: "desc" }`);
      win.applySort("存在しない列");
      expect(page.get("sortState")).toEqual({ key: "started_at", dir: "desc" });
    });

    it("列を押した並びも並替selectが同じ順序を名乗る", () => {
      win.applySort("diamonds");
      const select = doc.getElementById("flt-sort");
      expect(select.value).toBe("diamonds");

      // selectの選択肢に無い並び(コイン昇順)は、専用の選択肢を足して名乗る。
      win.applySort("diamonds");
      expect(select.options[select.selectedIndex].textContent).toBe("コイン 少ない順");
    });
  });
});
