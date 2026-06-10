"use strict";

const STATUS_LABELS = {
  idle: { badge: "IDLE", cls: "badge-idle", message: "待機中" },
  connecting: { badge: "CONNECTING", cls: "badge-connecting", message: "接続処理を実行中です…" },
  connected: { badge: "RECEIVING", cls: "badge-connected", message: "LIVEに接続済み。Eventを受信しています。" },
  reconnecting: { badge: "RECONNECTING", cls: "badge-reconnecting", message: "接続が不安定なため再接続しています…（収集Dataは保持されます）" },
  disconnected: { badge: "STOPPED", cls: "badge-idle", message: "収集を停止しました。" },
  ended: { badge: "LIVE ENDED", cls: "badge-ended", message: "LIVE配信が終了しました。" },
  error: { badge: "ERROR", cls: "badge-error", message: "Errorが発生しました。" },
};

function fmtTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString("ja-JP", { hour12: false });
}

function fmtDateTime(epochSeconds) {
  if (!epochSeconds) return "-";
  return new Date(epochSeconds * 1000).toLocaleString("ja-JP", { hour12: false });
}

function fmtDuration(seconds) {
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function fmtNum(value) {
  return Number(value || 0).toLocaleString("ja-JP");
}

async function apiSend(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    const detail = payload.detail;
    throw new Error(typeof detail === "string" ? detail : "Requestに失敗しました。");
  }
  return res.json();
}

function connectWS(onMessage) {
  const indicator = document.getElementById("ws-indicator");
  const statusEl = document.getElementById("ws-status");
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);
  ws.onopen = () => {
    if (indicator) indicator.classList.add("online");
    if (statusEl) statusEl.textContent = "Server接続: ONLINE";
  };
  ws.onmessage = (msg) => onMessage(JSON.parse(msg.data));
  ws.onclose = () => {
    if (indicator) indicator.classList.remove("online");
    if (statusEl) statusEl.textContent = "Server接続: OFFLINE — 再接続中…";
    setTimeout(() => connectWS(onMessage), 2000);
  };
  ws.onerror = () => ws.close();
  return ws;
}

const NIER_AXIS_COLOR = "#6f6a59";
const NIER_GRID_COLOR = "rgba(143, 136, 113, 0.3)";
const CHART_DISPLAY_LIMIT = 720;

function nierTooltip() {
  return {
    backgroundColor: "#4d4a3f",
    titleColor: "#d8d2bc",
    bodyColor: "#d8d2bc",
    titleFont: { family: "monospace" },
    bodyFont: { family: "monospace" },
  };
}

function nierTicks() {
  return { color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 }, precision: 0 };
}

function createTimelineChart(canvas) {
  let firstStart = null;
  let bucketSeconds = 10;
  let markers = [];

  const markerPlugin = {
    id: "tictokMarkers",
    afterDatasetsDraw(c) {
      if (!markers.length || firstStart === null) return;
      const { ctx, chartArea, scales } = c;
      markers.forEach((m) => {
        const idx = Math.round((m.time - firstStart) / bucketSeconds);
        if (idx < 0 || idx >= c.data.labels.length) return;
        const x = scales.x.getPixelForValue(idx);
        ctx.save();
        ctx.strokeStyle = "#a4502f";
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#a4502f";
        ctx.font = "10px monospace";
        ctx.textAlign = "left";
        ctx.fillText(m.label, x + 3, chartArea.top + 10);
        ctx.restore();
      });
    },
  };

  const chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { label: "Gift数", type: "bar", data: [], backgroundColor: "#8e4f2f", yAxisID: "y" },
        { label: "Diamonds", type: "bar", data: [], backgroundColor: "rgba(169, 110, 73, 0.55)", yAxisID: "y2" },
        { label: "同接数", type: "line", data: [], borderColor: "#4d4a3f", backgroundColor: "#4d4a3f", borderWidth: 2, pointRadius: 0, tension: 0.25, yAxisID: "y2" },
        { label: "Comment数", type: "line", data: [], borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: "y" },
        { label: "Like数", type: "line", data: [], borderColor: "#9b8c52", backgroundColor: "#9b8c52", borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: "y", hidden: true },
        { label: "入室数", type: "line", data: [], borderColor: "#7a7263", backgroundColor: "#7a7263", borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: "y", hidden: true },
        { label: "Follow", type: "line", data: [], borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0, yAxisID: "y", hidden: true },
        { label: "Share", type: "line", data: [], borderColor: "#a96e49", backgroundColor: "#a96e49", borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0, yAxisID: "y", hidden: true },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
          grid: { color: NIER_GRID_COLOR },
        },
        y: {
          position: "left",
          beginAtZero: true,
          title: { display: true, text: "件数", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } },
          ticks: nierTicks(),
          grid: { color: NIER_GRID_COLOR },
        },
        y2: {
          position: "right",
          beginAtZero: true,
          title: { display: true, text: "Diamonds / 同接数", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } },
          ticks: nierTicks(),
          grid: { drawOnChartArea: false },
        },
      },
      plugins: {
        legend: {
          labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 },
        },
        tooltip: nierTooltip(),
      },
    },
    plugins: [markerPlugin],
  });

  function clear() {
    firstStart = null;
    markers = [];
    chart.data.labels = [];
    chart.data.datasets.forEach((ds) => { ds.data = []; });
    chart.update();
  }

  function update(data) {
    bucketSeconds = data.bucket_seconds;
    markers = data.markers || [];
    const raw = data.buckets || [];
    if (!raw.length) {
      clear();
      return;
    }
    const size = data.bucket_seconds;
    const byStart = new Map(raw.map((b) => [b.start, b]));
    const last = raw[raw.length - 1].start;
    let first = raw[0].start;
    if ((last - first) / size + 1 > CHART_DISPLAY_LIMIT) {
      first = last - (CHART_DISPLAY_LIMIT - 1) * size;
    }
    firstStart = first;
    const labels = [];
    const series = { gifts: [], diamonds: [], viewers: [], comments: [], likes: [], joins: [], follows: [], shares: [] };
    let viewers = raw[0].viewers;
    for (let s = first; s <= last; s += size) {
      const b = byStart.get(s);
      if (b) viewers = b.viewers;
      labels.push(fmtTime(s));
      series.gifts.push(b ? b.gifts : 0);
      series.diamonds.push(b ? b.diamonds : 0);
      series.viewers.push(viewers);
      series.comments.push(b ? b.comments : 0);
      series.likes.push(b ? b.likes : 0);
      series.joins.push(b ? b.joins : 0);
      series.follows.push(b ? b.follows : 0);
      series.shares.push(b ? b.shares : 0);
    }
    chart.data.labels = labels;
    const order = ["gifts", "diamonds", "viewers", "comments", "likes", "joins", "follows", "shares"];
    order.forEach((key, i) => { chart.data.datasets[i].data = series[key]; });
    chart.update();
  }

  return { chart, update, clear };
}

function topItemText(items) {
  const entries = Object.entries(items || {});
  if (!entries.length) return "-";
  entries.sort((a, b) => b[1] - a[1]);
  const [name, count] = entries[0];
  return `${name} x${count}`;
}

function renderTableRows(tbodyId, emptyId, rows, toCells, numericCols) {
  const tbody = document.getElementById(tbodyId);
  const empty = document.getElementById(emptyId);
  tbody.innerHTML = "";
  if (empty) empty.classList.toggle("hidden", rows.length > 0);
  rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    if (i === 0) tr.className = "rank-top";
    toCells(row, i + 1).forEach((cell, col) => {
      const td = document.createElement("td");
      if (numericCols.includes(col)) td.className = "num";
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}
