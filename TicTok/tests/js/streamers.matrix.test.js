import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 人×期間の一覧(Gifter × 配信日/週/月)。1つの期間の断面しか出せなかった表の上に、期間を
// 列・人を行にした一覧を置く。縛るのは6点。
// (1) 投げていない列は空欄のまま(0で埋めると「0コイン投げた」に読める)。
// (2) 見出しclickだけで並べ替える。もう一度押すと昇順へ反す。
// (3) 列の見出しは投げていない人を消さずに薄く下へ落とし、下の期間別ランキングも同じ
//     期間へ送る(見つけた期間をもう一度selectから選び直させない)。
// (4) 粒度(日/週/月)を変えると列を引き直し、見出しの名乗りも追う。
// (5) カレンダーの範囲は問い合わせに乗り、0件になっても「記録が無い」と名乗らない。
// (6) 取得できなかったときに「記録がありません」と名乗らない。
describe("streamers.js の人×期間の一覧", () => {
  let page;
  let win;
  let doc;

  // 窓は問い合わせのquery そのもの。route を実URLで張って、画面が組み立てた窓が
  // 意図どおりかを応答の側から縛る。
  const URL_DAY = "/api/streamers/streamer/matrix?granularity=day";
  const URL_MONTH = "/api/streamers/streamer/matrix?granularity=month";
  const URL_SINCE = "/api/streamers/streamer/matrix?granularity=day&since=2026-09-01";

  const PERIODS = [
    { key: "2026-08-01", diamonds: 900, gifts: 9, battles: 1 },
    { key: "2026-08-03", diamonds: 400, gifts: 4, battles: 0 },
    { key: "2026-08-04", diamonds: 100, gifts: 1, battles: 2 },
  ];
  const MATRIX = {
    granularity: "day",
    since: "",
    until: "",
    first_date: "2026-07-01",
    last_date: "2026-08-04",
    periods: PERIODS,
    gifters: [
      {
        identity_key: "k1", user_id: "1", unique_id: "fan01", nickname: "FAN01",
        avatar: "", fans_level: 0, gifter_level: 0, gifter_badge: "",
        member_badge: "", league: "", diamonds: 900, gifts: 9, periods: 2,
        cells: {
          "2026-08-01": { diamonds: 800, gifts: 8 },
          "2026-08-04": { diamonds: 100, gifts: 1 },
        },
      },
      {
        identity_key: "k2", user_id: "2", unique_id: "fan02", nickname: "FAN02",
        avatar: "", fans_level: 0, gifter_level: 0, gifter_badge: "",
        member_badge: "", league: "", diamonds: 500, gifts: 5, periods: 2,
        cells: {
          "2026-08-01": { diamonds: 100, gifts: 1 },
          "2026-08-03": { diamonds: 400, gifts: 4 },
        },
      },
    ],
    battle_gifters: [],
    gifter_count: 2,
    battle_gifter_count: 0,
    older_periods: 5,
  };
  const MONTHLY = {
    ...MATRIX,
    granularity: "month",
    periods: [
      { key: "2026-07", diamonds: 5000, gifts: 50, battles: 3 },
      { key: "2026-08", diamonds: 1400, gifts: 14, battles: 3 },
    ],
    gifters: [{
      ...MATRIX.gifters[0], diamonds: 6400, periods: 2,
      cells: {
        "2026-07": { diamonds: 5000, gifts: 50 },
        "2026-08": { diamonds: 1400, gifts: 14 },
      },
    }],
    gifter_count: 1,
    older_periods: 0,
  };
  const EMPTY_RANGE = {
    ...MATRIX, since: "2026-09-01", until: "2026-09-30",
    periods: [], gifters: [], battle_gifters: [],
    gifter_count: 0, battle_gifter_count: 0, older_periods: 0,
  };

  function load(routes) {
    page = loadPage({ page: "streamers", url: "http://localhost:8520/streamers", routes });
    win = page.win;
    doc = page.document;
    return page.settle();
  }

  async function loadMatrix(routes) {
    await load(routes);
    win.eval("selectedUid = 'streamer'");
    await win.loadMatrix("streamer");
  }

  function colHeads() {
    return Array.from(doc.querySelectorAll("#sm-gmx th.sm-mx-day"))
      .map((th) => th.querySelector("b").textContent);
  }
  function numHeads() {
    return Array.from(doc.querySelectorAll("#sm-gmx thead th.sm-mx-num"))
      .map((th) => th.textContent.replace(/[▼▲\s]/g, ""));
  }
  function rowNames() {
    return Array.from(doc.querySelectorAll("#sm-gmx tbody tr"))
      .map((tr) => tr.querySelector(".u-name").textContent);
  }
  function cellsOf(rowIndex) {
    return Array.from(doc.querySelectorAll("#sm-gmx tbody tr")[rowIndex]
      .querySelectorAll("td.sm-mx-cell")).map((td) => td.textContent);
  }
  // 見出しは並べ替えのたびに描き直されるので、押す直前に引き直す(押した瞬間の節を
  // 持ち回ると、外れた古い節を見ることになる)。
  function findHead(text) {
    return Array.from(doc.querySelectorAll("#sm-gmx thead th"))
      .find((el) => (el.querySelector("b") || el).textContent.startsWith(text));
  }
  function clickHead(text) {
    findHead(text).dispatchEvent(new win.Event("click", { bubbles: true }));
  }
  function clickSeg(id, value) {
    doc.querySelector(`#${id} [data-value="${value}"]`)
      .dispatchEvent(new win.Event("click", { bubbles: true }));
  }

  beforeEach(() => {
    page = null;
  });
  afterEach(async () => {
    if (page) await page.close();
  });

  it("列は配信日、行は人。投げていない列は空欄のまま残す", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX });
    expect(colHeads()).toEqual(["08/01", "08/03", "08/04"]);
    expect(rowNames()).toEqual(["FAN01", "FAN02"]);
    // 800 / (投げていない) / 100
    expect(cellsOf(0)).toEqual(["800", "", "100"]);
    expect(cellsOf(1)).toEqual(["100", "400", ""]);
    // 2つの表が同じ窓を見ているときは1回の応答を分け合う。1回の応答に両方の一覧が
    // 入っているので、別々に投げるとserver側で同じ集計を2度走らせることになる。
    expect(page.calls.fetches.filter((f) => f.url.includes("/matrix"))).toHaveLength(1);
  });

  it("出していない古い期間と、切った人数を名乗る", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX });
    const note = doc.getElementById("sm-gmx-note").textContent;
    expect(note).toContain("Gifter 2 人");
    expect(note).toContain("直近 3 配信日");
    expect(note).toContain("古い 5 日");
  });

  it("列の見出しでその列の順に並び替え、投げていない人は消さずに薄く下へ落とす", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX });
    // 08/03に投げたのはFAN02だけ。通算1位のFAN01は下へ落ちるが行は残る。
    clickHead("08/03");
    expect(rowNames()).toEqual(["FAN02", "FAN01"]);
    const rows = doc.querySelectorAll("#sm-gmx tbody tr");
    expect(rows[0].className).not.toContain("sm-mx-off");
    expect(rows[1].className).toContain("sm-mx-off");
    // 並んだ列の順位を行の先頭に出す。投げていない人には付けない。
    expect(rows[0].querySelector(".sm-mx-rank").textContent).toBe("1");
    expect(rows[1].querySelector(".sm-mx-rank")).toBeNull();
  });

  it("同じ見出しをもう一度押すと昇順へ反し、順位は出さない", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX });
    clickHead("08/01");
    expect(rowNames()).toEqual(["FAN01", "FAN02"]);
    clickHead("08/01");
    expect(rowNames()).toEqual(["FAN02", "FAN01"]);
    expect(findHead("08/01").textContent).toContain("▲");
    // 昇順では1位が最下位になるので、順位は付けない。
    expect(doc.querySelector("#sm-gmx tbody .sm-mx-rank")).toBeNull();
  });

  it("通算・伸びの見出しでも並び替わる（並び順の専用buttonは置かない）", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX });
    expect(doc.getElementById("sm-gmx-sort")).toBeNull();
    // 伸び(後半 − 前半)はFAN02が正、FAN01は08/01が前半なので負。
    clickHead("伸び");
    expect(rowNames()).toEqual(["FAN02", "FAN01"]);
    clickHead("通算");
    expect(rowNames()).toEqual(["FAN01", "FAN02"]);
  });

  it("列の見出しは下の期間別ランキングも同じ期間へ送る", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX });
    clickHead("08/03");
    expect(JSON.parse(win.eval("JSON.stringify(rankingPick['sm-gifters'])"))).toEqual({
      granularity: "day", period: "2026-08-03",
    });
    // 粒度の表示も追従させる(表の上のsegが「全期間」のままだと、表がどの日の物か読めない)。
    expect(doc.getElementById("sm-gifters-gran").value).toBe("day");
  });

  it("粒度を変えると列を引き直し、見出しの名乗りも追う", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX, [URL_MONTH]: MONTHLY });
    expect(doc.getElementById("sm-gmx-unit").textContent).toBe("配信日");
    clickSeg("sm-gmx-gran", "month");
    await page.settle();
    expect(doc.getElementById("sm-gmx-unit").textContent).toBe("配信月");
    // 月の列は年から出す(07だけでは何年の7月か読めない)。
    expect(colHeads()).toEqual(["2026/07", "2026/08"]);
    expect(numHeads()).toEqual(["通算", "月数", "伸び"]);
    expect(doc.getElementById("sm-gmx-note").textContent).toContain("直近 2 配信月");
  });

  it("カレンダーの範囲は問い合わせに乗り、0件を「記録が無い」と名乗らない", async () => {
    await loadMatrix({ [URL_DAY]: MATRIX, [URL_SINCE]: EMPTY_RANGE });
    // カレンダーの端は在る記録に合わせる。
    expect(doc.getElementById("sm-gmx-since").min).toBe("2026-07-01");
    expect(doc.getElementById("sm-gmx-until").max).toBe("2026-08-04");
    doc.getElementById("sm-gmx-since").value = "2026-09-01";
    doc.getElementById("sm-gmx-since").dispatchEvent(new win.Event("change", { bubbles: true }));
    await page.settle();
    const empty = doc.getElementById("sm-gmx-empty");
    expect(empty.className).not.toContain("hidden");
    expect(empty.textContent).toContain("選んだ期間");
    // 「最新へ」で指定を外し、元の窓へ戻る。
    doc.getElementById("sm-gmx-latest").dispatchEvent(new win.Event("click", { bubbles: true }));
    await page.settle();
    expect(doc.getElementById("sm-gmx-since").value).toBe("");
    expect(colHeads()).toEqual(["08/01", "08/03", "08/04"]);
  });

  it("取得できなかったときは0件として描かない", async () => {
    await loadMatrix({});
    const empty = doc.getElementById("sm-gmx-empty");
    expect(empty.className).toContain("list-failed");
    expect(empty.textContent).not.toContain("ありません。");
    expect(doc.querySelectorAll("#sm-gmx tbody tr")).toHaveLength(0);
  });
});
