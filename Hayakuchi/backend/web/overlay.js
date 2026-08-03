const BUBBLE = {
  idle: "準備中",
  ready: "よーい…",
  listening: "早口スタート！",
};

const CONFETTI_COLORS = ["#ffe066", "#5ce18a", "#7fd4ff", "#ff8fa0", "#ffffff"];
const CONFETTI_BASE = 24;
const COMBO_MIN = 3;
const COUNT_UP_MS = 700;

const el = {
  stage: document.getElementById("stage"),
  face: document.getElementById("face"),
  bubble: document.getElementById("bubble"),
  combo: document.getElementById("combo"),
  streak: document.getElementById("streak"),
  banner: document.getElementById("banner"),
  title: document.getElementById("title"),
  moraRow: document.getElementById("mora-row"),
  stamp: document.getElementById("stamp"),
  stampText: document.getElementById("stamp-text"),
  stampGrade: document.getElementById("stamp-grade"),
  stampTime: document.getElementById("stamp-time"),
  stampScore: document.getElementById("stamp-score"),
  levelTag: document.getElementById("level-tag"),
  levelFill: document.getElementById("level-fill"),
  confetti: document.getElementById("confetti"),
};

let moraNodes = [];
let lastCombo = 0;
let countUpTimer = null;

function replay(node, name) {
  node.style.animation = "none";
  void node.offsetWidth;
  node.style.animation = "";
  if (name) {
    node.dataset.show = "true";
  }
}

function setBubble(text) {
  if (el.bubble.textContent === text) {
    return;
  }
  el.bubble.textContent = text;
  replay(el.bubble);
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
  el.combo.replaceChildren();
  lastCombo = 0;
}

function applyStates(states) {
  states.forEach((state, index) => {
    const node = moraNodes[index];
    if (node && node.dataset.state !== state) {
      node.dataset.state = state;
    }
  });
}

function burst(amount) {
  for (let index = 0; index < amount; index += 1) {
    const piece = document.createElement("span");
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.background = CONFETTI_COLORS[index % CONFETTI_COLORS.length];
    piece.style.animationDelay = `${Math.random() * 0.35}s`;
    el.confetti.appendChild(piece);
    setTimeout(() => piece.remove(), 2200);
  }
}

function renderCombo(combo) {
  if (combo < COMBO_MIN) {
    el.combo.replaceChildren();
    lastCombo = combo;
    return;
  }
  el.combo.replaceChildren();
  const value = document.createElement("b");
  value.textContent = combo;
  const label = document.createElement("i");
  label.textContent = "COMBO";
  el.combo.append(value, label);
  el.combo.dataset.hot = String(combo > lastCombo);
  if (combo > lastCombo) {
    replay(el.combo);
  }
  lastCombo = combo;
}

function countUp(target) {
  clearInterval(countUpTimer);
  const started = performance.now();
  countUpTimer = setInterval(() => {
    const ratio = Math.min(1, (performance.now() - started) / COUNT_UP_MS);
    el.stampScore.textContent = Math.round(target * (1 - (1 - ratio) ** 3));
    if (ratio >= 1) {
      clearInterval(countUpTimer);
    }
  }, 30);
}

function renderProgress(event) {
  applyStates(event.mora_states);
  renderCombo(event.combo);
  if (event.hesitating) {
    el.face.dataset.mood = "hesitating";
    setBubble("あれ…？");
  } else if (event.restarted) {
    el.face.dataset.mood = "speaking";
    setBubble("言い直し！");
  } else {
    el.face.dataset.mood = "speaking";
    setBubble(BUBBLE.listening);
  }
}

function renderResult(event) {
  applyStates(event.mora_states);
  el.combo.replaceChildren();
  if (event.abandoned) {
    el.face.dataset.mood = "giveup";
    setBubble("ギブアップ…");
    el.stamp.dataset.passed = "none";
    el.stampText.textContent = "ギブアップ";
  } else {
    el.face.dataset.mood = event.passed ? "clear" : "miss";
    setBubble(event.passed ? "言えた！" : "噛んだ！");
    el.stamp.dataset.passed = String(event.passed);
    el.stampText.textContent = event.passed ? "正解！" : "残念！";
  }
  el.stampGrade.textContent = event.grade;
  el.stampTime.textContent = `${(event.duration_ms / 1000).toFixed(2)}秒`;
  el.stamp.dataset.show = "true";
  replay(el.stamp, true);
  countUp(event.score);
  el.streak.textContent = event.streak > 1 ? "🔥".repeat(Math.min(event.streak, 5)) : "";
  if (event.passed) {
    burst(CONFETTI_BASE + Math.min(event.streak, 5) * 6);
  }
  if (event.levels_gained > 0) {
    el.banner.textContent = "レベルアップ！";
    replay(el.banner, true);
    burst(CONFETTI_BASE);
  }
}

function renderProfile(event) {
  el.levelTag.textContent = `Lv.${event.level}`;
  const ratio = event.exp_to_next > 0 ? event.exp / event.exp_to_next : 0;
  el.levelFill.style.width = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
}

function renderState(event) {
  el.stage.dataset.phase = event.phase;
  if (event.phase === "listening") {
    el.face.dataset.mood = "speaking";
    el.stamp.dataset.show = "false";
  } else if (event.phase !== "result") {
    el.face.dataset.mood = "idle";
    el.stamp.dataset.show = "false";
    el.combo.replaceChildren();
    lastCombo = 0;
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
  profile: renderProfile,
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
