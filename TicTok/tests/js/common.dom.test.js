import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadCommon } from "./helpers/page.js";

const TABLE_HTML = `<!doctype html><html><body>
  <table>
    <thead><tr><th>#</th><th>配信者</th><th>コイン</th><th>Comment</th></tr></thead>
    <tbody id="t-body"></tbody>
  </table>
  <div id="t-empty" class="hidden" data-label="録画">対象がありません。</div>
</body></html>`;

describe("renderTableRows", () => {
  let page;
  let win;
  let doc;
  beforeEach(() => {
    page = loadCommon({ html: TABLE_HTML });
    win = page.win;
    doc = page.document;
  });
  afterEach(async () => page.close());

  const rows = [
    { name: "配信者A", coins: 1200, comments: 30 },
    { name: "配信者B", coins: 300, comments: 5 },
  ];
  const toCells = (r, i) => [String(i), r.name, win.fmtNum(r.coins), win.fmtNum(r.comments)];

  it("数値列は data だけでなく header にも num を付ける(ヘッダと値が縦に揃う)", () => {
    win.renderTableRows("t-body", "t-empty", rows, toCells, [0, 2, 3]);
    const ths = Array.from(doc.querySelectorAll("thead th"));
    expect(ths.map((th) => th.classList.contains("num"))).toEqual([true, false, true, true]);
    const firstTds = Array.from(doc.querySelectorAll("#t-body tr:first-child td"));
    expect(firstTds.map((td) => td.className)).toEqual(["num", "", "num", "num"]);
  });

  it("先頭行に rank-top が付く", () => {
    win.renderTableRows("t-body", "t-empty", rows, toCells, []);
    const trs = Array.from(doc.querySelectorAll("#t-body tr"));
    expect(trs[0].className).toBe("rank-top");
    expect(trs[1].className).toBe("");
  });

  it("行が有るときだけ空表示を隠す", () => {
    win.renderTableRows("t-body", "t-empty", rows, toCells, []);
    expect(doc.getElementById("t-empty").classList.contains("hidden")).toBe(true);
    win.renderTableRows("t-body", "t-empty", [], toCells, []);
    expect(doc.getElementById("t-empty").classList.contains("hidden")).toBe(false);
    expect(doc.querySelectorAll("#t-body tr")).toHaveLength(0);
  });

  it("再描画で前回の行が残らない", () => {
    win.renderTableRows("t-body", "t-empty", rows, toCells, []);
    win.renderTableRows("t-body", "t-empty", [rows[0]], toCells, []);
    expect(doc.querySelectorAll("#t-body tr")).toHaveLength(1);
  });

  it("cellがNodeならそのまま入れ、文字列は textContent として入れる(HTMLは解釈しない)", () => {
    const link = doc.createElement("a");
    link.href = "/history";
    link.textContent = "詳細";
    win.renderTableRows("t-body", "t-empty", [rows[0]], () => [link, "<b>生</b>", "", ""], []);
    const tds = Array.from(doc.querySelectorAll("#t-body tr td"));
    expect(tds[0].firstChild).toBe(link);
    expect(tds[1].textContent).toBe("<b>生</b>");
    expect(tds[1].querySelector("b")).toBeNull();
  });

  it("onRow に行要素・元data・indexを渡す", () => {
    const seen = [];
    win.renderTableRows("t-body", "t-empty", rows, toCells, [], (tr, row, i) => {
      tr.dataset.name = row.name;
      seen.push(i);
    });
    expect(seen).toEqual([0, 1]);
    expect(doc.querySelector("#t-body tr").dataset.name).toBe("配信者A");
  });
});

describe("chipBar", () => {
  let page;
  beforeEach(() => {
    page = loadCommon({ html: `<!doctype html><html><body><div id="kpi"></div></body></html>` });
  });
  afterEach(async () => page.close());

  it("label/値のchipを並べ、追加classを値側へ付ける", () => {
    page.win.chipBar("kpi", [["録画", "12"], ["失敗", "1", "bad"]]);
    const chips = Array.from(page.document.querySelectorAll("#kpi .a-chip"));
    expect(chips).toHaveLength(2);
    expect(chips[0].querySelector(".l").textContent).toBe("録画");
    expect(chips[0].querySelector(".v").className).toBe("v");
    expect(chips[1].querySelector(".v").className).toBe("v bad");
  });

  it("再描画で前回のchipが残らない", () => {
    page.win.chipBar("kpi", [["a", "1"], ["b", "2"]]);
    page.win.chipBar("kpi", [["a", "1"]]);
    expect(page.document.querySelectorAll("#kpi .a-chip")).toHaveLength(1);
  });
});

// 「読み込み中」「0件」「取得失敗」は必ず描き分ける。取得できなかったものを0件として
// 描くと、記録が無かったという嘘の提示になる。
describe("一覧placeholderの3状態", () => {
  let page;
  let win;
  let el;
  let warn;
  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body>
        <div id="ph" data-label="運用log">まだ記録がありません。</div>
      </body></html>`,
    });
    win = page.win;
    el = page.document.getElementById("ph");
    warn = vi.spyOn(win.console, "warn").mockImplementation(() => {});
  });
  afterEach(async () => {
    warn.mockRestore();
    await page.close();
  });

  it("loading は読み込み中を出す", () => {
    win.setListState(el, "loading");
    expect(el.textContent).toBe("読み込み中…");
    expect(el.classList.contains("list-loading")).toBe(true);
    expect(el.classList.contains("hidden")).toBe(false);
  });

  it("ok は placeholder ごと隠す", () => {
    win.setListState(el, "ok");
    expect(el.classList.contains("hidden")).toBe(true);
  });

  it("failed は「0件という意味ではありません」を明示し、生文言はtooltipへ逃がす", () => {
    win.setListState(el, "failed", { status: 500, detail: "boom" });
    expect(el.textContent).toBe("運用logを取得できませんでした（0件という意味ではありません）。");
    expect(el.classList.contains("list-failed")).toBe(true);
    expect(el.title).toBe("HTTP 500 / boom");
    expect(warn).toHaveBeenCalled();
  });

  it("empty は最初のtextContent(素の0件文言)へ戻る", () => {
    win.setListState(el, "loading");
    win.setListState(el, "empty");
    expect(el.textContent).toBe("まだ記録がありません。");
    expect(el.classList.contains("list-loading")).toBe(false);
    expect(el.classList.contains("list-failed")).toBe(false);
  });

  it("失敗の後に別状態へ移ると失敗の見た目とtooltipが残らない", () => {
    win.setListState(el, "failed", { status: 500, detail: "boom" });
    win.setListMessage(el, "配信者を選ぶと表示されます。");
    expect(el.textContent).toBe("配信者を選ぶと表示されます。");
    expect(el.classList.contains("list-failed")).toBe(false);
    expect(el.hasAttribute("title")).toBe(false);
  });

  it("要素が無い画面でも落ちない", () => {
    expect(() => win.setListState(null, "loading")).not.toThrow();
    expect(() => win.setListMessage(null, "x")).not.toThrow();
  });
});

describe("空き容量バー", () => {
  let page;
  beforeEach(() => {
    page = loadCommon({ html: `<!doctype html><html><body><div id="bar"></div></body></html>` });
  });
  afterEach(async () => page.close());

  const data = {
    volumes: {
      K: { path: "K:\\rec", total_bytes: 1024 ** 3 * 100, free_bytes: 1024 ** 3 * 25 },
      C: { path: "C:\\", total_bytes: 1024 ** 3 * 200, free_bytes: 1024 ** 3 * 10 },
    },
    low_volumes: ["C"],
    min_free_bytes: 1024 ** 3 * 20,
  };

  it("volumeを名前順に並べ、使用率で塗り、下限割れへ low を付ける", () => {
    const bar = page.document.getElementById("bar");
    page.win.renderDiskBar(bar, data);
    const vols = Array.from(bar.querySelectorAll(".d-vol"));
    expect(vols.map((v) => v.querySelector(".l").textContent)).toEqual(["C", "K"]);
    expect(vols[0].className).toBe("d-vol low");
    expect(vols[1].className).toBe("d-vol");
    // 100GB中25GB空き → 使用率75%、200GB中10GB空き → 95%。
    // (CSSOM は "95.0%" を "95%" へ正規化する)
    expect(vols[0].querySelector(".fill").style.width).toBe("95%");
    expect(vols[1].querySelector(".fill").style.width).toBe("75%");
    expect(vols[1].querySelector(".v").textContent).toBe("25.0GB");
  });

  it("volumeが空なら「不明」と名乗る(0GBと描かない)", () => {
    const bar = page.document.getElementById("bar");
    page.win.renderDiskBar(bar, { volumes: {} });
    expect(bar.textContent).toBe("空き容量: 不明");
  });

  it("取得失敗は不明と区別して「取得失敗」を出す", () => {
    const bar = page.document.getElementById("bar");
    page.win.showDiskUnavailable(bar);
    expect(bar.textContent).toBe("空き容量: 取得失敗");
  });
});

describe("toast", () => {
  let page;
  let win;
  beforeEach(() => {
    page = loadCommon();
    win = page.win;
  });
  afterEach(async () => page.close());

  it("同じ文面のerrorは積まずに回数だけ増やす", () => {
    const first = win.showToast("録画に失敗しました。", "error");
    const again = win.showToast("録画に失敗しました。", "error");
    expect(again).toBe(first);
    expect(page.document.querySelectorAll(".toast-error")).toHaveLength(1);
    expect(first.querySelector(".toast-count").textContent).toBe("×2");
  });

  it("文面が違えば別のtoastとして積む", () => {
    win.showToast("A に失敗しました。", "error");
    win.showToast("B に失敗しました。", "error");
    expect(page.document.querySelectorAll(".toast-error")).toHaveLength(2);
  });

  it("空文言では何も出さない", () => {
    expect(win.showToast("")).toBeNull();
    expect(win.showToast(null)).toBeNull();
    expect(page.document.querySelectorAll(".toast")).toHaveLength(0);
  });

  it("showError は Error の message を error toast にする", () => {
    win.showError(new Error("Serverへ接続できませんでした。"));
    const toast = page.document.querySelector(".toast-error");
    expect(toast.querySelector(".toast-body").textContent).toBe("Serverへ接続できませんでした。");
  });

  it("閉じるbuttonで消える", () => {
    win.showToast("お知らせ");
    page.document.querySelector(".toast-close").click();
    expect(page.document.querySelectorAll(".toast")).toHaveLength(0);
  });

  it("titleを付けると見出し行が出て、無指定なら出ない", () => {
    win.showToast("接続できませんでした。", "error", { title: "録画の保護" });
    win.showToast("保存しました。");
    const withTitle = page.document.querySelector(".toast-error");
    expect(withTitle.querySelector(".toast-title").textContent).toBe("録画の保護");
    const plain = page.document.querySelector(".toast:not(.toast-error)");
    expect(plain.querySelector(".toast-title")).toBeNull();
  });

  it("titleが違えば同じ文面でも別のtoastとして積む", () => {
    win.showToast("接続できませんでした。", "error", { title: "録画の保護" });
    win.showToast("接続できませんでした。", "error", { title: "派生物の削除" });
    expect(page.document.querySelectorAll(".toast-error")).toHaveLength(2);
  });

  it("showError の第2引数が操作名の見出しになる", () => {
    win.showError(new Error("Serverへ接続できませんでした。"), "派生物の削除");
    const toast = page.document.querySelector(".toast-error");
    expect(toast.querySelector(".toast-title").textContent).toBe("派生物の削除");
    expect(toast.querySelector(".toast-body").textContent).toBe("Serverへ接続できませんでした。");
  });

  it("配列は1行ずつ順に出る", async () => {
    vi.useFakeTimers();
    try {
      const toast = win.showToast(["1行目", "2行目", "3行目"]);
      expect(toast.querySelectorAll(".toast-line")).toHaveLength(1);
      vi.advanceTimersByTime(50);
      expect(toast.querySelectorAll(".toast-line")).toHaveLength(2);
      vi.advanceTimersByTime(100);
      expect(toast.querySelectorAll(".toast-line")).toHaveLength(3);
      expect(toast.textContent).toContain("3行目");
    } finally {
      vi.useRealTimers();
    }
  });

  it("空行は詰めて、全部空なら何も出さない", () => {
    const toast = win.showToast(["有効な行", "", null]);
    expect(toast.querySelectorAll(".toast-line")).toHaveLength(1);
    expect(win.showToast(["", null])).toBeNull();
  });

  it("進捗barは自動で消える情報表示にだけ付く(errorには付けない)", () => {
    win.showToast("保存しました。");
    win.showToast("失敗しました。", "error");
    const plain = page.document.querySelector(".toast:not(.toast-error)");
    expect(plain.querySelector(".toast-progress-bar")).not.toBeNull();
    expect(page.document.querySelector(".toast-error .toast-progress-bar")).toBeNull();
  });

  it("情報表示は出し切ってからdurationぶん経つと消え、errorは残る", () => {
    vi.useFakeTimers();
    try {
      win.showToast("保存しました。", null, { duration: 1000 });
      win.showToast("失敗しました。", "error");
      vi.advanceTimersByTime(50);
      expect(page.document.querySelectorAll(".toast:not(.toast-error)")).toHaveLength(1);
      vi.advanceTimersByTime(1000);
      expect(page.document.querySelectorAll(".toast:not(.toast-error)")).toHaveLength(0);
      expect(page.document.querySelectorAll(".toast-error")).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("segmented control", () => {
  let page;
  let win;
  let root;
  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body>
        <div id="rate" class="seg" role="radiogroup" data-value="1" data-revert="1">
          <button class="seg-item" type="button" data-value="0.5">0.5x</button>
          <button class="seg-item" type="button" data-value="1">1x</button>
          <button class="seg-item" type="button" data-value="2" disabled>2x</button>
          <button class="seg-item" type="button" data-value="4">4x</button>
        </div>
      </body></html>`,
    });
    win = page.win;
    root = win.initSegmented("rate");
  });
  afterEach(async () => page.close());

  it("<select>と同じ value / selectedIndex / options のI/Fを持つ", () => {
    expect(root.value).toBe("1");
    expect(root.selectedIndex).toBe(1);
    expect(root.options.map((o) => o.value)).toEqual(["0.5", "1", "2", "4"]);
  });

  it("初期選択に seg-on と aria-checked が付き、tab stopは1つだけ", () => {
    const items = Array.from(page.document.querySelectorAll(".seg-item"));
    expect(items.map((b) => b.classList.contains("seg-on"))).toEqual([false, true, false, false]);
    expect(items.map((b) => b.getAttribute("aria-checked"))).toEqual(["false", "true", "false", "false"]);
    expect(items.filter((b) => b.tabIndex === 0)).toHaveLength(1);
  });

  it("値の代入はuser操作ではないので change を出さない", () => {
    const onChange = vi.fn();
    root.addEventListener("change", onChange);
    root.value = "4";
    expect(root.value).toBe("4");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("click は change を出す", () => {
    const onChange = vi.fn();
    root.addEventListener("change", onChange);
    page.document.querySelectorAll(".seg-item")[0].click();
    expect(root.value).toBe("0.5");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("矢印keyは disabled の選択肢を飛ばす", () => {
    root.value = "1";
    root.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(root.value).toBe("4");
  });

  it("Home / End は端へ移る", () => {
    root.dispatchEvent(new win.KeyboardEvent("keydown", { key: "End", bubbles: true }));
    expect(root.value).toBe("4");
    root.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    expect(root.value).toBe("0.5");
  });
});

// 段の多い群(再生速度)はpillを並べず1本のbarで出す。呼び出し側は<select>と同じI/Fで
// 書かれているので、置き換えて壊れる形は「I/Fが違う」か「操作がchangeを出さない」。
describe("目盛り付きのbar", () => {
  let page;
  let win;
  let root;
  const range = () => page.document.querySelector(".segbar-range");
  const out = () => page.document.querySelector(".segbar-out");
  const drag = (index) => {
    range().value = String(index);
    range().dispatchEvent(new win.Event("input", { bubbles: true }));
  };
  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body>
        <span id="rate" class="segbar" data-stops="0.5,1,2,4" data-value="1"
              data-revert="1" data-wheel="1" data-label="再生速度" data-unit="x"></span>
      </body></html>`,
    });
    win = page.win;
    root = win.initSegBar("rate");
  });
  afterEach(async () => page.close());

  it("<select>と同じ value / selectedIndex / options のI/Fを持つ", () => {
    expect(root.value).toBe("1");
    expect(root.selectedIndex).toBe(1);
    expect(root.options.map((o) => o.value)).toEqual(["0.5", "1", "2", "4"]);
  });

  it("今の値をbarの隣に出す(barだけでは「この辺」までしか読めない)", () => {
    expect(out().textContent).toBe("1x");
    expect(range().max).toBe("3");
    expect(range().value).toBe("1");
  });

  it("摘みを動かすと change を出す(離すまで待たない)", () => {
    const onChange = vi.fn();
    root.addEventListener("change", onChange);
    drag(3);
    expect(root.value).toBe("4");
    expect(out().textContent).toBe("4x");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("値の表示をclickすると既定値へ戻す(pillの「選択中を再click」の代わり)", () => {
    drag(3);
    out().click();
    expect(root.value).toBe("1");
  });

  it("wheelは1段ずつ送る(向きはsegmented controlと同じ)", () => {
    root.dispatchEvent(new win.WheelEvent("wheel", { deltaY: 1, bubbles: true, cancelable: true }));
    expect(root.value).toBe("2");
    root.dispatchEvent(new win.WheelEvent("wheel", { deltaY: -1, bubbles: true, cancelable: true }));
    expect(root.value).toBe("1");
  });

  it("値の代入はuser操作ではないので change を出さない", () => {
    const onChange = vi.fn();
    root.addEventListener("change", onChange);
    root.value = "2";
    expect(root.value).toBe("2");
    expect(range().value).toBe("2");
    expect(onChange).not.toHaveBeenCalled();
  });
});

// job件数はnavの「Job」に付くbadge。数の出所はWSだけで、届く前は何も描かない
// (0件と描くと「job が無い」という未確認の主張になる)。
describe("job badge", () => {
  let page;
  let win;
  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body><div class="a-topbar"><nav class="a-nav"></nav></div></body></html>`,
    });
    win = page.win;
  });
  afterEach(async () => page.close());

  const jobLink = () => page.document.querySelector('.a-nav a[href^="/jobs"]');
  const jobBadge = () => jobLink().querySelector(".nav-badge");

  it("snapshot が届く前はbadgeそのものを作らない", () => {
    expect(jobBadge()).toBeNull();
  });

  it("実行中・待機中の合計を出す", () => {
    win.applyJobBar({
      type: "jobs",
      data: [
        { job_id: "1", state: "running" },
        { job_id: "2", state: "pending" },
        { job_id: "3", state: "pending" },
        { job_id: "4", state: "completed" },
      ],
    });
    expect(jobBadge().textContent).toBe("3");
    expect(jobBadge().className).toBe("nav-badge");
    expect(jobLink().title).toContain("実行中 1 / 待機中 2");
  });

  it("失敗・中断が在るときはその件数を警告色で出すが、tabの行き先は変えない", () => {
    win.applyJobBar({
      type: "jobs",
      data: [
        { job_id: "1", state: "failed" },
        { job_id: "2", state: "interrupted" },
      ],
    });
    expect(jobBadge().textContent).toBe("2");
    expect(jobBadge().className).toContain("alert");
    // filterを積むと、失敗が履歴に残っている間ずっと「失敗・中断のみ」へ着地し、
    // 人が選んだ状態filterが押すたびに上書きされる。
    expect(jobLink().getAttribute("href")).toBe("/jobs");
    expect(jobLink().title).toContain("失敗・中断が2件");
    expect(win.jobBarFailedCount()).toBe(2);
  });

  // badgeを引く側がhrefの文字列で照合していた頃は、tabのhrefにqueryが付いた時点で
  // linkを見失い、以後どれだけjobが動いても数字がその場で固まっていた。
  it("tabのhrefにqueryが付いていても数え直せる", () => {
    win.applyJobBar({ type: "jobs", data: [{ job_id: "1", state: "failed" }] });
    jobLink().setAttribute("href", "/jobs?state=failed");
    win.applyJobBar({
      type: "jobs",
      data: [{ job_id: "1", state: "failed" }, { job_id: "2", state: "failed" }],
    });
    expect(jobBadge().textContent).toBe("2");
  });

  it("session一括投入の明細行は合成行と二重に数えない", () => {
    win.applyJobBar({
      type: "jobs",
      data: [
        { job_id: "g1", group_id: "g1", state: "running" },
        { job_id: "j1", group_id: "g1", state: "running" },
        { job_id: "j2", group_id: "g1", state: "pending" },
      ],
    });
    expect(jobBadge().textContent).toBe("1");
  });

  it("動いているjobが無ければbadgeを空にする", () => {
    win.applyJobBar({ type: "jobs", data: [{ job_id: "1", state: "running" }] });
    win.applyJobBar({ type: "jobs", data: [{ job_id: "1", state: "completed" }] });
    expect(jobBadge().textContent).toBe("");
    expect(jobLink().hasAttribute("title")).toBe(false);
    expect(jobLink().getAttribute("href")).toBe("/jobs");
  });
});

describe("jobEtaText", () => {
  let page;
  let win;
  beforeEach(() => {
    page = loadCommon();
    win = page.win;
  });
  afterEach(async () => page.close());

  it("進捗が浅いうちは残り時間を出さない(当てにならない外挿をしない)", () => {
    const now = Date.now() / 1000;
    expect(win.jobEtaText({ started_at: now - 60, pct: 4 })).toBe("");
    expect(win.jobEtaText({ started_at: now - 60, pct: 0 })).toBe("");
  });

  it("開始時刻が無いjobは残り時間を出さない", () => {
    expect(win.jobEtaText({ pct: 50 })).toBe("");
  });

  it("完了済みは残り時間を出さない", () => {
    expect(win.jobEtaText({ started_at: Date.now() / 1000 - 60, pct: 100 })).toBe("");
  });

  it("経過時間から線形に外挿する", () => {
    // common.js は jsdom realm の中で動くので、そちらの Date を止める。
    const now = vi.spyOn(win.Date, "now").mockReturnValue(1_000_000_000 * 1000);
    try {
      // 100秒で25%進んだ → 残り75%は300秒。
      expect(win.jobEtaText({ started_at: 1_000_000_000 - 100, pct: 25 })).toBe("残り約 00:05:00");
    } finally {
      now.mockRestore();
    }
  });
});
