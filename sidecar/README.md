# Sidecar

Turns text into audio using [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS).
The App starts it and sets up its environment; run it by hand only when you want
to -- see [ADR-0001](../docs/adr/0001-local-sidecar-for-tts.md) and
[ADR-0016](../docs/adr/0016-app-provisions-the-sidecar-environment.md).
Runs on native Python -- Windows and Linux alike, and the
[Dockerfile](Dockerfile) is the same server on Linux
([ADR-0008](../docs/adr/0008-switch-to-vieneu-tts.md) explains the engine,
[ADR-0017](../docs/adr/0017-linux-launcher.md) the two platforms). Nothing in
this directory checks what platform it is on.

## Setup

Nothing to do by hand: on first launch the App creates `sidecar/venv` and
installs [requirements.txt](requirements.txt) into it, saying so on the Controls
strip's status line. It re-installs whenever `requirements.txt` changes, tracked
by the `venv/requirements.sha256` marker the App writes after a successful
install. Deleting `venv` is the way to force a clean reinstall.

To set it up by hand instead, or to run the server without the App:

```bash
cd sidecar
python -m venv venv
venv\Scripts\activate      # Windows
. venv/bin/activate        # Linux
pip install -r requirements.txt
```

Either way the first synthesis downloads the model from Hugging Face (~1
minute, ~1.3 GB). No vendoring, no platform workarounds --
`pip install vieneu` is the real, complete package. The App's own provisioning
uses `venv/bin/python` on Linux and `venv\Scripts\python.exe` on Windows, so
both layouts work.

## Pick a voice

VieNeu-TTS ships 23 named voices. Set the voice from the App's Player Bar
(it fetches the live list from `GET /speakers` automatically once the
Sidecar is running) or the App's Options window.
`DEFAULT_SPEAKER` in [server.py](server.py) (`Minh Quân`) is only the fallback
used when a request doesn't specify one.

## Run

```bash
venv\Scripts\python.exe -m uvicorn server:app --port 8934    # Windows
venv/bin/python -m uvicorn server:app --port 8934            # Linux
```

Use `python -m uvicorn`, not the bare `uvicorn` command -- the launcher scripts
pip writes into a venv (`venv\Scripts\uvicorn.exe`,
`venv\Scripts\pip.exe`, `venv/bin/uvicorn`, …) embed the venv's
absolute path at creation time, so they break if the venv folder is ever
moved or renamed after `pip install`. `python -m uvicorn` doesn't rely on that
launcher at all.

Leave this running while reading, or let the App spawn it for you. The App
expects it at `http://localhost:8934` by default (also configurable in the
Options window).

If you do leave one running (or use Docker below), the App notices: it probes
`/speakers` before spawning and uses the one it finds, rather than starting a
second process that could only fail to bind the port. A Sidecar the App did
not start is left running when the App closes.

When the App spawns it, no console window appears, and its output is appended
to `sidecar.log` next to this file -- as is the venv/pip output from setting
the environment up. Check that log first if the App warns that the Sidecar
never became healthy. On Windows that is also what `CREATE_NO_WINDOW` is for;
on Linux there is no console to suppress and the log file is the whole story
([ADR-0017](../docs/adr/0017-linux-launcher.md)).

## Run in Docker (alternative to the venv)

```bash
cd sidecar
docker compose up -d
```

Same server, same port, same API -- the App can't tell the difference.
The model persists in a named volume (`vieneu-cache`), so `docker compose up`
after the first run doesn't re-download it. `docker compose logs -f` to watch
startup; `docker compose down` to stop.

## API

- `POST /synthesize` with JSON `{"text": "...", "speaker": "Minh Quân"}`
  (speaker optional) returns a WAV file. Always normal speed -- the App
  controls playback rate itself
  ([ADR-0003](../docs/adr/0003-sentence-chunk-contract.md)).
- `GET /speakers` returns `{"speakers": [...]}`.
