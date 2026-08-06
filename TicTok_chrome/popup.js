const DEFAULT_CONFIG = {
  messages: '',
  intervalSec: 30,
  durationMin: 5,
};

const els = {
  messages: document.getElementById('messages'),
  interval: document.getElementById('interval'),
  duration: document.getElementById('duration'),
  start: document.getElementById('start'),
  stop: document.getElementById('stop'),
  probe: document.getElementById('probe'),
  status: document.getElementById('status'),
};

let pollTimer = null;

function setStatus(text, isError) {
  els.status.textContent = text;
  els.status.classList.toggle('error', Boolean(isError));
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function send(message) {
  const tab = await activeTab();
  if (!tab || !tab.url || !tab.url.startsWith('https://www.tiktok.com/')) {
    throw new Error('TikTokのtabを開いた状態で実行してください。');
  }
  try {
    return await chrome.tabs.sendMessage(tab.id, message);
  } catch {
    throw new Error(
      'content scriptに接続できません。拡張を読み込んだ後にTikTokのtabを再読み込みしてください。'
    );
  }
}

function describe(status) {
  if (status.lastError) return `停止: ${status.lastError}`;
  if (!status.running) {
    return status.sent > 0 ? `完了: ${status.sent}/${status.planned} 件送信` : '待機中';
  }
  const wait = status.nextAt ? Math.max(0, Math.round((status.nextAt - Date.now()) / 1000)) : 0;
  return `実行中: ${status.sent}/${status.planned} 件送信 / 次まで ${wait} 秒`;
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const response = await send({ type: 'STATUS' });
      if (!response || !response.ok) return;
      setStatus(describe(response.status), Boolean(response.status.lastError));
      if (!response.status.running) stopPolling();
    } catch {
      stopPolling();
    }
  }, 1000);
}

async function loadConfig() {
  const stored = await chrome.storage.local.get(DEFAULT_CONFIG);
  els.messages.value = stored.messages;
  els.interval.value = stored.intervalSec;
  els.duration.value = stored.durationMin;
}

async function saveConfig() {
  await chrome.storage.local.set({
    messages: els.messages.value,
    intervalSec: Number(els.interval.value),
    durationMin: Number(els.duration.value),
  });
}

els.start.addEventListener('click', async () => {
  try {
    await saveConfig();
    const response = await send({
      type: 'START',
      config: {
        messages: els.messages.value.split('\n'),
        intervalSec: Number(els.interval.value),
        durationMin: Number(els.duration.value),
      },
    });
    if (!response.ok) {
      setStatus(response.error, true);
      return;
    }
    setStatus(describe(response.status), false);
    startPolling();
  } catch (error) {
    setStatus(error.message, true);
  }
});

els.stop.addEventListener('click', async () => {
  try {
    const response = await send({ type: 'STOP' });
    stopPolling();
    setStatus(response.ok ? describe(response.status) : response.error, !response.ok);
  } catch (error) {
    setStatus(error.message, true);
  }
});

els.probe.addEventListener('click', async () => {
  try {
    const response = await send({ type: 'PROBE' });
    if (!response.ok) {
      setStatus(response.error, true);
      return;
    }
    const p = response.probe;
    setStatus(
      [
        `composer: ${p.composerSelector || '未検出'}`,
        `tag: ${p.composerTag || '-'} / contenteditable: ${p.contentEditable}`,
        `send button: ${p.sendSelector || '未検出（Enter送信に転落）'}`,
      ].join('\n'),
      !p.composerSelector
    );
  } catch (error) {
    setStatus(error.message, true);
  }
});

for (const el of [els.messages, els.interval, els.duration]) {
  el.addEventListener('change', saveConfig);
}

loadConfig();
window.addEventListener('unload', stopPolling);
