import { describe, it, expect, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 出力tabの**素材は週で決まる**。素材を選ぶ棚そのものを外した ―― 期間を指定してあるのに
// その期間の素材を人が選び直す作業が残っていて、しかも並ぶのは
// v1c43ag5000cdab7s77og65i71rvmudg.mp4 のようなfile名だけで、中身を当てられなかった
// (利用者の指定)。素材は**その週のgiftに当たったハイライト**そのものである。
//
// 縛るのは4つ。
//
// (1) 開けば、その週の素材だけが下見へ渡ること。週keyはServerが台帳の行へ付けた物
//     (当たったgiftのeventの時刻から決まる)で、**画面は日付から週を組み立てない**。
// (2) 週を動かせば素材も付け替わること。前の週の素材が残ったまま繋がれると、file名の
//     期間と中身が食い違う。
// (3) giftが1件も当たっていない本を素材にしないこと。「この週の物」と名乗る根拠が無い。
// (4) 開いた時点で出来上がりが出ること。人がここで決めることはもう何も残っていない。
describe("story.js 出力tabの素材を週で選ぶ", () => {
  let page;
  let win;
  let doc;

  const STREAMER = "pomiiiip";
  const URL_LIST = "/api/highlights";
  const URL_MENTIONS = `/api/streamers/${STREAMER}/mentions`;
  const THIS_WEEK = "2026-08-29";
  const PREV_WEEK = "2026-08-22";

  function highlight(over = {}) {
    return {
      id: 1, unique_id: STREAMER, filename: "a.mp4", path: "/hl/a.mp4",
      url: "/api/highlights/1/media", duration_seconds: 60.8, status: "matched",
      segment_count: 10, gift_total_count: 12, gift_diamonds: 20585,
      // 素材の週。**Serverが名乗る。** ``weeks`` は跨いだ週を全部持つ(土曜7時の境目を
      // 跨いだ配信では2つになる)ので、選択の判定はこちらで行う。
      week: THIS_WEEK, week_label: "8/29(土) 7:00 〜 9/5(土) 7:00", weeks: [THIS_WEEK],
      ...over,
    };
  }

  // 今週の2本・前の週の1本・giftが1件も当たっていない1本。
  const HIGHLIGHTS = [
    highlight(),
    highlight({ id: 2, filename: "b.mp4", path: "/hl/b.mp4",
                url: "/api/highlights/2/media" }),
    highlight({ id: 3, filename: "c.mp4", path: "/hl/c.mp4",
                url: "/api/highlights/3/media",
                week: PREV_WEEK, week_label: "8/22(土) 7:00 〜 8/29(土) 7:00",
                weeks: [PREV_WEEK] }),
    highlight({ id: 4, filename: "d.mp4", path: "/hl/d.mp4",
                url: "/api/highlights/4/media", week: "", week_label: "", weeks: [] }),
  ];

  const DEFAULTS = {
    match: { days: null, day_stages: [14, 30], scope: "gift", gift_lead: 6, gift_tail: 2,
             min_diamonds: 98, window: 5, hop: 0.128 },
    export: { order: "diamonds", pad_lead: 0.3, pad_tail: 0.5, min_diamonds: 1000 },
  };

  const MENTIONS = {
    streamer: STREAMER, week: THIS_WEEK, prev_week: PREV_WEEK, next_week: "",
    start_label: "8/29(土) 7:00", end_label: "9/5(土) 7:00", post_min: 1000,
    weeks: [{ key: PREV_WEEK, label: "8/22", diamonds: 30000 },
            { key: THIS_WEEK, label: "8/29", diamonds: 35896 }],
    items: [],
  };

  const PREV_MENTIONS = { ...MENTIONS, week: PREV_WEEK, prev_week: "",
                          next_week: THIS_WEEK,
                          start_label: "8/22(土) 7:00", end_label: "8/29(土) 7:00" };

  const EXPORTS = { streamer: STREAMER, week: THIS_WEEK, exists: true,
                    directory: "D:/rec/pomiiiip/LiveHightlite_マージ済み", items: [] };

  // 下見の応答。**中身は問わない** ―― この面の仕事は「何を素材として渡したか」で、
  // 誰のfileに何が入るかを決めるのはServerである。
  const PLAN = {
    order: "diamonds", week: THIS_WEEK, post_min: 1000, min_diamonds: 1000,
    files: [{
      identity_key: "k1", nickname: "あきと🐢💤", user_nickname: "あきと🐢💤",
      unique_id: "akito", user_unique_id: "akito", coin: 13543, rank: 1,
      position: 1, position_total: 1, filename: "260829-260905_coin13543_あきと_story.mp4",
      count: 1, cut_count: 1, diamonds: 6000, seconds: 6.0, items: [], cuts: [],
    }],
    skipped: [], uncovered: [],
    counts: { total: 1, gifters: 1 }, diamonds: 6000,
  };

  const rows = () => Array.from(
    doc.querySelectorAll("#ex-rows tr.st-group"));

  function routes(over = {}) {
    return {
      "POST /api/highlights/export/plan": PLAN,
      [`GET ${URL_LIST}`]: { items: HIGHLIGHTS, defaults: DEFAULTS,
                             upload_dirs: { [STREAMER]: "D:/rec/pomiiiip/highlights" } },
      [`GET ${URL_MENTIONS}`]: MENTIONS,
      [`GET ${URL_MENTIONS}?week=${PREV_WEEK}`]: PREV_MENTIONS,
      [`GET ${URL_MENTIONS}?week=${THIS_WEEK}`]: MENTIONS,
      [`GET /api/highlights/exports?streamer=${STREAMER}&week=${THIS_WEEK}`]: EXPORTS,
      [`GET /api/highlights/exports?streamer=${STREAMER}&week=${PREV_WEEK}`]:
        { ...EXPORTS, week: PREV_WEEK },
      ...over,
    };
  }

  async function openExport(over = {}) {
    page = loadPage({ page: "story", routes: routes(over) });
    win = page.win;
    doc = page.document;
    await page.settle();
    doc.getElementById("tab-export").click();
    await page.settle();
    return page;
  }

  afterEach(() => { if (page) page.close(); page = null; });

  // 下見へ渡った素材のid。**画面が何を素材にしたか**は、この1点でしか外から見えない。
  const sentIds = () => {
    const call = page.calls.fetches.filter(
      (f) => f.url === "/api/highlights/export/plan").pop();
    return call ? JSON.parse(call.body).highlight_ids : null;
  };

  it("開けば、その週の素材だけが下見へ渡る", async () => {
    await openExport();
    // 今週の2本だけ。前の週の本と、giftの当たっていない本は入らない ――
    // 「この週の物」と名乗る根拠が無い素材を勝手に繋がない。
    expect(sentIds()).toEqual([1, 2]);
    expect(doc.getElementById("ex-plan").disabled).toBe(false);
  });

  it("素材を選ぶ棚は置かない", async () => {
    await openExport();
    // file名だけが並ぶ棚は、押す人が中身を当てられない。週が素材を決める。
    expect(doc.getElementById("ex-list")).toBeNull();
    expect(doc.getElementById("ex-week-pick")).toBeNull();
    expect(doc.getElementById("ex-all")).toBeNull();
    expect(doc.getElementById("ex-none")).toBeNull();
  });

  it("週を動かせば素材も付け替わる", async () => {
    await openExport();
    const select = doc.getElementById("ex-week");
    select.value = PREV_WEEK;
    select.dispatchEvent(new win.Event("change"));
    await page.settle();
    // 前の週の1本だけになる。今週の2本が残ったままなら、file名の期間と中身が食い違う。
    expect(sentIds()).toEqual([3]);
  });

  it("開いた時点で出来上がりが出る(「出来上がりを確認」を押させない)", async () => {
    await openExport();
    // 押していないのに下見が引かれ、表が組まれている。
    expect(rows().length).toBe(1);
    expect(rows()[0].textContent).toContain("あきと🐢💤");
  });

  it("対象の判定文はもう出さない(閾値の説明は帯を1段占めるだけだった)", async () => {
    await openExport();
    expect(doc.getElementById("ex-week-rule")).toBeNull();
    expect(doc.getElementById("view-export").textContent)
      .not.toContain("以上のgifter");
  });
});
