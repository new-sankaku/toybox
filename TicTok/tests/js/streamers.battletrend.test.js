import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// Battle 分析のスコア推移。生誕祭のようなイベント回は通常の数十〜数百倍まで跳ねるため、
// 線形軸のままだと残りの全戦が軸の底へ潰れる。跳ねた戦を一覧から外して逃げると「いつ
// 跳ねたのか」が読めなくなるので、外さずに軸の取り方で読めるようにすることを縛る。
describe("streamers.js のスコア推移(Battle)", () => {
  let page;
  let win;
  let doc;

  const DAY = 86400;
  const BASE = Date.UTC(2026, 4, 1, 3, 0, 0) / 1000; // 2026-05-01

  // 通常回20戦 + 生誕祭1戦。backendは新しい順で返すので、ここも新しい順で作る。
  function history() {
    const normal = Array.from({ length: 20 }, (_, i) => ({
      battle_id: `n${i}`,
      started_at: BASE + i * DAY,
      own_score: 10000 + i * 100,
      opp_score: 9000 + i * 100,
      diamonds: 5000 + i * 50,
      result: "win",
      opponent: { nickname: `相手${i}`, unique_id: `opp${i}` },
    }));
    const festival = {
      battle_id: "fes",
      started_at: BASE + 30 * DAY,
      own_score: 3000000,
      opp_score: 2500000,
      diamonds: 1500000,
      result: "win",
      opponent: { nickname: "生誕祭", unique_id: "fes" },
    };
    return [festival, ...normal].sort((a, b) => b.started_at - a.started_at);
  }

  // Scoreとコインは単位が違うのでpanelを分けてある。x(戦の並び)だけを共有する。
  function pane(name) {
    const id = name === "score" ? "sm-battle-trend-p1" : "sm-battle-trend-p2";
    return page.calls.charts.find((c) => c.canvas && c.canvas.id === id);
  }
  const score = () => pane("score");
  const coin = () => pane("coin");

  function setMode(id, value) {
    const el = doc.getElementById(id);
    el.value = value;
    el.dispatchEvent(new win.Event("change", { bubbles: true }));
  }

  beforeEach(async () => {
    page = loadPage({ page: "streamers", url: "http://localhost:8520/streamers" });
    win = page.win;
    doc = page.document;
    await page.settle();
    win.renderBattleTrend(history());
  });
  afterEach(async () => {
    await page.close();
  });

  it("既定は対数軸(跳ねた1戦で他が潰れない)", () => {
    expect(doc.getElementById("sm-battle-trend-y").value).toBe("log");
    expect(score().options.scales.y.type).toBe("logarithmic");
    expect(coin().options.scales.y.type).toBe("logarithmic");
    // 対数だと名乗らせる(圧縮された縦を実差として読ませない)。
    expect(score().options.scales.y.title.text).toContain("対数");
  });

  it("どの表示でも跳ねた戦を一覧から外さない", () => {
    ["log", "linear", "clip"].forEach((mode) => {
      setMode("sm-battle-trend-y", mode);
      [score(), coin()].forEach((c) =>
        c.data.datasets.forEach((ds) => expect(ds.data).toHaveLength(21)));
    });
  });

  it("線形は生の値をそのまま置く", () => {
    setMode("sm-battle-trend-y", "linear");
    const c = score();
    expect(c.options.scales.y.type).toBe("linear");
    expect(c.options.scales.y.beginAtZero).toBe(true);
    expect(c.options.scales.y.max).toBeUndefined();
    expect(Math.max(...c.data.datasets[0].data)).toBe(3000000);
  });

  it("常用域は上位を上端で頭打ちにし、頭打ちにした戦へ印を付ける", () => {
    setMode("sm-battle-trend-y", "clip");
    const c = score();
    const plotted = Math.max(...c.data.datasets[0].data);
    expect(plotted).toBeGreaterThan(0);
    expect(plotted).toBeLessThan(3000000);
    // 頭打ちの印が枠で切れないよう、軸は頭打ちの位置より少しだけ上まで取る。
    expect(c.options.scales.y.max).toBeGreaterThan(plotted);
    // 生誕祭は時系列の最後(古い→新しい順に並べ替えた末尾)。
    expect(c.data.datasets[0].pointStyle[20]).toBe("triangle");
    expect(c.data.datasets[0].pointStyle[0]).toBe("circle");
    const bar = coin().data.datasets[0];
    expect(bar.backgroundColor[20]).not.toBe(bar.backgroundColor[0]);
    expect(c.options.scales.y.title.text).toContain("頭打ち");
  });

  it("頭打ちにしてもtooltipは実値を出す(その戦がいくつだったかを画面から消さない)", () => {
    setMode("sm-battle-trend-y", "clip");
    const c = score();
    const label = c.options.plugins.tooltip.callbacks.label({
      datasetIndex: 0,
      dataIndex: 20,
      dataset: { label: "自陣Score" },
      parsed: { y: c.options.scales.y.max },
    });
    expect(label).toContain("3,000,000");
    expect(label).toContain("頭打ち");
  });

  it("対数軸に0は置けないので、0の戦は線を切る(軸の外へ落とさない)", () => {
    win.renderBattleTrend([
      { battle_id: "z", started_at: BASE + DAY, own_score: 0, opp_score: 12000, diamonds: 0 },
      { battle_id: "a", started_at: BASE, own_score: 11000, opp_score: 9000, diamonds: 400 },
    ]);
    expect(score().data.datasets[0].data).toEqual([11000, null]);
    expect(coin().data.datasets[0].data).toEqual([400, null]);
  });

  it("横軸を日時にすると実際の時間で並ぶ(配信の空いた期間が空白として出る)", () => {
    setMode("sm-battle-trend-x", "time");
    const c = score();
    expect(c.options.scales.x.type).toBe("linear");
    expect(c.data.labels).toEqual([]);
    expect(c.data.datasets[0].data[0].x).toBe(BASE * 1000);
    expect(c.data.datasets[0].data[20].x).toBe((BASE + 30 * DAY) * 1000);
    // 目盛はいちばん下のpanelだけが出し、上のpanelは軸を共有する。
    expect(c.options.scales.x.ticks.display).toBe(false);
    expect(coin().options.scales.x.ticks.display).toBe(true);
    // 間隔から幅を決めさせると、密に戦った日の棒が消える。
    expect(coin().data.datasets[0].barThickness).toBe(3);
  });

  it("日時軸では日をまたぐ隙間の線を消す(配信していない期間に推移を描かない)", () => {
    setMode("sm-battle-trend-x", "time");
    const seg = score().data.datasets[0].segment.borderColor;
    const span = (ms) => seg({ p0: { parsed: { x: 0 } }, p1: { parsed: { x: ms } } });
    expect(span(30 * 86400000)).toBe("transparent");
    expect(span(3600 * 1000)).toBeUndefined(); // 同じ配信の中は繋ぐ
  });

  it("横軸が戦順なら1戦=1枠の等間隔(日付labelで並ぶ)", () => {
    setMode("sm-battle-trend-x", "time");
    setMode("sm-battle-trend-x", "seq");
    const c = score();
    expect(c.options.scales.x.type).toBe("category");
    expect(c.data.labels).toHaveLength(21);
    expect(typeof c.data.datasets[0].data[0]).toBe("number");
    expect(coin().data.datasets[0].barThickness).toBeUndefined();
    // 戦順は時間を名乗らないので、隙間で線を切る必要も無い。
    expect(c.data.datasets[0].segment).toBeUndefined();
  });

  it("同じ日に複数戦あっても目盛りが重ならない(2戦目以降へ通し番号)", () => {
    win.renderBattleTrend([
      { battle_id: "b", started_at: BASE + 60, own_score: 2, opp_score: 1, diamonds: 1 },
      { battle_id: "a", started_at: BASE, own_score: 1, opp_score: 1, diamonds: 1 },
    ]);
    const labels = score().data.labels;
    expect(labels[0]).toBe(labels[1].split(":")[0]);
    expect(labels[1]).toMatch(/:2$/);
  });

  it("戦数が少なければ頭打ちしない(切っていないのに頭打ちと名乗らない)", () => {
    setMode("sm-battle-trend-y", "clip");
    win.renderBattleTrend([
      { battle_id: "b", started_at: BASE + DAY, own_score: 900000, opp_score: 1000, diamonds: 5 },
      { battle_id: "a", started_at: BASE, own_score: 1000, opp_score: 1000, diamonds: 5 },
    ]);
    const c = score();
    expect(c.options.scales.y.max).toBeUndefined();
    expect(c.options.scales.y.title.text).not.toContain("頭打ち");
  });
});
