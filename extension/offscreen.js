// Owns the <audio> element so playback survives the tab navigating to the
// next Chapter (ADR-0002). Fetches WAV audio for each Chunk from the Sidecar,
// keeping a few Chunks synthesized ahead of what's playing (Q14: three).
//
// chunks is an array of { text, paragraphIndex } (see chunker.js's
// buildParagraphChunks) -- sentence-sized for synthesis, but tagged with the
// source Paragraph so SKIP can jump by Paragraph, the coarser unit a reader
// actually navigates by.

const PREFETCH_AHEAD = 6;

let chunks = [];
let paragraphs = [];
let index = 0;
let sidecarUrl = "";
let speaker = "";
let rate = 1.0;
let chapterSessionId = null; // identifies which chapter is currently loaded/warmed
let activeSessionId = null; // set once PLAY_CHAPTER starts it; guards prewarm from other tabs stealing state
const cache = new Map(); // index -> Promise<string> (object URL)

const audio = new Audio();
audio.preservesPitch = true;

async function fetchChunkAudio(i) {
  const res = await fetch(`${sidecarUrl}/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: chunks[i].text, speaker }),
  });
  if (!res.ok) throw new Error(`sidecar returned ${res.status}`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

function prefetch() {
  for (let i = index; i < Math.min(chunks.length, index + PREFETCH_AHEAD); i++) {
    if (!cache.has(i)) cache.set(i, fetchChunkAudio(i));
  }
}

function notify(msg) {
  chrome.runtime.sendMessage({ target: "content-bar", ...msg });
}

async function playCurrent() {
  if (index >= chunks.length) {
    activeSessionId = null; // chapter finished -- other tabs may prewarm freely again
    notify({ type: "CHAPTER_DONE" });
    return;
  }
  prefetch();
  notify({
    type: "CHUNK_INDEX",
    index,
    total: chunks.length,
    paragraphIndex: chunks[index].paragraphIndex,
    totalParagraphs: paragraphs.length,
    paragraphText: paragraphs[chunks[index].paragraphIndex],
  });
  // Usually resolves instantly (already prefetched -- Q14: three chunks
  // ahead), but genuinely waits on the sidecar for the chapter's first chunk,
  // or if synthesis ever falls behind playback.
  notify({ type: "PLAYBACK_STATE", state: "buffering" });

  let url;
  try {
    url = await cache.get(index);
  } catch (err) {
    notify({ type: "PLAYBACK_STATE", state: "paused" });
    notify({ type: "ERROR", message: `Sidecar unreachable: ${err.message}` });
    return;
  }

  audio.src = url;
  audio.playbackRate = rate;
  audio.play();
  notify({ type: "PLAYBACK_STATE", state: "playing" });
}

audio.addEventListener("ended", () => {
  index += 1;
  playCurrent();
});

function play() {
  audio.play();
  notify({ type: "PLAYBACK_STATE", state: "playing" });
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
}

function pause() {
  audio.pause();
  notify({ type: "PLAYBACK_STATE", state: "paused" });
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
}

function skip(direction) {
  // Jumps by Paragraph, not Chunk -- finds the first Chunk belonging to the
  // adjacent Paragraph. paragraphIndex is non-decreasing as index increases
  // (buildParagraphChunks's construction order), so the first match is
  // always that Paragraph's start, whichever direction we're going.
  const currentParagraph = chunks[index] ? chunks[index].paragraphIndex : 0;
  const targetParagraph = currentParagraph + direction;
  const target = chunks.findIndex((c) => c.paragraphIndex === targetParagraph);
  if (target === -1) return; // no such paragraph -- start/end of chapter
  index = target;
  playCurrent(); // setting audio.src interrupts whatever was playing
}

// Registers this offscreen document as the browser's active media session,
// so the OS/Chrome "now playing" widget and hardware media keys (keyboard,
// headset) reach it -- notably NOT the same thing as the little audio-wave
// icon Chrome shows on a tab, which is tied to a real tab's own audio output
// and can't apply to a hidden offscreen document (see ADR-0002).
if ("mediaSession" in navigator) {
  navigator.mediaSession.setActionHandler("play", play);
  navigator.mediaSession.setActionHandler("pause", pause);
  navigator.mediaSession.setActionHandler("previoustrack", () => skip(-1));
  navigator.mediaSession.setActionHandler("nexttrack", () => skip(1));
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "offscreen") return;

  if (msg.type === "PREWARM_CHAPTER") {
    // Fired at page load, before Play is pressed -- fills the cache ahead of
    // time so pressing Play (which usually comes a few seconds later, while
    // the reader's still looking at the page) often hits a warm cache instead
    // of paying the first chunk's synthesis time right when it matters.
    // Every readable tab prewarms on load, but this offscreen document is a
    // single shared player -- if another chapter is actively playing, a
    // prewarm from some other tab must not steal its chunks/cache.
    if (activeSessionId && activeSessionId !== msg.chapterSessionId) return;
    if (chapterSessionId === msg.chapterSessionId) return; // already warm
    chunks = msg.chunks;
    paragraphs = msg.paragraphs;
    index = 0;
    sidecarUrl = msg.sidecarUrl;
    speaker = msg.speaker;
    chapterSessionId = msg.chapterSessionId;
    cache.clear();
    prefetch(); // fills the cache only -- no audio element touched
  } else if (msg.type === "PLAY_CHAPTER") {
    activeSessionId = msg.chapterSessionId;
    if (chapterSessionId !== msg.chapterSessionId) {
      // Wasn't prewarmed (or the prewarm message hasn't landed yet) -- set up
      // fresh, same as before this existed.
      chunks = msg.chunks;
      paragraphs = msg.paragraphs;
      index = 0;
      sidecarUrl = msg.sidecarUrl;
      speaker = msg.speaker;
      chapterSessionId = msg.chapterSessionId;
      cache.clear();
    }
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: msg.title || "Web novel",
        artist: "Web Novel Reader",
      });
    }
    playCurrent();
  } else if (msg.type === "TOGGLE_PLAY") {
    if (audio.paused) play();
    else pause();
  } else if (msg.type === "SET_RATE") {
    rate = msg.rate;
    audio.playbackRate = rate; // applies instantly, even mid-chunk
  } else if (msg.type === "SET_SPEAKER") {
    speaker = msg.speaker;
    // Drop not-yet-played prefetched chunks (old voice) and re-fetch with the
    // new one. Leaves the currently-playing chunk alone -- the voice changes
    // starting with the next chunk, not mid-sentence.
    for (const i of [...cache.keys()]) {
      if (i > index) cache.delete(i);
    }
    prefetch();
  } else if (msg.type === "SKIP") {
    skip(msg.direction);
  }
});
