import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 大口(実弾)の日次人数。帯は「その日1日のコイン合計」で決まり、重ならない
// (1K〜5K / 5K〜10K / …)。重ねて数えると同じ人を帯の数だけ数えることになり、
// 合計が「1K以上を投げた人数」でなくなる。帯の定義はserverから来るので、本数や
// labelが変わっても画面側で数値を再掲しないことも縛る。
//
// 表示は帯ごとに1段のsmall multiples。積み上げ1枚に戻すと、下の帯が動いた分だけ
// 上の帯の底が上下し、帯自身の増減が読めなくなる。
describe("streamers.js の大口(実弾)日次人数", () => {
  let page;
  let win;
  let doc;

  const TIERS = [
    { min: 1000, max: 5000, label: "1K〜5K", min_label: "1K" },
    { min: 5000, max: 10000, label: "5K〜10K", min_label: "5K" },
    { min: 10000, max: 50000, label: "10K〜50K", min_label: "10K" },
    { min: 50000, max: 100000, label: "50K〜100K", min_label: "50K" },
    { min: 100000, max: null, label: "100K↑", min_label: "100K" },
  ];
  const DAYS = [
    { date: "2026-08-01", tiers: [3, 1, 0, 0, 0], whales: 4 },
    { date: "2026-08-02", tiers: [1, 0, 2, 0, 1], whales: 4 },
    { date: "2026-08-03", tiers: [0, 0, 0, 0, 0], whales: 0 },
  ];
  // 顔ぶれ。身元は人ぶんしか無いのでpeopleへ畳み、日ごとの一覧はkeyと額だけを持つ。
  const ROSTER_DAYS = [
    {
      date: "2026-08-01",
      tiers: [2, 1, 0, 0, 0],
      whales: 3,
      whales_list: [
        { key: "k9", coins: 8000, tier: 1 },
        { key: "k1", coins: 3000, tier: 0 },
        { key: "k2", coins: 1200, tier: 0 },
      ],
    },
    { date: "2026-08-02", tiers: [0, 0, 0, 0, 0], whales: 0, whales_list: [] },
  ];
  const PEOPLE = {
    k9: { unique_id: "whale_king", nickname: "Whale King", avatar: "https://cdn/x.jpg" },
    k1: { unique_id: "aoi", nickname: "あおい", avatar: "" },
    k2: { unique_id: "", nickname: "", avatar: "" },
  };

  function tipEl() {
    return doc.querySelector(".sm-whale-tip");
  }
  // Chart.jsは読まないので、外部tooltipが受け取る形だけを組んで呼ぶ。
  function hover({ panel = 0, dataIndex = 0, opacity = 1 } = {}) {
    const chart = panelCharts()[panel];
    chart.options.plugins.tooltip.external({
      chart,
      tooltip: { opacity, dataPoints: [{ dataIndex }], caretX: 10, caretY: 10 },
    });
    return tipEl();
  }
  function tipNames() {
    return Array.from(tipEl().querySelectorAll(".u-name")).map((el) => el.textContent);
  }

  beforeEach(async () => {
    page = loadPage({ page: "streamers", url: "http://localhost:8520/streamers" });
    win = page.win;
    doc = page.document;
    await page.settle();
  });
  afterEach(async () => {
    await page.close();
  });

  // 段はDOMへその都度組み直される。作り直しで捨てた古いchartがcalls.chartsに残るので、
  // 「今containerにぶら下がっているcanvas」だけを段として数える。
  function panelCharts() {
    return page.calls.charts.filter(
      (c) => c.canvas && c.canvas.closest && c.canvas.closest("#sm-whale-panels"),
    );
  }
  function panelNames() {
    return Array.from(doc.querySelectorAll("#sm-whale-panels .sm-whale-name"))
      .map((el) => el.textContent);
  }
  function panelPeaks() {
    return Array.from(doc.querySelectorAll("#sm-whale-panels .sm-whale-peak"))
      .map((el) => el.textContent);
  }

  it("最上段が合計、以下がserverのlabel順で帯ごと1段", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    expect(panelNames()).toEqual(["1K↑ 合計", "1K〜5K", "5K〜10K", "10K〜50K", "50K〜100K", "100K↑"]);
    const charts = panelCharts();
    expect(charts).toHaveLength(6);
    expect(charts[0].data.labels).toEqual(["2026-08-01", "2026-08-02", "2026-08-03"]);
    expect(charts[0].data.datasets[0].data).toEqual([4, 4, 0]);
    expect(charts[1].data.datasets[0].data).toEqual([3, 1, 0]);
    expect(charts[3].data.datasets[0].data).toEqual([0, 2, 0]);
    expect(charts[5].data.datasets[0].data).toEqual([0, 1, 0]);
  });

  it("積み上げず、段ごとに独立した縦目盛りを持つ(桁の違う帯を潰さない)", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    panelCharts().forEach((c) => {
      expect(c.data.datasets).toHaveLength(1);
      expect(c.data.datasets[0].stack).toBeUndefined();
      expect(c.options.scales.x.stacked).toBeUndefined();
      expect(c.options.scales.y.stacked).toBeUndefined();
      expect(c.options.scales.y.beginAtZero).toBe(true);
      // 金額軸は持たない(人数だけの話)。
      expect(c.options.scales.y2).toBeUndefined();
    });
  });

  it("日付の目盛りは最下段だけが出す(同じ軸を段の数だけ書かない)", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    const charts = panelCharts();
    expect(charts.map((c) => c.options.scales.x.display)).toEqual([
      false, false, false, false, false, true,
    ]);
  });

  it("段ごとの目盛りは伏せる代わりに、名前の脇へその段の最大人数を出す", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    expect(panelPeaks()).toEqual([
      "最大 4人", "最大 3人", "最大 1人", "最大 2人", "最大 0人", "最大 1人",
    ]);
    panelCharts().forEach((c) => {
      expect(c.options.scales.y.display).toBe(false);
    });
  });

  it("名前と最大値は塗りの外(左の欄)へ出す(棒に重ねて上の余白を作らない)", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    const container = doc.getElementById("sm-whale-panels");
    // 1段=名前欄+塗りの2cell。塗りの中にlabelを置かない。
    expect(container.children).toHaveLength(12);
    expect(container.querySelectorAll(".sm-whale-plot .sm-whale-name")).toHaveLength(0);
    panelCharts().forEach((c) => {
      expect(c.options.layout.padding.top).toBeLessThanOrEqual(2);
    });
  });

  // 棒に添える人数。目盛りを伏せている以上、実数はここが主な読み口になる。
  describe("棒の人数ラベル", () => {
    // Chart.jsは読まないので、pluginが受け取る形だけを組んで描画命令を拾う。
    // y = 棒の上端。top = 塗り領域の上端。
    function drawnLabels({ values, step = 30, top = 0, panel = 0 }) {
      const drawn = [];
      const chart = {
        getDatasetMeta: () => ({
          data: values.map((v, i) => ({ x: i * step, y: 40 - v })),
        }),
        data: { datasets: [{ data: values }] },
        chartArea: { top, right: values.length * step, left: 0, bottom: 40 },
        ctx: {
          save() {}, restore() {},
          measureText: (t) => ({ width: String(t).length * 6.6 }),
          fillText(t, x, y) { drawn.push({ t, x, y, fill: this.fillStyle, baseline: this.textBaseline }); },
        },
      };
      panelCharts()[panel].config.plugins[0].afterDatasetsDraw(chart);
      return drawn;
    }

    beforeEach(() => {
      win.renderWhales({ days: DAYS, tiers: TIERS });
    });

    it("棒が立った日だけに書く(0の日は書かない)", () => {
      expect(drawnLabels({ values: [3, 0, 12] }).map((d) => d.t)).toEqual(["3", "12"]);
    });

    it("数字が棒の間隔に入らない密度なら、その段は数字を出さない", () => {
      expect(drawnLabels({ values: [3, 4, 5], step: 6 })).toEqual([]);
    });

    it("上に1行ぶん残っている棒は棒の上へ書く", () => {
      const [low] = drawnLabels({ values: [5] });
      expect(low.baseline).toBe("bottom");
      expect(low.y).toBeLessThan(40 - 5);
    });

    // 全部の棒が上に1行空けられるだけの余白を取ると、その空きぶん棒が縮んで段の上半分が
    // 死ぬ。入らない一番高い棒だけを棒の中へ入れて、枠から出さない。
    it("上に余白が無い一番高い棒は棒の中へ書く", () => {
      const [tall] = drawnLabels({ values: [38], top: 0 });
      expect(tall.baseline).toBe("top");
      expect(tall.y).toBeGreaterThanOrEqual(0);
    });

    it("棒の中の文字色は塗りの濃さで選ぶ(濃い帯でink色に沈ませない)", () => {
      // panel 1 = 一番薄い帯(1K〜5K)、panel 5 = 一番濃い帯(100K↑)。
      const pale = drawnLabels({ values: [38], panel: 1 })[0];
      const dark = drawnLabels({ values: [38], panel: 5 })[0];
      expect(pale.fill).not.toBe(dark.fill);
    });
  });

  // 帯の本数はrampの5段より多い。足りないぶんを剰余で先頭へ折り返すと、薄い色が下の帯にも
  // 現れて色から読める上下関係が壊れる。段数ぶんの薄→濃を作れているかを縛る。
  it("帯がrampの段数より多くても、段ごとに違う色が薄→濃の順で当たる", () => {
    const many = Array.from({ length: 11 }, (_, i) => ({
      min: 1000 * (i + 1), max: null, label: `帯${i}`, min_label: "1K",
    }));
    win.renderWhales({
      days: [{ date: "2026-08-01", tiers: many.map(() => 1), whales: 11 }],
      tiers: many,
    });
    // 先頭は合計段(帯の系統色ではない)なので外す。
    const fills = panelCharts().slice(1).map((c) => c.data.datasets[0].backgroundColor);
    expect(fills).toHaveLength(11);
    expect(new Set(fills).size).toBe(11);
    const lum = fills.map((f) => {
      const m = String(f).match(/(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
      return 0.299 * Number(m[1]) + 0.587 * Number(m[2]) + 0.114 * Number(m[3]);
    });
    lum.forEach((v, i) => {
      if (i) expect(v).toBeLessThan(lum[i - 1]);
    });
  });

  it("帯の本数が変わったら段を組み直す(古い帯が残らない)", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    win.renderWhales({
      days: [{ date: "2026-08-01", tiers: [2, 1], whales: 3 }],
      tiers: TIERS.slice(0, 2),
    });
    expect(panelNames()).toEqual(["1K↑ 合計", "1K〜5K", "5K〜10K"]);
    const charts = panelCharts();
    expect(charts).toHaveLength(3);
    expect(charts[2].data.datasets[0].data).toEqual([1]);
  });

  it("同じ帯構成で描き直しても段は作り直さない(dataだけ差し替える)", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    const first = panelCharts();
    win.renderWhales({ days: DAYS.slice(0, 2), tiers: TIERS });
    const second = panelCharts();
    expect(second).toHaveLength(6);
    expect(second[0]).toBe(first[0]);
    expect(second[0].data.labels).toEqual(["2026-08-01", "2026-08-02"]);
  });

  it("合計段の呼び名はserverの最小帯から作る", () => {
    win.renderWhales({
      days: [{ date: "2026-08-01", tiers: [1], whales: 1 }],
      tiers: [{ min: 2000, max: null, label: "2K↑", min_label: "2K" }],
    });
    expect(panelNames()).toEqual(["2K↑ 合計", "2K↑"]);
  });

  it("日数と最大人数を見出しに添える", () => {
    win.renderWhales({ days: DAYS, tiers: TIERS });
    expect(doc.getElementById("sm-whale-note").textContent).toBe("3日 / 最大 4人");
  });

  it("1人も居なければ案内を出し、0の平線が並ぶだけのgraphは畳む", () => {
    win.renderWhales({ days: [DAYS[2]], tiers: TIERS });
    expect(doc.getElementById("sm-whale-empty").classList.contains("hidden")).toBe(false);
    expect(doc.getElementById("sm-whale-panels").classList.contains("hidden")).toBe(true);
    win.renderWhales({ days: DAYS, tiers: TIERS });
    expect(doc.getElementById("sm-whale-empty").classList.contains("hidden")).toBe(true);
    expect(doc.getElementById("sm-whale-panels").classList.contains("hidden")).toBe(false);
  });

  // 人数だけでは「同じ常連が毎日居るのか、日替わりで別人が来ているのか」が読めない。
  // 棒に重ねたら、その日その帯の顔ぶれを名前とアイコンで名乗らせる。
  describe("棒に重ねたときの顔ぶれ", () => {
    beforeEach(() => {
      win.renderWhales({ days: ROSTER_DAYS, tiers: TIERS, people: PEOPLE });
    });

    it("段の帯に属する人だけを額の多い順に出す", () => {
      hover({ panel: 1, dataIndex: 0 });
      expect(tipNames()).toEqual(["あおい", "(unknown)"]);
      expect(tipEl().querySelector(".sm-whale-tip-head").textContent)
        .toBe("2026-08-01 1K〜5K 2人");
    });

    it("合計段は帯で絞らず、その日の大口を全部出す", () => {
      hover({ panel: 0, dataIndex: 0 });
      expect(tipNames()).toEqual(["Whale King", "あおい", "(unknown)"]);
      expect(tipEl().querySelector(".sm-whale-tip-head").textContent)
        .toBe("2026-08-01 1K↑ 合計 3人");
    });

    it("アイコンを添える(URLがある人は画像、無い人は頭文字)", () => {
      hover({ panel: 0, dataIndex: 0 });
      const avatars = Array.from(tipEl().querySelectorAll(".av"));
      expect(avatars).toHaveLength(3);
      expect(avatars[0].querySelector("img").src).toContain("/api/avatar?u=");
      // URLを記録できていない人はID単位のpoolを引き、そこにも無ければ頭文字へ落ちる。
      expect(avatars[1].querySelector("img").src).toContain("/api/avatar?id=aoi");
      expect(avatars[2].querySelector("img")).toBeNull();
      expect(avatars[2].textContent).toBe("?");
    });

    it("人数は帯の集計から出し、一覧が切れても数は狂わない(残りは他N人)", () => {
      const many = Array.from({ length: 30 }, (_, i) => ({ key: `m${i}`, coins: 9000 - i, tier: 0 }));
      win.renderWhales({
        days: [{ date: "2026-08-05", tiers: [40, 0, 0, 0, 0], whales: 40, whales_list: many }],
        tiers: TIERS,
        people: {},
      });
      hover({ panel: 1, dataIndex: 0 });
      expect(tipEl().querySelector(".sm-whale-tip-head").textContent).toBe("2026-08-05 1K〜5K 40人");
      expect(tipEl().querySelectorAll(".sm-whale-tip-row")).toHaveLength(12);
      expect(tipEl().querySelector(".sm-whale-tip-more").textContent).toBe("他 28人");
    });

    it("大口が居ない日は札に0人とだけ出す(前の日の顔ぶれを残さない)", () => {
      hover({ panel: 1, dataIndex: 0 });
      hover({ panel: 1, dataIndex: 1 });
      expect(tipNames()).toEqual([]);
      expect(tipEl().querySelector(".sm-whale-tip-head").textContent).toBe("2026-08-02 1K〜5K 0人");
    });

    it("cursorが外れたら畳む", () => {
      hover({ panel: 0, dataIndex: 0 });
      expect(tipEl().classList.contains("hidden")).toBe(false);
      hover({ panel: 0, dataIndex: 0, opacity: 0 });
      expect(tipEl().classList.contains("hidden")).toBe(true);
    });

    it("別の配信者を描き直したら畳む(前の配信者の顔ぶれを出したまま残さない)", () => {
      hover({ panel: 0, dataIndex: 0 });
      win.renderWhales({ days: ROSTER_DAYS, tiers: TIERS, people: PEOPLE });
      expect(tipEl().classList.contains("hidden")).toBe(true);
    });

    it("serverが古くて顔ぶれを返さなくても落ちない(人数だけの表示に留まる)", () => {
      win.renderWhales({ days: DAYS, tiers: TIERS });
      hover({ panel: 1, dataIndex: 0 });
      expect(tipNames()).toEqual([]);
      expect(tipEl().querySelector(".sm-whale-tip-head").textContent).toBe("2026-08-01 1K〜5K 3人");
    });
  });

  it("serverが古くて帯を返さなくても落ちない", () => {
    win.renderWhales({ days: [{ date: "2026-08-01", active: 10 }] });
    expect(panelNames()).toEqual([]);
    expect(doc.getElementById("sm-whale-empty").classList.contains("hidden")).toBe(false);
  });
});
