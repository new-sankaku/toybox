import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// Job一覧の行の組み立て。session一括はgroupの合成行と明細行の両方が台帳に載るので、
// 畳み方を誤ると**filterに一致したjobが一覧から消える**。行が出ないだけなので、
// 「そんなjobは無かった」と読まれて終わる。
// 種別labelはserverが唯一の出所(core/ops_labels.py)。画面は応答から選択肢まで作るので、
// stubにこれが無いと種別filterのoptionが1つも生えない。
const KIND_LABELS = {
  overlay: "焼き込み",
  upscale: "Up出力",
  reprocess: "再mp4化",
  stt: "文字起こし",
  session_overlay: "Session 焼き込み",
};
// bootで叩くURL。filterの初期値(状態=実行中・待機中)がそのまま載る。
const BOOT_URL = "GET /api/jobs?state=active&kind=all&limit=200";

// 取り消し・再実行が効くdomainもserverが唯一の出所(api/media_jobs.QUEUED_JOB_DOMAINS)。
// 画面が同じ一覧を持っていた頃は、台帳へ種別が増えても画面が古いままで、実際に文字起こし
// (stt)のjobだけbuttonが出ず、実行中の9時間jobを取り消せなかった。
const QUEUED_KINDS = ["overlay", "upscale", "reprocess", "stt", "session_overlay"];

function jobsBody(extra = {}) {
  return {
    jobs: [], gpu: null, stt: null, total: 0, limit: 200,
    kind_labels: KIND_LABELS, queued_kinds: QUEUED_KINDS, ...extra,
  };
}

describe("jobs.js の行の組み立て", () => {
  let page;
  let win;
  let doc;
  let errorSpy;

  function open(routes, url) {
    page = loadPage({
      page: "jobs",
      url: url ?? "http://localhost:8520/jobs",
      routes: routes ?? { [BOOT_URL]: jobsBody() },
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

  // 別のURL(deep link)・別の応答で開き直す。query初期化はscript評価時に走るので、URLは
  // 読み込み前に決まっていなければならない。afterEachが閉じる相手もここで差し替わる。
  async function reopen(url, routes) {
    errorSpy.mockRestore();
    await page.close();
    await open(routes, url);
  }

  function seed(list) {
    page.set("jobs", list);
  }
  function setFilter({ state = "all", kind = "all", text = "" } = {}) {
    doc.getElementById("job-flt-state").value = state;
    doc.getElementById("job-flt-kind").value = kind;
    doc.getElementById("job-flt-text").value = text;
  }
  function expand(...groupIds) {
    page.run(`expandedGroups.clear(); ${groupIds.map((g) => `expandedGroups.add(${JSON.stringify(g)})`).join("; ")}`);
  }
  const rowIds = () => win.visibleRows().map((r) => r.job.job_id);

  const GROUP = [
    { job_id: "g1", group_id: "g1", state: "running", domain: "overlay", started_at: 100 },
    { job_id: "m1", group_id: "g1", state: "running", domain: "overlay", started_at: 101 },
    { job_id: "m2", group_id: "g1", state: "pending", domain: "overlay", queued_at: 102 },
    { job_id: "solo", state: "completed", domain: "stt", finished_at: 90 },
  ];

  describe("groupの畳み込み", () => {
    it("既定ではgroupの明細を出さず、合成行だけを出す", () => {
      seed(GROUP);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["g1", "solo"]);
    });

    it("合成行には畳んでいる明細の件数を持たせる", () => {
      seed(GROUP);
      setFilter();
      expand();
      const rows = win.visibleRows();
      expect(rows.find((r) => r.job.job_id === "g1").members).toBe(2);
      expect(rows.find((r) => r.job.job_id === "solo").members).toBe(0);
    });

    it("開いたgroupは合成行の直後へ明細を差し込む", () => {
      seed(GROUP);
      setFilter();
      expand("g1");
      expect(rowIds()).toEqual(["g1", "m1", "m2", "solo"]);
    });

    it("差し込んだ明細はsub行として印を持つ", () => {
      seed(GROUP);
      setFilter();
      expand("g1");
      const rows = win.visibleRows();
      expect(rows.map((r) => Boolean(r.sub))).toEqual([false, true, true, false]);
    });
  });

  // ここが本題。filterでgroupの合成行が落ちたとき、明細を畳んだまま隠すと
  // 「filterに一致しているのに一覧に出ないjob」ができる。
  describe("groupの合成行がfilterで落ちたとき", () => {
    it("明細を単独行として出す(消さない)", () => {
      seed([
        { job_id: "g1", group_id: "g1", state: "completed", domain: "overlay", finished_at: 50 },
        { job_id: "m1", group_id: "g1", state: "running", domain: "overlay", started_at: 101 },
      ]);
      setFilter({ state: "active" });
      expand();
      // 合成行(completed)はfilterから外れるが、実行中の明細は出す。
      expect(rowIds()).toEqual(["m1"]);
    });

    it("種別filterで合成行が落ちた場合も同じ", () => {
      seed([
        { job_id: "g1", group_id: "g1", state: "running", domain: "session_overlay", started_at: 100 },
        { job_id: "m1", group_id: "g1", state: "running", domain: "overlay", started_at: 101 },
      ]);
      setFilter({ kind: "overlay" });
      expand();
      expect(rowIds()).toEqual(["m1"]);
    });
  });

  describe("filter", () => {
    // domain は 種別select の option value と同じ語を使う(選べない種別で絞ると
    // 一致0件になるため、実際に選べる値でしかこの経路は再現できない)。
    const LIST = [
      { job_id: "a", state: "running", domain: "overlay", started_at: 10 },
      { job_id: "b", state: "pending", domain: "overlay", queued_at: 11 },
      { job_id: "c", state: "completed", domain: "upscale", finished_at: 12 },
      { job_id: "d", state: "failed", domain: "upscale", finished_at: 13 },
      { job_id: "e", state: "interrupted", domain: "reprocess", finished_at: 14 },
      { job_id: "f", state: "cancelled", domain: "reprocess", finished_at: 15 },
    ];

    it("active は実行中と待機中だけ", () => {
      seed(LIST);
      setFilter({ state: "active" });
      expand();
      expect(rowIds().sort()).toEqual(["a", "b"]);
    });

    it("failed は失敗と中断だけ(取り消しは混ぜない)", () => {
      seed(LIST);
      setFilter({ state: "failed" });
      expand();
      expect(rowIds().sort()).toEqual(["d", "e"]);
    });

    it("all は全部", () => {
      seed(LIST);
      setFilter({ state: "all" });
      expand();
      expect(rowIds()).toHaveLength(6);
    });

    it("種別は domain で絞る", () => {
      seed(LIST);
      setFilter({ kind: "upscale" });
      expand();
      expect(rowIds().sort()).toEqual(["c", "d"]);
    });

    it("状態と種別は同時に効く", () => {
      seed(LIST);
      setFilter({ state: "failed", kind: "upscale" });
      expand();
      expect(rowIds()).toEqual(["d"]);
    });
  });

  // 動いているjobを過去のjobの下に埋めない。
  describe("並び", () => {
    it("実行中 → 待機中 → 終わったもの の順に置く", () => {
      seed([
        { job_id: "done", state: "completed", finished_at: 999 },
        { job_id: "wait", state: "pending", queued_at: 1 },
        { job_id: "run", state: "running", started_at: 2 },
      ]);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["run", "wait", "done"]);
    });

    it("同じ状態どうしは新しいものが上", () => {
      seed([
        { job_id: "old", state: "completed", finished_at: 100 },
        { job_id: "new", state: "completed", finished_at: 200 },
      ]);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["new", "old"]);
    });

    it("時刻はfinished→started→queuedの順に見る", () => {
      seed([
        { job_id: "q", state: "completed", queued_at: 500 },
        { job_id: "s", state: "completed", started_at: 300, queued_at: 1 },
      ]);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["q", "s"]);
    });

    it("元の配列を並べ替えない(台帳の順序を壊さない)", () => {
      const list = [
        { job_id: "done", state: "completed", finished_at: 999 },
        { job_id: "run", state: "running", started_at: 2 },
      ];
      seed(list);
      setFilter();
      expand();
      win.visibleRows();
      expect(page.get("jobs").map((j) => j.job_id)).toEqual(["done", "run"]);
    });
  });

  describe("状態badge", () => {
    it("未知の状態でも行を落とさず、その状態名をそのまま出す", () => {
      const cell = win.stateCell({ state: "なにか未知" });
      expect(cell.textContent).toBe("なにか未知");
    });

    it("対象なし(skipped)は失敗色にしない", () => {
      expect(win.stateCell({ state: "skipped" }).className).toBe("badge badge-idle");
      expect(win.stateCell({ state: "failed" }).className).toBe("badge badge-error");
    });

    it("前提の復帰待ちは順番待ちと区別して名乗る", () => {
      const future = { state: "pending", not_before: Date.now() / 1000 + 600, stage: "K:の復帰待ち" };
      const cell = win.stateCell(future);
      expect(cell.textContent).toBe("復帰待ち");
      expect(cell.title).toBe("K:の復帰待ち");
    });

    it("待ち時刻を過ぎた待機は通常の待機中に戻る", () => {
      const past = { state: "pending", not_before: Date.now() / 1000 - 600 };
      expect(win.stateCell(past).textContent).toBe("待機中");
    });
  });

  // 種別の訳語は運用log(ops_events)のmessage文にも出る。画面にも同じ表を置くと必ずずれる
  // ので、labelも選択肢もserverの応答から作る。
  describe("種別label", () => {
    it("serverが返したlabelで引く", () => {
      expect(win.kindText({ domain: "upscale" })).toBe("Up出力");
      expect(win.kindText({ domain: "overlay" })).toBe("焼き込み");
    });

    it("表に無いdomainは生値のまま出す(訳語を作らない)", () => {
      expect(win.kindText({ domain: "みしらぬ処理" })).toBe("みしらぬ処理");
    });

    it("起動時sweepが積んだjobは自動と名乗る", () => {
      expect(win.kindText({ domain: "overlay", sweep: true })).toBe("焼き込み（自動）");
    });

    it("種別selectの選択肢もserverの応答から作る", () => {
      const options = [...doc.getElementById("job-flt-kind").options].map((o) => o.value);
      expect(options).toEqual(["all", ...Object.keys(KIND_LABELS)]);
    });

    it("labelを1つも受け取れていない間は生値で並べる(空欄にしない)", async () => {
      // 応答が失敗したときにlabelが無いのは正常。ここで訳語を捏造しないことを確かめる。
      await reopen("http://localhost:8520/jobs", {});
      expect(win.kindText({ domain: "overlay" })).toBe("overlay");
    });
  });

  // serverへ渡すfilter。台帳の新しい200行を一括投入が埋めた日でも、古い失敗を拾えること。
  describe("filterの受け渡し", () => {
    it("bootのrequestに状態・種別・上限を載せる", () => {
      const urls = page.calls.fetches.map((f) => f.url);
      expect(urls).toContain("/api/jobs?state=active&kind=all&limit=200");
    });

    it("状態を変えるとserverへ取り直しに行く(手元の200件を絞るだけにしない)", async () => {
      const url = "GET /api/jobs?state=failed&kind=all&limit=200";
      await reopen("http://localhost:8520/jobs", {
        [BOOT_URL]: jobsBody(), [url]: jobsBody(),
      });
      doc.getElementById("job-flt-state").value = "failed";
      doc.getElementById("job-flt-state").dispatchEvent(new win.Event("change"));
      await page.settle();
      expect(page.calls.fetches.map((f) => f.url))
        .toContain("/api/jobs?state=failed&kind=all&limit=200");
    });

    it("?kind= は選択肢が出来る前でも最初のrequestに載る(2往復しない)", async () => {
      await reopen("http://localhost:8520/jobs?kind=upscale", {
        "GET /api/jobs?state=active&kind=upscale&limit=200": jobsBody(),
      });
      expect(page.calls.fetches.map((f) => f.url).filter((u) => u.startsWith("/api/jobs")))
        .toEqual(["/api/jobs?state=active&kind=upscale&limit=200"]);
      // 選択肢が届いた後はselectにも入る。
      expect(doc.getElementById("job-flt-kind").value).toBe("upscale");
    });

    it("対象の絞込はserverを叩かない(1文字ごとに取り直さない)", async () => {
      const before = page.calls.fetches.length;
      const input = doc.getElementById("job-flt-text");
      input.value = "あ";
      input.dispatchEvent(new win.Event("input"));
      await page.settle();
      expect(page.calls.fetches.length).toBe(before);
    });
  });

  describe("対象で絞込", () => {
    const LIST = [
      { job_id: "a1", state: "completed", domain: "overlay", finished_at: 10,
        filename: "00007_alice_20260102_010203.mp4" },
      { job_id: "b2", state: "completed", domain: "overlay", finished_at: 11,
        filename: "00008_bob_20260102_010203.mp4" },
    ];

    it("対象の文字列に部分一致した行だけを出す", () => {
      seed(LIST);
      setFilter({ text: "alice" });
      expand();
      expect(rowIds()).toEqual(["a1"]);
    });

    it("job idでも引ける(運用logからの誘導がidで飛んでくる)", () => {
      seed(LIST);
      setFilter({ text: "b2" });
      expand();
      expect(rowIds()).toEqual(["b2"]);
    });

    it("大文字小文字は区別しない", () => {
      seed(LIST);
      setFilter({ text: "ALICE" });
      expand();
      expect(rowIds()).toEqual(["a1"]);
    });
  });

  // 運用logの「このjobを見る」からの着地。目的の行が見えるfilterで降りないと空の表になる。
  describe("?job= の受け口", () => {
    it("絞込入力へ入り、状態は全てになる(終わったjobでも見える)", async () => {
      await reopen("http://localhost:8520/jobs?job=beef00", {
        "GET /api/jobs?state=all&kind=all&limit=200&job=beef00": jobsBody(),
      });
      expect(doc.getElementById("job-flt-text").value).toBe("beef00");
      expect(doc.getElementById("job-flt-state").value).toBe("all");
    });

    it("serverへも名指しで渡す(直近200件の外に居ても着地できる)", async () => {
      await reopen("http://localhost:8520/jobs?job=beef00", {
        "GET /api/jobs?state=all&kind=all&limit=200&job=beef00": jobsBody(),
      });
      expect(page.calls.fetches.map((f) => f.url).filter((u) => u.startsWith("/api/jobs")))
        .toEqual(["/api/jobs?state=all&kind=all&limit=200&job=beef00"]);
    });

    it("入力を人が触ったら名指しを外して取り直す(何を打っても0件、を避ける)", async () => {
      await reopen("http://localhost:8520/jobs?job=beef00", {
        "GET /api/jobs?state=all&kind=all&limit=200&job=beef00": jobsBody(),
        "GET /api/jobs?state=all&kind=all&limit=200": jobsBody(),
      });
      const input = doc.getElementById("job-flt-text");
      input.value = "alice";
      input.dispatchEvent(new win.Event("input"));
      await page.settle();
      expect(page.calls.fetches.map((f) => f.url))
        .toContain("/api/jobs?state=all&kind=all&limit=200");
    });

    it("状態が明示されていればそちらを優先する", async () => {
      await reopen("http://localhost:8520/jobs?job=beef00&state=failed", {
        "GET /api/jobs?state=failed&kind=all&limit=200&job=beef00": jobsBody(),
      });
      expect(doc.getElementById("job-flt-state").value).toBe("failed");
    });
  });

  // GPU現況と一覧の食い違いの説明。filterで隠しただけのjobを「別queueの実行」と名指し
  // しないこと(状態・種別で絞ると、実行中の行はそもそも一覧に出ない)。
  describe("台帳外のGPU実行の注記", () => {
    beforeEach(() => {
      page.run(`gpu = { active: ["overlay"], limit: 1, waiting: 0 }`);
      seed([]);
    });

    it("絞っていなければ、台帳に無い実行として名乗る", () => {
      setFilter();
      win.render();
      expect(doc.getElementById("gpu-summary").textContent).toContain("下の一覧に出ない別queue");
    });

    it("失敗のみで絞っている間は言わない(隠しただけかもしれない)", () => {
      setFilter({ state: "failed" });
      win.render();
      expect(doc.getElementById("gpu-summary").textContent).not.toContain("別queue");
    });

    it("種別で絞っている間も言わない", () => {
      setFilter({ kind: "upscale" });
      win.render();
      expect(doc.getElementById("gpu-summary").textContent).not.toContain("別queue");
    });
  });

  // navのtabはfilterを積まない(積むと、失敗が履歴に残っている間ずっと「失敗・中断のみ」へ
  // 着地して人の選んだ状態filterを毎回上書きする)。隠れている失敗を名乗る口はこの画面側。
  describe("filterで隠れている失敗の注記", () => {
    const note = () => doc.getElementById("job-failed-note");
    function seedBar(list) {
      win.applyJobBar({ type: "jobs", data: list });
    }

    it("実行中・待機中で絞っている間は、隠れている失敗の件数と行き先を出す", () => {
      seedBar([{ job_id: "1", state: "failed" }, { job_id: "2", state: "interrupted" }]);
      setFilter({ state: "active" });
      win.render();
      expect(note().textContent).toContain("失敗・中断が2件");
      expect(note().querySelector("a").getAttribute("href")).toBe("/jobs?state=failed");
    });

    it("失敗が無ければ何も出さない", () => {
      seedBar([{ job_id: "1", state: "running" }]);
      setFilter({ state: "active" });
      win.render();
      expect(note().textContent).toBe("");
    });

    it("全て・失敗のみで見ているときは出さない(一覧に出ている)", () => {
      seedBar([{ job_id: "1", state: "failed" }]);
      setFilter({ state: "all" });
      win.render();
      expect(note().textContent).toBe("");
      setFilter({ state: "failed" });
      win.render();
      expect(note().textContent).toBe("");
    });

    it("種別・対象で絞っている間は出さない(その範囲の件数ではない)", () => {
      seedBar([{ job_id: "1", state: "failed" }]);
      setFilter({ state: "active", kind: "upscale" });
      win.render();
      expect(note().textContent).toBe("");
      setFilter({ state: "active", text: "abc" });
      win.render();
      expect(note().textContent).toBe("");
    });
  });

  describe("列clickでの並べ替え", () => {
    const LIST = [
      { job_id: "run", state: "running", domain: "overlay", started_at: 5, queued_at: 1 },
      { job_id: "wait", state: "pending", domain: "overlay", queued_at: 20 },
      { job_id: "done", state: "completed", domain: "overlay", finished_at: 50, queued_at: 9 },
    ];
    const click = (key) => doc.querySelector(`#job-table th[data-sort="${key}"]`).click();

    it("既定は実行中→待機中→その他のまま", () => {
      seed(LIST);
      setFilter();
      expand();
      expect(rowIds()).toEqual(["run", "wait", "done"]);
    });

    it("1回目は降順、2回目は昇順", () => {
      seed(LIST);
      setFilter();
      expand();
      click("queued");
      expect(rowIds()).toEqual(["wait", "done", "run"]);
      click("queued");
      expect(rowIds()).toEqual(["run", "done", "wait"]);
    });

    it("3回目で既定の並びへ戻る", () => {
      seed(LIST);
      setFilter();
      expand();
      click("queued");
      click("queued");
      click("queued");
      expect(page.get("sortState")).toBe(null);
      expect(rowIds()).toEqual(["run", "wait", "done"]);
    });

    it("並べ替え中の列をheaderが名乗る", () => {
      seed(LIST);
      setFilter();
      click("queued");
      const th = doc.querySelector('#job-table th[data-sort="queued"]');
      expect(th.getAttribute("aria-sort")).toBe("descending");
      click("queued");
      expect(th.getAttribute("aria-sort")).toBe("ascending");
    });
  });

  describe("列の書式", () => {
    function cellsOf(job) {
      seed([job]);
      setFilter();
      expand();
      win.render();
      return [...doc.querySelectorAll("#job-rows tr:first-child td")];
    }

    it("投入は0埋めの月日時分秒(運用logと同じ書式)", () => {
      const at = new Date(2026, 7, 2, 9, 3, 4).getTime() / 1000;
      const cells = cellsOf({ job_id: "x", state: "completed", domain: "overlay",
        finished_at: at, queued_at: at });
      expect(cells[4].textContent).toBe("08/02 09:03:04");
    });

    // 待機中のjobの所要をqueued_atからの経過で出していた頃は、順番待ちの時間が
    // 「実行にかかった時間」として積み上がり、まだ1秒も動いていないjobが3時間かかった
    // ように読めた(待機列が詰まっているのか重いjobなのかを取り違える)。
    it("所要は実行時間だけを出す(待機中は待機の長さと名乗る)", () => {
      // jobs.js は jsdom realm の中で動くので、そちらの Date を止める。
      const now = 1_000_000_000;
      const clock = vi.spyOn(win.Date, "now").mockReturnValue(now * 1000);
      try {
        const waiting = cellsOf({ job_id: "w", state: "pending", domain: "overlay",
          queued_at: now - 3600 });
        expect(waiting[5].textContent).toBe("待機 01:00:00");
        expect(waiting[5].querySelector(".job-wait")).not.toBeNull();
        const running = cellsOf({ job_id: "r", state: "running", domain: "overlay",
          queued_at: now - 3600, started_at: now - 60 });
        expect(running[5].textContent).toBe("00:01:00");
        const done = cellsOf({ job_id: "d", state: "completed", domain: "overlay",
          queued_at: now - 3600, started_at: now - 3000, finished_at: now - 2880 });
        expect(done[5].textContent).toBe("00:02:00");
      } finally {
        clock.mockRestore();
      }
    });

    // 実行前に取り消した(始まっていないまま終わった)行は所要そのものが無い。
    // 待機の長さを出すと、もう並んでいないjobが待ち続けているように見える。
    it("実行されずに終わったjobの所要は空(-)", () => {
      const now = 1_000_000_000;
      const cells = cellsOf({ job_id: "c", state: "cancelled", domain: "overlay",
        queued_at: now - 3600, finished_at: now });
      expect(cells[5].textContent).toBe("-");
    });

    it("投入と所要は右寄せ(num)で、headerも同じ列に合わせる", () => {
      cellsOf({ job_id: "x", state: "completed", domain: "overlay", queued_at: 1 });
      const cells = [...doc.querySelectorAll("#job-rows tr:first-child td")];
      expect([cells[4].className, cells[5].className]).toEqual(["num", "num"]);
      const heads = [...doc.querySelectorAll("#job-table thead th")];
      expect([heads[4].className, heads[5].className]).toEqual(["num", "num"]);
    });

    // 操作列。取り消せるかどうかの根拠は応答のqueued_kinds。画面に一覧を持っていた頃は
    // 台帳へ足された種別(stt/laugh)が漏れ、実行中のjobを止める手段が画面から無かった。
    const actionLabels = () =>
      [...doc.querySelectorAll("#job-rows tr:first-child .row-actions button")]
        .map((b) => b.textContent);

    it("台帳のjobは実行中でも取り消せる(種別はserverの一覧で判断する)", () => {
      cellsOf({ job_id: "x", state: "running", domain: "stt", started_at: 1 });
      expect(actionLabels()).toEqual(["取り消し"]);
    });

    it("台帳に無い種別(容量scan等)はbuttonを出さない", () => {
      cellsOf({ job_id: "x", state: "running", domain: "storage", started_at: 1 });
      expect(actionLabels()).toEqual([]);
    });

    // 1行に切ってtooltipへ回していた頃は、肝心の失敗理由がhoverした時にしか読めず、
    // 「見切れてメッセージが分からない」まま残っていた。列幅の上限はCSSが持つ。
    it("結果の長文は全文をそのまま出す(切らない)", () => {
      const message = "ffmpeg exited with 1:\n" + "x".repeat(300);
      const cells = cellsOf({ job_id: "x", state: "failed", domain: "overlay",
        finished_at: 1, message });
      const result = cells[6].firstChild;
      expect(result.className).toBe("job-result");
      expect(result.textContent).toBe(message);
    });

    // 成果物を作るjobはどれもpathを返しているのに、この列はfile名しか出しておらず
    // 「どこに出来たのか分からない」ままだった。切り出しは配信者別の _clips へ出るうえ、
    // rootが録画の所在で変わるので、dirまで出さないと利用者は成果物に辿り着けない。
    it("成果物の置き場をfile名と一緒に出す", () => {
      const cells = cellsOf({ job_id: "x", state: "completed", domain: "overlay",
        finished_at: 1,
        result: { filename: "a.overlay.mp4", output_path: "K:\\rec\\u\\mp4\\a.overlay.mp4" } });
      const result = cells[6].firstChild;
      expect(result.textContent).toContain("a.overlay.mp4");
      expect(result.querySelector(".job-result-path").textContent).toBe("K:\\rec\\u\\mp4");
    });

    it("一括切り出しは件数と出力先dirを出す(file名は1本に定まらない)", () => {
      const cells = cellsOf({ job_id: "x", state: "completed", domain: "clip_batch",
        finished_at: 1,
        result: { count: 3, output_dir: "K:\\rec\\_clips\\u" } });
      const result = cells[6].firstChild;
      expect(result.textContent).toContain("3件を切り出し");
      expect(result.querySelector(".job-result-path").textContent).toBe("K:\\rec\\_clips\\u");
    });

    // 失敗理由と置き場が1つの塊になると、どちらも読めなくなる。
    it("失敗した行にはpathを足さない", () => {
      const cells = cellsOf({ job_id: "x", state: "failed", domain: "overlay",
        finished_at: 1, message: "ffmpeg exited with 1",
        result: { output_path: "K:\\rec\\u\\mp4\\a.mp4" } });
      expect(cells[6].firstChild.querySelector(".job-result-path")).toBe(null);
    });
  });

  // 終わったjobの進捗列は「完了 ✓」しか出せず、どの段階に何秒かかったか・どこで落ちたかを
  // 辿る先が無かった。段階の履歴は台帳(stages)が唯一の出所。
  describe("段階の経過", () => {
    const STAGES = [
      { label: "(1/3) 動画を解析中", at: 1000, pct: 2 },
      { label: "(2/3) コメント層を描画中", at: 1010, pct: 30 },
      { label: "(3/3) 焼き込み合成中", at: 1070, pct: 60 },
    ];
    function cellsOf(job) {
      seed([job]);
      setFilter();
      expand();
      win.render();
      return [...doc.querySelectorAll("#job-rows tr:first-child td")];
    }
    const stageRows = () => [...doc.querySelectorAll("#job-rows .job-stages li")]
      .map((li) => [li.querySelector(".s-label").textContent,
                    li.querySelector(".s-time").textContent]);

    it("既定では畳み、段階数だけを名乗る", () => {
      const cells = cellsOf({ job_id: "x", state: "completed", domain: "overlay",
        finished_at: 1100, stages: STAGES });
      const toggle = cells[3].querySelector(".job-stage-toggle");
      expect(toggle.textContent).toBe("▶ 経過 3段階");
      expect(cells[3].querySelector(".job-stages")).toBe(null);
    });

    it("開くと段階ごとの所要が出る(最後は終了時刻まで)", () => {
      const cells = cellsOf({ job_id: "x", state: "completed", domain: "overlay",
        finished_at: 1100, stages: STAGES });
      cells[3].querySelector(".job-stage-toggle").click();
      expect(stageRows()).toEqual([
        ["(1/3) 動画を解析中", "00:00:10"],
        ["(2/3) コメント層を描画中", "00:01:00"],
        ["(3/3) 焼き込み合成中", "00:00:30"],
      ]);
    });

    it("失敗したjobは最後の段階に印を付ける(そこで落ちた)", () => {
      const cells = cellsOf({ job_id: "x", state: "failed", domain: "overlay",
        finished_at: 1100, stages: STAGES });
      cells[3].querySelector(".job-stage-toggle").click();
      const items = [...doc.querySelectorAll("#job-rows .job-stages li")];
      expect(items.map((li) => li.className)).toEqual(["", "", "s-failed"]);
    });

    it("段階を1件も持たないjob(既存行・group合成行)には出さない", () => {
      const cells = cellsOf({ job_id: "x", state: "completed", domain: "overlay",
        finished_at: 1100 });
      expect(cells[3].querySelector(".job-stage-toggle")).toBe(null);
    });

    it("実行中でも通ってきた段階を出す(進捗列は今の1点しか持たない)", () => {
      const cells = cellsOf({ job_id: "x", state: "running", domain: "overlay",
        started_at: 1000, pct: 60, stage: "(3/3) 焼き込み合成中（1:00 / 2:00）",
        stages: STAGES });
      expect(cells[3].querySelector(".dl-progress")).not.toBe(null);
      expect(cells[3].querySelector(".job-stage-toggle").textContent).toBe("▶ 経過 3段階");
    });
  });

  // limitで切れた一覧を「これが全部」と読ませない。0件の断定が一番の害だった。
  describe("読み込み上限の告知", () => {
    it("台帳の該当件数がlimitを超えていたら常に名乗る", async () => {
      await reopen("http://localhost:8520/jobs", {
        [BOOT_URL]: jobsBody({ total: 512, limit: 200 }),
      });
      expect(doc.getElementById("job-limit-note").textContent)
        .toBe("※ 直近200件のみ表示（該当 512件）");
    });

    it("切れていなければ何も出さない", () => {
      expect(doc.getElementById("job-limit-note").textContent).toBe("");
    });

    it("0件の文言は、切れているときだけ見えていない行の存在を先に言う", async () => {
      await reopen("http://localhost:8520/jobs", {
        [BOOT_URL]: jobsBody({ total: 512, limit: 200 }),
      });
      doc.getElementById("job-flt-text").value = "一致しない語";
      win.render();
      expect(doc.getElementById("job-empty").textContent)
        .toContain("台帳の該当は512件");
    });

    it("filterを外していれば0件は0件と出す", () => {
      seed([]);
      setFilter();
      win.render();
      expect(doc.getElementById("job-empty").textContent).toBe("jobはありません。");
    });
  });
});
