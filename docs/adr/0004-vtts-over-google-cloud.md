# v-tts locally, accepting a non-commercial licence, over free Google Cloud TTS

**Superseded by [ADR-0008](0008-switch-to-vieneu-tts.md)** -- v-tts never
actually ran (see that ADR for why); replaced by VieNeu-TTS, which is
Apache-2.0, so the non-commercial constraint described below no longer
applies. Kept for the still-valid reasoning on offline vs. Google Cloud.

Google Cloud's `vi-VN-Wavenet-*` voices would cost nothing at this reading volume
(4M characters/month free, perpetual; ~2-4 chapters/day fits inside it) and are a
documented, supported API. We chose v-tts anyway: it runs offline, needs no credit
card on a billing-enabled project, and needs no API key.

The price is a constraint invisible in the code: **v-tts is CC BY-NC 4.0**. This
project can never be published or used commercially while it depends on that
model. Acceptable because this is a personal tool that is never distributed --
but it is the reason to check the licence before reusing any of this elsewhere.

Quality was unverified at decision time; it is a listening judgement no
documentation could settle. If it disappoints, the engine is one line behind the
chunk contract in ADR-0003 -- Google WaveNet and edge-tts both drop in unchanged.
