# 04-adapters-audio-voices

## Goal
Implement synthesis adapters, artifact merging, and voice preset storage/management helpers.

## Depends on
- `03-schemas-db-contracts`
- `config.py`
- `schemas.py`

## Do
1. Add `tts_adapter.py` with a protocol/result model, `MockTtsAdapter`, and lazy `UpstreamDotsAdapter` that imports upstream only in real mode.
2. Add `audio.py` to merge chunk WAV files with `silence_ms`, write `final.txt`, `final.tts`, and `manifest.json`.
3. Add `voices.py` to discover, save, and delete voice presets from `{DOTS_VOICES_DIR}` and the `prompt_text` mapping file.
4. Enforce prompt audio suffix, voice name, root path, and no-download safety constraints.

## Verify
Run immediately after this step:
1. `uv run python -m compileall src`.
2. Targeted mock adapter + audio merge smoke: synthesize two chunks, merge WAV/text/tts/manifest, assert files and sample rate.
3. Targeted voice smoke: save/discover/delete a preset and assert `prompt_text` mapping updates.

## Notes
- Added `tts_adapter.py` with `TtsAdapter`, `SynthesisResult`, `MockTtsAdapter`, lazy `UpstreamDotsAdapter`, and `create_tts_adapter`.
- Added `audio.py` with chunk text/`.tts` writing and final WAV/text/`.tts`/manifest merge helpers.
- Added `voices.py` with voice name/suffix/root validation, prompt_text mapping helpers, discover/save/delete/get-audio helpers.
- Verification `uv run python -m compileall src` passed.
- Verification mock adapter + audio merge smoke passed: synthesized two mock chunks, merged final artifacts, asserted sample rate and files.
- Verification voice smoke passed: saved/discovered/deleted a preset and confirmed `prompt_text` mapping updates.
