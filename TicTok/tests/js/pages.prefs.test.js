import { describe, it, expect, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// user報告の再現: 画面で選んだ設定が、別の画面へ移って戻ると初期値へ戻る。
// 各画面は独立した document なので nav 遷移はフルリロードで、control の値は
// localStorage に残していない限り必ず消える。
//
// jsdom は JSDOM instance ごとに別の localStorage を持つ。それでは「同じ browser で
// 画面を移った」再現にならないので、instance を跨いで生き残る storage を差し込み、
// 画面1で操作 → 別画面を開く → 画面1へ戻る、を実際に通す。
function sharedStorage() {
  const map = new Map();
  const store = {
    getItem: (k) => (map.has(String(k)) ? map.get(String(k)) : null),
    setItem: (k, v) => map.set(String(k), String(v)),
    removeItem: (k) => map.delete(String(k)),
    clear: () => map.clear(),
    key: (i) => Array.from(map.keys())[i] ?? null,
  };
  Object.defineProperty(store, "length", { get: () => map.size });
  return store;
}

function installStorage(store) {
  return (win) => {
    Object.defineProperty(win, "localStorage", { configurable: true, value: store });
  };
}

describe("画面を切り替えても表示設定が残る", () => {
  const open = [];
  afterEach(async () => {
    while (open.length) await open.pop().close();
  });

  async function visit(store, name, path) {
    const page = loadPage({
      page: name,
      url: `http://localhost:8520${path}`,
      before: installStorage(store),
    });
    open.push(page);
    page.fireReady();
    await page.settle();
    // 復元の途中で例外が出ると、値は戻らないのに画面だけ動いて見える。
    expect(page.errors.map(String)).toEqual([]);
    return page;
  }

  // 画面で control を動かし、別画面を挟んでから戻り、値が残っているかを見る。
  // 「別画面を挟む」ところが肝 — 同じ画面の再読み込みだけでは、user が報告した
  // 画面遷移の経路を通らない。
  async function survivesNavigation(name, path, controls) {
    const store = sharedStorage();
    const first = await visit(store, name, path);

    Object.entries(controls).forEach(([id, next]) => {
      const el = first.document.getElementById(id);
      expect(el, `${name}: #${id} が無い`).toBeTruthy();
      if (typeof next === "boolean") {
        el.checked = next;
      } else {
        el.value = next;
        // 存在しない選択肢を渡すと value は変わらず、そのまま既定値を保存して
        // 「戻っている」ように見えてしまう。操作が効いたことを先に確かめる。
        expect(el.value, `${name}: #${id} に ${next} という選択肢が無い`).toBe(next);
      }
      // 実際のbrowserはselectの選択で input と change の両方を出す。片方だけを出すと、
      // もう片方で購読している画面(履歴の並替はinput)を取り逃がす。
      el.dispatchEvent(new first.win.Event("input", { bubbles: true }));
      el.dispatchEvent(new first.win.Event("change", { bubbles: true }));
    });

    await visit(store, "capacity", "/capacity");
    const back = await visit(store, name, path);

    Object.entries(controls).forEach(([id, want]) => {
      const el = back.document.getElementById(id);
      const got = typeof want === "boolean" ? el.checked : el.value;
      expect(got, `${name}: #${id} が戻っていない`).toBe(want);
    });
    return back;
  }

  it("履歴: 期間・状態・並替が残る", async () => {
    await survivesNavigation("history", "/history", {
      "flt-period": "today",
      "flt-status": "live",
      "flt-sort": "diamonds",
    });
  });

  it("Fan台帳: 並替・絞込が残る", async () => {
    await survivesNavigation("fans", "/fans", {
      "fan-sort": "comments",
      "fan-filter": "multi",
    });
  });

  it("全体監視: 並替が残る", async () => {
    await survivesNavigation("overview", "/overview", { "sort-select": "viewers" });
  });

  it("Job: 状態が残る", async () => {
    await survivesNavigation("jobs", "/jobs", { "job-flt-state": "failed" });
  });

  // 種別(左pane)はbuttonの棚なのでこの型に載らない。selectで持つ表示件数だけをここで見る。
  it("素材: 表示件数が残る", async () => {
    await survivesNavigation("assets", "/assets", { "as-limit": "200" });
  });

  it("運用log: 重要度が残る", async () => {
    await survivesNavigation("ops", "/ops", { "flt-severity": "error" });
  });

  it("全体解析: 期間と表示切替が残る", async () => {
    await survivesNavigation("analytics", "/analytics", {
      "an-period": "30",
      "an-ti-numbers": true,
    });
  });

  it("配信者: heatmapの指標・スコア推移の軸が残る", async () => {
    await survivesNavigation("streamers", "/streamers", {
      "sm-hm-metric": "comments",
      "sm-battle-trend-x": "time",
      "sm-battle-trend-y": "clip",
    });
  });

  it("配信者動画: 検索の並び・素材の絞込が残る", async () => {
    await survivesNavigation("videos", "/videos", {
      "flt-order": "rank",
      "src-stt": false,
    });
  });

  // 折り畳みはcheckbox/selectではなく見出しbuttonなので、survivesNavigationの型に載らない。
  // 「畳んだ状態で戻ってくるか」を、classとaria-expandedの両方で見る(片方だけを直すと、
  // 見た目は畳まれているのに支援技術には開いていると名乗る)。
  it("配信者動画: 文字起こし・コメントの折り畳みが残る", async () => {
    const store = sharedStorage();
    const first = await visit(store, "videos", "/videos");
    ["transcript-fold", "comment-fold"].forEach((id) => {
      first.document.getElementById(id).dispatchEvent(
        new first.win.MouseEvent("click", { bubbles: true }),
      );
    });

    await visit(store, "capacity", "/capacity");
    const back = await visit(store, "videos", "/videos");
    [["transcript-block", "transcript-fold"], ["comment-block", "comment-fold"]]
      .forEach(([block, button]) => {
        expect(
          back.document.getElementById(block).classList.contains("vd-block-folded"),
          `#${block} が畳まれていない`,
        ).toBe(true);
        expect(back.document.getElementById(button).getAttribute("aria-expanded")).toBe("false");
      });
  });

  it("検索語は残さない(1回限りの入力を次の訪問へ持ち越さない)", async () => {
    const store = sharedStorage();
    const first = await visit(store, "history", "/history");
    const search = first.document.getElementById("flt-search");
    search.value = "たまたま調べた人";
    search.dispatchEvent(new first.win.Event("input", { bubbles: true }));

    const back = await visit(store, "history", "/history");
    expect(back.document.getElementById("flt-search").value).toBe("");
  });

  it("URLで名指しした期間は保存値より強い(貼ったlinkが人によって別の集計を指さない)", async () => {
    const store = sharedStorage();
    const first = await visit(store, "analytics", "/analytics");
    const period = first.document.getElementById("an-period");
    period.value = "30";
    period.dispatchEvent(new first.win.Event("change", { bubbles: true }));

    const linked = await visit(store, "analytics", "/analytics?days=7");
    expect(linked.document.getElementById("an-period").value).toBe("7");
  });

  it("保存値が今の選択肢に無いときは既定で始まる(選択なしの空欄にしない)", async () => {
    const store = sharedStorage();
    store.setItem("tictok.history.period", "選択肢から消えた期間");
    const page = await visit(store, "history", "/history");
    const period = page.document.getElementById("flt-period");
    expect(period.value).toBe("all");
    expect(period.selectedIndex).toBeGreaterThanOrEqual(0);
  });

  it("storageが使えない環境でも全画面が組み上がる", async () => {
    const broken = {
      getItem() { throw new Error("SecurityError"); },
      setItem() { throw new Error("SecurityError"); },
      removeItem() { throw new Error("SecurityError"); },
      clear() { throw new Error("SecurityError"); },
      key() { throw new Error("SecurityError"); },
      length: 0,
    };
    const PAGES = [
      ["index", "/"], ["overview", "/overview"], ["history", "/history"],
      ["streamers", "/streamers"], ["videos", "/videos"], ["capacity", "/capacity"],
      ["fans", "/fans"], ["analytics", "/analytics"], ["jobs", "/jobs"],
      ["ops", "/ops"], ["settings", "/settings"],
    ];
    for (const [name, path] of PAGES) {
      const page = await visit(broken, name, path);
      expect(page.loaded[0]).toBe("common.js");
    }
  });
});
