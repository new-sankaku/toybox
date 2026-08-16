import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

// Timelineのbucket集計。ここは**桁が違うだけの嘘**が出る場所で、線は普通に描かれるので
// 気付かれない。bucketは束ねずに1本=1点で描くので、値はDBのbucketそのものが出るのが正しい。
// 危ないのは2つ:
//   - 欠損bucketの同接を0にしてしまう … 実際には続いていた配信が急落したように見える
//   - 表示上限での切り詰めを取り違える … 残すのは新しい側で、古い側から落とす
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

  // 上限は本数ではなく時間で持ち、bucket幅から本数を出す。本数をベタ書きすると、
  // bucket_secondsを変えた瞬間に「描く時間の長さ」が黙って変わる。
  it("表示上限はbucket幅から計算する(時間で持つ)", () => {
    const hours = page.get("TIMELINE_SPAN_HOURS");
    const ceiling = page.get("TIMELINE_MAX_POINTS");
    expect(win.timelineDisplayLimit(60)).toBe((hours * 3600) / 60);
    expect(win.timelineDisplayLimit(30)).toBe((hours * 3600) / 30);
    // 細かいbucketでは時間側でなく点数の天井が効く(際限なく増やさない)。
    expect(win.timelineDisplayLimit(1)).toBe(ceiling);
  });

  it("bucketは束ねない(1本=1点で、値はbucketそのまま)", () => {
    // 540 bucket: 旧実装では上限点数(180)を超えて3本ずつ束ねられていた本数。
    const rows = [];
    for (let i = 0; i < 540; i += 1) {
      rows.push({ diamonds: 1, viewers: 100, comments: 2, likes: 0 });
    }
    chart.update(buckets(rows), []);
    const s = series();

    expect(s.labels).toHaveLength(540);
    // 束ねていれば diamonds[0] は3、comments[0] は6になる。
    expect(s.diamonds[0]).toBe(1);
    expect(s.comments[0]).toBe(2);
    expect(s.viewers.every((v) => v === 100)).toBe(true);
  });

  it("同接も束ねずbucketの値がそのまま並ぶ", () => {
    const rows = [];
    for (let i = 0; i < 540; i += 1) {
      rows.push({ diamonds: 0, viewers: i, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows), []);
    const s = series();
    expect(s.viewers.slice(0, 3)).toEqual([0, 1, 2]);
    expect(s.viewers[539]).toBe(539);
  });

  it("表示上限を超えたら古い側から切り詰める(新しい側は必ず残る)", () => {
    const limit = win.timelineDisplayLimit(10);
    const rows = [];
    for (let i = 0; i < limit + 280; i += 1) {
      rows.push({ diamonds: 1, viewers: i, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows), []);
    const s = series();
    expect(s.labels).toHaveLength(limit);
    // 残るのは新しい側のlimit本(index 280..)。
    expect(s.viewers[0]).toBe(280);
    expect(s.viewers[limit - 1]).toBe(limit + 279);
  });

  it("短い配信は当然そのまま出る", () => {
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
    const limit = win.timelineDisplayLimit(10);
    const rows = [];
    // 表示上限より多く並べ、古い側の同接だけ別の値にしておく。
    for (let i = 0; i < limit + 50; i += 1) {
      rows.push({ diamonds: 0, viewers: i < 50 ? 777 : 100, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows, size), []);
    const s = series();
    // 切り詰めで残るのは新しい側だけ。
    expect(s.labels).toHaveLength(limit);
    expect(s.viewers.every((v) => v === 100)).toBe(true);
  });

  it("表示点数は上限を超えない", () => {
    const limit = win.timelineDisplayLimit(10);
    const rows = [];
    for (let i = 0; i < limit + 1000; i += 1) {
      rows.push({ diamonds: 1, viewers: 5, comments: 0, likes: 0 });
    }
    chart.update(buckets(rows), []);
    expect(series().labels).toHaveLength(limit);
  });

  it("bucketが1件も無ければ前回の線を消す(古い線を残さない)", () => {
    chart.update(buckets([{ diamonds: 5, viewers: 10, comments: 1, likes: 0 }]), []);
    expect(series().diamonds).toHaveLength(1);
    chart.update({ bucket_seconds: 10, buckets: [] }, []);
    const s = series();
    expect(s.diamonds).toEqual([]);
    expect(s.labels).toEqual([]);
  });

  it("最大値は描いている系列から採る(bucketの最大値そのもの)", () => {
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
