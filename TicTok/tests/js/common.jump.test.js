import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadCommon } from "./helpers/page.js";

// 全画面共通の横断jump (Ctrl+K)。配信者・Session・録画・視聴者を1つの入力で引く。
// apiSend → 候補組み立て → 絞り込み → 描画 まで通しで見る。
const STREAMERS = {
  streamers: [
    { unique_id: "streamer_a", nickname: "配信者A", sessions: 120, diamonds: 340000 },
    { unique_id: "otherone", nickname: "べつのひと", sessions: 3, diamonds: 500 },
  ],
};
const SESSIONS = {
  sessions: [
    { id: 339, unique_id: "streamer_a", owner_nickname: "配信者A", started_at: Date.UTC(2026, 6, 21, 5, 0, 0) / 1000 },
  ],
};
const RECORDINGS = {
  recordings: [
    { filename: "00339_streamer_a_20260721_144949.mp4", unique_id: "streamer_a", session_id: 339, quality: "hd" },
  ],
};
const FANS = {
  fans: [
    { unique_id: "fan_a", nickname: "常連", diamonds: 9000, streamer_count: 2, identity_key: "u:123" },
  ],
};

const OK_ROUTES = {
  "/api/streamers": STREAMERS,
  "/api/sessions?limit=0": SESSIONS,
  "/api/recordings": RECORDINGS,
  "/api/fans": FANS,
};

function ctrlK(win) {
  win.document.dispatchEvent(
    new win.KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }),
  );
}

describe("横断jump (Ctrl+K)", () => {
  let page;
  let win;
  let warn;
  beforeEach(() => {
    page = loadCommon({ routes: OK_ROUTES });
    win = page.win;
    warn = vi.spyOn(win.console, "warn").mockImplementation(() => {});
  });
  afterEach(async () => {
    warn.mockRestore();
    await page.close();
  });

  const rows = () => Array.from(page.document.querySelectorAll(".jump-row"));

  it("Ctrl+K を押すまでAPIを叩かない(使わない利用者にcostを払わせない)", () => {
    expect(page.calls.fetches).toHaveLength(0);
  });

  it("Ctrl+K で候補を取り、4種すべてを読む", async () => {
    ctrlK(win);
    await page.settle();
    const urls = page.calls.fetches.map((f) => f.url).sort();
    expect(urls).toEqual(["/api/fans", "/api/recordings", "/api/sessions?limit=0", "/api/streamers"]);
  });

  it("2度目のCtrl+Kは開閉のtoggleで、候補を取り直さない", async () => {
    ctrlK(win);
    await page.settle();
    const first = page.calls.fetches.length;
    ctrlK(win); // 閉じる
    ctrlK(win); // 開く
    await page.settle();
    expect(page.calls.fetches).toHaveLength(first);
  });

  it("語順に依存せず、空白区切りの語をすべて含むものだけ残す", async () => {
    ctrlK(win);
    await page.settle();
    const input = page.document.querySelector(".jump-overlay input");

    input.value = "streamer_a";
    input.dispatchEvent(new win.Event("input", { bubbles: true }));
    expect(rows().length).toBeGreaterThan(0);
    rows().forEach((r) => expect(r.textContent).toContain("streamer_a"));

    input.value = "20260721 streamer_a";
    input.dispatchEvent(new win.Event("input", { bubbles: true }));
    const titles = rows().map((r) => r.querySelector(".jump-title").textContent);
    expect(titles).toContain("00339_streamer_a_20260721_144949.mp4");
  });

  it("0埋めの有無どちらのSession番号でも当たる", async () => {
    ctrlK(win);
    await page.settle();
    const input = page.document.querySelector(".jump-overlay input");
    for (const q of ["339", "00339"]) {
      input.value = q;
      input.dispatchEvent(new win.Event("input", { bubbles: true }));
      const titles = rows().map((r) => r.querySelector(".jump-title").textContent);
      expect(titles).toContain("#00339 配信者A");
    }
  });

  it("配信者 → 視聴者 → Session → 録画 の順で並べる(件数の多い種別に押し出されない)", async () => {
    ctrlK(win);
    await page.settle();
    const input = page.document.querySelector(".jump-overlay input");
    input.value = "";
    input.dispatchEvent(new win.Event("input", { bubbles: true }));
    const kinds = rows().map((r) => r.querySelector(".jump-kind").className.replace("jump-kind k-", ""));
    expect(kinds).toEqual(["streamer", "streamer", "fan", "session", "recording"]);
  });

  it("一致が無ければ「一致なし」と名乗る", async () => {
    ctrlK(win);
    await page.settle();
    const input = page.document.querySelector(".jump-overlay input");
    input.value = "存在しない語";
    input.dispatchEvent(new win.Event("input", { bubbles: true }));
    expect(rows()).toHaveLength(0);
    expect(page.document.querySelector(".jump-note").textContent).toBe("一致なし");
  });

  it("配信者の飛び先は /streamers?uid=、Sessionと録画は /history?session=", async () => {
    ctrlK(win);
    await page.settle();
    const input = page.document.querySelector(".jump-overlay input");
    input.value = "streamer_a";
    input.dispatchEvent(new win.Event("input", { bubbles: true }));
    const items = win.filterJumpItems("streamer_a");
    expect(items.find((i) => i.kind === "streamer").href).toBe("/streamers?uid=streamer_a");
    expect(items.find((i) => i.kind === "session").href).toBe("/history?session=339");
    expect(items.find((i) => i.kind === "recording").href).toBe("/history?session=339");
  });

  it("視聴者の飛び先は名寄せ済みの identity_key", async () => {
    ctrlK(win);
    await page.settle();
    expect(win.filterJumpItems("常連")[0].href).toBe("/fans?fan=" + encodeURIComponent("u:123"));
  });
});

describe("横断jumpの取得失敗", () => {
  let page;
  let warn;
  afterEach(async () => {
    warn.mockRestore();
    await page.close();
  });

  it("視聴者台帳が無い環境でも他3種のjumpは生きる", async () => {
    // /api/fans を routes から外す = 404 を返す。他3種は生きているはず。
    const { "/api/fans": _omit, ...withoutFans } = OK_ROUTES;
    page = loadCommon({ routes: withoutFans });
    warn = vi.spyOn(page.win.console, "warn").mockImplementation(() => {});
    ctrlK(page.win);
    await page.settle();
    const kinds = Array.from(page.document.querySelectorAll(".jump-kind")).map((el) =>
      el.className.replace("jump-kind k-", ""),
    );
    expect(kinds).toContain("streamer");
    expect(kinds).not.toContain("fan");
  });

  it("配信者一覧が落ちたら「0件」ではなく取得失敗を名乗る", async () => {
    page = loadCommon({ routes: { "/api/sessions?limit=0": SESSIONS, "/api/recordings": RECORDINGS } });
    warn = vi.spyOn(page.win.console, "warn").mockImplementation(() => {});
    ctrlK(page.win);
    await page.settle();
    expect(page.document.querySelector(".jump-note").textContent).toBe(
      "候補を取得できませんでした",
    );
  });
});
