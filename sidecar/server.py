"""
Sidecar: turns a chunk of Vietnamese text into a WAV file, using VieNeu-TTS.

Run: uvicorn server:app --port 8934
See ../docs/adr/0001-local-sidecar-for-tts.md and
../docs/adr/0008-switch-to-vieneu-tts.md for why this exists and why VieNeu.

Speed is NOT handled here -- see docs/adr/0003-sentence-chunk-contract.md.
The extension applies playbackRate itself. This endpoint always synthesizes
at VieNeu's normal speed.

The voice is chosen by the extension's options page and sent per request; this
file's DEFAULT_SPEAKER is only the fallback when no speaker is given (e.g.
testing this server directly with curl).
"""
import io

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import soundfile as sf

DEFAULT_SPEAKER = "Minh Quân"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    # ponytail: wide open, but this only ever binds to localhost for one user.
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
)

_tts = None


@app.on_event("startup")
def load_model():
    # Load once at startup, not on first request -- otherwise the first
    # Chunk of the first Chapter eats the model-load time too.
    global _tts
    from vieneu import Vieneu

    _tts = Vieneu(mode="v3nano")


class SynthesizeRequest(BaseModel):
    text: str
    speaker: str | None = None


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest):
    if not req.text.strip():
        raise HTTPException(400, "empty text")

    audio = _tts.infer(req.text, voice=req.speaker or DEFAULT_SPEAKER)

    buf = io.BytesIO()
    sf.write(buf, audio, _tts.sample_rate, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav")


@app.get("/speakers")
def speakers():
    # Backs the options page's "Fetch voices from sidecar" button.
    return {"speakers": [voice_id for _, voice_id in _tts.list_preset_voices()]}
