import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 配信者動画画面。録画の実体(TS/MP4)の名乗り・確認状態の絞り込み・切り出し範囲・
// segment吸着など、秒数と実体の扱いを間違えると出力が壊れる箇所を見る。
describe("videos.js", () => {
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

  describe("reviewStateOf", () => {
    it("serverの3状態はそのまま通す", () => {
      expect(win.reviewStateOf({ review_state: "checking" })).toBe("checking");
      expect(win.reviewStateOf({ review_state: "checked" })).toBe("checked");
    });

    it("未設定・未知の値は未確認へ寄せる", () => {
      expect(win.reviewStateOf({})).toBe("unchecked");
      expect(win.reviewStateOf({ review_state: "なにか" })).toBe("unchecked");
      expect(win.reviewStateOf(null)).toBe("unchecked");
    });
  });

  describe("hitCutRange", () => {
    it("終了時刻があればIN/OUTの範囲を返す", () => {
      expect(win.hitCutRange({ video_time: 10, end_time: 25 })).toEqual([10, 25]);
    });

    it("終了時刻が無い・開始以前ならrangeを作らない(0秒の切り出しを作らない)", () => {
      expect(win.hitCutRange({ video_time: 10 })).toBeNull();
      expect(win.hitCutRange({ video_time: 10, end_time: 10 })).toBeNull();
      expect(win.hitCutRange({ video_time: 10, end_time: 5 })).toBeNull();
      expect(win.hitCutRange({ video_time: 10, end_time: "x" })).toBeNull();
    });
  });

  describe("snapToSegments", () => {
    beforeEach(() => {
      state().segments = [
        { start: 10.0, end: 20.0 },
        { start: 20.0, end: 31.2 },
      ];
    });

    it("吸着offなら秒をそのまま返す", () => {
      doc.getElementById("snap-seg").checked = false;
      expect(win.snapToSegments(20.4, "in")).toBe(20.4);
    });

    it("IN は segment の開始へ、OUT は終了へ吸着する", () => {
      doc.getElementById("snap-seg").checked = true;
      expect(win.snapToSegments(20.4, "in")).toBe(20.0);
      expect(win.snapToSegments(31.0, "out")).toBe(31.2);
    });

    it("窓(1.5秒)より遠い境界へは吸着しない", () => {
      doc.getElementById("snap-seg").checked = true;
      expect(win.snapToSegments(25.0, "in")).toBe(25.0);
    });

    it("segmentが未取得なら吸着しない(存在しない境界へ寄せない)", () => {
      doc.getElementById("snap-seg").checked = true;
      state().segments = [];
      expect(win.snapToSegments(20.4, "in")).toBe(20.4);
    });
  });

  // 同じ範囲を2回記録しても画面は成功としか言わず、重複は一括書き出しで同じmp4が2本
  // 出るまで見えなかった。押せる形で残さないことを、buttonの状態で確かめる。
  // 記録の口は1つなので、押した結果が入力の状態で変わることもここで見る。
  describe("同じ範囲の記録", () => {
    beforeEach(() => {
      state().current = { recording_id: 1 };
      state().marks = [
        { id: 7, recording_id: 1, start: 100, end: 130, group_id: null, origin: "manual" },
      ];
    });

    it("既にlistに在る範囲は「記録済」で押せない", () => {
      win.setCut(100, 130);
      const button = doc.getElementById("add-mark");
      expect(button.textContent).toBe("記録済");
      expect(button.disabled).toBe(true);
    });

    it("frame未満のずれは同じ範囲として扱う(詰め直した拍子の重複を作らない)", () => {
      win.setCut(100.01, 129.99);
      expect(doc.getElementById("add-mark").disabled).toBe(true);
    });

    it("別の範囲・別の録画なら押せる", () => {
      win.setCut(100, 140);
      expect(doc.getElementById("add-mark").disabled).toBe(false);
      expect(doc.getElementById("add-mark").textContent).toBe("見どころ記録（尺あり）");
      state().current = { recording_id: 2 };
      win.setCut(100, 130);
      expect(doc.getElementById("add-mark").disabled).toBe(false);
    });

    // 点は尺を持たないので重複の判定に掛からない(同じ位置の点は別の覚え書きであり得る)。
    it("IN/OUTが無ければ点として記録すると名乗る", () => {
      win.setCut(null, null);
      expect(doc.getElementById("add-mark").textContent).toBe("見どころ記録（点）");
      expect(doc.getElementById("add-mark").disabled).toBe(false);
    });

    it("同じ範囲の判定は尺のある行だけを見る(点は素材にならない)", () => {
      state().marks = [
        { id: 8, recording_id: 1, start: 100, end: null, group_id: null, origin: "manual" },
      ];
      win.setCut(100, 130);
      expect(doc.getElementById("add-mark").disabled).toBe(false);
    });
  });

  // メモは覚え書きであり、書き出しfile名とEDL/FCPXMLのclip名でもある。以前は最後の
  // 検索語を黙って使っており、無関係な語のfileが数十件できていた。欄の値をそのまま使う。
  describe("見どころのメモ", () => {
    it("欄の値を使う(前後の空白は落とす)", () => {
      doc.getElementById("mark-memo").value = "  神回の煽り  ";
      expect(win.currentClipLabel()).toBe("神回の煽り");
    });

    it("空欄ならlabelを付けない(検索語を勝手に使わない)", () => {
      state().query = "煽り";
      doc.getElementById("mark-memo").value = "";
      expect(win.currentClipLabel()).toBe("");
    });
  });

  describe("activeCommentIndex", () => {
    beforeEach(() => {
      state().comments = [{ t: 0 }, { t: 5 }, { t: 5 }, { t: 12 }, { t: 30 }];
    });

    it("再生位置以前の最後のcommentを指す", () => {
      expect(win.activeCommentIndex(0)).toBe(0);
      expect(win.activeCommentIndex(11.9)).toBe(2);
      expect(win.activeCommentIndex(12)).toBe(3);
      expect(win.activeCommentIndex(1000)).toBe(4);
    });

    it("最初のcommentより前は該当なし", () => {
      expect(win.activeCommentIndex(-1)).toBe(-1);
    });

    it("commentが無い録画でも落ちない", () => {
      state().comments = [];
      expect(win.activeCommentIndex(10)).toBe(-1);
    });
  });

  describe("selectedSources", () => {
    it("checkされたsourceだけを送る", () => {
      doc.getElementById("src-stt").checked = true;
      doc.getElementById("src-comment").checked = true;
      expect(win.selectedSources()).toEqual(["stt", "comment"]);
      doc.getElementById("src-comment").checked = false;
      expect(win.selectedSources()).toEqual(["stt"]);
      doc.getElementById("src-stt").checked = false;
      expect(win.selectedSources()).toEqual([]);
    });
  });

  // 笑い声は音そのものが根拠で、当たる語を持たない。検索対象のcheckboxとして並べていた
  // 頃は語の検索に混ざる建前で、実際には「笑い声」と打った時だけ出る隠しmodeだった。
  describe("探し方: 笑い声", () => {
    const LAUGH = {
      total: 2, mode: "laugh", hint: "", terms: [],
      items: [
        { id: 1, source: "laugh", recording_id: 7, session_id: 3, unique_id: "@who",
          started_at: 100, video_time: 12, end_time: 24, nickname: null,
          body: "12秒（強さ 0.80）", snippet: "12秒（強さ 0.80）" },
      ],
    };

    async function pickLaugh(order) {
      const urls = [];
      win.fetch = (input) => {
        urls.push(String(input));
        return Promise.resolve(new Response(JSON.stringify(LAUGH), {
          status: 200, headers: { "Content-Type": "application/json" },
        }));
      };
      if (order) doc.getElementById("flt-laugh-order").value = order;
      doc.getElementById("flt-mode").value = "laugh";
      doc.getElementById("flt-mode").dispatchEvent(new win.Event("change", { bubbles: true }));
      await page.settle();
      return urls;
    }

    it("語を送らず専用の一覧を引く(検索語が残っていても条件に混ぜない)", async () => {
      doc.getElementById("q").value = "ガンダム";
      const urls = await pickLaugh();
      expect(urls.some((u) => u.startsWith("/api/search/laughs?"))).toBe(true);
      expect(urls.some((u) => u.includes("/api/search?"))).toBe(false);
      expect(urls.join("|")).not.toContain("ガンダム");
      expect(state().hits).toHaveLength(1);
    });

    it("効かない操作は押せる状態で残さない(語の欄・検索対象)", async () => {
      await pickLaugh();
      expect(doc.getElementById("q").disabled).toBe(true);
      expect(doc.getElementById("src-stt").disabled).toBe(true);
      expect(doc.getElementById("src-comment").disabled).toBe(true);
      // 並替は探し方ごとに選択肢が違う。関連度順は笑い声には無い。
      expect(doc.getElementById("order-field").classList.contains("hidden")).toBe(true);
      expect(doc.getElementById("laugh-order-field").classList.contains("hidden")).toBe(false);
    });

    it("強さ順・長さ順をserverへ渡す(語の一致度が無い代わりの手掛かり)", async () => {
      expect((await pickLaugh("strength")).join("|")).toContain("order=strength");
      expect((await pickLaugh("length")).join("|")).toContain("order=length");
    });

    it("語での検索へ戻すと、語の欄と検索対象が押せる状態へ戻る", async () => {
      await pickLaugh();
      doc.getElementById("flt-mode").value = "keyword";
      doc.getElementById("flt-mode").dispatchEvent(new win.Event("change", { bubbles: true }));
      await page.settle();
      expect(doc.getElementById("q").disabled).toBe(false);
      expect(doc.getElementById("src-stt").disabled).toBe(false);
      expect(doc.getElementById("src-comment").disabled).toBe(false);
      // 語での検索へ戻れば並替も語のものへ戻る(笑い声の選択肢が残らない)。
      expect(doc.getElementById("laugh-order-field").classList.contains("hidden")).toBe(true);
    });
  });

  describe("bulkTargetCount", () => {
    const streamer = { targets: { overlay: 3 }, done: { overlay: 7 } };

    it("既定は未処理ぶんだけを数える", () => {
      expect(win.bulkTargetCount(streamer, "overlay", false)).toBe(3);
    });

    it("作り直しなら処理済みも対象へ含める", () => {
      expect(win.bulkTargetCount(streamer, "overlay", true)).toBe(10);
    });

    it("その種別の集計が無ければ0", () => {
      expect(win.bulkTargetCount(streamer, "up", false)).toBe(0);
      expect(win.bulkTargetCount({}, "overlay", true)).toBe(0);
    });
  });

  describe("showView", () => {
    it("選んだviewだけを出し、tabのactiveを一致させる", () => {
      win.showView("marks");
      expect(doc.getElementById("view-marks").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(true);
      expect(doc.getElementById("tab-marks").classList.contains("active")).toBe(true);
      expect(doc.getElementById("tab-search").classList.contains("active")).toBe(false);
    });
  });

  describe("確認状態での絞り込み", () => {
    beforeEach(() => {
      state().browseAll = [
        { recording_id: 1, review_state: "unchecked" },
        { recording_id: 2, review_state: "checked" },
        { recording_id: 3, review_state: "checking" },
        { recording_id: 4 },
      ];
      state().current = null;
      state().hitIndex = -1;
    });

    it("未選択なら全件を残す", () => {
      doc.getElementById("flt-review").value = "";
      win.applyBrowseFilter();
      expect(state().hits.map((r) => r.recording_id)).toEqual([1, 2, 3, 4]);
    });

    it("状態で絞り込み、印の無い録画は未確認として扱う", () => {
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(state().hits.map((r) => r.recording_id)).toEqual([1, 4]);
    });

    it("開いていた録画が一覧から外れたら選択なしへ戻す(別録画に枠を残さない)", () => {
      state().current = { recording_id: 2 };
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(state().hitIndex).toBe(-1);
    });

    it("開いていた録画が残るなら、絞り込み後の位置を追い直す", () => {
      state().current = { recording_id: 4 };
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(state().hitIndex).toBe(1);
    });

    it("0件でも「取得失敗」の見た目にはしない", () => {
      state().browseAll = [{ recording_id: 1, review_state: "checked" }];
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      const empty = doc.getElementById("hit-empty");
      expect(empty.textContent).toBe("");
      expect(empty.classList.contains("list-failed")).toBe(false);
    });

    it("件数の要約に絞り込み後と全体の両方を出す", () => {
      doc.getElementById("flt-review").value = "unchecked";
      win.applyBrowseFilter();
      expect(doc.getElementById("search-summary").textContent).toBe("2/4");
    });
  });

  // 録画一覧を笑い声の量で並べる。未解析(値を持たない録画)を0秒と同じ顔で並べると、
  // 末尾が「笑わなかった配信」と「まだ数えていない配信」の混ざった塊になる。
  describe("録画一覧の笑い声順", () => {
    beforeEach(() => {
      state().browseAll = [
        { recording_id: 1, started_at: 300, laugh_seconds: 12, laugh_windows: 3 },
        { recording_id: 2, started_at: 200, laugh_seconds: 90, laugh_windows: 9 },
        { recording_id: 3, started_at: 100 },
        { recording_id: 4, started_at: 400, laugh_seconds: 0, laugh_windows: 0 },
      ];
      state().current = null;
      state().hitIndex = -1;
      doc.getElementById("flt-review").value = "";
    });

    it("既定は配信が新しい順のまま(受け取った並びを触らない)", () => {
      doc.getElementById("flt-browse-order").value = "time";
      win.applyBrowseFilter();
      expect(state().hits.map((r) => r.recording_id)).toEqual([1, 2, 3, 4]);
    });

    it("笑い声順は多い順に並べ、未解析だけを末尾へ落とす", () => {
      doc.getElementById("flt-browse-order").value = "laugh";
      win.applyBrowseFilter();
      // 0秒(解析済み)は未解析より前。解析して笑いが無かったことは分かっている事実。
      expect(state().hits.map((r) => r.recording_id)).toEqual([2, 1, 4, 3]);
    });

    it("末尾に溜まった未解析の本数を要約へ出す", () => {
      doc.getElementById("flt-browse-order").value = "laugh";
      win.applyBrowseFilter();
      expect(doc.getElementById("search-summary").textContent).toContain("未解析 1");
    });

    it("未解析の欄は0秒ではなく「—」と出す", () => {
      expect(win.laughText({ laugh_seconds: null })).toBe("—");
      expect(win.laughText({ laugh_seconds: 30 })).not.toBe("—");
    });
  });

  // 配信者選択は「選ぶと何かが出てくる」配信者だけを並べる。実体も文字起こしも索引も無い配信者を
  // 混ぜると、選んでも空の一覧しか出ない選択肢が並ぶ(素材がretentionで消えた配信者)。
  // 名簿の出所は一括処理の集計(state.bulk)1つだけ。同じ走査をする一覧を2本持っていた頃は、
  // 同じ画面に母集合の違う「録画」列が並び、数が食い違っていた。
  describe("配信者の絞り込み候補", () => {
    const entry = (over) => ({
      unique_id: "x", recordings: 1, playable: 0, comment_indexed: 0, seconds: 0,
      targets: {}, done: {}, ...over,
    });
    const options = () =>
      [...doc.getElementById("flt-streamer").options].map((o) => o.value);

    it("実体のある配信者は候補に出す", () => {
      state().bulk = [entry({ unique_id: "alive", playable: 2 })];
      win.fillStreamerSelects();
      expect(options()).toEqual(["", "alive"]);
    });

    it("実体も文字起こしも索引も無い配信者は候補から外す", () => {
      state().bulk = [entry({ unique_id: "ghost", recordings: 5 })];
      win.fillStreamerSelects();
      expect(options()).toEqual([""]);
    });

    it("実体が無くても文字起こし・索引が在れば残す(そこへ辿る道がここしかない)", () => {
      state().bulk = [
        entry({ unique_id: "stt-only", done: { transcribe: 1 } }),
        entry({ unique_id: "cmt-only", comment_indexed: 1 }),
      ];
      win.fillStreamerSelects();
      expect(options()).toEqual(["", "stt-only", "cmt-only"]);
    });

    it("選択中の配信者が候補から消えたら「全て」へ戻す", () => {
      state().bulk = [entry({ unique_id: "alive", playable: 1 })];
      win.fillStreamerSelects();
      doc.getElementById("flt-streamer").value = "alive";
      state().bulk = [entry({ unique_id: "alive" })];
      win.fillStreamerSelects();
      expect(doc.getElementById("flt-streamer").value).toBe("");
    });
  });

  // 一括処理は配信者×種別の表1枚。cellの数字は「押したら何本走るか」で、押せない理由は
  // 押す前に出す(押してから409や503で知るのでは遅い)。
  describe("一括処理の表", () => {
    const entry = (over) => ({
      unique_id: "x", recordings: 4, playable: 4, comment_indexed: 4, seconds: 60,
      targets: {}, done: {}, ...over,
    });
    const rows = () => [...doc.getElementById("bulk-rows").rows];
    // 列の並びは videos.js が持つ(BULK_KIND_ORDER)。test 側に写すと、種別を足したときに
    // test だけ古い並びを見続ける。
    const kindOrder = () => page.get("BULK_KIND_ORDER");
    const labelOf = (kind) => page.get("BULK_LABELS")[kind];
    const cellOf = (row, kind) =>
      row.cells[kindOrder().indexOf(kind) + 2].querySelector("button");

    it("種別を選ばせずに全種別を列として出す", () => {
      state().bulk = [entry({ unique_id: "alive", targets: { overlay: 3, upscale: 1 } })];
      win.renderBulk();
      const heads = [...doc.getElementById("bulk-head").rows[0].cells].map(
        (th) => th.textContent);
      kindOrder().forEach((kind) => {
        expect(heads.some((text) => text.includes(labelOf(kind)))).toBe(true);
      });
    });

    it("表からは消さず、実体0本であることを名乗る", () => {
      state().bulk = [
        entry({ unique_id: "alive", targets: { overlay: 2 } }),
        entry({ unique_id: "ghost", playable: 0, recordings: 5 }),
      ];
      win.renderBulk();
      expect(rows()).toHaveLength(2);
      expect(rows()[0].cells[0].textContent).toBe("alive");
      expect(rows()[1].cells[0].textContent).toContain("実体なし");
    });

    it("対象0本のcellは押させない", () => {
      state().bulk = [entry({ unique_id: "alive", targets: { overlay: 2 }, done: { upscale: 4 } })];
      win.renderBulk();
      const row = rows()[0];
      expect(cellOf(row, "overlay").disabled).toBe(false);
      expect(cellOf(row, "overlay").textContent).toContain("2");
      expect(cellOf(row, "upscale").disabled).toBe(true);
    });

    it("文字起こしが無効なときは押させない(押してから503で知らせない)", () => {
      state().bulk = [entry({ unique_id: "alive", targets: { transcribe: 3 } })];
      state().sttAvailable = false;
      win.renderBulk();
      expect(cellOf(rows()[0], "transcribe").disabled).toBe(true);
    });

    // 録画を選んで投入する道は、cellを押さないと開かない。押されていたのは列見出し
    // (=まるごと投入)ばかりで、選ぶ道が在ることに気付けていなかった。cellと確認paneの
    // 両方で名乗らせる。
    it("対象のあるcellは「選ぶ」と名乗る(対象0本のcellには出さない)", () => {
      state().bulk = [entry({ unique_id: "alive", targets: { overlay: 2 }, done: { upscale: 4 } })];
      win.renderBulk();
      expect(cellOf(rows()[0], "overlay").textContent).toContain("選ぶ");
      expect(cellOf(rows()[0], "upscale").textContent).not.toContain("選ぶ");
    });

    // 確認paneは列見出しからも開く。そこから来た人には表のcellを押す導線が視界に入らない
    // ので、決める場所と同じ行に選び直す道を置く。
    describe("投入前の確認", () => {
      const pending = (uniqueId) => ({
        kind: "overlay", uniqueId, redo: false, recordingIds: null,
        estimate: {
          kind: "overlay", unique_id: uniqueId, redo: false, recordings: 3, seconds: 60,
          source_bytes: 0, largest_source_bytes: 0, eta_seconds: null, eta_samples: 0,
          skipped: {}, disk: { volumes: {}, low_volumes: [] },
        },
      });
      const confirmButtons = () =>
        [...doc.querySelectorAll(".bulk-confirm .vd-cuts-tools button")];

      it("まるごと投入の確認から、録画を選ぶ一覧を開ける", () => {
        state().bulk = [entry({ unique_id: "alive", targets: { overlay: 3 } })];
        state().bulkPending = pending("alive");
        win.renderBulk();
        const pick = confirmButtons().find((b) => b.textContent.includes("録画を選んで"));
        expect(pick).toBeTruthy();
        expect(pick.disabled).toBe(false);
        pick.click();
        expect(state().bulkOpen).toEqual({ uniqueId: "alive", kind: "overlay" });
      });

      it("全配信者ぶんの確認からは開けない(録画一覧は配信者1人ぶん)", () => {
        state().bulk = [entry({ unique_id: "alive", targets: { overlay: 3 } })];
        state().bulkPending = pending(null);
        win.renderBulk();
        const pick = confirmButtons().find((b) => b.textContent.includes("録画を選んで"));
        expect(pick.disabled).toBe(true);
      });
    });

    it("「作り直す」余地の無い種別には再出力の指定を効かせない", () => {
      state().bulk = [entry({
        unique_id: "alive",
        targets: { overlay: 1, pack: 1 },
        done: { overlay: 3, pack: 3 },
      })];
      doc.getElementById("bulk-redo").checked = true;
      win.renderBulk();
      // 焼き込みは済みも対象へ戻る。ts結合は戻らない(serverの投入側も戻さない)。
      expect(cellOf(rows()[0], "overlay").textContent).toContain("4");
      expect(cellOf(rows()[0], "pack").textContent).toContain("1");
    });
  });

  // M keyは動画を見ている最中に押されるので、視線はstatusの1行から遠い。記録できた事実と
  // 行き先が画面に出ないと、押せていないのか記録先が違うのかを区別できない。
  describe("見どころ記録の合図", () => {
    beforeEach(() => {
      state().current = { recording_id: 7, unique_id: "u1" };
      state().groups = [{ id: 3, name: "切り抜きA" }];
      win.fetch = async () =>
        new Response(JSON.stringify({ id: 99, items: [] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      // 画面の起動時のfetchはstub routeが無く全て404になり、errorのtoastは閉じるまで
      // 残る(showToastの仕様)。掃除せずに始めると、この後の記録操作が出した合図ではなく
      // 起動時のerrorを読んでしまう。
      const layer = doc.getElementById("toast-layer");
      if (layer) layer.replaceChildren();
    });

    // toastは新しいものほど後ろへ積まれる。読むのは今の操作が出した最後の1枚。
    const toastText = () => {
      const bodies = doc.querySelectorAll("#toast-layer .toast-body");
      const body = bodies[bodies.length - 1];
      return body ? body.textContent : null;
    };

    it("記録した時刻と行き先を画面内notificationに出す", async () => {
      await win.saveBookmark(65, null, "", null);
      expect(toastText()).toBe("★ 00:01:05 → 未分類");
      expect(doc.getElementById("player-status").textContent).toBe(toastText());
    });

    it("記録先グループを選んでいればその名前を出す", async () => {
      state().addGroup = "3";
      await win.saveBookmark(65, null, "", null);
      expect(toastText()).toBe("★ 00:01:05 → 切り抜きA");
    });

    it("範囲で記録したときはIN/OUTの両方を出す", async () => {
      await win.saveBookmark(65, 90, "", null);
      expect(toastText()).toBe("★ 00:01:05 - 00:01:30 → 未分類");
    });

    it("記録した位置をtimeline上で光らせる(点はendを持たない)", async () => {
      await win.saveBookmark(65, null, "", null);
      expect(page.get("markFlash")).toMatchObject({ start: 65, end: null });
      expect(win.markFlashAlpha()).toBeGreaterThan(0);
    });

    it("失敗したら成功の合図を出さない", async () => {
      win.fetch = async () =>
        new Response(JSON.stringify({ detail: "録画が見つかりません。" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        });
      await win.saveBookmark(65, null, "", null);
      expect(toastText()).toBe("録画が見つかりません。");
      expect(page.get("markFlash")).toBeNull();
    });
  });
});
