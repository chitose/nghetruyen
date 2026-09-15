// Relays messages between the content script (in the reading tab) and the
// offscreen document (which owns the <audio> element -- see ADR-0002). Neither
// side can message the other directly.
importScripts("defaults.js");

// chrome.storage.session defaults to extension-pages-only access; content.js
// needs it for the auto-continue-to-next-chapter flag.
chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" });

// Not a plain variable: MV3 kills this service worker after ~30s idle and
// wipes module state, but offscreen.js keeps playing and sending status
// updates (CHUNK_INDEX/PLAYBACK_STATE) through a freshly-restarted worker.
// Without persisting this, those updates silently vanish -- the player bar
// freezes mid-chapter even though audio is still playing.
async function setReadingTab(tabId) {
  await chrome.storage.session.set({ readingTabId: tabId });
}
async function getReadingTab() {
  const { readingTabId } = await chrome.storage.session.get("readingTabId");
  return readingTabId ?? null;
}

// PREWARM_CHAPTER (page load) and PLAY_CHAPTER (button click) can both call
// this within moments of each other -- e.g. clicking Play right after a page
// loads, before prewarm's own call has resolved. Both would see no offscreen
// document yet and both call createDocument(), and the second throws. This
// in-flight guard makes the second caller await the first's creation instead
// of racing it.
let creatingOffscreen = null;
// Resolves true when it had to create a fresh document -- Chrome closes an
// AUDIO_PLAYBACK offscreen document on its own once playback has been paused
// for a while, silently wiping its chunks/index/cache. Callers use this to
// notice that loss and recover instead of talking to an empty document.
async function ensureOffscreenDocument() {
  if (creatingOffscreen) return creatingOffscreen;
  creatingOffscreen = (async () => {
    const existing = await chrome.runtime.getContexts({
      contextTypes: ["OFFSCREEN_DOCUMENT"],
    });
    if (existing.length > 0) return false;
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["AUDIO_PLAYBACK"],
      justification: "Plays synthesized chapter audio across chapter navigations.",
    });
    return true;
  })();
  try {
    return await creatingOffscreen;
  } finally {
    creatingOffscreen = null;
  }
}

async function getSidecarConfig() {
  const { sidecarUrl, speaker } = await chrome.storage.sync.get(["sidecarUrl", "speaker"]);
  return {
    sidecarUrl: sidecarUrl || DEFAULT_SIDECAR_URL,
    speaker: speaker || DEFAULT_SPEAKER,
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target === "background") {
    if (msg.type === "PLAY_CHAPTER" || msg.type === "PREWARM_CHAPTER") {
      setReadingTab(sender.tab.id);
      Promise.all([ensureOffscreenDocument(), getSidecarConfig()]).then(([, config]) => {
        chrome.runtime.sendMessage({ ...msg, target: "offscreen", ...config }).catch(() => {});
      });
      return;
    }
    if (msg.type === "TOGGLE_PLAY" || msg.type === "SET_RATE" || msg.type === "SET_SPEAKER" || msg.type === "SKIP") {
      // ensureOffscreenDocument() first: if the doc was ever lost (e.g. an
      // extension reload, or Chrome closing it after a paused chapter sits
      // idle) a bare sendMessage would reject with "Could not establish
      // connection. Receiving end does not exist." and silently do nothing.
      // A freshly (re)created document has no chunks/index/cache -- this
      // message would just no-op against it -- so ask the reading tab to
      // restart the chapter instead, which does carry full state.
      ensureOffscreenDocument().then((created) => {
        if (created) {
          getReadingTab().then((tabId) => {
            if (tabId != null) chrome.tabs.sendMessage(tabId, { target: "content-bar", type: "RESTART_CHAPTER" }).catch(() => {});
          });
          return;
        }
        chrome.runtime.sendMessage({ ...msg, target: "offscreen" }).catch(() => {});
      });
      return;
    }
  }

  if (msg.target === "content-bar") {
    getReadingTab().then((tabId) => {
      if (tabId != null) chrome.tabs.sendMessage(tabId, msg).catch(() => {});
    });
  }

  if (msg.target === "background" && msg.type === "GET_SPEAKERS") {
    // Runs here, not in content.js: a page-context fetch to a loopback
    // sidecar gets blocked by Private Network Access, but the service
    // worker's fetch is extension-privileged (covered by host_permissions).
    fetch(`${msg.sidecarUrl}/speakers`)
      .then((res) => res.json())
      .then((data) => sendResponse({ ok: true, speakers: data.speakers }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
});
