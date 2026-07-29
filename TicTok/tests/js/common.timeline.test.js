import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

// Timelineのbucket集計。ここは**桁が違うだけの嘘**が出る場所で、線は普通に描かれるので
// 気付かれない。特に危ないのが2つ:
//   - 同接(level)を合計してしまう … bucketを束ねた瞬間に「同接3000人」のような値が出る
//   - 欠損bucketの同接を0にしてしまう … 実際には続いていた配信が急落したように見える
// 集計の指定は TIMELINE_SERIES の agg("sum" / "last")が唯一の根拠。
describe("common.js のTimeline集計", () => {
  let page;
  let win;
  let chart;

  beforeEach(() => {
    page = loadCommon({ html: `<!doctype html><html><body><div id="tl"></div></body></html>` });
    win = page.win;
    chart = win.createTimelineChart(page.document.getElementById("tl"));
  });
  afterEach(async () => page.close());

  /** 系列ごとの描画データ。panelの並びは TIMELINE_SERIES と同じ。 */
  function series() {
    const keys = page.get("TIMELINE_SERIES").map((s) => s.key);
    const out = {};
    chart.charts.forEach((c, i) => {
      out[keys[i]] = c.data.datasets[0].data;
    });
    out.labels = chart.charts[0].data.labels;
    return out;
  }

  const T0 = Date.UTC(2026, 6, 21, 5, 0, 0) / 1000;

  function buckets(rows, size = 10) {
    return {
      bucket_seconds: size,
      buckets: rows.map((r, i) => ({ start: T0 + i * size, ...r })),
    };
  }

  // 表示上限(CHART_DISPLAY_LIMIT)での切り詰めが先、束ねはその後。順序を取り違えると
  // 束ねる本数が変わり、件数系列の1点あたりの意味が静かにずれる。
  const GROUP_OF = (count) => {
    const kept = Math.min(count, page.get("CHART_DISPLAY_LIMIT"));
    return Math.ceil(kept / page.get("TIMELINE_MAX_POINTS"));
  };

  it("同接と件数で集計の仕方が違う(同接は合計しない)", () => {
    // 540 bucket: 表示上限(720)には掛からず、上限点数(180)は超えるので必ず束ねられる。
    const rows = [];
    for (let i = 0; i < 540; i += 1) {
      rows.push({ diamonds: 1, viewers: 100, comments: 2, likes: 0 });
    }
    chart.update(buckets(rows), []);
    const s = series();

    const group = GROUP_OF(540);
    expect(group).toBe(3);
    // 件数は束ねた本数ぶん積み上がる。
    expect(s.diamonds[0]).toBe(group * 1);
    expect(s.comments[0]).toBe(group * 2);
    // 同接はどれだけ束ねても人数のまま。
    expect(s.viewers.every((v) => v === 100)).toBe(true);
  });

  it("束ねた同接はその窓の最後の値になる(平均でも最大でもない)", () => {
    const rows = [];
    for (let i = 0; i < 540; i += 1) {
      rows.push({ diamonds: 0, viewers: i, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows), []);
    const s = series();
    const group = GROUP_OF(540);
    // 1つ目の窓は 0..group-1 を束ねるので、最後の値 = group-1。
    expect(s.viewers[0]).toBe(group - 1);
    expect(s.viewers[1]).toBe(2 * group - 1);
  });

  it("切り詰めてから束ねる(束ねてから切り詰めない)", () => {
    const limit = page.get("CHART_DISPLAY_LIMIT");
    const rows = [];
    for (let i = 0; i < 1000; i += 1) {
      rows.push({ diamonds: 1, viewers: i, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows), []);
    const s = series();
    // 1000本を先に720本へ切り詰めるので、束ねる本数は ceil(720/180)=4。
    // 先に束ねていたなら ceil(1000/180)=6 になる。
    expect(GROUP_OF(1000)).toBe(4);
    expect(s.diamonds[0]).toBe(4);
    // 残るのは新しい側の720本(index 280..999)なので、最初の窓の最終値は283。
    expect(s.viewers[0]).toBe(1000 - limit + 3);
  });

  it("束ねない量なら値がそのまま出る", () => {
    chart.update(
      buckets([
        { diamonds: 5, viewers: 10, comments: 1, likes: 0 },
        { diamonds: 7, viewers: 12, comments: 2, likes: 3 },
      ]),
      [],
    );
    const s = series();
    expect(s.diamonds).toEqual([5, 7]);
    expect(s.viewers).toEqual([10, 12]);
    expect(s.likes).toEqual([0, 3]);
  });

  // 欠損bucket(そのbucketにeventが1件も無い)は、件数なら0が正しいが、
  // 同接を0にすると「視聴者が居なくなった」という起きていない出来事を描くことになる。
  it("欠損bucketは件数を0で埋め、同接は直前の値を持ち越す", () => {
    const size = 10;
    chart.update(
      {
        bucket_seconds: size,
        buckets: [
          { start: T0, diamonds: 5, viewers: 40, comments: 1, likes: 0 },
          // T0+10 と T0+20 は欠損。
          { start: T0 + size * 3, diamonds: 2, viewers: 55, comments: 1, likes: 0 },
        ],
      },
      [],
    );
    const s = series();
    expect(s.diamonds).toEqual([5, 0, 0, 2]);
    expect(s.comments).toEqual([1, 0, 0, 1]);
    expect(s.viewers).toEqual([40, 40, 40, 55]);
  });

  it("先頭を切り詰めても、最初の点は0ではなく切り詰め前の同接から続く", () => {
    const size = 10;
    const limit = page.get("CHART_DISPLAY_LIMIT");
    const rows = [];
    // 表示上限より多く並べ、古い側の同接だけ別の値にしておく。
    for (let i = 0; i < limit + 50; i += 1) {
      rows.push({ diamonds: 0, viewers: i < 50 ? 777 : 100, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows, size), []);
    const s = series();
    // 切り詰めで残るのは新しい側だけ。
    expect(s.labels.length).toBeLessThanOrEqual(page.get("TIMELINE_MAX_POINTS"));
    expect(s.viewers.every((v) => v === 100)).toBe(true);
  });

  it("表示点数は上限を超えない", () => {
    const rows = [];
    for (let i = 0; i < 3000; i += 1) {
      rows.push({ diamonds: 1, viewers: 5, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows), []);
    expect(series().labels.length).toBeLessThanOrEqual(page.get("TIMELINE_MAX_POINTS"));
  });

  it("bucketが1件も無ければ前回の線を消す(古い線を残さない)", () => {
    chart.update(buckets([{ diamonds: 5, viewers: 10, comments: 1, likes: 0 }]), []);
    expect(series().diamonds).toHaveLength(1);
    chart.update({ bucket_seconds: 10, buckets: [] }, []);
    const s = series();
    expect(s.diamonds).toEqual([]);
    expect(s.labels).toEqual([]);
  });

  it("最大値は束ねた後の系列から採る(同接は人数、件数は窓の合計)", () => {
    const peaks = () =>
      Array.from(page.document.querySelectorAll(".a-spark-peak")).map((el) => el.textContent);
    chart.update(
      buckets([
        { diamonds: 5, viewers: 10, comments: 1, likes: 0 },
        { diamonds: 7, viewers: 12, comments: 2, likes: 0 },
      ]),
      [],
    );
    // 並びは TIMELINE_SERIES と同じ: コイン / 同接 / Comment / Like。
    expect(peaks()).toEqual(["最大 7", "最大 12", "最大 2", "最大 0"]);
  });

  it("clearで最大値の表示も消す(前の配信の数字を残さない)", () => {
    chart.update(buckets([{ diamonds: 5, viewers: 10, comments: 1, likes: 0 }]), []);
    chart.update({ bucket_seconds: 10, buckets: [] }, []);
    const peaks = Array.from(page.document.querySelectorAll(".a-spark-peak")).map(
      (el) => el.textContent,
    );
    expect(peaks).toEqual(["", "", "", ""]);
  });
});
