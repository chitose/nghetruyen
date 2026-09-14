# The Sidecar runs inside WSL2, not native Windows Python

**Superseded by [ADR-0008](0008-switch-to-vieneu-tts.md)** -- this was v-tts's
requirement specifically (the Linux-only binary below), not a property of
this project. VieNeu-TTS runs natively on Windows; the Sidecar moved back.
Kept as the record of why WSL2 was reached for in the first place.

v-tts cannot run on native Windows Python at all. Its Vietnamese text
normalizer (`vinorm`, a hard dependency via `viphoneme`) ships a native binary
that `vinorm.TTSnorm()` invokes via `subprocess`:

```
main: ELF 64-bit LSB pie executable, x86-64, ... for GNU/Linux
```

There is no Windows build. This came after two other upstream defects in the
same package -- v-tts's own default Hugging Face repo (`v-tts/v-tts-pretrained`)
points at a namespace that doesn't exist (the real account is
`letrggghieu`), and `pip install git+...` never ships `infer.py` or `src/`,
which `v_tts.TTS._load_model()` needs (fixed by vendoring the actual repo --
see the comment in [server.py](../../sidecar/server.py)). Each was fixable;
the native Linux binary is not, short of running on Linux.

WSL2 already has a real Linux kernel, so it runs the ELF binary directly --
no Docker layer needed, no container to build or update. Only where the
Sidecar is invoked from changes:

```bash
wsl
cd /mnt/c/dev/gh/reading-web/sidecar
venv-wsl/bin/uvicorn server:app --port 8934
```

One more fix landed in `server.py` alongside this: `vinorm` (imported for the
binary above) also does `import imp`, a module Python 3.12 removed entirely --
both Windows' and WSL2's Ubuntu ship 3.12, so this hit either way. Shimmed in
`server.py` rather than patched in the installed package, since `vinorm` only
ever calls `imp.find_module()` to locate its own directory.

Verified end-to-end: `curl http://localhost:8934/speakers` and `/synthesize`
from Windows both reach the WSL2-hosted server with no extra forwarding
config -- ADR-0001's "runs on this machine" holds, it's just the machine's
Linux half.

The Windows venv created before this discovery (`sidecar/venv/`) is dead;
`sidecar/venv-wsl/` (built with WSL2's Python, gitignored the same way) is
the one that's actually used.
