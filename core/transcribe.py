"""Whisper-based ASR producing word-level timestamps.

Runs out-of-process via core/ml_worker.py under whichever interpreter
core/runtime.py resolves. This keeps faster-whisper -- and, once frozen,
the multi-hundred-MB weight it drags in -- out of the main app process
entirely, which is what makes on-demand dependency installation actually
work once frozen (see core/runtime.py for why sys.executable alone isn't
enough there).
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from core.hardware import Accelerator, get_hardware_report
from core.runtime import ensure_runtime_ready, get_ml_worker_script, get_runtime_python
from core.transcript import Sentence, Transcript, Word

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, float], None]  # (seconds_processed, total_seconds)


class TranscriptionError(RuntimeError):
    pass


def pick_device_and_compute_type(prefer_gpu: bool = True) -> tuple[str, str]:
    if not prefer_gpu:
        return "cpu", "int8"
    report = get_hardware_report()
    if report.recommended_accelerator == Accelerator.CUDA:
        return "cuda", "float16"
    return "cpu", "int8"


def transcribe_audio(
    audio_path: Path,
    model_size: str = "medium",
    language: str | None = "en",
    vad_filter: bool = True,
    beam_size: int = 5,
    prefer_gpu: bool = True,
    on_progress: ProgressCallback | None = None,
) -> Transcript:
    ensure_runtime_ready()
    runtime_python = get_runtime_python()
    worker_script = get_ml_worker_script()
    device, compute_type = pick_device_and_compute_type(prefer_gpu)
    logger.info(
        "Transcribing %s (model=%s language=%s vad=%s beam=%s device=%s compute=%s)",
        audio_path,
        model_size,
        language,
        vad_filter,
        beam_size,
        device,
        compute_type,
    )

    with tempfile.TemporaryDirectory(prefix="foulplay_worker_") as tmp:
        tmp_dir = Path(tmp)
        args_path = tmp_dir / "args.json"
        out_path = tmp_dir / "out.json"
        args_path.write_text(
            json.dumps(
                {
                    "audio_path": str(audio_path),
                    "model_size": model_size,
                    "language": language,
                    "vad_filter": vad_filter,
                    "beam_size": beam_size,
                    "device": device,
                    "compute_type": compute_type,
                }
            ),
            encoding="utf-8",
        )

        cmd = [
            runtime_python,
            str(worker_script),
            "transcribe",
            "--args-json",
            str(args_path),
            "--out-json",
            str(out_path),
        ]
        logger.debug("Running: %s", " ".join(cmd))
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("[ml_worker] %s", line)
                continue
            progress = payload.get("progress")
            if progress and on_progress:
                on_progress(progress.get("seconds_done", 0.0), progress.get("total_seconds", 0.0))
        process.wait()

        if not out_path.exists():
            logger.error("Transcription worker produced no output (exit code %s)", process.returncode)
            raise TranscriptionError(
                f"Transcription worker produced no output (exit code {process.returncode})."
            )
        result = json.loads(out_path.read_text(encoding="utf-8"))

    if "error" in result:
        logger.error("Transcription worker reported an error: %s", result["error"])
        raise TranscriptionError(result["error"])

    words = [Word(**w) for w in result["words"]]
    sentences = [Sentence(**s) for s in result["sentences"]]
    logger.info(
        "Transcription complete: %d sentences, %d words, detected language=%s",
        len(sentences),
        len(words),
        result.get("source_language"),
    )
    return Transcript(words=words, sentences=sentences, source_language=result.get("source_language", "en"))
