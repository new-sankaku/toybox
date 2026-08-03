const PHASE_LABEL = {
  idle: "じゅんびちゅう",
  ready: "よーい",
  listening: "はなしてる",
  result: "けっか",
};

const el = {
  now: document.getElementById("now"),
  overlayUrl: document.getElementById("overlay-url"),
  phraseList: document.getElementById("phrase-list"),
  next: document.getElementById("next"),
  again: document.getElementById("again"),
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
    meta.textContent = `${"★".repeat(phrase.difficulty)} ${phrase.mora_count}おん`;
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
  el.verdict.textContent = event.passed ? "せいかい！" : "ざんねん！";
  el.verdict.dataset.passed = String(event.passed);
  const parts = [
    `せいかくさ ${(event.accuracy * 100).toFixed(1)}%`,
    `${(event.duration_ms / 1000).toFixed(2)}びょう`,
    `ランク ${event.grade}`,
    `れんぞく ${event.streak}かい`,
  ];
  if (event.first_error_mora !== null && event.first_error_mora !== undefined) {
    parts.push(`${event.first_error_mora + 1}おんめで かんだ`);
  }
  if (event.overridden) {
    parts.push("てなおし ずみ");
  }
  el.detail.textContent = parts.join(" / ");
  el.hypothesis.textContent = event.hypothesis || "-";
}

const HANDLERS = {
  state: (event) => {
    el.now.textContent = PHASE_LABEL[event.phase] || event.phase;
  },
  phrase: markActive,
  level: renderLevel,
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
el.again.addEventListener("click", () => send({ type: "select", phrase_id: activeId }));
el.pass.addEventListener("click", () => send({ type: "override", passed: true }));
el.fail.addEventListener("click", () => send({ type: "override", passed: false }));

loadPhrases();
connect();
