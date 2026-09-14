# Sidecar

Turns text into audio using [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS).
Started manually, not as a service -- see [ADR-0001](../docs/adr/0001-local-sidecar-for-tts.md).
Runs on native Windows Python -- see [ADR-0008](../docs/adr/0008-switch-to-vieneu-tts.md)
for why (v-tts, the previous engine, didn't).

## Setup (once)

```bash
cd sidecar
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

First run downloads the model from Hugging Face (~1 minute). No vendoring, no
platform workarounds -- `pip install vieneu` is the real, complete package.

## Pick a voice

VieNeu-TTS ships 23 named voices. Set the voice from the extension's Player
Bar or options page -- click "Fetch voices from sidecar" there while this is
running (`GET /speakers` below) to see the current names and pick one.
`DEFAULT_SPEAKER` in [server.py](server.py) (`Minh Quân`) is only the fallback
used when a request doesn't specify one.

## Run

```bash
venv\Scripts\activate
uvicorn server:app --port 8934
```

Leave this running while reading. The extension expects it at
`http://localhost:8934` by default (also configurable on the options page).

## API

- `POST /synthesize` with JSON `{"text": "...", "speaker": "Minh Quân"}`
  (speaker optional) returns a WAV file. Always normal speed -- the extension
  controls playback rate itself
  ([ADR-0003](../docs/adr/0003-sentence-chunk-contract.md)).
- `GET /speakers` returns `{"speakers": [...]}`.
