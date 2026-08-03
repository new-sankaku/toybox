const PHASE_LABEL = {
  idle: "IDLE",
  ready: "READY",
  listening: "LISTENING",
  result: "RESULT",
};

const el = {
  display: document.getElementById("display"),
  difficulty: document.getElementById("difficulty"),
  phase: document.getElementById("phase"),
  moraRow: document.getElementById("mora-row"),
  meter: document.getElementById("meter"),
  resultCard: document.getElementById("result-card"),
  verdict: document.getElementById("verdict"),
  accuracy: document.getElementById("accuracy"),
  duration: document.getElementById("duration"),
  grade: document.getElementById("grade"),
  note: document.getElementById("result-note"),
};

let moraNodes = [];

function renderPhrase(event) {
  el.display.textContent = event.display;
  el.difficulty.textContent = "★".repeat(event.difficulty);
  el.moraRow.replaceChildren();
  moraNodes = event.mora.map((mora) => {
    const node = document.createElement("span");
    node.className = "mora";
    node.dataset.state = "pending";
    node.textContent = mora;
    el.moraRow.appendChild(node);
    return node;
  });
  el.meter.style.width = "0%";
  hideResult();
}

function applyStates(states) {
  states.forEach((state, index) => {
    const node = moraNodes[index];
    if (node && node.dataset.state !== state) {
      node.dataset.state = state;
    }
  });
}

function hideResult() {
  el.resultCard.dataset.hidden = "true";
}

function renderProgress(event) {
  applyStates(event.mora_states);
  const total = moraNodes.length || 1;
  el.meter.style.width = `${Math.min(100, (event.lit_mora / total) * 100)}%`;
}

function renderResult(event) {
  applyStates(event.mora_states);
  el.meter.style.width = "100%";
  el.verdict.textContent = event.passed ? "CLEAR" : "MISS";
  el.verdict.dataset.passed = String(event.passed);
  el.accuracy.textContent = `${Math.round(event.accuracy * 100)}%`;
  el.duration.textContent = `${(event.duration_ms / 1000).toFixed(2)}s`;
  el.grade.textContent = event.grade;
  const notes = [];
  if (event.first_error_mora !== null && event.first_error_mora !== undefined) {
    notes.push(`${event.first_error_mora + 1}Mora目で崩れました`);
  }
  if (event.overridden) {
    notes.push("配信者による判定変更");
  }
  el.note.textContent = notes.join(" / ");
  el.resultCard.dataset.hidden = "false";
}

function renderState(event) {
  el.phase.textContent = PHASE_LABEL[event.phase] || event.phase;
  if (event.phase === "listening" || event.phase === "ready") {
    hideResult();
  }
  if (event.phase === "ready") {
    applyStates(moraNodes.map(() => "pending"));
    el.meter.style.width = "0%";
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
