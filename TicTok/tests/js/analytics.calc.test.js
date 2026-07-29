import { describe, it, expect, beforeAll, afterAll, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 全体解析の表示計算。統計そのものは backend が出すが、単位・丸め・「計測不能」の
// 描き分けは画面側が持つ。ここが崩れると、値が無いだけの欄が 0 に見える。
describe("analytics.js の表示計算", () => {
  let page;
  let win;
  let errorSpy;

  beforeAll(async () => {
    // API を stub していないので loadAll は 404 を踏む。safeRender が個別に囲うため
    // 描画は落ちないが、console.error は出るので黙らせる。
    page = loadPage({ page: "analytics", url: "http://localhost:8520/analytics" });
    win = page.win;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterAll(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  describe("periodDays", () => {
    it("選択中の期間を数値で返す", () => {
      const el = page.document.getElementById("an-period");
      el.value = "30";
      expect(win.periodDays()).toBe(30);
      el.value = "0";
      expect(win.periodDays()).toBe(0);
    });
  });

  describe("時間帯index の色", () => {
    it("平均(×1.0)は中間色、×4以上は暖色、×0.5以下は寒色へ振り切る", () => {
      expect(win.tiColor(1).bg).toBe("rgb(233, 227, 207)");
      expect(win.tiColor(4).bg).toBe("rgb(184, 90, 47)");
      expect(win.tiColor(0.5).bg).toBe("rgb(111, 147, 168)");
    });

    it("振り切った先は clamp する(×8 と ×4 は同じ色)", () => {
      expect(win.tiColor(8).bg).toBe(win.tiColor(4).bg);
      expect(win.tiColor(0.1).bg).toBe(win.tiColor(0.5).bg);
    });

    it("背景の明るさで文字色を切り替える", () => {
      expect(win.tiColor(1).fg).toBe("#2f2b22");
      expect(win.tiColor(4).fg).toBe("#f0ead6");
    });

    it("観測が無いマスは色を塗らず「データなし」と名乗る", () => {
      const html = win.tiCellHTML(null, "月", "12:00");
      expect(html).toContain("an-hm-empty");
      expect(html).toContain("データなし");
      expect(win.tiCellHTML({ index: 1.2, n: 0 }, "月", "12:00")).toContain("an-hm-empty");
      expect(win.tiCellHTML({ index: null, n: 5 }, "月", "12:00")).toContain("an-hm-empty");
    });

    it("観測があるマスは倍率と観測本数をtitleへ入れる", () => {
      const html = win.tiCellHTML({ index: 1.25, n: 12 }, "月", "12:00");
      expect(html).toContain("×1.25");
      expect(html).toContain("観測12本");
      expect(html).not.toContain("an-hm-empty");
    });
  });

  describe("tiSlotLabel", () => {
    it("分を HH:MM へ", () => {
      expect(win.tiSlotLabel(0)).toBe("00:00");
      expect(win.tiSlotLabel(80)).toBe("01:20");
      expect(win.tiSlotLabel(1420)).toBe("23:40");
    });
  });

  describe("値が無いことの描き分け", () => {
    // null は「まだ測れていない」であって 0 ではない。ここを 0 と描くと
    // 「起きなかった」という未確認の主張になる。
    it.each([
      ["dwellSeconds", (v) => win.dwellSeconds(v)],
      ["dwellPct", (v) => win.dwellPct(v)],
      ["anomValue", (v) => win.anomValue("x", v)],
      ["actSeconds", (v) => win.actSeconds(v)],
      ["actPct", (v) => win.actPct(v)],
      ["entryRatio", (v) => win.entryRatio(v)],
      ["bfPct", (v) => win.bfPct(v)],
      ["cvSeconds", (v) => win.cvSeconds(v)],
    ])("%s(null) は - を出す", (_name, fn) => {
      expect(fn(null)).toBe("-");
    });

    it("peakPct は未取得を — で出す", () => {
      expect(win.peakPct({})).toBe("—");
      expect(win.peakPct({ peak: {} })).toBe("—");
    });
  });

  describe("滞在時間・活性の単位", () => {
    it("dwellSeconds は90秒未満を秒、それ以上を分にする", () => {
      expect(win.dwellSeconds(45.4)).toBe("45秒");
      expect(win.dwellSeconds(90)).toBe("1.5分");
      expect(win.dwellSeconds(600)).toBe("10.0分");
    });

    it("actSeconds は秒→分→時間で桁を繰り上げる", () => {
      expect(win.actSeconds(30)).toBe("30秒");
      expect(win.actSeconds(90)).toBe("2分");
      expect(win.actSeconds(3600)).toBe("1.0時間");
      expect(win.actSeconds(7200)).toBe("2.0時間");
    });

    it("cvSeconds は90秒未満を小数1桁の秒で出す", () => {
      expect(win.cvSeconds(45.57)).toBe("45.6秒");
      expect(win.cvSeconds(120)).toBe("2.0分");
    });

    it("計測不能は0や-ではなくその旨を名乗る", () => {
      expect(win.cvUnmeasured("")).toContain("計測不能");
      expect(win.cvUnmeasured("start eventが無い")).toContain("start eventが無い");
    });
  });

  describe("率の書式", () => {
    it("dwellPct は整数%、actPct は既定1桁", () => {
      expect(win.dwellPct(0.256)).toBe("26%");
      expect(win.actPct(0.1234)).toBe("12.3%");
      expect(win.actPct(0.1234, 0)).toBe("12%");
    });

    it("entryRatio / bfPct は1桁%", () => {
      expect(win.entryRatio(0.5)).toBe("50.0%");
      expect(win.bfPct(0.1234)).toBe("12.3%");
    });

    it("peakPct は符号を明示する", () => {
      expect(win.peakPct({ peak: { pct: 12.4 } })).toBe("+12%");
      expect(win.peakPct({ peak: { pct: -7.6 } })).toBe("-8%");
      expect(win.peakPct({ peak: { pct: 0 } })).toBe("+0%");
    });
  });

  describe("anomValue", () => {
    it("指標ごとに単位を変える", () => {
      expect(win.anomValue("follow_per_join", 0.0123)).toBe("1.23%");
      expect(win.anomValue("viewers_med", 12.34)).toBe("12.3人");
    });

    it("それ以外は桁数で丸めを変える(大きい値に小数を出さない)", () => {
      expect(win.anomValue("diamonds", 150.7)).toBe("151");
      expect(win.anomValue("diamonds", 1.234)).toBe("1.23");
    });

    it("方向は多い/少ないを言葉で名乗る", () => {
      expect(win.anomDirection(1.5)).toContain("多い");
      expect(win.anomDirection(-1.5)).toContain("少ない");
      expect(win.anomDirection(0)).toContain("多い");
    });
  });

  describe("bfCi", () => {
    it("観測がある時だけ率と信頼区間を出す", () => {
      expect(win.bfCi({ n: 10, rate: 0.2, ci: [15, 25] })).toBe("20.0%（95%区間 15〜25%）");
    });

    it("区間が無ければ率だけ出す", () => {
      expect(win.bfCi({ n: 10, rate: 0.2 })).toBe("20.0%");
    });

    it("観測0本は率を名乗らない", () => {
      expect(win.bfCi({ n: 0, rate: 0.2 })).toBe("-");
      expect(win.bfCi(null)).toBe("-");
    });
  });

  describe("corrColor", () => {
    it("正の相関と負の相関で色相を変え、強さを不透明度へ写す", () => {
      expect(win.corrColor(0.5)).toBe("rgba(169, 110, 73, 0.4)");
      expect(win.corrColor(-0.5)).toBe("rgba(77, 110, 110, 0.4)");
    });

    it("|相関| が1を超えても不透明度は上限で止める", () => {
      expect(win.corrColor(2)).toBe("rgba(169, 110, 73, 0.8)");
    });

    it("相関が無い(null)マスは塗らない", () => {
      expect(win.corrColor(null)).toBe("transparent");
    });
  });

  describe("organicLabels", () => {
    it("minute があればそれを、無ければ slot×15分 を HH:MM へ", () => {
      expect(win.organicLabels([{ minute: 75 }, { slot: 3 }, { minute: 0 }])).toEqual([
        "01:15",
        "00:45",
        "00:00",
      ]);
    });
  });

  describe("anEscape", () => {
    it("HTML特殊文字を実体参照へ逃がす", () => {
      expect(win.anEscape('<b>&"')).toBe("&lt;b&gt;&amp;&quot;");
    });

    it("null / undefined は空文字", () => {
      expect(win.anEscape(null)).toBe("");
      expect(win.anEscape(undefined)).toBe("");
    });
  });

  describe("_rgba", () => {
    it("#rrggbb を rgba() へ開く", () => {
      expect(win._rgba("#a96e49", 0.5)).toBe("rgba(169, 110, 73, 0.5)");
      expect(win._rgba("#000000", 1)).toBe("rgba(0, 0, 0, 1)");
    });
  });

  describe("safeRender", () => {
    it("data が無ければ描画関数を呼ばない", () => {
      const fn = vi.fn();
      win.safeRender("x", fn, null);
      expect(fn).not.toHaveBeenCalled();
    });

    it("1つの描画が投げても呼び出し元へ伝播させない(他の節を巻き込まない)", () => {
      expect(() =>
        win.safeRender("x", () => {
          throw new Error("boom");
        }, {}),
      ).not.toThrow();
      expect(errorSpy).toHaveBeenCalled();
    });
  });
});
