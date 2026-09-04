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
      expect(win.tiColor(1).fg).toBe("#322f27"); // --ink-strong
      expect(win.tiColor(4).fg).toBe("#e9e3cf"); // --chart-surface
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
      ["actSeconds", (v) => win.actSeconds(v)],
      ["actPct", (v) => win.actPct(v)],
      ["entryRatio", (v) => win.entryRatio(v)],
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
      expect(win.cvUnmeasured()).toContain("計測不能");
    });
  });

  describe("率の書式", () => {
    it("% は画面ぜんぶで小数1桁に揃える", () => {
      expect(win.dwellPct(0.256)).toBe("25.6%");
      expect(win.actPct(0.1234)).toBe("12.3%");
      expect(win.actPct(0.1234, 0)).toBe("12%");
    });

    it("entryRatio は1桁%", () => {
      expect(win.entryRatio(0.5)).toBe("50.0%");
    });

    it("peakPct は符号を明示する", () => {
      expect(win.peakPct({ peak: { pct: 12.4 } })).toBe("+12.4%");
      expect(win.peakPct({ peak: { pct: -7.6 } })).toBe("-7.6%");
      expect(win.peakPct({ peak: { pct: 0 } })).toBe("+0.0%");
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

  describe("setNote", () => {
    // 注記は図の直下の1行だけ。統計の作法を語る折りたたみは画面から外した。
    it("結論だけを legendline へ入れる", () => {
      win.setNote("an-dwell-note", "結論だけ");
      expect(page.document.getElementById("an-dwell-note").innerHTML).toBe("結論だけ");
      expect(page.document.getElementById("an-dwell-note-more")).toBe(null);
    });
  });

  describe("anTable", () => {
    it("数値列は header と値の両方へ num を付ける(項目と値が縦に揃う)", () => {
      win.anTable("an-coverage", ["指標", "件数"], [["行", "12"]], [1], "なし");
      const table = page.document.getElementById("an-coverage");
      const ths = Array.from(table.querySelectorAll("thead th"));
      expect(ths.map((th) => th.className)).toEqual(["", "num"]);
      const tds = Array.from(table.querySelectorAll("tbody td"));
      expect(tds[1].className).toBe("num");
    });

    it("tbody には th を置かない(.result-table th の sticky反転色が黒帯になる)", () => {
      win.anTable("an-coverage", ["指標", "件数"], [["行", "12"]], [1], "なし");
      expect(page.document.querySelectorAll("#an-coverage tbody th").length).toBe(0);
    });

    it("行が無いときは空欄ではなく理由を出す", () => {
      win.anTable("an-coverage", ["指標", "件数"], [], [1], "まだありません。");
      expect(page.document.getElementById("an-coverage").textContent).toContain("まだありません。");
    });
  });

  describe("時間帯index の見せ方", () => {
    it("既定はマスに数値を書かず、色とtooltipへ寄せる", () => {
      const html = win.tiCellHTML({ index: 1.25, n: 12 }, "月", "12:00", false);
      expect(html).toContain("></div>");
      expect(html).not.toContain(">1.25<");
      // 値そのものはtooltipに残す(色だけでは何倍か読めない)。
      expect(html).toContain("×1.25");
    });

    it("checkboxを入れたときだけ倍率を書き込む", () => {
      expect(win.tiCellHTML({ index: 1.25, n: 12 }, "月", "12:00", true)).toContain(">1.25<");
    });

    it("観測が1マスも無い行を見分ける(既定で畳む対象)", () => {
      expect(win.tiSlotHasData({ minute: 0, dow: {}, all: { index: null, n: 0 } })).toBe(false);
      expect(win.tiSlotHasData({ minute: 0, dow: { 1: { index: 1.2, n: 3 } }, all: null })).toBe(true);
    });
  });

  describe("headingText", () => {
    // 目次chipの番号は見出しから拾う。<select>を含む①だけ、option文字列まで
    // 連結されて「指標: 入室指標: Comment…」になっていた。
    it("見出しのspanは残し、form controlの文字列だけ落とす", () => {
      const h = page.document.createElement("h3");
      h.innerHTML = '■ ① <span>入室</span>が多いのはいつか'
        + '<select><option>指標: 入室</option><option>指標: Comment</option></select>';
      expect(win.headingText(h)).toBe("■ ① 入室が多いのはいつか");
    });
  });

  describe("目次と section の並び", () => {
    it("DOM順が番号順になっている(本文が番号で名指しするため)", () => {
      const ids = Array.from(page.document.querySelectorAll("main section[id^='an-s']"))
        .map((s) => s.id);
      expect(ids).toEqual([
        "an-s1", "an-s1d", "an-s2", "an-s2d", "an-s3", "an-s3d", "an-s5",
        "an-s6", "an-s7", "an-s9", "an-s11", "an-s12", "an-s14",
      ]);
    });

    it("目次chipは番号だけを出し、説明をtitleへ隠さない", () => {
      const links = Array.from(page.document.querySelectorAll("#an-index a"));
      expect(links.map((a) => a.textContent)).toEqual([
        "①", "①'", "②", "②'", "③", "③'", "⑤", "⑥", "⑦", "⑨", "⑪", "⑫", "⑭",
      ]);
      expect(links[0].hasAttribute("title")).toBe(false);
    });
  });

  describe("表を持つ節は全幅へ戻す", () => {
    it("⑪⑫⑭②' は an-col1 を持たない", () => {
      ["an-s2d", "an-s11", "an-s12", "an-s14"].forEach((id) => {
        expect(page.document.getElementById(id).classList.contains("an-col1")).toBe(false);
      });
    });
  });

  // 解説・但し書きの折りたたみは画面から外した。読む物は図と1行の注記だけ。
  describe("説明文は画面に残さない", () => {
    it("解説・但し書きの<details>を持たない", () => {
      expect(page.document.querySelectorAll("details").length).toBe(0);
      expect(page.document.getElementById("an-caveats")).toBe(null);
    });
  });
});

// 期間はURLとlocalStorageの両方に乗せる。他画面(overview/videos)と同じ作法。
describe("analytics.js の期間の記憶", () => {
  it("?days= を初期値に採り、URLへ書き戻す", async () => {
    const page = loadPage({ page: "analytics", url: "http://localhost:8520/analytics?days=30#an-s12" });
    const spy = vi.spyOn(page.win.console, "warn").mockImplementation(() => {});
    await page.settle();
    expect(page.document.getElementById("an-period").value).toBe("30");
    expect(page.win.location.search).toBe("?days=30");
    expect(page.win.location.hash).toBe("#an-s12");
    spy.mockRestore();
    await page.close();
  });

  it("URLに無ければ localStorage の選択を使う", async () => {
    const page = loadPage({
      page: "analytics",
      url: "http://localhost:8520/analytics",
      before: (win) => win.localStorage.setItem("tictok.analytics.days", "7"),
    });
    const spy = vi.spyOn(page.win.console, "warn").mockImplementation(() => {});
    await page.settle();
    expect(page.document.getElementById("an-period").value).toBe("7");
    spy.mockRestore();
    await page.close();
  });
});
