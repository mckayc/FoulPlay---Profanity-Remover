"""Out-of-process ML worker.

Runs under whichever interpreter core/runtime.py resolves for ML work --
the dev venv, or the managed per-user runtime once frozen. Deliberately
self-contained (stdlib + faster-whisper only, no imports from the rest of
this app's package) because the runtime interpreter that executes this
script does not have the rest of the app's source importable: in dev mode
it happens to be the same venv, but once frozen it's a separate embeddable
Python that only ever gets this one file copied alongside it (see
packaging/build_runtime_template.py and core/runtime.get_ml_worker_script).

Usage:
    <runtime_python> ml_worker.py transcribe --args-json <path> --out-json <path>

Progress updates are printed to stdout as JSON lines (one per completed
segment); the final result (or an {"error": ...} on failure) is written to
--out-json, not stdout, so the two streams don't get mixed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Force huggingface_hub to copy model files into the snapshot directory
# instead of symlinking to a shared blob store. Every observed
# "Unable to open file 'model.bin'" failure followed a *freshly created*
# symlink being opened immediately afterward -- consistent with Windows
# security software (Defender/SmartScreen behavior monitoring) scrutinizing
# file access from this unsigned app's spawned processes around a new
# reparse point into a huge binary. A real file copy has no such
# just-created-symlink window for that class of interference to hit.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_MODEL_LOAD_ATTEMPTS = 3
_MODEL_LOAD_RETRY_DELAY_SECONDS = 2.0


def _purge_model_cache(model_size: str) -> None:
    """Deletes the cached snapshot for this model so the next load attempt
    does a genuinely fresh download (using real file copies, since
    HF_HUB_DISABLE_SYMLINKS is set above) rather than reusing a
    possibly-broken symlink-based snapshot from before that env var took
    effect.
    """
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return

    import shutil

    cache_dir = Path(HF_HUB_CACHE) / f"models--Systran--faster-whisper-{model_size}"
    if cache_dir.exists():
        print(f"Purging cached model directory: {cache_dir}", file=sys.stderr, flush=True)
        shutil.rmtree(cache_dir, ignore_errors=True)


def _load_model_with_retry(model_size: str, device: str, compute_type: str):
    """Loading a freshly-downloaded model can transiently fail on Windows
    (observed: 'Unable to open file model.bin' immediately after
    huggingface_hub creates the cache symlink, likely Windows security
    software scrutinizing file access from this unsigned app's spawned
    processes). A short retry alone wasn't enough when the *existing*
    cache was already symlink-based; purging the cache before retrying
    forces a fresh, symlink-free download to fully rule that out.
    """
    from faster_whisper import WhisperModel

    last_error: Exception | None = None
    for attempt in range(1, _MODEL_LOAD_ATTEMPTS + 1):
        try:
            return WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(
                f"Model load attempt {attempt}/{_MODEL_LOAD_ATTEMPTS} failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
            if attempt < _MODEL_LOAD_ATTEMPTS:
                _purge_model_cache(model_size)
                time.sleep(_MODEL_LOAD_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


def _run_transcribe(args: dict) -> dict:
    model = _load_model_with_retry(args["model_size"], args["device"], args["compute_type"])
    segments, info = model.transcribe(
        args["audio_path"],
        word_timestamps=True,
        language=args.get("language") or None,
        vad_filter=args.get("vad_filter", True),
        beam_size=args.get("beam_size", 5),
    )

    total_seconds = info.duration or 0.0
    words: list[dict] = []
    sentences: list[dict] = []
    for sentence_id, segment in enumerate(segments):
        text = (segment.text or "").strip()
        sentences.append({"id": sentence_id, "text": text, "start": segment.start, "end": segment.end})
        for w in segment.words or []:
            word_text = (w.word or "").strip()
            if not word_text:
                continue
            words.append({"text": word_text, "start": w.start, "end": w.end, "sentence_id": sentence_id})

        print(
            json.dumps({"progress": {"seconds_done": segment.end, "total_seconds": total_seconds}}),
            flush=True,
        )

    return {"source_language": info.language or "en", "sentences": sentences, "words": words}


_COMMANDS = {"transcribe": _run_transcribe}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=sorted(_COMMANDS))
    parser.add_argument("--args-json", required=True)
    parser.add_argument("--out-json", required=True)
    parsed = parser.parse_args()

    with open(parsed.args_json, "r", encoding="utf-8") as f:
        worker_args = json.load(f)

    try:
        result = _COMMANDS[parsed.command](worker_args)
    except Exception as exc:  # noqa: BLE001
        with open(parsed.out_json, "w", encoding="utf-8") as f:
            json.dump({"error": str(exc)}, f)
        return 1

    with open(parsed.out_json, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
