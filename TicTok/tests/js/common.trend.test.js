import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

// 推移のコイン段は「配信ごと」ではなく「日ごと」。壊れ方は見た目では気付けない形になる:
//   - 日をまたいだ配信のコインが開始日へ寄る … その日の棒が実際より高く/低く出る
//   - 同じ日の2配信が2本の棒に割れる         … 1本が「その日いくら出たか」を指さない
//   - 配信の無い日が詰まる                   … 離れた2日が隣り合って見え、空白が消える
//   - 単位を変えると合計が変わる             … 境界の日が落ちている
describe("common.js の推移(コインの日次)", () => {
  let page;
  let chart;

  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body><div id="trend"></div></body></html>`,
    });
    chart = page.win.createSessionTrendChart(page.document.getElementById("trend"), {});
  });
  afterEach(async () => page.close());

  const coinChart = () => chart.charts[0];
  const hourChart = () => chart.charts[1];
  const ys = (ds) => ds.map((p) => p.y);
  const coins = () => ys(coinChart().data.datasets[0].data);
  const hours = () => ys(hourChart().data.datasets[0].data);
  const sum = (values) => values.reduce((a, b) => a + (b || 0), 0);

  // 日の刻みはlocal時刻。test側もlocal時刻で組み、TZに依らず同じ束ね方になるようにする。
  const at = (y, m, d, h) => new Date(y, m - 1, d, h, 0, 0).getTime() / 1000;
  const session = (id, start, durHours) => ({
    id, started_at: start, ended_at: start + durHours * 3600,
  });

  // 2026/06/29(月)週に2本、翌週に1本、8月へ飛んで1本。#2は日をまたぐ。
  const ROWS = [
    session(1, at(2026, 6, 29, 20), 2),
    session(2, at(2026, 7, 5, 23), 2), // 7/5 23:00 → 7/6 01:00
    session(3, at(2026, 7, 6, 20), 3),
    session(4, at(2026, 8, 3, 20), 1),
  ];
  // #2 のコインは7/5と7/6へ分かれて乗る(serverがevent時刻で数えた形)。
  const DAILY = [
    { date: "2026-06-29", diamonds: 1000 },
    { date: "2026-07-05", diamonds: 300 },
    { date: "2026-07-06", diamonds: 2200 },
    { date: "2026-08-03", diamonds: 300 },
  ];
  const view = (extra = {}) => ({ daily: DAILY, coinUnit: "日", ...extra });

  it("コインは日ごとに1本。配信の無い日も0の点として残す(空いた日を詰めない)", () => {
    chart.update(ROWS, view());
    // 6/29〜8/3 = 36日。1日=1点で、配信の無い日も0で埋まる。
    expect(coins().length).toBe(36);
    expect(coins()[0]).toBe(1000);
    expect(coins()[6]).toBe(300); // 7/5
    expect(coins()[7]).toBe(2200); // 7/6
    expect(coins()[35]).toBe(300); // 8/3
    expect(sum(coins())).toBe(3800);
    // 空いた日は0の点として在る(飛ばして詰めていない)。
    expect(coins().slice(1, 6)).toEqual([0, 0, 0, 0, 0]);
  });

  it("日をまたいだ配信のコインは開始日へ寄らない(週まとめでも境目が動く)", () => {
    chart.update(ROWS, view({ unit: "week" }));
    // 7/5(日)23:00開始の配信は6/29週だが、日付をまたいだぶんのコインは7/6週へ乗る。
    // sessionの合計を開始日へ寄せると [1500, 2000, ...] になってしまう。
    expect(coins()).toEqual([1300, 2200, 0, 0, 0, 300]);
    // 配信時間は「その配信がどの期間に始まったか」なので、開始週のまま。
    expect(hours()).toEqual([4, 3, 0, 0, 0, 1]);
  });

  it("単位を変えてもコインの合計は変わらない(まとめで日が落ちない)", () => {
    const totals = {};
    ["session", "week", "month"].forEach((unit) => {
      chart.update(ROWS, view({ unit }));
      totals[unit] = sum(coins());
    });
    expect(totals.session).toBe(3800);
    expect(totals.week).toBe(3800);
    expect(totals.month).toBe(3800);
  });

  it("月は暦月で束ね、目盛と見出しがその月を名乗る", () => {
    chart.update(ROWS, view({ unit: "month" }));
    expect(coins()).toEqual([1000, 2500, 300]);
    const tick = coinChart().options.scales.x.ticks.callback;
    // 目盛は月の頭の日indexに立つ(6/29が0日目なので7/1=2, 8/1=33)。
    expect([0, 2, 33].map((v) => tick(v))).toEqual(["26/06", "26/07", "26/08"]);
    expect(coinChart().options.plugins.tooltip.callbacks.title([{ dataIndex: 1 }]))
      .toBe("2026/07（月合計）");
  });

  it("日の棒は「その日に掛かっていた配信」の本数を名乗る(またいだ翌日も1本と数える)", () => {
    chart.update(ROWS, view());
    const footer = coinChart().options.plugins.tooltip.callbacks.footer;
    expect(footer([{ dataIndex: 0 }])).toEqual(["配信 1本"]); // 6/29
    expect(footer([{ dataIndex: 6 }])).toEqual(["配信 1本"]); // 7/5
    expect(footer([{ dataIndex: 7 }])).toEqual(["配信 2本"]); // 7/6 = またいだ#2 + #3
    expect(footer([{ dataIndex: 1 }])).toEqual(["配信なし"]); // 6/30
  });

  it("同じ日の2配信は1本の棒へ畳まれる(配信ごとの段は2点のまま)", () => {
    const sameDay = [
      session(10, at(2026, 6, 1, 20), 2),
      session(11, at(2026, 6, 1, 23), 0.5),
    ];
    chart.update(sameDay, view({ daily: [{ date: "2026-06-01", diamonds: 1500 }] }));
    expect(coins()).toEqual([1500]);
    expect(hours().length).toBe(2);
  });

  it("x軸は実日付。空いた期間はそのぶん横に空く", () => {
    chart.update(ROWS, view());
    const xs = hourChart().data.datasets[0].data.map((p) => p.x);
    // 6/29 20:00 = 0 + 20/24、7/5 23:00 = 6 + 23/24、8/3 20:00 = 35 + 20/24。
    expect(xs[0]).toBeCloseTo(20 / 24, 6);
    expect(xs[1]).toBeCloseTo(6 + 23 / 24, 6);
    expect(xs[3]).toBeCloseTo(35 + 20 / 24, 6);
    // コインの棒は日の真ん中に立ち、配信の点と同じ軸に載る。
    expect(coinChart().data.datasets[0].data[6].x).toBe(6.5);
    expect(coinChart().options.scales.x.max).toBe(36.5);
  });

  it("収集中(終端なし)の配信は0時間ではなく収集中と名乗る", () => {
    chart.update([{ id: 20, started_at: at(2026, 6, 1, 20), ended_at: null }],
      view({ daily: [{ date: "2026-06-01", diamonds: 10 }] }));
    const label = hourChart().options.plugins.tooltip.callbacks.label;
    expect(label({ dataIndex: 0, dataset: { label: "配信時間" } })).toBe("配信時間: 収集中");
  });
});

// コインの移動平均は棒とは別の段に、窓の違う3本を引く。壊れ方は「線は出ているのに
// 3本が同じ形」で、見た目では気付けない:
//   - 窓が埋まる前から引く … 左端で3本が同じ点の平均になり、重なったまま始まる
//   - 窓を配信のあった日で数える … 窓の実長が配信頻度で伸び縮みする
describe("common.js の推移(コインの移動平均)", () => {
  let page;
  let chart;

  beforeEach(() => {
    page = loadCommon({
      html: `<!doctype html><html><body><div id="trend"></div></body></html>`,
    });
    chart = page.win.createSessionTrendChart(page.document.getElementById("trend"), {
      panels: ["coins", "coinsMa"],
    });
  });
  afterEach(async () => page.close());

  const at = (y, m, d, h) => new Date(y, m - 1, d, h, 0, 0).getTime() / 1000;
  const maChart = () => chart.charts[1];
  const line = (i) => maChart().data.datasets[i].data.map((p) => p.y);

  // 6/1〜6/5の5日。3日目だけ配信が無い(=0コインの日)。
  const ROWS = [
    { id: 1, started_at: at(2026, 6, 1, 20), ended_at: at(2026, 6, 1, 22) },
    { id: 2, started_at: at(2026, 6, 5, 20), ended_at: at(2026, 6, 5, 22) },
  ];
  const DAILY = [
    { date: "2026-06-01", diamonds: 100 },
    { date: "2026-06-02", diamonds: 200 },
    { date: "2026-06-04", diamonds: 400 },
    { date: "2026-06-05", diamonds: 500 },
  ];

  it("窓が埋まるまで線を引かない(左端で3本が重ならない)", () => {
    chart.update(ROWS, { daily: DAILY, coinMa: [2, 3, 4], coinMaText: "日" });
    // 日次は [100, 200, 0, 400, 500]。
    expect(line(0)).toEqual([null, 150, 100, 200, 450]);
    expect(line(1)).toEqual([null, null, 100, 200, 300]);
    expect(line(2)).toEqual([null, null, null, 175, 275]);
  });

  it("窓は暦日で数える(配信の無い日を飛ばさない)", () => {
    chart.update(ROWS, { daily: DAILY, coinMa: [3], coinMaText: "日" });
    // 6/3は配信が無く0コイン。窓から外すと 6/4の3日平均は (100+200+400)/3=233 になる。
    expect(line(0)[3]).toBe(200);
  });

  it("窓の名前は呼び側が決める(単位を変えると凡例も変わる)", () => {
    chart.update(ROWS, { daily: DAILY, coinMa: [7, 14, 25], coinMaText: "日" });
    expect(maChart().data.datasets.map((d) => d.label)).toEqual(["7日", "14日", "25日"]);
    chart.update(ROWS, { unit: "month", daily: DAILY, coinMa: [3, 6, 12], coinMaText: "か月" });
    expect(maChart().data.datasets.map((d) => d.label)).toEqual(["3か月", "6か月", "12か月"]);
  });

  it("窓を渡さなかった線は引かない(空の線を凡例へ出さない)", () => {
    chart.update(ROWS, { daily: DAILY, coinMa: [3], coinMaText: "日" });
    expect(maChart().data.datasets[1].data).toEqual([]);
    expect(maChart().data.datasets[1].hidden).toBe(true);
    expect(maChart().data.datasets[0].hidden).toBe(false);
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
  const ys = (ds) => ds.map((p) => p.y);
  const cpm = () => ys(chart.charts[0].data.datasets[0].data);
  const avg = () => ys(chart.charts[1].data.datasets[0].data);
  const nobox = () => ys(chart.charts[1].data.datasets[1].data);
  const peak = () => ys(chart.charts[2].data.datasets[0].data);

  // 同じ週の2配信。尺が6倍違うので、率を単純平均するか時間で加重するかで答えが変わる。
  const ROWS = [
    { id: 1, started_at: at(2026, 6, 29, 20), ended_at: at(2026, 6, 29, 21),
      comments: 600, observed_seconds: 3600,
      viewers: 100, viewers_avg: 10, viewers_avg_nobox: 5, nobox_seconds: 1800 },
    { id: 2, started_at: at(2026, 6, 30, 20), ended_at: at(2026, 6, 30, 26),
      comments: 1200, observed_seconds: 21600,
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
                    comments: 0, observed_seconds: 0 }]);
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
    expect(cpm()).toEqual([10, null]);
    expect(ys(chart.charts[0].data.datasets[1].data)[1]).toBe(10);
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
