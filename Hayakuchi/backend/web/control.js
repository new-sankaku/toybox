const PHASE_LABEL = {
  idle: "準備中",
  ready: "よーい",
  listening: "発話中",
  result: "結果",
};

const el = {
  now: document.getElementById("now"),
  overlayUrl: document.getElementById("overlay-url"),
  phraseList: document.getElementById("phrase-list"),
  next: document.getElementById("next"),
  again: document.getElementById("again"),
  giveup: document.getElementById("giveup"),
  lv: document.getElementById("lv"),
  score: document.getElementById("score"),
  current: document.getElementById("current"),
  micFill: document.getElementById("mic-fill"),
  micIcon: document.getElementById("mic-icon"),
  verdict: document.getElementById("verdict"),
  detail: document.getElementById("detail"),
  hypothesis: document.getElementById("hypothesis"),
  pass: document.getElementById("pass"),
  fail: document.getElementById("fail"),
};

const MIN_DB = -70;
const MAX_DB = 0;
let socket = null;
let activeId = null;

el.overlayUrl.textContent = `${location.origin}/overlay.html`;

function send(command) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(command));
  }
}

async function loadPhrases() {
  const phrases = await fetch("/api/phrases").then((response) => response.json());
  el.phraseList.replaceChildren();
  phrases.forEach((phrase) => {
    const item = document.createElement("li");
    item.dataset.phraseId = phrase.phrase_id;
    item.dataset.active = String(phrase.phrase_id === activeId);
    const title = document.createElement("span");
    title.className = "phrase-title";
    title.textContent = phrase.display;
    const meta = document.createElement("span");
    meta.className = "phrase-meta";
    for (let index = 0; index < phrase.difficulty; index += 1) {
      const star = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", "#ico-star");
      star.appendChild(use);
      meta.appendChild(star);
    }
    meta.append(` ${phrase.mora_count}拍`);
    item.append(title, meta);
    item.addEventListener("click", () => send({ type: "select", phrase_id: phrase.phrase_id }));
    el.phraseList.appendChild(item);
  });
}

function markActive(event) {
  activeId = event.phrase_id;
  el.current.textContent = event.display;
  el.phraseList.querySelectorAll("li").forEach((item) => {
    item.dataset.active = String(item.dataset.phraseId === activeId);
  });
}

function renderLevel(event) {
  const ratio = (event.level_db - MIN_DB) / (MAX_DB - MIN_DB);
  el.micFill.style.width = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
  el.micIcon.dataset.speaking = String(event.speaking);
}

function renderResult(event) {
  if (event.timed_out) {
    el.verdict.textContent = "時間切れ";
    el.verdict.dataset.passed = "false";
  } else if (event.abandoned) {
    el.verdict.textContent = "ギブアップ";
    delete el.verdict.dataset.passed;
  } else {
    el.verdict.textContent = event.passed ? "正解！" : "残念！";
    el.verdict.dataset.passed = String(event.passed);
  }
  el.score.textContent = `${event.score}点（自己ベスト ${event.best_score}点）`;
  const breakdown = event.breakdown || {};
  const parts = [
    `正確さ ${(event.accuracy * 100).toFixed(1)}%`,
    `${(event.duration_ms / 1000).toFixed(2)}秒`,
    `ランク ${event.grade}`,
    `連続 ${event.streak}回`,
    `制限 ${(event.limit_ms / 1000).toFixed(1)}秒`,
    `最大コンボ ${event.max_combo}`,
    `倍率 ${breakdown.multiplier ?? "-"}`,
  ];
  if (event.restarts > 0) {
    parts.push(`言い直し ${event.restarts}回`);
  }
  if (event.first_error_mora !== null && event.first_error_mora !== undefined) {
    parts.push(`${event.first_error_mora + 1}拍目で噛んだ`);
  }
  if (event.levels_gained > 0) {
    parts.push(`レベルアップ ${event.levels_gained}`);
  }
  if (event.overridden) {
    parts.push("手動で変更済み");
  }
  el.detail.textContent = parts.join(" / ");
  el.hypothesis.textContent = event.hypothesis || "-";
}

function renderProfile(event) {
  el.lv.textContent = `Lv.${event.level}  ${event.exp}/${event.exp_to_next}`;
}

const HANDLERS = {
  state: (event) => {
    el.now.textContent = PHASE_LABEL[event.phase] || event.phase;
  },
  phrase: markActive,
  level: renderLevel,
  profile: renderProfile,
  result: renderResult,
};

function connect() {
  socket = new WebSocket(`ws://${location.host}/ws`);
  socket.addEventListener("message", (message) => {
    const event = JSON.parse(message.data);
    const handler = HANDLERS[event.type];
    if (handler) {
      handler(event);
    }
  });
  socket.addEventListener("close", () => setTimeout(connect, 1000));
}

el.next.addEventListener("click", () => send({ type: "select" }));
el.again.addEventListener("click", () => send({ type: "retry" }));
el.giveup.addEventListener("click", () => send({ type: "giveup" }));
el.pass.addEventListener("click", () => send({ type: "override", passed: true }));
el.fail.addEventListener("click", () => send({ type: "override", passed: false }));

loadPhrases();
connect();
