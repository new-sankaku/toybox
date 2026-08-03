const BUBBLE = {
  idle: "じゅんびちゅう",
  ready: "よーい…",
  listening: "はやくち！",
};

const CONFETTI_COLORS = ["#ffe066", "#5ce18a", "#7fd4ff", "#ff8fa0", "#ffffff"];
const CONFETTI_COUNT = 26;

const el = {
  stage: document.getElementById("stage"),
  face: document.getElementById("face"),
  bubble: document.getElementById("bubble"),
  streak: document.getElementById("streak"),
  title: document.getElementById("title"),
  moraRow: document.getElementById("mora-row"),
  stamp: document.getElementById("stamp"),
  stampText: document.getElementById("stamp-text"),
  stampGrade: document.getElementById("stamp-grade"),
  stampTime: document.getElementById("stamp-time"),
  confetti: document.getElementById("confetti"),
};

let moraNodes = [];

function setBubble(text) {
  if (el.bubble.textContent === text) {
    return;
  }
  el.bubble.textContent = text;
  el.bubble.style.animation = "none";
  void el.bubble.offsetWidth;
  el.bubble.style.animation = "";
}

function renderPhrase(event) {
  el.title.textContent = event.display;
  el.moraRow.replaceChildren();
  moraNodes = event.mora.map((mora) => {
    const node = document.createElement("span");
    node.className = "mora";
    node.dataset.state = "pending";
    node.textContent = mora;
    el.moraRow.appendChild(node);
    return node;
  });
  el.stamp.dataset.show = "false";
}

function applyStates(states) {
  states.forEach((state, index) => {
    const node = moraNodes[index];
    if (node && node.dataset.state !== state) {
      node.dataset.state = state;
    }
  });
}

function burst() {
  for (let index = 0; index < CONFETTI_COUNT; index += 1) {
    const piece = document.createElement("span");
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.background = CONFETTI_COLORS[index % CONFETTI_COLORS.length];
    piece.style.animationDelay = `${Math.random() * 0.35}s`;
    el.confetti.appendChild(piece);
    setTimeout(() => piece.remove(), 2200);
  }
}

function renderProgress(event) {
  applyStates(event.mora_states);
}

function renderResult(event) {
  applyStates(event.mora_states);
  el.face.dataset.mood = event.passed ? "clear" : "miss";
  setBubble(event.passed ? "いえた！" : "かんだ！");
  el.stamp.dataset.passed = String(event.passed);
  el.stampText.textContent = event.passed ? "せいかい！" : "ざんねん！";
  el.stampGrade.textContent = event.grade;
  el.stampTime.textContent = `${(event.duration_ms / 1000).toFixed(2)}びょう`;
  el.stamp.dataset.show = "true";
  el.streak.textContent = event.streak > 1 ? "🔥".repeat(Math.min(event.streak, 5)) : "";
  if (event.passed) {
    burst();
  }
}

function renderState(event) {
  el.stage.dataset.phase = event.phase;
  if (event.phase === "listening") {
    el.face.dataset.mood = "speaking";
    el.stamp.dataset.show = "false";
  } else if (event.phase !== "result") {
    el.face.dataset.mood = "idle";
    el.stamp.dataset.show = "false";
    applyStates(moraNodes.map(() => "pending"));
  }
  if (BUBBLE[event.phase]) {
    setBubble(BUBBLE[event.phase]);
  }
}

const HANDLERS = {
  phrase: renderPhrase,
  progress: renderProgress,
  result: renderResult,
  state: renderState,
};

function connect() {
  const socket = new WebSocket(`ws://${location.host}/ws`);
  socket.addEventListener("message", (message) => {
    const event = JSON.parse(message.data);
    const handler = HANDLERS[event.type];
    if (handler) {
      handler(event);
    }
  });
  socket.addEventListener("close", () => setTimeout(connect, 1000));
}

connect();
