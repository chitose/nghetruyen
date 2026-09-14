# The Sidecar synthesizes one sentence-sized chunk per request

The Sidecar exposes a single operation: given a chunk of text, return one
complete audio buffer at normal speed. Playback speed is applied afterward via
`HTMLMediaElement.playbackRate` in the offscreen document, not re-synthesized --
it's a native platform feature (rung 4), it changes instantly instead of waiting
several seconds per adjustment, and it keeps the Sidecar's contract to one
argument. The content script splits a Chapter into
sentence-sized chunks and requests them one at a time, keeping a few ahead of
playback.

Whole-Chapter requests are not viable. A Chapter is ~8,000-11,500 characters,
roughly 35 minutes of speech; at v-tts's 3-4x realtime that is a 9-12 minute
wait before the first word. Sentence chunks synthesize in a few seconds, so
audio starts almost immediately and the buffer stays ahead indefinitely.

The contract deliberately does not stream, even though some engines can. Chunking
already gives fast first-audio, so streaming would buy nothing while ruling out
every engine that returns whole files. Every candidate considered -- v-tts, Piper,
edge-tts, Google Cloud TTS -- fits chunk-in/audio-out unchanged, which is what
makes the engine a one-line swap.
