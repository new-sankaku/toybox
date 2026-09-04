import { describe, it, expect, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// バックアップの画面は「異常なし」を一目で出すために作った。だから固定すべきは見た目ではなく、
// **異常が異常に見えること**である —— 止まった経路が生きている経路と同じ姿で出る、取得に
// 失敗した回が空の図として出る、のどちらも、この画面が防ごうとしている事故そのものになる。

const NOW = 1788400000;

function lane(key, label, state, extra = {}) {
  return {
    key,
    label,
    source: "元",
    source_note: "",
    state,
    dests: [{ path: "U:\\TicTokDB", exists: true, reachable: true, volume: "U:" }],
    schedule: {
      enabled: state !== "off",
      mark_at: NOW - 600,
      pending: 0,
      pending_oldest_at: null,
      grace_seconds: 1200,
      overdue: false,
      failures: 0,
      retry_in_seconds: 0,
    },
    last_ok: { ts: NOW - 600, message: "完了", severity: "info", detail: {} },
    last_fail: null,
    ...extra,
  };
}

function overview(patch = {}) {
  return {
    now: NOW,
    lanes: [
      lane("db", "DB", "ok"),
      lane("config", "設定", "ok"),
      lane("files", "録画ファイル", "ok"),
      lane("mirror", "ミラー", "ok"),
    ],
    schedule: { tick_seconds: 60, quiet_seconds: 900, min_interval_seconds: 3600,
                holding: 0, last_files_run_at: NOW - 600, steps: {} },
    snapshots: {
      dir: "U:\\TicTokDB",
      items: [{ name: "tictok-scheduled-20260903-023348.db", bytes: 1_600_000_000,
                taken_at: NOW - 3600, created_at: NOW - 3600, reason: "scheduled",
                layer: "daily" }],
      bytes: 1_600_000_000,
      keep: 3,
      daily: [],
      weekly: [],
      expiring: [],
      keep_daily: 14,
      keep_weekly: 8,
    },
    configs: [],
    primary: { configured: true, root: "U:\\TicTokBackup\\_primary_backup",
               last_run: { copied: 11, copied_bytes: 402231964 }, pools: [], root_id: "abc" },
    guard: { ratio: 0.02, rows: 50000, min_rows: 500, tables: ["events", "settings"],
             counts: {}, updated_at: NOW - 3600, frozen: null },
    row_trash: { keep_days: 365, tables: [], counts: [], rows: 0, oldest: null, newest: null },
    journal: { enabled: true, dir: "journal", files: 16, bytes: 407_000_000,
               newest_at: NOW - 60, retention_days: 14 },
    defenses: [
      { key: "authorizer", label: "DROP拒否", covers: "a", misses: "b", state: "ok", value: null },
      { key: "guard", label: "行数監視", covers: "a", misses: "b", state: "ok", value: 2 },
      { key: "trash", label: "削除行の保管", covers: "a", misses: "b", state: "ok", value: 0 },
      { key: "snapshot", label: "別driveへコピー", covers: "a", misses: "b", state: "ok", value: null },
    ],
    volumes: { "U:": { free_bytes: 300_000_000_000, total_bytes: 900_000_000_000, path: "U:\\" } },
    sources: { db: { path: "C:\\TicTok\\tictok.db", volume: "C:" },
               record: { path: "C:\\TicTok\\recordings", volume: "C:" } },
    record_dir: "C:\\TicTok\\recordings",
    final_dirs: ["K:\\80_Tiktok", "J:\\80_Tiktok"],
    relocation: {
      enabled: true,
      items: 0,
      bytes: 0,
      locations: {
        work: { items: 148, bytes: 78_829_933_698, unknown_bytes: 1 },
        final: { items: 411, bytes: 191_497_081_578, unknown_bytes: 76 },
        outside: { items: 0, bytes: 0, unknown_bytes: 0 },
      },
      final_dirs: ["K:\\80_Tiktok", "J:\\80_Tiktok"],
      unavailable_dirs: [],
    },
    mirror_check: {
      at: null, final_dirs: ["K:\\80_Tiktok", "J:\\80_Tiktok"],
      missing_items: 0, missing_bytes: 0, missing_by_dst: {},
      diverged: 0, errors: 0, stale: false, enabled: true,
    },
    ...patch,
  };
}

function loadBackupPage(routes) {
  return loadPage({
    page: "backup",
    url: "http://localhost:8520/backup",
    routes: {
      "/api/disk": { volumes: {}, min_free_bytes: 0, low_volumes: [] },
      "/api/ops/summary": { since: 0, window_hours: 24, counts: {} },
      "/api/backup/health": { now: NOW, state: "", alerts: [] },
      ...routes,
    },
  });
}

async function open(payload) {
  const page = loadBackupPage({ "/api/backup/overview": payload });
  page.fireReady();
  await page.settle();
  return page;
}

// この画面の文字はchipに畳んである。中身の点検はchipの文字列でやる。
function chips(host) {
  return Array.from(host.querySelectorAll(".bk-tag")).map((el) => el.textContent);
}

describe("バックアップの状況", () => {
  let page;
  afterEach(async () => {
    if (page) await page.close();
    page = null;
  });

  it("経路ごとに1つの節を置き、状態を data-state で名乗る", async () => {
    page = await open(overview());
    const lanes = Array.from(page.document.querySelectorAll("#bk-map .bk-lane"));
    expect(lanes.map((el) => el.dataset.state)).toEqual(["ok", "ok", "ok", "ok"]);
    expect(lanes.map((el) => el.querySelector(".bk-lane-label").textContent))
      .toEqual(["DB", "設定", "録画ファイル", "ミラー"]);
  });

  // 木の形は data から数えて決める。列は固定でも、行は退避先の数で変わる ——
  // 保存先を1つ足した日に配置codeを直すことになると、地図はいずれ実態と食い違う。
  it("行は保存先の数だけ取り、経路の節はその範囲へまたがる", async () => {
    const data = overview();
    page = await open(data);
    const dests = page.document.querySelectorAll("#bk-map .bk-dst");
    expect(dests.length).toBe(1 + 1 + 1 + 1);
    const config = page.document.querySelector('#bk-map .bk-lane[data-lane="config"]');
    expect(config.style.gridRow).toBe("2 / 3");
    expect(page.document.querySelector("#bk-map").style.getPropertyValue("--bk-rows"))
      .toBe("4");
  });

  it("保存先が3つある経路は、その3行ぶんへ節をまたがせる", async () => {
    const data = overview();
    data.lanes[1] = lane("config", "設定", "ok", {
      dests: [
        { path: "C:\\rec\\_config", exists: true, reachable: true, volume: "C:", parent: "C:\\rec" },
        { path: "K:\\80_Tiktok\\_config", exists: true, reachable: true, volume: "K:", parent: "K:\\80_Tiktok" },
        { path: "J:\\80_Tiktok\\_config", exists: true, reachable: true, volume: "J:", parent: "J:\\80_Tiktok" },
      ],
    });
    page = await open(data);
    expect(page.document.querySelectorAll('#bk-map .bk-dst[data-lane="config"]').length).toBe(3);
    expect(page.document.querySelector('#bk-map .bk-lane[data-lane="config"]').style.gridRow)
      .toBe("2 / 5");
    // 元は自分から伸びる経路の全行をまたぐ(tictok.db は DB と 設定 の2本)。
    expect(page.document.querySelectorAll("#bk-map .bk-src")[0].style.gridRow).toBe("1 / 5");
  });

  it("盾は点いている経路の数を出す", async () => {
    page = await open(overview());
    expect(page.document.querySelector(".bk-shield-num").textContent).toBe("4/4");
    expect(Array.from(page.document.querySelectorAll(".bk-band"))
      .map((el) => el.getAttribute("data-state"))).toEqual(["ok", "ok", "ok", "ok"]);
  });

  // 止めてある経路は「守れていない」ではない。分母に数えると、設定どおりの状態が
  // 欠落として並び、本当に落ちている経路が同じ見た目に埋もれる。
  it("止めてある経路は盾の分母から外す", async () => {
    const data = overview();
    data.lanes[3] = lane("mirror", "ミラー", "off");
    page = await open(data);
    expect(page.document.querySelector(".bk-shield-num").textContent).toBe("3/3");
  });

  it("失敗した経路は次の再試行までの時間を出す", async () => {
    const data = overview();
    data.lanes[0] = lane("db", "DB", "failing", {
      schedule: { enabled: true, mark_at: NOW - 9000, pending: 2,
                  pending_oldest_at: NOW - 9000, grace_seconds: 1200, overdue: true,
                  failures: 3, retry_in_seconds: 240 },
      last_fail: { ts: NOW - 120, message: "保存先が見つかりません", severity: "error", detail: {} },
    });
    page = await open(data);
    const row = page.document.querySelector('#bk-map .bk-lane[data-lane="db"]');
    expect(row.dataset.state).toBe("failing");
    const tag = row.querySelector(".bk-tag-warn");
    expect(tag.textContent).toBe("再試行 4分後");
    expect(tag.title).toBe("保存先が見つかりません");
    expect(page.document.querySelector(".bk-shield-num").textContent).toBe("3/4");
  });

  // 「まだ写していない録画がある」は正常な途中経過。警告の色で出すと、60秒周期の正常な
  // 待ちが毎回警告として点滅する。
  it("残りのある経路は進行中の印にする", async () => {
    const data = overview();
    data.lanes[2] = lane("files", "録画ファイル", "working", {
      schedule: { enabled: true, mark_at: NOW - 300, pending: 5,
                  pending_oldest_at: NOW - 300, grace_seconds: 5400, overdue: false,
                  failures: 0, retry_in_seconds: 0 },
    });
    page = await open(data);
    const row = page.document.querySelector('#bk-map .bk-lane[data-lane="files"]');
    expect(row.dataset.state).toBe("working");
    expect(row.querySelector(".bk-tag-run").textContent).toBe("未処理 5");
    expect(row.querySelector(".bk-tag-warn")).toBe(null);
  });

  it("届かない保存先は破線にして経路を切る", async () => {
    const data = overview();
    data.lanes[1] = lane("config", "設定", "unreachable", {
      dests: [{ path: "K:\\80_Tiktok\\_config", exists: false, reachable: false, volume: "K:" }],
    });
    page = await open(data);
    expect(page.document.querySelector('#bk-map .bk-lane[data-lane="config"]').dataset.state)
      .toBe("unreachable");
    const dest = page.document.querySelector('#bk-map .bk-dst[data-lane="config"]');
    expect(dest.classList.contains("bk-dst-gone")).toBe(true);
    expect(dest.dataset.state).toBe("unreachable");
  });

  // 元と同じdriveに在る写しは、そのdriveが壊れれば一緒に消える。設定した本人でも
  // volumeを並べて見なければ気付けないので、画面が名乗る。
  it("保存先が元と同じdriveなら印を付ける", async () => {
    const data = overview();
    data.lanes[0] = lane("db", "DB", "ok", {
      dests: [{ path: "C:\\TicTok\\backups", exists: true, reachable: true, volume: "C:" }],
    });
    page = await open(data);
    expect(page.document.querySelector('#bk-map .bk-dst[data-lane="db"] .bk-vol-same'))
      .not.toBe(null);
  });

  it("設定の保存先が録画の保存先と同じdriveでも印は付けない", async () => {
    const data = overview();
    data.lanes[1] = lane("config", "設定", "ok", {
      dests: [{ path: "C:\\TicTok\\recordings\\_config", exists: true, reachable: true, volume: "C:" }],
    });
    page = await open(data);
    expect(page.document.querySelector('#bk-map .bk-dst[data-lane="config"] .bk-vol-same'))
      .toBe(null);
  });

  it("世代の升目は暦で並べ、世代のある日だけを点ける", async () => {
    const data = overview();
    // 升目は「今日」から遡って作る。固定日を差し込むと、日付が変わった翌日に落ちる。
    const today = new Date().toLocaleDateString("sv-SE");
    data.snapshots.daily = [{ key: today, name: "tictok-scheduled-20260903-023348.db" }];
    page = await open(data);
    const rows = page.document.querySelectorAll("#bk-gen .bk-gen-row");
    const cells = rows[0].querySelectorAll(".bk-gen-cell");
    expect(cells.length).toBe(14);
    expect(cells[13].classList.contains("is-on")).toBe(true);
    expect(cells[13].classList.contains("is-now")).toBe(true);
    expect(cells[0].classList.contains("is-on")).toBe(false);
    expect(rows[0].querySelector(".bk-gen-tot").textContent).toBe("1/14 日");
  });

  it("行数監視が凍結中なら備えを警告にして解除の口を出す", async () => {
    const data = overview();
    data.guard.frozen = { since: NOW - 3600, reason: "急減",
                          drops: [{ table: "bookmarks", before: 192, after: 133 }] };
    data.defenses[1].state = "failing";
    page = await open(data);
    const guard = page.document.querySelectorAll("#bk-guards .bk-guard")[1];
    expect(guard.dataset.state).toBe("failing");
    const button = page.document.getElementById("bk-unfreeze");
    expect(button.hidden).toBe(false);
    expect(button.title).toBe("bookmarks 192→133");
  });

  it("凍結していないときは解除のbuttonを出さない", async () => {
    page = await open(overview());
    expect(page.document.getElementById("bk-unfreeze").hidden).toBe(true);
  });

  // 取得できなかったことを「異常なし」として描かない。バックアップの画面でそれをやると、
  // 止まっていることに誰も気付かないという、この機能が防ごうとしている形になる。
  it("取得に失敗したら図を消して失敗として出す", async () => {
    page = loadBackupPage({});
    page.fireReady();
    await page.settle();
    const empty = page.document.getElementById("bk-empty");
    expect(empty.classList.contains("list-failed")).toBe(true);
    expect(empty.classList.contains("hidden")).toBe(false);
    expect(page.document.querySelectorAll("#bk-map .bk-lane").length).toBe(0);
    expect(page.document.querySelector(".bk-shield-num")).toBe(null);
  });
});

// ---- 警報 ----
// 色と動きは見ている人にしか効かない。開いた瞬間に「何か変だ」と分かる必要があるので、
// 最も重い状態の語を大書きし、その横に**実際のpathと実際のerror文**をchipで並べる。
// ここで固定するのは、その中身が「読み方の説明」ではなく事実であること。
describe("バックアップの警報", () => {
  let page;
  afterEach(async () => {
    if (page) await page.close();
    page = null;
  });

  it("異常が無ければ出さない", async () => {
    page = await open(overview());
    expect(page.document.getElementById("bk-alarm").hidden).toBe(true);
  });

  it("失敗の内容・再試行・未処理・設定keyを並べる", async () => {
    const data = overview();
    data.lanes[0] = lane("db", "DB", "failing", {
      reason: { key: "failed", settings: ["db_backup_dir"] },
      schedule: { enabled: true, mark_at: NOW - 40000, pending: 6,
                  pending_oldest_at: NOW - 40000, grace_seconds: 1800, overdue: true,
                  failures: 4, retry_in_seconds: 900 },
      last_fail: { kind: "maintenance.backup_failed", ts: NOW - 300, severity: "error",
                   label: "DBバックアップに失敗", message: "保存先に書き込めません: [WinError 3]",
                   detail: {} },
    });
    page = await open(data);
    const alarm = page.document.getElementById("bk-alarm");
    expect(alarm.hidden).toBe(false);
    expect(alarm.dataset.level).toBe("error");
    expect(alarm.querySelector(".bk-alarm-big").textContent).toBe("失敗");
    const texts = chips(alarm.querySelector(".bk-alarm-item"));
    expect(texts).toContain("保存先に書き込めません: [WinError 3]");
    expect(texts).toContain("再試行 4回目 · 15分後");
    expect(texts).toContain("未処理 6本");
    expect(texts).toContain("db_backup_dir");
  });

  // 「届かない」は保存先ごとに違う。3つのうち1つだけ外れている状況で全部を並べると、
  // どれが問題なのかを人が突き合わせることになる。
  it("届かない保存先は、そのpathだけを名指しする", async () => {
    const data = overview();
    data.lanes[1] = lane("config", "設定", "unreachable", {
      reason: { key: "unreachable", settings: [], paths: ["K:\\80_Tiktok\\_config"] },
      dests: [
        { path: "C:\\rec\\_config", exists: true, reachable: true, volume: "C:",
          parent: "C:\\rec" },
        { path: "K:\\80_Tiktok\\_config", exists: false, reachable: false, volume: "K:",
          parent: "K:\\80_Tiktok" },
      ],
    });
    page = await open(data);
    const item = page.document.querySelector(".bk-alarm-item");
    const gone = Array.from(item.querySelectorAll(".bk-tag-warn.bk-tag-path"));
    expect(gone.length).toBe(1);
    expect(gone[0].textContent).toBe("K:\\80_Tiktok\\_config");
    expect(gone[0].title).toBe("親 K:\\80_Tiktok");
  });

  // 保存先が決まっていないのは「止めてある」より重い —— 写しがどこにも無いという意味。
  it("保存先が未設定なら重さを上げて設定keyを名指しする", async () => {
    const data = overview();
    data.lanes[2] = lane("files", "録画ファイル", "off", {
      reason: { key: "no_path", settings: ["record_backup_dir"] },
      dests: [],
      last_ok: null,
    });
    page = await open(data);
    const alarm = page.document.getElementById("bk-alarm");
    expect(alarm.querySelector(".bk-alarm-big").textContent).toBe("保存先なし");
    expect(alarm.dataset.level).toBe("warn");
    expect(chips(alarm.querySelector(".bk-alarm-item"))).toContain("record_backup_dir");
  });

  it("設定で止めてあるだけなら警報の重さを上げない", async () => {
    const data = overview();
    data.lanes[3] = lane("mirror", "ミラー", "off", {
      reason: { key: "single", settings: ["record_dir_final2"] },
    });
    page = await open(data);
    const alarm = page.document.getElementById("bk-alarm");
    expect(alarm.dataset.level).toBe("off");
    expect(alarm.querySelector(".bk-alarm-big").textContent).toBe("保存先が1つ");
  });

  // 走ったが一部が写せなかった回は、kindだけ見ると成功として通る。写せなかったfileを
  // 名指ししないと、その数件を誰も追わない。
  it("一部が写せていない回は写せないfileを名指しする", async () => {
    const data = overview();
    data.lanes[2] = lane("files", "録画ファイル", "degraded", {
      reason: { key: "partial", settings: [] },
      last_ok: { kind: "record_backup.job_completed", ts: NOW - 120, severity: "warning",
                 label: "録画ファイルのバックアップ",
                 message: "写した 8 件 / 失敗 2 件",
                 detail: {} },
    });
    data.primary.last_run.failures = [
      { path: "pomiiiip/ts/00600/seg00012.ts", reason: "[WinError 112] 空き容量がありません" },
      { path: "pomiiiip/ts/00600/seg00013.ts", reason: "[WinError 112] 空き容量がありません" },
    ];
    page = await open(data);
    const item = page.document.querySelector(".bk-alarm-item");
    expect(Array.from(item.querySelectorAll(".bk-tag-warn.bk-tag-path"))
      .map((el) => el.textContent))
      .toEqual(["pomiiiip/ts/00600/seg00012.ts", "pomiiiip/ts/00600/seg00013.ts"]);
    expect(page.document.querySelector(".bk-alarm-big").textContent).toBe("一部失敗");
  });

  // 大書きも1つしか出せない。軽い方を採ると重い方が隠れる。
  it("複数が同時に壊れていても、大書きするのは最も重い1語だけ", async () => {
    const data = overview();
    data.lanes[0] = lane("db", "DB", "late",
                         { reason: { key: "overdue", settings: [] } });
    data.lanes[1] = lane("config", "設定", "failing", {
      reason: { key: "failed", settings: [] },
      last_fail: { kind: "backup.settings_export_failed", ts: NOW - 60, severity: "error",
                   label: "設定値のバックアップに失敗", message: "書けない保存先があります",
                   detail: {} },
    });
    page = await open(data);
    const alarm = page.document.getElementById("bk-alarm");
    expect(alarm.querySelectorAll(".bk-alarm-big").length).toBe(1);
    expect(alarm.querySelector(".bk-alarm-big").textContent).toBe("失敗");
    expect(alarm.querySelectorAll(".bk-alarm-item").length).toBe(2);
    expect(alarm.querySelector(".bk-alarm-count").textContent).toBe("2 / 4");
  });

  // 取得できなかった回に前の警報が残ると、直っていないのに直ったように・壊れていないのに
  // 壊れているように見える。どちらも実際の状態とは無関係な表示になる。
  it("取得に失敗したら警報を消し、失敗として出す", async () => {
    const data = overview();
    data.lanes[0] = lane("db", "DB", "failing",
                         { reason: { key: "failed", settings: [] } });
    let down = false;
    page = loadBackupPage({
      "/api/backup/overview": () => (down
        // 失敗はNodeのResponseで作る。jsdom側のResponseは接続失敗に化ける。
        ? new Response(JSON.stringify({ detail: "落ちました" }),
                       { status: 500, headers: { "Content-Type": "application/json" } })
        : data),
    });
    page.fireReady();
    await page.settle();
    expect(page.document.getElementById("bk-alarm").hidden).toBe(false);

    down = true;
    await page.win.loadBackup();
    expect(page.document.getElementById("bk-alarm").hidden).toBe(true);
    expect(page.document.getElementById("bk-empty").classList.contains("list-failed"))
      .toBe(true);
  });

});

// ---- 写しの中身 ----
// 「流れている」は「写しに在る」ではない。図が緑でも、どこまで何が保存先に在るのかを
// 答えない限り、この画面は「分からない」のまま残る。ここで固定するのは**数え方**である ——
// 直近の回で増えた分を総量として出す、確かめていない物を揃っていると書く、のどちらも
// 「写したつもり」を作る。

describe("写しの中身", () => {
  let page;
  afterEach(async () => {
    if (page) await page.close();
    page = null;
  });

  // ミラーの保存先は最終保存先そのもの。既定の1つでは、系統ごとの欠けを試せない。
  function mirrorLane(extra = {}) {
    return lane("mirror", "ミラー", "ok", {
      dests: [
        { path: "K:\\80_Tiktok", exists: true, reachable: true, volume: "K:" },
        { path: "J:\\80_Tiktok", exists: true, reachable: true, volume: "J:" },
      ],
      ...extra,
    });
  }

  it("録画ファイルは直近で増えた分ではなく、保存先に在る量を出す", async () => {
    const data = overview();
    // 写した11件は総量を1つも語らない。既に同じだった分を足して初めて
    // 「保存先に何件在るか」になる。
    data.primary.last_run = { copied: 11, copied_bytes: 400, skipped: 2030,
                              skipped_bytes: 48_000_000_000, failed: 0, seconds: 3.0,
                              started_at: NOW - 600, pools: [] };
    page = await open(data);
    const dest = page.document.querySelector('#bk-map .bk-dst[data-lane="files"]');
    expect(dest.querySelector(".bk-node-meta").textContent).toContain("2,041件");
    // 直近の回の内訳は帯で出す。区画は「既存/コピー」の2つで、0の失敗は置かない。
    const laneNode = page.document.querySelector('#bk-map .bk-lane[data-lane="files"]');
    expect(Array.from(laneNode.querySelectorAll(".bk-seg")).map((el) => el.className))
      .toEqual(["bk-seg bk-seg-keep", "bk-seg bk-seg-new"]);
    expect(chips(laneNode)).toContain("コピー 11");
  });

  it("ミラーは空き容量ではなく、どちらの系統に何が欠けているかを出す", async () => {
    const data = overview();
    data.lanes[3] = mirrorLane();
    data.mirror_check = {
      ...data.mirror_check, at: NOW - 120, missing_items: 12293,
      missing_bytes: 582_536_254_256,
      missing_by_dst: { "J:\\80_Tiktok": { count: 12293, bytes: 582_536_254_256 } },
    };
    page = await open(data);
    const dests = Array.from(
      page.document.querySelectorAll('#bk-map .bk-dst[data-lane="mirror"]'));
    expect(dests[0].querySelector(".bk-node-meta").textContent).toContain("411本");
    expect(dests[1].querySelector(".bk-node-meta").textContent).toContain("欠け 12,293件");
    const sides = Array.from(
      page.document.querySelectorAll("#bk-mirror .bk-side"));
    expect(sides.map((el) => el.dataset.level)).toEqual(["ok", "warn"]);
    expect(sides[1].querySelector(".bk-side-val").textContent).toContain("12,293件");
    expect(sides[0].querySelector(".bk-side-val").textContent).toBe("0");
  });

  // 確かめていない状態と、確かめて揃っていた状態を同じ言葉で出してはならない。
  it("一度も照合していないミラーを「一致」と書かない", async () => {
    const data = overview();
    data.lanes[3] = mirrorLane();
    page = await open(data);
    const dests = Array.from(
      page.document.querySelectorAll('#bk-map .bk-dst[data-lane="mirror"]'));
    expect(dests[0].querySelector(".bk-node-meta").textContent).toBe("未照合");
    const mirror = page.document.getElementById("bk-mirror");
    expect(mirror.querySelector(".bk-mirror-word").textContent).toBe("未照合");
    expect(mirror.textContent).not.toContain("一致");
    expect(Array.from(mirror.querySelectorAll(".bk-side"))
      .map((el) => el.dataset.level)).toEqual(["unknown", "unknown"]);
  });

  it("揃っていないと分かっているミラーは、警報に系統ごとの欠けを出す", async () => {
    const data = overview();
    data.mirror_check = {
      ...data.mirror_check, at: NOW - 120, missing_items: 12293,
      missing_bytes: 582_536_254_256,
      missing_by_dst: { "J:\\80_Tiktok": { count: 12293, bytes: 582_536_254_256 } },
    };
    data.lanes[3] = mirrorLane({ state: "degraded",
                                 reason: { key: "unsynced", settings: [] } });
    page = await open(data);
    const alarm = page.document.getElementById("bk-alarm");
    expect(alarm.hidden).toBe(false);
    expect(alarm.querySelector(".bk-alarm-big").textContent).toBe("差分あり");
    expect(alarm.textContent).toContain("80_Tiktok");
    expect(alarm.textContent).toContain("12,293件");
  });

  it("世代は升目だけでなく、戻せるfileを時刻と大きさで並べる", async () => {
    page = await open(overview());
    const rows = page.document.querySelectorAll("#bk-genlist .bk-genitem");
    expect(rows.length).toBe(1);
    expect(rows[0].querySelector(".bk-genitem-size").textContent).toBe("1.5 GB");
    expect(rows[0].querySelector(".bk-genitem-layer").textContent).toBe("日次");
  });

  it("取得に失敗したら写しの数字も消す", async () => {
    const data = overview();
    let down = false;
    page = loadBackupPage({
      "/api/backup/overview": () => (down
        ? new Response(JSON.stringify({ detail: "落ちました" }),
                       { status: 500, headers: { "Content-Type": "application/json" } })
        : data),
    });
    page.fireReady();
    await page.settle();
    expect(page.document.querySelectorAll("#bk-map .bk-dst").length).toBe(4);

    down = true;
    await page.win.loadBackup();
    // 前回の数字が残ると、取得に失敗した画面が「これだけ写しに在る」と名乗り続ける。
    expect(page.document.querySelectorAll("#bk-map .bk-dst").length).toBe(0);
    expect(page.document.getElementById("bk-mirror").children.length).toBe(0);
    expect(page.document.getElementById("bk-genlist").children.length).toBe(0);
    expect(page.document.getElementById("bk-guards").children.length).toBe(0);
  });
});
