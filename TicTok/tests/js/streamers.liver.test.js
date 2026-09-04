import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// ライバー(自分でも配信している人)の割合。コイン基準と人数基準は別物なので、どちらの
// 分母かが読めない1項目に畳むと数字の意味が決まらない。0% と「まだ判っていない」を
// 同じ見た目にすると、判定が進んでいないだけの配信者を「ライバーからの支援が無い」と
// 読み違える。serverが旧processでfieldを返さない状態でも落ちないことも縛る
// (staticは再起動なしで新しくなるので、この食い違いは実際に起きる)。
describe("streamers.js のライバー指標", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "streamers", url: "http://localhost:8520/streamers" });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  function renderList(streamers) {
    page.set("streamers", streamers);
    win.renderList();
    return Array.from(doc.querySelectorAll("#sm-list .sm-item-meta"));
  }

  describe("表示の形", () => {
    it("値が有るときは%で出す", () => {
      expect(win.fmtPercent(62.34)).toBe("62.3%");
      expect(win.fmtPercent(0)).toBe("0.0%");
    });

    it("判定がまだ無い/fieldが無いときは0%ではなく—にする", () => {
      expect(win.fmtPercent(null)).toBe("—");
      expect(win.fmtPercent(undefined)).toBe("—");
    });
  });

  describe("配信者一覧", () => {
    const ALPHA = {
      unique_id: "alpha", nickname: "アルファ", diamonds: 1000, sessions: 3,
      liver_coin_share: 30, liver_gifter_share: 12.5, liver_diamonds: 300,
      liver_gift_diamonds: 1000, liver_gifters: 1, liver_total_gifters: 8,
      liver_coin_coverage: 50, liver_gifter_coverage: 25,
    };

    it("コイン基準と人数基準を別々に出す", () => {
      const meta = renderList([ALPHA])[0];
      expect(meta.textContent).toContain("30.0%");
      expect(meta.textContent).toContain("ライバー/コイン");
      expect(meta.textContent).toContain("12.5%");
      expect(meta.textContent).toContain("ライバー/人数");
    });

    it("一覧の行に隠れた説明のtooltipは付けない", () => {
      const meta = renderList([ALPHA])[0];
      expect(meta.title).toBe("");
    });

    it("serverが古くてfieldが無くても一覧は落ちない", () => {
      const meta = renderList([
        { unique_id: "alpha", nickname: "アルファ", diamonds: 1000, sessions: 3 },
      ])[0];
      expect(meta.textContent).toContain("—");
      expect(errorSpy).not.toHaveBeenCalled();
    });
  });

  describe("Gifter / 収益分析", () => {
    const BASE = {
      total_gifters: 40, repeat_gifters: 10, once_gifters: 30,
      top1: 20, top5: 50, top10: 70,
    };

    function chips(concentration) {
      win.renderConcentration(concentration);
      return Array.from(doc.querySelectorAll("#sm-conc .a-chip")).map((el) => ({
        text: el.textContent,
        title: el.title,
      }));
    }

    it("コイン基準・人数基準・判定済みを独立した項目として並べる", () => {
      const rendered = chips({
        ...BASE, liver_coin_share: 30, liver_gifter_share: 12.5,
        liver_diamonds: 300, liver_gift_diamonds: 1000,
        liver_gifters: 1, liver_total_gifters: 8,
        liver_coin_coverage: 50, liver_gifter_coverage: 25,
      });
      const labels = rendered.map((c) => c.text);
      expect(labels.some((t) => t.includes("ライバー / コイン全体") && t.includes("30.0%"))).toBe(true);
      expect(labels.some((t) => t.includes("ライバー / ギフト人数") && t.includes("12.5%"))).toBe(true);
      expect(labels.some((t) => t.includes("リーグ判定済み(コイン)") && t.includes("50.0%"))).toBe(true);
      expect(labels.some((t) => t.includes("リーグ判定済み(人数)") && t.includes("25.0%"))).toBe(true);
    });

    it("比率の項目は分母をtooltipで示す", () => {
      const rendered = chips({
        ...BASE, liver_coin_share: 30, liver_gifter_share: 12.5,
        liver_diamonds: 300, liver_gift_diamonds: 1000,
        liver_gifters: 1, liver_total_gifters: 8,
        liver_coin_coverage: 50, liver_gifter_coverage: 25,
      });
      const coin = rendered.find((c) => c.text.includes("コイン全体"));
      expect(coin.title).toContain("300 / 1,000 コイン");
    });

    it("判定がまだ無いときは比率を—にする(0%と混同させない)", () => {
      const rendered = chips({
        ...BASE, liver_coin_share: null, liver_gifter_share: null,
        liver_coin_coverage: 0, liver_gifter_coverage: 0,
      });
      const coin = rendered.find((c) => c.text.includes("コイン全体"));
      const head = rendered.find((c) => c.text.includes("ギフト人数"));
      expect(coin.text).toContain("—");
      expect(head.text).toContain("—");
    });
  });

  describe("ライバーからのギフト", () => {
    const LIVERS = [
      { identity_key: "1", unique_id: "big", nickname: "ビッグ", league: "A1",
        diamonds: 5000, gifts: 10, sessions: 4 },
      { identity_key: "2", unique_id: "mid", nickname: "ミッド", league: "A2",
        diamonds: 2000, gifts: 5, sessions: 2 },
      { identity_key: "3", unique_id: "small", nickname: "スモール", league: "B3",
        diamonds: 100, gifts: 1, sessions: 1 },
    ];

    it("誰が投げたかを一覧で出す(名前からFan台帳へ飛べる)", () => {
      win.renderLivers(LIVERS);
      const rows = Array.from(doc.querySelectorAll("#sm-livers tr"));
      expect(rows).toHaveLength(3);
      expect(rows[0].textContent).toContain("ビッグ");
      expect(rows[0].textContent).toContain("A1");
      expect(rows[0].querySelector("a").getAttribute("href")).toBe("/fans?fan=1");
    });

    it("どんなライバーかをリーグ帯のグループで畳んで出す", () => {
      win.renderLivers(LIVERS);
      const chips = Array.from(doc.querySelectorAll("#sm-liver-tiers .a-chip"));
      // A帯(A1+A2)が7000コインでB帯(100)より上、という並び。
      expect(chips[0].textContent).toContain("A 帯");
      expect(chips[0].textContent).toContain("2 人");
      expect(chips[0].textContent).toContain("7,000");
      expect(chips[0].title).toContain("A1, A2");
      expect(chips[1].textContent).toContain("B 帯");
    });

    it("1人も居なければ表は空で、案内だけ出す", () => {
      win.renderLivers([]);
      expect(doc.querySelectorAll("#sm-livers tr")).toHaveLength(0);
      expect(doc.getElementById("sm-livers-empty").classList.contains("hidden")).toBe(false);
    });
  });
});
