import { describe, it, expect, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 監視画面のコラボ相手欄。コラボ(非BattleのLinkMic)のpeerは数値user_idしか名乗らないため、
// 表示名も戦績も配信者profileの対戦相手別集計(user_id軸)から解決する。ここが噛み合わなく
// なると、画面には「対戦履歴なし」だけが出て誰も間違いに気付けない。
const PEER = "7300000000000000104";
const OTHER = "7300000000000000102";

function profile() {
  return {
    battles: {
      opponents: [
        {
          key: PEER,
          user_id: PEER,
          unique_id: "kotsubu",
          nickname: "こつぶ組",
          avatar: "",
          battles: 3,
          wins: 2,
          losses: 1,
        },
        {
          key: OTHER,
          user_id: OTHER,
          unique_id: "other",
          nickname: "別の相手",
          avatar: "",
          battles: 1,
          wins: 0,
          losses: 1,
        },
      ],
      history: [
        {
          session_id: 12,
          battle_id: 903,
          started_at: 1786200000,
          type: "personal",
          own_score: 40000,
          opp_score: 30000,
          result: "win",
          opponent_count: 1,
          opponent_keys: [PEER],
          opponent_user_ids: [PEER],
        },
        {
          session_id: 12,
          battle_id: 902,
          started_at: 1786100000,
          type: "personal",
          own_score: 10000,
          opp_score: 20000,
          result: "lose",
          opponent_count: 1,
          opponent_keys: [PEER],
          opponent_user_ids: [PEER],
        },
        {
          session_id: 11,
          battle_id: 901,
          started_at: 1786000000,
          type: "personal",
          own_score: 30000,
          opp_score: 10000,
          result: "win",
          opponent_count: 1,
          opponent_keys: [PEER],
          opponent_user_ids: [PEER],
        },
        {
          session_id: 11,
          battle_id: 900,
          started_at: 1785900000,
          type: "team",
          own_score: 5000,
          opp_score: 9000,
          result: "lose",
          opponent_count: 2,
          opponent_keys: [OTHER],
          opponent_user_ids: [OTHER],
        },
      ],
    },
  };
}

function snapshot(collab) {
  return {
    unique_id: "streamer_c",
    status: "connected",
    simulation: false,
    error_message: null,
    ffmpeg_available: true,
    record_video: true,
    recording: null,
    owner: { unique_id: "streamer_c", nickname: "うぃ", avatar: "" },
    session_id: 12,
    room_id: 777,
    stats: {},
    steps: [],
    recent_events: [],
    collab,
  };
}

const SERIES = {
  battle_id: 903,
  start_time: 1786200000,
  end_time: 1786200300,
  type: "personal",
  result: "win",
  participants: [
    { user_id: "own", nickname: "うぃ", is_own: true, side: "own" },
    { user_id: PEER, nickname: "こつぶ組", is_own: false, side: "opp" },
  ],
  series: [
    { t: 1786200000, own: 0, opp: 0, parts: [{ id: PEER, score: 0 }] },
    { t: 1786200100, own: 12000, opp: 9000, parts: [{ id: PEER, score: 9000 }] },
    { t: 1786200300, own: 40000, opp: 30000, parts: [{ id: PEER, score: 30000 }] },
  ],
};

const ROUTES = {
  "/api/streamers/streamer_c/profile": profile,
  "/api/monitors/streamer_c/battles": { unique_id: "streamer_c", owner: {}, battles: [] },
  "/api/monitors/streamer_c/timeline": { bucket_seconds: 10, buckets: [], markers: [] },
  "/api/monitors/streamer_c/summary": { totals: {}, users: [], gifts: [] },
  "/api/monitors/streamer_c/history-stats": { sessions: [] },
  "/api/system/disk": { entries: [] },
  [`/api/sessions/12/battle-series/903`]: SERIES,
};

// 直近欄の上限を確かめるため、その相手との戦をn件(新しい順)に水増ししたprofile。
function profileWithBattles(n) {
  const data = profile();
  data.battles.history = Array.from({ length: n }, (_, i) => ({
    session_id: 12,
    battle_id: 800 + n - i,
    started_at: 1786200000 - i * 1000,
    type: "personal",
    own_score: 1000,
    opp_score: 500,
    result: i % 2 ? "lose" : "win",
    opponent_count: 1,
    opponent_keys: [PEER],
    opponent_user_ids: [PEER],
  }));
  return data;
}

async function openPage(collab, opts = {}) {
  const routes = opts.battles
    ? { ...ROUTES, "/api/streamers/streamer_c/profile": () => profileWithBattles(opts.battles) }
    : ROUTES;
  const page = loadPage({ page: "index", url: "http://localhost:8520/", routes });
  page.fireReady();
  await page.settle();
  page.calls.sockets[0].emit({ type: "monitors", data: [snapshot(collab)] });
  await page.settle();
  return page;
}

const LIVE_COLLAB = [{ channel_id: "c1", start: 1786200000, guests_max: 1, peers: [PEER] }];

describe("監視画面のコラボ相手の対戦履歴", () => {
  let page;
  afterEach(async () => {
    if (page) await page.close();
    page = null;
  });

  it("コラボしていなければ何も出さない", async () => {
    page = await openPage([]);
    const panel = page.document.getElementById("collab-vs");
    expect(panel.classList.contains("hidden")).toBe(true);
    expect(page.document.querySelector('#seg-bar button[data-pane="battle"]').classList.contains("collab-live")).toBe(false);
  });

  it("コラボが始まったら相手の通算成績を出す", async () => {
    page = await openPage(LIVE_COLLAB);
    const panel = page.document.getElementById("collab-vs");
    expect(panel.classList.contains("hidden")).toBe(false);
    expect(panel.querySelector(".cvs-name").textContent).toContain("こつぶ組");
    // その相手が出た3戦だけを数える(別の相手の1戦は入らない)。
    expect(panel.querySelector(".cvs-rec").textContent).toBe("3戦 2勝1敗");
    expect(panel.querySelector(".cvs-rate").textContent).toBe("66.7%");
    expect(page.document.querySelector('#seg-bar button[data-pane="battle"]').classList.contains("collab-live")).toBe(true);
  });

  it("直近の勝敗は勝/負の文字で古→新に並べ、平均は自陣/敵陣で出す", async () => {
    page = await openPage(LIVE_COLLAB);
    const line = page.document.querySelector("#collab-vs .cvs-line");
    // history は新しい順(win, lose, win) → 表示は古い順(勝/負/勝)。記号(●○)は勝ち負けを
    // 取り違えるので文字で名乗る。
    const marks = [...line.querySelectorAll(".cvs-mark")];
    expect(marks.map((m) => m.textContent)).toEqual(["勝", "負", "勝"]);
    expect(marks.map((m) => m.className)).toEqual(["cvs-mark win", "cvs-mark lose", "cvs-mark win"]);
    expect(line.textContent).toContain("直近3戦");
    expect(line.textContent).toContain("平均 自陣 26.7K / 敵陣 20K");
  });

  it("直近の勝敗は最大10戦まで(古い戦は載せない)", async () => {
    page = await openPage(LIVE_COLLAB, { battles: 14 });
    const marks = [...page.document.querySelectorAll("#collab-vs .cvs-line .cvs-mark")];
    expect(marks.length).toBe(10);
    expect(page.document.querySelector("#collab-vs .cvs-line").textContent).toContain("直近10戦");
  });

  it("相手が1人なら開いた状態で出し、その相手の戦だけを表に並べる", async () => {
    page = await openPage(LIVE_COLLAB);
    const rows = [...page.document.querySelectorAll("#collab-vs .cvs-row")];
    expect(rows.length).toBe(3);
    expect(rows[0].children[2].textContent).toBe("40K");
    expect(rows[0].children[4].textContent).toBe("+10K");
    expect(rows[1].children[4].textContent).toBe("-10K");
  });

  it("戦を選ぶとその戦のscore曲線を引き、相手の線は相手本人のscoreで描く", async () => {
    page = await openPage(LIVE_COLLAB);
    const before = page.calls.charts.length;
    page.document.querySelector("#collab-vs .cvs-row").dispatchEvent(
      new page.win.MouseEvent("click", { bubbles: true }),
    );
    await page.settle();
    expect(page.calls.fetches.map((f) => f.url)).toContain("/api/sessions/12/battle-series/903");
    const chart = page.calls.charts[page.calls.charts.length - 1];
    expect(page.calls.charts.length).toBeGreaterThan(before);
    expect(chart.data.datasets[0].data).toEqual([0, 12000, 40000]);
    // 個人マルチ/チーム戦の opp は「最強の敵陣」なので、相手本人が parts に居る限り
    // そちらを描く。labelもその相手の名前を名乗る。
    expect(chart.data.datasets[1].label).toBe("こつぶ組");
    expect(chart.data.datasets[1].data).toEqual([0, 9000, 30000]);
  });

  it("チーム戦では相手個人ではなく敵陣を描く（自陣がチーム合計のため）", async () => {
    const team = {
      ...SERIES,
      type: "team",
      series: SERIES.series.map((s) => ({ ...s, own: s.own * 2 })),
    };
    const routes = { ...ROUTES, "/api/sessions/12/battle-series/903": team };
    page = loadPage({ page: "index", url: "http://localhost:8520/", routes });
    page.fireReady();
    await page.settle();
    page.calls.sockets[0].emit({ type: "monitors", data: [snapshot(LIVE_COLLAB)] });
    await page.settle();
    page.document.querySelector("#collab-vs .cvs-row").dispatchEvent(
      new page.win.MouseEvent("click", { bubbles: true }),
    );
    await page.settle();

    const chart = page.calls.charts[page.calls.charts.length - 1];
    expect(chart.data.datasets[1].label).toBe("敵陣（最上位）");
    expect(chart.data.datasets[1].data).toEqual([0, 9000, 30000]);
  });

  it("一度も対戦していない相手も、serverが解決した名前で出す", async () => {
    // 名前の出所はserverが相手のroom_infoから解決したpeer_info。対戦履歴が無くても
    // 名乗れる(以前はここが数値IDだった)。
    page = await openPage([{
      channel_id: "c1", start: 1786200000, guests_max: 1, peers: ["9999999999999"],
      peer_info: { "9999999999999": { nickname: "はじめまして組", unique_id: "hajime", avatar: "" } },
    }]);
    const panel = page.document.getElementById("collab-vs");
    expect(panel.querySelector(".cvs-name").textContent).toContain("はじめまして組");
    expect(panel.querySelector(".cvs-rec").textContent).toBe("対戦履歴なし");
    expect(panel.querySelector(".cvs-toggle").disabled).toBe(true);
  });

  it("名前を解決できていない相手だけIDのまま出す", async () => {
    page = await openPage([{ channel_id: "c1", start: 1786200000, guests_max: 1, peers: ["9999999999999"] }]);
    const panel = page.document.getElementById("collab-vs");
    expect(panel.querySelector(".cvs-name").textContent).toContain("ID …999999");
  });

  it("名前は対戦履歴の表示名よりserverの解決結果を優先する", async () => {
    // 対戦相手集計の名前はその戦の時点のもので、改名/アイコン変更に追随しない。
    page = await openPage([{
      channel_id: "c1", start: 1786200000, guests_max: 1, peers: [PEER],
      peer_info: { [PEER]: { nickname: "こつぶ組(改名後)", unique_id: "kotsubu2", avatar: "" } },
    }]);
    const panel = page.document.getElementById("collab-vs");
    expect(panel.querySelector(".cvs-name").textContent).toContain("こつぶ組(改名後)");
    expect(panel.querySelector(".cvs-rec").textContent).toBe("3戦 2勝1敗");
  });

  it("戦績が取れていない間は「対戦履歴なし」と言い切らない", async () => {
    // profile を返さない server。ここで「対戦履歴なし」を出すと、80戦した相手が
    // 未対戦に見える(取得失敗を既定値で埋めて誤認させる典型)。
    const routes = { ...ROUTES };
    delete routes["/api/streamers/streamer_c/profile"];
    page = loadPage({ page: "index", url: "http://localhost:8520/", routes });
    page.fireReady();
    await page.settle();
    page.calls.sockets[0].emit({ type: "monitors", data: [snapshot(LIVE_COLLAB)] });
    await page.settle();

    const panel = page.document.getElementById("collab-vs");
    expect(panel.classList.contains("hidden")).toBe(false);
    expect(panel.querySelector(".cvs-rec").textContent).toBe("戦績を取得できません");
    expect(panel.querySelector(".cvs-rate").textContent).toBe("");
  });

  it("コラボが終われば欄ごと下げる", async () => {
    page = await openPage(LIVE_COLLAB);
    expect(page.document.getElementById("collab-vs").classList.contains("hidden")).toBe(false);
    page.calls.sockets[0].emit({ type: "state", monitor: "streamer_c", data: snapshot([]) });
    await page.settle();
    expect(page.document.getElementById("collab-vs").classList.contains("hidden")).toBe(true);
  });

  it("相手が入れ替わったら出し直す", async () => {
    page = await openPage(LIVE_COLLAB);
    page.calls.sockets[0].emit({
      type: "state",
      monitor: "streamer_c",
      data: snapshot([{ channel_id: "c1", start: 1786200000, guests_max: 1, peers: [OTHER] }]),
    });
    await page.settle();
    const panel = page.document.getElementById("collab-vs");
    expect(panel.querySelector(".cvs-name").textContent).toContain("別の相手");
    expect(panel.querySelector(".cvs-rec").textContent).toBe("1戦 0勝1敗");
  });
});
