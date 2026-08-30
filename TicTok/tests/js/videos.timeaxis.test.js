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
  function layoutBar(id, { left = 0, width = 200, top = 0, height = 60 } = {}) {
    const rect = {
      left, top, width, height, right: left + width, bottom: top + height, x: left, y: top,
    };
    const el = doc.getElementById(id);
    el.getBoundingClientRect = () => rect;
    // content boxを基準に換算するので、border無しのbarとして clientLeft/Width も与える。
    Object.defineProperty(el, "clientLeft", { configurable: true, get: () => 0 });
    Object.defineProperty(el, "clientWidth", { configurable: true, get: () => width });
    return el;
  }

  function layoutHeat(box) {
    return layoutBar("heat", box);
  }

  function setDuration(seconds) {
    Object.defineProperty(doc.getElementById("video"), "duration", {
      configurable: true,
      get: () => seconds,
    });
  }

  /** jsdom の <video> は currentTime を実装しないので、値を持つだけの property に置き換える。 */
  function setCurrentTime(seconds) {
    Object.defineProperty(doc.getElementById("video"), "currentTime", {
      configurable: true,
      writable: true,
      value: seconds,
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

    /** thumb の収まり計算が親(wrapper)の矩形を読む。 */
    function layoutWrap(id, width) {
      doc.getElementById(id).parentElement.getBoundingClientRect = () => ({
        left: 0, top: 0, width, height: 80, right: width, bottom: 80, x: 0, y: 0,
      });
    }

    beforeEach(() => {
      layoutHeat({ left: 0, width: 1200 });
      layoutBar("zoom", { left: 0, width: 1200, top: 100, height: 60 });
      setDuration(120);
      state().sprite = SPEC;
      layoutWrap("heat", 1200);
      layoutWrap("zoom", 1200);
    });

    const posOf = () => doc.getElementById("thumb-img").style.backgroundPosition;

    it("秒 → 何枚目 → 行と列 を対応させる", () => {
      // 25秒 = 3枚目(index 2) = 1行目の3列目。
      win.showThumb("heat", 250);
      expect(posOf()).toBe("-320px 0px");
      expect(doc.getElementById("thumb-time").textContent).toBe("00:00:25");

      // 63秒 = 7枚目(index 6) = 2行目の2列目。
      win.showThumb("heat", 630);
      expect(posOf()).toBe("-160px -90px");
      expect(doc.getElementById("thumb-time").textContent).toBe("00:01:03");
    });

    it("最後の1枚を超える位置は最終枚へclampする(空tileを出さない)", () => {
      win.showThumb("heat", 1200); // 尺の右端
      // index 11 = 3行目の2列目。
      expect(posOf()).toBe("-160px -180px");
    });

    it("spriteが無い録画ではthumbを出さない", () => {
      state().sprite = null;
      win.showThumb("heat", 250);
      expect(doc.getElementById("thumb").classList.contains("hidden")).toBe(true);
    });

    it("尺が分かる前はthumbを出さない", () => {
      setDuration(NaN);
      win.showThumb("heat", 250);
      expect(doc.getElementById("thumb").classList.contains("hidden")).toBe(true);
    });

    // 拡大窓は全尺barと換算が違う(窓の始点+割合)。同じx座標でも別の秒になるので、
    // 全尺barの換算を使い回すと、bar上の位置と別の場面のthumbnailが出る。
    it("拡大窓では窓の秒でtileを選ぶ(全尺barの換算を使わない)", () => {
      state().zoomStart = 60;
      state().zoomSpan = 60; // 窓は60〜120秒
      // 中央(x:600) = 90秒 = 10枚目(index 9) = 2行目の5列目。
      win.showThumb("zoom", 600);
      expect(posOf()).toBe("-640px -90px");
      expect(doc.getElementById("thumb-time").textContent).toBe("00:01:30");
      expect(doc.getElementById("thumb").classList.contains("hidden")).toBe(false);
    });

    // thumbは1つしか無いので、出す先のwrapperへ移してから位置を決める。移していないと
    // 全尺barのwrapperの中で「拡大窓の高さぶん上」に置かれ、絵が別のbarの上に出る。
    it("thumbは出したbarのwrapperへ移る", () => {
      win.showThumb("zoom", 600);
      expect(doc.getElementById("thumb").parentElement)
        .toBe(doc.getElementById("zoom").parentElement);
      win.showThumb("heat", 250);
      expect(doc.getElementById("thumb").parentElement)
        .toBe(doc.getElementById("heat").parentElement);
    });

    it("拡大窓でも尺が分かる前はthumbを出さない", () => {
      setDuration(NaN);
      win.showThumb("zoom", 600);
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
      // IN/OUT欄は手打ちできるinputなので、値はvalueへ入る(0.1秒桁つき)。
      expect(doc.getElementById("cut-in").value).toBe("00:00:10.0");
      expect(doc.getElementById("cut-out").value).toBe("00:00:25.0");
      expect(doc.getElementById("cut-len").textContent).toBe("尺 00:00:15");
      expect(doc.getElementById("do-clip").disabled).toBe(false);
      // 記録の口は1つで、IN/OUTが立っていれば尺つきで入ると自分で名乗る。
      const add = doc.getElementById("add-mark");
      expect(add.disabled).toBe(false);
      expect(add.textContent).toBe("見どころ記録（尺あり）");
    });

    it("OUTがINより前なら尺を出さず理由を出す(負の尺で投入させない)", () => {
      win.setCut(25, 10);
      expect(doc.getElementById("cut-len").textContent).toBe("OUTがINより前です");
      expect(doc.getElementById("do-clip").disabled).toBe(true);
    });

    // 等値は逆転ではない。上端laneをdragせずclickするとpointerdownがIN=OUTを置くので、
    // ここで「OUTがINより前です」と出すと、seekのつもりで押しただけで叱られる。
    it("IN==OUT は0秒の切り出しなので通さない", () => {
      win.setCut(10, 10);
      expect(doc.getElementById("cut-len").textContent).toBe("範囲が0です");
      expect(doc.getElementById("do-clip").disabled).toBe(true);
    });

    it("未設定は --:--:-- のままで、尺は - ", () => {
      win.setCut(null, null);
      // 未設定のinputは空で、--:--:-- はplaceholderが出す。
      expect(doc.getElementById("cut-in").value).toBe("");
      expect(doc.getElementById("cut-in").placeholder).toBe("--:--:--");
      expect(doc.getElementById("cut-out").value).toBe("");
      expect(doc.getElementById("cut-out").placeholder).toBe("--:--:--");
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

  // IN/OUT線は帯の全高に描かれる。掴める範囲が上端laneだけだと、線の上を掴んだ操作が
  // 黙ってseekになり、掴んだつもりの再生位置が飛ぶ。
  describe("全尺barの当たり判定", () => {
    beforeEach(() => {
      layoutHeat({ left: 0, width: 200, top: 0, height: 60 });
      setDuration(100);
    });

    it("波形の高さでもIN/OUT線の上ならhandleを掴む(seekへ落ちない)", () => {
      win.setCut(20, 60);
      // 20秒=x:40 / 60秒=x:120。laneより下(y:40)で線の上を押す。
      expect(win.hitTestHeat(40, 40, "mouse")).toBe("in");
      expect(win.hitTestHeat(120, 40, "mouse")).toBe("out");
    });

    it("lane外の許容幅は半分に絞り、線から離れればseekに戻す", () => {
      win.setCut(20, 60);
      // mouseの許容幅は lane内8px / lane外4px。
      expect(win.hitTestHeat(126, 5, "mouse")).toBe("out");
      expect(win.hitTestHeat(126, 40, "mouse")).toBe("seek");
      expect(win.hitTestHeat(123, 40, "mouse")).toBe("out");
    });

    it("範囲の新規作成と平行移動は上端laneのまま(下でdragしてもseek)", () => {
      win.setCut(20, 60);
      expect(win.hitTestHeat(80, 5, "mouse")).toBe("band");
      expect(win.hitTestHeat(80, 40, "mouse")).toBe("seek");
      win.setCut(null, null);
      expect(win.hitTestHeat(80, 5, "mouse")).toBe("new");
      expect(win.hitTestHeat(80, 40, "mouse")).toBe("seek");
    });

    it("IN/OUTが近接していても近いほうを返す(OUTがINに飲まれない)", () => {
      // 20秒=x:40 / 23秒=x:46。lane内の許容幅8pxでは両方が当たる。
      win.setCut(20, 23);
      expect(win.hitTestHeat(41, 5, "mouse")).toBe("in");
      expect(win.hitTestHeat(45, 5, "mouse")).toBe("out");
    });

    it("尺が分かる前は何も掴ませない", () => {
      win.setCut(20, 60);
      setDuration(NaN);
      expect(win.hitTestHeat(40, 5, "mouse")).toBe("seek");
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

    it("clipOptions は5つの指定をすべて載せる(取りこぼすと既定値で走る)", () => {
      const opts = win.clipOptions();
      expect(Object.keys(opts).sort()).toEqual(
        ["mode", "normalize_audio", "remove_bgm", "subtitles", "variant"]);
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

  // 拡大窓は「今どこを見ているか」を持つ唯一の状態。追従が窓の位置を毎回作り直していた頃は、
  // 追従checkboxを外しても窓が再生位置へ引き戻され続け、外したこと自体が効かなかった。
  describe("拡大窓の位置", () => {
    beforeEach(() => {
      setDuration(600);
      state().zoomStart = null;
      state().zoomSpan = 100;
      doc.getElementById("zoom-follow").checked = true;
    });

    const windowNow = () => win.zoomWindow(600);

    it("追従を外したら、再生が進んでも窓はその場に留まる", () => {
      setCurrentTime(200);
      win.followZoom();
      const start = windowNow().start;
      doc.getElementById("zoom-follow").checked = false;
      setCurrentTime(500);
      win.followZoom();
      expect(windowNow().start).toBe(start);
    });

    it("追従中でも、再生位置が窓の中に居る間は窓を動かさない", () => {
      setCurrentTime(200);
      win.followZoom();
      const start = windowNow().start;
      setCurrentTime(start + 90);
      win.followZoom();
      expect(windowNow().start).toBe(start);
    });

    it("追従は窓の外へ出たときだけ置き直す(左端から2割の位置へ)", () => {
      setCurrentTime(200);
      win.followZoom();
      setCurrentTime(400);
      win.followZoom();
      expect(windowNow().start).toBeCloseTo(400 - 100 * 0.2, 6);
    });

    it("窓が尺の外へはみ出さない", () => {
      setCurrentTime(600);
      win.followZoom();
      expect(windowNow().start).toBe(500);
      setCurrentTime(0);
      win.followZoom();
      expect(windowNow().start).toBe(0);
    });

    it("左右移動は追従を外して窓幅の割合ぶん動かす", () => {
      setCurrentTime(300);
      win.followZoom();
      const start = windowNow().start;
      win.panZoom(1);
      expect(doc.getElementById("zoom-follow").checked).toBe(false);
      expect(windowNow().start).toBeCloseTo(start + 20, 6);
      win.panZoom(-1);
      expect(windowNow().start).toBeCloseTo(start, 6);
    });

    it("拡縮しても追従中は再生位置が窓の同じ場所に残る(直後に窓が跳ばない)", () => {
      setCurrentTime(300);
      win.followZoom();
      const before = windowNow();
      const ratio = (300 - before.start) / before.span;
      win.zoomBy(0.5, 0.9);
      const after = windowNow();
      expect(after.span).toBe(50);
      expect((300 - after.start) / after.span).toBeCloseTo(ratio, 6);
    });

    it("追従していなければ、拡縮はcursorの下の時刻を動かさない", () => {
      setCurrentTime(300);
      win.followZoom();
      doc.getElementById("zoom-follow").checked = false;
      const before = windowNow();
      const pinned = before.start + 0.75 * before.span;
      win.zoomBy(0.5, 0.75);
      const after = windowNow();
      expect(after.start + 0.75 * after.span).toBeCloseTo(pinned, 6);
    });

    it("窓幅は下限より狭くならない(波形が箱になるだけの拡大を止める)", () => {
      setCurrentTime(300);
      win.followZoom();
      for (let i = 0; i < 20; i += 1) win.zoomBy(0.5, 0.5);
      expect(windowNow().span).toBe(8);
    });
  });

  // 飛んだgiftのicon。時間軸の上へ並べる物なので、間引きで残す基準と残す位置が
  // ずれると「その時刻に飛んでいないgift」を描くことになる。
  describe("ギフトiconの間引き", () => {
    const gift = (t, diamonds, giftId = 1) => ({ t, diamonds, gift_id: giftId });
    // 秒をそのままxとして扱う写像。間引きの規則だけを見る。
    const asX = (seconds) => seconds;
    // 幅の実測に使うcontext(stubは1文字6px)。名前を出すときの場所取りがこれで決まる。
    const ctx = () => doc.getElementById("heat").getContext("2d");
    const pick = (gifts, size = 10, rows = 1, withName = false) =>
      win.pickGiftIcons(ctx(), gifts, asX, 200, size, rows, withName);

    it("重なる位置では高額なgiftだけを残す", () => {
      expect(pick([gift(10, 1), gift(14, 500), gift(60, 5)])
        .map((p) => p.gift.diamonds)).toEqual([500, 5]);
    });

    it("iconの一辺ぶん離れていれば両方残す", () => {
      expect(pick([gift(10, 1), gift(30, 1)]).map((p) => p.x)).toEqual([10, 30]);
    });

    it("barの外のgiftは持ち込まない", () => {
      expect(pick([gift(-40, 9), gift(50, 9), gift(400, 9)]).map((p) => p.x)).toEqual([50]);
    });

    it("残した後は左から右へ並べ直す(高額順のまま描かない)", () => {
      expect(pick([gift(150, 1), gift(50, 900), gift(100, 20)]).map((p) => p.x))
        .toEqual([50, 100, 150]);
    });

    it("拡大窓は窓の中でicon画像を出せるgiftだけを拾う", () => {
      state().gifts = [gift(5, 1, 11), gift(50, 1, 22), gift(60, 1, 33), gift(500, 1, 22)];
      // 22番のiconだけ出せる。出せないgiftを場所取りに使うと、そこに描けたはずの
      // 隣のgiftまで消える。
      state().giftIcons = { 22: "/api/gift-icon?gift_id=22" };
      const picked = win.giftIconsInWindow(ctx(), { start: 10, end: 100 }, asX, 200, 10, 1);
      expect(picked.map((p) => p.gift.gift_id)).toEqual([22]);
    });

    // 送り主を添える版。名前のぶん1件が横に広がるので、場所取りがiconの幅のままだと
    // 「iconは離れているのに名前だけ重なる」状態になる。
    describe("送り主つき", () => {
      const named = (t, diamonds, nickname) =>
        ({ ...gift(t, diamonds), nickname });

      it("名前は頭3文字だけを採る(絵文字も1文字として数える)", () => {
        expect(win.giftSenderName({ nickname: "あいうえお" })).toBe("あいう");
        expect(win.giftSenderName({ nickname: "🎁🎈🎀🎉" })).toBe("🎁🎈🎀");
        expect(win.giftSenderName({ nickname: "", uid: "gifter" })).toBe("gif");
        expect(win.giftSenderName({ nickname: "", uid: "" })).toBe("");
      });

      it("名前のぶんまで場所を取る(iconの幅だけでは名前が重なる)", () => {
        // 3文字=18px。1件の幅は max(icon 10, 18+2)=20 なので、20px差では並べられない。
        const gifts = [named(50, 9, "あいうえお"), named(70, 5, "かきくけこ")];
        expect(pick(gifts, 10, 1, true).map((p) => p.gift.diamonds)).toEqual([9]);
        expect(pick(gifts, 10, 1, false).map((p) => p.gift.diamonds)).toEqual([9, 5]);
      });

      it("同じ列に置けないものは下の段へ回す(段が在れば落とさない)", () => {
        const picked = pick([named(50, 9, "あいう"), named(70, 5, "かきく")], 10, 2, true);
        expect(picked.map((p) => [p.gift.diamonds, p.row])).toEqual([[9, 0], [5, 1]]);
      });

      it("段が尽きたら落とす(高額なものから段を埋める)", () => {
        const picked = pick(
          [named(50, 1, "あいう"), named(55, 9, "かきく"), named(60, 5, "さしす")], 10, 2, true);
        expect(picked.map((p) => [p.gift.diamonds, p.row])).toEqual([[9, 0], [5, 1]]);
      });

      it("段が空いていれば全て最上段へ載る(混んだ時だけ下へ伸びる)", () => {
        const picked = pick([named(30, 9, "あいう"), named(120, 5, "かきく")], 10, 3, true);
        expect(picked.every((p) => p.row === 0)).toBe(true);
      });
    });
  });

  // 間引きの規則が正しくても、canvasへ落ちる位置がずれれば同じ嘘になる。実際に描かれた
  // drawImageのx座標で見る。
  describe("ギフトiconの描画", () => {
    /** jsdomはlayoutを持たないので、canvasの実寸はtestが与える(0だと描画がそのまま返る)。 */
    function sizeCanvas(id, width, height) {
      const el = doc.getElementById(id);
      Object.defineProperty(el, "clientWidth", { configurable: true, get: () => width });
      Object.defineProperty(el, "clientHeight", { configurable: true, get: () => height });
      return el;
    }

    function drawnIcons(canvas) {
      return canvas.getContext("2d").__ops.filter((op) => op[0] === "drawImage");
    }

    beforeEach(() => {
      doc.getElementById("show-gifts").checked = true;
      state().gifts = [{ t: 50, diamonds: 9, gift_id: 22 }];
      state().giftIcons = { 22: "/api/gift-icon?gift_id=22" };
      // 読み込み済みのicon画像。jsdomは画像を取りに行かないので、載る条件だけを与える。
      page.run('giftIconImages.set("22", { complete: true, naturalWidth: 24 })');
      page.run("giftLayout = null");
      setDuration(100);
      setCurrentTime(0);
    });

    it("全尺barでは尺に対する位置へ置く(iconの中心が時刻)", () => {
      const canvas = sizeCanvas("heat", 200, 60);
      win.drawHeat();
      const icons = drawnIcons(canvas);
      expect(icons).toHaveLength(1);
      // 50/100秒 → x=100。drawImageの左端はそこからicon半分ぶん戻る。
      expect(icons[0][2] + icons[0][4] / 2).toBeCloseTo(100, 1);
    });

    it("拡大窓では窓の中の位置へ置く", () => {
      const canvas = sizeCanvas("zoom", 200, 90);
      state().zoomStart = 40;
      state().zoomSpan = 20;
      doc.getElementById("zoom-follow").checked = false;
      win.drawZoom();
      const icons = drawnIcons(canvas);
      expect(icons).toHaveLength(1);
      // 窓は40〜60秒。50秒は窓の中央なのでx=100。
      expect(icons[0][2] + icons[0][4] / 2).toBeCloseTo(100, 1);
    });

    it("表示を切れば描かない", () => {
      doc.getElementById("show-gifts").checked = false;
      const canvas = sizeCanvas("heat", 200, 60);
      win.drawHeat();
      expect(drawnIcons(canvas)).toHaveLength(0);
    });

    it("icon画像を取れなかったgiftは描かない(別の絵で代用しない)", () => {
      page.run('giftIconImages.set("22", { complete: true, naturalWidth: 0 })');
      const canvas = sizeCanvas("heat", 200, 60);
      win.drawHeat();
      expect(drawnIcons(canvas)).toHaveLength(0);
    });

    // 送り主。誰が送ったかは拡大窓だけで出す(全尺barは1px≈数秒で名前が読めない)。
    describe("送り主の表示", () => {
      function openZoom(height = 128) {
        const canvas = sizeCanvas("zoom", 200, height);
        state().zoomStart = 40;
        state().zoomSpan = 20;
        doc.getElementById("zoom-follow").checked = false;
        win.drawZoom();
        return canvas;
      }
      const texts = (canvas) =>
        canvas.getContext("2d").__ops.filter((op) => op[0] === "fillText").map((op) => op[1]);

      it("拡大窓には名前の頭3文字を出す", () => {
        state().gifts = [{ t: 50, diamonds: 9, gift_id: 22, nickname: "あいうえお", uid: "gifter" }];
        expect(texts(openZoom())).toContain("あいう");
      });

      it("avatarを取れていなければ頭文字の円へ落とす(別人の絵を置かない)", () => {
        state().gifts = [{ t: 50, diamonds: 9, gift_id: 22, nickname: "Zoe", uid: "zoe" }];
        // jsdomは画像を取りに行かないので、pool側は常に未取得のまま。
        expect(texts(openZoom())).toEqual(expect.arrayContaining(["Z", "Zoe"]));
      });

      it("全尺barは送り主を出さない(名前を足すと隣のgiftが落ちるだけ)", () => {
        state().gifts = [{ t: 50, diamonds: 9, gift_id: 22, nickname: "あいうえお", uid: "gifter" }];
        page.run("giftLayout = null");
        const canvas = sizeCanvas("heat", 200, 60);
        win.drawHeat();
        expect(texts(canvas)).not.toContain("あいう");
      });

      it("送り主が判らない行には何も添えない", () => {
        state().gifts = [{ t: 50, diamonds: 9, gift_id: 22, nickname: "", uid: "" }];
        expect(texts(openZoom())).not.toContain("?");
      });
    });
  });

  describe("chapterExportUrl", () => {
    it("開いている録画のidと書式をURLへ載せる", () => {
      state().current = { recording_id: 42 };
      expect(win.chapterExportUrl("txt")).toBe("/api/recordings/42/chapters/export?format=txt");
      expect(win.chapterExportUrl("vtt")).toBe("/api/recordings/42/chapters/export?format=vtt");
    });
  });

  // 文字起こしの「今の行」。無音は実データで再生時間の3〜5割を占めるので、そこで印が
  // 外れると一文ごとに点滅する。帯(vd-seg-prev)は残し、太字(vd-seg-active)だけを
  // 発話中に限る。
  describe("highlightActiveSegment", () => {
    beforeEach(() => {
      state().segments = [
        { start: 0, end: 2, text: "いち" },
        { start: 5, end: 7, text: "に" },
        { start: 10, end: 12, text: "さん" },
      ];
      win.renderSegments();
    });

    const classesAt = (index) =>
      Array.from(doc.getElementById("segments").children[index].classList);

    it("発話中の行はvd-seg-active", () => {
      setCurrentTime(6);
      win.highlightActiveSegment();
      expect(classesAt(1)).toContain("vd-seg-active");
      expect(classesAt(0)).not.toContain("vd-seg-prev");
    });

    it("無音では直前の行に帯を残す(印を消さない)", () => {
      setCurrentTime(6);
      win.highlightActiveSegment();
      setCurrentTime(8);
      win.highlightActiveSegment();
      expect(classesAt(1)).toContain("vd-seg-prev");
      expect(classesAt(1)).not.toContain("vd-seg-active");
    });

    it("同じ行の発話中/無音の入れ替わりを取りこぼさない", () => {
      setCurrentTime(6);
      win.highlightActiveSegment();
      setCurrentTime(8);
      win.highlightActiveSegment();
      setCurrentTime(6);
      win.highlightActiveSegment();
      expect(classesAt(1)).toContain("vd-seg-active");
      expect(classesAt(1)).not.toContain("vd-seg-prev");
    });

    it("印は1行だけ(次の発話へ移ると前の行から両方外れる)", () => {
      setCurrentTime(8);
      win.highlightActiveSegment();
      setCurrentTime(11);
      win.highlightActiveSegment();
      expect(classesAt(1)).not.toContain("vd-seg-prev");
      expect(classesAt(1)).not.toContain("vd-seg-active");
      expect(classesAt(2)).toContain("vd-seg-active");
    });

    it("最初の発話より前は印を付けない(まだ読む行が無い)", () => {
      setCurrentTime(6);
      win.highlightActiveSegment();
      setCurrentTime(-1);
      win.highlightActiveSegment();
      expect(classesAt(0)).not.toContain("vd-seg-active");
      expect(classesAt(1)).not.toContain("vd-seg-prev");
    });
  });
});
