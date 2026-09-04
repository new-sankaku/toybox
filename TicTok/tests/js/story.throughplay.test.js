import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 出力tabの**通し再生**。1本のmp4は3〜8個の窓を繋いだ物で、その窓は素材ごとに別のfileに
// 在る(montage)。ここで縛るのは「順番どおりに、その窓だけを、1つも飛ばさずに流す」という
// 1点だけである。
//
// 実際に起きていた3つの壊れ方を、そのままの形で置いてある:
//
// (1) **窓が丸ごと飛ぶ。** 送っている最中にも時刻のtickは走り、その値は前の窓の位置である。
//     それを次の窓の終わりと比べると、前の窓の方が後ろに在るだけで次の窓が「もう終わった」
//     ことになる。実測(あきと🐢💤 / 3窓)では2本目 Strong Finish が 36.3〜43.8秒、3本目
//     Rocket Game が 6.8〜12.9秒で、43.8 > 12.9 のため3本目が一度も映らなかった。
//
// (2) **シークバーを掴むと秒が飛び回る。** 掴んだ位置を窓の頭へ送り返すと、送り返した先が
//     次の窓の終わりを越えていて(1)が連鎖し、窓が次々に送られる。
//
// (3) **窓の終わりを行き過ぎる。** timeupdateは1秒に4回ほどしか来ない。montageの繋ぎ目は
//     音の境目の手前から映像の演出が始まるので、行き過ぎた分には次のgiftの場面が映る。
describe("story.js 出力tabの通し再生", () => {
  let page;
  let win;
  let doc;

  // あきと🐢💤 の実データ(recordings/.../260829-260905_coin19380_あきと🐢💤_story.mp4.json
  // と highlight_segments)そのままの3窓。素材は3本とも別のfileである。
  const CHAPTERS = [
    { no: 1, url: "/api/highlights/2/media", start: 15.064, end: 21.757,
      coin: 6000, label: "Goal Highlight", source: "hl2.mp4" },
    { no: 2, url: "/api/highlights/8/media", start: 37.259, end: 43.75,
      coin: 6000, label: "Strong Finish", source: "hl8.mp4" },
    { no: 3, url: "/api/highlights/3/media", start: 7.403, end: 12.91,
      coin: 399, label: "Rocket Game", source: "hl3.mp4" },
  ];

  // jsdom の <video> は読み込みを持たない。currentTime の代入も seeking も無いので、
  // test から動かせる形にしておく。
  function playableVideo(win_) {
    let at = 0;
    Object.defineProperty(win_.HTMLMediaElement.prototype, "readyState",
      { get: () => 3, configurable: true });
    Object.defineProperty(win_.HTMLMediaElement.prototype, "currentTime",
      { get: () => at, set: (v) => { at = v; }, configurable: true });
    Object.defineProperty(win_.HTMLMediaElement.prototype, "seeking",
      { get: () => false, configurable: true });
  }

  const video = () => doc.getElementById("ex-video");
  const runIndex = () => page.run("state.run ? state.run.index : null");
  const runNote = () => doc.getElementById("ex-run-note").textContent;

  // 窓の頭の読み込みが終わった、を模す。runStep は src を差し替えて loadedmetadata を待つ。
  const loaded = () => video().dispatchEvent(new win.Event("loadedmetadata"));
  const at = (seconds) => { video().currentTime = seconds; };
  const tick = () => video().dispatchEvent(new win.Event("timeupdate"));
  const seeked = () => video().dispatchEvent(new win.Event("seeked"));
  // 窓の送りは SEQUENCE_STEP_MS だけ待ってから始まる(seekの着地待ち)。**実時間で待つ** ――
  // 溜めて送る仕組みそのものがtestの相手なので、timerを差し替えて飛ばすと確かめられない。
  // 固定の秒数で待たずに条件が立つまで見るのは、待ち時間の見積もりでtestが揺れないため。
  const step = async (done) => {
    for (let i = 0; i < 40; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 25));
      await page.settle();
      if (done()) return;
    }
    throw new Error("窓が送られませんでした");
  };

  // 1つの窓を頭から終わりまで流す。読み込み → 頭へ着地 → 終わりまで進む、の順。
  async function playThrough(chapter, index) {
    loaded();
    at(chapter.start);
    seeked();
    tick();
    at(chapter.end);
    tick();
    // 送っている間も時刻のtickは走り、その値は**この窓の位置**である。
    tick();
    tick();
    await step(() => runIndex() !== index);
  }

  async function start(mode = "all") {
    page.run(`startRun("あきと", ${JSON.stringify(CHAPTERS)}, ${JSON.stringify(mode)})`);
    await page.settle();
  }

  beforeEach(async () => {
    page = loadPage({ page: "story", routes: {}, before: playableVideo });
    win = page.win;
    doc = page.document;
    await page.settle();
    doc.getElementById("tab-export").click();
    await page.settle();
  });

  afterEach(async () => {
    if (page) await page.close();
  });

  it("窓を1つも飛ばさずに順番どおり流す(前の窓の位置で次の窓を判定しない)", async () => {
    await start();
    expect(runIndex()).toBe(0);
    expect(video().getAttribute("src")).toBe(CHAPTERS[0].url);

    await playThrough(CHAPTERS[0], 0);
    expect(runIndex()).toBe(1);
    expect(video().getAttribute("src")).toBe(CHAPTERS[1].url);

    // **ここが飛んでいた。** 2本目の終わり(43.75秒)は3本目の終わり(12.91秒)より後ろなので、
    // 送っている最中のtickをそのまま読むと3本目が「もう終わった」ことになる。
    await playThrough(CHAPTERS[1], 1);
    expect(runIndex()).toBe(2);
    expect(video().getAttribute("src")).toBe(CHAPTERS[2].url);
    expect(runNote()).toContain("Rocket Game");

    await playThrough(CHAPTERS[2], 2);
    expect(page.run("state.run")).toBeNull();
    expect(runNote()).toBe("終わり");
  });

  it("窓の頭へ着く前のtickでは送らない(読み込み中の0秒で次へ行かない)", async () => {
    await start();
    // src を差し替えた直後。位置は0秒で、窓(15.064〜21.757秒)の中ではない。
    at(0);
    tick();
    tick();
    await new Promise((resolve) => setTimeout(resolve, 200));
    await page.settle();
    expect(runIndex()).toBe(0);
  });

  it("シークバーで窓の中へ移ったら、その窓へ印を移して続ける(頭へ送り返さない)", async () => {
    await start();
    loaded();
    at(CHAPTERS[0].start);
    seeked();

    // 人が2本目の中(40秒)へ掴んで移った。src も人が選んだ章から変わっている。
    video().src = CHAPTERS[1].url;
    at(40.0);
    seeked();
    await page.settle();
    expect(runIndex()).toBe(1);
    expect(runNote()).toContain("Strong Finish");
    // 掴んだ位置のまま。窓の頭へ送り返していない。
    expect(video().currentTime).toBe(40.0);

    // そこから窓の終わりまで流せば、次の窓へ進む。
    at(CHAPTERS[1].end);
    tick();
    await step(() => runIndex() === 2);
    expect(runIndex()).toBe(2);
  });

  it("シークバーでどの窓にも入らない場所へ移ったら、通し再生を止める", async () => {
    await start();
    loaded();
    at(CHAPTERS[0].start);
    seeked();

    at(3.0);            // 1本目の窓(15.064〜21.757秒)の外
    seeked();
    await page.settle();
    expect(page.run("state.run")).toBeNull();
    expect(runNote()).toContain("止めました");
    // 掴んだ場所はそのまま。送り返さない。
    expect(video().currentTime).toBe(3.0);
  });

  it("こちらが送った着地は人のseekと取り違えない", async () => {
    await start();
    loaded();
    at(CHAPTERS[0].start);
    seeked();
    await page.settle();
    expect(runIndex()).toBe(0);
    expect(page.run("state.run.seekTo")).toBeNull();
  });
});
