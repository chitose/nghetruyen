// Adapter resolution (schema in docs/adapters.md), a generic best-effort
// fallback for hosts with no configured Adapter, sentence chunking, and the
// Player Bar. One file: single-user tool (Q4), no module system.
//
// Adapters live in chrome.storage.sync, configurable via the options page
// (DEFAULT_ADAPTERS in defaults.js seeds it). When no Adapter matches the
// current hostname, extraction falls back to genericExtract() below -- see
// ADR-0006 for why, and its known ceiling.

// Returns { el } to click, or { url } to navigate to, or null if there's no
// next chapter. Re-run at click time (not cached from page load) so a click
// always hits the live DOM -- the element may not have a real href (JS-only
// "next" buttons), so triggering it via .click() lets the site's own handler
// run instead of us guessing a URL.
function findNextTarget(adapter) {
  if (adapter.nextMode === "generic") return findGenericNextTarget();
  if (adapter.nextMode === "increment-url") {
    // ponytail: some SPA sites (dichtienghoa.net) have no real next-chapter
    // link at all -- the button is JS-only with no href. The URL's trailing
    // chapter id incrementing by 1 is the only signal we have; confirmed
    // against real consecutive chapters when the Adapter was written, but a
    // gap or reorder in the site's ids would silently skip a chapter. There's
    // also no "end of novel" signal in this mode -- see docs/adapters.md.
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

// `innerText` (not textContent) inserts a line break at every block-level
// element and every <br>, which is exactly the "paragraph" boundary we want
// -- and it works the same whether a site uses <p> (metruyenchu.co,
// khotruyenchu.fun) or raw text nodes split by <br> (dichtienghoa.net), so
// there's no need to special-case either markup style.
function paragraphsFromInnerText(text) {
  return text
    .split(/\n+/)
    .map((p) => p.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function extractWithAdapter(adapter) {
  const container = document.querySelector(adapter.contentSelector);
  if (!container) return null;

  const clone = container.cloneNode(true);
  for (const sel of adapter.stripSelectors) {
    clone.querySelectorAll(sel).forEach((el) => el.remove());
  }
  // innerText needs real layout to resolve line breaks, but the clone is
  // detached (kept that way so stripping junk never touches the live page).
  // Lay it out off-screen just long enough to read it, then discard.
  clone.style.cssText = "position:fixed; left:-99999px; top:0;";
  document.body.appendChild(clone);
  const paragraphs = paragraphsFromInnerText(clone.innerText || "");
  clone.remove();

  return { paragraphs, nextAdapter: adapter };
}

// --- Generic fallback, for hosts with no configured Adapter ---

const GENERIC_MIN_SCORE = 200; // below this, treat the page as "nothing to read"
const NEXT_LINK_KEYWORDS = ["chương sau", "chương tiếp", "tiếp theo", "next chapter", "next", "»", ">>"];

function scoreElement(el) {
  const text = el.innerText || "";
  let linkText = 0;
  el.querySelectorAll("a").forEach((a) => (linkText += (a.innerText || "").length));
  return text.length - linkText * 2; // penalize link-dense blocks (nav, sidebars)
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

// ponytail: naive readability heuristic -- scores article/main/div/section by
// (text length - 2x link text length) and takes the highest scorer. Will pick
// the wrong block on unusual layouts, and won't strip hidden watermark text
// the way a real Adapter's stripSelectors do (see docs/adapters.md on
// khotruyenchu.fun). A frequently-read site that misfires deserves a real
// Adapter, not a smarter heuristic here.
function genericExtract() {
  if (!isProbablyReaderable(document)) return null; // page doesn't look like an article/reader page at all
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
  const paragraphs = paragraphsFromInnerText(best.innerText || "");
  return { paragraphs, nextAdapter: { nextMode: "generic" } };
}

// splitIntoChunks comes from chunker.js, loaded first (see manifest.json).

// --- Player Bar ---

let bar, textPanel, playBtn, statusEl, rateSlider, speakerSelect, textToggleBtn, autoNextCheckbox;
let pendingChapter;
let started = false;
let showText = false; // opt-in, resets each page load -- see Q6 in the design log
let autoNext = true; // persisted; true preserves the original auto-advance behavior
let lastChunkText = "";
let lastParagraphText = "";
let chapterSessionId = null;

function injectPlayerBar(defaultRate, sidecarUrl, currentSpeaker, autoNextEnabled) {
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
    <select id="vn-tts-speaker">${KNOWN_SPEAKERS.map((s) => `<option${s === currentSpeaker ? " selected" : ""}>${s}</option>`).join("")}</select>
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
      startChapter();
    } else {
      chrome.runtime.sendMessage({ target: "background", type: "TOGGLE_PLAY" });
    }
  });

  // Debounced: offscreen.js's skip() is async (awaits the cache before it can
  // set audio.src), so rapid repeat clicks can overlap and land out of order
  // -- e.g. two chunks resolving in reverse order, leaving the wrong one
  // playing. One skip per SKIP_DEBOUNCE_MS is plenty for a button meant to
  // move by one Paragraph at a time.
  const SKIP_DEBOUNCE_MS = 400;
  let lastSkipAt = 0;
  function sendSkip(direction) {
    const now = Date.now();
    if (now - lastSkipAt < SKIP_DEBOUNCE_MS) return;
    lastSkipAt = now;
    chrome.runtime.sendMessage({ target: "background", type: "SKIP", direction });
  }
  bar.querySelector("#vn-tts-prev").addEventListener("click", () => sendSkip(-1));
  bar.querySelector("#vn-tts-next").addEventListener("click", () => sendSkip(1));

  textToggleBtn.addEventListener("click", () => {
    showText = !showText;
    textPanel.hidden = !showText;
    if (showText) textPanel.textContent = lastParagraphText;
  });

  autoNextCheckbox.addEventListener("change", () => {
    autoNext = autoNextCheckbox.checked;
    chrome.storage.sync.set({ autoNext });
  });

  rateSlider.addEventListener("input", () => {
    const rate = parseFloat(rateSlider.value);
    rateLabel.textContent = `${rate.toFixed(1)}x`;
    chrome.runtime.sendMessage({ target: "background", type: "SET_RATE", rate });
  });

  speakerSelect.addEventListener("change", () => {
    const speaker = speakerSelect.value;
    chrome.storage.sync.set({ speaker }); // sticks for future chapters/sessions
    chrome.runtime.sendMessage({ target: "background", type: "SET_SPEAKER", speaker }); // applies to this chapter's remaining chunks
  });

  // Best-effort: replace the single placeholder option with the sidecar's
  // real list. If the sidecar isn't running yet, the picker still shows the
  // stored speaker and works once you retry after starting it.
  // Fetched via background.js, not directly here -- a page-context fetch to
  // a loopback sidecar gets blocked by Private Network Access.
  chrome.runtime.sendMessage({ target: "background", type: "GET_SPEAKERS", sidecarUrl }, (res) => {
    if (!res || !res.ok) return; // keep the placeholder; sidecar not up yet
    speakerSelect.innerHTML = res.speakers
      .map((s) => `<option value="${s}"${s === currentSpeaker ? " selected" : ""}>${s}</option>`)
      .join("");
  });
}

function startChapter() {
  if (!pendingChapter || !pendingChapter.paragraphs.length) {
    statusEl.textContent = "Couldn't find chapter text on this page.";
    return;
  }
  started = true;
  playBtn.textContent = "⏸";
  statusEl.textContent = `1 / ${pendingChapter.paragraphs.length}`;
  chrome.runtime.sendMessage({
    target: "background",
    type: "PLAY_CHAPTER",
    chunks: pendingChapter.chunks, // same array the prewarm already sent -- reuses its warm cache
    paragraphs: pendingChapter.paragraphs,
    chapterSessionId,
    title: document.title, // shown in the OS/Chrome "now playing" widget
  });
  window._vnTtsNextAdapter = pendingChapter.nextAdapter;
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "RESTART_CHAPTER") {
    // The offscreen document background.js was about to talk to had been
    // closed (Chrome reclaims it once a chapter's sat paused for a while) and
    // its playback position with it -- restarting is a full recovery, just
    // from the top of the chapter instead of where it was paused.
    startChapter();
  } else if (msg.type === "CHUNK_INDEX") {
    statusEl.onclick = null;
    statusEl.style.cursor = "";
    lastChunkText = `${msg.paragraphIndex + 1} / ${msg.totalParagraphs}`;
    lastParagraphText = msg.paragraphText;
    statusEl.textContent = lastChunkText;
    if (showText) textPanel.textContent = lastParagraphText;
  } else if (msg.type === "PLAYBACK_STATE") {
    if (msg.state === "buffering") {
      playBtn.textContent = "⏳";
      playBtn.disabled = true;
      statusEl.textContent = `Buffering… ${lastChunkText}`;
    } else {
      playBtn.disabled = false;
      playBtn.textContent = msg.state === "playing" ? "⏸" : "▶";
      if (msg.state === "playing") statusEl.textContent = lastChunkText;
    }
  } else if (msg.type === "ERROR") {
    statusEl.textContent = msg.message;
    started = false; // the audio element never actually started; let Play retry cleanly
  } else if (msg.type === "CHAPTER_DONE") {
    playBtn.textContent = "▶";
    started = false;
    const nextAdapter = window._vnTtsNextAdapter;
    const goNext = () => {
      // Re-query at click time, not the stale reference from CHAPTER_DONE --
      // the DOM may have shifted during however long the chapter took to play.
      const target = findNextTarget(nextAdapter);
      if (!target) return;
      if (target.url) location.href = target.url;
      else target.el.click();
    };
    if (!findNextTarget(nextAdapter)) {
      statusEl.textContent = "End of novel.";
      return;
    }
    if (autoNext) {
      chrome.storage.session.set({ vnTtsAutoContinue: true }, goNext);
    } else {
      statusEl.textContent = "Chapter done — click to continue ➜";
      statusEl.style.cursor = "pointer";
      statusEl.onclick = goNext;
    }
  }
});

// --- Boot ---

(async function init() {
  const {
    adapters: storedAdapters,
    defaultRate = DEFAULT_RATE,
    sidecarUrl = DEFAULT_SIDECAR_URL,
    speaker = DEFAULT_SPEAKER,
    autoNext: storedAutoNext = DEFAULT_AUTO_NEXT,
  } = await chrome.storage.sync.get(["adapters", "defaultRate", "sidecarUrl", "speaker", "autoNext"]);
  const adapters = storedAdapters ? mergeDefaultAdapters(storedAdapters) : DEFAULT_ADAPTERS;
  if (storedAdapters && adapters.length !== storedAdapters.length) {
    chrome.storage.sync.set({ adapters }); // persist newly-added built-ins so options.js sees them too
  }
  const adapter = adapters.find((a) => a.hostname === location.hostname);
  pendingChapter = adapter ? extractWithAdapter(adapter) : genericExtract();
  if (!pendingChapter || !pendingChapter.paragraphs.length) return; // nothing readable here -- stay invisible

  // Computed once and reused by both the prewarm and the real PLAY_CHAPTER
  // message below, so pressing Play doesn't re-split what's already known.
  pendingChapter.chunks = buildParagraphChunks(pendingChapter.paragraphs);
  chapterSessionId = `${location.href}#${Date.now()}`;

  autoNext = storedAutoNext;
  injectPlayerBar(defaultRate, sidecarUrl, speaker, autoNext);

  // Start synthesizing the first few Chunks now, before Play is pressed --
  // the reader usually spends a few seconds looking at the page first, which
  // is otherwise wasted time the Sidecar could be filling the cache in.
  // Cost: this fires for every readable page you land on, not just ones you
  // actually listen to -- wasted synthesis on pages you never press Play on,
  // but it only costs local CPU time, not quota or money.
  chrome.runtime.sendMessage({
    target: "background",
    type: "PREWARM_CHAPTER",
    chunks: pendingChapter.chunks,
    paragraphs: pendingChapter.paragraphs,
    chapterSessionId,
  });

  chrome.storage.session.get("vnTtsAutoContinue", ({ vnTtsAutoContinue }) => {
    if (vnTtsAutoContinue) {
      chrome.storage.session.remove("vnTtsAutoContinue");
      startChapter();
    }
  });
})();
