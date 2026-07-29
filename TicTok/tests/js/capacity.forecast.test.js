import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 容量の予測表示。ここは「数字を出せないとき」の扱いがすべてで、出せない理由を伏せて
// 数字や0を描くと、**満杯までの猶予を実際より長く読ませる**。行は出ているので誤りに見えない。
describe("capacity.js の予測表示", () => {
  let page;
  let win;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "capacity", url: "http://localhost:8520/capacity" });
    win = page.win;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  describe("fmtDays", () => {
    it("2日以上は整数の日で丸める", () => {
      expect(win.fmtDays(2)).toBe("2 日");
      expect(win.fmtDays(2.4)).toBe("2 日");
      expect(win.fmtDays(2.6)).toBe("3 日");
      expect(win.fmtDays(399)).toBe("399 日");
    });

    it("2日未満は小数1桁(「0 日」に潰さない)", () => {
      expect(win.fmtDays(1.5)).toBe("1.5 日");
      expect(win.fmtDays(0.4)).toBe("0.4 日");
      expect(win.fmtDays(0)).toBe("0.0 日");
    });

    it("400日以上は具体的な日数を装わない", () => {
      expect(win.fmtDays(400)).toBe("1年以上");
      expect(win.fmtDays(5000)).toBe("1年以上");
    });
  });

  describe("forecastCell", () => {
    it("数字を出すのは status=ok のときだけ、しかも幅で出す", () => {
      expect(win.forecastCell({ status: "ok", days_low: 12.3, days_high: 40.6 })).toBe(
        "12 日 〜 41 日",
      );
    });

    it("観測期間より先は「少なくとも」と断って下限だけ出す", () => {
      expect(win.forecastCell({ status: "beyond_horizon", beyond_days: 120 })).toBe(
        "少なくとも 120 日 先",
      );
    });

    it("出せない理由はそれぞれの文言で名乗る(空欄や0にしない)", () => {
      expect(win.forecastCell({ status: "insufficient_data" })).toBe("記録が足りません");
      expect(win.forecastCell({ status: "not_shrinking" })).toBe("減っていません");
      expect(win.forecastCell({ status: "inconclusive" })).toBe("減少と言い切れません");
    });

    it("未知のstatusでも数字を作らない", () => {
      expect(win.forecastCell({ status: "なにか未知" })).toBe("—");
      expect(win.forecastCell({})).toBe("—");
    });
  });

  describe("forecastTitle", () => {
    it("観測日数と件数を添える", () => {
      const title = win.forecastTitle({ status: "ok", observed_days: 12.34, n: 1234 });
      expect(title).toContain("観測 12.3 日");
      expect(title).toContain("記録 1,234 件");
    });

    it("観測日数が無くても件数だけは出す", () => {
      expect(win.forecastTitle({ status: "ok", n: 5 })).toContain("記録 5 件");
    });

    it("あてはまりは読み方まで添える(数字だけでは意味が伝わらない)", () => {
      const title = win.forecastTitle({ status: "ok", r2: 0.9367 });
      expect(title).toContain("0.94");
      expect(title).toContain("1.00に近いほど");
    });

    it("記録が足りないときは必要件数を言う", () => {
      const title = win.forecastTitle({ status: "insufficient_data", n: 1, min_samples: 3 });
      expect(title).toContain("予測には記録が 3 件必要です");
    });

    it("何も分からなければ空(嘘の根拠を作らない)", () => {
      expect(win.forecastTitle({ status: "ok" })).toBe("");
    });
  });

  // 容量の合計。bytesを持たない行を黙って0GBとして混ぜると、合計が実態より小さく見え、
  // 「まだ空きがある」と読ませる。
  describe("placeTotalText", () => {
    it("本数と容量を併記する", () => {
      expect(win.placeTotalText({ items: 1234, bytes: 1024 ** 3 * 25 })).toBe(
        "1,234 本 / 25.0GB",
      );
    });

    it("容量不明の行があればその本数を明示する", () => {
      const text = win.placeTotalText({ items: 10, bytes: 1024 ** 3, unknown_bytes: 3 });
      expect(text).toBe("10 本 / 1.0GB / 容量不明 3 本");
    });

    it("容量不明が0本なら余計な但し書きを出さない", () => {
      const text = win.placeTotalText({ items: 10, bytes: 1024 ** 3, unknown_bytes: 0 });
      expect(text).toBe("10 本 / 1.0GB");
    });

    it("集計自体が無ければ - (0本と描かない)", () => {
      expect(win.placeTotalText(null)).toBe("-");
      expect(win.placeTotalText(undefined)).toBe("-");
    });
  });
});
