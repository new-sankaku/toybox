import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 配信者を選んだ先頭に出る「週のGifter(土曜7時〜次の土曜7時)」。ショート動画の説明文へ
// 貼る@IDを作る口なので、縛るのは「貼る文字列が画面の見え方と必ず一致すること」に寄せる。
// (1) 週は土曜の朝7時始まり。下のランキングの「週」(月曜0時始まり)とは別の窓を引き、
//     名乗りには時刻を入れる(日付だけだと土曜の朝がどちらの週とも読める)。
// (2) コイン額の区分(10K以上/5K以上/1K以上/100コイン以上)は別々の枠で、copyも枠ごと。
//     区分は排他なので、同じ人が2つの枠に出ることはない。copyは区分の名前とuser nameの
//     2つで、user nameは1人1行。週の選択の隣には、範囲→区分→名前を1本にした
//     まとめcopyがあり、載るのは応答のpost_min以上の区分だけ。
// (3) 行を押すとその人がその週に投げたgiftを出す(合計コインからは何が飛んだか読めない)。
// (4) @IDの取れていない人は落とさず薄く残し、印を付けられない理由を名乗る。
// (5) 週を移ると印の指定も開いた行も持ち越さない(顔ぶれが変わるため)。
// (6) 取得できなかったときに「0件」として描かない(一覧もgift一覧も)。
describe("streamers.js の週のメンション", () => {
  let page;
  let win;
  let doc;

  const URL_LATEST = "/api/streamers/streamer/mentions";
  const URL_PREV = "/api/streamers/streamer/mentions?week=2026-08-22";
  // 一度描いた後の引き直しは、見ている週を明示して引く(最新へ勝手に戻さない)。
  const URL_CURRENT = "/api/streamers/streamer/mentions?week=2026-08-29";

  const TIERS = [
    { min: 10000, max: null, label: "10K以上" },
    { min: 5000, max: 10000, label: "5K以上" },
    { min: 1000, max: 5000, label: "1K以上" },
    { min: 100, max: 1000, label: "100コイン以上" },
  ];

  function gifter(n, diamonds, tier, over = {}) {
    return {
      identity_key: `k${n}`, user_id: String(n), unique_id: `fan${n}`,
      nickname: `FAN${n}`, avatar: "", fans_level: 0, gifter_level: 0,
      gifter_badge: "", member_badge: "", league: "",
      diamonds, gifts: 3, sessions: 1, rank: n, tier,
      ...over,
    };
  }

  // 10K以上に2人、他の区分に1人ずつ。区分をまたいで同じ人が出ないことも見る。
  const GIFTERS = [
    gifter(1, 20000, 0),
    gifter(2, 12000, 0),
    gifter(3, 6000, 1),
    gifter(4, 2000, 2),
    gifter(5, 300, 3),
  ];
  // 一番下の区分に届かなかった人。一覧には出ないが、人数とコインは応答が名乗る。
  const BELOW = { below_count: 2, below_diamonds: 90 };
  function tiersFor(rows) {
    return TIERS.map((t, i) => {
      const inTier = rows.filter((g) => g.tier === i);
      return {
        ...t,
        count: inTier.length,
        mentionable: inTier.filter((g) => g.unique_id).length,
        diamonds: inTier.reduce((sum, g) => sum + g.diamonds, 0),
      };
    });
  }
  // 日ぶんの貢献。Serverが窓を割り、貼る文面まで組んで返す(画面は組み立てない)。
  // roster は上位から順で、メダルの付く3人はserverが印を持つ。
  function dayRow(n, diamonds, rank, medal, over = {}) {
    return {
      identity_key: `d${n}`, user_id: String(n), unique_id: `fan${n}`,
      nickname: `FAN${n}`, avatar: "", fans_level: 0, gifter_level: 0,
      gifter_badge: "", member_badge: "", league: "",
      diamonds, gifts: 2, sessions: 1, rank, medal,
      // 貼る文面で表示名の代わりに出す省略形。付いていない人は空。
      alias: "",
      ...over,
    };
  }
  const DAY_LIVE = {
    key: "2026-09-01", title: "9月1日(火)",
    start_label: "2026-09-01 07:00", end_label: "2026-09-02 07:00",
    roster: [
      dayRow(1, 5000, 1, "🥇"),
      dayRow(2, 4000, 2, "🥈"),
      dayRow(3, 3000, 3, "🥉"),
      dayRow(4, 900, 4, ""),
    ],
    roster_truncated: 2,
    gifter_count: 6, diamonds: 13100, post_count: 3,
    post_text: ["トップ3貢献", "🥇 FAN1 🥈 FAN2 🥉 FAN3", "1k⬆️3名"].join("\n"),
    // 顔ぶれを番号で並べた文面。上位3人だけの文面とは別のcopyの口になる。
    roster_text: ["1. FAN1　5,000", "2. FAN2　4,000", "3. FAN3　3,000",
                  "4. FAN4　900"].join("\n"),
  };
  const DAY_QUIET = {
    key: "2026-08-31", title: "8月31日(月)",
    start_label: "2026-08-31 07:00", end_label: "2026-09-01 07:00",
    roster: [], roster_truncated: 0,
    gifter_count: 0, diamonds: 0, post_count: 0, post_text: "", roster_text: "",
  };
  const DAYS = [DAY_LIVE, DAY_QUIET];

  function payload(over = {}) {
    const gifters = over.gifters || GIFTERS;
    return {
      week: "2026-08-29", prev_week: "2026-08-22", next_week: "",
      start_label: "2026-08-29 07:00", end_label: "2026-09-05 07:00",
      post_label: "8月29日〜9月5日", post_min: 1000,
      // 省略形の欄の上限。画面はServerの返したこの値を使う(数字を画面へ書かない)。
      alias_max: 40,
      weeks: [
        { key: "2026-08-22", label: "2026-08-22 07:00", diamonds: 4000, gifts: 40 },
        { key: "2026-08-29", label: "2026-08-29 07:00", diamonds: 40350, gifts: 24 },
      ],
      gifters,
      tiers: tiersFor(gifters),
      // gifter_countはその週に投げた全員。一覧に出るのは区分に入った人だけ。
      gifter_count: gifters.length + BELOW.below_count,
      ...BELOW,
      mentionable_count: gifters.filter((g) => g.unique_id).length,
      diamonds: 40350, dropped_weeks: 0,
      days: DAYS,
      // サブアカウントの統合。束ねた側は日の顔ぶれから消えるので、外す相手として
      // 名乗りまで込みで返る。
      merges: [],
      ...over,
    };
  }
  const LATEST = payload();
  const PREV = payload({
    week: "2026-08-22", prev_week: "", next_week: "2026-08-29",
    start_label: "2026-08-22 07:00", end_label: "2026-08-29 07:00",
    post_label: "8月22日〜8月29日",
    gifters: [gifter(9, 12000, 0)],
    days: [{ ...DAY_QUIET, key: "2026-08-24", title: "8月24日(月)" }],
  });

  async function load(routes) {
    page = loadPage({ page: "streamers", url: "http://localhost:8520/streamers", routes });
    win = page.win;
    doc = page.document;
    await page.settle();
    win.eval("selectedUid = 'streamer'");
    await win.loadMentions("streamer");
  }

  const panels = () => Array.from(doc.querySelectorAll(".sm-mn-tier"));
  const panel = (i) => panels()[i];
  const tierNames = () =>
    panels().map((p) => p.querySelector(".sm-mn-tier-name").textContent);
  const textOf = (i, field = "name") =>
    panel(i).querySelector(`textarea[data-field=${field}]`).value;
  const copyBtn = (i, field) =>
    panel(i).querySelector(`.sm-mn-tier-copy[data-field=${field}]`);
  const rowsOf = (i) => Array.from(panel(i).querySelectorAll("tbody tr"));
  const namesOf = (i) => rowsOf(i).map((tr) => tr.querySelector(".u-name").textContent);
  const picksOf = (i) =>
    rowsOf(i).map((tr) => tr.querySelector("input[type=checkbox]"));
  const headBox = (i) => panel(i).querySelector(".sm-mn-tier-head input");
  const note = () => doc.getElementById("sm-mn-note").textContent;
  const giftsRow = (i) => panel(i).querySelector(".sm-mn-gifts");
  const giftLines = (i) =>
    Array.from(panel(i).querySelectorAll(".sm-mn-gift")).map((row) => [
      row.querySelector(".sm-mn-gift-when").textContent,
      row.querySelector(".sm-mn-gift-name").textContent,
      row.querySelector(".sm-mn-gift-coins").textContent,
    ]);
  const carets = (i) =>
    Array.from(panel(i).querySelectorAll(".sm-mn-caret")).map((c) => c.textContent);

  const GIFTS_URL = (key) =>
    `/api/streamers/streamer/mentions/gifts?week=2026-08-29&identity_key=${key}`;
  const GIFTS = {
    week: "2026-08-29", identity_key: "k1", diamonds: 20000, truncated: 0,
    icons: { 100: "/api/gift-icon?gift_id=100" },
    items: [
      { time: 1, label: "09/03 22:10", name: "Rose", gift_id: 100, count: 3,
        diamonds: 15000 },
      { time: 0, label: "08/30 20:00", name: "Lion", gift_id: 200, count: 1,
        diamonds: 5000 },
    ],
  };

  const toastText = () =>
    [...doc.querySelectorAll(".toast")].map((t) => t.textContent).join("\n");

  function click(el) {
    el.dispatchEvent(new win.Event("click", { bubbles: true }));
  }
  function setBox(box, on) {
    box.checked = on;
    box.dispatchEvent(new win.Event("change", { bubbles: true }));
  }

  beforeEach(() => {
    page = null;
  });
  afterEach(async () => {
    if (page) await page.close();
  });

  it("配信者を選ぶと最新の週を引き、時刻まで入れた範囲で名乗る", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 日付だけだと土曜の朝(0〜7時)がどちらの週とも読めるので、時刻まで見出しへ出す。
    // 組み立てはServer側にあり、画面はその文字列をそのまま出すだけ。
    expect(doc.getElementById("sm-mn-range").textContent)
      .toBe("（2026-08-29 07:00 〜 2026-09-05 07:00）");
    expect(doc.getElementById("sm-mn-week").value).toBe("2026-08-29");
    // 選択肢は窓の開始だけ。どの週も同じ形なので終端は区別の助けにならない。
    expect([...doc.getElementById("sm-mn-week").options].map((o) => o.textContent))
      .toEqual(["2026-08-22 07:00　4k", "2026-08-29 07:00　40.4k"]);
    expect(doc.getElementById("sm-mn-next").disabled).toBe(true);
    expect(doc.getElementById("sm-mn-prev").disabled).toBe(false);
    expect(note()).toContain("Gifter 7 人");
    expect(note()).toContain("コイン 40,350");
    // 一覧に出ない人が居ることを名乗る。黙ると週の人数と枠の合計が合わない理由が
    // 画面から読めない。
    expect(note()).toContain("区分外（100未満）2 人・90 コイン");
  });

  it("区分ごとに別の枠へ分け、枠ごとにcopyを持たせる", async () => {
    await load({ [URL_LATEST]: LATEST });
    expect(tierNames()).toEqual([
      "10K以上", "5K以上", "1K以上", "100コイン以上",
    ]);
    // 貼る文字列は枠ごと。1本にまとめない(区分の境目を目で探すことになる)。
    expect(textOf(0)).toBe("FAN1\nFAN2");
    expect(textOf(1)).toBe("FAN3");
    expect(textOf(2)).toBe("FAN4");
    expect(textOf(3)).toBe("FAN5");
    // 貼るのは表示名だけ。@IDの一覧は出さない(一覧の行に出ている物で足りる)。
    expect(panel(0).querySelectorAll("textarea[data-field=id]")).toHaveLength(0);
    expect(panel(0).querySelector(".sm-mn-copy-name").textContent).toBe("user name");
    expect(panels().every((p) => p.querySelector(".sm-mn-tier-copy"))).toBe(true);
    // 区分は排他。同じ人が2つの枠に出ることはない。
    expect(namesOf(0)).toEqual(["FAN1", "FAN2"]);
    expect(namesOf(1)).toEqual(["FAN3"]);
  });

  it("枠の見出しに人数・コインと、区分の上限を出す", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 「5K以上」が5K〜10Kであることを読めるようにする(区分が排他なので必要)。
    // 桁は区分の名前と同じ丸め(大文字K)。見出しは1行に収める決まりで、揃えないと
    // 同じ枠の中に「5K以上」と「5,000〜10,000」が並ぶ。
    expect(panel(1).querySelector(".sm-mn-tier-range").textContent).toBe("5K〜10K");
    expect(panel(0).querySelector(".sm-mn-tier-range").textContent).toBe("10K〜");
    expect(panel(3).querySelector(".sm-mn-tier-range").textContent).toBe("100〜1K");
    expect(panel(0).querySelector(".sm-mn-tier-count").textContent)
      .toBe("2 人・32,000 コイン");
  });

  it("枠の見出しの印はその枠の全員に効き、他の枠には及ばない", async () => {
    await load({ [URL_LATEST]: LATEST });
    setBox(headBox(0), false);
    expect(textOf(0)).toBe("");
    expect(picksOf(0).every((b) => !b.checked)).toBe(true);
    // 他の枠は触らない。
    expect(textOf(1)).toBe("FAN3");
    setBox(headBox(0), true);
    expect(textOf(0)).toBe("FAN1\nFAN2");
  });

  it("行の印を外すとその枠の文字列からその人だけ消える", async () => {
    await load({ [URL_LATEST]: LATEST });
    setBox(picksOf(0)[0], false);
    expect(textOf(0)).toBe("FAN2");
    // 一部だけ載っている枠は、入・切のどちらでもない見た目にする。
    expect(headBox(0).indeterminate).toBe(true);
    expect(headBox(0).checked).toBe(false);
    setBox(picksOf(0)[0], true);
    expect(textOf(0)).toBe("FAN1\nFAN2");
    expect(headBox(0).indeterminate).toBe(false);
    expect(headBox(0).checked).toBe(true);
  });

  it("0人の区分も枠を残し、人数は見出しが出す", async () => {
    const only = [gifter(1, 20000, 0)];
    await load({ [URL_LATEST]: payload({ gifters: only }) });
    // 抜くと「この区分には誰も居なかった」が「この区分は無い」に化ける。
    expect(tierNames()).toHaveLength(4);
    // 0人であることは見出しの人数で読める。枠の中に一文は足さない。
    expect(panel(1).querySelector(".sm-mn-tier-empty")).toBeNull();
    expect(panel(1).querySelector(".sm-mn-tier-count").textContent).toBe("0 人・0 コイン");
    expect(headBox(1).disabled).toBe(true);
    // 貼る欄は出さない。空の欄とcopyを並べても押せるものは無い。
    expect(panel(1).querySelectorAll(".sm-mn-text")).toHaveLength(0);
    expect(panel(1).querySelectorAll(".sm-mn-copy-bar")).toHaveLength(0);
    // 人の居る枠には出る(消えたままにならない)。
    expect(panel(0).querySelectorAll(".sm-mn-copy-bar")).toHaveLength(1);
  });

  it("@IDの取れていない人は落とさず、印を付けられない形で残す", async () => {
    const withUnknown = [gifter(1, 20000, 0), gifter(2, 15000, 0, { unique_id: "" })];
    await load({ [URL_LATEST]: payload({ gifters: withUnknown }) });
    expect(picksOf(0)[1].disabled).toBe(true);
    expect(rowsOf(0)[1].className).toContain("sm-mn-noid");
    expect(namesOf(0)).toContain("FAN2");
    // メンションできない人は名前も出さない(投稿へ誰も呼べない行が混ざる)。
    expect(textOf(0)).toBe("FAN1");
    // 一覧の2人と貼れる1人が食い違う理由を名乗る(黙ると印の付け忘れに読める)。
    expect(note()).toContain("@ID未取得 1 人");
    // 貼れない人は枠の印の「満杯」判定に混ぜない。
    expect(headBox(0).checked).toBe(true);
    expect(headBox(0).indeterminate).toBe(false);
  });

  it("枠のコピーは区分名とuser nameの2つで、押したものを名乗る", async () => {
    await load({ [URL_LATEST]: LATEST });
    click(copyBtn(0, "name"));
    await page.settle();
    expect(page.calls.clipboard).toEqual(["FAN1\nFAN2"]);
    expect(toastText()).toContain("10K以上 のuser name 2 人をコピーしました");
    // 区分の名前そのもの。投稿の見出しへ貼る物なので、人数は付けない。
    click(copyBtn(0, "tier"));
    await page.settle();
    expect(page.calls.clipboard[1]).toBe("10K以上");
    expect(toastText()).toContain("10K以上 をコピーしました");
    // 枠ごとに別の文字列。隣の枠の人が混ざらない。
    click(copyBtn(1, "name"));
    await page.settle();
    expect(page.calls.clipboard[2]).toBe("FAN3");
    // @IDのcopyは無くした(貼るのは表示名だけ)。
    expect(copyBtn(0, "id")).toBeNull();
  });

  it("週の選択の隣のコピーは、範囲と区分ごとの名前を1本にまとめる", async () => {
    await load({ [URL_LATEST]: LATEST });
    const btn = doc.getElementById("sm-mn-copy-all");
    expect(btn.disabled).toBe(false);
    click(btn);
    await page.settle();
    // 投稿の文面そのもの。範囲→区分の名前→その区分の表示名、の順で積む。
    // 100コインの区分(FAN5)はpost_minの下なので入らない。
    expect(page.calls.clipboard[0]).toBe("8月29日〜9月5日\n\n10K以上\nFAN1\nFAN2\n\n5K以上\nFAN3\n\n1K以上\nFAN4");
    expect(toastText()).toContain("8月29日〜9月5日 の 4 人をコピーしました");
  });

  it("まとめコピーは印を外した人を落とし、空になった区分は見出しごと落とす", async () => {
    await load({ [URL_LATEST]: LATEST });
    setBox(picksOf(0)[1], false);
    setBox(headBox(1), false);
    click(doc.getElementById("sm-mn-copy-all"));
    await page.settle();
    // 名前の無い見出しだけが残ると、貼った先で「0人だった」ではなく貼り忘れに読める。
    expect(page.calls.clipboard[0]).toBe("8月29日〜9月5日\n\n10K以上\nFAN1\n\n1K以上\nFAN4");
    expect(toastText()).toContain("の 2 人をコピーしました");
  });

  it("誰も残らないまとめコピーは、空をclipboardへ書かずに理由を出す", async () => {
    await load({ [URL_LATEST]: LATEST });
    [0, 1, 2].forEach((i) => setBox(headBox(i), false));
    click(doc.getElementById("sm-mn-copy-all"));
    await page.settle();
    expect(page.calls.clipboard).toHaveLength(0);
    expect(toastText()).toContain("この週にメンションできる人がいません。");
  });

  it("誰も選んでいない枠のコピーは、空をclipboardへ書かずに理由を出す", async () => {
    await load({ [URL_LATEST]: LATEST });
    setBox(headBox(2), false);
    click(copyBtn(2, "name"));
    await page.settle();
    expect(page.calls.clipboard).toHaveLength(0);
    expect(toastText()).toContain("1K以上にメンションできる人がいません。");
  });

  it("前の週へ移ると窓を引き直し、前の週で外した印は持ち越さない", async () => {
    await load({ [URL_LATEST]: LATEST, [URL_PREV]: PREV });
    setBox(headBox(0), false);
    expect(textOf(0)).toBe("");
    click(doc.getElementById("sm-mn-prev"));
    await page.settle();
    expect(namesOf(0)).toEqual(["FAN9"]);
    // 顔ぶれが変わるので、前の週の指定は効かせない。
    expect(textOf(0)).toBe("FAN9");
    expect(doc.getElementById("sm-mn-prev").disabled).toBe(true);
    expect(doc.getElementById("sm-mn-next").disabled).toBe(false);
  });

  it("収集中の更新で引き直しても、選んだ週と外した印は残る", async () => {
    // liveの更新は同じ配信者のまま loadMentions を呼び直す。ここで週や印が戻ると、
    // 貼る直前に選び直した内容が黙って消える。
    let current = LATEST;
    await load({ [URL_LATEST]: LATEST, [URL_CURRENT]: () => current });
    setBox(picksOf(0)[0], false);
    expect(textOf(0)).toBe("FAN2");
    await win.loadMentions("streamer");
    expect(doc.getElementById("sm-mn-week").value).toBe("2026-08-29");
    expect(textOf(0)).toBe("FAN2");
    // 後から投げた人は既定で載る(「付けた人」を覚えると新しい人が黙って漏れる)。
    // 一覧はコイン順なので、15000の人は2番目へ入る。
    current = payload({
      gifters: [GIFTERS[0], gifter(7, 15000, 0, { rank: 2 }), ...GIFTERS.slice(1)],
    });
    await win.loadMentions("streamer");
    expect(textOf(0)).toBe("FAN7\nFAN2");
  });

  it("行を押すとその人がその週に投げたgiftを日時・コインつきで出す", async () => {
    await load({ [URL_LATEST]: LATEST, [GIFTS_URL("k1")]: GIFTS });
    expect(giftsRow(0)).toBeNull();
    expect(carets(0)[0]).toBe("▸");
    click(rowsOf(0)[0]);
    await page.settle();
    expect(carets(0)[0]).toBe("▾");
    expect(rowsOf(0)[0].className).toContain("sm-mn-row-open");
    // 何が飛んだかを読む口なので、日時・名前(個数)・コインを1件ずつ出す。
    expect(giftLines(0)).toEqual([
      ["09/03 22:10", "Rose×3", "15,000"],
      ["08/30 20:00", "Lion", "5,000"],
    ]);
    // iconを出せるgiftだけ絵を添える(出せないgiftに別の絵を当てない)。
    const icons = panel(0).querySelectorAll(".sm-mn-gift-icon");
    expect(icons).toHaveLength(1);
    expect(icons[0].getAttribute("src")).toBe("/api/gift-icon?gift_id=100");
    // もう一度押すと畳む。
    click(rowsOf(0)[0]);
    expect(giftsRow(0)).toBeNull();
  });

  it("giftは開いた人のぶんだけ引き、二度目は引き直さない", async () => {
    let calls = 0;
    await load({
      [URL_LATEST]: LATEST,
      [GIFTS_URL("k1")]: () => { calls += 1; return GIFTS; },
    });
    // 開くまでは引かない(1週に数百人居るので、一覧へ畳み込むと開かない人まで運ぶ)。
    expect(calls).toBe(0);
    click(rowsOf(0)[0]);
    await page.settle();
    expect(calls).toBe(1);
    click(rowsOf(0)[0]);
    click(rowsOf(0)[0]);
    await page.settle();
    expect(calls).toBe(1);
  });

  it("印のcheckboxと名前のlinkは行の開閉に巻き込まない", async () => {
    await load({ [URL_LATEST]: LATEST, [GIFTS_URL("k1")]: GIFTS });
    setBox(picksOf(0)[0], false);
    await page.settle();
    expect(giftsRow(0)).toBeNull();
    click(rowsOf(0)[0].querySelector("a"));
    await page.settle();
    expect(giftsRow(0)).toBeNull();
  });

  it("giftを取得できなかったときに「投げていない」と描かない", async () => {
    // gift側のrouteだけ張らない=404。
    await load({ [URL_LATEST]: LATEST });
    click(rowsOf(0)[0]);
    await page.settle();
    const cell = giftsRow(0).querySelector("td");
    expect(cell.className).toContain("sm-mn-gifts-failed");
    expect(cell.textContent).toContain("取得できませんでした");
    expect(giftLines(0)).toEqual([]);
  });

  it("取得できなかったときは黙らず、取得失敗だと名乗る", async () => {
    // routeを張らない=404。0件は何も出さないので、失敗を黙ると0件と見分けが付かない。
    await load({});
    const empty = doc.getElementById("sm-mn-empty");
    expect(empty.className).toContain("list-failed");
    expect(empty.textContent).toContain("取得できませんでした");
    expect(panels()).toHaveLength(0);
    expect(doc.getElementById("sm-mn-range").textContent).toBe("");
    // 週が無いのだから、まとめcopyも押せない状態へ戻す。
    expect(doc.getElementById("sm-mn-copy-all").disabled).toBe(true);
  });

  // ---- 日のGifter ----
  // 上の週を1日ずつに割った貢献。縛るのは「貼る文字列が画面の見え方と一致すること」と
  // 「Serverの組んだ文面をそのまま出すこと」の2点。
  const dayCards = () => Array.from(doc.querySelectorAll(".sm-md-day"));
  const dayCard = (i) => dayCards()[i];
  const dayTitles = () =>
    dayCards().map((c) => c.querySelector(".sm-md-title").textContent);
  const dayText = (i) => {
    const box = dayCard(i).querySelector(".sm-md-text");
    return box ? box.textContent : null;
  };
  const dayRanks = (i) =>
    Array.from(dayCard(i).querySelectorAll(".sm-md-rank")).map((r) => r.textContent);
  const dayNames = (i) =>
    Array.from(dayCard(i).querySelectorAll("tbody .u-name")).map((n) => n.textContent);
  const dayCopyLabels = (i) =>
    Array.from(dayCard(i).querySelectorAll(".sm-md-copy")).map((b) => b.textContent);
  const dayCopyBtn = (i, kind) =>
    dayCard(i).querySelector(`.sm-md-copy[data-kind=${kind}]`);

  it("週の下に日ぶんの札を並べ、窓の端は時刻付きで名乗る", async () => {
    await load({ [URL_LATEST]: LATEST });
    expect(dayTitles()).toEqual(["9月1日(火)", "8月31日(月)"]);
    // 日付だけだと未明(0〜7時)がどちらの日とも読める。組み立てはServer側にあり、
    // 画面はその文字列をそのまま出す。
    expect(dayCard(0).querySelector(".sm-md-range").textContent)
      .toBe("2026-09-01 07:00 〜 2026-09-02 07:00");
    // 文面の「1k⬆️3名」がどこから来た数なのか、画面でも同じ数を出す。
    expect(dayCard(0).querySelector(".sm-md-count").textContent)
      .toBe("6 人・13,100 コイン・1K以上 3 人");
    expect(doc.getElementById("sm-md-note").textContent).toBe("2 日・コイン 13,100");
  });

  it("貼る文面はServerの組んだ物をそのまま欄へ出す", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 画面側で組み立てない ―― 組ませると名乗りの形が2つに割れる。
    expect(dayText(0)).toBe("トップ3貢献\n🥇 FAN1 🥈 FAN2 🥉 FAN3\n1k⬆️3名");
    // 行数を決め打たない ―― 名前が折り返した日に最後の行が隠れると、貼る物を確かめられない。
    expect(dayCard(0).querySelector(".sm-md-text").tagName).toBe("DIV");
  });

  it("メダルの付く行は番号ではなくメダルで出し、印を付ける", async () => {
    await load({ [URL_LATEST]: LATEST });
    // メダルと番号を両方出すと、同じことを2回読ませることになる。
    expect(dayRanks(0)).toEqual(["🥇", "🥈", "🥉", "4"]);
    expect(dayNames(0)).toEqual(["FAN1", "FAN2", "FAN3", "FAN4"]);
    const rows = Array.from(dayCard(0).querySelectorAll("tbody tr"));
    expect(rows.slice(0, 3).every((tr) => tr.className.includes("sm-md-medal-row")))
      .toBe(true);
    expect(rows[3].className).not.toContain("sm-md-medal-row");
  });

  it("顔ぶれを切ったときは切った件数を名乗る", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 黙ると一覧の長さがその日の人数だと読める。
    expect(dayCard(0).querySelector(".sm-md-more").textContent).toBe("＋2");
  });

  it("Giftの無かった日も札を残し、貼る欄とcopyは出さない", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 抜くと「誰も投げなかった日」が「配信の無かった日」に化ける。
    // 0人であることは見出しの人数で読めるので、札の中に一文は足さない。
    expect(dayCard(1).querySelector(".sm-md-empty-day")).toBeNull();
    expect(dayCard(1).querySelector(".sm-md-count").textContent).toContain("0 人");
    expect(dayText(1)).toBeNull();
    expect(dayCard(1).querySelector(".sm-md-copy")).toBeNull();
  });

  it("日ぶんのcopyは欄の中身と同じ文字列を写す", async () => {
    await load({ [URL_LATEST]: LATEST });
    click(dayCard(0).querySelector(".sm-md-copy"));
    await page.settle();
    // 押したものと欄に出ている物が違えば、確かめてから貼れない。
    expect(page.calls.clipboard).toEqual([dayText(0)]);
    expect(toastText()).toContain("9月1日(火) の貢献をコピーしました");
  });

  it("顔ぶれはTop◯のcopyで、番号付きの文面を写す", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 題の人数は実際に写る行数から作る ―― 決め打つと、10人に満たない日だけ
    // 題と中身の件数が食い違う。
    expect(dayCopyLabels(0)).toEqual(["コピー", "Top4"]);
    click(dayCopyBtn(0, "roster"));
    await page.settle();
    expect(page.calls.clipboard).toEqual([DAY_LIVE.roster_text]);
    expect(toastText()).toContain("9月1日(火) の顔ぶれをコピーしました");
  });

  it("週を移ると日ぶんの札も入れ替わる", async () => {
    await load({ [URL_LATEST]: LATEST, [URL_PREV]: PREV });
    click(doc.getElementById("sm-mn-prev"));
    await page.settle();
    expect(dayTitles()).toEqual(["8月24日(月)"]);
  });

  it("取得できなかったときは黙らず、取得失敗だと名乗る", async () => {
    // routeを張らない=404。週の一覧と同じ応答から描くので、片方だけ黙らない。
    await load({});
    const empty = doc.getElementById("sm-md-empty");
    expect(empty.className).toContain("list-failed");
    expect(empty.textContent).toContain("取得できませんでした");
    expect(dayCards()).toHaveLength(0);
    expect(doc.getElementById("sm-md-note").textContent).toBe("");
  });

  // ---- 名前の省略形 ----
  // 貼る文面(トップ3貢献・顔ぶれ)だけで表示名の代わりに出す短い名前。人ごとに1つで、
  // 週にも配信者にも紐付かない。文面を組むのはServerなので、画面は保存したら引き直す
  // ―― 画面側で名前だけ差し替えると、名乗りの形が2つに割れる。
  const ALIAS_URL = "PUT /api/user-aliases";
  const aliasRows = () =>
    Array.from(doc.querySelectorAll("#sm-al-rows tr"));
  const aliasNames = () =>
    aliasRows().map((tr) => tr.querySelector(".u-name").textContent);
  const aliasInput = (i) => aliasRows()[i].querySelector(".sm-al-input");
  const aliasMedals = () =>
    aliasRows().map((tr) => tr.querySelectorAll("td")[1].textContent);
  function setInput(input, value) {
    input.value = value;
    input.dispatchEvent(new win.Event("change", { bubbles: true }));
  }

  it("省略形の枠に日ぶんの顔ぶれが並び、トップ3に出た日数と設定済みの数を名乗る", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 並ぶのは日ぶんの顔ぶれに出た人だけ。週の一覧まで広げると、付けたい相手を
    // 数百人から探すことになる。
    expect(aliasNames()).toEqual(["FAN1", "FAN2", "FAN3", "FAN4"]);
    // 付ける相手を選ぶ材料はこの日数しかないので、0日の人も伏せずに出す。
    expect(aliasMedals()).toEqual(["1 日", "1 日", "1 日", ""]);
    expect(doc.getElementById("sm-al-note").textContent).toBe("4 人中 0 人に設定");
    // 上限は応答から採る。画面へ数字を書くと、上限を動かした日に「入力できたのに
    // 保存で弾かれる欄」ができる。
    expect(aliasInput(0).maxLength).toBe(40);
  });

  it("省略形を入れると保存し、文面を引き直す", async () => {
    const withAlias = payload({
      days: [{ ...DAY_LIVE,
               roster: [{ ...DAY_LIVE.roster[0], alias: "視聴者A" },
                        ...DAY_LIVE.roster.slice(1)],
               post_text: ["トップ3貢献", "🥇 視聴者A 🥈 FAN2 🥉 FAN3",
                           "1k⬆️3名"].join("\n") },
              DAY_QUIET],
    });
    await load({ [URL_LATEST]: LATEST, [ALIAS_URL]: { identity_key: "d1", alias: "視聴者A" },
                 [URL_CURRENT]: withAlias });
    setInput(aliasInput(0), "視聴者A");
    await page.settle();

    const put = page.calls.fetches.find((f) => f.method === "PUT");
    expect(JSON.parse(put.body)).toEqual({ identity_key: "d1", alias: "視聴者A" });
    // 文面はServerの組んだ物。引き直した応答がそのまま欄に出る。
    expect(dayText(0)).toContain("🥇 視聴者A 🥈 FAN2 🥉 FAN3");
    // 表の名前は表示名のまま。順位の根拠なので、省略形は隣へ添えるだけである。
    expect(dayNames(0)[0]).toBe("FAN1");
    expect(dayCard(0).querySelector(".sm-md-alias").textContent).toBe("→ 視聴者A");
    expect(doc.getElementById("sm-al-note").textContent).toBe("4 人中 1 人に設定");
    expect(toastText()).toContain("FAN1 を「視聴者A」で貼るようにしました");
  });

  it("欄を空にすると省略形を外す", async () => {
    const withAlias = payload({
      days: [{ ...DAY_LIVE,
               roster: [{ ...DAY_LIVE.roster[0], alias: "視聴者A" },
                        ...DAY_LIVE.roster.slice(1)] },
              DAY_QUIET],
    });
    await load({ [URL_LATEST]: withAlias, [ALIAS_URL]: { identity_key: "d1", alias: "" },
                 [URL_CURRENT]: LATEST });
    expect(aliasInput(0).value).toBe("視聴者A");
    setInput(aliasInput(0), "  ");
    await page.settle();

    const put = page.calls.fetches.find((f) => f.method === "PUT");
    expect(JSON.parse(put.body)).toEqual({ identity_key: "d1", alias: "" });
    expect(toastText()).toContain("FAN1 の省略形を外しました");
    expect(dayCard(0).querySelector(".sm-md-alias")).toBeNull();
  });

  it("値が変わっていなければ保存しない", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 触っただけで書き込むと、同じ値をDBへ書き戻した回数だけ更新時刻が動く。
    setInput(aliasInput(0), "");
    await page.settle();
    expect(page.calls.fetches.some((f) => f.method === "PUT")).toBe(false);
  });

  it("保存できなかったときは欄を元へ戻し、付いたように見せない", async () => {
    // ALIAS_URLを張らない=404。文面は引き直さないので、貼る物は前のままである。
    await load({ [URL_LATEST]: LATEST });
    setInput(aliasInput(0), "視聴者A");
    await page.settle();
    expect(aliasInput(0).value).toBe("");
    expect(toastText()).toContain("FAN1 の省略形の保存");
    expect(dayText(0)).toContain("🥇 FAN1 🥈 FAN2 🥉 FAN3");
  });

  // ---- サブアカウントの統合 ----
  // 同じ人が別アカウントで投げている場合に、日のGifterを1人へ畳む。畳んだ結果を組むのは
  // Serverなので、画面がするのは「誰を誰へ束ねるか」を送って引き直すことだけである。
  // 縛るのは (1) 掴めるのは名前で、受け皿は行と束ねの札の両方 (2) 送る中身が掴んだ人と
  // 落とした先の組であること (3) 外す口が束ねの中にあること (4) 失敗を黙らないこと。

  const MERGE_URL = "/api/user-merges";
  const mergeGroups = () => Array.from(doc.querySelectorAll(".sm-mg-group"));
  const mergeMembers = (i) =>
    Array.from(mergeGroups()[i].querySelectorAll(".sm-mg-member .u-name"))
      .map((el) => el.textContent);
  const aliasHandle = (i) => aliasRows()[i].querySelector(".u");
  const mergeHint = () => doc.getElementById("sm-mg-hint").textContent;
  // dataTransferはjsdomに無い。画面側も掴んだ相手をdataTransferでは運ばない(dragover中は
  // 中身を読めないため)ので、event単体で本番と同じ経路を通る。
  function drag(from, to) {
    from.dispatchEvent(new win.Event("dragstart", { bubbles: true }));
    to.dispatchEvent(new win.Event("dragover", { bubbles: true, cancelable: true }));
    to.dispatchEvent(new win.Event("drop", { bubbles: true, cancelable: true }));
    from.dispatchEvent(new win.Event("dragend", { bubbles: true }));
  }
  // 束ねた後のServerの応答: FAN2 が FAN1 へ畳まれ、日の顔ぶれは1行減る。
  const MERGED = payload({
    days: [{ ...DAY_LIVE,
             roster: [{ ...DAY_LIVE.roster[0], diamonds: 9000, accounts: 2 },
                      ...DAY_LIVE.roster.slice(2)
                        .map((r, i) => ({ ...r, rank: i + 2, medal: ["🥈", "🥉"][i] }))],
             post_text: ["トップ3貢献", "🥇 FAN1 🥈 FAN3 🥉 FAN4"].join("\n") },
            DAY_QUIET],
    merges: [{
      primary: { identity_key: "d1", user_id: "1", unique_id: "fan1",
                 nickname: "FAN1", avatar: "", alias: "" },
      members: [{ identity_key: "d2", user_id: "2", unique_id: "fan2",
                  nickname: "FAN2", avatar: "", alias: "" }],
      updated_at: 1,
    }],
  });

  it("束ねが1件も無いときは、掴んで重ねる手順を出す", async () => {
    await load({ [URL_LATEST]: LATEST });
    // 掴めること自体は見た目に出ない。行き先が無い間だけ手順を出す。
    expect(mergeGroups()).toHaveLength(0);
    expect(mergeHint()).toBe("左の行を主アカウントの行へ重ねる");
    expect(doc.getElementById("sm-mg-note").textContent).toBe("");
  });

  it("名前を別の行へ重ねると、重ねた先を主として束ねる", async () => {
    await load({ [URL_LATEST]: LATEST, [`PUT ${MERGE_URL}`]: {},
                 [URL_CURRENT]: MERGED });
    // FAN2(サブ)を掴んで、FAN1(主)の行へ落とす。
    drag(aliasHandle(1), aliasRows()[0]);
    await page.settle();

    const put = page.calls.fetches.find((f) => f.method === "PUT");
    expect(JSON.parse(put.body)).toEqual({ member_key: "d2", primary_key: "d1" });
    expect(toastText()).toContain("FAN2 を同じ人として統合しました");
    // 畳んだ顔ぶれを組むのはServer。引き直した応答がそのまま出る。
    expect(dayNames(0)).toEqual(["FAN1", "FAN3", "FAN4"]);
    expect(dayCard(0).querySelector(".sm-md-merged").textContent).toBe("統合 2");
    // 束ねた側は左の顔ぶれから消えるので、右の札が外す相手を名乗る。
    expect(mergeGroups()).toHaveLength(1);
    expect(mergeMembers(0)).toEqual(["FAN2"]);
    expect(doc.getElementById("sm-mg-note").textContent).toBe("1 人へ 1 件");
    expect(mergeHint()).toBe("");
  });

  it("束ねの札へ重ねると、その札の主へ入る", async () => {
    await load({ [URL_LATEST]: MERGED, [`PUT ${MERGE_URL}`]: {} });
    // 既に束ねの在るFAN1の札へ、3人目(FAN3)を落とす。
    drag(aliasHandle(1), mergeGroups()[0]);
    await page.settle();

    const put = page.calls.fetches.find((f) => f.method === "PUT");
    // 落とした札の主(FAN1)が primary。札の中のどこへ落ちても同じ主へ入る。
    expect(JSON.parse(put.body)).toEqual({ member_key: "d3", primary_key: "d1" });
  });

  it("自分自身へは束ねない", async () => {
    await load({ [URL_LATEST]: LATEST });
    drag(aliasHandle(0), aliasRows()[0]);
    await page.settle();
    // 受け皿の印も出さない ―― 何も起きない場所が光ると、落とせるように読める。
    expect(aliasRows()[0].className).not.toContain("sm-mg-over");
    expect(page.calls.fetches.some((f) => f.method === "PUT")).toBe(false);
  });

  it("外すと束ねが解け、そのアカウントが顔ぶれへ戻る", async () => {
    await load({ [URL_LATEST]: MERGED, [`DELETE ${MERGE_URL}`]: { member_key: "d2" },
                 [URL_CURRENT]: LATEST });
    click(mergeGroups()[0].querySelector(".sm-mg-off"));
    await page.settle();

    const del = page.calls.fetches.find((f) => f.method === "DELETE");
    expect(JSON.parse(del.body)).toEqual({ member_key: "d2" });
    expect(toastText()).toContain("FAN2 の統合を外しました");
    expect(dayNames(0)).toEqual(["FAN1", "FAN2", "FAN3", "FAN4"]);
    expect(mergeGroups()).toHaveLength(0);
  });

  it("束ねられなかったときは黙らず、畳んだように見せない", async () => {
    // MERGE_URLを張らない=404。顔ぶれは引き直さないので、前のままである。
    await load({ [URL_LATEST]: LATEST });
    drag(aliasHandle(1), aliasRows()[0]);
    await page.settle();
    expect(toastText()).toContain("FAN2 の統合");
    expect(dayNames(0)).toEqual(["FAN1", "FAN2", "FAN3", "FAN4"]);
    expect(mergeGroups()).toHaveLength(0);
  });
});
