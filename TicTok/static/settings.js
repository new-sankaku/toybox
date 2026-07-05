"use strict";

const form = document.getElementById("settings-form");
const statusEl = document.getElementById("settings-status");

function buildOptions(item) {
  const group = document.createElement("div");
  group.className = "radio-group";
  item.options.forEach((opt) => {
    const option = document.createElement("label");
    option.className = "radio-option";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = item.key;
    radio.value = opt.value;
    radio.dataset.key = item.key;
    radio.checked = String(opt.value) === String(item.value);

    const text = document.createElement("span");
    text.textContent = opt.label;

    option.append(radio, text);
    group.appendChild(option);
  });
  return group;
}

function buildNumber(item) {
  const input = document.createElement("input");
  input.type = "number";
  input.min = item.min;
  input.max = item.max;
  input.step = item.step;
  input.value = item.value;
  input.dataset.key = item.key;
  return input;
}

function buildHeader() {
  ["項目", "設定値", "説明"].forEach((text) => {
    const head = document.createElement("div");
    head.className = "s-cell s-head";
    head.textContent = text;
    form.appendChild(head);
  });
}

function buildField(item) {
  const hasOptions = Array.isArray(item.options) && item.options.length > 0;

  const label = document.createElement("div");
  label.className = "s-cell s-label";
  label.textContent = item.label;

  const control = document.createElement("div");
  control.className = "s-cell s-control";
  control.appendChild(hasOptions ? buildOptions(item) : buildNumber(item));

  const note = document.createElement("div");
  note.className = "s-cell s-note";
  note.textContent = hasOptions ? item.note : `${item.note}（${item.min}〜${item.max}）`;

  form.append(label, control, note);
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  if (!res.ok) {
    statusEl.textContent = "設定の取得に失敗しました。";
    return;
  }
  const data = await res.json();
  form.innerHTML = "";
  buildHeader();
  data.settings.forEach((item) => buildField(item));
}

document.getElementById("settings-save").addEventListener("click", async () => {
  const values = {};
  form.querySelectorAll("input[type=number][data-key]").forEach((input) => {
    values[input.dataset.key] = input.value;
  });
  form.querySelectorAll("input[type=radio][data-key]:checked").forEach((input) => {
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
