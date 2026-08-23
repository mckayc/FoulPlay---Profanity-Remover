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
import sys


def _run_transcribe(args: dict) -> dict:
    from faster_whisper import WhisperModel

    model = WhisperModel(args["model_size"], device=args["device"], compute_type=args["compute_type"])
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
