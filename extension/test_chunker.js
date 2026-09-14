const assert = require("assert");
const { splitIntoChunks, buildParagraphChunks } = require("./chunker.js");

// basic sentence split
assert.deepStrictEqual(
  splitIntoChunks("Xin chào. Tôi khỏe. Cảm ơn!"),
  ["Xin chào.", "Tôi khỏe.", "Cảm ơn!"]
);

// no terminal punctuation -- whole thing is one chunk
assert.deepStrictEqual(splitIntoChunks("không có dấu chấm"), ["không có dấu chấm"]);

// Vietnamese ellipsis and quote handling
assert.deepStrictEqual(splitIntoChunks('Anh nói "đi thôi…" rồi bước ra.'), [
  'Anh nói "đi thôi…" rồi bước ra.',
]);

// empty / whitespace-only input
assert.deepStrictEqual(splitIntoChunks("   "), []);

// long run-on sentence gets split on word boundaries under maxLen
const long = "từ ".repeat(200) + ".";
const chunks = splitIntoChunks(long, 50);
assert.ok(chunks.length > 1, "long sentence should split into multiple chunks");
for (const c of chunks) assert.ok(c.length <= 50, `chunk exceeds maxLen: "${c}"`);
assert.strictEqual(chunks.join(" ").replace(/\s+/g, " "), long.trim().replace(/\s+/g, " "));

// a single word longer than maxLen still gets emitted (hard cut, no infinite loop)
const noSpaces = "a".repeat(500) + ".";
const noSpaceChunks = splitIntoChunks(noSpaces, 100);
assert.ok(noSpaceChunks.length >= 5);

// buildParagraphChunks: sentences tagged with their source paragraph, and
// never merged or split across a paragraph boundary
const paragraphChunks = buildParagraphChunks([
  "Câu một. Câu hai.",
  "Đoạn hai chỉ có một câu.",
  "",
  "Đoạn ba.",
]);
assert.deepStrictEqual(
  paragraphChunks,
  [
    { text: "Câu một.", paragraphIndex: 0 },
    { text: "Câu hai.", paragraphIndex: 0 },
    { text: "Đoạn hai chỉ có một câu.", paragraphIndex: 1 },
    { text: "Đoạn ba.", paragraphIndex: 3 },
  ]
);
// the empty paragraph (index 2) produces no chunks but isn't skipped --
// paragraphIndex tracks the real input array position, not a compacted count
assert.strictEqual(paragraphChunks.some((c) => c.paragraphIndex === 2), false);

console.log("chunker: all checks passed");
