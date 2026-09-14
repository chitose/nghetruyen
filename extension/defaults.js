// Shared seed data: the built-in Adapters (from docs/adapters.md) and default
// settings. Used by content.js as a fallback when storage is empty, and by
// options.js to pre-populate the form on first open -- one copy, not two.

const DEFAULT_SIDECAR_URL = "http://localhost:8934";
const DEFAULT_SPEAKER = "Minh Quân";
const DEFAULT_RATE = 1.0;
const DEFAULT_AUTO_NEXT = true; // preserves the original auto-advance behavior
// VieNeu-TTS's built-in preset voices (ADR-0008). Static fallback shown
// before the sidecar's own /speakers responds (or if it isn't running yet)
// -- overwritten by the live list whenever that fetch succeeds.
const KNOWN_SPEAKERS = [
  "Minh Đức", "Phạm Tuyên", "Thái Sơn", "Xuân Vĩnh", "Thanh Bình", "Trúc Ly",
  "Ngọc Linh", "Đoan Trang", "Mai Anh", "Thục Đoan", "Minh Triết", "Thùy Dung",
  "Quang Sơn", "Ngọc Trân", "Mỹ Duyên", "Quỳnh Anh", "Đức Trí", "Kim Thanh",
  "Ngọc Huyền", "Adam", "Mạnh Dũng", "Minh Quân", "Anh Khôi",
];

const DEFAULT_ADAPTERS = [
  {
    hostname: "metruyenchu.co",
    contentSelector: "main article",
    stripSelectors: [],
    nextMode: "text",
    nextValue: "Chương sau",
  },
  {
    hostname: "khotruyenchu.fun",
    contentSelector: ".entry-content",
    stripSelectors: [
      ".story-navigation",
      ".reading-tools-bar",
      ".code-block",
      "script",
      'a[href*="discovernative.com"]',
      'strong[style*="height:0"]',
      'i[style*="opacity:0"]',
    ],
    nextMode: "css",
    nextValue: ".story-navigation .nav-next a",
  },
  {
    hostname: "dichtienghoa.net",
    contentSelector: ".chapter-content .chapter-body",
    stripSelectors: [],
    nextMode: "increment-url",
    nextValue: "",
  },
];

// DEFAULT_ADAPTERS is only used as the storage fallback when no `adapters`
// key exists at all -- once anything has ever been saved, storage wins
// forever, so a new built-in Adapter added here later would silently never
// reach an existing user. Called wherever storage.adapters is read, so new
// built-ins keep showing up without clobbering the user's own additions/edits.
function mergeDefaultAdapters(stored) {
  const existingHosts = new Set(stored.map((a) => a.hostname));
  const missing = DEFAULT_ADAPTERS.filter((a) => !existingHosts.has(a.hostname));
  return missing.length ? [...stored, ...missing] : stored;
}

if (typeof module !== "undefined") {
  module.exports = {
    DEFAULT_SIDECAR_URL,
    DEFAULT_SPEAKER,
    DEFAULT_RATE,
    DEFAULT_AUTO_NEXT,
    KNOWN_SPEAKERS,
    DEFAULT_ADAPTERS,
    mergeDefaultAdapters,
  };
}
