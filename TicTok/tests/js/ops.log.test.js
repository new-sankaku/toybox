import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 運用logは「昨夜なにが壊れたか」を遡る画面。1行のlogから対象の画面へ辿れないと、番号を
// 手で控えて別画面で探し直すことになる。ここでは辿る導線と、条件の確定手段、種別の
// 選び方を確かめる。
const KINDS = {
  kinds: [
    { kind: "overlay.job_started", count: 12 },
    { kind: "overlay.job_failed", count: 3 },
    { kind: "collector.disconnected", count: 7 },
  ],
  unique_ids: [{ unique_id: "tester", count: 9 }],
  kind_labels: {
    "overlay.job_started": "コメント焼き込み・開始",
    "overlay.job_failed": "コメント焼き込み・失敗",
    "collector.disconnected": "eventの切断",
  },
};

const PAGE_SIZE = 200;

function eventsPayload(events) {
  return {
    // serverは1requestにpage sizeぶんしか返さない。新着が1ページに収まらない状況を
    // 再現するため、stubも同じところで切る。
    events: events.slice(0, PAGE_SIZE),
    limit: PAGE_SIZE,
    next: null,
    severities: ["error", "warning", "info"],
    detail_max_chars: 4000,
    retention_days: 90,
    settings_kind: "process.settings_updated",
    kind_labels: KINDS.kind_labels,
  };
}

const EVENT = {
  id: 501,
  ops_id: "abc123",
  ts: 1767000000,
  severity: "warning",
  kind: "overlay.job_failed",
  message: "焼き込みに失敗しました",
  detail: {},
  duration_ms: 1500,
  unique_id: "tester",
  session_id: 339,
  session_unique_id: "tester",
  recording_id: null,
  recording_filename: null,
  job_id: "9f2a1b",
};

function loadOps(events) {
  return loadPage({
    page: "ops",
    url: "http://localhost:8520/ops",
    routes: {
      "/api/ops/kinds": KINDS,
      "/api/ops/summary": { since: 0, window_hours: 24, counts: { error: 1, warning: 2, info: 3 } },
      // fetchのstubはURLの完全一致で引く。条件が空のときのquery("?"だけ)と、
      // 種別を選んだときのqueryを別々に置く。
      "/api/ops/events?": () => eventsPayload(events),
      "/api/ops/events?kind_prefix=overlay.": () => eventsPayload(events),
      "/api/perf": {
        enabled: true, window_seconds: 60, request_count: 0, total_ms: 0,
        routes: [], loop_lag: { max_ms: 0, warned: 0 }, inflight: [], config: {},
      },
      "/api/disk": { volumes: {}, min_free_bytes: 0, low_volumes: [] },
    },
  });
}

describe("ops.js の対象列", () => {
  let page;
  let errorSpy;

  beforeEach(async () => {
    page = loadOps([EVENT]);
    errorSpy = vi.spyOn(page.win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  it("session は履歴画面へのlinkにする", () => {
    const link = page.document.querySelector("#ops-rows td.ops-target a");
    expect(link.getAttribute("href")).toBe("/history?session=339");
    expect(link.textContent).toBe("session #00339");
  });

  // 削除済みsessionの飛び先は無い。押して空の画面へ着く方が「消えた」より読みにくい。
  it("削除済みsessionはlinkにしない", async () => {
    const node = page.win.targetNode({ ...EVENT, session_unique_id: null });
    expect(node.querySelector("a")).toBe(null);
    expect(node.textContent).toContain("session #00339（削除済み）");
  });

  it("対象が何も無い記録は - を出す(空欄にしない)", () => {
    const node = page.win.targetNode({ id: 1 });
    expect(node.textContent).toBe("-");
  });

  // job_idは1回の処理に紐づく記録を束ねる唯一のkey。写して貼らせない。
  it("job_id からは同一画面の絞り込みとJob画面の両方へ行ける", () => {
    const detail = page.document.querySelector("#ops-rows .ops-detail");
    const button = Array.from(detail.querySelectorAll("button")).find(
      (el) => el.textContent === "このjobだけ",
    );
    expect(button).toBeTruthy();
    button.dispatchEvent(new page.win.Event("click", { bubbles: true }));
    expect(page.document.getElementById("flt-job").value).toBe("9f2a1b");
    const link = Array.from(detail.querySelectorAll("a")).find(
      (el) => el.getAttribute("href") === "/jobs?job=9f2a1b",
    );
    expect(link).toBeTruthy();
  });
});

describe("ops.js の条件", () => {
  let page;
  let errorSpy;

  beforeEach(async () => {
    page = loadOps([EVENT]);
    errorSpy = vi.spyOn(page.win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  // 数十件のflatな一覧から目で拾うのは現実的でない。group名はkindの前半そのままにする:
  // 日本語のgroup名を画面が作ると、Serverが持たない訳語を名乗ることになる。
  it("種別はdomainでまとめ、group先頭に前方一致の「すべて」を置く", () => {
    const groups = Array.from(page.document.querySelectorAll("#flt-kind optgroup"));
    expect(groups.map((g) => g.label)).toEqual(["overlay", "collector"]);
    const first = groups[0].querySelector("option");
    expect(first.value).toBe("overlay.");
    expect(first.textContent).toBe("overlay すべて（15）");
    // 個別のkindは日本語で出し、記録上のkeyはtooltipに残す。
    const kinds = Array.from(groups[0].querySelectorAll("option")).slice(1);
    expect(kinds.map((o) => o.value)).toEqual(["overlay.job_started", "overlay.job_failed"]);
    expect(kinds[0].title).toBe("overlay.job_started");
  });

  it("「すべて」を選ぶと前方一致(kind_prefix)で問い合わせる", async () => {
    const select = page.document.getElementById("flt-kind");
    select.value = "overlay.";
    select.dispatchEvent(new page.win.Event("change", { bubbles: true }));
    await page.settle();
    const last = page.calls.fetches.filter((f) => f.url.startsWith("/api/ops/events")).pop();
    expect(last.url).toContain("kind_prefix=overlay.");
  });

  // 打ち終わりが判らない自由入力はchangeで走らせないが、Enterで確定できないと打った後に
  // mouseへ持ち替えることになる。
  it.each(["flt-job", "flt-since", "flt-until"])("%s はEnterで絞り込める", async (id) => {
    const before = page.calls.fetches.filter((f) => f.url.startsWith("/api/ops/events")).length;
    const input = page.document.getElementById(id);
    const ev = new page.win.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    input.dispatchEvent(ev);
    await page.settle();
    expect(ev.defaultPrevented).toBe(true);
    const after = page.calls.fetches.filter((f) => f.url.startsWith("/api/ops/events")).length;
    expect(after).toBe(before + 1);
  });
});

describe("ops.js の新着", () => {
  let page;
  let errorSpy;
  let events;

  beforeEach(async () => {
    // routes の handler はこの配列を毎回読む。後から記録が入った状況を作れる。
    events = [EVENT];
    page = loadOps(events);
    errorSpy = vi.spyOn(page.win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  it("新着が無いうちはbuttonの文言を変えない", () => {
    expect(page.document.getElementById("ops-reload").textContent).toBe("最新にする");
  });

  it("表に出ている最新より後の記録を数える(表は勝手に入れ替えない)", async () => {
    const rowsBefore = page.document.getElementById("ops-rows").childElementCount;
    page.win.setNewEventCount(3, false);
    expect(page.document.getElementById("ops-reload").textContent).toBe("最新にする（新着 3件）");
    // 基準の行がpageに入っていなければ「以上」と断る(ちょうどの数は分からない)。
    page.win.setNewEventCount(200, true);
    expect(page.document.getElementById("ops-reload").textContent).toBe("最新にする（新着 200件以上）");
    expect(page.document.getElementById("ops-rows").childElementCount).toBe(rowsBefore);
  });

  // 表を勝手に入れ替えると、追っている記録が読んでいる途中で流れる。数だけ出して、
  // 入れ替えは押した時にする。
  it("後から入った記録を数え、表はそのままにする", async () => {
    const rowsBefore = page.document.getElementById("ops-rows").childElementCount;
    events.unshift({ ...EVENT, id: 503, ops_id: "c3" }, { ...EVENT, id: 502, ops_id: "c2" });
    await page.win.pollOpsUpdates();
    await page.settle();
    expect(page.document.getElementById("ops-reload").textContent).toBe("最新にする（新着 2件）");
    expect(page.document.getElementById("ops-rows").childElementCount).toBe(rowsBefore);
  });

  it("基準の行がpageに入らないほど入っていれば「以上」と断る", async () => {
    const many = Array.from({ length: 250 }, (_, i) => ({ ...EVENT, id: 1000 + i, ops_id: `x${i}` }));
    events.unshift(...many);
    await page.win.pollOpsUpdates();
    await page.settle();
    expect(page.document.getElementById("ops-reload").textContent)
      .toBe("最新にする（新着 200件以上）");
  });

  it("押すと今の条件で取り直し、新着の表示を戻す", async () => {
    page.win.setNewEventCount(3, false);
    page.document.getElementById("ops-reload").dispatchEvent(
      new page.win.Event("click", { bubbles: true }),
    );
    await page.settle();
    expect(page.document.getElementById("ops-reload").textContent).toBe("最新にする");
  });
});
