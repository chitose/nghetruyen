"""Sentence splitter -- ported from the retired Chrome extension's chunker.js.
See docs/adr/0009-standalone-app-replaces-extension.md: chunking moves entirely
into the Python host, so the injected JS no longer needs this at all.

ponytail: naive -- doesn't handle real abbreviations ("T.S.", "1.5") or
nested quotes. Boundary rule: punctuation only ends a sentence if followed
by end-of-string or whitespace + an uppercase letter -- otherwise it's an
ellipsis/abbreviation mid-sentence (common in dialogue). Upgrade to a real
tokenizer if mis-splits turn out to be frequent.
"""
import re

_ENDERS = re.compile("[.!?…]+[\"'" + "”)]*")
_NEXT_STARTS_SENTENCE = re.compile("^\\s+[\"'" + "“(]?[A-ZÀ-Ỵ]", re.UNICODE)


def split_into_chunks(text: str, max_len: int = 400) -> list[str]:
    boundaries = []
    for m in _ENDERS.finditer(text):
        end = m.end()
        rest = text[end:]
        if rest == "" or _NEXT_STARTS_SENTENCE.match(rest):
            boundaries.append(end)

    sentences = []
    start = 0
    for b in boundaries:
        sentences.append(text[start:b])
        start = b
    if start < len(text):
        sentences.append(text[start:])

    chunks = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        while len(s) > max_len:
            cut = s.rfind(" ", 0, max_len)
            if cut <= 0:
                cut = max_len
            chunks.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            chunks.append(s)
    return chunks


def join_short_paragraphs(paragraphs: list[str], max_words: int) -> list[str]:
    """Read Short paragraphs together with the ones that follow.

    Web novels often put a line of dialogue or a scene beat on its own
    Paragraph; playback and next/prev then stop on each one. Accumulating
    Paragraphs until they reach `max_words` words keeps whole exchanges
    together. `max_words` <= 1 leaves them alone.
    """
    if max_words <= 1:
        return [p.strip() for p in paragraphs if p and p.strip()]
    joined: list[str] = []
    pending = ""
    for paragraph in paragraphs:
        text = paragraph.strip()
        if not text:
            continue
        pending = f"{pending} {text}".strip()
        if len(pending.split()) >= max_words:
            joined.append(pending)
            pending = ""
    if pending:
        joined.append(pending)
    return joined


def build_paragraph_chunks(paragraphs: list[str], max_len: int = 400) -> list[dict]:
    chunks = []
    paragraph_index = 0
    for paragraph in paragraphs:
        for text in split_into_chunks(paragraph, max_len):
            chunks.append({"text": text, "paragraphIndex": paragraph_index})
        if paragraph.strip():  # Only increment index for non-empty paragraphs
            paragraph_index += 1
    return chunks
