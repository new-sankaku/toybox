"use strict";

// バックアップの状況。状態は色・線・棒で出し、文字は数値とpathだけにする。

const BACKUP_POLL_MS = 30000;

const BK_STATES = {
  ok: { label: "正常", word: "", level: "" },
  working: { label: "実行中", word: "", level: "" },
  degraded: { label: "一部失敗", word: "一部失敗", level: "warn" },
  late: { label: "遅延", word: "遅延", level: "warn" },
  failing: { label: "失敗", word: "失敗", level: "error" },
  unreachable: { label: "未接続", word: "未接続", level: "error" },
  off: { label: "無効", word: "無効", level: "off" },
};
const BK_HEALTHY = ["ok", "working"];
const BK_LEVEL_RANK = { error: 3, warn: 2, off: 1 };

const BK_REASONS = {
  no_path: "保存先なし",
  disabled: "無効",
  single: "保存先が1つ",
  unreachable: "未接続",
  failed: "前回失敗",
  overdue: "遅延",
  partial: "一部失敗",
  unsynced: "差分あり",
};
const BK_REASON_LEVEL = { no_path: "warn" };
const BK_REASON_WORD = { no_path: "保存先なし", single: "保存先が1つ", unsynced: "差分あり" };

const BK_ICONS = {
  db: '<path d="M8 1.8c3.3 0 5.5.9 5.5 2s-2.2 2-5.5 2-5.5-.9-5.5-2 2.2-2 5.5-2z"/><path d="M2.5 3.8v8.4c0 1.1 2.2 2 5.5 2s5.5-.9 5.5-2V3.8"/><path d="M2.5 8c0 1.1 2.2 2 5.5 2s5.5-.9 5.5-2"/>',
  film: '<rect x="1.8" y="3" width="12.4" height="10"/><path d="M4.6 3v10M11.4 3v10M1.8 8h12.4"/>',
  drive: '<rect x="1.6" y="4" width="12.8" height="8" rx="1"/><path d="M4 8.5h4"/><circle cx="11.8" cy="8.5" r="0.8"/>',
  archive: '<rect x="1.8" y="3" width="12.4" height="3"/><path d="M3 6v7h10V6"/><path d="M6.4 9h3.2"/>',
  sheet: '<path d="M3.5 1.8h6L12.5 5v9.2h-9z"/><path d="M9.2 1.8V5h3.3"/><path d="M5.6 8.4h5M5.6 11h5"/>',
  lock: '<rect x="3.5" y="7" width="9" height="6.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/>',
  scale: '<path d="M8 2v12"/><path d="M3 5h10"/><path d="M3 5 1.5 9h3z"/><path d="M13 5l1.5 4h-3z"/>',
  trash: '<path d="M2.5 4h11"/><path d="M4.5 4V2.5h7V4"/><path d="M4 4l.8 10h6.4L12 4"/>',
  book: '<path d="M2 2.5h5a2 2 0 0 1 1 1.7v9a2 2 0 0 0-1-1.4H2z"/><path d="M14 2.5H9a2 2 0 0 0-1 1.7v9a2 2 0 0 1 1-1.4h5z"/>',
  alert: '<path d="M8 1.6 15 14H1z"/><path d="M8 6v4"/><path d="M8 11.7v0.3"/>',
};

const BK_SHIELD_PATH = "M60 5 L113 24 L113 74 C113 108 89 130 60 143 C31 130 7 108 7 74 L7 24 Z";
const BK_SHIELD_TOP = 5;
const BK_SHIELD_BOTTOM = 143;

const BK_SVG_NS = "http://www.w3.org/2000/svg";

function bkIcon(name, cls) {
  const body = BK_ICONS[name] || "";
  return `<svg class="bk-ic ${cls || ""}" viewBox="0 0 16 16" aria-hidden="true">${body}</svg>`;
}

function bkEl(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function bkSvgEl(tag, attrs) {
  const node = document.createElementNS(BK_SVG_NS, tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  });
  return node;
}

function bkAgo(epochSeconds, now) {
  if (!epochSeconds) return "";
  const seconds = Math.max(0, (now || Date.now() / 1000) - Number(epochSeconds));
  if (seconds < 90) return "たった今";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}分`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}時間`;
  return `${Math.round(hours / 24)}日`;
}

function bkUntil(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  if (value < 60) return "1分内";
  const minutes = Math.ceil(value / 60);
  return minutes < 60 ? `${minutes}分後` : `${Math.ceil(minutes / 60)}時間後`;
}

function bkShortPath(path) {
  const parts = String(path || "").split(/[\\/]+/).filter(Boolean);
  return parts.slice(-2).join("\\") || String(path || "");
}

function bkLevelOf(lane) {
  const reason = (lane.reason || {}).key;
  return BK_REASON_LEVEL[reason] || BK_STATES[lane.state].level || "";
}

function bkWordOf(lane) {
  const reason = (lane.reason || {}).key;
  return BK_REASON_WORD[reason] || BK_STATES[lane.state].word || "";
}

// 割合を1本の棒で出す。数値を読ませずに大小だけを渡す所で使う。
function bkMeter(ratio, cls, title) {
  const bar = bkEl("span", `bk-meter ${cls || ""}`);
  const fill = bkEl("span", "bk-meter-fill");
  fill.style.inlineSize = `${Math.min(100, Math.max(0, ratio * 100)).toFixed(1)}%`;
  bar.appendChild(fill);
  if (title) bar.title = title;
  return bar;
}

// 内訳を1本の帯で出す。0の区画は置かない。
function bkStack(parts) {
  const total = parts.reduce((sum, part) => sum + Math.max(0, part.value || 0), 0);
  if (!total) return null;
  const bar = bkEl("span", "bk-stack");
  parts.forEach((part) => {
    const value = Math.max(0, part.value || 0);
    if (!value) return;
    const seg = bkEl("span", `bk-seg bk-seg-${part.key}`);
    seg.style.inlineSize = `${(value / total * 100).toFixed(2)}%`;
    seg.title = `${part.label} ${fmtNum(value)}`;
    bar.appendChild(seg);
  });
  return bar;
}

function bkChip(text, cls, title) {
  const chip = bkEl("span", `bk-tag ${cls || ""}`, text);
  if (title) chip.title = title;
  return chip;
}

// ---- 盾 ----

function renderShield(lanes) {
  const host = document.getElementById("bk-shield");
  if (!host) return;
  const active = lanes.filter((lane) => lane.state !== "off");
  const lit = active.filter((lane) => BK_HEALTHY.includes(lane.state));
  const height = (BK_SHIELD_BOTTOM - BK_SHIELD_TOP) / (lanes.length || 1);
  const bands = lanes.map((lane, index) => {
    const y = BK_SHIELD_TOP + height * index;
    return `<rect class="bk-band" data-state="${lane.state}" style="--i:${index}"`
      + ` x="0" y="${y.toFixed(2)}" width="120" height="${height.toFixed(2)}">`
      + `<title>${lane.label}: ${BK_STATES[lane.state].label}</title></rect>`;
  }).join("");
  const seams = lanes.slice(1).map((_lane, index) => {
    const y = BK_SHIELD_TOP + height * (index + 1);
    return `<path class="bk-seam" d="M0 ${y.toFixed(2)} H120" />`;
  }).join("");
  host.innerHTML = `
    <svg class="bk-shield-svg" viewBox="0 0 120 152" preserveAspectRatio="xMidYMid meet">
      <defs><clipPath id="bk-shield-clip"><path d="${BK_SHIELD_PATH}" /></clipPath></defs>
      <g clip-path="url(#bk-shield-clip)">${bands}${seams}</g>
      <path class="bk-shield-edge" d="${BK_SHIELD_PATH}" />
      <text class="bk-shield-num" x="60" y="80">${lit.length}/${active.length}</text>
    </svg>`;
  host.setAttribute("aria-label", `正常 ${lit.length} / ${active.length}`);
}

// ---- 図 ----

const BK_ROOTS = [
  { key: "db", label: "tictok.db", icon: "db", lanes: ["db", "config"] },
  { key: "record", label: "録画", icon: "film", lanes: ["files", "mirror"] },
];

const BK_DEST_ICONS = { db: "archive", config: "sheet", files: "drive", mirror: "drive" };

function bkDestMeta(lane, dest, data) {
  if (lane.key === "db") {
    const snap = data.snapshots || {};
    return `${fmtNum((snap.items || []).length)}本 · ${fmtBytes(snap.bytes)}`;
  }
  if (lane.key === "config") {
    const entry = (data.configs || []).find((item) => item.dir === dest.path);
    if (!entry) return "";
    const settingsCount = (entry.settings || {}).count || 0;
    const tablesCount = (entry.tables || {}).count || 0;
    const latest = (entry.settings || {}).latest;
    return `${fmtNum(Math.min(settingsCount, tablesCount))}本`
      + (latest ? ` · ${fmtDateTimeShort(latest.created_at)}` : "");
  }
  if (lane.key === "files") {
    const stock = bkPrimaryStock(data);
    return stock ? `${fmtNum(stock.items)}件 · ${fmtBytes(stock.bytes)}` : "";
  }
  // 照合していない系統を「揃っている」形で出さない。
  const check = data.mirror_check || {};
  if (!check.at) return "未照合";
  const gap = (check.missing_by_dst || {})[dest.path];
  if (gap && gap.count) return `欠け ${fmtNum(gap.count)}件 · ${fmtBytes(gap.bytes)}`;
  const final = ((data.relocation || {}).locations || {}).final || {};
  return final.items ? `${fmtNum(final.items)}本 · ${fmtBytes(final.bytes)}` : "";
}

// 一次保存の控えに在る量。直近の回で写した分と、既に同じで写さなかった分の合計。
function bkPrimaryStock(data) {
  const run = (data.primary || {}).last_run;
  if (!run) return null;
  return {
    items: (run.copied || 0) + (run.skipped || 0),
    bytes: (run.copied_bytes || 0) + (run.skipped_bytes || 0),
    at: run.started_at || 0,
  };
}

function bkNode(cls, icon, name, meta, opts) {
  const node = bkEl("div", `bk-node ${cls}`);
  const inner = bkEl("span", "bk-node-in");
  const head = bkEl("span", "bk-node-head");
  head.innerHTML = bkIcon(icon);
  const body = bkEl("span", "bk-node-body");
  body.appendChild(bkEl("b", "bk-node-name", name));
  if (meta) body.appendChild(bkEl("span", "bk-node-meta", meta));
  head.appendChild(body);
  if (opts && opts.volume) {
    const tag = bkEl("span", "bk-vol", opts.volume);
    if (opts.sameVolume) {
      tag.classList.add("bk-vol-same");
      tag.title = "元と同じdrive";
    }
    head.appendChild(tag);
  }
  inner.appendChild(head);
  if (opts && opts.gauge) inner.appendChild(opts.gauge);
  node.appendChild(inner);
  if (opts && opts.title) node.title = opts.title;
  return node;
}

// driveの使用量。空きが尽きかけている保存先を、数字を読まずに見つけるための棒。
function bkVolumeGauge(volume) {
  if (!volume || !volume.total_bytes) return null;
  const used = Math.max(0, volume.total_bytes - volume.free_bytes);
  const row = bkEl("span", "bk-free");
  row.appendChild(bkMeter(used / volume.total_bytes, "bk-meter-vol",
    `${fmtBytes(used)} / ${fmtBytes(volume.total_bytes)}`));
  row.appendChild(bkEl("span", "bk-free-val", `空き ${fmtBytes(volume.free_bytes)}`));
  return row;
}

function bkRunStack(run) {
  return bkStack([
    { key: "keep", value: run.skipped, label: "既存" },
    { key: "new", value: run.copied, label: "コピー" },
    { key: "fail", value: run.failed, label: "失敗" },
    { key: "todo", value: run.remaining, label: "未処理" },
  ]);
}

function bkLaneNode(lane, data, now) {
  const node = bkEl("div", "bk-lane");
  node.dataset.state = lane.state;
  node.dataset.lane = lane.key;
  const inner = bkEl("span", "bk-node-in");

  const head = bkEl("span", "bk-lane-head");
  head.appendChild(bkEl("b", "bk-lane-label", lane.label));
  const word = bkWordOf(lane);
  if (word) {
    const chip = bkEl("span", "bk-lane-word", word);
    chip.title = BK_REASONS[(lane.reason || {}).key] || BK_STATES[lane.state].label;
    head.appendChild(chip);
  }
  inner.appendChild(head);

  const run = lane.key === "files" ? ((data.primary || {}).last_run || {}) : null;
  if (run) {
    const stack = bkRunStack(run);
    if (stack) inner.appendChild(stack);
  }

  const step = lane.schedule || {};
  const foot = bkEl("span", "bk-lane-foot");
  if (lane.last_ok) {
    foot.appendChild(bkChip(bkAgo(lane.last_ok.ts, now), "",
      `${lane.last_ok.label || ""} ${fmtDateTime(lane.last_ok.ts)}`));
  }
  if (run && run.copied) foot.appendChild(bkChip(`コピー ${fmtNum(run.copied)}`, "bk-tag-new"));
  if (run && run.failed) foot.appendChild(bkChip(`失敗 ${fmtNum(run.failed)}`, "bk-tag-warn"));
  if (lane.state === "failing" && step.failures) {
    foot.appendChild(bkChip(`再試行 ${bkUntil(step.retry_in_seconds)}`, "bk-tag-warn",
      (lane.last_fail && lane.last_fail.message) || ""));
  } else if (step.pending) {
    foot.appendChild(bkChip(`未処理 ${fmtNum(step.pending)}`,
      lane.state === "late" ? "bk-tag-warn" : "bk-tag-run",
      step.pending_oldest_at ? `最古 ${fmtDateTime(step.pending_oldest_at)}` : ""));
  }
  inner.appendChild(foot);
  node.appendChild(inner);
  return node;
}

function bkDestNode(lane, dest, data, sourceVolume) {
  const volume = (data.volumes || {})[dest.volume];
  const node = bkNode(`bk-dst${dest.reachable ? "" : " bk-dst-gone"}`,
    BK_DEST_ICONS[lane.key], bkShortPath(dest.path), bkDestMeta(lane, dest, data), {
      volume: dest.volume,
      sameVolume: (lane.key === "db" || lane.key === "files")
        && Boolean(sourceVolume) && dest.volume === sourceVolume,
      gauge: dest.reachable ? bkVolumeGauge(volume) : null,
      title: dest.reachable ? dest.path : `${dest.path}\n親 ${dest.parent || ""}`,
    });
  node.dataset.lane = lane.key;
  // 届かないのは退避先1つずつの事実で、経路の状態をそのまま流さない。
  node.dataset.state = dest.reachable
    ? (lane.state === "unreachable" ? "ok" : lane.state)
    : "unreachable";
  return node;
}

// 線1本ぶんの幾何。節の実測位置から引く。
function bkWirePath(from, to, origin) {
  const x1 = from.right - origin.left;
  const y1 = from.top + from.height / 2 - origin.top;
  const x2 = to.left - origin.left;
  const y2 = to.top + to.height / 2 - origin.top;
  const bend = Math.max(14, (x2 - x1) * 0.45);
  return {
    d: `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + bend).toFixed(1)} ${y1.toFixed(1)},`
      + ` ${(x2 - bend).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`,
    mid: { x: (x1 + x2) / 2, y: (y1 + y2) / 2 },
  };
}

const BK_BREAK_STATES = ["failing", "unreachable"];

function drawWires(host, links, mirrorNodes, mirrorState) {
  const wires = host.querySelector(".bk-wires");
  if (!wires) return;
  const origin = host.getBoundingClientRect();
  wires.replaceChildren();
  if (origin.width <= 0 || origin.height <= 0) return;
  wires.setAttribute("viewBox", `0 0 ${origin.width.toFixed(1)} ${origin.height.toFixed(1)}`);
  links.forEach((link) => {
    const geo = bkWirePath(link.from.getBoundingClientRect(),
                           link.to.getBoundingClientRect(), origin);
    const group = bkSvgEl("g", { class: "bk-wire", "data-state": link.state });
    group.appendChild(bkSvgEl("path", { class: "bk-wire-line", d: geo.d }));
    if (link.segment === "dest" && BK_BREAK_STATES.includes(link.state)) {
      group.appendChild(bkSvgEl("path", {
        class: "bk-wire-break",
        d: `M ${geo.mid.x - 6} ${geo.mid.y - 6} L ${geo.mid.x + 6} ${geo.mid.y + 6}`
          + ` M ${geo.mid.x + 6} ${geo.mid.y - 6} L ${geo.mid.x - 6} ${geo.mid.y + 6}`,
      }));
    } else if (link.state !== "off") {
      group.appendChild(bkSvgEl("path", { class: "bk-wire-spark", d: geo.d }));
    }
    wires.appendChild(group);
  });
  drawMirrorLink(wires, origin, mirrorNodes, mirrorState);
}

// ミラーは枝ではなく保存先どうしの関係なので、木の線と同じ向きには描かない。
function drawMirrorLink(wires, origin, nodes, state) {
  if (!nodes || nodes.length < 2) return;
  const boxes = nodes.map((node) => node.getBoundingClientRect());
  const x = Math.max(...boxes.map((box) => box.right)) - origin.left;
  const ys = boxes.map((box) => box.top + box.height / 2 - origin.top);
  const bend = 18;
  const group = bkSvgEl("g", { class: "bk-wire bk-wire-mirror", "data-state": state });
  group.appendChild(bkSvgEl("path", {
    class: "bk-wire-line",
    d: `M ${x.toFixed(1)} ${ys[0].toFixed(1)} C ${(x + bend).toFixed(1)} ${ys[0].toFixed(1)},`
      + ` ${(x + bend).toFixed(1)} ${ys[1].toFixed(1)}, ${x.toFixed(1)} ${ys[1].toFixed(1)}`,
  }));
  wires.appendChild(group);
}

let bkWireRedraw = null;

function renderTree(data) {
  const host = document.getElementById("bk-map");
  if (!host) return;
  host.replaceChildren();
  host.appendChild(bkSvgEl("svg", { class: "bk-wires", "aria-hidden": "true",
                                    preserveAspectRatio: "none" }));

  const lanes = data.lanes || [];
  const byKey = new Map(lanes.map((lane) => [lane.key, lane]));
  const sources = data.sources || {};
  const links = [];
  const mirrorNodes = [];
  let row = 1;

  BK_ROOTS.forEach((root) => {
    const rootLanes = root.lanes.map((key) => byKey.get(key)).filter(Boolean);
    if (!rootLanes.length) return;
    const rootStart = row;
    const source = sources[root.key] || {};
    const sourceVolume = source.volume;
    const laneNodes = [];
    rootLanes.forEach((lane) => {
      const laneStart = row;
      const destNodes = (lane.dests.length ? lane.dests : [null]).map((dest) => {
        const node = dest
          ? bkDestNode(lane, dest, data, sourceVolume)
          : bkNode("bk-dst bk-dst-none", BK_DEST_ICONS[lane.key], "—", "", {});
        node.style.gridColumn = "3";
        node.style.gridRow = String(row);
        host.appendChild(node);
        if (lane.key === "mirror" && dest) mirrorNodes.push(node);
        row += 1;
        return node;
      });
      const laneNode = bkLaneNode(lane, data, data.now);
      laneNode.style.gridColumn = "2";
      laneNode.style.gridRow = `${laneStart} / ${row}`;
      host.appendChild(laneNode);
      laneNodes.push(laneNode);
      destNodes.forEach((node) => {
        links.push({ from: laneNode, to: node, state: node.dataset.state || lane.state,
                     segment: "dest" });
      });
    });
    const rootNode = bkNode("bk-src", root.icon, root.label, bkShortPath(source.path), {
      volume: sourceVolume,
      title: source.path || "",
    });
    rootNode.style.gridColumn = "1";
    rootNode.style.gridRow = `${rootStart} / ${row}`;
    host.appendChild(rootNode);
    laneNodes.forEach((laneNode, index) => {
      links.push({ from: rootNode, to: laneNode, state: rootLanes[index].state,
                   segment: "lane" });
    });
  });

  host.style.setProperty("--bk-rows", String(Math.max(1, row - 1)));

  const mirror = byKey.get("mirror");
  const redraw = () => drawWires(host, links, mirrorNodes,
                                mirror ? mirror.state : "off");
  redraw();
  if (bkWireRedraw) window.removeEventListener("resize", bkWireRedraw);
  bkWireRedraw = redraw;
  window.addEventListener("resize", bkWireRedraw);
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(redraw);
  }
}

// ---- 警報 ----

// 出すのは数値・path・serverのerror文だけ。1経路1行に畳む。
function bkAlarmChips(lane, data) {
  const step = lane.schedule || {};
  const reason = lane.reason || {};
  const chips = [];

  (lane.dests || []).filter((dest) => !dest.reachable).forEach((dest) => {
    chips.push([dest.path, "bk-tag-warn bk-tag-path", `親 ${dest.parent || "?"}`]);
  });
  if (lane.last_fail && (lane.state === "failing" || lane.state === "unreachable")) {
    chips.push([lane.last_fail.message, "bk-tag-warn",
                `${lane.last_fail.label || ""} ${fmtDateTime(lane.last_fail.ts)}`]);
  }
  if (step.failures) {
    chips.push([`再試行 ${fmtNum(step.failures)}回目 · ${bkUntil(step.retry_in_seconds)}`, ""]);
  }
  if (reason.key === "unsynced") {
    const check = data.mirror_check || {};
    Object.entries(check.missing_by_dst || {}).forEach(([path, gap]) => {
      if (!gap || !gap.count) return;
      chips.push([`${bkShortPath(path)} 欠け ${fmtNum(gap.count)}件 · ${fmtBytes(gap.bytes)}`,
                  "bk-tag-warn", path]);
    });
    if (check.diverged) chips.push([`食い違い ${fmtNum(check.diverged)}件`, "bk-tag-warn"]);
    if (check.at) chips.push([`照合 ${fmtDateTimeShort(check.at)}`, ""]);
  } else if (lane.state === "degraded") {
    const run = (data.primary || {}).last_run || {};
    (run.failures || []).slice(0, 3).forEach((item) => {
      chips.push([item.path, "bk-tag-warn bk-tag-path", item.reason || ""]);
    });
  }
  if (step.pending) {
    chips.push([`未処理 ${fmtNum(step.pending)}本`, "bk-tag-warn"]);
    if (step.pending_oldest_at) {
      chips.push([`最古 ${fmtDateTimeShort(step.pending_oldest_at)}`, ""]);
    }
  }
  if ((reason.settings || []).length) {
    chips.push([reason.settings.join(" / "), ""]);
  }
  if (reason.key !== "unsynced") {
    (lane.dests || []).filter((dest) => dest.reachable).forEach((dest) => {
      const volume = (data.volumes || {})[dest.volume];
      chips.push([bkShortPath(dest.path)
        + (volume ? ` · 空き ${fmtBytes(volume.free_bytes)}` : ""), "bk-tag-path", dest.path]);
    });
  }
  if (!chips.length) chips.push([BK_STATES[lane.state].label, ""]);
  return chips.slice(0, 6);
}

function bkAlarmItem(lane, data) {
  const item = bkEl("div", "bk-alarm-item");
  item.dataset.level = bkLevelOf(lane);
  item.dataset.lane = lane.key;
  item.appendChild(bkEl("b", "bk-alarm-lane", lane.label));
  item.appendChild(bkEl("span", "bk-alarm-word", bkWordOf(lane)));
  bkAlarmChips(lane, data).forEach(([text, cls, title]) => {
    if (!text) return;
    item.appendChild(bkChip(text, cls, title));
  });
  return item;
}

function renderAlarm(data) {
  const host = document.getElementById("bk-alarm");
  if (!host) return;
  host.replaceChildren();
  const troubled = (data.lanes || []).filter((lane) => bkLevelOf(lane));
  if (!troubled.length) {
    host.hidden = true;
    host.removeAttribute("data-level");
    return;
  }
  const worst = troubled.reduce((best, lane) =>
    (BK_LEVEL_RANK[bkLevelOf(lane)] || 0) > (BK_LEVEL_RANK[bkLevelOf(best)] || 0)
      ? lane : best);
  host.hidden = false;
  host.dataset.level = bkLevelOf(worst);

  const banner = bkEl("div", "bk-alarm-banner");
  banner.innerHTML = bkIcon("alert", "bk-alarm-ic");
  banner.appendChild(bkEl("b", "bk-alarm-big", bkWordOf(worst)));
  banner.appendChild(bkEl("span", "bk-alarm-count",
    `${fmtNum(troubled.length)} / ${fmtNum((data.lanes || []).length)}`));
  host.appendChild(banner);

  const list = bkEl("div", "bk-alarm-list");
  troubled.forEach((lane) => list.appendChild(bkAlarmItem(lane, data)));
  host.appendChild(list);
}

// ---- ミラー ----

function bkMirrorHead(check) {
  if (!check.enabled) return { text: "保存先が1つ", level: "off" };
  if (!check.at) return { text: "未照合", level: "warn" };
  if (check.stale) return { text: "再同期後 未照合", level: "warn" };
  if (check.missing_items) {
    return { text: `${fmtNum(check.missing_items)}件 · ${fmtBytes(check.missing_bytes)}`,
             level: "warn" };
  }
  return { text: "一致", level: "" };
}

function renderMirror(data) {
  const host = document.getElementById("bk-mirror");
  if (!host) return;
  host.replaceChildren();
  const check = data.mirror_check || {};
  const locations = (data.relocation || {}).locations || {};
  const head = bkMirrorHead(check);

  const banner = bkEl("div", "bk-mirror-head");
  banner.dataset.level = head.level;
  banner.appendChild(bkEl("b", "bk-mirror-word", head.text));
  host.appendChild(banner);

  const dirs = data.final_dirs || [];
  const worst = dirs.reduce((max, path) => {
    const gap = (check.missing_by_dst || {})[path];
    return Math.max(max, (gap && gap.bytes) || 0);
  }, 0);
  const rows = bkEl("div", "bk-sides");
  dirs.forEach((path) => {
    const gap = (check.missing_by_dst || {})[path] || {};
    const row = bkEl("div", "bk-side");
    row.dataset.level = !check.at ? "unknown" : gap.count ? "warn" : "ok";
    row.appendChild(bkEl("span", "bk-side-dot"));
    const name = bkEl("b", "bk-side-name", bkShortPath(path));
    name.title = path;
    row.appendChild(name);
    row.appendChild(bkMeter(worst ? (gap.bytes || 0) / worst : 0, "bk-meter-gap",
      gap.count ? `欠け ${fmtNum(gap.count)}件 · ${fmtBytes(gap.bytes)}` : "欠けなし"));
    row.appendChild(bkEl("span", "bk-side-val",
      !check.at ? "—" : gap.count ? `${fmtNum(gap.count)}件 · ${fmtBytes(gap.bytes)}` : "0"));
    rows.appendChild(row);
  });
  host.appendChild(rows);

  const foot = bkEl("div", "bk-mirror-foot");
  if ((locations.final || {}).items) {
    foot.appendChild(bkChip(
      `${fmtNum(locations.final.items)}本 · ${fmtBytes(locations.final.bytes)}`,
      "", "2つに入っている録画"));
  }
  if (check.diverged) foot.appendChild(bkChip(`食い違い ${fmtNum(check.diverged)}件`, "bk-tag-warn"));
  if (check.errors) foot.appendChild(bkChip(`読めない ${fmtNum(check.errors)}件`, "bk-tag-warn"));
  if ((locations.work || {}).items) {
    foot.appendChild(bkChip(
      `未移送 ${fmtNum(locations.work.items)}本 · ${fmtBytes(locations.work.bytes)}`, "bk-tag-run"));
  }
  if ((locations.outside || {}).items) {
    foot.appendChild(bkChip(`保存先の外 ${fmtNum(locations.outside.items)}本`, "bk-tag-warn"));
  }
  host.appendChild(foot);

  const stamp = document.getElementById("bk-mirror-stamp");
  if (stamp) stamp.textContent = check.at ? fmtDateTimeShort(check.at) : "";
  const button = document.getElementById("bk-compare");
  if (button) button.disabled = !check.enabled || bkComparing;
}

let bkComparing = false;

async function compareMirror() {
  const status = document.getElementById("bk-compare-status");
  const button = document.getElementById("bk-compare");
  bkComparing = true;
  button.disabled = true;
  status.textContent = "照合中…";
  try {
    const report = await apiSend("GET", "/api/storage/mirror");
    const parts = [];
    if (report.total_items) {
      parts.push(`${fmtNum(report.total_items)}件 · ${fmtBytes(report.total_bytes)}`);
    }
    if (report.diverged_count) parts.push(`食い違い ${fmtNum(report.diverged_count)}件`);
    if ((report.errors || []).length) parts.push(`読めない ${fmtNum(report.errors.length)}件`);
    showToast(parts.length ? parts.join(" / ") : "一致", null, { title: "照合" });
  } catch (err) {
    showError(err, "照合");
  } finally {
    bkComparing = false;
    status.textContent = "";
  }
  await loadBackup();
}

// ---- DB世代 ----

function bkLocalDay(date) {
  return date.toLocaleDateString("sv-SE");
}

// ISO週(月曜始まり)。serverの ``date.isocalendar()`` と同じ規約で数える。
function bkIsoWeek(date) {
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const shift = (day.getDay() + 6) % 7;
  day.setDate(day.getDate() - shift + 3);
  const firstThursday = new Date(day.getFullYear(), 0, 4);
  const offset = (firstThursday.getDay() + 6) % 7;
  firstThursday.setDate(firstThursday.getDate() - offset + 3);
  const week = 1 + Math.round((day - firstThursday) / (7 * 86400000));
  return `${day.getFullYear()}-W${String(week).padStart(2, "0")}`;
}

function bkGenRow(caption, keys, filled, unit) {
  const row = bkEl("div", "bk-gen-row");
  row.appendChild(bkEl("span", "bk-gen-cap", caption));
  const cells = bkEl("span", "bk-gen-cells");
  keys.forEach((key, index) => {
    const cell = bkEl("span", "bk-gen-cell");
    cell.style.setProperty("--i", String(index));
    const hit = filled.get(key);
    if (hit) {
      cell.classList.add("is-on");
      cell.title = `${key} — ${hit.name}`;
    } else {
      cell.title = key;
    }
    if (index === keys.length - 1) cell.classList.add("is-now");
    cells.appendChild(cell);
  });
  row.appendChild(cells);
  row.appendChild(bkEl("span", "bk-gen-tot",
    `${fmtNum(keys.filter((key) => filled.has(key)).length)}/${fmtNum(keys.length)} ${unit}`));
  return row;
}

function renderGenerations(data) {
  const host = document.getElementById("bk-gen");
  if (!host) return;
  host.replaceChildren();
  const snap = data.snapshots || {};
  const daily = new Map((snap.daily || []).map((item) => [item.key, item]));
  const weekly = new Map((snap.weekly || []).map((item) => [item.key, item]));

  const today = new Date();
  const dayKeys = [];
  for (let back = (snap.keep_daily || 14) - 1; back >= 0; back -= 1) {
    const date = new Date(today);
    date.setDate(date.getDate() - back);
    dayKeys.push(bkLocalDay(date));
  }
  const weekKeys = [];
  for (let back = (snap.keep_weekly || 8) - 1; back >= 0; back -= 1) {
    const date = new Date(today);
    date.setDate(date.getDate() - back * 7);
    weekKeys.push(bkIsoWeek(date));
  }
  host.appendChild(bkGenRow("日次", dayKeys, daily, "日"));
  host.appendChild(bkGenRow("週次", weekKeys, weekly, "週"));

  const items = snap.items || [];
  const newest = items.length ? items[0] : null;
  const foot = bkEl("div", "bk-gen-foot");
  const total = bkEl("span", "bk-tag");
  total.innerHTML = bkIcon("archive");
  total.appendChild(document.createTextNode(`${fmtNum(items.length)}本 · ${fmtBytes(snap.bytes)}`));
  total.title = snap.dir || "";
  foot.appendChild(total);
  if (newest) {
    foot.appendChild(bkChip(fmtDateTime(newest.taken_at || newest.created_at), "", "最新"));
  }
  if ((snap.expiring || []).length) {
    foot.appendChild(bkChip(`削除予定 ${fmtNum(snap.expiring.length)}本`, "bk-tag-warn"));
  }
  host.appendChild(foot);

  const stamp = document.getElementById("bk-gen-stamp");
  if (stamp) {
    stamp.textContent = newest ? fmtDateTimeShort(newest.taken_at || newest.created_at) : "";
  }
  renderGenerationList(items);
}

const BK_LAYER_LABELS = { daily: "日次", weekly: "週次", expiring: "削除予定" };
const BK_REASON_LABELS = { manual: "手動", premigration: "移行前" };

function bkLayerLabel(item, newest) {
  if (BK_LAYER_LABELS[item.layer]) return BK_LAYER_LABELS[item.layer];
  if (BK_REASON_LABELS[item.reason]) return BK_REASON_LABELS[item.reason];
  return item === newest ? "最新" : "—";
}

function renderGenerationList(items) {
  const host = document.getElementById("bk-genlist");
  if (!host) return;
  host.replaceChildren();
  if (!items.length) return;
  const newest = items[0];
  items.forEach((item) => {
    const row = bkEl("div", "bk-genitem");
    row.dataset.layer = item.layer || "";
    row.title = [item.path || item.name, item.reason || ""].filter(Boolean).join("\n");
    row.appendChild(bkEl("span", "bk-genitem-at",
                         fmtDateTime(item.taken_at || item.created_at)));
    row.appendChild(bkEl("span", "bk-genitem-layer", bkLayerLabel(item, newest)));
    row.appendChild(bkEl("span", "bk-genitem-size", fmtBytes(item.bytes)));
    host.appendChild(row);
  });
}

// ---- DB保護 ----

const BK_DEFENSE_ICONS = {
  authorizer: "lock", guard: "scale", trash: "trash", snapshot: "archive",
};

function bkDefenseChip(icon, label, value, state, title) {
  const chip = bkEl("div", "bk-guard");
  chip.dataset.state = state;
  chip.innerHTML = bkIcon(icon);
  const body = bkEl("span", "bk-guard-body");
  body.appendChild(bkEl("b", "bk-guard-name", label));
  body.appendChild(bkEl("span", "bk-guard-val", value));
  chip.appendChild(body);
  chip.appendChild(bkEl("span", "bk-guard-dot"));
  if (title) chip.title = title;
  return chip;
}

function renderGuards(data) {
  const host = document.getElementById("bk-guards");
  if (!host) return;
  host.replaceChildren();
  const trash = data.row_trash || {};
  const snap = data.snapshots || {};
  const values = {
    authorizer: "",
    guard: `${fmtNum((data.guard || {}).tables ? data.guard.tables.length : 0)}表`,
    trash: `${fmtNum(trash.rows)}行 · ${fmtNum(trash.keep_days)}日`,
    snapshot: `${fmtNum((snap.items || []).length)}本`,
  };
  (data.defenses || []).forEach((item) => {
    host.appendChild(bkDefenseChip(
      BK_DEFENSE_ICONS[item.key] || "lock", item.label, values[item.key] || "",
      item.state, `○ ${item.covers}　✕ ${item.misses}`));
  });

  const journal = data.journal || {};
  host.appendChild(bkDefenseChip(
    "book", "Journal",
    `${fmtNum(journal.files)}日 · ${fmtBytes(journal.bytes)}`,
    journal.enabled ? "ok" : "off",
    "○ DBへ書けなかった間のevent　✕ DB fileの喪失"));

  const frozen = (data.guard || {}).frozen;
  const button = document.getElementById("bk-unfreeze");
  if (!button) return;
  button.hidden = !frozen;
  if (!frozen) return;
  button.title = (frozen.drops || [])
    .map((drop) => `${drop.table} ${fmtNum(drop.before)}→${fmtNum(drop.after)}`)
    .join(" / ") || frozen.reason || "";
}

async function unfreezePrune() {
  if (!window.confirm("古いDB世代の自動削除を再開します。")) return;
  try {
    await apiSend("POST", "/api/maintenance/unfreeze");
  } catch (err) {
    showError(err, "自動削除");
    return;
  }
  showToast("再開しました。", null, { title: "自動削除" });
  await loadBackup();
}

// ---- 取得 ----

function renderBackup(data) {
  renderAlarm(data);
  renderShield(data.lanes || []);
  renderTree(data);
  renderMirror(data);
  renderGenerations(data);
  renderGuards(data);
  const stamp = document.getElementById("bk-stamp");
  if (stamp) stamp.textContent = fmtTime(data.now);
  setListState(document.getElementById("bk-empty"), "ok");
}

async function loadBackup() {
  try {
    renderBackup(await apiSend("GET", "/api/backup/overview"));
  } catch (err) {
    // 取得に失敗した回を「異常なし」に見せない。前回の数字も残さない。
    document.getElementById("bk-map").replaceChildren();
    document.getElementById("bk-shield").replaceChildren();
    document.getElementById("bk-mirror").replaceChildren();
    document.getElementById("bk-gen").replaceChildren();
    document.getElementById("bk-genlist").replaceChildren();
    document.getElementById("bk-guards").replaceChildren();
    document.getElementById("bk-alarm").hidden = true;
    setListState(document.getElementById("bk-empty"), "failed", err);
  }
}

document.getElementById("bk-unfreeze").addEventListener("click", unfreezePrune);
document.getElementById("bk-compare").addEventListener("click", compareMirror);

loadBackup();
pollWhileVisible(loadBackup, BACKUP_POLL_MS);
connectWS(() => {});
