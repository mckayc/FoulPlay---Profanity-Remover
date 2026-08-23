"""Dialogue isolation via Demucs (vocals vs. accompaniment separation).

Demucs is invoked as a subprocess (`python -m demucs`) rather than through
its Python API -- this keeps the module decoupled from Demucs internals
and lets progress be streamed line-by-line from stdout.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from core.hardware import Accelerator, get_hardware_report
from core.runtime import ensure_runtime_ready, get_runtime_python

_MODEL_NAME = "htdemucs"


class SeparationError(RuntimeError):
    pass


def pick_demucs_device(prefer_gpu: bool = True) -> str:
    if not prefer_gpu:
        return "cpu"
    report = get_hardware_report()
    if report.recommended_accelerator == Accelerator.CUDA:
        return "cuda"
    # DirectML support in Demucs/torch is unproven and fragile enough that
    # forcing it risks silent breakage; CPU is the reliable fallback for
    # AMD/Intel and CPU-only machines. Revisit if torch-directml coverage
    # for the ops Demucs needs improves.
    return "cpu"


def separate_dialogue(
    audio_wav: Path,
    output_dir: Path,
    prefer_gpu: bool = True,
    on_output: Callable[[str], None] | None = None,
) -> tuple[Path, Path]:
    """Runs Demucs two-stem separation. Returns (vocals_path, accompaniment_path)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    device = pick_demucs_device(prefer_gpu)

    ensure_runtime_ready()
    cmd = [
        get_runtime_python(),
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "-n",
        _MODEL_NAME,
        "-d",
        device,
        "-o",
        str(output_dir),
        str(audio_wav),
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        if on_output:
            on_output(line.rstrip())
    process.wait()

    if process.returncode != 0:
        raise SeparationError(f"Demucs separation failed (exit code {process.returncode}).")

    stem_dir = output_dir / _MODEL_NAME / audio_wav.stem
    vocals = stem_dir / "vocals.wav"
    accompaniment = stem_dir / "no_vocals.wav"
    if not vocals.exists() or not accompaniment.exists():
        raise SeparationError(f"Expected Demucs output not found in {stem_dir}")
    return vocals, accompaniment
