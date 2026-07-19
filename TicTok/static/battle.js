"use strict";

const params = new URLSearchParams(location.search);
const monitorId = params.get("monitor");
const sessionId = params.get("session");

const titleEl = document.getElementById("battle-title");
const sumEl = document.getElementById("battle-sum");
const cardsEl = document.getElementById("battle-cards");
const emptyEl = document.getElementById("battle-empty");

function showEmpty(text) {
  setListMessage(emptyEl, text);
}

function hideEmpty() {
  setListState(emptyEl, "ok");
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
  setListState(emptyEl, "loading");
  try {
    render(await apiSend("GET", path));
  } catch (err) {
    cardsEl.innerHTML = "";
    sumEl.textContent = "";
    setListState(emptyEl, "failed", err);
  }
}

connectWS(() => {});
load();
