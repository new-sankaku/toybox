import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// Session詳細の「UserごとのGift」。Lvは名前の後ろに寄せず独立した列に置く(名前の長さで
// 横位置が動くと行をまたいで読み比べられない)。Gift名にはiconを添えるが、iconはpoolに
// 在るgiftしか出せないので、出せないgiftは名前だけで並ぶ — 画像が無いことは「そのgiftが
// 飛ばなかった」ではないため、行そのものは必ず残す。
describe("history.js のSession詳細", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  const SUMMARY = {
    gift_icons: { 5655: "/api/gift-icon?gift_id=5655" },
    users: [
      {
        unique_id: "whale", nickname: "クジラ", avatar: "",
        gifts: 3, diamonds: 15,
        gifter_level: 7, gifter_badge: "", fans_level: 2, member_badge: "",
        items: {
          Rose: { count: 3, diamonds: 15, gift_id: 5655 },
          Lion: { count: 1, diamonds: 1, gift_id: 9999 },
        },
      },
      {
        unique_id: "minnow", nickname: "小魚", avatar: "",
        gifts: 1, diamonds: 1,
        gifter_level: 0, gifter_badge: "", fans_level: 0, member_badge: "",
        items: { Lion: { count: 1, diamonds: 1, gift_id: 9999 } },
      },
    ],
    gifts: [
      { name: "Rose", count: 3, diamonds: 15, gift_id: 5655 },
      { name: "Lion", count: 1, diamonds: 1, gift_id: 9999 },
    ],
  };

  const DETAIL = {
    session: {
      id: 1, unique_id: "streamer", owner_nickname: "配信者",
      started_at: 1700000000, ended_at: 1700003600, status: "ended",
      stats: { gifts: 4, diamonds: 16, comments: 10 }, note: "",
    },
    timeline: { buckets: [], markers: [], bucket_seconds: 60 },
    recordings: [],
    battles: [],
    summary: SUMMARY,
    owner: { unique_id: "streamer", nickname: "配信者" },
  };

  beforeEach(async () => {
    page = loadPage({
      page: "history",
      url: "http://localhost:8520/history",
      routes: {
        "/api/sessions/1": DETAIL,
        "/api/sessions/1/collabs": { collabs: [] },
        "/api/sessions/1/comment-analysis": { analysis: null },
      },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
    await win.showDetail(1);
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const userRows = () => Array.from(doc.querySelectorAll("#user-ranking tr"));

  it("GLv/MLvは独立した列で、値の無い行も「-」で列を保つ", () => {
    const headers = Array.from(
      doc.querySelectorAll("#user-ranking")[0].closest("table").tHead.rows[0].cells,
    ).map((th) => th.textContent.trim());
    expect(headers).toEqual(["#", "User", "GLv", "MLv", "Gift数", "コイン", "Gift内訳"]);

    const rows = userRows();
    expect(rows[0].cells[2].textContent.trim()).toBe("7");
    expect(rows[0].cells[3].textContent.trim()).toBe("2");
    // Lvの無いuserにも同じ列を置く(空にすると縦の線が崩れる)。
    expect(rows[1].cells[2].textContent.trim()).toBe("-");
    expect(rows[1].cells[3].textContent.trim()).toBe("-");
  });

  it("Lvは名前のcellへ重ねない(列と二重に出さない)", () => {
    expect(userRows()[0].cells[1].querySelector(".u-badges")).toBeNull();
  });

  it("Gift内訳はiconを出せるgiftにだけ画像を添え、出せないgiftも名前で残す", () => {
    const lines = Array.from(userRows()[0].querySelectorAll(".gi-line"));
    expect(lines.map((l) => l.querySelector(".gi-name").textContent.trim()))
      .toEqual(["Rose", "Lion"]);
    expect(lines[0].querySelector(".gi-icon").getAttribute("src"))
      .toBe("/api/gift-icon?gift_id=5655");
    expect(lines[1].querySelector(".gi-icon")).toBeNull();
  });

  it("Gift種類別のGift名にも同じiconが付く", () => {
    const rows = Array.from(doc.querySelectorAll("#gift-ranking tr"));
    expect(rows[0].cells[1].textContent.trim()).toBe("Rose");
    expect(rows[0].querySelector(".gi-icon").getAttribute("src"))
      .toBe("/api/gift-icon?gift_id=5655");
    expect(rows[1].querySelector(".gi-icon")).toBeNull();
  });

  it("icon URLが1本も無くても表は描ける(iconは後付けの情報)", async () => {
    win.renderTableRows(
      "user-ranking", "user-ranking-empty", SUMMARY.users,
      (user, rank) => [
        String(rank),
        win.userCell(user, { stackId: true, hideBadges: true }),
        win.badgeLevelCell(user.gifter_badge, user.gifter_level, "GLv"),
        win.badgeLevelCell(user.member_badge, user.fans_level, "MLv"),
        win.fmtNum(user.gifts), win.fmtNum(user.diamonds),
        win.giftItemsNode(user.items, {}),
      ],
      [0, 4, 5],
    );
    expect(userRows()).toHaveLength(2);
    expect(doc.querySelectorAll("#user-ranking .gi-icon")).toHaveLength(0);
  });
});
