import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 出力済みclipの画面と、切り出しが「どこへ出たか」を名乗る経路。
//
// この機能の事故は必ず「作ったのに見つからない」形で出る。成果物はDBに行を持たず、置き場は
// 配信者folderの下(<root>/<配信者>/_clips/)で、録画を最終保存先へ移すと随伴するため一時
// 保存先と最終保存先へ散らばる。画面が片方しか出さない・出力先を言わない・queueへ載っただけ
// なのに出来たと言う、のいずれも操作の直後は正常に見える。
describe("videos.js の出力済みclip", () => {
  let page;
  let win;
  let doc;
  let errorSpy;
  let calls;

  const CLIPS = {
    roots: [
      { key: "work", label: "一時保存先", path: "C:\\rec", exists: true,
        count: 1, bytes: 100, leftover_count: 1, leftover_bytes: 500 },
      { key: "final", label: "最終保存先", path: "K:\\rec", exists: true,
        count: 1, bytes: 200, leftover_count: 0, leftover_bytes: 0 },
    ],
    items: [
      { root: "final",
        name: "alice/_clips/00002_alice_20260101_000000_000030-000045_歓声.mp4",
        filename: "00002_alice_20260101_000000_000030-000045_歓声.mp4",
        unique_id: "alice", stem: "00002_alice_20260101_000000", kind: "clip",
        start: 30, end: 45, label: "歓声", parts: null, recording_id: 2,
        recording_started_at: 100, bytes: 200, modified_at: 2000,
        path: "K:\\rec\\alice\\_clips\\00002_alice_20260101_000000_000030-000045_歓声.mp4",
        url: "/api/clips/file?root=final&name=alice%2F_clips%2Fx.mp4" },
      { root: "work",
        name: "bob/_clips/00001_bob_20260101_000000_000010-000020.overlay.mp4",
        filename: "00001_bob_20260101_000000_000010-000020.overlay.mp4",
        unique_id: "bob", stem: "00001_bob_20260101_000000", kind: "overlay",
        start: 10, end: 20, label: "", parts: null, recording_id: null,
        recording_started_at: null, bytes: 100, modified_at: 1000,
        path: "C:\\rec\\bob\\_clips\\00001_bob_20260101_000000_000010-000020.overlay.mp4",
        url: "/api/clips/file?root=work&name=bob%2F_clips%2Fy.mp4" },
    ],
    total_bytes: 300,
  };

  function open(routes) {
    calls = [];
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: {
        "/api/clips": (call) => {
          calls.push(call.url);
          return CLIPS;
        },
        ...routes,
      },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    return page.settle();
  }

  beforeEach(async () => {
    await open();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const showClips = async () => {
    win.showView("clips");
    await page.settle();
  };
  const rows = () => Array.from(doc.querySelectorAll("#clips-rows tr"))
    .map((tr) => Array.from(tr.querySelectorAll("td")).map((td) => td.textContent));

  it("両方の保存先の成果物を1つの表に並べる", async () => {
    await showClips();
    // 新しい順。出来上がりの確認は直前に出したものから始まる。
    expect(rows().map((cells) => cells[0])).toEqual(["alice", "bob"]);
    expect(rows()[0][1]).toContain("歓声");
    expect(rows()[0][2]).toBe("切り出し");
    expect(rows()[1][2]).toBe("焼き込み切り抜き");
    expect(rows()[0][8]).toBe("最終保存先");
    expect(rows()[1][8]).toBe("一時保存先");
  });

  it("保存先ごとの内訳と、落ちた回の残骸を分けて出す", async () => {
    await showClips();
    const chips = Array.from(doc.querySelectorAll("#clips-roots span"))
      .map((el) => el.textContent);
    expect(chips[0]).toContain("一時保存先: 1件");
    // 中間dirの残骸は成果物ではない。件数として別に出す(成果物へ混ぜると容量が嘘になる)。
    expect(chips[0]).toContain("中間fileの残骸 1件");
    expect(chips[1]).toContain("最終保存先: 1件");
    expect(chips[1]).not.toContain("残骸");
  });

  it("実pathを行のtooltipに載せる(NLEへ渡す実体はこれ)", async () => {
    await showClips();
    const name = doc.querySelector("#clips-rows td:nth-child(2) span");
    expect(name.title).toBe(CLIPS.items[0].path);
  });

  it("種別で絞れる(焼き込み切り抜きだけを見る)", async () => {
    await showClips();
    doc.getElementById("clips-kind").value = "overlay";
    doc.getElementById("clips-kind").dispatchEvent(new win.Event("change"));
    await page.settle();
    expect(rows().map((cells) => cells[0])).toEqual(["bob"]);
  });

  it("視聴はserverが組み立てたURLをそのまま使う(符号化を画面側で作り直さない)", async () => {
    await showClips();
    doc.querySelector("#clips-rows tr td:last-child button").click();
    await page.settle();
    expect(doc.getElementById("clip-file-video").getAttribute("src"))
      .toBe(CLIPS.items[0].url);
    expect(doc.getElementById("clip-file-play").classList.contains("hidden")).toBe(false);
  });

  it("開くたびに実物を見に行く(消えたfileが残って見えない)", async () => {
    await showClips();
    expect(calls.length).toBe(1);
    win.showView("search");
    await showClips();
    expect(calls.length).toBe(2);
  });

  it("取得できなかった時に0件と言わない", async () => {
    await page.close();
    errorSpy.mockRestore();
    await open({ "/api/clips": () => { throw new Error("boom"); } });
    await showClips();
    const empty = doc.getElementById("clips-empty");
    expect(empty.classList.contains("list-failed")).toBe(true);
    expect(empty.textContent).toContain("取得できませんでした");
  });
});

// 単発の切り出しは、素材版によって「その場で切る」経路と「GPUのqueueへ載せる」経路に
// 分かれる。応答の形が経路で変わるので、画面はrouteで分岐しなければならない。分岐が無かった
// 頃は焼き込みを選ぶと「出力: undefined」と表示され、完了も一切出なかった。
describe("videos.js の単発切り出し", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  async function open(clipResponse) {
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: {
        "POST /api/recordings/1/clip": () => clipResponse,
      },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
    // IN/OUTと開いている録画が揃っていないとbuttonは押せない(runClipが即returnする)。
    page.get("state").current = { recording_id: 1, unique_id: "alice" };
    page.get("state").cutIn = 10;
    page.get("state").cutOut = 20;
  }

  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  it("その場で切れた時は出力pathを出す", async () => {
    await open({ route: "copy", path: "K:\\rec\\alice\\_clips\\a.mp4",
                 filename: "a.mp4", keyframe_lead_seconds: 0,
                 actual_start_seconds: 10 });
    await win.runClip();
    await page.settle();
    expect(doc.getElementById("player-status").textContent)
      .toContain("K:\\rec\\alice\\_clips\\a.mp4");
  });

  it("queueへ載っただけの時は出来たと言わない(pathはまだ無い)", async () => {
    await open({ route: "render", job_id: "abcd", kind: "clip_overlay", state: "pending" });
    await win.runClip();
    await page.settle();
    const status = doc.getElementById("player-status").textContent;
    expect(status).toContain("順番待ち");
    expect(status).not.toContain("undefined");
  });

  it("焼き込み切り抜きの完了を受け取って出力先を出す", async () => {
    await open({ route: "render", job_id: "abcd" });
    win.onMessage({
      type: "job_update",
      job: { job_id: "abcd", domain: "clip_overlay", state: "completed",
             result: { output_path: "K:\\rec\\alice\\_clips\\a.overlay.mp4" } },
    });
    expect(doc.getElementById("player-status").textContent)
      .toContain("K:\\rec\\alice\\_clips\\a.overlay.mp4");
  });
});

// スクショ。押した瞬間は成果物がまだ無く(queueへ載るだけ)、出来上がりは数秒後にjob_updateで
// 届く。押した側の状態欄しか見ていなかった切り抜きと同じ事故(「出力: undefined」・完了が
// どこにも出ない)を繰り返さないための最小限を守る。
describe("videos.js のスクショ", () => {
  let page;
  let win;
  let doc;
  let errorSpy;
  let posted;

  beforeEach(async () => {
    posted = [];
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: {
        "POST /api/recordings/1/still": (call) => {
          posted.push(JSON.parse(call.init.body));
          return { job_id: "ee01", kind: "still", state: "pending" };
        },
      },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
    page.get("state").current = { recording_id: 1, unique_id: "alice" };
  });

  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  it("範囲が無くても撮れる(1 frameが成果物で、IN/OUTは要らない)", async () => {
    page.get("state").cutIn = null;
    page.get("state").cutOut = null;
    // jsdomの<video>は currentTime を常に0で返すので、位置は差し替えて与える。
    Object.defineProperty(doc.getElementById("video"), "currentTime",
      { value: 12.34, configurable: true });
    win.runStill();
    await page.settle();
    expect(posted.length).toBe(1);
    expect(posted[0].at).toBeCloseTo(12.34, 2);
    // 素材版は「今再生している版」。選択中の版がこの録画に無ければ元録画が再生されており、
    // その絵が保存される。
    expect(posted[0].variant).toBe("source");
  });

  it("押した直後に出来たと言わない(pathはまだ無い)", async () => {
    win.runStill();
    await page.settle();
    const status = doc.getElementById("player-status").textContent;
    expect(status).toContain("スクショ");
    expect(status).not.toContain("undefined");
  });

  it("完了を受け取って出力先を出す", async () => {
    win.runStill();
    await page.settle();
    win.onMessage({
      type: "job_update",
      job: { job_id: "ee01", domain: "still", state: "completed",
             result: { output_path: "K:\\rec\\alice\\_clips\\a_shot00001234.png" } },
    });
    expect(doc.getElementById("player-status").textContent)
      .toContain("K:\\rec\\alice\\_clips\\a_shot00001234.png");
  });

  it("失敗を黙って捨てない", async () => {
    win.runStill();
    await page.settle();
    win.onMessage({
      type: "job_update",
      job: { job_id: "ee01", domain: "still", state: "failed",
             message: "この位置に映像がありません（12.34秒）。" },
    });
    expect(doc.getElementById("player-status").textContent).toContain("映像がありません");
  });
});
