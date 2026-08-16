import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

// 推移の期間まとめ(週合計/月合計)。壊れ方は「棒は普通に立っているのに数字が違う」形で、
// 見た目では気付けない。危ないのは3つ:
//   - 単位を変えると合計が変わる     … 境界の配信が落ちている(その配信だけ無かったことになる)
//   - 配信の無い週/月が詰まる        … 離れた期間が隣り合って見え、途切れが消える
//   - 1本が何配信ぶんの合計か名乗らない … 1配信の棒と期間合計の棒を読み分けられない
describe("common.js の推移(期間まとめ)", () => {
  let page;
  let win;
  let chart;

  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body><div id="trend"></div></body></html>`,
    });
    win = page.win;
    chart = win.createSessionTrendChart(page.document.getElementById("trend"), { movingAvg: true });
  });
  afterEach(async () => page.close());

  const coinChart = () => chart.charts[0];
  const hourChart = () => chart.charts[1];
  const coins = () => coinChart().data.datasets[0].data;
  const hours = () => hourChart().data.datasets[0].data;
  const sum = (values) => values.reduce((a, b) => a + b, 0);

  // 週/月の境界はlocal時刻で刻む。test側もlocal時刻で組み、TZに依らず同じ束ね方になるようにする。
  const at = (y, m, d, h) => new Date(y, m - 1, d, h, 0, 0).getTime() / 1000;
  const session = (id, start, durHours, diamonds) => ({
    id,
    started_at: start,
    ended_at: start + durHours * 3600,
    stats: { diamonds },
  });

  // 2026/06/29(月)週に2本、翌週に1本、8月へ飛んで1本。
  const ROWS = [
    session(1, at(2026, 6, 29, 20), 2, 1000),
    session(2, at(2026, 7, 5, 23), 1, 500), // 日曜深夜 = まだ6/29週
    session(3, at(2026, 7, 6, 20), 3, 2000),
    session(4, at(2026, 8, 3, 20), 1, 300),
  ];

  it("単位を変えても合計は変わらない(まとめで配信が落ちない)", () => {
    const totals = {};
    ["session", "week", "month"].forEach((unit) => {
      chart.update(ROWS, { unit });
      totals[unit] = { coins: sum(coins()), hours: sum(hours()) };
    });
    expect(totals.week).toEqual(totals.session);
    expect(totals.month).toEqual(totals.session);
    expect(totals.session.coins).toBe(3800);
    expect(totals.session.hours).toBe(7);
  });

  it("週は月曜起点で束ねる(日曜深夜の配信は翌週へ回さない)", () => {
    chart.update(ROWS, { unit: "week" });
    // 6/29週(1500) → 7/6週(2000) → 配信の無い3週 → 8/3週(300)。
    expect(coins()).toEqual([1500, 2000, 0, 0, 0, 300]);
    expect(hours()).toEqual([3, 3, 0, 0, 0, 1]);
  });

  it("配信の無い週は0の点として残す(空白期間を詰めない)", () => {
    chart.update(ROWS, { unit: "week" });
    const footer = coinChart().options.plugins.tooltip.callbacks.footer;
    expect(footer([{ dataIndex: 2 }])).toEqual(["配信 0本"]);
    expect(footer([{ dataIndex: 0 }])).toEqual(["配信 2本"]);
  });

  it("月は暦月で束ね、目盛と見出しがその月を名乗る", () => {
    chart.update(ROWS, { unit: "month" });
    // 週(月曜起点)と月(暦月)は境目が違う。7/5の配信は6/29週だが月では7月へ入る。
    expect(coins()).toEqual([1000, 2500, 300]);
    const tick = coinChart().options.scales.x.ticks.callback;
    expect([0, 1, 2].map((i) => tick(null, i))).toEqual(["26/06", "26/07", "26/08"]);
    expect(coinChart().options.plugins.tooltip.callbacks.title([{ dataIndex: 1 }]))
      .toBe("2026/07（月合計）");
  });

  it("期間合計の配信時間はその期間の総尺(tooltipも合計を名乗る)", () => {
    chart.update(ROWS, { unit: "month" });
    const label = hourChart().options.plugins.tooltip.callbacks.label;
    expect(label({ dataIndex: 1, dataset: { label: "配信時間" } })).toBe("配信時間: 04:00:00");
  });

  it("既定(配信ごと)は1配信=1本のまま。同じ日の2本目も別の棒として残る", () => {
    const sameDay = [
      session(10, at(2026, 6, 1, 20), 2, 1000),
      session(11, at(2026, 6, 1, 23), 1, 500),
    ];
    chart.update(sameDay);
    expect(coinChart().data.labels).toEqual(["20260601", "20260601:2"]);
    expect(coins()).toEqual([1000, 500]);
    // 1本=1配信なので「何本ぶんか」は名乗らない(期間合計の棒とここで見分けが付く)。
    expect(coinChart().options.plugins.tooltip.callbacks.footer([{ dataIndex: 0 }])).toEqual([]);
    expect(coinChart().options.plugins.tooltip.callbacks.title([{ dataIndex: 1 }]))
      .toContain("#00011");
  });

  it("収集中(終端なし)の配信は0時間ではなく収集中と名乗る", () => {
    chart.update([{ id: 20, started_at: at(2026, 6, 1, 20), ended_at: null, stats: { diamonds: 10 } }]);
    const label = hourChart().options.plugins.tooltip.callbacks.label;
    expect(label({ dataIndex: 0, dataset: { label: "配信時間" } })).toBe("配信時間: 収集中");
  });

  it("移動平均の窓は単位ごとに呼び側が決める(棒の本数で数える)", () => {
    chart.update(ROWS, { unit: "week", movingAvgWindow: 2 });
    const ma = coinChart().data.datasets[1].data;
    expect(ma[0]).toBe(1500);
    expect(ma[1]).toBe((1500 + 2000) / 2);
    expect(ma[2]).toBe((2000 + 0) / 2);
  });
});

// 率(コメント/分)と水準(同接)のpane。量(コイン・配信時間)と違って**足せない**ので、
// 期間まとめの壊れ方が「棒は立つのに数字だけ違う」形になり見た目では気付けない。危ないのは:
//   - 期間まとめで率を単純平均する   … 10分の配信と6時間の配信が同じ重みになる
//   - 測れていない点を0として混ぜる  … 「起きなかった」と「観測が無い」が同じ絵になる
//   - 宝箱の記録が無い期間へ線を引く … 落とさなかったのか記録が無いのかを区別できない
describe("common.js の推移(率と水準のpane)", () => {
  let page;
  let chart;

  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body><div id="trend"></div></body></html>`,
    });
    chart = page.win.createSessionTrendChart(page.document.getElementById("trend"), {
      panels: ["comments", "viewers", "peak"],
      movingAvg: true,
    });
  });
  afterEach(async () => page.close());

  const at = (y, m, d, h) => new Date(y, m - 1, d, h, 0, 0).getTime() / 1000;
  const cpm = () => chart.charts[0].data.datasets[0].data;
  const avg = () => chart.charts[1].data.datasets[0].data;
  const nobox = () => chart.charts[1].data.datasets[1].data;
  const peak = () => chart.charts[2].data.datasets[0].data;

  // 同じ週の2配信。尺が6倍違うので、率を単純平均するか時間で加重するかで答えが変わる。
  const ROWS = [
    { id: 1, started_at: at(2026, 6, 29, 20), ended_at: at(2026, 6, 29, 21),
      stats: { diamonds: 0 }, comments: 600, observed_seconds: 3600,
      viewers: 100, viewers_avg: 10, viewers_avg_nobox: 5, nobox_seconds: 1800 },
    { id: 2, started_at: at(2026, 6, 30, 20), ended_at: at(2026, 6, 30, 26),
      stats: { diamonds: 0 }, comments: 1200, observed_seconds: 21600,
      viewers: 40, viewers_avg: 40, viewers_avg_nobox: 30, nobox_seconds: 18000 },
  ];

  it("コメントは観測秒あたりで、期間まとめでは分子分母をそれぞれ足してから割る", () => {
    chart.update(ROWS);
    expect(cpm()).toEqual([600 / 60, 1200 / 360]); // 10.0/分 と 3.33/分
    chart.update(ROWS, { unit: "week" });
    // 単純平均なら (10 + 3.33)/2 = 6.67。時間加重は 1800コメント / 420分 = 4.28…
    expect(cpm()[0]).toBeCloseTo(1800 / 420, 6);
  });

  it("同接の期間まとめは観測時間で加重し、Peakだけは最大を採る", () => {
    chart.update(ROWS, { unit: "week" });
    expect(avg()[0]).toBeCloseTo((10 * 3600 + 40 * 21600) / 25200, 6);
    // 宝箱窓を除く平均の重みは、窓を除いた後に残った時間(観測秒ではない)。
    expect(nobox()[0]).toBeCloseTo((5 * 1800 + 30 * 18000) / 19800, 6);
    // Peakは合計でも平均でもなく、その期間の最大。
    expect(peak()[0]).toBe(100);
  });

  it("観測秒が無い配信は率を持たない(0にしない)", () => {
    chart.update([{ id: 3, started_at: at(2026, 6, 29, 20), ended_at: at(2026, 6, 29, 21),
                    stats: { diamonds: 0 }, comments: 0, observed_seconds: 0 }]);
    expect(cpm()).toEqual([null]);
    expect(avg()).toEqual([null]);
  });

  it("宝箱の記録が無い配信には線を引かず、移動平均もその点を窓から外す", () => {
    const rows = [
      { ...ROWS[0], viewers_avg_nobox: null, nobox_seconds: 0 },
      ROWS[1],
    ];
    chart.update(rows);
    expect(nobox()).toEqual([null, 30]);
    // 率の移動平均は、値を持たない点を0として混ぜない(混ぜると線だけが落ち込む)。
    const ma = chart.charts[0].data.datasets[1].data;
    chart.update([{ ...rows[0], comments: 600 }, { ...rows[1], observed_seconds: 0 }], { movingAvgWindow: 2 });
    expect(chart.charts[0].data.datasets[0].data).toEqual([10, null]);
    expect(chart.charts[0].data.datasets[1].data[1]).toBe(10);
    expect(ma.length).toBe(2);
  });

  it("宝箱窓を除く平均は、残った時間の割合を添えて名乗る", () => {
    chart.update(ROWS);
    const footer = chart.charts[1].options.plugins.tooltip.callbacks.footer;
    expect(footer([{ dataIndex: 0 }])).toEqual(["宝箱窓の外: 観測時間の 50%"]);
    chart.update([{ ...ROWS[0], viewers_avg_nobox: null, nobox_seconds: 0 }]);
    expect(footer([{ dataIndex: 0 }])).toEqual(["宝箱窓を除く: 宝箱の記録が無い期間"]);
  });
});
