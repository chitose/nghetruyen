# TTS runs in a local sidecar, not in the browser

Chrome on Windows exposes no `vi-VN` voice unless the Windows Vietnamese speech
pack is installed, and even then only the pre-neural "Microsoft An". The good
free Vietnamese voices are unreachable from page or extension JavaScript: the
Edge read-aloud endpoint needs WebSocket headers the browser API forbids and
rejects non-Edge user agents, and every cloud free tier is exhausted by a
handful of chapters (one 5000-word chapter is ~30k characters). So synthesis
happens in a process on this machine and the extension fetches audio from
localhost.

The cost is deliberate: the extension is inert unless that process is running.
Accepted because this is a single-user, load-unpacked tool, not a Web Store
product.

That process ran inside WSL2 for a while, when the engine was v-tts
([ADR-0007](0007-sidecar-runs-in-wsl2.md), superseded); the current engine
(VieNeu-TTS, [ADR-0008](0008-switch-to-vieneu-tts.md)) runs on native Windows
Python, same as this ADR originally assumed.
