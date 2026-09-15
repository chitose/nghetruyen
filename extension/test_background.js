// Reproduces two silent-hang bugs in background.js's message relay, using a
// minimal mocked chrome.* running the real source in a vm context (no
// framework -- same convention as test_chunker.js).
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "background.js"), "utf8");
const DEFAULTS_SRC = fs.readFileSync(path.join(__dirname, "defaults.js"), "utf8");

// storage: shared across instances, simulating chrome.storage.session
// surviving a service-worker restart (unlike module-level `let`s).
function loadBackground(storage) {
  const sentToTabs = [];
  const offscreenSent = [];
  const state = { offscreenCreated: false };

  const chrome = {
    runtime: {
      onMessage: { addListener: (fn) => (chrome._listener = fn) },
      sendMessage: (msg) => {
        offscreenSent.push(msg);
        return Promise.resolve();
      },
      getContexts: async () => (state.offscreenCreated ? [{}] : []),
    },
    storage: {
      session: {
        setAccessLevel: async () => {},
        get: async (key) => ({ [key]: storage.session[key] }),
        set: async (obj) => Object.assign(storage.session, obj),
        remove: async (key) => delete storage.session[key],
      },
      sync: { get: async () => ({}) },
    },
    tabs: {
      sendMessage: (tabId, msg) => {
        sentToTabs.push({ tabId, msg });
        return Promise.resolve();
      },
    },
    offscreen: {
      createDocument: async () => {
        if (state.offscreenCreated) throw new Error("Only a single offscreen document may be created.");
        state.offscreenCreated = true;
      },
    },
  };

  const sandbox = { chrome, importScripts: () => {}, module: undefined };
  vm.createContext(sandbox);
  vm.runInContext(DEFAULTS_SRC, sandbox); // real importScripts("defaults.js") would inline these consts
  vm.runInContext(SRC, sandbox);

  return {
    sentToTabs,
    offscreenSent,
    state,
    dispatch: (msg, sender = {}) => chrome._listener(msg, sender, () => {}),
  };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

async function testOffscreenCreationRace() {
  const bg = loadBackground({ session: {} });
  // Prewarm fires on page load; Play fires moments later, before prewarm's
  // ensureOffscreenDocument() has resolved -- the common case of pressing
  // Play quickly on the very first chapter.
  bg.dispatch({ target: "background", type: "PREWARM_CHAPTER", chapterSessionId: "s1", chunks: [], paragraphs: [] }, { tab: { id: 1 } });
  bg.dispatch({ target: "background", type: "PLAY_CHAPTER", chapterSessionId: "s1", chunks: [], paragraphs: [] }, { tab: { id: 1 } });
  await flush();
  await flush();

  assert.strictEqual(
    bg.offscreenSent.filter((m) => m.type === "PLAY_CHAPTER").length,
    1,
    "PLAY_CHAPTER should still reach the offscreen document even when it races PREWARM_CHAPTER's offscreen-document creation"
  );
}

async function testReadingTabIdSurvivesRestart() {
  const storage = { session: {} };

  // Instance A: tab 42 starts a chapter.
  const instanceA = loadBackground(storage);
  instanceA.dispatch({ target: "background", type: "PLAY_CHAPTER", chapterSessionId: "s1", chunks: [], paragraphs: [] }, { tab: { id: 42 } });
  await flush();

  // Simulate the service worker being killed and restarted mid-playback --
  // fresh module state, same persistent storage.
  const instanceB = loadBackground(storage);
  // offscreen.js is untouched by the restart and keeps sending status
  // updates for the chapter that's still playing.
  instanceB.dispatch({ target: "content-bar", type: "PLAYBACK_STATE", state: "playing" }, {});
  await flush();

  assert.strictEqual(
    instanceB.sentToTabs.length,
    1,
    "a content-bar status update should still reach the reading tab after the service worker restarts"
  );
  assert.strictEqual(instanceB.sentToTabs[0].tabId, 42);
}

async function testToggleAfterOffscreenLostAsksForRestart() {
  const bg = loadBackground({ session: {} });
  bg.dispatch({ target: "background", type: "PLAY_CHAPTER", chapterSessionId: "s1", chunks: [], paragraphs: [] }, { tab: { id: 7 } });
  await flush();

  // Chrome closed the offscreen document on its own (paused chapter left
  // idle) -- simulate that by wiping the mock's "document exists" flag, same
  // as loadBackground's initial state, then pressing the play button.
  bg.state.offscreenCreated = false;
  bg.dispatch({ target: "background", type: "TOGGLE_PLAY" }, {});
  await flush();
  await flush();

  assert.strictEqual(
    bg.offscreenSent.some((m) => m.type === "TOGGLE_PLAY"),
    false,
    "TOGGLE_PLAY should not be forwarded to a freshly (re)created, stateless offscreen document"
  );
  assert.deepStrictEqual(
    bg.sentToTabs.map((s) => ({ tabId: s.tabId, type: s.msg.type })).filter((s) => s.type === "RESTART_CHAPTER"),
    [{ tabId: 7, type: "RESTART_CHAPTER" }],
    "losing the offscreen document should ask the reading tab to restart the chapter instead of silently doing nothing"
  );
}

(async () => {
  await testOffscreenCreationRace();
  await testReadingTabIdSurvivesRestart();
  await testToggleAfterOffscreenLostAsksForRestart();
  console.log("background: all checks passed");
})();
