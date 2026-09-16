# Reading Web

A personal Chrome extension that reads Vietnamese web novels aloud, with a local
sidecar process doing the speech synthesis.

## Language

**Chapter**:
One instalment of a novel, identified by its URL. The unit the reader navigates
and the unit position is remembered against.
_Avoid_: Page, episode, part

**Page**:
One HTTP document. Usually one Chapter, but some sites split a long Chapter
across several Pages. Only use this word when the distinction from Chapter matters.

**Adapter**:
The configured, per-hostname instruction for how to pull a Chapter's prose out
of a Page and where the next one lives. Optional -- a host with no Adapter
falls back to a best-effort generic guess (ADR-0006).
_Avoid_: Parser, scraper, extractor, provider

**Sidecar**:
The local process running alongside the App that turns text into audio. Not
part of the App; the App talks to it over HTTP on localhost.
_Avoid_: Server, backend, daemon, service

**App**:
The standalone Windows program (see ADR-0009) that embeds a Web View to
display Pages, spawns and owns the Sidecar's lifecycle, and holds all
playback state, settings, and Adapters. Replaced the Chrome extension.
_Avoid_: Extension, client, program

**Player Bar**:
The floating control surface the App overlays on a Page: playback, position,
and voice controls. The only UI the App owns.
_Avoid_: Widget, overlay, HUD, controls, toolbar

**Paragraph**:
A block of prose as the source Page renders it -- one `<p>`, or one run of
text between `<br>`s. The unit `next`/`prev` navigates, and the unit the
toggleable text panel displays.
_Avoid_: Block, section, line

**Chunk**:
A sentence-sized slice of a Paragraph. The unit the Sidecar synthesizes.
Playback advances through Chunks automatically; `next`/`prev` skips whole
Paragraphs instead.
_Avoid_: Segment, fragment, utterance, block
