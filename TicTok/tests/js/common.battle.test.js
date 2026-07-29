import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { loadCommon } from "./helpers/page.js";

// PK(バトル)の陣営構造。TikTokは個人マルチもteam構造で送るため、参加者の並べ方と
// 陣営のまとめ方を間違えると、自陣と敵陣が入れ替わったまま画面に出る。
describe("common.js のbattle構造", () => {
  let win;
  let page;
  beforeAll(() => {
    page = loadCommon();
    win = page.win;
  });
  afterAll(async () => page.close());

  const owner = { nickname: "配信者", unique_id: "streamer1", avatar: "https://cdn/x.jpg" };

  describe("battleParticipants", () => {
    it("participants[] があればそれをそのまま使う", () => {
      const parts = [{ user_id: "a", side: "own", is_own: true }];
      expect(win.battleParticipants({ participants: parts }, owner)).toBe(parts);
    });

    it("participants[] が無い旧recordは own/opp scalar から2人分を組み立てる", () => {
      const parts = win.battleParticipants({ own_score: 1200, opp_score: 800 }, owner);
      expect(parts).toHaveLength(2);
      expect(parts[0]).toMatchObject({ is_own: true, side: "own", score: 1200, nickname: "配信者" });
      expect(parts[1]).toMatchObject({ is_own: false, side: "opp", score: 800 });
    });

    it("旧recordに opponents があれば人数ぶん展開する", () => {
      const parts = win.battleParticipants(
        { own_score: 100, opponents: [{ user_id: "o1", score: 50 }, { user_id: "o2", score: 30 }] },
        owner,
      );
      expect(parts.map((p) => p.side)).toEqual(["own", "opp", "opp"]);
      expect(parts.map((p) => p.score)).toEqual([100, 50, 30]);
    });
  });

  describe("participantUser", () => {
    it("自陣の名前が空ならownerの名前で補う(汎用の「自分」にしない)", () => {
      const u = win.participantUser({ is_own: true }, owner);
      expect(u.nickname).toBe("配信者");
      expect(u.unique_id).toBe("streamer1");
      expect(u.avatar).toBe("https://cdn/x.jpg");
    });

    it("敵陣で名前が無ければ unique_id、それも無ければ (unknown)", () => {
      expect(win.participantUser({ is_own: false, unique_id: "opp1" }, owner).nickname).toBe("opp1");
      expect(win.participantUser({ is_own: false }, owner).nickname).toBe("(unknown)");
    });
  });

  describe("battleTeams", () => {
    const teamParts = [
      { user_id: "a", side: "own", is_own: true, team_id: 1, score: 300, team_score: 500 },
      { user_id: "b", side: "own", is_own: false, team_id: 1, score: 200, team_score: 500 },
      { user_id: "c", side: "opp", is_own: false, team_id: 2, score: 400, team_score: 400 },
      { user_id: "d", side: "opp", is_own: false, team_id: 2, score: 100, team_score: 400 },
    ];

    it("team_id で束ね、自チームを先頭へ並べる", () => {
      const teams = win.battleTeams(teamParts);
      expect(teams).toHaveLength(2);
      expect(teams[0].own).toBe(true);
      expect(teams[0].label).toBe("自チーム");
      expect(teams[1].label).toBe("敵チーム");
      expect(teams[0].members.map((m) => m.user_id)).toEqual(["a", "b"]);
    });

    it("team_score があれば合計はそれを使う(個人scoreの単純和で上書きしない)", () => {
      const teams = win.battleTeams(teamParts);
      expect(teams[0].total).toBe(500);
      expect(teams[1].total).toBe(400);
    });

    it("team_score が無い陣営は所属者のscore合計へ落とす", () => {
      const teams = win.battleTeams([
        { side: "own", is_own: true, team_id: 1, score: 10 },
        { side: "own", is_own: false, team_id: 1, score: 20 },
        { side: "opp", is_own: false, team_id: 2, score: 5 },
      ]);
      expect(teams[0].total).toBe(30);
      expect(teams[1].total).toBe(5);
    });

    it("敵陣が3つ以上なら敵チームへ連番を振る", () => {
      const teams = win.battleTeams([
        { side: "own", is_own: true, team_id: 1, score: 1 },
        { side: "opp", is_own: false, team_id: 2, score: 1 },
        { side: "opp", is_own: false, team_id: 3, score: 1 },
      ]);
      expect(teams.map((t) => t.label)).toEqual(["自チーム", "敵チーム1", "敵チーム2"]);
    });

    it("team_id が無い旧dataは side で束ねる", () => {
      const teams = win.battleTeams([
        { side: "own", is_own: true, score: 10 },
        { side: "opp", is_own: false, score: 20 },
      ]);
      expect(teams.map((t) => t.own)).toEqual([true, false]);
    });
  });

  describe("battleTopology / battleModeLabel", () => {
    it("2人なら1v1", () => {
      const battle = { participants: [{ side: "own", is_own: true }, { side: "opp" }] };
      expect(win.battleTopology(battle, owner).kind).toBe("1v1");
      expect(win.battleModeLabel(battle)).toBe("個人戦 1v1");
    });

    it("3人以上でtype未指定なら個人マルチ", () => {
      const battle = {
        participants: [{ side: "own", is_own: true }, { side: "opp" }, { side: "opp" }],
      };
      const topo = win.battleTopology(battle, owner);
      expect(topo.kind).toBe("multi");
      expect(topo.n).toBe(3);
      expect(win.battleModeLabel(battle)).toBe("個人戦 3コラ");
    });

    it("type=team のときだけチーム戦として人数構成を名乗る", () => {
      const battle = {
        type: "team",
        participants: [
          { side: "own", is_own: true, team_id: 1 },
          { side: "own", team_id: 1 },
          { side: "opp", team_id: 2 },
          { side: "opp", team_id: 2 },
        ],
      };
      expect(win.battleTopology(battle, owner).kind).toBe("team");
      expect(win.battleModeLabel(battle)).toBe("チーム戦 2v2");
    });
  });

  describe("battleBarUnits", () => {
    it("個人戦は自分を先頭、相手はscore降順", () => {
      const topo = win.battleTopology(
        {
          participants: [
            { is_own: false, side: "opp", score: 100 },
            { is_own: true, side: "own", score: 50 },
            { is_own: false, side: "opp", score: 300 },
          ],
        },
        owner,
      );
      const units = win.battleBarUnits(topo);
      expect(units.map((u) => u.score)).toEqual([50, 300, 100]);
      expect(units.map((u) => u.self)).toEqual([true, false, false]);
    });

    it("チーム戦はチーム合計を1segmentずつ、自チーム先頭", () => {
      const topo = win.battleTopology(
        {
          type: "team",
          participants: [
            { side: "opp", is_own: false, team_id: 2, team_score: 900 },
            { side: "own", is_own: true, team_id: 1, team_score: 700 },
          ],
        },
        owner,
      );
      const units = win.battleBarUnits(topo);
      expect(units).toEqual([
        { score: 700, own: true, self: false },
        { score: 900, own: false, self: false },
      ]);
    });
  });

  describe("BS(バトルスコア)と実弾", () => {
    it("BSは実弾を必ず上回るので、下回るBSは欠損として実弾へ補正する", () => {
      expect(win.effectiveBs({ score: 100, diamonds: 500 })).toBe(500);
      expect(win.effectiveBs({ score: 900, diamonds: 500 })).toBe(900);
      expect(win.effectiveBs({ diamonds: 500 })).toBe(500);
    });

    it("補正した値は確定BSではないので(推測)を明示する", () => {
      expect(win.bsEstimated({ score: 100, diamonds: 500 })).toBe(true);
      expect(win.bsEstimated({ score: 900, diamonds: 500 })).toBe(false);
      expect(win.bsCellText({ score: 100, diamonds: 500 })).toBe("500(推測)");
      expect(win.bsCellText({ score: 900, diamonds: 500 })).toBe("900");
    });

    it("どちらも無い(=不明)は0ではなく — を出す", () => {
      expect(win.fmtBs(0)).toBe("—");
      expect(win.fmtBs(null)).toBe("—");
      expect(win.bsCellText({})).toBe("—");
      expect(win.fmtBsCoins({})).toBe("BS — / 実弾 —");
    });

    it("fmtBsCoins はBSと実弾を併記する", () => {
      expect(win.fmtBsCoins({ score: 1200, diamonds: 800 })).toBe("BS 1,200 / 実弾 800");
    });
  });

  describe("groupContribsByHost", () => {
    it("host_id が無い自陣の貢献は自陣hostへ寄せる", () => {
      const battle = {
        participants: [
          { user_id: "own1", side: "own", is_own: true },
          { user_id: "opp1", side: "opp", is_own: false },
        ],
        contributions: [
          { side: "own", diamonds: 10 },
          { host_id: "opp1", side: "opp", diamonds: 20 },
        ],
      };
      const topo = win.battleTopology(battle, owner);
      const byHost = win.groupContribsByHost(battle, topo);
      expect(byHost.get("own1")).toHaveLength(1);
      expect(byHost.get("opp1")).toHaveLength(1);
    });

    it("host_id も自陣hostも無い敵陣の貢献は捨てずに専用keyへ集める", () => {
      const battle = { participants: [], contributions: [{ side: "opp", diamonds: 5 }] };
      const topo = win.battleTopology(battle, owner);
      const byHost = win.groupContribsByHost(battle, topo);
      expect(byHost.get("__opp__")).toHaveLength(1);
    });
  });

  describe("battleResultMeta / battleWhenText", () => {
    it("勝敗を表示用のclassと文言へ", () => {
      expect(win.battleResultMeta("win")).toEqual({ cls: "win", text: "WIN" });
      expect(win.battleResultMeta("lose")).toEqual({ cls: "lose", text: "LOSE" });
      expect(win.battleResultMeta(null)).toEqual({ cls: "draw", text: "—" });
    });

    it("終了時刻が無いbattleは「進行中」", () => {
      const text = win.battleWhenText({ start_time: Date.UTC(2026, 6, 21, 5, 0, 0) / 1000 });
      expect(text).toBe("14:00:00〜進行中");
    });

    it("duration があれば m:ss を添える", () => {
      const start = Date.UTC(2026, 6, 21, 5, 0, 0) / 1000;
      expect(win.battleWhenText({ start_time: start, end_time: start + 305, duration: 305 })).toBe(
        "14:00:00〜14:05:05 (5:05)",
      );
    });
  });

  describe("isMeaningfulMission / bonusTaskLabel", () => {
    it("中身の無いmission(START取りこぼしのplaceholder)は表示対象から外す", () => {
      expect(win.isMeaningfulMission({})).toBe(false);
      expect(win.isMeaningfulMission({ multiplier: 0, progress: 0, contributors: [] })).toBe(false);
    });

    it("倍率・時刻・進捗・貢献者のどれかがあれば表示する", () => {
      expect(win.isMeaningfulMission({ multiplier: 2 })).toBe(true);
      expect(win.isMeaningfulMission({ task_start_ts: 1 })).toBe(true);
      expect(win.isMeaningfulMission({ contributors: [{}] })).toBe(true);
    });

    it("既知のprompt keyだけ条件文言を名乗る", () => {
      const m = {
        prompts: [{ key: "pm_mt_live_match_instructions_2", fields: { multi: 3 } }],
      };
      expect(win.bonusTaskLabel(m)).toBe("ギフト3個");
    });

    it("未知key・key無しは種別を名乗らず空を返す", () => {
      expect(win.bonusTaskLabel({ prompts: [{ key: "pm_mt_unknown", fields: { multi: 3 } }] })).toBe("");
      expect(win.bonusTaskLabel({})).toBe("");
    });
  });
});
