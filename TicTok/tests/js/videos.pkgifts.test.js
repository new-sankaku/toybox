import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// シーン検索の「PK・ギフト」panel。ここの事故は画面が黙って嘘をつく形で出る:
// 別のPKのギフトが並ぶ、観ていない戦のスコアが出る、確定scoreが再生位置の値として出る、
// clickが別の時刻へ飛ぶ。どれもそれらしく描かれるので、目で見ても気付けない。
describe("videos.js のPK・ギフトpanel", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "videos", url: "http://localhost:8520/videos" });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const state = () => page.get("state");

  function setCurrentTime(seconds) {
    Object.defineProperty(doc.getElementById("video"), "currentTime", {
      configurable: true,
      writable: true,
      value: seconds,
    });
  }

  /** serverの応答そのままの形(/api/recordings/{id}/gifts)を入れて描かせる。 */
  function render({ gifts = [], battles = [], icons = {}, now = 0 } = {}) {
    state().gifts = gifts;
    state().battles = battles;
    state().giftIcons = icons;
    setCurrentTime(now);
    win.renderPkPanel(true);
  }

  const PARTS = (own, opp) => [
    { user_id: "me", score: own, side: "own", team_id: null },
    { user_id: "rival", score: opp, side: "opp", team_id: null },
  ];

  const BATTLE = {
    battle_id: 7, ordinal: 2, type: "personal", start: 100, end: 200,
    partial: false, aborted: false, ongoing: false, result: "win",
    own_score: 400, opp_score: 300, opponents: ["相手"],
    participants: [
      { user_id: "me", nickname: "自分", is_own: true, side: "own", team_id: null, score: 400 },
      { user_id: "rival", nickname: "相手", is_own: false, side: "opp", team_id: null, score: 300 },
    ],
    series: [
      { t: 100, own: 0, opp: 0, parts: PARTS(0, 0) },
      { t: 150, own: 400, opp: 100, parts: PARTS(400, 100) },
      { t: 200, own: 400, opp: 300, parts: PARTS(400, 300) },
    ],
  };

  const LATER = {
    ...BATTLE, battle_id: 8, ordinal: 3, start: 300, end: 400,
    result: "lose", own_score: 10, opp_score: 90,
    series: [{ t: 300, own: 0, opp: 0, parts: PARTS(0, 0) },
             { t: 400, own: 10, opp: 90, parts: PARTS(10, 90) }],
  };

  const gift = (t, name, battle, diamonds = 5) => ({
    t, gift_id: 1, name, count: 1, diamonds, nickname: name, uid: name, battle,
  });

  const nowText = () => doc.getElementById("pk-now").textContent;
  const giftRows = () => Array.from(doc.getElementById("pk-gift-list").children);
  const giftTexts = () => giftRows().map((row) => row.textContent);
  const segments = () => Array.from(doc.querySelectorAll("#pk-now .seg"));

  describe("出す戦の選び方", () => {
    it("再生位置が入っている1戦だけを出す(複数のPKを同時に並べない)", () => {
      render({ battles: [BATTLE, LATER], now: 150 });
      expect(nowText()).toContain("PK 2戦目");
      expect(nowText()).not.toContain("PK 3戦目");
      render({ battles: [BATTLE, LATER], now: 350 });
      expect(nowText()).toContain("PK 3戦目");
      expect(nowText()).not.toContain("PK 2戦目");
    });

    it("PKの窓の外ではPKもギフトも出さず、次のPKへ飛ぶ口だけを置く", () => {
      render({
        battles: [BATTLE, LATER],
        gifts: [gift(50, "外", null), gift(120, "中", 2)],
        now: 50,
      });
      expect(nowText()).toContain("PK中ではありません");
      expect(nowText()).toContain("PK 2戦目");
      expect(giftTexts().join(" ")).not.toContain("外");
      expect(giftTexts().join(" ")).not.toContain("中");
    });

    it("後ろにPKが無ければ直前のPKを指す(終わった戦へ戻る口が無いと探し直しになる)", () => {
      render({ battles: [BATTLE], now: 500 });
      expect(nowText()).toContain("直前のPK 2戦目");
    });

    it("PKが1戦も無い録画ではその旨を名乗る", () => {
      render({ gifts: [gift(10, "バラ", null)] });
      expect(nowText()).toContain("この録画にPKはありません");
    });

    it("不成立のPKは勝敗の枠で「—」を出さず、不成立と名乗る", () => {
      render({ battles: [{ ...BATTLE, aborted: true, result: null }], now: 150 });
      expect(nowText()).toContain("不成立");
      expect(doc.querySelector("#pk-now .res")).toBe(null);
    });

    it("この録画に一部だけ入っているPKはその旨を名乗る", () => {
      render({ battles: [{ ...BATTLE, partial: true }], now: 150 });
      expect(doc.querySelector(".vd-pk-partial")).not.toBe(null);
    });
  });

  describe("PK後の勝利(罰ゲーム)時間", () => {
    // serverが決めた窓(punish_end)まで同じ戦を出し続ける。TikTokはPKが終わると勝敗の
    // 演出に入り、その間もギフトは飛ぶので、終了と同時に空にすると誰が投げたのか読めない。
    const PUNISHED = { ...BATTLE, punish_end: 380, punish_measured: true, settled_at: 200 };

    it("PKが終わってもその戦を出し続ける(勝利時間の終わりまで)", () => {
      render({ battles: [PUNISHED], now: 300 });
      expect(nowText()).toContain("PK 2戦目");
      expect(nowText()).not.toContain("PK中ではありません");
      expect(nowText()).toContain("勝利時間");
    });

    it("勝利時間が終われば普段どおりPK外になる", () => {
      render({ battles: [PUNISHED], now: 390 });
      expect(nowText()).toContain("PK中ではありません");
    });

    it("窓を実測できていない戦は目安だと名乗る", () => {
      render({ battles: [{ ...PUNISHED, punish_measured: false }], now: 300 });
      expect(nowText()).toContain("勝利時間（目安）");
    });

    it("勝利時間のバーは確定scoreで止める(PK後のroster解体で0対0へ潰さない)", () => {
      const teardown = {
        ...PUNISHED,
        series: [...BATTLE.series, { t: 260, own: 0, opp: 0, parts: PARTS(0, 0) }],
      };
      render({ battles: [teardown], now: 300 });
      expect(segments().map((s) => s.textContent)).toEqual(["400", "300"]);
    });

    it("勝利時間に飛んだギフトも同じ欄へ流す(別枠で数え、行の地も分ける)", () => {
      render({
        battles: [PUNISHED],
        gifts: [gift(120, "PK中", 2, 90), { ...gift(250, "演出中", null, 500), punish: 2 }],
        now: 300,
      });
      expect(giftTexts()).toHaveLength(2);
      expect(giftTexts()[1]).toContain("演出中");
      expect(giftRows()[1].classList.contains("vd-gift-punish")).toBe(true);
      expect(giftRows()[0].classList.contains("vd-gift-punish")).toBe(false);
      const head = doc.getElementById("pk-gift-head").textContent;
      // PKの貢献(90コイン)と勝利時間(500コイン)を混ぜない。
      expect(head).toContain("1 / 1件");
      expect(head).toContain("90 / 90 コイン");
      expect(head).toContain("勝利時間 1 / 1件 500 / 500 コイン");
    });

    it("勝利時間のギフトが無ければ、その枠は出さない(0件と出すと取りこぼしと紛れる)", () => {
      render({ battles: [PUNISHED], gifts: [gift(120, "PK中", 2)], now: 300 });
      expect(doc.querySelector(".vd-pk-punish-sum").hidden).toBe(true);
    });

    it("PK中は勝利時間の名乗りを出さない", () => {
      render({ battles: [PUNISHED], now: 150 });
      expect(doc.querySelector(".vd-pk-phase").hidden).toBe(true);
    });
  });

  describe("スコアバー", () => {
    it("再生位置での値で分割する(確定scoreではない)", () => {
      render({ battles: [BATTLE], now: 150 });
      expect(segments().map((s) => s.textContent)).toEqual(["400", "100"]);
      expect(nowText()).toContain("+300 リード");
      render({ battles: [BATTLE], now: 200 });
      expect(segments().map((s) => s.textContent)).toEqual(["400", "300"]);
    });

    it("陣営ぶんに分ける(個人マルチは3本目まで出す)", () => {
      const multi = {
        ...BATTLE,
        participants: [
          ...BATTLE.participants,
          { user_id: "third", nickname: "3人目", is_own: false, side: "opp", team_id: null, score: 50 },
        ],
        series: [{ t: 100, own: 400, opp: 100, parts: [
          { user_id: "me", score: 400, side: "own", team_id: null },
          { user_id: "rival", score: 100, side: "opp", team_id: null },
          { user_id: "third", score: 50, side: "opp", team_id: null },
        ] }],
      };
      render({ battles: [multi], now: 150 });
      // 自陣が先頭、相手はscore降順(動画焼き込みのlane順と同じ)。
      expect(segments().map((s) => s.textContent)).toEqual(["400", "100", "50"]);
      expect(segments()[0].className).toContain("c-own");
      expect(segments()[1].className).toContain("c1");
      expect(segments()[2].className).toContain("c2");
      expect(segments()[2].title).toContain("3人目");
    });

    it("チーム戦はチーム合計で分ける", () => {
      const team = {
        ...BATTLE, type: "team",
        participants: [
          { user_id: "me", nickname: "自分", is_own: true, side: "own", team_id: 1, score: 300 },
          { user_id: "mate", nickname: "味方", is_own: false, side: "own", team_id: 1, score: 100 },
          { user_id: "a", nickname: "敵1", is_own: false, side: "opp", team_id: 2, score: 60 },
          { user_id: "b", nickname: "敵2", is_own: false, side: "opp", team_id: 2, score: 40 },
        ],
        series: [{ t: 100, own: 400, opp: 100, parts: [
          { user_id: "me", score: 300, side: "own", team_id: 1 },
          { user_id: "mate", score: 100, side: "own", team_id: 1 },
          { user_id: "a", score: 60, side: "opp", team_id: 2 },
          { user_id: "b", score: 40, side: "opp", team_id: 2 },
        ] }],
      };
      render({ battles: [team], now: 150 });
      expect(segments().map((s) => s.textContent)).toEqual(["400", "100"]);
      expect(nowText()).toContain("チーム戦 2v2");
    });

    it("陣営別scoreを持たない古い記録は2分割へ落とす(確定scoreで埋めない)", () => {
      const legacy = {
        ...BATTLE, participants: [],
        series: [{ t: 100, own: 7, opp: 3 }, { t: 200, own: 400, opp: 300 }],
      };
      render({ battles: [legacy], now: 150 });
      // 150秒の時点はまだ7対3。確定score(400対300)で埋めると、終わった後の値を
      // 再生位置の値として見せることになる。
      expect(segments().map((s) => s.textContent)).toEqual(["7", "3"]);
    });

    it("推移の記録がこの録画に無い戦は最終スコアだと名乗る", () => {
      render({ battles: [{ ...BATTLE, series: [] }], now: 150 });
      expect(segments().map((s) => s.textContent)).toEqual(["400", "300"]);
      expect(nowText()).toContain("最終スコア");
    });
  });

  describe("ギフトの絞り方", () => {
    it("今の戦の窓に入ったギフトだけを出す(他の戦・PK外は出さない)", () => {
      render({
        battles: [BATTLE, LATER],
        gifts: [gift(50, "外", null), gift(120, "中", 2), gift(350, "後", 3)],
        now: 150,
      });
      expect(giftTexts()).toHaveLength(1);
      expect(giftTexts()[0]).toContain("中");
    });

    it("「ここまで / この戦の合計」で数える", () => {
      render({
        battles: [BATTLE],
        gifts: [gift(120, "a", 2, 90), gift(190, "b", 2, 10)],
        now: 150,
      });
      const head = () => doc.getElementById("pk-gift-head").textContent;
      expect(head()).toContain("1 / 2件");
      expect(head()).toContain("90 / 100 コイン");
      setCurrentTime(195);
      win.syncPkPanel();
      expect(head()).toContain("2 / 2件");
      expect(head()).toContain("100 / 100 コイン");
    });

    it("その戦にギフトが1件も無ければ、欄は残したままその旨を出す", () => {
      render({ battles: [BATTLE], gifts: [gift(50, "外", null)], now: 150 });
      expect(giftRows()).toHaveLength(1);
      expect(giftTexts()[0]).toContain("ギフトはありません");
    });

    it("icon URLの無いgiftも行としては残す(画像が無いことは飛ばなかったではない)", () => {
      render({ battles: [BATTLE], gifts: [gift(120, "無名", 2)], now: 150 });
      expect(giftRows()[0].querySelector("img")).toBe(null);
      expect(giftTexts()[0]).toContain("無名");
    });
  });

  describe("流れ方(飛んだ順に下へ積む)", () => {
    const feed = () => ({
      battles: [BATTLE],
      gifts: [gift(110, "先", 2), gift(150, "中", 2), gift(190, "後", 2)],
    });

    it("再生位置まで届いた分だけを出し、進むほど下に増える", () => {
      render({ ...feed(), now: 105 });
      // まだ1件も飛んでいない時間。行は無く、その旨だけを出す。
      expect(giftTexts()[0]).toContain("まだ飛んでいません");
      setCurrentTime(120);
      win.syncPkPanel();
      expect(giftTexts()).toHaveLength(1);
      expect(giftTexts()[0]).toContain("先");
      setCurrentTime(160);
      win.syncPkPanel();
      expect(giftTexts().map((t) => t.includes("中"))).toEqual([false, true]);
      setCurrentTime(195);
      win.syncPkPanel();
      expect(giftTexts()).toHaveLength(3);
      // 一番下が今の行。
      expect(giftRows()[2].classList.contains("vd-gift-active")).toBe(true);
    });

    it("巻き戻すと、まだ飛んでいない行は残さない", () => {
      render({ ...feed(), now: 195 });
      expect(giftRows()).toHaveLength(3);
      setCurrentTime(120);
      win.syncPkPanel();
      expect(giftTexts()).toHaveLength(1);
      expect(giftTexts()[0]).toContain("先");
      setCurrentTime(100);
      win.syncPkPanel();
      expect(giftTexts()[0]).toContain("まだ飛んでいません");
    });

    it("追従ONの間は下端へ貼り付く(積み上がる一覧では今の行は常に一番下)", () => {
      const list = doc.getElementById("pk-gift-list");
      // jsdomはlayoutを持たないので、scrollHeightはtestが与える。
      Object.defineProperty(list, "scrollHeight", { configurable: true, value: 500 });
      render({ ...feed(), now: 195 });
      expect(list.scrollTop).toBe(500);
      list.scrollTop = 0;
      doc.getElementById("pk-follow").checked = false;
      setCurrentTime(120);
      win.syncPkPanel();
      expect(list.scrollTop).toBe(0);
    });

    it("行そのものは作り直さない(同じ戦の中では同じ行が積まれる)", () => {
      render({ ...feed(), now: 195 });
      const first = giftRows()[0];
      setCurrentTime(100);
      win.syncPkPanel();
      setCurrentTime(195);
      win.syncPkPanel();
      expect(giftRows()[0]).toBe(first);
    });
  });

  describe("clickの行き先", () => {
    const click = (node) =>
      node.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));

    it("giftの行はその瞬間へ飛ぶ", () => {
      render({ battles: [BATTLE], gifts: [gift(120, "中", 2)], now: 150 });
      click(giftRows()[0].querySelector(".vd-gift-who"));
      expect(doc.getElementById("video").currentTime).toBe(120);
    });

    it("PKの見出しはその戦の頭へ飛ぶ", () => {
      render({ battles: [BATTLE], now: 150 });
      click(doc.querySelector(".vd-pk-now-head"));
      expect(doc.getElementById("video").currentTime).toBe(100);
    });

    it("PK外の案内は次のPKの頭へ飛ぶ", () => {
      render({ battles: [BATTLE], now: 50 });
      click(doc.querySelector("#pk-now button"));
      expect(doc.getElementById("video").currentTime).toBe(100);
    });
  });

  describe("再生への追従", () => {
    it("最後に飛んだ行に帯を付ける", () => {
      render({
        battles: [BATTLE],
        gifts: [gift(110, "先", 2), gift(120, "中", 2), gift(190, "後", 2)],
        now: 150,
      });
      expect(giftRows()[1].classList.contains("vd-gift-active")).toBe(true);
      setCurrentTime(195);
      win.syncPkPanel();
      expect(giftRows()[2].classList.contains("vd-gift-active")).toBe(true);
      expect(giftRows()[1].classList.contains("vd-gift-active")).toBe(false);
    });

    it("同じ戦を映している間は行を作り直さない(scroll位置と選択が飛ぶ)", () => {
      render({ battles: [BATTLE], gifts: [gift(120, "中", 2)], now: 130 });
      const row = giftRows()[0];
      setCurrentTime(150);
      win.syncPkPanel();
      expect(giftRows()[0]).toBe(row);
      // 戦から出れば作り直す(PK外はギフトを出さない)。
      setCurrentTime(500);
      win.syncPkPanel();
      expect(giftRows()[0]).not.toBe(row);
    });
  });

  describe("時間軸のギフト表示との関係", () => {
    it("表示checkboxを切ってもpanelは中身を出す(切ってある間だけ空になると0件と区別が付かない)", async () => {
      doc.getElementById("show-gifts").checked = false;
      state().current = { recording_id: 5 };
      setCurrentTime(150);
      win.fetch = () =>
        Promise.resolve(new Response(JSON.stringify({
          recording_id: 5, icons: {},
          items: [{ t: 120, gift_id: 1, name: "バラ", count: 1, diamonds: 1,
                    nickname: "a", uid: "a", battle: 2 }],
          battles: [BATTLE],
        }), { status: 200, headers: { "Content-Type": "application/json" } }));
      await win.loadGifts(5);
      expect(state().gifts).toHaveLength(1);
      expect(nowText()).toContain("PK 2戦目");
      expect(giftTexts()[0]).toContain("バラ");
    });
  });
});
