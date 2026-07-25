"use strict";

// Fan台帳: 視聴者を主語に、誰がどの配信者へ幾ら投じたかを横断で見る画面。
// 対象はgiftを送った視聴者のみ。commentだけの視聴者を含めると数万人規模になり
// 一覧として使えないため、台帳の主題(誰が幾ら投じたか)に絞っている。
let ledger = null;

const elSearch = document.getElementById("fan-search");
const elSort = document.getElementById("fan-sort");
const elFilter = document.getElementById("fan-filter");

function daysSince(epochSeconds) {
  if (!epochSeconds) return null;
  return (Date.now() / 1000 - epochSeconds) / 86400;
}

// 経過日数は事実としてのみ出す。観測期間が1か月程度しかないため、「離脱」「休眠」といった
// 判定labelは付けられない(来ていないだけなのか離れたのかを分離する材料が無い)。
function elapsedText(epochSeconds) {
  const d = daysSince(epochSeconds);
  if (d === null) return "—";
  if (d < 1) return "24時間以内";
  return `${Math.floor(d)} 日前`;
}

async function loadLedger() {
  setListState(document.getElementById("fan-empty"), "loading");
  try {
    ledger = await apiSend("GET", "/api/fans");
  } catch (err) {
    // 取得失敗を0件として描くと「投げた視聴者がいない」という誤った事実の提示になる。
    ledger = null;
    document.getElementById("fan-rows").innerHTML = "";
    document.getElementById("fan-note").textContent = "";
    setListState(document.getElementById("fan-empty"), "failed", err);
    return;
  }
  renderSummary();
  renderRows();
}

function renderSummary() {
  const totalCoins = ledger.fans.reduce((sum, f) => sum + f.diamonds, 0);
  chipBar("fan-kpi", [
    ["giftを送った視聴者", fmtNum(ledger.total_gifters)],
    ["表示中", `${fmtNum(ledger.fans.length)} / ${fmtNum(ledger.eligible)} 名`],
    ["表示分のコイン計", fmtNum(totalCoins)],
    ["複数の配信者へ投げた人", `${fmtNum(ledger.multi_streamer)} 名`],
  ]);

  const parts = [];
  if (ledger.min_diamonds > 0) {
    parts.push(`通算 ${fmtNum(ledger.min_diamonds)} コイン以上の視聴者のみ`);
  }
  // 除外した身元不明分は必ず出す。黙って落とすと、台帳の合計がSessionのコイン合計と
  // 合わない理由を画面から辿れなくなる。
  const un = ledger.unidentified || {};
  if (un.gift_events) {
    parts.push(
      `身元を特定できないGift ${fmtNum(un.gift_events)} 件`
      + `（${fmtNum(un.diamonds)} コイン）は台帳から除外`,
    );
  } else {
    parts.push("身元を特定できないGiftは0件");
  }
  parts.push("集計対象はgiftを送った視聴者のみ（Commentのみの視聴者は含みません）");
  document.getElementById("fan-note").textContent = parts.join(" / ");
}

const SORTERS = {
  diamonds: (a, b) => b.diamonds - a.diamonds,
  gifts: (a, b) => b.gifts - a.gifts,
  sessions: (a, b) => b.sessions - a.sessions,
  comments: (a, b) => b.comments - a.comments,
  last_seen: (a, b) => (b.last_seen || 0) - (a.last_seen || 0),
  last_seen_asc: (a, b) => (a.last_seen || 0) - (b.last_seen || 0),
  first_seen: (a, b) => (a.first_seen || 0) - (b.first_seen || 0),
};

// 配信者別の内訳は必ず額を併記する。実測では 286,946 対 3 コインのような極端な偏りがあり、
// 「2人へ投げた」とだけ出すと両方のファンであるかのように読めてしまう。
// div(block)で組む。.u-text は .u-stack の中でしか縦積みにならず、素で使うと
// 「286,946@wicha_3111」のように行が繋がって読めなくなる。
function streamerBreakdown(fan) {
  const wrap = document.createElement("div");
  fan.streamers.forEach((s) => {
    // 投げた先の配信者名は、その配信者の画面への入口でもある。素のtextだと
    // navで選び直すしかなく、逆方向(配信者→この台帳)と同じく行き来できなかった。
    const line = document.createElement("a");
    line.className = "uid fan-streamer-link";
    line.href = `/streamers?uid=${encodeURIComponent(s.unique_id)}`;
    line.title = `@${s.unique_id} の配信者画面を開きます。`;
    line.textContent = `@${s.unique_id}: ${fmtNum(s.diamonds)}`;
    line.addEventListener("click", (e) => e.stopPropagation());
    wrap.appendChild(line);
  });
  return wrap;
}

function renderRows() {
  if (!ledger) return;
  const q = elSearch.value.trim().toLowerCase();
  let rows = ledger.fans.filter((f) => {
    if (elFilter.value === "multi" && f.streamer_count < 2) return false;
    if (!q) return true;
    return `${f.unique_id} ${f.nickname}`.toLowerCase().includes(q);
  });
  rows = rows.slice().sort(SORTERS[elSort.value] || SORTERS.diamonds);

  setListMessage(
    document.getElementById("fan-empty"),
    q || elFilter.value !== "all"
      ? "絞込に一致する視聴者がいません。"
      : "giftを送った視聴者がまだいません。",
  );
  renderTableRows(
    "fan-rows",
    "fan-empty",
    rows,
    (f, rank) => [
      String(rank),
      userCell(f, { stackId: true }),
      fmtNum(f.diamonds),
      fmtNum(f.gifts),
      fmtNum(f.sessions),
      fmtNum(f.comments),
      streamerBreakdown(f),
      f.first_seen ? fmtDateTime(f.first_seen) : "—",
      f.last_seen ? fmtDateTime(f.last_seen) : "—",
      elapsedText(f.last_seen),
    ],
    [0, 2, 3, 4, 5],
    (tr, f) => {
      tr.classList.add("row-clickable");
      tr.title = "クリックで明細を表示";
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");
      tr.addEventListener("click", () => showFanDetail(f));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          showFanDetail(f);
        }
      });
    },
  );
}

// ---- 1人ぶんの明細 ----
function closeFanDetail() {
  const modal = document.getElementById("fan-modal");
  modal.classList.add("hidden");
  focusModalClose(modal);
}

async function showFanDetail(fan) {
  const modal = document.getElementById("fan-modal");
  const message = document.getElementById("fan-modal-message");
  modal.classList.remove("hidden");
  focusModalOpen(modal, document.getElementById("fan-modal-close"));
  document.getElementById("fan-modal-title").textContent =
    `${fan.nickname} の明細`;
  message.textContent = "";
  const ident = document.getElementById("fan-modal-ident");
  ident.innerHTML = "";
  ident.appendChild(userCell(fan, { stackId: true }));
  chipBar("fan-modal-kpi", []);
  renderTableRows("fan-modal-streamers", "fan-modal-streamers-empty", [], () => [], []);
  renderTableRows("fan-modal-sessions", "fan-modal-sessions-empty", [], () => [], []);

  let profile;
  try {
    profile = await apiSend("GET", `/api/fans/${encodeURIComponent(fan.identity_key)}`);
  } catch (err) {
    message.textContent = `明細を取得できませんでした。${errorDetailText(err)}`;
    return;
  }
  if (modal.classList.contains("hidden")) return;

  const act = profile.activity || {};
  chipBar("fan-modal-kpi", [
    ["コイン", fmtNum(profile.diamonds)],
    ["Gift数", fmtNum(profile.gifts)],
    ["Comment", fmtNum(act.comment || 0)],
    ["Like", fmtNum(act.like || 0)],
    ["入室", fmtNum(act.join || 0)],
    ["Gifter Lv", fmtNum(profile.gifter_level)],
    ["初観測", profile.first_seen ? fmtDateTime(profile.first_seen) : "—"],
    ["最終観測", elapsedText(profile.last_seen)],
  ]);

  renderTableRows(
    "fan-modal-streamers",
    "fan-modal-streamers-empty",
    profile.streamers || [],
    (s) => [
      `@${s.unique_id}`,
      fmtNum(s.diamonds),
      fmtNum(s.gifts),
      fmtNum(s.sessions),
      s.first_gift ? fmtDateTime(s.first_gift) : "—",
      s.last_gift ? fmtDateTime(s.last_gift) : "—",
    ],
    [1, 2, 3],
  );

  renderTableRows(
    "fan-modal-sessions",
    "fan-modal-sessions-empty",
    profile.sessions || [],
    (s) => [
      fmtDateTime(s.started_at),
      `@${s.unique_id}`,
      fmtNum(s.diamonds),
      fmtNum(s.gifts),
      s.first_gift ? fmtDateTime(s.first_gift) : "—",
      s.last_gift ? fmtDateTime(s.last_gift) : "—",
    ],
    [2, 3],
  );
}

elSearch.addEventListener("input", renderRows);
elSort.addEventListener("change", renderRows);
elFilter.addEventListener("change", renderRows);
document.getElementById("fan-modal-close").addEventListener("click", closeFanDetail);
document.getElementById("fan-modal").addEventListener("click", (e) => {
  if (e.target.id === "fan-modal") closeFanDetail();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("fan-modal").classList.contains("hidden")) {
    closeFanDetail();
  }
});

// 収集中はgiftが増えるので、statsの更新でだけ台帳を引き直す(全走査のため毎tickは避ける)。
let reloadTimer = null;
function handleMessage(msg) {
  if (msg.type !== "stats") return;
  if (reloadTimer) return;
  reloadTimer = setTimeout(() => {
    reloadTimer = null;
    loadLedger();
  }, 15000);
}

// 他画面(配信者のGifter上位など)からの ?fan=<identity_key> でその明細を開く。
// 名前を見つけてから実績を見るのに、nav→検索box→入力→行clickの4操作が要っていた。
loadLedger().then(() => {
  const wanted = new URLSearchParams(location.search).get("fan");
  if (!wanted || !ledger) return;
  const fan = ledger.fans.find((f) => f.identity_key === wanted);
  if (fan) showFanDetail(fan);
});
connectWS(handleMessage);
