"use strict";

// 動画容量画面: 動画がどこに何GBあるか(と最終保存先への移動)、driveの空きと満杯まで、
// 増え方の内訳、録画folderの内訳。
// もとは運用log画面に同居していたが、運用logは「起きたこと」を遡る画面で、こちらは
// 「置き場所をどうするか」を決める画面なので主役が違う。
// 語は設定画面に合わせる(一時保存先 / 最終保存先)。同じものを「作業先」「退避先」と
// 呼び分けると、設定画面と突き合わせられない。DBのbackupだけは「DB backup」と書いて
// 動画の移動と区別する(以前はどちらも「退避」で、同じ画面に2つの意味で並んでいた)。

// 容量の書式は fmtBytesGb(「12.3 GB」)に統一する。同じ画面で fmtGb(x)+"GB" と混在させると、
// 同じ値が2つの見た目で並び、別の量に見える。
//
// 保持policy(削除)は設定画面が持つ。この画面はfileを消さないので、消す導線はそちらへ送る。
// settings.html には retention 用のanchorが無いため、既存のbutton idを飛び先にする。
const RETENTION_HREF = "/settings#retention-preview";

// ---- 動画の保存先 ----
// 「対象を確認」で一覧(dry-run)を出し、確認してから「最終保存先へ移動」。押した順序を
// 保つため、一覧を見るまで実行buttonは出さない。
let relocationPlan = null;

function placeTotalText(entry) {
  if (!entry) return "-";
  const parts = [`${fmtNum(entry.items)} 本`, fmtBytesGb(entry.bytes)];
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
  const clipBacklog = placement.clip_items || 0;
  moveText.textContent = backlog
    ? `まだ移していない完了録画: ${fmtNum(backlog)} 本 / ${fmtBytesGb(placement.bytes)}`
    : "まだ移していない完了録画はありません。";

  const notes = [];
  // 切り出しは常に一時保存先へ出て、録画に随伴して最終保存先へ移る。録画が0本でも成果物
  // だけが残るので(録画を移した後に切り出した分)、別の行として必ず出す。
  if (clipBacklog) {
    notes.push(`一緒に移る切り出し ${fmtNum(clipBacklog)} 本`
      + `（${fmtBytesGb(placement.clip_bytes)}）`);
  }
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
    [`@${s.unique_id}`, `${fmtNum(s.items)} 本`, fmtBytesGb(s.bytes)].forEach((value, i) => {
      const td = document.createElement("td");
      if (i >= 1) td.className = "num";
      td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  setListState(document.getElementById("reloc-empty"),
    tbody.childElementCount === 0 ? "empty" : "ok");

  const clips = plan.clip_total_items || 0;
  document.getElementById("reloc-summary").textContent =
    `移動する録画 ${fmtNum(plan.total_items)} 本 / ${fmtBytesGb(plan.total_bytes)}`
    + (clips ? ` ＋ 切り出し ${fmtNum(clips)} 本 / ${fmtBytesGb(plan.clip_total_bytes)}` : "")
    + `（移動先 ${plan.final_dir}）`;
  const applyBtn = document.getElementById("reloc-apply");
  // 録画が0本でも切り出しだけが残ることがある。件数の合計で判断しないと、移すものが在る
  // のにbuttonが出ない。
  applyBtn.classList.toggle("hidden", plan.total_items === 0 && clips === 0);
  // 実行中に一覧を取り直しても、押せる見た目に戻さない(2度目は409で断られる)。
  applyBtn.disabled = relocateRunning;
}

// ---- 移動の実行状態 ----
// 移動は分単位かかり、進捗はjob台帳が持つ。押した本人のtabにしか実行中が出ないと、
// 再読み込みや別tabからは「押していない」ように見えて二重に押される。台帳はWSが
// 接続時にsnapshot(jobs)を配るので、画面はそこから復元する。
const RELOCATE_JOB_DOMAIN = "relocate";
const relocateJobStates = new Map();
let relocateRunning = false;
// このtabがPOSTの応答を待っているか。待っている側は応答が終わり方を書くので、WSからは
// 出さない(同じことを2回名乗ると、どちらが結果なのか読めなくなる)。
let relocateAwaitingHere = false;

function relocStatusRunning() {
  const status = document.getElementById("reloc-status");
  status.classList.remove("is-error");
  status.replaceChildren(document.createTextNode("移動中…（進捗は"));
  const link = document.createElement("a");
  link.href = "/jobs?kind=relocate";
  link.textContent = "Job画面";
  status.append(link, document.createTextNode("で確認できます）"));
}

function applyRelocateState(running) {
  if (running === relocateRunning) return;
  relocateRunning = running;
  document.getElementById("reloc-apply").disabled = running;
  if (running) {
    relocStatusRunning();
    return;
  }
  // 終わり方(何本移せたか)はPOSTの応答が書く。応答を受け取らない側(再読み込み後・別tab)
  // には届かないので、実行中の表示を残さず現況を取り直す。
  setFormMessage(document.getElementById("reloc-status"), "");
  loadCapacity();
}

function trackRelocateJob(job) {
  if (!job || job.domain !== RELOCATE_JOB_DOMAIN) return;
  relocateJobStates.set(job.job_id, job.state);
}

function onJobMessage(message) {
  if (message.type === "jobs") {
    relocateJobStates.clear();
    (message.data || []).forEach(trackRelocateJob);
  } else if (message.type === "job_update" && message.job) {
    const job = message.job;
    const prev = relocateJobStates.get(job.job_id);
    trackRelocateJob(job);
    // 移動は数分かかる。終わり方を持っているのはPOSTの応答を待っているtabだけで、
    // reload後や別tabには何も届かなかった。実行中から終端へ移ったここが唯一の契機。
    // snapshot(type=jobs)では出さない — 接続のたび過去の移動を蒸し返すことになる。
    if (job.domain === RELOCATE_JOB_DOMAIN && !relocateAwaitingHere
        && ["pending", "running"].includes(prev)
        && !["pending", "running"].includes(job.state)) {
      if (job.state === "completed") {
        showToast(job.message || "最終保存先への移動が終わりました。", null,
          { title: "最終保存先へ移動" });
      } else {
        showToast(job.message || job.state, "error", { title: "最終保存先へ移動" });
      }
      // 現況の取り直しはapplyRelocateStateが実行中→停止の移りで既に行う。
    }
  } else {
    return;
  }
  applyRelocateState([...relocateJobStates.values()].some((state) => state === "running"));
}

document.getElementById("reloc-plan").addEventListener("click", async () => {
  const status = document.getElementById("reloc-status");
  setFormMessage(status, "対象を確認中…");
  try {
    renderRelocationPlan(await apiSend("GET", "/api/storage/relocate"));
    setFormMessage(status, "");
  } catch (err) {
    setFormMessage(status, err.message, true);
    showError(err, "移動対象の確認");
  }
});

document.getElementById("reloc-apply").addEventListener("click", async () => {
  if (!relocationPlan) return;
  const planClips = relocationPlan.clip_total_items || 0;
  if (!relocationPlan.total_items && !planClips) return;
  const ok = await confirmDialog(
    `${fmtNum(relocationPlan.total_items)} 本（${fmtBytesGb(relocationPlan.total_bytes)}）を`
    + `\n${relocationPlan.final_dir}\nへ移します。録画中のものは含みません。`
    + (planClips
      ? `\n\nその録画から作った切り出し ${fmtNum(planClips)} 本`
        + `（${fmtBytesGb(relocationPlan.clip_total_bytes)}）も一緒に移します。`
      : "")
    + `\n\n容量が大きいため数分かかります。`,
    { title: "最終保存先へ移動", confirmLabel: "移動する", danger: false },
  );
  if (!ok) return;
  const btn = document.getElementById("reloc-apply");
  const status = document.getElementById("reloc-status");
  btn.disabled = true;
  relocStatusRunning();
  relocateAwaitingHere = true;
  try {
    const result = await apiSend("POST", "/api/storage/relocate", { confirm: true });
    const r = result.result || {};
    const failed = (r.failures || []).length;
    // 一部でも移せなかったら警告色にする。全部成功したときと同じ見た目で出すと、
    // 「移動しました」の後ろに付く失敗件数が読み飛ばされる。
    setFormMessage(
      status,
      `${fmtNum(r.moved || 0)} 本（${fmtBytesGb(r.moved_bytes || 0)}）を移動しました`
      + (r.clips_moved
        ? `。切り出し ${fmtNum(r.clips_moved)} 本（${fmtBytesGb(r.clips_moved_bytes || 0)}）も移動しました`
        : "")
      + (failed ? `。${fmtNum(failed)} 本は失敗し一時保存先に残っています。` : "。"),
      failed > 0,
    );
    renderRelocationPlan(result.plan);
    loadCapacity();
  } catch (err) {
    setFormMessage(status, err.message, true);
    showError(err, "最終保存先へ移動");
  } finally {
    relocateAwaitingHere = false;
    // 実行中はWSの台帳が押せない状態を持つ。応答が返った時点で走っていなければ戻す。
    btn.disabled = relocateRunning;
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

// driveの空きだけは topbar のbarと同じ周期で取り直すので、行の描画を分けて持つ。
function renderDiskRows(data) {
  const volumes = ((data.now || {}).disk || {}).volumes || {};
  const forecasts = data.forecasts || {};
  const tbody = document.getElementById("cap-rows");
  tbody.replaceChildren();
  // 空きの列に敷くbarの基準。drive間で全体sizeが違うので、比べたいのは「空きの絶対量」
  // ではなくそのdriveの中でどれだけ残っているか。各行の全体を1とする。
  const freeRatio = (v) => (v.total_bytes ? (v.free_bytes || 0) / v.total_bytes : 0);
  Object.keys(volumes).sort().forEach((name) => {
    const v = volumes[name] || {};
    const f = forecasts[name] || { status: "insufficient_data", n: 0 };
    const perDay = f.slope_bytes_per_day;
    const cells = [
      name,
      fmtBytesGb(v.free_bytes),
      fmtBytesGb(v.total_bytes),
      // 減少を負で出す。絶対値だけ出すと増えているのか減っているのか読めない。
      perDay === undefined ? "—" : `${perDay > 0 ? "+" : ""}${fmtBytesGb(perDay)}`,
      forecastCell(f),
    ];
    const tr = document.createElement("tr");
    cells.forEach((value, i) => {
      const td = document.createElement("td");
      if (i >= 1) td.className = "num";
      td.textContent = value;
      // 空きの列だけ、そのdriveの全体に対する割合をbarで敷く。桁を読む前に残量が判る。
      if (i === 1) {
        td.classList.add("q");
        td.style.setProperty("--q", freeRatio(v).toFixed(4));
      }
      tr.appendChild(td);
    });
    const title = forecastTitle(f);
    if (title) tr.title = title;
    // 閾値割れは既にops_eventとして残るので、ここでは色を付けるだけにする。
    // rank-topは順位表の1位を指すclassで、renderTableRowsが先頭行へ自動で付ける。
    // 「危ない」に流用すると1位の強調と見分けが付かないので、警告は専用のclassで出す。
    if (f.status === "ok" && f.days_low < 14) tr.classList.add("row-warn");
    tbody.appendChild(tr);
  });
  setListState(document.getElementById("cap-empty"),
    tbody.childElementCount === 0 ? "empty" : "ok");
}

function renderCapacity(data) {
  capacityReport = data;
  const now = data.now || {};
  renderDiskRows(data);

  const samples = data.samples || [];
  document.getElementById("cap-summary").textContent = samples.length
    ? `記録 ${fmtNum(samples.length)} 件（最新 ${fmtDateTime(data.sampled_at)}）`
    : "記録はまだありません（最初の記録が入るまで予測は出ません）";

  renderPlacement(data.placement);

  const daily = (data.recording_daily || []).slice(-14).reverse();
  const dailyBody = document.getElementById("cap-daily");
  dailyBody.replaceChildren();
  // 増加の列に敷くbarは、出ている14日の中での最大を1とする相対。
  const dailyMax = daily.reduce((a, d) => (d.bytes > a ? d.bytes : a), 0);
  daily.forEach((d) => {
    const tr = document.createElement("tr");
    [d.day, `${fmtNum(d.recordings)} 本`, fmtBytesGb(d.bytes)].forEach((value, i) => {
      const td = document.createElement("td");
      if (i >= 1) td.className = "num";
      td.textContent = value;
      if (i === 2 && dailyMax > 0) {
        td.classList.add("q");
        td.style.setProperty("--q", ((d.bytes || 0) / dailyMax).toFixed(4));
      }
      tr.appendChild(td);
    });
    dailyBody.appendChild(tr);
  });
  setListState(document.getElementById("cap-daily-empty"),
    dailyBody.childElementCount === 0 ? "empty" : "ok");

  const c = data.completion || {};
  // 母数0はnullで返る(0%ではない)。「対象なし」と「1件も終わっていない」を混同しない。
  const rate = (value) => (value === null || value === undefined ? "—" : `${value.toFixed(1)}%`);
  // 率はserverが%で返す(0〜100)。barへ渡すのは0〜1なので100で割る。
  const ratio = (value) => (value === null || value === undefined ? null : value / 100);
  renderChips("cap-completion", [
    ["完了した録画", `${fmtNum(c.completed_recordings || 0)} 本`],
    ["文字起こし済み", `${rate(c.transcribed_rate)} (${fmtNum(c.transcribed || 0)})`, ratio(c.transcribed_rate)],
    ["焼き込み済み", `${rate(c.overlay_rate)} (${fmtNum(c.overlay_done || 0)})`, ratio(c.overlay_rate)],
  ]);

  const db = now.db_files || {};
  const backups = now.backups || {};
  const rows = now.rows || {};
  renderChips("cap-dbusage", [
    ["Database", fmtBytesGb(db.db)],
    ["WAL", fmtBytesGb(db.wal)],
    ["DB backup", `${fmtBytesGb(backups.bytes)} (${fmtNum(backups.files || 0)}件)`],
  ]);
  document.getElementById("cap-dbrows").textContent = [
    `event ${fmtNum(rows.events || 0)}行`,
    `検索index ${fmtNum(rows.search_hits || 0)}行`,
    `User ${fmtNum(rows.users || 0)}人`,
  ].join(" / ");
}

// 3つ目のratio(0〜1)は任意。割合の値にだけ達成barを添える。母数が無い(null)ときは
// 付けない — 長さ0のbarは「0%」に読めるが、実際は「対象なし」で別の意味になる。
function renderChips(containerId, entries) {
  const bar = document.getElementById(containerId);
  bar.replaceChildren();
  entries.forEach(([label, value, ratio]) => {
    const chip = document.createElement("div");
    chip.className = "a-chip";
    const l = document.createElement("span");
    l.className = "l";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "v";
    v.textContent = value;
    chip.append(l, v);
    if (Number.isFinite(ratio)) {
      const track = document.createElement("span");
      track.className = "bar";
      const fill = document.createElement("i");
      fill.style.width = `${Math.min(100, Math.max(0, ratio * 100)).toFixed(1)}%`;
      track.appendChild(fill);
      chip.appendChild(track);
    }
    bar.appendChild(chip);
  });
}

// 直近に描いた集計。空きだけを差し替えるために持つ。
let capacityReport = null;

// 取り直せたかを返す。「最新にする」は押しても値がほとんど動かない操作なので、
// 押した側が成否を名乗るにはここの結果が要る。
async function loadCapacity() {
  try {
    renderCapacity(await apiSend("GET", "/api/capacity"));
    return true;
  } catch (err) {
    // 取得失敗を「記録なし」として描くと、予測が出ない理由を取り違える。
    setListState(document.getElementById("cap-empty"), "failed", err);
    setListState(document.getElementById("cap-daily-empty"), "failed", err);
    return false;
  }
}

// topbarの空きbarは60秒ごとに取り直しているのに、この表は起動時の値のままだった。同じ画面に
// 新旧2つの空きが並ぶので、barと同じ周期・同じ出所(O(1)の /api/disk)で空きだけ合わせる。
// 完了録画の所在や日次の実績まで取り直すと、録画数千本ぶんのpath解決が60秒ごとに走るため、
// そちらは「最新にする」を押したときだけにする。
async function refreshDiskRows() {
  if (!capacityReport) return;
  let disk;
  try {
    disk = await apiSend("GET", "/api/disk");
  } catch (err) {
    // 取れなかっただけで、表に出ているのは最後に測れた値。0や空へ描き替える理由はない。
    console.warn(`cap-rows: ${errorDetailText(err)}`, err);
    return;
  }
  capacityReport.now = { ...(capacityReport.now || {}), disk };
  renderDiskRows(capacityReport);
}

setInterval(refreshDiskRows, DISK_POLL_MS);

document.getElementById("cap-reload").addEventListener("click", async () => {
  const btn = document.getElementById("cap-reload");
  const status = document.getElementById("cap-status");
  btn.disabled = true;
  setFormMessage(status, "取り直し中…");
  // 取り直しても値はほぼ同じで、グラフは同じ絵のまま描き直る。取り直した時刻を出さないと
  // 押せたのかどうかが画面から読めない(新しいsampleを作る操作ではないので数値も動かない)。
  const ok = await loadCapacity();
  setFormMessage(status,
    ok ? `取り直しました（${fmtDateTime(Date.now() / 1000)}）` : "取り直せませんでした。", !ok);
  btn.disabled = false;
});

document.getElementById("cap-sample").addEventListener("click", async () => {
  const btn = document.getElementById("cap-sample");
  const status = document.getElementById("cap-status");
  btn.disabled = true;
  setFormMessage(status, "記録中…");
  try {
    const result = await apiSend("POST", "/api/capacity/sample");
    renderCapacity(result.report);
    setFormMessage(status, `記録しました（${fmtDateTime(result.sampled_at)}）`);
  } catch (err) {
    setFormMessage(status, err.message, true);
    showError(err, "容量の記録");
  } finally {
    btn.disabled = false;
  }
});

// ---- 録画folderの内訳 ----
// 判定と文言はserverが持つ(種別labelも再生成可否もAPI応答のまま描画する)。
const usageStatusEl = document.getElementById("usage-status");
const usageSummaryEl = document.getElementById("usage-summary");
const usageScanBtn = document.getElementById("usage-scan");

// 配信者別に出す種別列の上限。serverは11種別を返すので全部を列にすると横に潰れる。容量の
// 大きい方から選び、残りは「その他」1列へ畳む(和が「容量」列と一致することが条件なので、
// その他は合計からの差で出す)。
const USAGE_STREAMER_COLUMNS = 6;

// 表示する種別列と、畳む種別。列の並びはserverの定義順(category_labels)のままにする。
// 上の種別表と列の順が入れ替わると、同じ種別を2つの並びで読むことになる。
function usageStreamerColumns(usage) {
  const labels = usage.category_labels || [];
  const totals = usage.categories || {};
  const bytesOf = (key) => (totals[key] || {}).bytes || 0;
  const shownKeys = new Set(
    [...labels]
      .sort((a, b) => bytesOf(b.key) - bytesOf(a.key))
      .slice(0, USAGE_STREAMER_COLUMNS)
      .filter((entry) => bytesOf(entry.key) > 0)
      .map((entry) => entry.key),
  );
  const hidden = labels.filter((entry) => !shownKeys.has(entry.key));
  return {
    shown: labels.filter((entry) => shownKeys.has(entry.key)),
    hidden,
    // 畳んだ側が全部0なら列を作らない(常に0.0 GBが並ぶ列は読む助けにならない)。
    other: hidden.some((entry) => bytesOf(entry.key) > 0),
  };
}

function renderUsageStreamerHead(columns) {
  const head = document.getElementById("usage-streamer-head");
  head.replaceChildren();
  const cells = [
    { label: "配信者" },
    { label: "容量", num: true, title: "この配信者のfileの合計です（右の内訳の和と一致します）。" },
  ];
  columns.shown.forEach((entry) => cells.push({ label: entry.label, num: true }));
  if (columns.other) {
    cells.push({
      label: "その他",
      num: true,
      title: `列にしていない種別（${columns.hidden.map((e) => e.label).join(" / ")}）の合計です。`
        + "cellにカーソルを合わせると、その配信者ぶんの内訳が出ます。",
    });
  }
  cells.forEach(({ label, num, title }) => {
    const th = document.createElement("th");
    if (num) th.className = "num";
    if (title) th.title = title;
    th.textContent = label;
    head.appendChild(th);
  });
}

// 「その他」cell。差で出すので、列にした種別の和と足すと必ず「容量」列に一致する。
function usageOtherCell(row, columns) {
  const bytesOf = (key) => (row.categories[key] || {}).bytes || 0;
  const shownBytes = columns.shown.reduce((sum, entry) => sum + bytesOf(entry.key), 0);
  const span = document.createElement("span");
  span.textContent = fmtBytesGb(Math.max(0, (row.bytes || 0) - shownBytes));
  const parts = columns.hidden
    .filter((entry) => bytesOf(entry.key) > 0)
    .map((entry) => `${entry.label} ${fmtBytesGb(bytesOf(entry.key))}`);
  span.title = parts.length ? parts.join("\n") : "この配信者には該当するfileがありません。";
  return span;
}

// 「作り直せる」種別のcell。作り直せると書きながら消す導線が無いと、読んだ人はこの画面で
// 探し続けることになる。削除そのものは設定画面(確認2段)が持つので、そこへ送る。
function usageRegenerableCell(row, regenerable) {
  if (!regenerable.has(row.key)) return "作り直せない";
  const wrap = document.createElement("span");
  wrap.append(document.createTextNode("作り直せる "));
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-compact";
  btn.textContent = "保持policyで確認する";
  btn.title = "設定画面の保持policyへ移動します。この画面ではfileを消しません。";
  btn.addEventListener("click", () => { location.href = RETENTION_HREF; });
  wrap.appendChild(btn);
  return wrap;
}

function renderUsage(payload) {
  const scan = payload && payload.scan;
  const hasScan = Boolean(scan && scan.usage);
  setListState(document.getElementById("usage-category-empty"), hasScan ? "ok" : "empty");
  setListState(document.getElementById("usage-streamer-empty"), hasScan ? "ok" : "empty");
  if (!hasScan) {
    document.getElementById("usage-category-list").replaceChildren();
    document.getElementById("usage-streamer-list").replaceChildren();
    document.getElementById("usage-streamer-head").replaceChildren();
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
      usageRegenerableCell(row, regenerable),
    ],
    [1, 2],
    null,
    [{ col: 1, value: (row) => row.bytes }],
  );

  const columns = usageStreamerColumns(usage);
  renderUsageStreamerHead(columns);
  renderTableRows(
    "usage-streamer-list",
    null,
    usage.streamers || [],
    (row) => {
      const cat = (key) => fmtBytesGb((row.categories[key] || {}).bytes || 0);
      const cells = [row.label, fmtBytesGb(row.bytes)];
      columns.shown.forEach((entry) => cells.push(cat(entry.key)));
      if (columns.other) cells.push(usageOtherCell(row, columns));
      return cells;
    },
    // 配信者列以外はすべて容量。列数は種別の数で変わるので、番号も数から組む。
    Array.from({ length: 1 + columns.shown.length + (columns.other ? 1 : 0) },
      (_, i) => i + 1),
    null,
    // barを敷くのは合計の列だけ。種別ごとの列にも敷くと、列ごとに基準の違うbarが横に
    // 7本並び、隣の列と長さを比べられるように見えてしまう。
    [{ col: 1, value: (row) => row.bytes }],
  );
}

async function loadUsage() {
  try {
    renderUsage(await apiSend("GET", "/api/storage/usage"));
    setFormMessage(usageStatusEl, "");
  } catch (err) {
    // 生のfetchでは失敗時にrenderUsageを呼べず、placeholderがhiddenのまま見出しだけの
    // 空欄になっていた。取得できなかったことを表の位置で名乗らせる。
    document.getElementById("usage-category-list").replaceChildren();
    document.getElementById("usage-streamer-list").replaceChildren();
    document.getElementById("usage-streamer-head").replaceChildren();
    setListState(document.getElementById("usage-category-empty"), "failed", err);
    setListState(document.getElementById("usage-streamer-empty"), "failed", err);
    usageSummaryEl.textContent = "";
    setFormMessage(usageStatusEl, "");
  }
}

usageScanBtn.addEventListener("click", async () => {
  usageScanBtn.disabled = true;
  setFormMessage(usageStatusEl, "走査中…（数TB規模では数分かかります）");
  try {
    renderUsage(await apiSend("POST", "/api/storage/scan"));
    setFormMessage(usageStatusEl, "走査しました。");
    // 数TB規模では数分かかる。待つ間に画面を離れるのが普通なので、結末はtoastで残す。
    showToast("録画folderを走査しました。", null, { title: "容量の再scan" });
  } catch (err) {
    setFormMessage(usageStatusEl, err.message, true);
    showError(err, "容量の再scan");
  } finally {
    usageScanBtn.disabled = false;
  }
});

loadCapacity();
loadUsage();
// 進捗の中身はJob画面が持つ。この画面が台帳から要るのは「移動が走っているか」だけで、
// 実行中の表示と二重実行の抑止をそこから復元する。
connectWS(onJobMessage);
