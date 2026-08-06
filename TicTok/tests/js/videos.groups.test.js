import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// グループ(切り抜き動画1本の単位)の画面。この機能の事故は「どこへ入ったか分からない」形で
// 出る — 記録先が見えないまま未分類へ落ちる、表示している範囲と書き出す範囲がずれる、
// 付け替えたつもりが別のグループへ入る。どれも画面上は正常に見えるので、
// 「表示・記録先・操作対象の3つが同じグループを指しているか」を実DOMで確かめる。
describe("videos.js のグループ", () => {
  let page;
  let win;
  let doc;
  let errorSpy;
  let posted;
  let playbacks;

  const GROUPS = [
    { id: 1, name: "神回", memo: "投稿用", created_at: 1 },
    { id: 2, name: "罵倒集", memo: "", created_at: 2 },
  ];
  // 神回のcutはposition順(=書き出し順)がstart順と食い違う並びにする。表がpositionでは
  // なくstartで並べてしまう退行は、この食い違いが無いと検出できない。
  const CUTS = [
    { id: 11, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 300, end: 330, label: "後の場面", group_id: 1, position: 0, filename: "a.mp4" },
    { id: 10, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 100, end: 160, label: "前の場面", group_id: 1, position: 1, filename: "a.mp4" },
    { id: 12, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 500, end: 520, label: "未整理", group_id: null, position: null, filename: "a.mp4" },
  ];
  const MARKS = [
    { id: 20, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 50, end: 70, memo: "範囲あり", group_id: 1 },
    { id: 21, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 80, end: null, memo: "点だけ", group_id: 1 },
    { id: 22, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 90, end: 95, memo: "未整理", group_id: null },
  ];

  function record({ url, method, init }) {
    posted.push({ url, method, body: init && init.body ? JSON.parse(init.body) : null });
    return { affected: 1, id: 99, name: "新規", memo: "" };
  }

  beforeEach(async () => {
    posted = [];
    playbacks = [];
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: {
        "/api/groups": { items: GROUPS },
        "/api/cutlist": { items: CUTS },
        "/api/bookmarks": { items: MARKS },
        "POST /api/cutlist/bulk": record,
        "POST /api/bookmarks/bulk": record,
        "POST /api/cutlist": record,
        "POST /api/bookmarks": record,
        "DELETE /api/bookmarks/20": record,
        "DELETE /api/cutlist/11": record,
        "/api/recordings/1/playback?variant=source": ({ url }) => {
          playbacks.push(url);
          return { recording_id: 1, variant: "source", mode: "mp4",
                   url: "/api/recordings/1/play" };
        },
      },
    });
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
  const tabsOf = (hostId) =>
    Array.from(doc.getElementById(hostId).querySelectorAll(".vd-group-pick"));
  const tabNames = (hostId) =>
    tabsOf(hostId).map((el) => el.querySelector(".vd-group-name").textContent);
  const cutRows = () => Array.from(doc.querySelectorAll("#cut-rows tr"));
  const cellsOf = (tr) => Array.from(tr.children).map((td) => td.textContent);

  describe("上段のグループtab", () => {
    it("集計の棚(全て・未分類)と実体のグループを両方並べる", () => {
      expect(tabNames("cuts-groups")).toEqual(["全て", "未分類", "神回", "罵倒集"]);
      // 見どころtabにも同じ棚が出る(片方にしか無いと、そのtabでは仕分けられない)。
      expect(tabNames("marks-groups")).toEqual(["全て", "未分類", "神回", "罵倒集"]);
    });

    it("内訳は件数と合計尺を出す(どのグループに素材が何分あるかで選ぶため)", () => {
      const meta = tabsOf("cuts-groups")[2].querySelector(".vd-group-meta").textContent;
      // 神回: cut 2件(30秒+60秒)・見どころ2件。
      expect(meta).toContain("切り出し 2");
      expect(meta).toContain("00:01:30");
      expect(meta).toContain("見どころ 2");
    });

    it("内訳は手元のlistから数える(表に出ている件数と必ず一致する)", () => {
      const ungrouped = tabsOf("cuts-groups")[1].querySelector(".vd-group-meta").textContent;
      expect(ungrouped).toContain("切り出し 1");
      expect(ungrouped).toContain("見どころ 1");
    });

    it("選択は両tabで共有する(片方で選んだグループへもう片方でも入っている)", () => {
      tabsOf("cuts-groups")[2].click();
      expect(state().groupSel).toBe("1");
      expect(tabsOf("marks-groups")[2].getAttribute("aria-pressed")).toBe("true");
      expect(doc.querySelectorAll("#mark-rows tr").length).toBe(2);
    });
  });

  describe("グループを選んだときの表示", () => {
    beforeEach(() => tabsOf("cuts-groups")[2].click());

    it("見出し・対象表示・listがすべて同じグループを指す", () => {
      expect(doc.getElementById("cuts-group-head").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("cuts-group-title").textContent).toBe("■ 神回");
      // 書き出し・連結・全削除が効く範囲は、押す前にこの1行で読める。
      expect(doc.getElementById("cuts-scope").textContent).toBe("対象: グループ「神回」");
      expect(doc.getElementById("cuts-group-stats").textContent).toContain("00:01:30");
      expect(cutRows().length).toBe(2);
    });

    it("並びはstartではなくposition(=書き出し順)", () => {
      // ラベルは書き出しfile名・EDLのclip名になるため、表の中で直せる入力欄にしてある。
      const labelOf = (tr) => tr.children[9].querySelector("input").value;
      expect(cutRows().map(labelOf)).toEqual(["後の場面", "前の場面"]);
    });

    it("頭出しは書き出し順に尺を積み上げた完成尺上の位置", () => {
      // 1本目は先頭(0秒)、2本目はその尺(30秒)ぶん後ろ。
      expect(cutRows().map((tr) => cellsOf(tr)[8])).toEqual(["00:00:00", "00:00:30"]);
      expect(cutRows().map((tr) => cellsOf(tr)[1])).toEqual(["1", "2"]);
    });

    it("グループの見どころを素材候補として同じ画面に出す", () => {
      expect(doc.getElementById("cuts-marks-block").classList.contains("hidden")).toBe(false);
      const rows = Array.from(doc.querySelectorAll("#cuts-mark-rows tr"));
      expect(rows.length).toBe(2);
      const promote = rows.map((tr) => tr.querySelector("button:last-child"));
      // 範囲付きだけがそのまま切り出しへ回せる(点はIN/OUTが決まっていない)。
      expect(promote.map((b) => b.disabled)).toEqual([false, true]);
    });

    it("素材候補の昇格は同じグループの切り出しへ入れる", async () => {
      doc.querySelector("#cuts-mark-rows tr button:last-child").click();
      await page.settle();
      const call = posted.find((p) => p.url === "/api/cutlist");
      expect(call.body).toMatchObject({ recording_id: 1, start: 50, end: 70, group_id: 1 });
    });

    it("グループを選んでいなければ順・頭出しは出さない(意味を持たないため)", () => {
      tabsOf("cuts-groups")[0].click();
      expect(doc.getElementById("cuts-group-head").classList.contains("hidden")).toBe(true);
      expect(doc.getElementById("cuts-marks-block").classList.contains("hidden")).toBe(true);
      expect(doc.getElementById("cuts-scope").textContent).toBe("対象: 切り出しリスト全体");
      expect(cutRows().map((tr) => cellsOf(tr)[1])).toEqual(["—", "—", "—"]);
    });
  });

  // 付け替えの経路は3つ(行のグループ欄・選択+移動先・tabへドラッグ)。1件だけ直すのが
  // 最も多い操作なので、そこに選択と画面上端への往復を強いないことが要件そのもの。
  // どの経路でも同じbulkへ同じ形で届くことを確かめる。
  describe("所属の付け替え", () => {
    const groupSelects = (tbodyId) =>
      Array.from(doc.querySelectorAll(`#${tbodyId} select.vd-gsel`));
    const change = (el, value) => {
      el.value = value;
      el.dispatchEvent(new win.Event("change", { bubbles: true }));
    };
    const fire = (el, type) =>
      el.dispatchEvent(new win.Event(type, { bubbles: true, cancelable: true }));
    const bulkCalls = (url) => posted.filter((p) => p.url === url);

    describe("行のグループ欄", () => {
      it("行は今の所属を名乗り、選択肢に全グループと新規を持つ", () => {
        const select = groupSelects("cut-rows")[0];
        expect(select.value).toBe("1");
        expect(Array.from(select.options).map((o) => o.textContent))
          .toEqual(["未分類", "神回", "罵倒集", "＋ 新しいグループ…"]);
        // 未分類の行は「まだ決めていない」ことが一覧の中で見分けられる。
        const ungrouped = groupSelects("cut-rows")[2];
        expect(ungrouped.value).toBe("none");
        expect(ungrouped.classList.contains("vd-gsel-none")).toBe(true);
      });

      it("選んだ瞬間にその行だけが移る(選択も上段への往復も要らない)", async () => {
        change(groupSelects("cut-rows")[0], "2");
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk").map((p) => p.body))
          .toEqual([{ op: "move", ids: [11], group_id: 2 }]);
      });

      it("未分類を選ぶとgroup_id=nullで戻す", async () => {
        change(groupSelects("cut-rows")[0], "none");
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk")[0].body)
          .toEqual({ op: "move", ids: [11], group_id: null });
      });

      it("1件直しても他の行の選択は消えない(まとめて動かす途中の手が壊れない)", async () => {
        const picks = doc.querySelectorAll("#cut-rows input[type=checkbox]");
        picks[1].click();
        picks[2].click();
        change(groupSelects("cut-rows")[0], "2");
        await page.settle();
        expect([...state().cutsSelected].sort()).toEqual([10, 12]);
      });

      it("見どころも同じ欄で移せる(専用のbulkへ行く)", async () => {
        change(groupSelects("mark-rows")[0], "2");
        await page.settle();
        expect(bulkCalls("/api/bookmarks/bulk").map((p) => p.body))
          .toEqual([{ op: "move", ids: [20], group_id: 2 }]);
      });
    });

    describe("選択と移動先", () => {
      it("選択が無い間は行き先buttonを押せない", () => {
        expect(doc.getElementById("cuts-move").disabled).toBe(true);
        expect(doc.getElementById("cuts-copy").disabled).toBe(true);
        doc.querySelector("#cut-rows input[type=checkbox]").click();
        expect(doc.getElementById("cuts-move").disabled).toBe(false);
        expect(doc.getElementById("cuts-move").textContent).toContain("1件");
      });

      it("移動先は件数付きで並べる(溜まっている先を取り違えない)", () => {
        expect(Array.from(doc.getElementById("cuts-move-target").options)
          .map((o) => o.textContent)).toEqual(["未分類", "神回（2）", "罵倒集（0）"]);
      });

      it("選択した行を移動先へまとめて入れる", async () => {
        doc.querySelector("#cut-rows input[type=checkbox]").click();
        change(doc.getElementById("cuts-move-target"), "2");
        doc.getElementById("cuts-move").click();
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk")[0].body)
          .toEqual({ op: "move", ids: [11], group_id: 2 });
      });

      it("切り出しは複製できる(グループごとにIN/OUTを詰め直せる)", async () => {
        doc.querySelector("#cut-rows input[type=checkbox]").click();
        change(doc.getElementById("cuts-move-target"), "2");
        doc.getElementById("cuts-copy").click();
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk")[0].body)
          .toEqual({ op: "copy", ids: [11], group_id: 2 });
        // 元の行は残るので、続けて別のグループへも配れる。
        expect(state().cutsSelected.size).toBe(1);
      });

      it("見どころは複製しない(同じ位置の点を2つ持っても区別が付かない)", () => {
        expect(doc.getElementById("marks-copy")).toBeNull();
      });

      it("見どころの付け替えは専用のbulkへ行く", async () => {
        doc.querySelector("#mark-rows input[type=checkbox]").click();
        change(doc.getElementById("marks-move-target"), "2");
        doc.getElementById("marks-move").click();
        await page.settle();
        expect(bulkCalls("/api/bookmarks/bulk")[0].body)
          .toEqual({ op: "move", ids: [20], group_id: 2 });
      });

      it("shift+クリックで直前に選んだ行からここまでを選ぶ", () => {
        const picks = doc.querySelectorAll("#cut-rows input[type=checkbox]");
        picks[0].click();
        picks[2].dispatchEvent(new win.MouseEvent("click", {
          bubbles: true, cancelable: true, shiftKey: true,
        }));
        expect(state().cutsSelected.size).toBe(3);
        // checkも実際に付いている(表示と対象がずれない)。
        expect(Array.from(doc.querySelectorAll("#cut-rows input[type=checkbox]"))
          .map((el) => el.checked)).toEqual([true, true, true]);
      });

      it("shift+クリックの解除も範囲で効く", () => {
        doc.getElementById("cuts-select-all").checked = true;
        doc.getElementById("cuts-select-all").dispatchEvent(new win.Event("change"));
        expect(state().cutsSelected.size).toBe(3);
        const picks = doc.querySelectorAll("#cut-rows input[type=checkbox]");
        picks[0].click();
        picks[2].dispatchEvent(new win.MouseEvent("click", {
          bubbles: true, cancelable: true, shiftKey: true,
        }));
        expect(state().cutsSelected.size).toBe(0);
      });
    });

    describe("tabへのドラッグ", () => {
      const dropOn = (tabIndex, tbodyId, rowIndex) => {
        const row = doc.querySelectorAll(`#${tbodyId} tr`)[rowIndex];
        const target = tabsOf("cuts-groups")[tabIndex].parentElement;
        fire(row, "dragstart");
        fire(target, "dragover");
        fire(target, "drop");
      };

      it("行をtabへ落とすとそのグループへ入る", async () => {
        dropOn(3, "cut-rows", 0);
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk")[0].body)
          .toEqual({ op: "move", ids: [11], group_id: 2 });
      });

      it("選択済みの行を掴んだら選択ぶん全部を運ぶ", async () => {
        const picks = doc.querySelectorAll("#cut-rows input[type=checkbox]");
        picks[0].click();
        picks[1].click();
        dropOn(3, "cut-rows", 0);
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk")[0].body.ids.sort()).toEqual([10, 11]);
      });

      it("選択していない行を掴んだらその行だけ運ぶ(無関係の行を巻き込まない)", async () => {
        doc.querySelectorAll("#cut-rows input[type=checkbox]")[0].click();
        dropOn(3, "cut-rows", 1);
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk")[0].body.ids).toEqual([10]);
      });

      it("「全て」は受け取らない(所属の指定にならないため)", async () => {
        dropOn(0, "cut-rows", 0);
        await page.settle();
        expect(bulkCalls("/api/cutlist/bulk").length).toBe(0);
      });
    });

    it("表示から消えた行の選択は捨てる(見えない行への一括操作を残さない)", () => {
      doc.querySelector("#cut-rows input[type=checkbox]").click();
      expect(state().cutsSelected.size).toBe(1);
      tabsOf("cuts-groups")[3].click();
      expect(state().cutsSelected.size).toBe(0);
    });

    it("絞り込みを変えても表示に残る行の選択は保つ", () => {
      // 「全て」で神回の行を選んでから神回のtabへ移る。同じ行が見えているので、
      // 選び直しにはならない。
      doc.querySelector("#cut-rows input[type=checkbox]").click();
      tabsOf("cuts-groups")[2].click();
      expect([...state().cutsSelected]).toEqual([11]);
    });
  });

  describe("記録先", () => {
    const chips = () => Array.from(doc.querySelectorAll("#dest-groups .vd-chip"));

    it("選択肢を畳まず並べる(今どこへ入るかが常に見える)", () => {
      expect(chips().map((c) => c.textContent))
        .toEqual(["未分類", "神回（4）", "罵倒集（0）", "＋ 新規", "＋ 検索語で作る"]);
      expect(chips()[0].getAttribute("aria-checked")).toBe("true");
    });

    it("chipを選ぶと以後の追加がそのグループへ入る", async () => {
      chips()[1].click();
      expect(chips()[1].getAttribute("aria-checked")).toBe("true");
      expect(win.currentAddGroupId()).toBe(1);
      // 確認はtoastへ出す。player-statusは切り出しpathやerrorの置き場で、記録先を
      // 変えただけで復元できない出力pathが消えてはいけない。
      expect(doc.querySelector(".toast-layer").textContent).toContain("神回");
      expect(doc.getElementById("player-status").textContent).not.toContain("神回");
      // 記録先は録画を跨いで使い回すので残す。
      expect(win.localStorage.getItem("tictok.videos.cutGroup")).toBe("1");
    });

    it("記録先は上段tabの表示選択とは別物(見る場所と入れる場所は独立)", () => {
      chips()[1].click();
      tabsOf("cuts-groups")[3].click();
      expect(state().groupSel).toBe("2");
      expect(win.currentAddGroupId()).toBe(1);
    });

    it("消えたグループを指したままにしない", async () => {
      chips()[1].click();
      tabsOf("cuts-groups")[2].click();
      expect(state().groupSel).toBe("1");
      // 「神回」が消えた状態で引き直す。
      serve(() => ({ items: [GROUPS[1]] }));
      await page.run("refreshGroupData()");
      expect(win.currentAddGroupId()).toBeNull();
      expect(state().groupSel).toBe("");
    });

    it("取得に失敗しても手元のlistは捨てない(消えたと誤認させない)", async () => {
      chips()[1].click();
      tabsOf("cuts-groups")[2].click();
      serve(() => { throw new Error("network down"); });
      const failure = await page.run("refreshGroupData()");
      expect(failure).toBeTruthy();
      // 0件で描き直すと「グループが消えた」と読めてしまう。選択も記録先も保つ。
      expect(state().groups.length).toBe(2);
      expect(state().groupSel).toBe("1");
      expect(win.currentAddGroupId()).toBe(1);
    });
  });

  // 見どころは「観て確かめる」ためにある。tabを跨がずに観られること、範囲がどこまでかが
  // 観ているだけで分かること、観ている対象と画面上の身元が一致していることを確かめる。
  describe("見どころの視聴", () => {
    const markRows = () => Array.from(doc.querySelectorAll("#mark-rows tr"));
    const buttonsOf = (tr) => Array.from(tr.querySelectorAll("td:last-child button"));
    // 位置ではなく文言で掴む(buttonが1つ増えるたびに無関係のtestが落ちる)。
    const buttonOf = (tr, label) => buttonsOf(tr).find((b) => b.textContent === label);
    const markVideo = () => doc.getElementById("mark-video");
    const status = () => doc.getElementById("mark-play-status").textContent;
    // 1件削除は確認を挟む(取り消せないうえ、視聴・切り出しへと同じ行に並ぶ)。
    // 確認を越えないと本体の挙動を確かめられないので、応答を1箇所に寄せる。
    const answerConfirm = (accept) => {
      const modal = doc.querySelector(".confirm-modal");
      if (!modal) throw new Error("確認dialogが出ていません");
      const buttons = Array.from(modal.querySelectorAll(".confirm-actions button"));
      buttons[accept ? buttons.length - 1 : 0].click();
    };

    /** jsdomの<video>はcurrentTimeを実装しないので、値を持つだけのpropertyに置き換える。 */
    function setCurrentTime(seconds) {
      Object.defineProperty(markVideo(), "currentTime", {
        configurable: true, writable: true, value: seconds,
      });
    }

    async function watch(index) {
      buttonsOf(markRows()[index])[0].click();
      await page.settle();
    }

    // 見どころtabを開いた状態から始める(この機能は「そのtabのまま観る」ためのもの)。
    beforeEach(() => doc.getElementById("tab-marks").click());

    it("行は「視聴」と「シーン検索視聴」を並べる(この場で観るか、道具付きで観るか)", () => {
      expect(buttonsOf(markRows()[0]).map((b) => b.textContent))
        .toEqual(["視聴", "シーン検索視聴", "切り出しへ", "削除"]);
    });

    it("「視聴」は見どころtabのまま再生する(観るたびtabを往復させない)", async () => {
      await watch(0);
      expect(doc.getElementById("mark-play").classList.contains("hidden")).toBe(false);
      expect(markVideo().getAttribute("src")).toBe("/api/recordings/1/play");
      expect(doc.getElementById("view-marks").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(true);
      // 観ている対象は行と同じ身元(配信者・配信日時・範囲)で名乗る。素材版もここで
      // 名乗る — この場の再生は常に元録画なので、焼き込みの出来を確かめたつもりで
      // 素の映像を観て「焼き込みが失敗している」と誤読するのを防ぐ。
      const head = doc.getElementById("mark-play-head").textContent;
      expect(head.startsWith("alice / ")).toBe(true);
      expect(head).toContain(" / 00:00:50 - 00:01:10");
      expect(head.endsWith(" / 素材: 元録画")).toBe(true);
    });

    it("尺が分かった時点で見どころの位置へ入る", async () => {
      setCurrentTime(0);
      await watch(0);
      markVideo().dispatchEvent(new win.Event("loadedmetadata"));
      expect(markVideo().currentTime).toBe(50);
    });

    it("範囲付きは終端で一度止める(どこまでが見どころか観ているだけで分かる)", async () => {
      await watch(0);
      setCurrentTime(70);
      markVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).toContain("終端");
      // 解除するので、続きを観たければ再生を押すだけでよい。
      setCurrentTime(200);
      doc.getElementById("mark-play-status").textContent = "";
      markVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).toBe("");
    });

    it("範囲の無い点は止めない(終端が無いため)", async () => {
      await watch(1);
      setCurrentTime(9999);
      markVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).not.toContain("終端");
    });

    it("同じ録画の別の見どころは読み込み直さずseekだけで移る", async () => {
      setCurrentTime(0);
      await watch(0);
      markVideo().dispatchEvent(new win.Event("loadedmetadata"));
      await watch(1);
      expect(playbacks.length).toBe(1);
      // jsdomは尺を持たないので位置決めはmetadata待ちのまま。実browserは読み込み済みで
      // 即座に入る(readyStateで分岐する)。ここでは待ちが解けた時の位置を見る。
      markVideo().dispatchEvent(new win.Event("loadedmetadata"));
      expect(markVideo().currentTime).toBe(80);
    });

    it("観ている見どころを消したらplayerを下げる(実体の無い行を観続けない)", async () => {
      await watch(0);
      buttonOf(markRows()[0], "削除").click();
      await page.settle();
      answerConfirm(true);
      await page.settle();
      expect(doc.getElementById("mark-play").classList.contains("hidden")).toBe(true);
      expect(markVideo().hasAttribute("src")).toBe(false);
    });

    // 1件削除は最も高頻度で、しかも取り消せない。まとめて削除する側にだけ確認があり、
    // 誤clickしやすい方が素通しだと、押した瞬間に詰めた範囲が消える。
    it("1件削除は確認を挟み、取り消せば消えない", async () => {
      const before = markRows().length;
      buttonOf(markRows()[0], "削除").click();
      await page.settle();
      answerConfirm(false);
      await page.settle();
      expect(markRows().length).toBe(before);
      expect(posted.some((p) => p.method === "DELETE")).toBe(false);
    });

    // 一覧(左)と視聴(右)は横並びなので、右が畳まれると左の表幅が観るたびに動く。
    // playerを下げている間は同じ場所に案内を出し、列そのものは残す。
    it("観ていない間は視聴側に案内を出す(右列を畳んで表幅を動かさない)", async () => {
      const placeholder = () => doc.getElementById("mark-play-empty");
      expect(placeholder().classList.contains("hidden")).toBe(false);
      await watch(0);
      expect(placeholder().classList.contains("hidden")).toBe(true);
      doc.getElementById("mark-play-close").click();
      expect(placeholder().classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("mark-play").classList.contains("hidden")).toBe(true);
    });

    it("「シーン検索視聴」はシーン検索の再生画面へ移る", async () => {
      buttonOf(markRows()[0], "シーン検索視聴").click();
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("tab-search").classList.contains("active")).toBe(true);
      await page.settle();
    });
  });

  // 切り出しリストも「観て確かめる」場所。詰めた範囲が狙い通りかを1件ずつ確かめる作業なので、
  // 見どころtabと同じく、そのtabのまま観られること・OUTがどこかが観ているだけで分かることを
  // 確かめる。playerは見どころとは別instanceなので、片方の再生がもう片方を壊さないことも見る。
  describe("切り出しリストの視聴", () => {
    const buttonsOf = (tr) => Array.from(tr.querySelectorAll("td:last-child button"));
    // 位置ではなく文言で掴む(buttonが1つ増えるたびに無関係のtestが落ちる)。
    const buttonOf = (tr, label) => buttonsOf(tr).find((b) => b.textContent === label);
    const cutVideo = () => doc.getElementById("cut-video");
    const status = () => doc.getElementById("cut-play-status").textContent;
    const answerConfirm = (accept) => {
      const modal = doc.querySelector(".confirm-modal");
      if (!modal) throw new Error("確認dialogが出ていません");
      const buttons = Array.from(modal.querySelectorAll(".confirm-actions button"));
      buttons[accept ? buttons.length - 1 : 0].click();
    };

    /** jsdomの<video>はcurrentTimeを実装しないので、値を持つだけのpropertyに置き換える。 */
    function setCurrentTime(seconds) {
      Object.defineProperty(cutVideo(), "currentTime", {
        configurable: true, writable: true, value: seconds,
      });
    }

    async function watch(index) {
      buttonOf(cutRows()[index], "視聴").click();
      await page.settle();
    }

    beforeEach(() => doc.getElementById("tab-cuts").click());

    it("行は「視聴」と「シーン検索視聴」を並べる(この場で観るか、道具付きで観るか)", () => {
      expect(buttonsOf(cutRows()[0]).map((b) => b.textContent))
        .toEqual(["視聴", "シーン検索視聴", "削除"]);
    });

    it("「視聴」は切り出しリストtabのまま再生する(観るたびtabを往復させない)", async () => {
      await watch(0);
      expect(doc.getElementById("cut-play").classList.contains("hidden")).toBe(false);
      expect(cutVideo().getAttribute("src")).toBe("/api/recordings/1/play");
      expect(doc.getElementById("view-cuts").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(true);
      // 観ている対象は行と同じ身元(配信者・配信日時・IN/OUT)で名乗る。素材版もここで
      // 名乗る — 上の「素材」で焼き込みを選んでいても、この場の再生は常に元録画なので、
      // 焼き込みの出来を確かめたつもりで素の映像を観て誤読するのを防ぐ。
      const head = doc.getElementById("cut-play-head").textContent;
      expect(head.startsWith("alice / ")).toBe(true);
      expect(head).toContain(" / 00:05:00 - 00:05:30");
      expect(head.endsWith(" / 素材: 元録画")).toBe(true);
    });

    it("尺が分かった時点でINへ入る", async () => {
      setCurrentTime(0);
      await watch(0);
      cutVideo().dispatchEvent(new win.Event("loadedmetadata"));
      expect(cutVideo().currentTime).toBe(300);
    });

    it("OUTで一度止める(どこまでが切り出しか観ているだけで分かる)", async () => {
      await watch(0);
      setCurrentTime(330);
      cutVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).toContain("終端");
      // 解除するので、続きを観たければ再生を押すだけでよい。
      setCurrentTime(400);
      doc.getElementById("cut-play-status").textContent = "";
      cutVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).toBe("");
    });

    it("同じ録画の別の切り出しは読み込み直さずseekだけで移る", async () => {
      setCurrentTime(0);
      await watch(0);
      cutVideo().dispatchEvent(new win.Event("loadedmetadata"));
      await watch(1);
      expect(playbacks.length).toBe(1);
      cutVideo().dispatchEvent(new win.Event("loadedmetadata"));
      expect(cutVideo().currentTime).toBe(100);
    });

    it("観ている切り出しを消したらplayerを下げる(実体の無い行を観続けない)", async () => {
      await watch(0);
      buttonOf(cutRows()[0], "削除").click();
      await page.settle();
      answerConfirm(true);
      await page.settle();
      expect(doc.getElementById("cut-play").classList.contains("hidden")).toBe(true);
      expect(cutVideo().hasAttribute("src")).toBe(false);
    });

    it("観ていない間は視聴側に案内を出す(右列を畳んで表幅を動かさない)", async () => {
      const placeholder = () => doc.getElementById("cut-play-empty");
      expect(placeholder().classList.contains("hidden")).toBe(false);
      await watch(0);
      expect(placeholder().classList.contains("hidden")).toBe(true);
      doc.getElementById("cut-play-close").click();
      expect(placeholder().classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("cut-play").classList.contains("hidden")).toBe(true);
    });

    it("「シーン検索視聴」はIN/OUTが入った状態でシーン検索へ移る", async () => {
      buttonOf(cutRows()[0], "シーン検索視聴").click();
      await page.settle();
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("tab-search").classList.contains("active")).toBe(true);
      expect(state().cutIn).toBe(300);
      expect(state().cutOut).toBe(330);
    });

    // 見どころと切り出しは別々の<video>で持つ。1つを共有すると、tabを移るたびに相手の
    // 位置と読み込みを壊し合う。
    it("見どころtabへ移っても切り出しの読み込みは捨てない(音だけ止める)", async () => {
      await watch(0);
      doc.getElementById("tab-marks").click();
      await page.settle();
      expect(cutVideo().getAttribute("src")).toBe("/api/recordings/1/play");
      expect(cutVideo().paused).toBe(true);
      expect(doc.getElementById("cut-play").classList.contains("hidden")).toBe(false);
    });
  });

  // 昇格の経路は切り出しリストtab側の作業台にもあるが、そちらはグループを選んだ時だけ
  // 現れる。見どころを見ている画面にも同じ経路が無いと、範囲を決めた後の行き先が
  // どこにも出ていない状態になる。
  describe("見どころtabからの昇格", () => {
    const markRows = () => Array.from(doc.querySelectorAll("#mark-rows tr"));
    const rowOf = (memo) =>
      markRows().find((tr) => tr.querySelector("input.vd-memo").value === memo);
    const buttonOf = (tr, label) =>
      Array.from(tr.querySelectorAll("td:last-child button"))
        .find((b) => b.textContent === label);

    beforeEach(() => doc.getElementById("tab-marks").click());

    it("未分類の見どころも所属を変えずに切り出しリストへ入る", async () => {
      buttonOf(rowOf("未整理"), "切り出しへ").click();
      await page.settle();
      const call = posted.find((p) => p.url === "/api/cutlist");
      expect(call.body).toMatchObject({ recording_id: 1, start: 90, end: 95, group_id: null });
      // 結果は押したtab側に出す(切り出しリストtabへ書くと見えない画面に出る)。
      expect(doc.getElementById("marks-status").textContent).toContain("未分類");
    });

    it("グループ付きは入り先の名前を出す(どこへ入ったか押した後に読める)", async () => {
      buttonOf(rowOf("範囲あり"), "切り出しへ").click();
      await page.settle();
      const call = posted.find((p) => p.url === "/api/cutlist");
      expect(call.body).toMatchObject({ start: 50, end: 70, group_id: 1, label: "範囲あり" });
      expect(doc.getElementById("marks-status").textContent).toContain("神回");
    });

    it("範囲の無い点は押せない(IN/OUTが決まっていない)", () => {
      expect(buttonOf(rowOf("点だけ"), "切り出しへ").disabled).toBe(true);
      expect(buttonOf(rowOf("範囲あり"), "切り出しへ").disabled).toBe(false);
    });
  });

  // jsdomのwindowはResponseを持たないので、応答はNode側のglobalで組んで渡す。
  function serve(handler) {
    win.fetch = () => {
      let body;
      try {
        body = handler();
      } catch (err) {
        return Promise.reject(err);
      }
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    };
  }
});
