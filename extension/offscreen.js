// Owns the <audio> element so playback survives the tab navigating to the
// next Chapter (ADR-0002). Fetches WAV audio for each Chunk from the Sidecar,
// keeping a few Chunks synthesized ahead of what's playing (Q14: three).
//
// chunks is an array of { text, paragraphIndex } (see chunker.js's
// buildParagraphChunks) -- sentence-sized for synthesis, but tagged with the
// source Paragraph so SKIP can jump by Paragraph, the coarser unit a reader
// actually navigates by.

const PREFETCH_AHEAD = 3;

let chunks = [];
let paragraphs = [];
let index = 0;
let sidecarUrl = "";
let speaker = "";
let rate = 1.0;
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

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "offscreen") return;

  if (msg.type === "PLAY_CHAPTER") {
    chunks = msg.chunks;
    paragraphs = msg.paragraphs;
    index = 0;
    sidecarUrl = msg.sidecarUrl;
    speaker = msg.speaker;
    cache.clear();
    playCurrent();
  } else if (msg.type === "TOGGLE_PLAY") {
    if (audio.paused) {
      audio.play();
      notify({ type: "PLAYBACK_STATE", state: "playing" });
    } else {
      audio.pause();
      notify({ type: "PLAYBACK_STATE", state: "paused" });
    }
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
    // Jumps by Paragraph, not Chunk -- finds the first Chunk belonging to the
    // adjacent Paragraph. paragraphIndex is non-decreasing as index increases
    // (buildParagraphChunks's construction order), so the first match is
    // always that Paragraph's start, whichever direction we're going.
    const currentParagraph = chunks[index] ? chunks[index].paragraphIndex : 0;
    const targetParagraph = currentParagraph + msg.direction;
    const target = chunks.findIndex((c) => c.paragraphIndex === targetParagraph);
    if (target === -1) return; // no such paragraph -- start/end of chapter
    index = target;
    playCurrent(); // setting audio.src interrupts whatever was playing
  }
});
