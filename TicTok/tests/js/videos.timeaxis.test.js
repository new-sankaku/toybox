import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 時間軸と「並び順の対応」。この画面の事故はどちらも**画面が黙って嘘をつく**形で出る。
// 表示が消えれば気付くが、別の位置のthumbnailが出る・別のコメントに★が付く・
// 無い素材版が選べてしまう、といったズレはそれらしく描かれるので気付かれない。
describe("videos.js の時間軸と対応付け", () => {
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

  const state = () => page.get("state");

  /** jsdom は layout を持たないので、bar の矩形は test が与える。 */
  function layoutHeat({ left = 0, width = 200, top = 0, height = 60 } = {}) {
    doc.getElementById("heat").getBoundingClientRect = () => ({
      left, top, width, height, right: left + width, bottom: top + height, x: left, y: top,
    });
  }

  function setDuration(seconds) {
    Object.defineProperty(doc.getElementById("video"), "duration", {
      configurable: true,
      get: () => seconds,
    });
  }

  describe("secondsFromClientX", () => {
    beforeEach(() => layoutHeat({ left: 100, width: 200 }));

    it("barの位置を尺へ線形に写す", () => {
      setDuration(100);
      expect(win.secondsFromClientX(100)).toBe(0);
      expect(win.secondsFromClientX(150)).toBe(25);
      expect(win.secondsFromClientX(300)).toBe(100);
    });

    it("barの外はclampする(負の秒・尺超えのseekを作らない)", () => {
      setDuration(100);
      expect(win.secondsFromClientX(0)).toBe(0);
      expect(win.secondsFromClientX(9999)).toBe(100);
    });

    it("尺が分かる前は秒を作らない(0秒と読ませない)", () => {
      setDuration(NaN);
      expect(win.secondsFromClientX(150)).toBeNull();
      setDuration(0);
      expect(win.secondsFromClientX(150)).toBeNull();
      setDuration(Infinity);
      expect(win.secondsFromClientX(150)).toBeNull();
    });
  });

  // sprite の何枚目を出すかは秒から導く。ここがずれると、bar上の位置と別の場面の
  // thumbnailが出る。絵は出ているので誤りに見えない。
  describe("showThumb の sprite index", () => {
    const SPEC = {
      count: 12,
      interval_seconds: 10,
      columns: 5,
      tile_width: 160,
      tile_height: 90,
      url: "/api/x/sprite.jpg",
    };

    beforeEach(() => {
      layoutHeat({ left: 0, width: 1200 });
      setDuration(120);
      state().sprite = SPEC;
      // thumb の収まり計算が親の矩形を読む。
      doc.getElementById("thumb").parentElement.getBoundingClientRect = () => ({
        left: 0, top: 0, width: 1200, height: 80, right: 1200, bottom: 80, x: 0, y: 0,
      });
    });

    const posOf = () => doc.getElementById("thumb-img").style.backgroundPosition;

    it("秒 → 何枚目 → 行と列 を対応させる", () => {
      // 25秒 = 3枚目(index 2) = 1行目の3列目。
      win.showThumb(250);
      expect(posOf()).toBe("-320px 0px");
      expect(doc.getElementById("thumb-time").textContent).toBe("00:00:25");

      // 63秒 = 7枚目(index 6) = 2行目の2列目。
      win.showThumb(630);
      expect(posOf()).toBe("-160px -90px");
      expect(doc.getElementById("thumb-time").textContent).toBe("00:01:03");
    });

    it("最後の1枚を超える位置は最終枚へclampする(空tileを出さない)", () => {
      win.showThumb(1200); // 尺の右端
      // index 11 = 3行目の2列目。
      expect(posOf()).toBe("-160px -180px");
    });

    it("spriteが無い録画ではthumbを出さない", () => {
      state().sprite = null;
      win.showThumb(250);
      expect(doc.getElementById("thumb").classList.contains("hidden")).toBe(true);
    });

    it("尺が分かる前はthumbを出さない", () => {
      setDuration(NaN);
      win.showThumb(250);
      expect(doc.getElementById("thumb").classList.contains("hidden")).toBe(true);
    });
  });

  describe("setCut", () => {
    beforeEach(() => {
      layoutHeat();
      setDuration(600);
      state().current = { recording_id: 1 };
    });

    it("IN/OUTと尺を同じ書式で出し、出力buttonを開ける", () => {
      win.setCut(10, 25);
      expect(doc.getElementById("cut-in").textContent).toBe("00:00:10");
      expect(doc.getElementById("cut-out").textContent).toBe("00:00:25");
      expect(doc.getElementById("cut-len").textContent).toBe("尺 00:00:15");
      expect(doc.getElementById("do-clip").disabled).toBe(false);
      expect(doc.getElementById("add-cut").disabled).toBe(false);
    });

    it("OUTがINより前なら尺を出さず理由を出す(負の尺で投入させない)", () => {
      win.setCut(25, 10);
      expect(doc.getElementById("cut-len").textContent).toBe("OUTがINより前です");
      expect(doc.getElementById("do-clip").disabled).toBe(true);
    });

    it("IN==OUT は0秒の切り出しなので通さない", () => {
      win.setCut(10, 10);
      expect(doc.getElementById("cut-len").textContent).toBe("OUTがINより前です");
      expect(doc.getElementById("do-clip").disabled).toBe(true);
    });

    it("未設定は --:--:-- のままで、尺は - ", () => {
      win.setCut(null, null);
      expect(doc.getElementById("cut-in").textContent).toBe("--:--:--");
      expect(doc.getElementById("cut-out").textContent).toBe("--:--:--");
      expect(doc.getElementById("cut-len").textContent).toBe("-");
      expect(doc.getElementById("do-clip").disabled).toBe(true);
    });

    it("録画を開いていなければ範囲が正しくても投入できない", () => {
      state().current = null;
      win.setCut(10, 25);
      expect(doc.getElementById("do-clip").disabled).toBe(true);
    });

    it("stateへも同じ値を書く(画面とstateが食い違わない)", () => {
      win.setCut(10, 25);
      expect(state().cutIn).toBe(10);
      expect(state().cutOut).toBe(25);
    });
  });

  // 切り出しの指定はシーン検索側と切り出しリスト側の2組のDOMに出る。値は1組しか
  // 持たないので、写し漏れると「正規化したつもりの一括が素のまま走る」ことになる。
  describe("切り出し指定の二重DOM同期", () => {
    it("primaryを変えるとmirrorへ写る", () => {
      doc.getElementById("clip-normalize").checked = true;
      win.syncClipControls(false);
      expect(doc.getElementById("cuts-normalize").checked).toBe(true);
    });

    it("mirrorを変えるとprimaryへ写る", () => {
      doc.getElementById("cuts-normalize").checked = true;
      win.syncClipControls(true);
      expect(doc.getElementById("clip-normalize").checked).toBe(true);
    });

    it("clipOptions は3つの指定をすべて載せる(取りこぼすと既定値で走る)", () => {
      const opts = win.clipOptions();
      expect(Object.keys(opts).sort()).toEqual(["mode", "normalize_audio", "variant"]);
    });

    it("clipOptions はprimary側の現在値を返す", () => {
      doc.getElementById("clip-normalize").checked = true;
      expect(win.clipOptions().normalize_audio).toBe(true);
      doc.getElementById("clip-normalize").checked = false;
      expect(win.clipOptions().normalize_audio).toBe(false);
    });
  });

  describe("素材版の可否", () => {
    it("持っていない版は選べなくし、理由をtooltipに出す", () => {
      state().variantKinds = ["source"];
      win.applyVariantAvailability();
      const items = Array.from(doc.querySelectorAll("#clip-variant .seg-item"));
      const source = items.find((b) => b.dataset.value === "source");
      const overlay = items.find((b) => b.dataset.value === "overlay");
      expect(source.disabled).toBe(false);
      expect(source.title).toBe("");
      expect(overlay.disabled).toBe(true);
      expect(overlay.title).toContain("ありません");
    });

    it("持っている版はすべて開ける", () => {
      state().variantKinds = ["source", "overlay", "upscaled"];
      win.applyVariantAvailability();
      const disabled = Array.from(doc.querySelectorAll("#clip-variant .seg-item"))
        .filter((b) => b.disabled)
        .map((b) => b.dataset.value);
      expect(disabled).toEqual([]);
    });

    it("録画に無い版が選ばれていたら再生は元録画へ落とす", () => {
      state().variantKinds = ["source"];
      doc.getElementById("clip-variant").value = "overlay";
      expect(win.playbackVariant()).toBe("source");
    });

    it("録画にある版はそのまま再生する", () => {
      state().variantKinds = ["source", "overlay"];
      doc.getElementById("clip-variant").value = "overlay";
      expect(win.playbackVariant()).toBe("overlay");
    });
  });

  // 見どころ側の source_hit_id とコメント行の id の対応だけで★を塗る。
  // 時刻の近さで推測すると、同じ秒の別コメントに付く。
  describe("コメント★の対応付け", () => {
    it("記録済みのhit idだけを集める", () => {
      state().bookmarks = [
        { source_hit_id: 11 },
        { source_hit_id: 22 },
        { source_hit_id: null },
        {},
      ];
      expect([...win.markedHitIds()].sort()).toEqual([11, 22]);
    });

    it("id が 0 の見どころを落とさない(0は偽値だが実在するid)", () => {
      state().bookmarks = [{ source_hit_id: 0 }];
      expect([...win.markedHitIds()]).toEqual([0]);
    });

    it("見どころが未取得でも落ちない", () => {
      state().bookmarks = null;
      expect([...win.markedHitIds()]).toEqual([]);
    });

    it("★は行の順番ではなくidで決まる", () => {
      state().comments = [
        { id: 10, t: 5, nickname: "a", body: "one" },
        { id: 20, t: 6, nickname: "b", body: "two" },
        { id: 30, t: 7, nickname: "c", body: "three" },
      ];
      state().bookmarks = [{ source_hit_id: 20 }];
      win.renderComments();
      const on = Array.from(doc.querySelectorAll("#comments .vd-cmt-mark")).map((b) =>
        b.classList.contains("vd-cmt-mark-on"),
      );
      expect(on).toEqual([false, true, false]);
    });

    it("★の切り替えでaria-pressedとtooltipも一致する", () => {
      state().comments = [{ id: 10, t: 5, body: "x" }];
      state().bookmarks = [{ source_hit_id: 10 }];
      win.renderComments();
      const mark = doc.querySelector("#comments .vd-cmt-mark");
      expect(mark.getAttribute("aria-pressed")).toBe("true");
      expect(mark.title).toBe("見どころから外す");

      state().bookmarks = [];
      win.syncCommentMarks();
      expect(mark.getAttribute("aria-pressed")).toBe("false");
      expect(mark.title).toBe("この位置を見どころに記録");
    });

    it("行数よりコメントが少なくなっても落ちない", () => {
      state().comments = [{ id: 1, t: 0, body: "a" }, { id: 2, t: 1, body: "b" }];
      state().bookmarks = [];
      win.renderComments();
      state().comments = [{ id: 1, t: 0, body: "a" }];
      expect(() => win.syncCommentMarks()).not.toThrow();
    });

    it("コメント行の時刻は再生時刻と同じ書式で出す", () => {
      state().comments = [{ id: 1, t: 3661, body: "a" }];
      state().bookmarks = [];
      win.renderComments();
      expect(doc.querySelector("#comments .vd-seg-t").textContent).toBe("01:01:01");
    });
  });

  describe("chapterExportUrl", () => {
    it("開いている録画のidと書式をURLへ載せる", () => {
      state().current = { recording_id: 42 };
      expect(win.chapterExportUrl("txt")).toBe("/api/recordings/42/chapters/export?format=txt");
      expect(win.chapterExportUrl("vtt")).toBe("/api/recordings/42/chapters/export?format=vtt");
    });
  });
});
