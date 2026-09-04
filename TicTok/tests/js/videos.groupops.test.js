import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// グループ操作tab。見どころtabは「選んだ1つのグループの中で」扱うので、グループを跨ぐ
// 仕分けはそこでは行えない。この画面の事故は「同じ範囲が2つのグループに散ったまま
// 気付かない」「移したつもりが動いていない」という形で出るため、「左右が同じ条件で
// 並んでいるか」「選択がそのまま行き先へ届くか」を実DOMで確かめる。
describe("videos.js のグループ操作tab", () => {
  let page;
  let doc;
  let errorSpy;
  let posted;

  const GROUPS = [
    { id: 1, name: "神回", memo: "投稿用", position: 0, created_at: 1 },
    { id: 2, name: "罵倒集", memo: "", position: 1, created_at: 2 },
  ];
  // 神回に尺のある行3件と点1件、罵倒集に1件、未分類に1件。
  // 並びは録画→位置なので、positionの食い違いはここでは見ない(見どころtabが持つ)。
  const MARKS = [
    { id: 20, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 50, end: 70, memo: "頭の方", group_id: 1, position: 0,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 21, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 80, end: null, memo: "点だけ", group_id: 1, position: 1,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 22, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 200, end: 230, memo: "まだ切っていない", group_id: 1, position: 2,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 24, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 700, end: 720, memo: "散った方", group_id: 1, position: 3,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 14, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 700, end: 720, memo: "散った片割れ", group_id: 2, position: 0,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
    { id: 23, recording_id: 1, unique_id: "alice", recording_started_at: 100,
      start: 600, end: 610, memo: "未整理", group_id: null, position: null,
      origin: "manual", pts_mapped: 1, filename: "a.mp4" },
  ];

  function record({ url, method, init }) {
    posted.push({ url, method, body: init && init.body ? JSON.parse(init.body) : null });
    return { affected: 2, ordered: 2, bookmarks: 2, id: 99, name: "新規", memo: "" };
  }

  // 棚は1枚=1グループの札。列の位置ではなく、札の中の役割(名前・メモ・内訳)で掴む。
  const shelfRows = () => Array.from(doc.querySelectorAll("#gops-rows .vd-gcard"));
  const paneRows = (side) => Array.from(doc.querySelectorAll(`#gops-${side}-rows tr`));
  const cellText = (tr, index) => tr.cells[index].textContent;
  const cardInput = (card, role) => card.querySelector(`.vd-gcard-${role}`);
  const cardStat = (card, key) => card.querySelector(`[data-stat="${key}"] .vd-gstat-v`).textContent;
  const $id = (id) => doc.getElementById(id);
  // 列は 選択・順・位置・尺・配信者と配信日・メモ・操作。
  const COL = { order: 1, start: 2, span: 3, who: 4, memo: 5 };
  // 位置ではなく文言で掴む(buttonが1つ増えるたびに無関係のtestが落ちる)。
  const buttonOf = (tr, label) =>
    Array.from(tr.querySelectorAll("button")).find((b) => b.textContent === label);
  const answerConfirm = (accept) => {
    const modal = doc.querySelector(".confirm-modal");
    if (!modal) throw new Error("確認dialogが出ていません");
    const buttons = Array.from(modal.querySelectorAll(".confirm-actions button"));
    buttons[accept ? buttons.length - 1 : 0].click();
  };
  // paneの選択。checkboxは行の先頭列。
  const pick = (side, index) => {
    paneRows(side)[index].querySelector("input[type=checkbox]").click();
  };
  async function setSide(side, value) {
    const select = $id(`gops-${side}-group`);
    select.value = value;
    select.dispatchEvent(new page.win.Event("change", { bubbles: true }));
    await page.settle();
  }

  beforeEach(async () => {
    posted = [];
    page = loadPage({
      page: "videos",
      url: "http://localhost:8520/videos",
      routes: {
        "/api/groups": { items: GROUPS },
        "/api/bookmarks": { items: MARKS },
        "POST /api/bookmarks/bulk": record,
        "POST /api/bookmarks": record,
        "POST /api/groups": record,
        "POST /api/groups/order": record,
        "POST /api/groups/1/merge": record,
        "PATCH /api/groups/1": record,
        "DELETE /api/groups/1": record,
      },
    });
    doc = page.document;
    errorSpy = vi.spyOn(page.win.console, "error").mockImplementation(() => {});
    await page.settle();
    $id("tab-groups").click();
    await page.settle();
  });

  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  it("script errorを出さずにtabが開く", () => {
    expect(page.errors).toEqual([]);
    expect(errorSpy).not.toHaveBeenCalled();
    expect($id("view-groups").classList.contains("hidden")).toBe(false);
  });

  // 棚はこの画面にしか無い。以前は改名も削除も並べ替えも画面から行えず、メモだけが
  // 他tabの見出しに在った。
  describe("グループ一覧(棚)", () => {
    it("全件と尺のある件数・点の件数・完成尺を出す", () => {
      const row = shelfRows()[0];
      expect(row.querySelector(".vd-gcard-no").textContent).toBe("1");
      expect(cardInput(row, "name").value).toBe("神回");
      expect(cardInput(row, "memo").value).toBe("投稿用");
      // 神回: 4件(20,21,22,24)、うち尺があるのは3件、点は1件。
      expect(cardStat(row, "marks")).toBe("4");
      expect(cardStat(row, "ranged")).toBe("3");
      expect(cardStat(row, "points")).toBe("1");
      // 完成尺は尺のある行だけの和(20+30+20=70秒)。
      expect(cardStat(row, "seconds")).toBe("00:01:10");
    });

    it("改名はPATCHへ行き、空にすると元の名前へ戻す(名前の無いグループを作らない)", async () => {
      const input = cardInput(shelfRows()[0], "name");
      input.value = "神回2";
      input.dispatchEvent(new page.win.Event("change", { bubbles: true }));
      await page.settle();
      expect(posted).toContainEqual(
        { url: "/api/groups/1", method: "PATCH", body: { name: "神回2" } });

      posted = [];
      input.value = "   ";
      input.dispatchEvent(new page.win.Event("change", { bubbles: true }));
      await page.settle();
      expect(posted).toEqual([]);
      expect(input.value).toBe("神回");
      expect($id("gops-status").textContent).toContain("空にできません");
    });

    it("並べ替えは全体の並びを送る(部分指定だと並行して増えた分と食い違う)", async () => {
      buttonOf(shelfRows()[0], "↓").click();
      await page.settle();
      expect(posted).toContainEqual(
        { url: "/api/groups/order", method: "POST", body: { group_ids: [2, 1] } });
    });

    it("端の行は動かせない(押しても何も起きないbuttonを残さない)", () => {
      expect(buttonOf(shelfRows()[0], "↑").disabled).toBe(true);
      expect(buttonOf(shelfRows()[1], "↓").disabled).toBe(true);
    });

    it("削除は中身の行き先(未分類へ戻る)を確認で名乗ってから消す", async () => {
      buttonOf(shelfRows()[0], "削除").click();
      await page.settle();
      const text = doc.querySelector(".confirm-modal").textContent;
      expect(text).toContain("未分類へ");
      expect(text).toContain("見どころ 4件");
      answerConfirm(true);
      await page.settle();
      expect(posted).toContainEqual({ url: "/api/groups/1", method: "DELETE", body: null });
    });

    it("取り消せば消えない", async () => {
      buttonOf(shelfRows()[0], "削除").click();
      await page.settle();
      answerConfirm(false);
      await page.settle();
      expect(posted).toEqual([]);
    });

    it("一覧の行からそのまま左右のpaneへ載せられる", async () => {
      buttonOf(shelfRows()[1], "左").click();
      await page.settle();
      expect($id("gops-left-group").value).toBe("2");
      // 出ている行は罵倒集の中身だけ。
      expect(paneRows("left").map((tr) => cellText(tr, COL.memo))).toEqual(["散った片割れ"]);
    });

    // 押せない状態(disabled)だけでは「使えない」としか読めない。下の2つの表がどの行から
    // 来ているのかを、棚の側からも辿れるようにする。
    it("今どちらのpaneに出しているグループかを行が名乗る", async () => {
      buttonOf(shelfRows()[1], "左").click();
      await page.settle();
      expect(buttonOf(shelfRows()[1], "左").getAttribute("aria-pressed")).toBe("true");
      expect(buttonOf(shelfRows()[0], "左").getAttribute("aria-pressed")).toBe("false");
    });
  });

  // 内訳を括弧で足していた頃は、名前の長いグループを選ぶと閉じたselectの中で名前そのものが
  // 切れ、どちらのpaneが何を指しているのか読めなかった(件数は対比帯が左右まとめて出す)。
  it("行き先selectはグループの名前だけを並べる", () => {
    expect(Array.from($id("gops-left-group").options).map((option) => option.textContent))
      .toEqual(["全て", "未分類", "神回", "罵倒集"]);
  });

  describe("左右の対比", () => {
    beforeEach(async () => {
      await setSide("left", "1");
      await setSide("right", "2");
    });

    // 並びは録画→位置。左右の表を突き合わせる画面なので、書き出し順ではなく素材の
    // 時間軸で揃える(同じ場面が縦に揃う)。
    it("録画→位置の順で並べる", () => {
      expect(paneRows("left").map((tr) => cellText(tr, COL.start)))
        .toEqual(["00:00:50", "00:01:20", "00:03:20", "00:11:40"]);
    });

    it("順はグループ内の書き出し順を出す(棚の表示順とは別物)", () => {
      expect(paneRows("left").map((tr) => cellText(tr, COL.order)))
        .toEqual(["1", "2", "3", "4"]);
    });

    it("点は尺の代わりに「点」と名乗る(0秒の素材があると読まれない)", () => {
      expect(cellText(paneRows("left")[1], COL.span)).toBe("点");
      expect(cellText(paneRows("left")[0], COL.span)).toBe("00:00:20");
    });

    it("絞り込みは左右の両方へ同じものが掛かる", async () => {
      await setSide("right", "1");
      const seg = $id("gops-filter");
      seg.querySelector("[data-value=point]").click();
      await page.settle();
      expect(paneRows("left").map((tr) => cellText(tr, COL.memo))).toEqual(["点だけ"]);
      expect(paneRows("right").map((tr) => cellText(tr, COL.memo))).toEqual(["点だけ"]);

      seg.querySelector("[data-value=ranged]").click();
      await page.settle();
      expect(paneRows("left").map((tr) => cellText(tr, COL.memo)))
        .toEqual(["頭の方", "まだ切っていない", "散った方"]);
    });

    it("食い違いの件数を表を読み比べる前に1行で出す", () => {
      expect($id("gops-diff").textContent).toContain("左: 4件（尺あり 3・点 1）");
      expect($id("gops-diff").textContent).toContain("右: 1件（尺あり 1・点 0）");
    });
  });

  describe("付け替え", () => {
    beforeEach(async () => {
      await setSide("left", "1");
      await setSide("right", "2");
    });

    it("選択した行をまとめて行き先へ移す", async () => {
      pick("left", 0); // 20
      pick("left", 1); // 21
      await page.settle();
      $id("gops-left-move").click();
      await page.settle();
      expect(posted).toContainEqual({
        url: "/api/bookmarks/bulk", method: "POST",
        body: { op: "move", ids: [20, 21], group_id: 2 },
      });
    });

    it("行き先の名前をbuttonの文言に出す(左右のselectは表2つ分離れている)", async () => {
      pick("left", 0);
      await page.settle();
      expect($id("gops-left-move").textContent).toBe("「罵倒集」へ移動 1");
      expect($id("gops-right-move").textContent).toBe("左へ移動");
    });

    // 複製は「同じ場面をグループごとに別の詰め方で持つ」ための操作。所属は排他なので、
    // 共用ではなく行ごと複製することでしか表せない。
    it("複製は元を残して行き先へ足す", async () => {
      pick("left", 0);
      await page.settle();
      expect($id("gops-left-copy").textContent).toBe("「罵倒集」へ複製 1");
      $id("gops-left-copy").click();
      await page.settle();
      expect(posted).toEqual([{
        url: "/api/bookmarks/bulk", method: "POST",
        body: { op: "copy", ids: [20], group_id: 2 },
      }]);
      expect($id("gops-status").textContent).toContain("複製");
      // moveと違い元が残るので、選択も残す(続けて別の行き先へも複製できる)。
      expect($id("gops-left-selected").textContent).toBe("1");
    });

    it("行き先が「全て」なら移動も複製も押せない(所属の指定にならない)", async () => {
      await setSide("right", "");
      pick("left", 0);
      await page.settle();
      expect($id("gops-left-move").disabled).toBe(true);
      expect($id("gops-left-copy").disabled).toBe(true);
      expect(buttonOf(paneRows("left")[0], "右へ").disabled).toBe(true);
    });

    it("1件だけの付け替えは行のbuttonで済む(選択してから帯まで往復させない)", async () => {
      buttonOf(paneRows("left")[0], "右へ").click();
      await page.settle();
      expect(posted).toEqual([{
        url: "/api/bookmarks/bulk", method: "POST",
        body: { op: "move", ids: [20], group_id: 2 },
      }]);
    });

    it("未分類も行き先になる(所属を外す経路)", async () => {
      await setSide("right", "none");
      pick("left", 0);
      await page.settle();
      $id("gops-left-move").click();
      await page.settle();
      expect(posted).toContainEqual({
        url: "/api/bookmarks/bulk", method: "POST",
        body: { op: "move", ids: [20], group_id: null },
      });
    });

    it("表示中を全選択は絞り込みの後の行だけを取る", async () => {
      $id("gops-filter").querySelector("[data-value=point]").click();
      await page.settle();
      $id("gops-left-all").click();
      await page.settle();
      expect($id("gops-left-selected").textContent).toBe("1");
      $id("gops-left-move").click();
      await page.settle();
      expect(posted).toEqual([{
        url: "/api/bookmarks/bulk", method: "POST",
        body: { op: "move", ids: [21], group_id: 2 },
      }]);
    });

    it("削除は件数を確認で名乗る", async () => {
      pick("left", 0);
      pick("left", 1);
      await page.settle();
      $id("gops-left-delete").click();
      await page.settle();
      expect(doc.querySelector(".confirm-modal").textContent)
        .toContain("見どころ 2件");
      answerConfirm(true);
      await page.settle();
      expect(posted).toContainEqual({
        url: "/api/bookmarks/bulk", method: "POST",
        body: { op: "delete", ids: [20, 21] },
      });
    });

    it("行clickはシーン検索の再生画面へ移る(この画面にplayerは置かない)", async () => {
      paneRows("left")[0].click();
      await page.settle();
      expect($id("view-search").classList.contains("hidden")).toBe(false);
      expect($id("tab-search").classList.contains("active")).toBe(true);
    });
  });

  describe("統合", () => {
    it("左右に実体のあるグループが揃って初めて押せる", async () => {
      await setSide("left", "");
      await setSide("right", "2");
      expect($id("gops-merge").disabled).toBe(true);
      await setSide("left", "2");
      // 同じグループ同士は統合にならない。
      expect($id("gops-merge").disabled).toBe(true);
      await setSide("left", "1");
      expect($id("gops-merge").disabled).toBe(false);
      expect($id("gops-merge").textContent).toBe("「神回」を「罵倒集」へ統合");
    });

    it("確認を越えると1回のAPIで移動と削除まで済ませる", async () => {
      await setSide("left", "1");
      await setSide("right", "2");
      $id("gops-merge").click();
      await page.settle();
      expect(doc.querySelector(".confirm-modal").textContent).toContain("「神回」を削除");
      answerConfirm(true);
      await page.settle();
      expect(posted).toContainEqual({
        url: "/api/groups/1/merge", method: "POST", body: { into: 2 },
      });
      // 消えたグループを指したまま残さない(空の表を「0件」として名乗る)。
      expect($id("gops-left-group").value).toBe("2");
    });
  });
});
