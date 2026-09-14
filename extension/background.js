// Relays messages between the content script (in the reading tab) and the
// offscreen document (which owns the <audio> element -- see ADR-0002). Neither
// side can message the other directly.
importScripts("defaults.js");

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
    if (msg.type === "PLAY_CHAPTER") {
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
});
