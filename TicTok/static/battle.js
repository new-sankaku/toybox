"use strict";

const params = new URLSearchParams(location.search);
const monitorId = params.get("monitor");
const sessionId = params.get("session");

const titleEl = document.getElementById("battle-title");
const sumEl = document.getElementById("battle-sum");
const cardsEl = document.getElementById("battle-cards");
const emptyEl = document.getElementById("battle-empty");

function showEmpty(text) {
  emptyEl.textContent = text;
  emptyEl.classList.remove("hidden");
}

function hideEmpty() {
  emptyEl.textContent = "";
  emptyEl.classList.add("hidden");
}

function render(data) {
  const battles = data.battles || [];
  const owner = data.owner || { unique_id: data.unique_id };
  titleEl.textContent = `@${data.unique_id} · Battle 一覧`;
  sumEl.textContent = battles.length ? `このSession: ${battleSummaryText(battles)}` : "";

  cardsEl.innerHTML = "";
  if (!battles.length) {
    showEmpty("Battleはありません。");
    return;
  }
  hideEmpty();
  renderBattleCards(cardsEl, battles, owner);
}

async function load() {
  let path;
  if (monitorId) {
    path = `/api/monitors/${encodeURIComponent(monitorId)}/battles`;
  } else if (sessionId) {
    path = `/api/sessions/${encodeURIComponent(sessionId)}/battles`;
  } else {
    showEmpty("対象が指定されていません（?monitor=ID または ?session=ID）");
    return;
  }
  try {
    const res = await fetch(path);
    if (!res.ok) throw new Error("Battleの取得に失敗しました。");
    const data = await res.json();
    render(data);
  } catch (err) {
    showEmpty(err.message || "Battleの取得に失敗しました。");
  }
}

connectWS(() => {});
load();
