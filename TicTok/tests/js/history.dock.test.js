import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 履歴のSession詳細は画面下部へdockする。floating windowは一覧を覆うので、詳細を
// 読みながら別のSessionへ移れなかった。dockは一覧と同時に見えている前提の作りなので、
// 「開いている間だけ一覧を畳む」「開いているSessionの行に印が残る」「閉じるとURLの
// ?session=も戻る」の3つが揃って初めて、行→詳細→次の行と辿れる。
describe("history.js の詳細dock", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  const session = (id) => ({
    id, unique_id: `s${id}`, owner_nickname: `配信者${id}`, owner_avatar: "",
    started_at: 1700000000 + id, ended_at: 1700003600 + id, status: "ended",
    stats: { gifts: 1, diamonds: 2, comments: 3 }, note: "", recording_count: 0,
  });
  const detail = (id) => ({
    session: session(id),
    timeline: { buckets: [], markers: [], bucket_seconds: 60 },
    recordings: [], battles: [],
    summary: { users: [], gifts: [], gift_icons: {} },
    owner: { unique_id: `s${id}`, nickname: `配信者${id}` },
  });

  beforeEach(async () => {
    page = loadPage({
      page: "history",
      url: "http://localhost:8520/history",
      routes: {
        "/api/sessions?limit=0": { sessions: [session(1), session(2)], active_session_ids: [] },
        "/api/sessions/1": detail(1),
        "/api/sessions/2": detail(2),
        "/api/sessions/1/collabs": { collabs: [] },
        "/api/sessions/2/collabs": { collabs: [] },
        "/api/sessions/1/comment-analysis": { analysis: null },
        "/api/sessions/2/comment-analysis": { analysis: null },
      },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const dock = () => doc.getElementById("detail-dock");
  const row = (id) => doc.querySelector(`tr[data-session-id="${id}"]`);

  it("閉じている間は一覧が全高。開くと一覧を畳んでdockが出る", async () => {
    expect(dock().classList.contains("hidden")).toBe(true);
    expect(doc.body.classList.contains("detail-docked")).toBe(false);

    await win.showDetail(1);
    await page.settle();
    expect(dock().classList.contains("hidden")).toBe(false);
    expect(doc.body.classList.contains("detail-docked")).toBe(true);
  });

  it("行をclickしても開く(dockは一覧と並んでいるので行そのものが入口)", async () => {
    row(2).dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await page.settle();
    expect(doc.getElementById("detail-title").textContent).toContain("@s2");
  });

  it("開いているSessionの行にだけ印が付き、切り替えると移る", async () => {
    await win.showDetail(1);
    await page.settle();
    expect(row(1).classList.contains("sel")).toBe(true);
    expect(row(2).classList.contains("sel")).toBe(false);

    await win.showDetail(2);
    await page.settle();
    expect(row(1).classList.contains("sel")).toBe(false);
    expect(row(2).classList.contains("sel")).toBe(true);
  });

  it("閉じると一覧が戻り、印もURLの?session=も残らない", async () => {
    await win.showDetail(1);
    await page.settle();
    expect(win.location.search).toBe("?session=1");

    doc.getElementById("detail-close").dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    await page.settle();
    expect(dock().classList.contains("hidden")).toBe(true);
    expect(doc.body.classList.contains("detail-docked")).toBe(false);
    expect(doc.querySelectorAll("tr.sel")).toHaveLength(0);
    // closeDetailの引数はfromPopState。listenerへ直接渡すとMouseEventが入り、
    // 「戻る由来」と誤認してURLを戻さなくなる。
    expect(win.location.search).toBe("");
  });
});

// マージ表示。合算はserver側(GROUP BY)でしか行わない — client側で各Sessionの結果を
// 足すと、top100で切られたギフターが落ち、改名したuserが別人に割れる。画面側の責任は
// 「合算できない区画を出さないこと」と「何をまとめたのかを名乗ること」の2つ。
describe("history.js のマージ表示", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  const session = (id) => ({
    id, unique_id: `s${id}`, owner_nickname: `配信者${id}`, owner_avatar: "",
    started_at: 1700000000 + id, ended_at: 1700003600 + id, status: "ended",
    stats: { gifts: 1, diamonds: 2, comments: 3 }, note: "", recording_count: 0,
  });
  const MERGED = {
    sessions: [session(1), session(2)],
    stats: {
      gifts: 3, diamonds: 42, comments: 7, likes_total: 11,
      battles: 3, viewers_peak: 40, duration: 7200,
    },
    summary: {
      gift_icons: {},
      users: [{
        unique_id: "whale", nickname: "クジラ", avatar: "",
        gifts: 2, diamonds: 35, gifter_level: 0, gifter_badge: "",
        fans_level: 0, member_badge: "", items: { Rose: { count: 2, diamonds: 35 } },
      }],
      gifts: [{ name: "Rose", count: 2, diamonds: 35 }],
    },
    recordings: [], battles: [], collabs: [],
  };

  // routesはinstallFetchがこのobjectを掴んだまま引くので、後から書き換えると
  // 次のfetchからその応答になる(Sessionが消えた後の挙動を見るため)。
  let routes;

  beforeEach(async () => {
    routes = {
      "/api/sessions?limit=0": { sessions: [session(1), session(2)], active_session_ids: [] },
      "/api/sessions/merged?ids=1,2": MERGED,
    };
    page = loadPage({
      page: "history",
      url: "http://localhost:8520/history",
      routes,
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const checks = () => Array.from(doc.querySelectorAll("#session-rows .sel-cell input"));
  const openBtn = () => doc.getElementById("merge-open");
  const check = (i) => {
    checks()[i].checked = true;
    checks()[i].dispatchEvent(new win.Event("change", { bubbles: true }));
  };

  it("2件選ぶまで押せない(1件をまとめても合算にならない)", () => {
    expect(openBtn().disabled).toBe(true);
    check(0);
    expect(openBtn().disabled).toBe(true);
    expect(openBtn().textContent).toContain("(1)");
    check(1);
    expect(openBtn().disabled).toBe(false);
    expect(openBtn().textContent).toContain("(2)");
  });

  it("何をまとめたのかを見出しで名乗り、合算値をそのまま並べる", async () => {
    await win.showMerged([1, 2]);
    await page.settle();
    const title = doc.getElementById("detail-title").textContent;
    expect(title).toContain("2 Session マージ");
    expect(title).toContain("@s1");
    const chips = Array.from(doc.querySelectorAll("#detail-totals .result-chip"))
      .map((c) => [c.querySelector(".label").textContent, c.querySelector(".value").textContent]);
    expect(chips).toContainEqual(["コイン合計", "42"]);
    // 同時に居た人数は足し算にならない。合算ではないことをlabelで名乗る。
    expect(chips.find(([l]) => l.startsWith("最大同接"))[1]).toBe("40");
    const row = doc.querySelector("#user-ranking tr");
    expect(row.cells[5].textContent.trim()).toBe("35");
  });

  it("合算できない区画はマージ中だけ畳む(Timeline・AI分析・Memo)", async () => {
    await win.showMerged([1, 2]);
    await page.settle();
    const hidden = Array.from(doc.querySelectorAll("#detail-rail .dk-tab.hidden"))
      .map((t) => t.dataset.cat);
    expect(hidden.sort()).toEqual(["ai", "memo", "timeline"]);
    await win.closeDetail();
    expect(doc.querySelectorAll("#detail-rail .dk-tab.hidden")).toHaveLength(0);
  });

  it("畳んだカテゴリを開いたままマージへ移らない(Giftへ戻す)", async () => {
    win.setDetailCategory("timeline");
    expect(win.document.querySelector('.dk-pane[data-cat="timeline"]').classList.contains("on"))
      .toBe(true);
    await win.showMerged([1, 2]);
    await page.settle();
    expect(doc.querySelector('.dk-pane[data-cat="gift"]').classList.contains("on")).toBe(true);
    expect(doc.querySelector('.dk-pane[data-cat="timeline"]').classList.contains("on")).toBe(false);
  });

  it("カテゴリの件数を縦paneへ出す(開かずに中身の有無が分かる)", async () => {
    await win.showMerged([1, 2]);
    await page.settle();
    const n = (cat) => doc.querySelector(`#detail-rail .dk-tab[data-cat="${cat}"] .dk-n`).textContent;
    expect(n("gift")).toBe("1");
    // 0件も「0」で出す。空欄だと「まだ読んでいない」と見分けが付かない。
    expect(n("battle")).toBe("0");
    expect(n("collab")).toBe("0");
    expect(n("rec")).toBe("0");
  });

  it("出力linkはマージ版を指す(単体exportのままだと1Session分しか落ちない)", async () => {
    await win.showMerged([1, 2]);
    await page.settle();
    expect(doc.getElementById("detail-csv").getAttribute("href"))
      .toBe("/api/sessions/merged/export.csv?ids=1,2");
    expect(doc.getElementById("detail-json").getAttribute("href"))
      .toBe("/api/sessions/merged/export.json?ids=1,2");
  });

  it("URLに残るので共有・再読込・戻るButtonが効く", async () => {
    await win.showMerged([1, 2]);
    await page.settle();
    expect(win.location.search).toBe("?merge=1,2");
    await win.closeDetail();
    expect(win.location.search).toBe("");
  });

  it("消えたSessionは選択に残さない(マージ要求がそのidで404になる)", async () => {
    check(0);
    check(1);
    routes["/api/sessions?limit=0"] = { sessions: [session(1)], active_session_ids: [] };
    await win.loadSessions();
    await page.settle();
    expect(page.get("mergeSelected").size).toBe(1);
    expect(openBtn().disabled).toBe(true);
  });
});
