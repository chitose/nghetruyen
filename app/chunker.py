"""Sentence-aware text splitter for one Vietnamese Chapter.

See docs/adr/0009-standalone-app-replaces-extension.md: chunking lives entirely
in the Python host, so the injected JS no longer needs any of this.

This is a dependency-free port of do-me's LangChain-style
`RecursiveCharacterTextSplitter` -- the source is
https://gist.github.com/do-me/4c8159e5581e1b773df2e5b37182a605 -- which in turn
credits LangChain. The algorithm, kept as-is:

1. Split the text on the highest-priority Separator that occurs in it, keeping
   each Separator attached to the piece before it.
2. Merge those pieces back up into chunks of at most `chunk_size`; anything
   still longer than that is split again with the lower-priority Separators,
   recursively, down to single characters, and merged again.

A chunk is therefore sentence-aligned but usually holds several sentences, and
never spans a Paragraph: `build_paragraph_chunks` splits each Paragraph on its
own, because a chunk carries the one Paragraph index that next/prev navigates
by. See [ADR-0003](../docs/adr/0003-sentence-chunk-contract.md).

Only the Separator list and two TTS-specific defaults are ours. The Separators
are tuned for Vietnamese prose, and the first two levels mirror the gist's own
example, which passes `["\\n\\n", "\\n", ". ", " ", ""]`:

    "\\n\\s*\\n"  paragraph break
    "\\n"         line break
    _SENTENCE_END ". " "! " "?" -- see _SENTENCE_END
    "; " ":" "--" clause break
    ", "          comma followed by a space
    "\\s+"        any run of whitespace, i.e. a word boundary
    ""            single characters, the last resort

Sentence punctuation is in there because a run-on Paragraph still has to be cut
somewhere, and a comma is a far better cut than an arbitrary word.

Deliberate departures from the gist:

* `chunk_overlap` defaults to 0. The gist defaults to 200 characters of overlap
  for retrieval; overlapping text read aloud says the same words twice, and
  `split_into_chunks` never asks for any.
* A chunk's own Separators are kept (`keep_separator=True`, the gist's own
  default), so concatenating a result reproduces its input apart from
  whitespace -- no doubled spaces for the Sidecar to speak.
* `split_text` runs the top Separator even over text that would already fit in
  one chunk (`force` in `_split_text`). Without that, a short Paragraph that is
  meant to be read as several stops would be handed over whole, and
  `split_into_chunks` would return one chunk per Paragraph rather than per
  sentence boundary.
"""
import re
from typing import Callable, Iterable, List, Optional, Sequence

# A sentence only ends at "." "!" or "?" when what follows starts a new
# sentence: whitespace (usually) plus an uppercase letter. A decimal's "." sits
# between digits ("3.14"), and the first period of "T.S." has a capital after
# it, so both are guarded; an abbreviation before a proper noun ("T.S. Eliot",
# "Mr. Nam") is not, and will cut. The uppercase ranges cover Vietnamese
# diacritics plus Đ/đ. Only the punctuation and any closing quote are captured,
# because a capture is what `_split_text_with_regex` keeps with the sentence it
# belongs to -- the whitespace stays behind with the sentence that follows.
_SENTENCE_END = (
    r"((?<![^\W\d_])(?<![0-9])[.!?]+[”\"'’)\]]*)(?=[“\"'(\[]?\s+[A-ZÀ-ỴĐ])"
)
# Used as regular expressions, in priority order (see the module docstring).
DEFAULT_SEPARATORS: tuple = (
    r"\n\s*\n",
    r"\n",
    _SENTENCE_END,
    r"(?<=[;:])\s+",
    r"(?<=[—–])\s+",
    r",\s+",
    r"\s+",
    "",
)


def _split_text_with_regex(text: str, separator: str, keep_separator: bool) -> List[str]:
    """Split `text` on the regex `separator`, optionally keeping the separator
    attached to the piece it follows -- LangChain's `keep_separator=True`
    behaviour, as in the gist. The pieces concatenate back to `text` exactly."""
    if separator:
        if keep_separator:
            # `re.split` keeps whatever the pattern captures, so exactly one
            # group may capture: the Separator itself. Any group a Separator
            # declares is made non-capturing first, or it would come back as a
            # piece of its own.
            pattern = re.sub(r"\((?!\?)", "(?:", separator)
            _splits = re.split(f"({pattern})", text)
            splits = [_splits[i] + _splits[i + 1] for i in range(1, len(_splits) - 1, 2)]
            if len(_splits) % 2 == 0:
                splits += _splits[-1:]
            splits = [_splits[0]] + splits
        else:
            splits = re.split(separator, text)
    else:
        splits = list(text)
    return [s for s in splits if s != ""]


def _overlap_tail(text: str, overlap: int) -> str:
    """The last `overlap` characters of a chunk, trimmed back to a word start so
    an overlap never begins mid-word (which would make the Sidecar pronounce a
    fragment). Returns "" when no sane cut exists."""
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else ""


class RecursiveTextSplitter:
    """Split text into chunks of at most `chunk_size` characters by recursively
    looking through `separators` for one to split on (see the module
    docstring). A piece with no Separator in it is emitted as-is, over-length,
    rather than dropped.

    The gist splits this into an abstract `TextSplitter` base and this subclass;
    with nothing else deriving from the base, the merge helpers live here
    instead.
    """

    def __init__(
        self,
        chunk_size: int = 400,
        chunk_overlap: int = 0,
        length_function: Callable[[str], int] = len,
        keep_separator: bool = True,
        separators: Optional[Sequence[str]] = None,
        is_separator_regex: bool = True,
    ) -> None:
        if chunk_overlap > chunk_size:
            raise ValueError(
                f"Got a larger chunk overlap ({chunk_overlap}) than chunk size "
                f"({chunk_size}), should be smaller."
            )
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._length_function = length_function
        self._keep_separator = keep_separator
        self._separators = tuple(separators) if separators is not None else DEFAULT_SEPARATORS
        self._is_separator_regex = is_separator_regex

    # --- public --------------------------------------------------------------

    def split_text(self, text: str) -> List[str]:
        if not text or not text.strip():
            return []
        return self._split_text(text, self._separators, force=True)

    # --- gist internals ------------------------------------------------------

    def _join_docs(self, docs: List[str], separator: str) -> Optional[str]:
        text = separator.join(docs).strip()
        return None if text == "" else text

    def _merge_splits(self, splits: Iterable[str], separator: str) -> List[str]:
        """Combine the pieces into chunks of up to `chunk_size`, carrying
        `chunk_overlap` characters from the end of one chunk into the next."""
        docs: List[str] = []
        current_doc: List[str] = []
        total = 0
        for d in splits:
            _len = self._length_function(d)
            if total + _len + (len(separator) if current_doc else 0) > self._chunk_size:
                if current_doc:
                    doc = self._join_docs(current_doc, separator)
                    if doc is not None:
                        docs.append(doc)
                    while total > self._chunk_overlap or (
                        total + _len + (len(separator) if current_doc else 0) > self._chunk_size
                        and total > 0
                    ):
                        total -= self._length_function(current_doc[0]) + (
                            len(separator) if len(current_doc) > 1 else 0
                        )
                        current_doc = current_doc[1:]
            current_doc.append(d)
            total += _len + (len(separator) if len(current_doc) > 1 else 0)
        doc = self._join_docs(current_doc, separator)
        if doc is not None:
            docs.append(doc)
        return docs

    def _split_text(
        self, text: str, separators: Sequence[str], force: bool = False
    ) -> List[str]:
        """Split incoming text and return chunks.

        `force` runs the top Separator over text that would already fit in one
        chunk, so a short Paragraph is still handed to the merge level rather
        than returned whole. Below the top level it stays off: a piece that
        fits is left whole instead of being split again on a lower-priority
        Separator and merged straight back into the same text."""
        if not force and self._length_function(text) <= self._chunk_size:
            return [text]
        # Get the appropriate separator to use.
        separator = separators[-1]
        new_separators: Sequence[str] = ()
        for i, _s in enumerate(separators):
            if _s == "":
                separator = _s
                break
            if re.search(_s if self._is_separator_regex else re.escape(_s), text):
                separator = _s
                new_separators = separators[i + 1:]
                break

        pattern = separator if self._is_separator_regex else re.escape(separator)
        splits = _split_text_with_regex(text, pattern, self._keep_separator)
        # Pieces carry their own Separator, so there is nothing to join them with.
        merge_separator = "" if self._keep_separator else separator

        # Merge this level's pieces back up, then recurse into whatever is still
        # over length -- a piece that is only long because it has no Separator
        # of its own. Recursing before merging would cut a piece that the merge
        # was going to take back to a sensible size anyway.
        merged = self._merge_splits(splits, merge_separator)
        if not new_separators:
            return merged
        final_chunks: List[str] = []
        for s in merged:
            if self._length_function(s) <= self._chunk_size:
                final_chunks.append(s)
            else:
                final_chunks.extend(self._split_text(s, new_separators))
        return final_chunks


def split_text(
    text: str,
    chunk_size: int = 400,
    chunk_overlap: int = 0,
    separators: Optional[Sequence[str]] = None,
    is_separator_regex: bool = True,
) -> List[str]:
    """Module-level convenience wrapper around `RecursiveTextSplitter`."""
    return RecursiveTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
        is_separator_regex=is_separator_regex,
    ).split_text(text)


def split_into_chunks(text: str, max_len: int = 400) -> List[str]:
    """The chunks one Paragraph is read as, in order: greedy slices of up to
    `max_len` characters, each ending at the best boundary available (line
    break, sentence end, clause, then word). Returns [] for an empty or
    whitespace-only Paragraph. A chunk exceeds `max_len` only when it holds a
    single unbreakable run of characters."""
    return [
        chunk
        for chunk in (c.strip() for c in split_text(text, chunk_size=max_len))
        if chunk
    ]


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
    """Tag every chunk with the index of the Paragraph it came from, so
    next/prev can move Paragraph by Paragraph and the chrome can show the text
    being read.

    Each Paragraph is split on its own, so a chunk never spans two of them --
    otherwise it would have two source indices and could not be attributed. A
    long Paragraph yields several chunks sharing one index.
    """
    chunks = []
    paragraph_index = 0
    for paragraph in paragraphs:
        for text in split_into_chunks(paragraph, max_len):
            chunks.append({"text": text, "paragraphIndex": paragraph_index})
        if paragraph.strip():  # Only increment index for non-empty paragraphs
            paragraph_index += 1
    return chunks
