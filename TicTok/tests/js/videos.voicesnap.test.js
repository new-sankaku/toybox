import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 文字起こしの秒を声の縁へ寄せる。whisperの語の時刻は実際に声が出るより 0.24〜0.37秒 手前を
// 指すので(直前の無音が長いほど手前へ食い込む)、そのまま飛ぶと無音から再生が始まり、
// そのままIN/OUTにすると頭に無音が入って語尾が切れる。
// 動かすのは外側だけ = 内容を削る向きには絶対に動かない、というのがこの寄せの前提なので、
// 「動かさない」側の条件を1つずつ見る。
describe("videos.js の声の縁への寄せ", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "videos", url: "http://localhost:8520/videos" });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
    page.set("state.current", { recording_id: 1 });
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  // 10.0〜12.0 と 20.0〜21.0 で声が出ている録画。
  function spans() {
    page.set("state.voiceSpans", [
      { start: 10.0, end: 12.0 },
      { start: 20.0, end: 21.0 },
    ]);
  }

  function fakeVideo(time = 0) {
    const video = doc.getElementById("video");
    let current = time;
    Object.defineProperty(video, "currentTime", {
      configurable: true, get: () => current, set: (v) => { current = v; },
    });
    video.play = () => Promise.resolve();
    video.pause = () => {};
    return video;
  }

  it("INは直後の声の頭まで進む", () => {
    spans();
    // 語頭が声の 0.3秒 手前を指している実測の形。
    expect(win.voiceIn(9.7)).toBe(10.0);
  });

  it("INは窓(0.6秒)より遠い声へは飛ばない", () => {
    spans();
    // ここで飛ばすと、押した行とは別の発話の頭へ着地する。
    expect(win.voiceIn(9.0)).toBe(9.0);
  });

  it("INは既に声の中なら動かない", () => {
    spans();
    // 文の途中の行(前の行と地続き)。次の声まで進めると別の発話へ移ってしまう。
    expect(win.voiceIn(11.0)).toBe(11.0);
  });

  it("OUTは声の尾まで伸びる", () => {
    spans();
    // 語末が声の終わりの 0.16秒 手前を指している実測の形。
    expect(win.voiceOut(11.85)).toBe(12.0);
  });

  it("OUTは声の途中では伸びない", () => {
    spans();
    // 選択が文の途中で終わっている。声の終わりまで伸ばすと、選んでいない発話まで入る。
    expect(win.voiceOut(10.5)).toBe(10.5);
  });

  it("OUTは無音の中なら動かない", () => {
    spans();
    expect(win.voiceOut(13.0)).toBe(13.0);
  });

  it("声の判定が無ければ何も変えない", () => {
    page.set("state.voiceSpans", []);
    expect(win.voiceIn(9.7)).toBe(9.7);
    expect(win.voiceOut(11.85)).toBe(11.85);
  });

  it("文字起こしの範囲選択はIN/OUTを両端とも寄せる", () => {
    spans();
    page.set("state.segments", [
      { start: 9.7, end: 10.9, text: "あ" },
      { start: 11.0, end: 11.85, text: "い" },
    ]);
    win.selectSegmentRange(0, 1);
    expect(page.get("state.cutIn")).toBe(10.0);
    expect(page.get("state.cutOut")).toBe(12.0);
  });

  it("行clickのseekも声の頭へ寄る", async () => {
    spans();
    const video = fakeVideo(0);
    page.set("state.segments", [{ start: 9.7, end: 10.9, text: "あ" }]);
    win.renderSegments();
    const row = doc.querySelector("#segments .vd-seg");
    row.dispatchEvent(new win.MouseEvent("mousedown", { bubbles: true }));
    win.dispatchEvent(new win.Event("mouseup"));
    expect(video.currentTime).toBe(10.0);
  });

  it("commentのhitは寄せない（秒は声ではなく発言の到着時刻）", () => {
    spans();
    expect(win.isTranscriptHit({ source: "comment" })).toBe(false);
    expect(win.isTranscriptHit({ source: "stt" })).toBe(true);
  });

  it("声の判定が後から届いたら、これから通る無音のぶんだけ寄せ直す", () => {
    spans();
    const video = fakeVideo(9.7);
    const hit = { recording_id: 1, source: "stt", video_time: 9.7, end_time: 11.85 };
    page.run(`state.current = ${JSON.stringify(hit)}`);
    win.setCut(9.7, 11.85);
    win.reapplyVoiceSnap(page.get("state.current"));
    expect(video.currentTime).toBe(10.0);
    expect(page.get("state.cutIn")).toBe(10.0);
    expect(page.get("state.cutOut")).toBe(12.0);
  });

  it("文字起こしが在る録画でだけ声の判定を作りに行く", async () => {
    // 初回は音声を丸ごと読む。寄せる秒が無い録画(文字起こし無し)まで作らせない。
    page.run("window.__asked = [];");
    page.run("apiSend = (m, url) => { window.__asked.push(url); return Promise.resolve("
             + "url.indexOf('/transcript') >= 0 ? { segments: [{ start: 1, end: 2, text: 'あ' }] }"
             + " : { spans: [] }); };");
    await win.loadTranscript(1);
    await page.settle();
    expect(win.__asked.some((url) => url.indexOf("/voice") >= 0)).toBe(true);

    page.run("window.__asked = [];");
    page.run("apiSend = (m, url) => { window.__asked.push(url); return Promise.resolve("
             + "url.indexOf('/transcript') >= 0 ? { segments: [] } : { spans: [] }); };");
    await win.loadTranscript(1);
    await page.settle();
    expect(win.__asked.some((url) => url.indexOf("/voice") >= 0)).toBe(false);
    expect(page.get("state.voiceSpans")).toEqual([]);
  });

  it("既に先へ進んでいたら再生位置は戻さない", () => {
    spans();
    const video = fakeVideo(30.0);
    const hit = { recording_id: 1, source: "stt", video_time: 9.7, end_time: 11.85 };
    page.run(`state.current = ${JSON.stringify(hit)}`);
    win.reapplyVoiceSnap(page.get("state.current"));
    expect(video.currentTime).toBe(30.0);
  });
});

// 意味検索の1行は約25秒のpassage(複数文の束)で、行を開くと当たった文の十数秒手前へ飛ぶ。
// 本文を1文ずつ押せるようにして、文そのものへ飛べるようにした部分。
describe("videos.js の意味検索passage", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "videos", url: "http://localhost:8520/videos" });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const passage = {
    id: 11, source: "stt", recording_id: 1, unique_id: "alice", started_at: 1.0,
    video_time: 100.0, end_time: 125.0, hit_ids: [11, 12, 13],
    body: "あ\nい\nう", snippet: "あ\nい\nう",
  };

  it("本文は1文ずつ押せる要素になる", () => {
    const node = win.passageNode(passage);
    const sentences = node.querySelectorAll(".vd-sent");
    expect(Array.from(sentences).map((el) => el.textContent)).toEqual(["あ", "い", "う"]);
    expect(Array.from(sentences).map((el) => el.dataset.hitId)).toEqual(["11", "12", "13"]);
  });

  it("行数とid数が食い違うpassageは文に割らない", () => {
    // 割ると押した文と飛ぶ先が別物になる。段落のまま出して従来どおり先頭へ飛ばす。
    const node = win.passageNode({ ...passage, hit_ids: [11, 12] });
    expect(node.querySelectorAll(".vd-sent").length).toBe(0);
    expect(node.textContent).toBe("あ\nい\nう");
  });

  it("文を押すとその文の秒をDBから引き直して開く", async () => {
    const opened = [];
    page.run("openHit = (hit) => { window.__opened = hit; return Promise.resolve(); }");
    page.run(
      "apiSend = (method, url) => { window.__asked = url;"
      + " return Promise.resolve({ items: [{ id: 12, source: 'stt', recording_id: 1,"
      + " video_time: 117.5, end_time: 119.0, body: 'い' }] }); }",
    );
    await win.openSentence(passage, 12, 0);
    expect(win.__asked).toBe("/api/search/hits?ids=12");
    const hit = win.__opened;
    expect(hit.video_time).toBe(117.5);
    expect(hit.end_time).toBe(119.0);
    // passageの束ねは持ち越さない(開いた先は1文であってpassageではない)。
    expect(hit.hit_ids).toBe(null);
    expect(opened.length).toBe(0);
  });

  it("indexが指す行が消えていたら先頭へ飛ばさずに知らせる", async () => {
    const shown = [];
    page.run("showError = (err, title) => { window.__err = String(err.message || err); }");
    page.run("openHit = () => { window.__opened = true; return Promise.resolve(); };"
             + " window.__opened = false;");
    page.run("apiSend = () => Promise.resolve({ items: [] });");
    await win.openSentence(passage, 12, 0);
    expect(win.__opened).toBe(false);
    expect(win.__err).toContain("検索indexにもうありません");
    expect(shown.length).toBe(0);
  });
});
