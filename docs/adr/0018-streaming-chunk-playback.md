# Chunks are queued into one output stream, not played one at a time

`AudioPlayer` used to call `sd.play()` once per Chunk and advance from
`sd.wait()` in a watcher thread. That put a measured **94-130 ms of silence at
every Chunk boundary** on the development machine, which is audible as a
hesitation between every few sentences.

The number was not the decode or the synthesis -- decoding a chunk takes 0.09 ms,
and the next chunk is usually already synthesized by the prefetch. It was
PortAudio's own accounting: `sd.wait()` returns as soon as the buffer has been
*consumed* by the driver, which is one output latency (~90 ms on that device)
before that audio has actually been heard, and the replacement `sd.play()` then
took another ~15 ms to spool a new stream up. VieNeu leaves only 8-10 ms of
trailing silence on a Chunk, so that hole was the entire gap between sentences.

Now one `sd.OutputStream` stays open and each Chunk is queued into it as
samples. The stream's callback moves to the next queued chunk when the current
one runs out, inside the same block if the boundary falls there, so there is
nothing to restart and nothing to wait for. Measured against the same two real
synthesized chunks, the player now adds **11 ms** at the join -- and that is
`EDGE_FADE_SECONDS` twice, a deliberate 5 ms fade at each chunk's edge.

The 5 ms fade is there because a chunk is a complete utterance whose first and
last samples are not zero by construction: butting two of them together can step
from one amplitude to another, which is a click. VieNeu's own edges are quiet
(about 0.005 of peak) so the fade is small by design, and it should not be
raised on the theory that more is smoother -- it would eat the first and last
consonant of every chunk.

Four consequences worth recording:

- **`AudioPlayer.play()` no longer restarts a running stream.** The App calls
  `load()` then `play()` once per chunk, so a `play()` that reopened the device
  would give the gap straight back. It starts the stream when there is none and
  otherwise leaves it alone; what `load()` queued is behind whatever is still
  draining.
- **A skip fades instead of cutting.** `sd.stop()` cut the audio instantly,
  which was right when a chunk was a stream of its own. The stream is now shared
  with what is queued, so `skip_to()` takes the current chunk down over
  `SKIP_FADE_SECONDS` (12 ms) and drops the queue, keeping the stream open for
  the jumped-to chunk. `stop()` -- quitting, closing a chapter -- still closes
  the stream outright.
- **`on_finished` is reported once per chunk that runs the queue dry**, from a
  thread of its own, never from the callback (the callback runs on PortAudio's
  thread and must not re-enter sounddevice). While the next chunk is still being
  synthesized the callback keeps firing against an empty queue, so "ran dry" is
  latched: without that, every silent block would advance a Chapter.
- **Speed still works by scaling the samplerate** ([ADR-0003](0003-sentence-chunk-contract.md)),
  so a rate change reopens the stream at the new rate and carries on from the
  current chunk's position. Because a chunk is written sample-for-sample, the
  stream rate is the chunk's own rate times the speed, which is what keeps the
  audible tempo right for audio the Sidecar synthesized at a fixed rate.
