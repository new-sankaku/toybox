"use strict";

const form = document.getElementById("settings-form");
const statusEl = document.getElementById("settings-status");

function buildField(item) {
  const wrap = document.createElement("label");
  wrap.className = "setting-field";

  const label = document.createElement("span");
  label.className = "field-label";
  label.textContent = item.label;

  const input = document.createElement("input");
  input.type = "number";
  input.min = item.min;
  input.max = item.max;
  input.step = item.step;
  input.value = item.value;
  input.dataset.key = item.key;

  const note = document.createElement("span");
  note.className = "setting-note";
  note.textContent = `${item.note}（${item.min}〜${item.max}）`;

  wrap.append(label, input, note);
  return wrap;
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  if (!res.ok) {
    statusEl.textContent = "設定の取得に失敗しました。";
    return;
  }
  const data = await res.json();
  form.innerHTML = "";
  data.settings.forEach((item) => form.appendChild(buildField(item)));
}

document.getElementById("settings-save").addEventListener("click", async () => {
  const values = {};
  form.querySelectorAll("input[data-key]").forEach((input) => {
    values[input.dataset.key] = input.value;
  });
  statusEl.textContent = "保存中…";
  try {
    await apiSend("PUT", "/api/settings", values);
    statusEl.textContent = "保存しました。";
  } catch (err) {
    statusEl.textContent = err.message;
  }
});

loadSettings();
connectWS(() => {});
