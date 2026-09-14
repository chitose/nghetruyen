// Sentence splitter, pulled out of content.js so it can be tested without
// Chrome APIs. See test_chunker.js.
//
// ponytail: naive -- doesn't handle real abbreviations ("T.S.", "1.5") or
// nested quotes. Boundary rule: punctuation only ends a sentence if followed
// by end-of-string or whitespace + an uppercase letter -- otherwise it's an
// ellipsis/abbreviation mid-sentence (common in dialogue: "...", rồi ...").
// Upgrade to a real tokenizer if mis-splits turn out to be frequent.
function splitIntoChunks(text, maxLen = 400) {
  const enders = /[.!?…]+["'”)]*/g;
  const boundaries = [];
  let m;
  while ((m = enders.exec(text))) {
    const end = m.index + m[0].length;
    const rest = text.slice(end);
    if (rest === "" || /^\s+["'“(]?\p{Lu}/u.test(rest)) boundaries.push(end);
  }

  const sentences = [];
  let start = 0;
  for (const b of boundaries) {
    sentences.push(text.slice(start, b));
    start = b;
  }
  if (start < text.length) sentences.push(text.slice(start));

  const chunks = [];
  for (let s of sentences) {
    s = s.trim();
    if (!s) continue;
    while (s.length > maxLen) {
      let cut = s.lastIndexOf(" ", maxLen);
      if (cut <= 0) cut = maxLen;
      chunks.push(s.slice(0, cut).trim());
      s = s.slice(cut).trim();
    }
    if (s) chunks.push(s);
  }
  return chunks;
}

// Splits each Paragraph into sentence Chunks, tagging every Chunk with which
// Paragraph it came from. Sentences never cross a Paragraph boundary --
// paragraphs are split independently, not concatenated first.
function buildParagraphChunks(paragraphs, maxLen = 400) {
  const chunks = [];
  paragraphs.forEach((paragraph, paragraphIndex) => {
    for (const text of splitIntoChunks(paragraph, maxLen)) {
      chunks.push({ text, paragraphIndex });
    }
  });
  return chunks;
}

if (typeof module !== "undefined") module.exports = { splitIntoChunks, buildParagraphChunks };
