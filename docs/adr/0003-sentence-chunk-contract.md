# The Sidecar synthesizes one chunk per request

The Sidecar exposes a single operation: given a chunk of text, return one
complete audio buffer at normal speed. Playback speed is applied afterward via
`HTMLMediaElement.playbackRate` in the offscreen document, not re-synthesized --
it's a native platform feature (rung 4), it changes instantly instead of waiting
several seconds per adjustment, and it keeps the Sidecar's contract to one
argument. The App's chunker (`app/chunker.py`) slices a Chapter into chunks and
requests them one at a time, keeping a few ahead of playback.

A chunk is not one sentence. The chunker is a recursive character splitter
([the gist it is ported from](https://gist.github.com/do-me/4c8159e5581e1b773df2e5b37182a605)):
it cuts a Paragraph at the best Separator available -- line break, then sentence
end, then clause, then word -- and then packs the pieces back up to `chunk_size`
(400 characters) rather than emitting one piece each. A chunk is therefore
sentence-aligned but usually holds several sentences: cutting mid-sentence costs
prosody at every chunk boundary, while a short sentence is too little text to be
worth a synthesis round trip of its own. Chunks never span a Paragraph
(`chunker.build_paragraph_chunks` splits each one on its own), because a chunk
carries the single Paragraph index that next/prev navigates by.

Whole-Chapter requests are not viable. A Chapter is ~8,000-11,500 characters,
roughly 35 minutes of speech; at v-tts's 3-4x realtime that is a 9-12 minute
wait before the first word. A 400-character chunk synthesizes in a few seconds,
so audio starts almost immediately and the buffer stays ahead indefinitely.

The contract deliberately does not stream, even though some engines can. Chunking
already gives fast first-audio, so streaming would buy nothing while ruling out
every engine that returns whole files. Every candidate considered -- v-tts, Piper,
edge-tts, Google Cloud TTS -- fits chunk-in/audio-out unchanged, which is what
makes the engine a one-line swap.

