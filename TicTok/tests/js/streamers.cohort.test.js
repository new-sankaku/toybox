import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// ファン継続率(日次コホート)。その日のActiveは 継続 / 復帰 / 新規 で過不足なく分かれる。
// 積み上げると土台(継続)が動いた分だけ上の系列の底も上下し、復帰・新規が増えたのか
// 土台が動いただけなのかが読めないので、同じ目盛りの上に線で重ねる。積み上げの高さで
// 読めていたActiveは合計の破線で別に引く。
describe("streamers.js のファン継続率(日次コホート)", () => {
  let page;
  let win;
  let doc;

  // active = new + returned + retained。復帰はserverが持たないので差で出す。
  const DAYS = [
    { date: "2026-08-01", active: 10, new: 10, retained: 0, retention: null },
    { date: "2026-08-02", active: 12, new: 4, retained: 6, retention: 60 },
    { date: "2026-08-03", active: 9, new: 1, retained: 5, retention: 41.6 },
  ];

  beforeEach(async () => {
    page = loadPage({ page: "streamers", url: "http://localhost:8520/streamers" });
    win = page.win;
    doc = page.document;
    await page.settle();
  });
  afterEach(async () => {
    await page.close();
  });

  function chartOf(id) {
    return page.calls.charts.find((c) => c.canvas && c.canvas.id === id);
  }
  const countChart = () => chartOf("sm-cohort-chart");
  const rateChart = () => chartOf("sm-cohort-rate-chart");

  it("内訳は積み上げず、系列ごとの線で描く", () => {
    win.renderCohort({ days: DAYS });
    const chart = countChart();
    expect(chart.config.type).toBe("line");
    expect(chart.options.scales.x.stacked).toBeUndefined();
    expect(chart.options.scales.y.stacked).toBeUndefined();
    expect(chart.data.datasets.every((ds) => ds.stack === undefined)).toBe(true);
  });

  it("継続/復帰/新規に加えて、合計のActiveを破線で引く", () => {
    win.renderCohort({ days: DAYS });
    const chart = countChart();
    expect(chart.data.datasets.map((d) => d.label)).toEqual([
      "継続", "復帰", "新規", "Active(合計)",
    ]);
    expect(chart.data.datasets[0].data).toEqual([0, 6, 5]);
    // 復帰 = active - new - retained
    expect(chart.data.datasets[1].data).toEqual([0, 2, 3]);
    expect(chart.data.datasets[2].data).toEqual([10, 4, 1]);
    expect(chart.data.datasets[3].data).toEqual([10, 12, 9]);
    expect(chart.data.datasets[3].borderDash).toEqual([4, 4]);
    // 合計は内訳の1つではないので、内訳の系統色を続けて名乗らせない。
    const tone = chart.data.datasets.slice(0, 3).map((d) => d.borderColor);
    expect(tone).not.toContain(chart.data.datasets[3].borderColor);
  });

  it("Activeはtooltipのfooterだけが持つ(本文と二重に出さない)", () => {
    win.renderCohort({ days: DAYS });
    const { filter, callbacks } = countChart().options.plugins.tooltip;
    expect(filter({ datasetIndex: 2 })).toBe(true);
    expect(filter({ datasetIndex: 3 })).toBe(false);
    expect(callbacks.footer([{ dataIndex: 1 }])).toBe("Active: 12人");
    expect(callbacks.footer([])).toBe("");
  });

  it("率は別の1枚に分ける(人と%を1枚へ重ねて目盛りを2本にしない)", () => {
    win.renderCohort({ days: DAYS });
    expect(countChart().options.scales.y.title.text).toBe("人");
    expect(countChart().options.scales.y2).toBeUndefined();
    const rate = rateChart();
    expect(rate.options.scales.y.max).toBe(100);
    expect(rate.data.datasets[0].data).toEqual([null, 60, 41.6]);
    // 初日は比べる前の配信日が無い。線を繋ぐと存在しない値を通ったように見える。
    expect(rate.data.datasets[0].spanGaps).toBe(false);
  });

  it("平均は率が取れた日だけで出す(初日のnullを0として混ぜない)", () => {
    win.renderCohort({ days: DAYS });
    const avg = rateChart().data.datasets[1];
    expect(avg.label).toBe("平均 51%");
    expect(avg.data).toEqual([50.8, 50.8, 50.8]);
  });

  it("視聴dataが無ければ案内を出す", () => {
    win.renderCohort({ days: [] });
    expect(doc.getElementById("sm-cohort-empty").classList.contains("hidden")).toBe(false);
    win.renderCohort({ days: DAYS });
    expect(doc.getElementById("sm-cohort-empty").classList.contains("hidden")).toBe(true);
    expect(doc.getElementById("sm-cohort-note").textContent).toBe("3日");
  });
});
