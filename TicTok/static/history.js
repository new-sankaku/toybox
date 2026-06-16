"use strict";

let aggChart = null;
let detailChart = null;
let currentSessionId = null;

function buildAggChart() {
  aggChart = new Chart(document.getElementById("agg-chart"), {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { label: "Gift数", type: "bar", data: [], backgroundColor: "#8e4f2f", yAxisID: "y" },
        { label: "Diamonds", type: "bar", data: [], backgroundColor: "rgba(169, 110, 73, 0.55)", yAxisID: "y2" },
        { label: "Comment数", type: "line", data: [], borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderWidth: 1.5, pointRadius: 2, tension: 0.25, yAxisID: "y" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { ...nierTicks(), maxRotation: 40 }, grid: { color: NIER_GRID_COLOR } },
        y: { position: "left", beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR } },
        y2: { position: "right", beginAtZero: true, ticks: nierTicks(), grid: { drawOnChartArea: false } },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: nierTooltip(),
      },
    },
  });
}

function renderChips(containerId, chips) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  chips.forEach(([label, value]) => {
    const chip = document.createElement("div");
    chip.className = "result-chip";
    const l = document.createElement("span");
    l.className = "label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "value";
    v.textContent = value;
    chip.append(l, v);
    container.appendChild(chip);
  });
}

async function loadDashboard() {
  const res = await fetch("/api/dashboard");
  if (!res.ok) return;
  const data = await res.json();
  const totals = data.totals || {};
  renderChips("agg-totals", [
    ["Session数", fmtNum(totals.sessions)],
    ["総Gift数", fmtNum(totals.gifts)],
    ["総Diamonds", fmtNum(totals.diamonds)],
    ["総Comment", fmtNum(totals.comments)],
    ["総Like", fmtNum(totals.likes)],
    ["総収集時間", fmtDuration(totals.duration || 0)],
  ]);
  const recents = data.recent_sessions || [];
  aggChart.data.labels = recents.map((s) => `#${s.id} @${s.unique_id}`);
  aggChart.data.datasets[0].data = recents.map((s) => s.gifts);
  aggChart.data.datasets[1].data = recents.map((s) => s.diamonds);
  aggChart.data.datasets[2].data = recents.map((s) => s.comments);
  aggChart.update();

  renderTableRows(
    "streamer-ranking",
    "streamer-ranking-empty",
    data.streamers || [],
    (s, rank) => [String(rank), `@${s.unique_id}`, fmtNum(s.sessions), fmtNum(s.gifts), fmtNum(s.diamonds), fmtNum(s.comments)],
    [0, 2, 3, 4, 5],
  );
  renderTableRows(
    "gifter-ranking",
    "gifter-ranking-empty",
    data.top_gifters || [],
    (u, rank) => [
      String(rank),
      u.unique_id ? `${u.nickname} (@${u.unique_id})` : u.nickname,
      fmtNum(u.gifts),
      fmtNum(u.diamonds),
      fmtNum(u.sessions),
    ],
    [0, 2, 3, 4],
  );
}

const RANKING_METRICS = [
  { key: "likes", label: "Like", head: "Like数" },
  { key: "comments", label: "Comment", head: "Comment数" },
  { key: "gifts", label: "Gift (Diamonds)", head: "Diamonds" },
  { key: "battles", label: "Battle Score", head: "Battle Score" },
];
let rankingsData = null;
let activeMetric = "gifts";

function initRankingTabs() {
  const bar = document.getElementById("ranking-tabs");
  RANKING_METRICS.forEach((metric) => {
    const tab = document.createElement("button");
    tab.className = `tab${metric.key === activeMetric ? " tab-active" : ""}`;
    tab.textContent = metric.label;
    tab.dataset.metric = metric.key;
    tab.addEventListener("click", () => {
      activeMetric = metric.key;
      bar.querySelectorAll(".tab").forEach((t) => {
        t.classList.toggle("tab-active", t.dataset.metric === activeMetric);
      });
      renderRanking();
    });
    bar.appendChild(tab);
  });
}

function renderRanking() {
  const metric = RANKING_METRICS.find((m) => m.key === activeMetric);
  document.getElementById("ranking-value-head").textContent = metric.head;
  const rows = ((rankingsData && rankingsData[activeMetric]) || []).filter((r) => r.value > 0);
  renderTableRows(
    "ranking-table",
    "ranking-empty",
    rows,
    (r, rank) => [
      String(rank),
      `#${r.session_id}`,
      `@${r.unique_id}`,
      fmtDateTime(r.started_at),
      r.ended_at ? fmtDuration(r.ended_at - r.started_at) : "収集中",
      fmtNum(r.value),
    ],
    [0, 5],
  );
}

async function loadRankings() {
  const res = await fetch("/api/rankings");
  if (!res.ok) return;
  rankingsData = await res.json();
  renderRanking();
}

function sessionActions(session, isActive) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";

  const showBtn = document.createElement("button");
  showBtn.className = "btn btn-small";
  showBtn.textContent = "表示";
  showBtn.addEventListener("click", () => showDetail(session.id));

  const csvLink = document.createElement("a");
  csvLink.className = "btn btn-small";
  csvLink.textContent = "CSV";
  csvLink.href = `/api/sessions/${session.id}/export.csv`;

  const jsonLink = document.createElement("a");
  jsonLink.className = "btn btn-small";
  jsonLink.textContent = "JSON";
  jsonLink.href = `/api/sessions/${session.id}/export.json`;

  const delBtn = document.createElement("button");
  delBtn.className = "btn btn-small btn-danger";
  delBtn.textContent = "削除";
  delBtn.disabled = isActive;
  delBtn.title = isActive ? "収集中のSessionは削除できません" : "";
  delBtn.addEventListener("click", async () => {
    if (!window.confirm(`Session #${session.id} (@${session.unique_id}) を削除しますか？この操作は取り消せません。`)) return;
    try {
      await apiSend("DELETE", `/api/sessions/${session.id}`);
      if (currentSessionId === session.id) {
        document.getElementById("session-detail").classList.add("hidden");
        currentSessionId = null;
      }
      await Promise.all([loadSessions(), loadDashboard()]);
    } catch (err) {
      window.alert(err.message);
    }
  });

  wrap.append(showBtn, csvLink, jsonLink, delBtn);
  return wrap;
}

async function loadSessions() {
  const res = await fetch("/api/sessions");
  if (!res.ok) return;
  const data = await res.json();
  const active = new Set(data.active_session_ids || []);
  renderTableRows(
    "session-list",
    "session-list-empty",
    data.sessions || [],
    (session) => {
      const stats = session.stats || {};
      const duration = session.ended_at
        ? fmtDuration(session.ended_at - session.started_at)
        : "収集中";
      const info = STATUS_LABELS[session.status] || STATUS_LABELS.idle;
      const note = session.note ? (session.note.length > 24 ? `${session.note.slice(0, 24)}…` : session.note) : "";
      return [
        `#${session.id}`,
        `@${session.unique_id}`,
        fmtDateTime(session.started_at),
        duration,
        active.has(session.id) ? "収集中" : info.badge,
        fmtNum(stats.gifts),
        fmtNum(stats.diamonds),
        note,
        sessionActions(session, active.has(session.id)),
      ];
    },
    [5, 6],
  );
}

async function showDetail(sessionId) {
  const res = await fetch(`/api/sessions/${sessionId}`);
  if (!res.ok) return;
  const data = await res.json();
  const session = data.session;
  currentSessionId = sessionId;

  document.getElementById("detail-title").textContent =
    `Session #${session.id} — @${session.unique_id} (${fmtDateTime(session.started_at)})`;
  const stats = session.stats || {};
  const duration = session.ended_at ? fmtDuration(session.ended_at - session.started_at) : "収集中";
  renderChips("detail-totals", [
    ["収集時間", duration],
    ["Gift合計", fmtNum(stats.gifts)],
    ["Diamonds合計", fmtNum(stats.diamonds)],
    ["Comment合計", fmtNum(stats.comments)],
    ["Like合計", fmtNum(stats.likes_total)],
    ["最大同接", fmtNum(stats.viewers)],
    ["Battle回数", fmtNum(stats.battles)],
  ]);
  document.getElementById("note-input").value = session.note || "";
  document.getElementById("note-status").textContent = "";

  detailChart.update(data.timeline);

  const summary = data.summary || {};
  renderTableRows(
    "user-ranking",
    "user-ranking-empty",
    summary.users || [],
    (user, rank) => [
      String(rank),
      user.unique_id ? `${user.nickname} (@${user.unique_id})` : user.nickname,
      fmtNum(user.gifts),
      fmtNum(user.diamonds),
      topItemText(user.items),
    ],
    [0, 2, 3],
  );
  renderTableRows(
    "gift-ranking",
    "gift-ranking-empty",
    summary.gifts || [],
    (gift, rank) => [String(rank), gift.name, fmtNum(gift.count), fmtNum(gift.diamonds)],
    [0, 2, 3],
  );

  renderRecordings(data.recordings || []);

  const detail = document.getElementById("session-detail");
  detail.classList.remove("hidden");
  detail.scrollIntoView({ behavior: "smooth", block: "start" });
}

const RECORDING_STATUS = {
  recording: "録画中",
  completed: "完了",
  failed: "失敗",
  interrupted: "中断",
  stopping: "停止中",
};

function recordingActions(rec) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  const playable = rec.status === "completed" || rec.status === "interrupted";
  if (playable) {
    const dl = document.createElement("a");
    dl.className = "btn btn-small";
    dl.textContent = "DL";
    dl.href = `/api/recordings/${rec.id}/download`;
    wrap.appendChild(dl);
  }
  const del = document.createElement("button");
  del.className = "btn btn-small btn-danger";
  del.textContent = "削除";
  del.disabled = rec.status === "recording";
  del.addEventListener("click", async () => {
    if (!window.confirm(`録画 #${rec.id} (${rec.filename}) を削除しますか？この操作は取り消せません。`)) return;
    try {
      await apiSend("DELETE", `/api/recordings/${rec.id}`);
      if (currentSessionId !== null) showDetail(currentSessionId);
    } catch (err) {
      window.alert(err.message);
    }
  });
  wrap.appendChild(del);
  return wrap;
}

function renderRecordings(recordings) {
  renderTableRows(
    "recording-list",
    "recording-list-empty",
    recordings,
    (rec) => {
      const dur = rec.ended_at ? fmtDuration(rec.ended_at - rec.started_at) : "-";
      const mb = `${(rec.bytes / 1048576).toFixed(1)} MB`;
      return [
        `#${rec.id}`,
        rec.filename,
        rec.quality || "-",
        RECORDING_STATUS[rec.status] || rec.status,
        dur,
        mb,
        recordingActions(rec),
      ];
    },
    [0, 4, 5],
  );
}

document.getElementById("note-save").addEventListener("click", async () => {
  if (currentSessionId === null) return;
  const status = document.getElementById("note-status");
  try {
    await apiSend("PATCH", `/api/sessions/${currentSessionId}`, {
      note: document.getElementById("note-input").value,
    });
    status.textContent = "保存しました。";
    await loadSessions();
  } catch (err) {
    status.textContent = err.message;
  }
});

function handleMessage(msg) {
  if (msg.type === "monitors" || msg.type === "state") {
    loadSessions();
    loadRankings();
  }
}

buildAggChart();
detailChart = createTimelineChart(document.getElementById("detail-chart"));
initRankingTabs();
loadDashboard();
loadSessions();
loadRankings();
connectWS(handleMessage);
setInterval(() => {
  loadDashboard();
  loadRankings();
}, 30000);
