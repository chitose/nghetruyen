// Extraction, generic fallback, and the Player Bar. Chunking, playback state,
// and config all live in the Python host now -- see
// docs/adr/0009-standalone-app-replaces-extension.md. This file only does
// what needs a live DOM: reading the page, rendering the bar, and (at
// Python's command) re-querying the next-chapter link to click/navigate it.

function findNextTarget(adapter) {
  if (!adapter) return findGenericNextTarget();
  if (adapter.nextMode === "generic") return findGenericNextTarget();
  if (adapter.nextMode === "increment-url") {
    return { url: location.href.replace(/(\d+)(?!.*\d)/, (m) => String(Number(m) + 1)) };
  }
  if (adapter.nextMode === "text") {
    const links = [...document.querySelectorAll("a")];
    const el = links.find((a) => a.textContent.trim() === adapter.nextValue);
    return el ? { el } : null;
  }
  const match = document.querySelector(adapter.nextValue);
  if (!match) return null;
  return { el: match.tagName === "A" ? match : match.querySelector("a") || match };
}

function paragraphsFromInnerText(text) {
  return text.split(/\n+/).map((p) => p.replace(/\s+/g, " ").trim()).filter(Boolean);
}

function extractWithAdapter(adapter) {
  const container = document.querySelector(adapter.contentSelector);
  if (!container) return null;
  const clone = container.cloneNode(true);
  for (const sel of adapter.stripSelectors) {
    clone.querySelectorAll(sel).forEach((el) => el.remove());
  }
  clone.style.cssText = "position:fixed; left:-99999px; top:0;";
  document.body.appendChild(clone);
  const paragraphs = paragraphsFromInnerText(clone.innerText || "");
  clone.remove();
  return paragraphs;
}

const GENERIC_MIN_SCORE = 200;
const NEXT_LINK_KEYWORDS = ["chương sau", "chương tiếp", "tiếp theo", "next chapter", "next", "»", ">>"];

function scoreElement(el) {
  const text = el.innerText || "";
  let linkText = 0;
  el.querySelectorAll("a").forEach((a) => (linkText += (a.innerText || "").length));
  return text.length - linkText * 2;
}

function findGenericNextTarget() {
  const relNext = document.querySelector('a[rel="next"]');
  if (relNext) return { el: relNext };
  const links = [...document.querySelectorAll("a")];
  for (const kw of NEXT_LINK_KEYWORDS) {
    const match = links.find((a) => a.textContent.trim().toLowerCase() === kw);
    if (match) return { el: match };
  }
  return null;
}

function genericExtract() {
  if (typeof isProbablyReaderable === "function" && !isProbablyReaderable(document)) return null;
  const candidates = document.querySelectorAll("article, main, div, section");
  let best = null;
  let bestScore = GENERIC_MIN_SCORE;
  for (const el of candidates) {
    const score = scoreElement(el);
    if (score > bestScore) {
      bestScore = score;
      best = el;
    }
  }
  if (!best) return null;
  return paragraphsFromInnerText(best.innerText || "");
}

let bar, textPanel, playBtn, statusEl, rateSlider, speakerSelect, textToggleBtn, autoNextCheckbox;
let started = false;
let showText = false;
let lastParagraphText = "";
let storedNextAdapter = null;

function injectPlayerBar(defaultRate, currentSpeaker, autoNextEnabled, knownSpeakers) {
  textPanel = document.createElement("div");
  textPanel.id = "vn-tts-text-panel";
  textPanel.hidden = true;
  document.body.appendChild(textPanel);

  bar = document.createElement("div");
  bar.id = "vn-tts-bar";
  bar.innerHTML = `
    <button id="vn-tts-prev" title="Previous paragraph">⏮</button>
    <button id="vn-tts-play">▶</button>
    <button id="vn-tts-next" title="Next paragraph">⏭</button>
    <input id="vn-tts-rate" type="range" min="0.5" max="2" step="0.1" value="${defaultRate}">
    <span id="vn-tts-rate-label">${defaultRate.toFixed(1)}x</span>
    <select id="vn-tts-speaker">${knownSpeakers.map((s) => `<option${s === currentSpeaker ? " selected" : ""}>${s}</option>`).join("")}</select>
    <button id="vn-tts-text-toggle" title="Show/hide current paragraph">👁</button>
    <label id="vn-tts-autonext-label" title="Automatically move to the next chapter when this one ends">
      <input type="checkbox" id="vn-tts-autonext" ${autoNextEnabled ? "checked" : ""}> Auto-next
    </label>
    <span id="vn-tts-status"></span>
  `;
  document.body.appendChild(bar);

  playBtn = bar.querySelector("#vn-tts-play");
  statusEl = bar.querySelector("#vn-tts-status");
  rateSlider = bar.querySelector("#vn-tts-rate");
  speakerSelect = bar.querySelector("#vn-tts-speaker");
  textToggleBtn = bar.querySelector("#vn-tts-text-toggle");
  autoNextCheckbox = bar.querySelector("#vn-tts-autonext");
  const rateLabel = bar.querySelector("#vn-tts-rate-label");

  playBtn.addEventListener("click", () => {
    if (!started) {
      started = true;
      playBtn.textContent = "⏸";
      window.pywebview.api.start_playback();
    } else {
      window.pywebview.api.toggle_play();
    }
  });

  const SKIP_DEBOUNCE_MS = 400;
  let lastSkipAt = 0;
  function sendSkip(direction) {
    const now = Date.now();
    if (now - lastSkipAt < SKIP_DEBOUNCE_MS) return;
    lastSkipAt = now;
    window.pywebview.api.skip(direction);
  }
  bar.querySelector("#vn-tts-prev").addEventListener("click", () => sendSkip(-1));
  bar.querySelector("#vn-tts-next").addEventListener("click", () => sendSkip(1));

  textToggleBtn.addEventListener("click", () => {
    showText = !showText;
    textPanel.hidden = !showText;
    if (showText) textPanel.textContent = lastParagraphText;
  });

  autoNextCheckbox.addEventListener("change", () => {
    window.pywebview.api.set_auto_next(autoNextCheckbox.checked);
  });

  rateSlider.addEventListener("input", () => {
    const rate = parseFloat(rateSlider.value);
    rateLabel.textContent = `${rate.toFixed(1)}x`;
    window.pywebview.api.set_rate(rate);
  });

  speakerSelect.addEventListener("change", () => {
    window.pywebview.api.set_speaker(speakerSelect.value);
  });

  window.pywebview.api.get_speakers().then((res) => {
    if (!res || !res.ok) return;
    speakerSelect.innerHTML = res.speakers
      .map((s) => `<option value="${s}"${s === currentSpeaker ? " selected" : ""}>${s}</option>`)
      .join("");
  });
}

// --- Python -> JS pushes ---

window.__vnTtsChunkIndex = function (paragraphIndex, totalParagraphs, paragraphText) {
  statusEl.onclick = null;
  statusEl.style.cursor = "";
  statusEl.textContent = `${paragraphIndex + 1} / ${totalParagraphs}`;
  lastParagraphText = paragraphText;
  if (showText) textPanel.textContent = paragraphText;
};

window.__vnTtsPlaybackState = function (state) {
  if (state === "buffering") {
    playBtn.textContent = "⏳";
    playBtn.disabled = true;
    statusEl.textContent = `Buffering…`;
  } else {
    playBtn.disabled = false;
    playBtn.textContent = state === "playing" ? "⏸" : "▶";
  }
};

window.__vnTtsError = function (message) {
  statusEl.textContent = message;
  started = false;
};

window.__vnTtsChapterDone = function (autoNext) {
  playBtn.textContent = "▶";
  started = false;
  const target = findNextTarget(storedNextAdapter);
  if (!target) {
    statusEl.textContent = "End of novel.";
    return;
  }
  const goNext = () => {
    if (target.url) location.href = target.url;
    else target.el.click();
  };
  if (autoNext) {
    goNext();
  } else {
    statusEl.textContent = "Chapter done — click to continue ➜";
    statusEl.style.cursor = "pointer";
    statusEl.onclick = goNext;
  }
};

// --- Boot ---

(async function init() {
  const init = await window.pywebview.api.get_init_data(location.hostname);
  const adapter = init.adapter;
  const paragraphs = adapter ? extractWithAdapter(adapter) : genericExtract();
  if (!paragraphs || !paragraphs.length) return; // nothing readable here -- stay invisible

  storedNextAdapter = adapter;
  injectPlayerBar(init.defaultRate, init.speaker, init.autoNext, init.knownSpeakers);
  const result = await window.pywebview.api.chapter_ready(paragraphs, document.title);
  if (result && result.autoStart) {
    started = true;
    playBtn.textContent = "⏸";
  }
})();
