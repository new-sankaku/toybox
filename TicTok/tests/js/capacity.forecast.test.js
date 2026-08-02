import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 容量の予測表示。ここは「数字を出せないとき」の扱いがすべてで、出せない理由を伏せて
// 数字や0を描くと、**満杯までの猶予を実際より長く読ませる**。行は出ているので誤りに見えない。
describe("capacity.js の予測表示", () => {
  let page;
  let win;
  let errorSpy;

  beforeEach(async () => {
    page = loadPage({ page: "capacity", url: "http://localhost:8520/capacity" });
    win = page.win;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  describe("fmtDays", () => {
    it("2日以上は整数の日で丸める", () => {
      expect(win.fmtDays(2)).toBe("2 日");
      expect(win.fmtDays(2.4)).toBe("2 日");
      expect(win.fmtDays(2.6)).toBe("3 日");
      expect(win.fmtDays(399)).toBe("399 日");
    });

    it("2日未満は小数1桁(「0 日」に潰さない)", () => {
      expect(win.fmtDays(1.5)).toBe("1.5 日");
      expect(win.fmtDays(0.4)).toBe("0.4 日");
      expect(win.fmtDays(0)).toBe("0.0 日");
    });

    it("400日以上は具体的な日数を装わない", () => {
      expect(win.fmtDays(400)).toBe("1年以上");
      expect(win.fmtDays(5000)).toBe("1年以上");
    });
  });

  describe("forecastCell", () => {
    it("数字を出すのは status=ok のときだけ、しかも幅で出す", () => {
      expect(win.forecastCell({ status: "ok", days_low: 12.3, days_high: 40.6 })).toBe(
        "12 日 〜 41 日",
      );
    });

    it("観測期間より先は「少なくとも」と断って下限だけ出す", () => {
      expect(win.forecastCell({ status: "beyond_horizon", beyond_days: 120 })).toBe(
        "少なくとも 120 日 先",
      );
    });

    it("出せない理由はそれぞれの文言で名乗る(空欄や0にしない)", () => {
      expect(win.forecastCell({ status: "insufficient_data" })).toBe("記録が足りません");
      expect(win.forecastCell({ status: "not_shrinking" })).toBe("減っていません");
      expect(win.forecastCell({ status: "inconclusive" })).toBe("減少と言い切れません");
    });

    it("未知のstatusでも数字を作らない", () => {
      expect(win.forecastCell({ status: "なにか未知" })).toBe("—");
      expect(win.forecastCell({})).toBe("—");
    });
  });

  describe("forecastTitle", () => {
    it("観測日数と件数を添える", () => {
      const title = win.forecastTitle({ status: "ok", observed_days: 12.34, n: 1234 });
      expect(title).toContain("観測 12.3 日");
      expect(title).toContain("記録 1,234 件");
    });

    it("観測日数が無くても件数だけは出す", () => {
      expect(win.forecastTitle({ status: "ok", n: 5 })).toContain("記録 5 件");
    });

    it("あてはまりは読み方まで添える(数字だけでは意味が伝わらない)", () => {
      const title = win.forecastTitle({ status: "ok", r2: 0.9367 });
      expect(title).toContain("0.94");
      expect(title).toContain("1.00に近いほど");
    });

    it("記録が足りないときは必要件数を言う", () => {
      const title = win.forecastTitle({ status: "insufficient_data", n: 1, min_samples: 3 });
      expect(title).toContain("予測には記録が 3 件必要です");
    });

    it("何も分からなければ空(嘘の根拠を作らない)", () => {
      expect(win.forecastTitle({ status: "ok" })).toBe("");
    });
  });

  // 容量の合計。bytesを持たない行を黙って0GBとして混ぜると、合計が実態より小さく見え、
  // 「まだ空きがある」と読ませる。書式は画面全体で fmtBytesGb に揃える(同じ値が2つの
  // 見た目で並ぶと別の量に見える)。
  describe("placeTotalText", () => {
    it("本数と容量を併記する", () => {
      expect(win.placeTotalText({ items: 1234, bytes: 1024 ** 3 * 25 })).toBe(
        "1,234 本 / 25.0 GB",
      );
    });

    it("容量不明の行があればその本数を明示する", () => {
      const text = win.placeTotalText({ items: 10, bytes: 1024 ** 3, unknown_bytes: 3 });
      expect(text).toBe("10 本 / 1.0 GB / 容量不明 3 本");
    });

    it("容量不明が0本なら余計な但し書きを出さない", () => {
      const text = win.placeTotalText({ items: 10, bytes: 1024 ** 3, unknown_bytes: 0 });
      expect(text).toBe("10 本 / 1.0 GB");
    });

    it("集計自体が無ければ - (0本と描かない)", () => {
      expect(win.placeTotalText(null)).toBe("-");
      expect(win.placeTotalText(undefined)).toBe("-");
    });
  });

  // 内訳が取れなかったときに、見出しだけの空欄を残すと「走査していない」と読まれる。
  // このtestのroutesは空なので /api/storage/usage は404になる。
  describe("内訳の取得に失敗したとき", () => {
    it("種別・配信者のどちらも理由を名乗る(空欄にしない)", () => {
      ["usage-category-empty", "usage-streamer-empty"].forEach((id) => {
        const el = page.document.getElementById(id);
        expect(el.classList.contains("hidden")).toBe(false);
        expect(el.textContent).toContain("取得できませんでした");
        expect(el.classList.contains("list-failed")).toBe(true);
      });
    });
  });
});

// 最終保存先への移動は分単位かかる。押した本人のtabにしか実行中が出ないと、再読み込みや
// 別tabからは「押していない」ように見えて二重に押される。実行中かどうかの出所はjob台帳で、
// WSが接続時にsnapshotを配るので、そこから復元できることを確かめる。
describe("capacity.js の移動の実行状態", () => {
  let page;
  let errorSpy;

  const CAPACITY = {
    now: { disk: { volumes: {} }, db_files: {}, backups: {}, rows: {} },
    sampled_at: null,
    samples: [],
    forecasts: {},
    recording_daily: [],
    placement: {
      enabled: true,
      record_dir: "K:/work",
      final_dir: "L:/final",
      items: 2,
      bytes: 1024 ** 3,
      locations: { work: { items: 2, bytes: 1024 ** 3 } },
    },
    completion: {},
  };

  beforeEach(async () => {
    page = loadPage({
      page: "capacity",
      url: "http://localhost:8520/capacity",
      routes: { "/api/capacity": CAPACITY, "/api/disk": { volumes: {} } },
    });
    errorSpy = vi.spyOn(page.win.console, "error").mockImplementation(() => {});
    await page.settle();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const socket = () => page.calls.sockets[page.calls.sockets.length - 1];

  it("台帳のsnapshotに実行中の移動があれば、移動中を出して実行を止める", async () => {
    socket().emit({
      type: "jobs",
      data: [{ job_id: "a1", domain: "relocate", state: "running", title: "最終保存先へ退避" }],
    });
    await page.settle();
    const status = page.document.getElementById("reloc-status");
    expect(status.textContent).toContain("移動中");
    expect(status.querySelector("a").getAttribute("href")).toBe("/jobs?kind=relocate");
    expect(page.document.getElementById("reloc-apply").disabled).toBe(true);
  });

  it("他のjobでは止めない(容量scanと同じ扱いにしない)", async () => {
    socket().emit({
      type: "jobs",
      data: [{ job_id: "b1", domain: "storage", state: "running", title: "容量scan" }],
    });
    await page.settle();
    expect(page.document.getElementById("reloc-apply").disabled).toBe(false);
    expect(page.document.getElementById("reloc-status").textContent).toBe("");
  });

  it("終わったら押せる状態へ戻し、現況を取り直す", async () => {
    socket().emit({
      type: "jobs",
      data: [{ job_id: "a1", domain: "relocate", state: "running", title: "最終保存先へ退避" }],
    });
    await page.settle();
    const before = page.calls.fetches.filter((f) => f.url === "/api/capacity").length;
    socket().emit({
      type: "job_update",
      job: { job_id: "a1", domain: "relocate", state: "completed", title: "最終保存先へ退避" },
    });
    await page.settle();
    expect(page.document.getElementById("reloc-apply").disabled).toBe(false);
    expect(page.document.getElementById("reloc-status").textContent).toBe("");
    const after = page.calls.fetches.filter((f) => f.url === "/api/capacity").length;
    expect(after).toBe(before + 1);
  });
});

// 配信者別の内訳。列を画面がhard-codeしていた頃は、serverが返す11種別のうち5種別しか
// 列が無く、「容量」列(全種別の合計)と内訳の和が合わなかった。_backup(再mp4化の退避)は
// 配信者別では完全に不可視で、合計だけが大きい理由が画面から辿れなかった。
describe("capacity.js の配信者別の内訳", () => {
  let page;
  let win;
  let errorSpy;

  const GB = 1024 ** 3;
  // serverの定義(record/disk_scan.py)と同じ形。順序も文言もserverが持つ。
  const CATEGORY_LABELS = [
    { key: "source", label: "生録画(mp4)" },
    { key: "overlay", label: "焼き込み(overlay)" },
    { key: "up", label: "Up出力(up)" },
    { key: "transient", label: "renderの中間file" },
    { key: "ts", label: "HLS中間data(.ts)" },
    { key: "sidecar", label: "sidecar(timing/meta/log)" },
    { key: "avatar", label: "アイコンcache" },
    { key: "icon", label: "Gift Icon/絵文字cache" },
    { key: "clip", label: "切り出しclip" },
    { key: "backup", label: "再mp4化の退避(_backup)" },
    { key: "other", label: "その他" },
  ];

  // 1配信者だけの走査結果。種別の合計は配信者ぶんの合計に一致する。
  const perStreamer = {
    source: 100 * GB,
    overlay: 40 * GB,
    up: 30 * GB,
    ts: 20 * GB,
    transient: 10 * GB,
    backup: 7 * GB,
    sidecar: 2 * GB,
    clip: GB,
  };

  function usagePayload() {
    const categories = {};
    CATEGORY_LABELS.forEach(({ key }) => {
      categories[key] = { bytes: perStreamer[key] || 0, files: perStreamer[key] ? 1 : 0 };
    });
    const total = Object.values(perStreamer).reduce((sum, n) => sum + n, 0);
    return {
      roots: ["K:/rec"],
      scan: {
        scanned_at: 1767000000,
        duration_ms: 12000,
        usage: {
          roots: ["K:/rec"],
          categories,
          category_labels: CATEGORY_LABELS,
          regenerable_categories: ["overlay", "up", "transient"],
          streamers: [{
            streamer: "tester",
            label: "tester",
            bytes: total,
            files: 8,
            categories: Object.fromEntries(
              Object.entries(perStreamer).map(([key, bytes]) => [key, { bytes, files: 1 }]),
            ),
          }],
          total_bytes: total,
          total_files: 8,
          errors: [],
        },
      },
    };
  }

  beforeEach(async () => {
    page = loadPage({ page: "capacity", url: "http://localhost:8520/capacity" });
    win = page.win;
    errorSpy = vi.spyOn(win.console, "error").mockImplementation(() => {});
    await page.settle();
    win.renderUsage(usagePayload());
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const headers = () =>
    Array.from(page.document.querySelectorAll("#usage-streamer-head th")).map(
      (th) => th.textContent,
    );
  const cells = () =>
    Array.from(page.document.querySelectorAll("#usage-streamer-list tr td")).map(
      (td) => td.textContent,
    );

  it("列の文言はserverの種別定義から出す(画面が訳語を持たない)", () => {
    const labels = CATEGORY_LABELS.map((entry) => entry.label);
    headers().slice(2).forEach((text) => {
      expect(text === "その他" || labels.includes(text)).toBe(true);
    });
    expect(headers().slice(0, 2)).toEqual(["配信者", "容量"]);
  });

  it("内訳の和が「容量」列に一致する(列に出さない種別も落とさない)", () => {
    const values = cells();
    const gb = (text) => Number(String(text).replace(" GB", ""));
    const total = gb(values[1]);
    const breakdown = values.slice(2).reduce((sum, text) => sum + gb(text), 0);
    expect(breakdown).toBeCloseTo(total, 1);
    expect(total).toBeCloseTo(210, 1);
  });

  it("畳んだ種別は「その他」に残り、内訳をtooltipで名乗る", () => {
    expect(headers()[headers().length - 1]).toBe("その他");
    const last = page.document.querySelector("#usage-streamer-list tr td:last-child span");
    // 上位6種別(source/overlay/up/ts/transient/backup)の外は sidecar と clip。
    expect(last.textContent).toBe("3.0 GB");
    expect(last.title).toContain("sidecar(timing/meta/log) 2.0 GB");
    expect(last.title).toContain("切り出しclip 1.0 GB");
  });

  it("_backupは配信者別でも見える(5種別固定の頃は不可視だった)", () => {
    expect(headers()).toContain("再mp4化の退避(_backup)");
  });

  it("数値列はheaderも右寄せに揃える", () => {
    const ths = Array.from(page.document.querySelectorAll("#usage-streamer-head th"));
    ths.slice(1).forEach((th) => expect(th.classList.contains("num")).toBe(true));
    expect(ths[0].classList.contains("num")).toBe(false);
  });

  // 「作り直せる」と書きながらこの画面からは何もできない状態だった。削除は設定画面が
  // 持つので、そこへ送る導線を種別表に置く。
  it("作り直せる種別には保持policyへの導線を出す", () => {
    const rows = Array.from(page.document.querySelectorAll("#usage-category-list tr"));
    const withButton = rows.filter((tr) => tr.querySelector("button"));
    expect(withButton.length).toBe(3);
    withButton.forEach((tr) => {
      expect(tr.textContent).toContain("作り直せる");
      expect(tr.querySelector("button").textContent).toBe("保持policyで確認する");
    });
  });
});
