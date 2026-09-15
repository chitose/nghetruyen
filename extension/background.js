// Relays messages between the content script (in the reading tab) and the
// offscreen document (which owns the <audio> element -- see ADR-0002). Neither
// side can message the other directly.
importScripts("defaults.js");

// chrome.storage.session defaults to extension-pages-only access; content.js
// needs it for the auto-continue-to-next-chapter flag.
chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" });

let readingTabId = null;

async function ensureOffscreenDocument() {
  const existing = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  if (existing.length > 0) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["AUDIO_PLAYBACK"],
    justification: "Plays synthesized chapter audio across chapter navigations.",
  });
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
      readingTabId = sender.tab.id;
      Promise.all([ensureOffscreenDocument(), getSidecarConfig()]).then(([, config]) => {
        chrome.runtime.sendMessage({ ...msg, target: "offscreen", ...config });
      });
      return;
    }
    if (msg.type === "TOGGLE_PLAY" || msg.type === "SET_RATE" || msg.type === "SET_SPEAKER" || msg.type === "SKIP") {
      chrome.runtime.sendMessage({ ...msg, target: "offscreen" });
      return;
    }
  }

  if (msg.target === "content-bar" && readingTabId != null) {
    chrome.tabs.sendMessage(readingTabId, msg).catch(() => {});
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
