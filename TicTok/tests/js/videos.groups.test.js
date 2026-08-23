import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// グループ(切り抜き動画1本の単位)と、その中身である見どころの画面。
// 見どころは印であり、同時に切り出しの素材でもある(尺を持つ行だけがmp4にできる)。
// この機能の事故は「どこへ入ったか分からない」形で出る — 記録先が見えないまま未分類へ
// 落ちる、表示している範囲と書き出す範囲がずれる、付け替えたつもりが別のグループへ入る。
// どれも画面上は正常に見えるので、「表示・記録先・操作対象の3つが同じグループを指して
// いるか」を実DOMで確かめる。
describe("videos.js のグループと見どころ", () => {
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
  // 神回のposition順(=書き出し順)がstart順と食い違う並びにする。表がpositionではなく
  // startで並べてしまう退行は、この食い違いが無いと検出できない。
  // 点(尺の無い行)も同じ表に混ぜる — mp4にできるのは尺のある行だけ、という区別が
  // 同じ表の中で成り立っていることがこの統合の前提そのものである。
  const MARKS = [
    { id: 11, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 300, end: 330, memo: "後の場面", group_id: 1, position: 0,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 10, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 100, end: 160, memo: "前の場面", group_id: 1, position: 1,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 21, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 80, end: null, memo: "点だけ", group_id: 1, position: 2,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 12, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 500, end: 520, memo: "未整理", group_id: null, position: null,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
  ];

  function record({ url, method, init }) {
    posted.push({ url, method, body: init && init.body ? JSON.parse(init.body) : null });
    return { affected: 1, id: 99, name: "新規", memo: "" };
  }

  // 既定のroute一式。上書きを受けられる形にしてあるのは、「型が1件も無い」のように
  // serverの応答そのものが違う状態を、別のtest fileを作らずに開けるようにするため。
  const baseRoutes = () => ({
    "/api/groups": { items: GROUPS },
    "/api/bookmarks": { items: MARKS },
    "POST /api/bookmarks/bulk": record,
    "POST /api/bookmarks": record,
    "DELETE /api/bookmarks": record,
    "DELETE /api/bookmarks?group=1": record,
    "POST /api/groups/1/order": record,
    "POST /api/clips/batch": (call) => {
      record(call);
      const items = JSON.parse(call.init.body).items;
      return { total: items.length, jobs: ["job-1"] };
    },
    "POST /api/reels": (call) => {
      record(call);
      return { parts: JSON.parse(call.init.body).items.length, job_id: "job-2" };
    },
    "/api/clip-presets": {
      presets: [{ id: 7, name: "短尺 (15〜60秒)", target_seconds: 45 }], fields: {},
    },
    "/api/groups/1/work-plan?preset_id=7": (call) => {
      record(call);
      return {
        group_id: 1, group: "神回", scene_count: 2, requested_seconds: 90,
        burns: ["字幕"], tighten: true, upscale: false, cache_bytes: 0, blocking: [],
        scenes: [{ position: 1, part_ready: false }, { position: 2, part_ready: false }],
      };
    },
    "POST /api/groups/1/work": (call) => {
      record(call);
      return { job_id: "job-3", group_id: 1, group: "神回", scenes: 4 };
    },
    "DELETE /api/bookmarks/10": record,
    "DELETE /api/bookmarks/11": record,
    "DELETE /api/bookmarks/21": record,
    "PATCH /api/bookmarks/10": record,
    "PATCH /api/bookmarks/11": record,
    "PATCH /api/bookmarks/12": record,
    "PATCH /api/bookmarks/21": record,
    "/api/recordings/1/playback?variant=source": ({ url }) => {
      playbacks.push(url);
      return { recording_id: 1, variant: "source", mode: "mp4",
               url: "/api/recordings/1/play" };
    },
  });

  async function open(overrides = {}) {
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: { ...baseRoutes(), ...overrides },
    });
    win = page.win;
    doc = page.document;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  }

  beforeEach(async () => {
    posted = [];
    playbacks = [];
    await open();
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
  const markRows = () => Array.from(doc.querySelectorAll("#mark-rows tr"));
  const cellsOf = (tr) => Array.from(tr.children).map((td) => td.textContent);
  // 列は 視聴・選択・順・出所・配信者・配信日・位置・尺・メモ・グループ・操作。
  const COL = { order: 2, origin: 3, who: 4, day: 5, start: 6, span: 7, memo: 8 };
  const fieldOf = (index, col) => markRows()[index].children[col].querySelector("input");
  const memoOf = (tr) => tr.children[COL.memo].querySelector("input").value;

  describe("左の縦paneのグループ棚", () => {
    it("集計の棚(全て・未分類)と実体のグループを両方並べる", () => {
      expect(tabNames("marks-groups")).toEqual(["全て", "未分類", "神回", "罵倒集"]);
    });

    // 棚を選ぶ根拠は「そのグループに素材が何分あるか」。点は素材にならないので、
    // 全件と「尺のある件数」を分けて出さないと、件数と合計尺が噛み合わない。
    it("内訳は全件と尺のある件数・合計尺を出す", () => {
      const meta = tabsOf("marks-groups")[2].querySelector(".vd-group-meta").textContent;
      expect(meta).toContain("3件");
      expect(meta).toContain("尺あり 2");
      expect(meta).toContain("00:01:30");
    });

    it("内訳は手元のlistから数える(表に出ている件数と必ず一致する)", () => {
      expect(tabsOf("marks-groups")[1].querySelector(".vd-group-meta").textContent)
        .toContain("1件");
    });

    it("尺のある行が1つも無い棚では合計尺を出さない(0秒の素材があると読める)", async () => {
      await page.close();
      await open({ "/api/bookmarks": { items: [MARKS[2]] } });
      expect(tabsOf("marks-groups")[2].querySelector(".vd-group-meta").textContent)
        .toBe("1件");
    });

    it("棚を選ぶとその中身だけが並ぶ", () => {
      tabsOf("marks-groups")[2].click();
      expect(state().groupSel).toBe("1");
      expect(markRows().length).toBe(3);
    });
  });

  describe("グループを選んだときの表示", () => {
    beforeEach(() => tabsOf("marks-groups")[2].click());

    // 見出し帯は廃した(帯1本ぶんの縦を主役へ回すため)。今どのグループの何を並べて
    // いるかは表の見出し行が名乗り、範囲は書き出し帯の「対象:」が持つ。
    it("表の見出し・対象表示・listがすべて同じグループを指す", () => {
      expect(doc.getElementById("marks-list-title").textContent)
        .toBe("■ 神回 ／ 見どころ（書き出し順）");
      // 書き出し・連結が効く範囲は、押す前にこの1行で読める。点は対象に入らないので、
      // 落ちる件数もここで名乗る(黙って落とすと表の件数と本数が食い違う)。
      expect(doc.getElementById("cuts-scope").textContent)
        .toBe("対象: グループ「神回」の2件／点 1件は対象外");
      // グループを選んでいる間の合計尺は、そのまま切り抜き1本の完成尺になる。
      expect(doc.getElementById("marks-summary").textContent)
        .toBe("3件（尺あり 2・点 1） / 完成尺 00:01:30");
      expect(markRows().length).toBe(3);
    });

    it("並びはstartではなくposition(=書き出し順)", () => {
      expect(markRows().map(memoOf)).toEqual(["後の場面", "前の場面", "点だけ"]);
    });

    it("順は書き出し順そのもの(表示順の番号)", () => {
      expect(markRows().map((tr) => cellsOf(tr)[COL.order])).toEqual(["1", "2", "3"]);
    });

    // メモは棚の足元に置く(見出し帯を1本畳むため)。棚と同じ列なので「今選んでいる棚」の
    // すぐ下で読める。
    it("メモは棚の足元に出て、どのグループのメモかを名乗る", () => {
      const memo = doc.getElementById("marks-group-memo");
      expect(memo.classList.contains("hidden")).toBe(false);
      expect(memo.value).toBe("投稿用");
      expect(doc.getElementById("marks-groups").querySelector(".vd-gside-memocap").textContent)
        .toBe("神回 のメモ");
    });

    it("グループを選んでいなければ順は出さない(意味を持たないため)", () => {
      tabsOf("marks-groups")[0].click();
      expect(doc.getElementById("marks-list-title").textContent).toBe("■ 見どころ");
      // どのグループのメモでもない状態では欄を出さない(空欄に打てば消えたように見える)。
      expect(doc.getElementById("marks-group-memo").classList.contains("hidden")).toBe(true);
      expect(doc.getElementById("cuts-scope").textContent)
        .toBe("対象: 見どころ全体の3件／点 1件は対象外");
      expect(markRows().map((tr) => cellsOf(tr)[COL.order])).toEqual(["—", "—", "—", "—"]);
      // 全行が「—」になる列(順)は畳む。
      expect(doc.getElementById("mark-table").classList.contains("vd-cutlist-flat"))
        .toBe(true);
    });

    // グループを選んでいない間に並ぶのは書き出し順を持たない行なので、並べる根拠は
    // 素材の時間軸(配信日→開始位置)しかない。serverが返す順(配信者ごとの塊)のまま
    // 出すと、同じ日の別配信がlistの端と端へ離れる。
    it("グループを選んでいない間は配信日順・同じ配信の中は開始位置順", () => {
      tabsOf("marks-groups")[0].click();
      expect(markRows().map((_, i) => fieldOf(i, COL.start).value))
        .toEqual(["00:01:20.0", "00:01:40.0", "00:05:00.0", "00:08:20.0"]);
    });
  });

  // shortの自動生成は作った範囲を見どころへ書き戻す。人が付けた印と混ぜて並べると、
  // 覚えの無い行が一覧を埋めるので既定では出さない(消えたのではなく隠れている)。
  describe("自動生成の行", () => {
    const AUTO = { id: 40, recording_id: 1, unique_id: "alice", recording_started_at: 100,
                   start: 700, end: 730, memo: "", group_id: null, position: null,
                   origin: "auto", pts_mapped: 1, filename: "a.mp4" };

    beforeEach(async () => {
      await page.close();
      await open({ "/api/bookmarks": { items: [...MARKS, AUTO] } });
    });

    it("既定では出さない(人が付けた印と混ぜない)", () => {
      expect(markRows().length).toBe(4);
      expect(doc.getElementById("marks-show-auto").checked).toBe(false);
      // 出所の列も畳む(全行が「—」になる)。
      expect(doc.getElementById("mark-table").classList.contains("vd-hide-origin"))
        .toBe(true);
    });

    it("出すと表に並び、出所の列で名乗る", () => {
      doc.getElementById("marks-show-auto").click();
      expect(markRows().length).toBe(5);
      const auto = markRows().find((tr) => memoOf(tr) === "");
      expect(cellsOf(auto)[COL.origin]).toBe("自動");
      expect(doc.getElementById("mark-table").classList.contains("vd-hide-origin"))
        .toBe(false);
      // 次に開いた時も同じ見え方で始める。
      expect(win.localStorage.getItem("tictok.videos.showAutoMarks")).toBe("1");
    });

    it("隠れている間は書き出しの対象にも入らない(見えない行がqueueへ入らない)", async () => {
      doc.getElementById("cuts-export").click();
      await page.settle();
      const starts = posted.find((p) => p.url === "/api/clips/batch").body.items
        .map((i) => i.start);
      expect(starts).not.toContain(700);
    });
  });

  // shortの自動生成が同じ場面を二度作ると、範囲しか持たない(メモの空の)行が並び、
  // 行だけを読んでも何が何だか分からなくなる。作らせない側はserverで塞ぐが、
  // 既に在る重複は行が自分で名乗る。
  describe("同じ範囲が並んだとき", () => {
    const TWINS = [
      { id: 31, recording_id: 1, unique_id: "alice", recording_started_at: 100,
        start: 100, end: 130, memo: "", group_id: 1, position: 0,
        origin: "manual", pts_mapped: 1, filename: "a.mp4" },
      { id: 32, recording_id: 1, unique_id: "alice", recording_started_at: 100,
        start: 100, end: 130, memo: "", group_id: 2, position: 0,
        origin: "manual", pts_mapped: 1, filename: "a.mp4" },
      { id: 33, recording_id: 1, unique_id: "alice", recording_started_at: 100,
        start: 200, end: 230, memo: "", group_id: 1, position: 1,
        origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    ];
    const dupOf = (tr) => tr.querySelector(".vd-src-dup");

    beforeEach(async () => {
      await page.close();
      await open({ "/api/bookmarks": { items: TWINS } });
    });

    it("同じ範囲の行だけが「重複」を名乗る", () => {
      expect(markRows().map((tr) => (dupOf(tr) ? dupOf(tr).textContent : null)))
        .toEqual(["重複2", "重複2", null]);
    });

    // 別のグループへ入っていても、書き出せば同じmp4がその件数ぶん出る。
    it("グループを跨いだ重複も数え、どこに在るかを名乗る", () => {
      expect(dupOf(markRows()[0]).title).toContain("2件");
      expect(dupOf(markRows()[0]).title).toContain("神回・罵倒集");
    });

    // 印を出しても、どちらを残すかは中身でしか決められない。確かめる手は1列目に在る。
    it("重複の行も1列目の「視聴」でその場で観られる", () => {
      expect(markRows()[0].children[0].querySelector("button").textContent).toBe("視聴");
    });

    // 印は範囲だけで数えるが、消してよいのは同じ棚に並んだ余りだけである。グループを
    // 跨いだ複製はグループごとにIN/OUTを詰めるための意図した操作で、片割れを消すと
    // 人が組んだ棚が崩れる。
    it("グループを跨いだ重複は消す対象にしない", () => {
      expect(doc.getElementById("cuts-dup-select").disabled).toBe(true);
    });

    describe("同じグループに同じ範囲が2行在るとき", () => {
      const SAME = [
        ...TWINS.slice(0, 1),
        { ...TWINS[1], id: 34, group_id: 1, position: 2 },
        TWINS[2],
      ];

      beforeEach(async () => {
        await page.close();
        await open({ "/api/bookmarks": { items: SAME } });
      });

      // 選ぶだけで消さない。押した瞬間に行が消えると、どちらを残すかを中身で決める手が
      // 無くなる(自動生成が作った行はメモを持たず、行だけを読んでも区別が付かない)。
      it("各組の先頭を残して余りだけを選び、削除は別の手に残す", async () => {
        doc.getElementById("cuts-dup-select").click();
        expect([...state().marksSelected]).toEqual([34]);
        expect(doc.getElementById("marks-bulk-delete").disabled).toBe(false);
        await page.settle();
        expect(posted.filter((p) => p.url === "/api/bookmarks/bulk")).toHaveLength(0);
      });
    });
  });

  // 付け替えの経路は3つ(行のグループ欄・選択+移動先・tabへドラッグ)。1件だけ直すのが
  // 最も多い操作なので、そこに選択と画面上端への往復を強いないことが要件そのもの。
  // どの経路でも同じbulkへ同じ形で届くことを確かめる。
  describe("所属の付け替え", () => {
    const groupSelects = () =>
      Array.from(doc.querySelectorAll("#mark-rows select.vd-gsel"));
    const change = (el, value) => {
      el.value = value;
      el.dispatchEvent(new win.Event("change", { bubbles: true }));
    };
    const fire = (el, type) =>
      el.dispatchEvent(new win.Event(type, { bubbles: true, cancelable: true }));
    const bulkCalls = () => posted.filter((p) => p.url === "/api/bookmarks/bulk");

    describe("行のグループ欄", () => {
      it("行は今の所属を名乗り、選択肢に全グループと新規を持つ", () => {
        const select = groupSelects()[0];
        expect(select.value).toBe("1");
        expect(Array.from(select.options).map((o) => o.textContent))
          .toEqual(["未分類", "神回", "罵倒集", "＋ 新しいグループ…"]);
        // 未分類の行は「まだ決めていない」ことが一覧の中で見分けられる。
        const ungrouped = groupSelects()[3];
        expect(ungrouped.value).toBe("none");
        expect(ungrouped.classList.contains("vd-gsel-none")).toBe(true);
      });

      it("選んだ瞬間にその行だけが移る(選択も上段への往復も要らない)", async () => {
        change(groupSelects()[0], "2");
        await page.settle();
        expect(bulkCalls().map((p) => p.body))
          .toEqual([{ op: "move", ids: [21], group_id: 2 }]);
      });

      it("未分類を選ぶとgroup_id=nullで戻す", async () => {
        change(groupSelects()[0], "none");
        await page.settle();
        expect(bulkCalls()[0].body).toEqual({ op: "move", ids: [21], group_id: null });
      });

      it("1件直しても他の行の選択は消えない(まとめて動かす途中の手が壊れない)", async () => {
        const picks = doc.querySelectorAll("#mark-rows input[type=checkbox]");
        picks[1].click();
        picks[2].click();
        change(groupSelects()[0], "2");
        await page.settle();
        expect([...state().marksSelected].sort((a, b) => a - b)).toEqual([10, 11]);
      });
    });

    describe("選択", () => {
      it("shift+クリックで直前に選んだ行からここまでを選ぶ", () => {
        const picks = doc.querySelectorAll("#mark-rows input[type=checkbox]");
        picks[0].click();
        picks[2].dispatchEvent(new win.MouseEvent("click", {
          bubbles: true, cancelable: true, shiftKey: true,
        }));
        expect(state().marksSelected.size).toBe(3);
        // checkも実際に付いている(表示と対象がずれない)。
        expect(Array.from(doc.querySelectorAll("#mark-rows input[type=checkbox]"))
          .map((el) => el.checked)).toEqual([true, true, true, false]);
      });

      it("shift+クリックの解除も範囲で効く", () => {
        doc.getElementById("marks-select-all").checked = true;
        doc.getElementById("marks-select-all").dispatchEvent(new win.Event("change"));
        expect(state().marksSelected.size).toBe(4);
        const picks = doc.querySelectorAll("#mark-rows input[type=checkbox]");
        picks[0].click();
        picks[3].dispatchEvent(new win.MouseEvent("click", {
          bubbles: true, cancelable: true, shiftKey: true,
        }));
        expect(state().marksSelected.size).toBe(0);
      });
    });

    describe("tabへのドラッグ", () => {
      const dropOn = (tabIndex, rowIndex) => {
        const row = markRows()[rowIndex];
        const target = tabsOf("marks-groups")[tabIndex].parentElement;
        fire(row, "dragstart");
        fire(target, "dragover");
        fire(target, "drop");
      };

      it("行をtabへ落とすとそのグループへ入る", async () => {
        dropOn(3, 0);
        await page.settle();
        expect(bulkCalls()[0].body).toEqual({ op: "move", ids: [21], group_id: 2 });
      });

      it("選択済みの行を掴んだら選択ぶん全部を運ぶ", async () => {
        const picks = doc.querySelectorAll("#mark-rows input[type=checkbox]");
        picks[0].click();
        picks[1].click();
        dropOn(3, 0);
        await page.settle();
        expect(bulkCalls()[0].body.ids.sort((a, b) => a - b)).toEqual([10, 21]);
      });

      it("選択していない行を掴んだらその行だけ運ぶ(無関係の行を巻き込まない)", async () => {
        doc.querySelectorAll("#mark-rows input[type=checkbox]")[0].click();
        dropOn(3, 1);
        await page.settle();
        expect(bulkCalls()[0].body.ids).toEqual([10]);
      });

      it("「全て」は受け取らない(所属の指定にならないため)", async () => {
        dropOn(0, 0);
        await page.settle();
        expect(bulkCalls().length).toBe(0);
      });
    });

    it("表示から消えた行の選択は捨てる(見えない行への一括操作を残さない)", () => {
      doc.querySelector("#mark-rows input[type=checkbox]").click();
      expect(state().marksSelected.size).toBe(1);
      tabsOf("marks-groups")[3].click();
      expect(state().marksSelected.size).toBe(0);
      // 黙って落とすと、選択した分だけ書き出すつもりの操作が全件へ戻ったことに気付けない。
      expect(doc.getElementById("marks-status").textContent).toContain("選択（1件）を解除");
      expect(doc.getElementById("marks-status").textContent).toContain("表示中の全件");
    });

    it("絞り込みを変えても表示に残る行の選択は保つ", () => {
      // 「全て」で神回の行を選んでから神回のtabへ移る。同じ行が見えているので、
      // 選び直しにはならない。
      doc.querySelector("#mark-rows input[type=checkbox]").click();
      tabsOf("marks-groups")[2].click();
      expect([...state().marksSelected]).toEqual([21]);
    });
  });

  // 並び(position)は作品と連結が繋ぐ順そのものなのに、これまで画面に変える手段が1つも
  // 無く、行を入れた順のまま固定されていた(serverのAPIは既にあった)。
  describe("書き出し順の並べ替え", () => {
    const fire = (el, type) =>
      el.dispatchEvent(new win.Event(type, { bubbles: true, cancelable: true }));
    const orderCalls = () => posted.filter((p) => p.url === "/api/groups/1/order");

    beforeEach(() => tabsOf("marks-groups")[2].click());

    it("行を別の行の上へ落とすとその位置へ入る", async () => {
      const rows = markRows();
      fire(rows[2], "dragstart");
      fire(rows[0], "dragover");
      fire(rows[0], "drop");
      await page.settle();
      // 3番目(点だけ=21)を先頭へ。掴んだ行を抜いてから落とした行の手前へ入れる。
      expect(orderCalls()[0].body).toEqual({ bookmark_ids: [21, 11, 10] });
      expect(doc.getElementById("marks-status").textContent).toContain("並べ替えました");
    });

    it("選択ぶんは表示順のまま連れて行く(選択の相対順を崩さない)", async () => {
      // 表示順は 11・10・21。後ろ2件を選んで先頭の上へ落とす。
      const picks = doc.querySelectorAll("#mark-rows input[type=checkbox]");
      picks[1].click();
      picks[2].click();
      const rows = markRows();
      fire(rows[1], "dragstart");
      fire(rows[0], "dragover");
      fire(rows[0], "drop");
      await page.settle();
      expect(orderCalls()[0].body).toEqual({ bookmark_ids: [10, 21, 11] });
    });

    it("自分の上へ落としても何も起きない", async () => {
      const rows = markRows();
      fire(rows[0], "dragstart");
      fire(rows[0], "dragover");
      fire(rows[0], "drop");
      await page.settle();
      expect(orderCalls()).toHaveLength(0);
    });

    // 「全て」「未分類」では順そのものが定まらない。掴めても落とす先の意味が無い。
    it("グループを選んでいない間は並べ替えない", async () => {
      tabsOf("marks-groups")[0].click();
      const rows = markRows();
      fire(rows[1], "dragstart");
      fire(rows[0], "dragover");
      fire(rows[0], "drop");
      await page.settle();
      expect(orderCalls()).toHaveLength(0);
    });
  });

  // 書き出し・連結は表示中の全件しか対象にできず、3件だけ選んで押しても表示中の全部が
  // queueへ入っていた(出来上がるまで気付けない)。選択がそのまま対象になることを確かめる。
  describe("書き出しの対象", () => {
    const picks = () => Array.from(doc.querySelectorAll("#mark-rows input[type=checkbox]"));
    const callsTo = (url) => posted.filter((p) => p.url === url);

    it("選択が無ければ表示中の尺のある行を書き出す(点は入らない)", async () => {
      doc.getElementById("cuts-export").click();
      await page.settle();
      expect(callsTo("/api/clips/batch")[0].body.items.map((i) => i.start))
        .toEqual([100, 300, 500]);
    });

    it("書き出しは由来の見どころを渡す(書き出した事実をその行へ書き戻させる)", async () => {
      doc.getElementById("cuts-export").click();
      await page.settle();
      const items = callsTo("/api/clips/batch")[0].body.items;
      expect(items.map((i) => i.bookmark_id)).toEqual([10, 11, 12]);
      // メモがそのまま書き出しfile名になる。
      expect(items[0].label).toBe("前の場面");
    });

    it("行を選んでいれば選択した分だけを書き出す", async () => {
      // 表示順の2件目(=id 10・100〜160)。
      picks()[1].click();
      doc.getElementById("cuts-export").click();
      await page.settle();
      const items = callsTo("/api/clips/batch")[0].body.items;
      expect(items).toHaveLength(1);
      expect(items[0]).toMatchObject({ recording_id: 1, start: 100, end: 160 });
    });

    it("対象の表示も選択に追従する(押す前に件数で読める)", () => {
      expect(doc.getElementById("cuts-scope").textContent)
        .toBe("対象: 見どころ全体の3件／点 1件は対象外");
      // 選んだ行が尺のある1件だけなら、対象外の内訳は出ない(落ちる行が無いため)。
      picks()[1].click();
      expect(doc.getElementById("cuts-scope").textContent)
        .toBe("対象: 選択中の1件（見どころ全体）");
      // 点を混ぜて選ぶと、そのぶんが対象から落ちることを名乗る。
      picks()[0].click();
      expect(doc.getElementById("cuts-scope").textContent)
        .toBe("対象: 選択中の1件（見どころ全体／点 1件は対象外）");
    });

    // 点を選んでも書き出しの対象にはならない。混ぜると件数だけが合わない結果になる。
    it("点だけを選んでも書き出せない", () => {
      picks()[0].click();
      expect(doc.getElementById("cuts-export").disabled).toBe(true);
    });

    it("連結も選んだ分だけを表示順(=書き出し順)のまま繋ぐ", async () => {
      tabsOf("marks-groups")[2].click();
      // position順の2件目。start順に並べ替えていれば1件目に来る行なので、
      // 選択を素通しして時刻順で繋ぐ退行もここで落ちる。
      picks()[1].click();
      doc.getElementById("cuts-reel").click();
      await page.settle();
      expect(callsTo("/api/reels")[0].body.items.map((i) => i.start)).toEqual([100]);
    });

    // 作品は「連結」と同じ帯に並ぶが単位が違う。連結は選択に従い、作品はグループ1件が
    // 単位である。同じ帯の隣り合う2つで挙動が違うので、押す前に読めることが要る。
    it("作品はグループを選んでいないと押せない", () => {
      expect(doc.getElementById("cuts-work").disabled).toBe(true);
      expect(doc.getElementById("cuts-work").title).toContain("グループを選んでください");
    });

    it("作品はグループ全体を1本にする(行の選択には従わない)", async () => {
      tabsOf("marks-groups")[2].click();
      // 1行だけ選んでも、送るのはグループ全体を指すgroup_idだけ。範囲は渡さない。
      picks()[1].click();
      const button = doc.getElementById("cuts-work");
      expect(button.disabled).toBe(false);
      expect(button.title).toContain("行の選択には従いません");
      button.click();
      await page.settle();
      const call = callsTo("/api/groups/1/work")[0];
      expect(call.body).toEqual({ preset_id: 7 });
      expect(doc.getElementById("cuts-status").textContent).toContain("4シーン");
    });

    it("下見は作らずに、何を焼くか・合計尺だけを出す", async () => {
      tabsOf("marks-groups")[2].click();
      doc.getElementById("cuts-plan").click();
      await page.settle();
      const status = doc.getElementById("cuts-status").textContent;
      expect(status).toContain("2シーン");
      expect(status).toContain("焼く: 字幕");
      // 下見で成果物を作らないこと(確認のcostが実行と同じになっては下見の意味が無い)。
      expect(callsTo("/api/groups/1/work")).toHaveLength(0);
    });

    it("素材が無いシーンが在れば投入しない(queueで落ちるより先に止める)", async () => {
      await page.close();
      await open({
        "/api/groups/1/work-plan?preset_id=7": {
          group_id: 1, group: "神回", scene_count: 2, requested_seconds: 90,
          burns: [], tighten: false, upscale: false, cache_bytes: 0, blocking: [2],
          scenes: [{ position: 1, part_ready: true }, { position: 2, part_ready: false }],
        },
      });
      tabsOf("marks-groups")[2].click();
      doc.getElementById("cuts-work").click();
      await page.settle();
      expect(callsTo("/api/groups/1/work")).toHaveLength(0);
      expect(doc.getElementById("cuts-status").textContent).toContain("2番目");
      // 止めた後も押せる状態に戻すこと(直してから押し直せない形にしない)。
      expect(doc.getElementById("cuts-work").disabled).toBe(false);
    });

    it("型が1つも無ければ押せない(queueへ載ってから落ちる形にしない)", async () => {
      errorSpy.mockRestore();
      await page.close();
      await open({ "/api/clip-presets": { presets: [], fields: {} } });
      tabsOf("marks-groups")[2].click();
      expect(doc.getElementById("cuts-work").disabled).toBe(true);
      expect(doc.getElementById("cuts-preset").textContent).toContain("型がありません");
    });

    // 表示中の全件削除は表示中の絞り込みに従う(全てを消すつもりの操作ではない)。
    it("「表示中をすべて削除」は絞り込みをそのままserverへ渡す", async () => {
      tabsOf("marks-groups")[2].click();
      doc.getElementById("cuts-clear").click();
      await page.settle();
      const modal = doc.querySelector(".confirm-modal");
      const buttons = Array.from(modal.querySelectorAll(".confirm-actions button"));
      buttons[buttons.length - 1].click();
      await page.settle();
      expect(posted.some((p) => p.url === "/api/bookmarks?group=1"
        && p.method === "DELETE")).toBe(true);
    });
  });

  // 記録先は「今どこへ入るか」を持つ1つのbuttonで、選択肢は押した時だけ出す。
  // 事故の形は「行き先を読めないまま押す」なので、名乗り・選び直し・選んだ後の閉じ方を
  // 実DOMで確かめる。
  describe("記録先", () => {
    const destButton = () => doc.getElementById("dest-pick");
    const panel = () => doc.querySelector(".vd-pick");
    const items = () => Array.from(doc.querySelectorAll(".vd-pick-item"));
    const nameOf = (item) => item.querySelector(".vd-pick-name").textContent;
    const countOf = (item) => item.querySelector(".vd-pick-count").textContent;
    const choose = (label) => {
      destButton().click();
      const item = items().find((el) => nameOf(el) === label);
      if (!item) throw new Error(`選択listに「${label}」がありません`);
      item.click();
    };

    it("押すまでは名乗りだけを出す(選択肢で行を埋めない)", () => {
      expect(panel()).toBeNull();
      expect(destButton().textContent).toContain("記録先");
      expect(destButton().textContent).toContain("未分類");
      expect(destButton().getAttribute("aria-expanded")).toBe("false");
    });

    it("押すと選択listが出て、今の行き先に印が付く", () => {
      destButton().click();
      expect(panel()).not.toBeNull();
      expect(destButton().getAttribute("aria-expanded")).toBe("true");
      expect(items().map(nameOf)).toEqual(["未分類", "神回", "罵倒集"]);
      // 件数は溜まっている先を取り違えないための目印。未分類にも出す(取りこぼしの数)。
      expect(items().map(countOf)).toEqual(["1", "3", "0"]);
      expect(items()[0].getAttribute("aria-selected")).toBe("true");
      expect(items()[0].querySelector(".vd-pick-tick").textContent).toBe("✓");
      // 数件しか無いうちは絞り込み欄そのものが邪魔になる。
      expect(doc.querySelector(".vd-pick-filter")).toBeNull();
    });

    it("グループを作る入口も同じ面に置く(選ぼうとして初めて無いことに気付くため)", () => {
      destButton().click();
      expect(Array.from(doc.querySelectorAll(".vd-pick-act")).map((b) => b.textContent))
        .toEqual(["＋ 新規グループ", "＋ 検索語で作る"]);
    });

    it("選ぶと以後の追加がそのグループへ入り、listは閉じる", () => {
      choose("神回");
      expect(panel()).toBeNull();
      expect(destButton().getAttribute("aria-expanded")).toBe("false");
      expect(destButton().textContent).toContain("神回");
      expect(win.currentAddGroupId()).toBe(1);
      // 確認はtoastへ出す。player-statusは切り出しpathやerrorの置き場で、記録先を
      // 変えただけで復元できない出力pathが消えてはいけない。
      expect(doc.querySelector(".toast-layer").textContent).toContain("神回");
      expect(doc.getElementById("player-status").textContent).not.toContain("神回");
      // 記録先は録画を跨いで使い回すので残す。
      expect(win.localStorage.getItem("tictok.videos.cutGroup")).toBe("1");
    });

    it("開いている間にもう一度押せば、選ばずに閉じられる", () => {
      destButton().click();
      expect(panel()).not.toBeNull();
      destButton().click();
      expect(panel()).toBeNull();
      expect(win.currentAddGroupId()).toBeNull();
    });

    // グループが十数件まで増えても、目で拾えないぶんは打鍵で絞る。
    it("多いときだけ絞り込み欄を出し、Enterで先頭の候補へ決める", async () => {
      await page.close();
      const many = Array.from({ length: 15 }, (_, i) => (
        { id: i + 1, name: `棚${i + 1}`, memo: "", created_at: i }
      ));
      many[4].name = "歌枠";
      await open({ "/api/groups": { items: many }, "/api/bookmarks": { items: [] } });
      destButton().click();
      const box = doc.querySelector(".vd-pick-filter");
      expect(box).not.toBeNull();
      expect(items()).toHaveLength(16);

      box.value = "歌";
      box.dispatchEvent(new win.Event("input"));
      expect(items().filter((el) => !el.hidden).map(nameOf)).toEqual(["歌枠"]);

      box.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      expect(panel()).toBeNull();
      expect(win.currentAddGroupId()).toBe(5);
      expect(destButton().textContent).toContain("歌枠");
    });

    // 再生に追従するコメント欄・文字起こし欄は、1行進むたびに自分のscrollTopを動かす。
    // これで選択listが閉じていた頃は、観ながら記録先を選ぶことができなかった。
    it("別の枠のscrollでは閉じない(再生追従で消えない)", () => {
      destButton().click();
      expect(panel()).not.toBeNull();
      doc.getElementById("comments")
        .dispatchEvent(new win.Event("scroll", { bubbles: false }));
      expect(panel()).not.toBeNull();
      doc.querySelector(".vd-pick-list")
        .dispatchEvent(new win.Event("scroll", { bubbles: false }));
      expect(panel()).not.toBeNull();
    });

    // 閉じる理由は起点が動くこと。頁ごと動けば面の居場所は嘘になる。
    it("起点を載せた枠がscrollすれば閉じる(面の位置が嘘になるため)", () => {
      destButton().click();
      expect(panel()).not.toBeNull();
      doc.dispatchEvent(new win.Event("scroll", { bubbles: false }));
      expect(panel()).toBeNull();
    });

    it("記録先は上段tabの表示選択とは別物(見る場所と入れる場所は独立)", () => {
      choose("神回");
      tabsOf("marks-groups")[3].click();
      expect(state().groupSel).toBe("2");
      expect(win.currentAddGroupId()).toBe(1);
    });

    it("消えたグループを指したままにしない", async () => {
      choose("神回");
      tabsOf("marks-groups")[2].click();
      expect(state().groupSel).toBe("1");
      // 「神回」が消えた状態で引き直す。
      serve(() => ({ items: [GROUPS[1]] }));
      await page.run("refreshGroupData()");
      expect(win.currentAddGroupId()).toBeNull();
      expect(state().groupSel).toBe("");
      expect(destButton().textContent).toContain("未分類");
    });

    it("取得に失敗しても手元のlistは捨てない(消えたと誤認させない)", async () => {
      choose("神回");
      tabsOf("marks-groups")[2].click();
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
  describe("視聴", () => {
    // 「視聴」は1列目・残りの操作は最終列なので、行全体から拾う。
    const buttonsOf = (tr) => Array.from(tr.querySelectorAll("button"));
    // 位置ではなく文言で掴む(buttonが1つ増えるたびに無関係のtestが落ちる)。
    const buttonOf = (tr, label) => buttonsOf(tr).find((b) => b.textContent === label);
    const markVideo = () => doc.getElementById("mark-video");
    const status = () => doc.getElementById("mark-play-status").textContent;
    // 1件削除は確認を挟む(取り消せないうえ、視聴と同じ行に並ぶ)。
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

    it("行は1列目の「視聴」から始まる(この場で観るか、道具付きで観るか)", () => {
      expect(buttonsOf(markRows()[0]).map((b) => b.textContent))
        .toEqual(["視聴", "シーン検索視聴", "削除"]);
    });

    it("「視聴」は見どころtabのまま再生する(観るたびtabを往復させない)", async () => {
      await watch(1);
      expect(doc.getElementById("mark-play").classList.contains("hidden")).toBe(false);
      expect(markVideo().getAttribute("src")).toBe("/api/recordings/1/play");
      expect(doc.getElementById("view-marks").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(true);
      // 観ている対象は行と同じ身元(配信者・配信日時・範囲)で名乗る。素材版もここで
      // 名乗る — この場の再生は常に元録画なので、焼き込みの出来を確かめたつもりで
      // 素の映像を観て「焼き込みが失敗している」と誤読するのを防ぐ。
      const head = doc.getElementById("mark-play-head").textContent;
      expect(head.startsWith("alice / ")).toBe(true);
      expect(head).toContain(" / 00:01:40 - 00:02:40");
      expect(head.endsWith(" / 素材: 元録画")).toBe(true);
    });

    it("尺が分かった時点で見どころの位置へ入る", async () => {
      setCurrentTime(0);
      await watch(1);
      markVideo().dispatchEvent(new win.Event("loadedmetadata"));
      expect(markVideo().currentTime).toBe(100);
    });

    it("尺のある行は終端で一度止める(どこまでが見どころか観ているだけで分かる)", async () => {
      await watch(1);
      setCurrentTime(160);
      markVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).toContain("終端");
      // 解除するので、続きを観たければ再生を押すだけでよい。
      setCurrentTime(400);
      doc.getElementById("mark-play-status").textContent = "";
      markVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).toBe("");
    });

    it("点は止めない(終端が無いため)", async () => {
      await watch(0);
      setCurrentTime(9999);
      markVideo().dispatchEvent(new win.Event("timeupdate"));
      expect(status()).not.toContain("終端");
    });

    it("同じ録画の別の行は読み込み直さずseekだけで移る", async () => {
      setCurrentTime(0);
      await watch(0);
      markVideo().dispatchEvent(new win.Event("loadedmetadata"));
      await watch(1);
      expect(playbacks.length).toBe(1);
      // jsdomは尺を持たないので位置決めはmetadata待ちのまま。実browserは読み込み済みで
      // 即座に入る(readyStateで分岐する)。ここでは待ちが解けた時の位置を見る。
      markVideo().dispatchEvent(new win.Event("loadedmetadata"));
      expect(markVideo().currentTime).toBe(100);
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

    // 端を今observeている位置で決める。時刻を打ち直すより、観ながら決める方が速くて
    // 正しい(何秒かは覚えていないが、ここから、というのは見れば判る)。
    describe("観ている位置から端を決める", () => {
      const patches = () => posted.filter((p) => p.method === "PATCH");

      it("「頭を今に」は尺を保ったまま窓ごと動かす", async () => {
        await watch(1);
        setCurrentTime(120);
        doc.getElementById("mark-play-setin").click();
        await page.settle();
        expect(patches().map((p) => [p.url, p.body]))
          .toEqual([["/api/bookmarks/10", { start: 120, end: 180 }]]);
      });

      it("「今までを尺に」は点を範囲に変える(mp4にできるようになる)", async () => {
        await watch(0);
        setCurrentTime(140);
        doc.getElementById("mark-play-setout").click();
        await page.settle();
        expect(patches().map((p) => [p.url, p.body]))
          .toEqual([["/api/bookmarks/21", { end: 140 }]]);
        expect(doc.getElementById("mark-play-status").textContent).toContain("mp4にできます");
      });

      it("頭より前で「今までを尺に」を押しても送らない(逆順の範囲を作らない)", async () => {
        await watch(0);
        setCurrentTime(10);
        doc.getElementById("mark-play-setout").click();
        await page.settle();
        expect(patches()).toHaveLength(0);
        expect(doc.getElementById("mark-play-status").textContent).toContain("頭より前");
      });
    });

    // 位置と尺は一覧の上で直せる。直せないと、点に尺を与えるにも端を1秒詰めるにも
    // 再生画面へ戻って取り直すことになり、古い行を消し忘れれば同じ場面が2件残る。
    // 2つの欄は独立に効く(位置は窓ごと動かして尺を保ち、尺は位置を据えたまま終端を動かす)。
    describe("位置と尺の編集", () => {
      const patches = () => posted.filter((p) => p.method === "PATCH");
      const type = (input, value) => {
        input.value = value;
        input.dispatchEvent(new win.Event("change", { bubbles: true }));
      };
      const arrow = (input, key, mods = {}) =>
        input.dispatchEvent(new win.KeyboardEvent("keydown", {
          key, bubbles: true, cancelable: true, ...mods,
        }));

      it("欄は保存済みの値を出す(点は空欄で「点」と名乗る)", () => {
        expect([fieldOf(1, COL.start).value, fieldOf(1, COL.span).value])
          .toEqual(["00:01:40.0", "00:01:00.0"]);
        expect(fieldOf(0, COL.span).value).toBe("");
        expect(fieldOf(0, COL.span).placeholder).toBe("点");
      });

      it("位置を直すと尺を保ったまま窓ごと動く", async () => {
        type(fieldOf(1, COL.start), "2:00");
        await page.settle();
        expect(patches().map((p) => [p.url, p.body]))
          .toEqual([["/api/bookmarks/10", { start: 120, end: 180 }]]);
      });

      it("点の位置は終端を持たないので位置だけを送る", async () => {
        type(fieldOf(0, COL.start), "1:30");
        await page.settle();
        expect(patches()[0].body).toEqual({ start: 90 });
      });

      it("点の尺欄に長さを入れると範囲になる(位置は動かさない)", async () => {
        type(fieldOf(0, COL.span), "25");
        await page.settle();
        expect(patches().map((p) => [p.url, p.body]))
          .toEqual([["/api/bookmarks/21", { end: 105 }]]);
      });

      it("尺欄を空にすると範囲を捨てて点へ戻す", async () => {
        type(fieldOf(1, COL.span), "");
        await page.settle();
        expect(patches()[0].body).toEqual({ end: null });
      });

      // 1秒詰めるのに終端の絶対時刻を数え直させない。
      it("符号を付けると今の値からの増減として読む", async () => {
        // 行1は 100〜160(尺60秒)。+2 で尺62秒 = 終端162秒。
        type(fieldOf(1, COL.span), "+2");
        await page.settle();
        expect(patches()[0].body).toEqual({ end: 162 });
      });

      it("負の符号も同じく増減として読む", async () => {
        type(fieldOf(1, COL.start), "-10");
        await page.settle();
        expect(patches()[0].body).toEqual({ start: 90, end: 150 });
      });

      it("↑↓で刻む(shiftで1秒・altで10秒)", async () => {
        arrow(fieldOf(1, COL.span), "ArrowUp");
        await page.settle();
        expect(patches()[0].body).toEqual({ end: 160.1 });
        posted.length = 0;
        arrow(fieldOf(1, COL.span), "ArrowDown", { shiftKey: true });
        await page.settle();
        expect(patches()[0].body).toEqual({ end: 159 });
        posted.length = 0;
        arrow(fieldOf(1, COL.span), "ArrowUp", { altKey: true });
        await page.settle();
        expect(patches()[0].body).toEqual({ end: 170 });
      });

      // 点の尺欄には動かす元が無い。0からの刻みで範囲を作れるようにする。
      it("点の尺欄でも↑で範囲を作れる", async () => {
        arrow(fieldOf(0, COL.span), "ArrowUp");
        await page.settle();
        expect(patches()[0].body).toEqual({ end: 80.1 });
      });

      it("0より前へは動かさない", async () => {
        arrow(fieldOf(0, COL.span), "ArrowDown");
        await page.settle();
        expect(patches()).toHaveLength(0);
      });

      // 読めない値で上書きすると、打った値が保存されたのか捨てられたのかが読めない。
      it("読めない値は送らず、元の値へ戻して理由を出す", async () => {
        const input = fieldOf(1, COL.start);
        type(input, "あとで");
        await page.settle();
        expect(patches()).toHaveLength(0);
        expect(input.value).toBe("00:01:40.0");
        expect(doc.getElementById("marks-status").textContent).toContain("時刻を読めません");
      });

      it("尺の候補は作品の型の目標秒から作る(2箇所が別の狙いを名乗らない)", () => {
        const options = Array.from(doc.querySelectorAll("#span-presets option"));
        expect(options.map((o) => o.value)).toEqual(["00:00:45.0"]);
        expect(fieldOf(0, COL.span).getAttribute("list")).toBe("span-presets");
      });

      it("欄をclickしても再生は始まらない(行clickと同じ扱いにしない)", async () => {
        const before = playbacks.length;
        fieldOf(1, COL.start).dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
        await page.settle();
        expect(playbacks).toHaveLength(before);
      });

      // 配信中に押した見どころのstartは暫定値で、録画の確定でPTS軸へ載せ直される。
      // 今直しても再mapに上書きされるので、その前に触らせない。
      it("配信中に記録した見どころは確定まで編集させない", async () => {
        await page.close();
        await open({
          "/api/bookmarks": { items: [{ ...MARKS[2], pts_mapped: 0 }] },
        });
        doc.getElementById("tab-marks").click();
        const input = fieldOf(0, COL.start);
        expect(input.disabled).toBe(true);
        expect(input.title).toContain("録画の確定後");
      });
    });

    it("メモは書き出しfile名でもある(直した値をその行へ保存する)", async () => {
      const memo = markRows()[1].children[COL.memo].querySelector("input");
      memo.value = "  決着  ";
      memo.dispatchEvent(new win.Event("change", { bubbles: true }));
      await page.settle();
      expect(posted.find((p) => p.url === "/api/bookmarks/10" && p.method === "PATCH").body)
        .toEqual({ memo: "決着" });
    });

    it("「シーン検索視聴」は尺があればIN/OUTが入った状態で移る", async () => {
      buttonOf(markRows()[1], "シーン検索視聴").click();
      await page.settle();
      expect(doc.getElementById("view-search").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("tab-search").classList.contains("active")).toBe(true);
      expect(state().cutIn).toBe(100);
      expect(state().cutOut).toBe(160);
    });
  });

  // 記録の口は1つ。以前は「見どころに記録」と「切り出しリストに追加」が並び、同じ範囲を
  // 2つの表へ二重に登録する形になっていた。押した結果が入力の状態で変わるので、
  // button自身に何が入るかを言わせる。
  describe("再生画面からの記録", () => {
    beforeEach(async () => {
      doc.getElementById("tab-marks").click();
      Array.from(markRows()[1].querySelectorAll("button"))
        .find((b) => b.textContent === "シーン検索視聴").click();
      await page.settle();
    });

    it("IN/OUTが無ければ点として記録すると名乗る", () => {
      win.setCut(null, null);
      const button = doc.getElementById("add-mark");
      expect(button.textContent).toBe("見どころに記録（点）");
      expect(button.title).toContain("mp4にはできません");
    });

    it("IN/OUTがあれば尺つきで記録すると名乗る", () => {
      win.setCut(400, 430);
      const button = doc.getElementById("add-mark");
      expect(button.textContent).toBe("見どころに記録（尺あり）");
      expect(button.disabled).toBe(false);
    });

    it("記録するとメモをそのまま渡す(書き出しfile名になる)", async () => {
      win.setCut(400, 430);
      doc.getElementById("mark-memo").value = "新しい場面";
      doc.getElementById("add-mark").click();
      await page.settle();
      expect(posted.find((p) => p.url === "/api/bookmarks" && p.method === "POST").body)
        .toMatchObject({ start: 400, end: 430, memo: "新しい場面" });
    });

    // 二重登録の関門。同じ範囲を2回足すと、一括書き出しで同じmp4が2本出るまで気付けない。
    it("既に同じ範囲が在れば押せない形で名乗る", () => {
      win.setCut(100, 160);
      const button = doc.getElementById("add-mark");
      expect(button.textContent).toBe("記録済");
      expect(button.disabled).toBe(true);
      expect(button.title).toContain("神回");
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
