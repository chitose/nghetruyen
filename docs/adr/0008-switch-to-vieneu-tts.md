# Switch from v-tts to VieNeu-TTS; the Sidecar returns to native Windows Python

v-tts never actually worked: its own default Hugging Face repo pointed at a
namespace that doesn't exist, `pip install git+...` never shipped the files
`v_tts.TTS._load_model()` needs, and once both were worked around, its text
normalizer turned out to depend on a Linux-only native binary -- the reason
the Sidecar moved into WSL2 at all (ADR-0007). Three upstream defects deep,
for a voice quality that was still unverified.

[VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS) replaces it: real PyPI
package (`pip install vieneu`), Apache-2.0, `Operating System :: OS
Independent` with Windows AMD64 explicitly declared, torch-free CPU path via
ONNX Runtime. Verified directly rather than trusted -- installed clean on
native Windows Python 3.13 with no vendoring, no `sys.path` tricks, no import
shims, and synthesized real audio (23 named voices, 48 kHz, ~2s to render one
sentence, RTF ~0.47 on CPU).

This makes [ADR-0007](0007-sidecar-runs-in-wsl2.md) moot -- WSL2 was v-tts's
requirement, not a property of this project. The Sidecar runs on native
Windows Python again, matching ADR-0001's original shape.
[ADR-0004](0004-vtts-over-google-cloud.md)'s reasoning for offline-over-Google
still holds; only the specific engine changes. `sidecar/venv-wsl/` and
`sidecar/vendor/` (the vendored v-tts clone) are deleted; `sidecar/venv/` is
a plain native venv again.

`server.py`'s contract is unchanged (ADR-0003: text in, WAV out, speed
applied by the extension) -- the whole point of that seam was making this
swap a rewrite of one file, not the extension.
