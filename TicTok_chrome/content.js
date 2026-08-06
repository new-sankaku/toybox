const COMPOSER_SELECTORS = [
  'div[data-e2e="comment-text-input"]',
  'div[data-e2e="comment-input"]',
  '[class*="DivCommentInput"] div[contenteditable="true"]',
  '[class*="comment"] div[contenteditable="true"]',
  'div[contenteditable="true"][role="textbox"]',
  'div[contenteditable="plaintext-only"]',
  'div[contenteditable="true"]',
  'input[data-e2e*="comment"]',
  'textarea[data-e2e*="comment"]',
];

const SEND_SELECTORS = [
  '[data-e2e="comment-post"]',
  '[data-e2e*="comment-submit"]',
  'button[type="submit"]',
  '[class*="Send"] button',
  'button[class*="Send"]',
];

const state = {
  running: false,
  sent: 0,
  planned: 0,
  index: 0,
  lastError: null,
  lastSentAt: null,
  nextAt: null,
  config: null,
  timer: null,
};

function isVisible(el) {
  if (!el || !el.isConnected) return false;
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  const style = getComputedStyle(el);
  return style.visibility !== 'hidden' && style.display !== 'none';
}

function resolveComposer() {
  for (const selector of COMPOSER_SELECTORS) {
    for (const el of document.querySelectorAll(selector)) {
      if (isVisible(el)) return { el, selector };
    }
  }
  return { el: null, selector: null };
}

function resolveSendButton(composer) {
  let scope = composer;
  for (let depth = 0; depth < 6 && scope && scope.parentElement; depth += 1) {
    scope = scope.parentElement;
    for (const selector of SEND_SELECTORS) {
      for (const el of scope.querySelectorAll(selector)) {
        if (isVisible(el) && !el.disabled) return { el, selector };
      }
    }
  }
  return { el: null, selector: null };
}

function readText(el) {
  if (el.isContentEditable) return el.textContent || '';
  return el.value || '';
}

function writeText(el, text) {
  el.focus();

  if (el.isContentEditable) {
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand('insertText', false, text);
    return;
  }

  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

function pressEnter(el) {
  for (const type of ['keydown', 'keypress', 'keyup']) {
    el.dispatchEvent(
      new KeyboardEvent(type, {
        key: 'Enter',
        code: 'Enter',
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true,
      })
    );
  }
}

function postOnce(text) {
  const { el, selector } = resolveComposer();
  if (!el) throw new Error('comment欄が見つかりません（selector全滅）');

  writeText(el, text);

  const written = readText(el);
  if (!written.includes(text)) {
    throw new Error(
      `入力が反映されません（selector=${selector} / 現在値="${written.slice(0, 40)}"）`
    );
  }

  const send = resolveSendButton(el);
  if (send.el) {
    send.el.click();
  } else {
    pressEnter(el);
  }

  const remained = readText(el);
  return {
    selector,
    sendSelector: send.selector,
    cleared: remained.trim() === '',
  };
}

function stop(reason) {
  if (state.timer !== null) {
    clearTimeout(state.timer);
    state.timer = null;
  }
  state.running = false;
  state.nextAt = null;
  if (reason) state.lastError = reason;
}

function tick() {
  if (!state.running) return;

  const messages = state.config.messages;
  const text = messages[state.index % messages.length];
  state.index += 1;

  try {
    const result = postOnce(text);
    state.sent += 1;
    state.lastSentAt = Date.now();
    state.lastError = result.cleared
      ? null
      : '送信後もcomment欄が空になりません。送信が成立していない可能性があります。';
  } catch (error) {
    stop(error.message);
    return;
  }

  if (state.sent >= state.planned) {
    stop(null);
    return;
  }

  state.nextAt = Date.now() + state.config.intervalMs;
  state.timer = setTimeout(tick, state.config.intervalMs);
}

function start(config) {
  stop(null);

  const messages = config.messages.filter((line) => line.trim() !== '');
  if (messages.length === 0) throw new Error('投稿する文面が空です');

  const intervalMs = Math.max(1000, Math.round(config.intervalSec * 1000));
  const planned = Math.max(1, Math.floor((config.durationMin * 60 * 1000) / intervalMs));

  state.config = { messages, intervalMs };
  state.running = true;
  state.sent = 0;
  state.index = 0;
  state.planned = planned;
  state.lastError = null;
  state.lastSentAt = null;

  tick();
  return { planned };
}

function probe() {
  const composer = resolveComposer();
  const send = composer.el ? resolveSendButton(composer.el) : { selector: null };
  return {
    url: location.href,
    composerSelector: composer.selector,
    composerTag: composer.el ? composer.el.tagName.toLowerCase() : null,
    contentEditable: composer.el ? composer.el.isContentEditable : null,
    sendSelector: send.selector,
  };
}

function snapshot() {
  return {
    running: state.running,
    sent: state.sent,
    planned: state.planned,
    lastError: state.lastError,
    lastSentAt: state.lastSentAt,
    nextAt: state.nextAt,
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  try {
    if (message.type === 'START') {
      const started = start(message.config);
      sendResponse({ ok: true, started, status: snapshot() });
    } else if (message.type === 'STOP') {
      stop(null);
      sendResponse({ ok: true, status: snapshot() });
    } else if (message.type === 'STATUS') {
      sendResponse({ ok: true, status: snapshot() });
    } else if (message.type === 'PROBE') {
      sendResponse({ ok: true, probe: probe() });
    } else {
      sendResponse({ ok: false, error: `unknown message: ${message.type}` });
    }
  } catch (error) {
    sendResponse({ ok: false, error: error.message });
  }
  return false;
});

window.addEventListener('pagehide', () => stop(null));
