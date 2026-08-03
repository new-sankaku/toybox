const el = {
  phase: document.getElementById("phase"),
  overlayUrl: document.getElementById("overlay-url"),
  phraseList: document.getElementById("phrase-list"),
  random: document.getElementById("random"),
  micFill: document.getElementById("mic-fill"),
  micLabel: document.getElementById("mic-label"),
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
    meta.className = "mono";
    meta.textContent = `★${phrase.difficulty} / ${phrase.mora_count}拍`;
    item.append(title, meta);
    item.addEventListener("click", () => send({ type: "select", phrase_id: phrase.phrase_id }));
    el.phraseList.appendChild(item);
  });
}

function markActive(phraseId) {
  activeId = phraseId;
  el.phraseList.querySelectorAll("li").forEach((item) => {
    item.dataset.active = String(item.dataset.phraseId === phraseId);
  });
}

function renderLevel(event) {
  const ratio = (event.level_db - MIN_DB) / (MAX_DB - MIN_DB);
  el.micFill.style.width = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
  el.micLabel.textContent = `${event.level_db.toFixed(0)}dB / floor ${event.floor_db.toFixed(0)}dB${event.speaking ? " / speaking" : ""}`;
}

function renderResult(event) {
  el.verdict.textContent = event.passed ? "CLEAR" : "MISS";
  el.verdict.dataset.passed = String(event.passed);
  const parts = [
    `accuracy ${(event.accuracy * 100).toFixed(1)}%`,
    `${(event.duration_ms / 1000).toFixed(2)}s`,
    `grade ${event.grade}`,
  ];
  if (event.first_error_mora !== null && event.first_error_mora !== undefined) {
    parts.push(`初回誤り ${event.first_error_mora + 1}拍目`);
  }
  if (event.overridden) {
    parts.push("手動変更済み");
  }
  el.detail.textContent = parts.join(" / ");
  el.hypothesis.textContent = event.hypothesis || "-";
}

const HANDLERS = {
  state: (event) => {
    el.phase.textContent = event.phase.toUpperCase();
  },
  phrase: (event) => markActive(event.phrase_id),
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

el.random.addEventListener("click", () => send({ type: "select" }));
el.pass.addEventListener("click", () => send({ type: "override", passed: true }));
el.fail.addEventListener("click", () => send({ type: "override", passed: false }));

loadPhrases();
connect();
