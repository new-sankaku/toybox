"use strict";

// 動画容量画面: 動画がどこに何GBあるか(と最終保存先への移動)、driveの空きと満杯まで、
// 増え方の内訳、録画folderの内訳。
// もとは運用log画面に同居していたが、運用logは「起きたこと」を遡る画面で、こちらは
// 「置き場所をどうするか」を決める画面なので主役が違う。
// 語は設定画面に合わせる(一時保存先 / 最終保存先)。同じものを「作業先」「退避先」と
// 呼び分けると、設定画面と突き合わせられない。DBのbackupだけは「DB backup」と書いて
// 動画の移動と区別する(以前はどちらも「退避」で、同じ画面に2つの意味で並んでいた)。

// ---- 動画の保存先 ----
// 「対象を確認」で一覧(dry-run)を出し、確認してから「最終保存先へ移動」。押した順序を
// 保つため、一覧を見るまで実行buttonは出さない。
let relocationPlan = null;

function placeTotalText(entry) {
  if (!entry) return "-";
  const parts = [`${fmtNum(entry.items)} 本`, `${fmtGb(entry.bytes)}GB`];
  // bytes未記録の行を黙って0GBとして混ぜない。合計が実態より小さく見える理由を書く。
  if (entry.unknown_bytes) parts.push(`容量不明 ${fmtNum(entry.unknown_bytes)} 本`);
  return parts.join(" / ");
}

function renderPlacement(placement) {
  const locations = (placement && placement.locations) || {};
  const enabled = Boolean(placement && placement.enabled);
  document.getElementById("cap-work-path").textContent = (placement && placement.record_dir) || "-";
  document.getElementById("cap-work-total").textContent = placeTotalText(locations.work);
  document.getElementById("cap-final-path").textContent =
    enabled ? placement.final_dir : "未設定";
  document.getElementById("cap-final-total").textContent =
    enabled ? placeTotalText(locations.final) : "—";

  const move = document.getElementById("cap-move");
  const moveText = document.getElementById("cap-move-text");
  const note = document.getElementById("cap-place-note");
  const planBtn = document.getElementById("reloc-plan");

  if (!enabled) {
    // 移す先が無い状態。buttonごと消すと「機能が無い」に見えるので、出したまま理由を書く。
    move.classList.add("cap-move-off");
    moveText.textContent = "最終保存先が未設定のため、録画は一時保存先に置かれたままになります。";
    planBtn.disabled = true;
    document.getElementById("reloc-apply").classList.add("hidden");
    note.replaceChildren(
      document.createTextNode("設定画面の「録画の最終保存先(HDD想定)」を入れると、完了した録画をそこへ移せます。"),
    );
    const link = document.createElement("a");
    link.href = "/settings";
    link.textContent = "設定を開く";
    note.append(" ", link);
    return;
  }

  move.classList.remove("cap-move-off");
  planBtn.disabled = false;
  const backlog = placement.items || 0;
  moveText.textContent = backlog
    ? `まだ移していない完了録画: ${fmtNum(backlog)} 本 / ${fmtGb(placement.bytes)}GB`
    : "まだ移していない完了録画はありません。";

  const notes = [];
  if (locations.outside && locations.outside.items) {
    notes.push(`どちらの保存先にも無い記録 ${fmtNum(locations.outside.items)} 本`
      + "（外部で動かされたか、保存先の設定を変えた録画です）");
  }
  if (placement.skipped_missing) {
    notes.push(`一時保存先にpathだけ残っていて実体が無い記録 ${fmtNum(placement.skipped_missing)} 本`
      + "（移動の対象外です）");
  }
  if (placement.skipped_existing_at_destination) {
    notes.push(`最終保存先に同名のfileが既にある録画 ${fmtNum(placement.skipped_existing_at_destination)} 本`
      + "（上書きしないため移動の対象外です）");
  }
  note.textContent = notes.join(" / ");
}

function renderRelocationPlan(plan) {
  relocationPlan = plan;
  document.getElementById("reloc-detail").classList.remove("hidden");
  const tbody = document.getElementById("reloc-rows");
  tbody.replaceChildren();
  (plan.by_streamer || []).forEach((s) => {
    const tr = document.createElement("tr");
    [`@${s.unique_id}`, `${fmtNum(s.items)} 本`, `${fmtGb(s.bytes)}GB`].forEach((value, i) => {
      const td = document.createElement("td");
      if (i >= 1) td.className = "num";
      td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  setListState(document.getElementById("reloc-empty"),
    tbody.childElementCount === 0 ? "empty" : "ok");

  document.getElementById("reloc-summary").textContent =
    `移動する録画 ${fmtNum(plan.total_items)} 本 / ${fmtGb(plan.total_bytes)}GB`
    + `（移動先 ${plan.final_dir}）`;
  document.getElementById("reloc-apply").classList.toggle("hidden", plan.total_items === 0);
}

document.getElementById("reloc-plan").addEventListener("click", async () => {
  const status = document.getElementById("reloc-status");
  status.textContent = "対象を確認中…";
  try {
    renderRelocationPlan(await apiSend("GET", "/api/storage/relocate"));
    status.textContent = "";
  } catch (err) {
    status.textContent = err.message;
  }
});

document.getElementById("reloc-apply").addEventListener("click", async () => {
  if (!relocationPlan || !relocationPlan.total_items) return;
  const ok = await confirmDialog(
    `${fmtNum(relocationPlan.total_items)} 本（${fmtGb(relocationPlan.total_bytes)}GB）を`
    + `\n${relocationPlan.final_dir}\nへ移します。録画中のものは含みません。`
    + `\n\n容量が大きいため数分かかります。`,
    { title: "最終保存先へ移動", confirmLabel: "移動する", danger: false },
  );
  if (!ok) return;
  const btn = document.getElementById("reloc-apply");
  const status = document.getElementById("reloc-status");
  btn.disabled = true;
  status.textContent = "移動中… (進捗はJob画面で確認できます)";
  try {
    const result = await apiSend("POST", "/api/storage/relocate", { confirm: true });
    const r = result.result || {};
    const failed = (r.failures || []).length;
    status.textContent =
      `${fmtNum(r.moved || 0)} 本（${fmtGb(r.moved_bytes || 0)}GB）を移動しました`
      + (failed ? `。${fmtNum(failed)} 本は失敗し一時保存先に残っています。` : "。");
    renderRelocationPlan(result.plan);
    loadCapacity();
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

// ---- driveの空きと満杯まで ----
// 予測は必ず幅で出す。「あと7日」と点で書くと、観測が3日しかない段階でも断定に見える。
// server側(core/capacity)がstatusで「出せない」を返してくるので、画面はそれを言葉にする。
const CAPACITY_STATUS_TEXT = {
  insufficient_data: "記録が足りません",
  not_shrinking: "減っていません",
  inconclusive: "減少と言い切れません",
  beyond_horizon: "観測期間に対して先すぎます",
};

function fmtDays(days) {
  if (days >= 400) return "1年以上";
  if (days >= 2) return `${Math.round(days)} 日`;
  return `${days.toFixed(1)} 日`;
}

// 満杯までの表示。数値を出せるのは status=ok のときだけで、それ以外は理由を書く。
function forecastCell(f) {
  if (f.status === "ok") {
    return `${fmtDays(f.days_low)} 〜 ${fmtDays(f.days_high)}`;
  }
  if (f.status === "beyond_horizon") {
    return `少なくとも ${fmtDays(f.beyond_days)} 先`;
  }
  return CAPACITY_STATUS_TEXT[f.status] || "—";
}

// 予測の確からしさ(観測日数・件数・あてはまり)は列にすると読み手に解釈を強いるので、
// 行のtooltipへ落とす。列に出していた頃は「あてはまり 0.94」だけが並んで意味が伝わらなかった。
function forecastTitle(f) {
  const parts = [];
  if (f.observed_days) {
    parts.push(`観測 ${f.observed_days.toFixed(1)} 日 / 記録 ${fmtNum(f.n)} 件`);
  } else if (f.n !== undefined) {
    parts.push(`記録 ${fmtNum(f.n || 0)} 件`);
  }
  if (f.r2 !== undefined) {
    parts.push(`直線へのあてはまり ${f.r2.toFixed(2)}（1.00に近いほど一定のペースで減っています）`);
  }
  if (f.status === "insufficient_data") {
    parts.push(`予測には記録が ${fmtNum(f.min_samples || 3)} 件必要です`);
  }
  return parts.join("\n");
}

function renderCapacity(data) {
  const now = data.now || {};
  const volumes = (now.disk || {}).volumes || {};
  const forecasts = data.forecasts || {};

  const tbody = document.getElementById("cap-rows");
  tbody.replaceChildren();
  Object.keys(volumes).sort().forEach((name) => {
    const v = volumes[name] || {};
    const f = forecasts[name] || { status: "insufficient_data", n: 0 };
    const perDay = f.slope_bytes_per_day;
    const cells = [
      name,
      `${fmtGb(v.free_bytes)}GB`,
      `${fmtGb(v.total_bytes)}GB`,
      // 減少を負で出す。絶対値だけ出すと増えているのか減っているのか読めない。
      perDay === undefined ? "—" : `${perDay > 0 ? "+" : ""}${fmtGb(perDay)}GB`,
      forecastCell(f),
    ];
    const tr = document.createElement("tr");
    cells.forEach((value, i) => {
      const td = document.createElement("td");
      if (i >= 1) td.className = "num";
      td.textContent = value;
      tr.appendChild(td);
    });
    const title = forecastTitle(f);
    if (title) tr.title = title;
    // 閾値割れは既にops_eventとして残るので、ここでは色を付けるだけにする。
    if (f.status === "ok" && f.days_low < 14) tr.classList.add("rank-top");
    tbody.appendChild(tr);
  });
  setListState(document.getElementById("cap-empty"),
    tbody.childElementCount === 0 ? "empty" : "ok");

  const samples = data.samples || [];
  document.getElementById("cap-summary").textContent = samples.length
    ? `記録 ${fmtNum(samples.length)} 件（最新 ${fmtDateTime(data.sampled_at)}）`
    : "記録はまだありません（最初の記録が入るまで予測は出ません）";

  renderPlacement(data.placement);

  const daily = (data.recording_daily || []).slice(-14).reverse();
  const dailyBody = document.getElementById("cap-daily");
  dailyBody.replaceChildren();
  daily.forEach((d) => {
    const tr = document.createElement("tr");
    [d.day, `${fmtNum(d.recordings)} 本`, `${fmtGb(d.bytes)}GB`].forEach((value, i) => {
      const td = document.createElement("td");
      if (i >= 1) td.className = "num";
      td.textContent = value;
      tr.appendChild(td);
    });
    dailyBody.appendChild(tr);
  });
  setListState(document.getElementById("cap-daily-empty"),
    dailyBody.childElementCount === 0 ? "empty" : "ok");

  const c = data.completion || {};
  // 母数0はnullで返る(0%ではない)。「対象なし」と「1件も終わっていない」を混同しない。
  const rate = (value) => (value === null || value === undefined ? "—" : `${value.toFixed(1)}%`);
  renderChips("cap-completion", [
    ["完了した録画", `${fmtNum(c.completed_recordings || 0)} 本`],
    ["転写済み", `${rate(c.transcribed_rate)} (${fmtNum(c.transcribed || 0)})`],
    ["焼き込み済み", `${rate(c.overlay_rate)} (${fmtNum(c.overlay_done || 0)})`],
  ]);

  const db = now.db_files || {};
  const backups = now.backups || {};
  const rows = now.rows || {};
  renderChips("cap-dbusage", [
    ["Database", `${fmtGb(db.db)}GB`],
    ["WAL", `${fmtGb(db.wal)}GB`],
    ["DB backup", `${fmtGb(backups.bytes)}GB (${fmtNum(backups.files || 0)}件)`],
  ]);
  document.getElementById("cap-dbrows").textContent = [
    `event ${fmtNum(rows.events || 0)}行`,
    `検索index ${fmtNum(rows.search_hits || 0)}行`,
    `User ${fmtNum(rows.users || 0)}人`,
  ].join(" / ");
}

function renderChips(containerId, entries) {
  const bar = document.getElementById(containerId);
  bar.replaceChildren();
  entries.forEach(([label, value]) => {
    const chip = document.createElement("div");
    chip.className = "a-chip";
    const l = document.createElement("span");
    l.className = "l";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "v";
    v.textContent = value;
    chip.append(l, v);
    bar.appendChild(chip);
  });
}

async function loadCapacity() {
  try {
    renderCapacity(await apiSend("GET", "/api/capacity"));
  } catch (err) {
    // 取得失敗を「記録なし」として描くと、予測が出ない理由を取り違える。
    setListState(document.getElementById("cap-empty"), "failed", err);
    setListState(document.getElementById("cap-daily-empty"), "failed", err);
  }
}

document.getElementById("cap-sample").addEventListener("click", async () => {
  const btn = document.getElementById("cap-sample");
  const status = document.getElementById("cap-status");
  btn.disabled = true;
  status.textContent = "記録中…";
  try {
    const result = await apiSend("POST", "/api/capacity/sample");
    renderCapacity(result.report);
    status.textContent = `記録しました（${fmtDateTime(result.sampled_at)}）`;
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

// ---- 録画folderの内訳 ----
// 判定と文言はserverが持つ(種別labelも再生成可否もAPI応答のまま描画する)。
const usageStatusEl = document.getElementById("usage-status");
const usageSummaryEl = document.getElementById("usage-summary");
const usageScanBtn = document.getElementById("usage-scan");

function renderUsage(payload) {
  const scan = payload && payload.scan;
  const hasScan = Boolean(scan && scan.usage);
  document.getElementById("usage-category-empty").classList.toggle("hidden", hasScan);
  document.getElementById("usage-streamer-empty").classList.toggle("hidden", hasScan);
  if (!hasScan) {
    document.getElementById("usage-category-list").innerHTML = "";
    document.getElementById("usage-streamer-list").innerHTML = "";
    usageSummaryEl.textContent = `対象folder: ${(payload.roots || []).join(" / ") || "-"}`;
    return;
  }
  const usage = scan.usage;
  const regenerable = new Set(usage.regenerable_categories || []);
  const errors = (usage.errors || []).length;
  usageSummaryEl.textContent =
    `最終scan: ${fmtDateTime(scan.scanned_at)}（${Math.round(scan.duration_ms / 1000)}秒）`
    + ` / 合計 ${fmtBytesGb(usage.total_bytes)}・${fmtNum(usage.total_files)} file`
    + ` / 対象folder: ${(usage.roots || []).join(" / ")}`
    + (errors ? ` / 読めなかった場所 ${fmtNum(errors)} 件（合計に含みません）` : "");

  const rows = (usage.category_labels || [])
    .map((entry) => ({ ...entry, ...(usage.categories[entry.key] || { bytes: 0, files: 0 }) }))
    .filter((row) => row.files > 0);
  renderTableRows(
    "usage-category-list",
    null,
    rows,
    (row) => [
      row.label,
      fmtBytesGb(row.bytes),
      fmtNum(row.files),
      regenerable.has(row.key) ? "作り直せる" : "作り直せない",
    ],
    [1, 2],
  );

  renderTableRows(
    "usage-streamer-list",
    null,
    usage.streamers || [],
    (row) => {
      const cat = (key) => fmtBytesGb((row.categories[key] || {}).bytes || 0);
      return [
        row.label,
        fmtBytesGb(row.bytes),
        cat("source"),
        cat("overlay"),
        cat("up"),
        cat("ts"),
        cat("transient"),
      ];
    },
    [1, 2, 3, 4, 5, 6],
  );
}

async function loadUsage() {
  try {
    const res = await fetch("/api/storage/usage");
    if (!res.ok) throw new Error(String(res.status));
    renderUsage(await res.json());
  } catch (err) {
    usageStatusEl.textContent = "録画folderの内訳を取得できませんでした。";
  }
}

usageScanBtn.addEventListener("click", async () => {
  usageScanBtn.disabled = true;
  usageStatusEl.textContent = "走査中…（数TB規模では数分かかります）";
  try {
    renderUsage(await apiSend("POST", "/api/storage/scan"));
    usageStatusEl.textContent = "走査しました。";
  } catch (err) {
    usageStatusEl.textContent = err.message;
  } finally {
    usageScanBtn.disabled = false;
  }
});

loadCapacity();
loadUsage();
// jobの進捗はJob画面が持つ。この画面はWSを接続表示とtopbarのjob badgeのためだけに使う。
connectWS(() => {});
