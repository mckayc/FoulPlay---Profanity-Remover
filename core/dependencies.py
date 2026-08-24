"""On-demand installer for heavy, optional ML dependencies.

Keeping torch/faster-whisper/demucs/whisperx out of the base install is
what lets the distributable app/installer stay small: the base app (UI +
ffmpeg orchestration) is a light footprint, and each pipeline feature
installs its own dependency group into the running Python environment the
first time it's actually used, choosing the right build (CUDA/DirectML/CPU)
for the detected hardware.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from core import proc
from core.hardware import Accelerator, get_hardware_report
from core.runtime import ensure_runtime_ready, get_runtime_python, is_runtime_ready

logger = logging.getLogger(__name__)


@dataclass
class DependencyGroup:
    key: str
    label: str
    import_name: str  # module probed with importlib to check if already installed
    packages: list[str]
    extra_index_url: str | None = None
    approx_size_mb: int = 0
    used_for: str = ""


def _torch_spec_for_accelerator(accelerator: Accelerator) -> tuple[list[str], str | None]:
    """Pick torch/torchaudio package specs + index for the detected hardware.

    CUDA gets the CUDA-enabled wheel from PyTorch's own index; DirectML
    needs a pinned torch version it's compatible with plus the
    torch-directml package; CPU uses the default (smaller) PyPI wheels.
    """
    if accelerator == Accelerator.CUDA:
        return ["torch", "torchaudio"], "https://download.pytorch.org/whl/cu121"
    if accelerator == Accelerator.DIRECTML:
        return ["torch==2.4.1", "torchaudio==2.4.1", "torch-directml"], None
    return ["torch", "torchaudio"], None


def get_dependency_groups() -> dict[str, DependencyGroup]:
    report = get_hardware_report()
    # Demucs (core/audio_isolate.py) only runs on CUDA or CPU today --
    # DirectML support for the ops it needs is unproven, so we don't pull
    # in torch-directml for the separation group even on AMD/Intel hardware.
    separation_accelerator = (
        report.recommended_accelerator if report.recommended_accelerator == Accelerator.CUDA else Accelerator.CPU
    )
    separation_torch_packages, separation_torch_index = _torch_spec_for_accelerator(separation_accelerator)

    return {
        "asr": DependencyGroup(
            key="asr",
            label="Speech transcription (faster-whisper)",
            import_name="faster_whisper",
            packages=["faster-whisper"],
            approx_size_mb=150,
            used_for="Generating the initial transcript when a video has no existing subtitles.",
        ),
        "alignment": DependencyGroup(
            key="alignment",
            label="Subtitle alignment (WhisperX)",
            import_name="whisperx",
            packages=["whisperx"],
            approx_size_mb=300,
            used_for="Aligning existing subtitle text to precise word timings (more accurate than ASR alone).",
        ),
        "separation": DependencyGroup(
            key="separation",
            label="Dialogue isolation (Demucs + PyTorch)",
            import_name="demucs",
            packages=[*separation_torch_packages, "demucs"],
            extra_index_url=separation_torch_index,
            approx_size_mb=2500 if separation_accelerator == Accelerator.CUDA else 400,
            used_for="Separating dialogue from music/effects so only the target word is muted.",
        ),
    }


def is_installed(group: DependencyGroup) -> bool:
    """Checks against the ML runtime interpreter (core/runtime.py), not the
    current process -- once frozen, packages are pip-installed into a
    separate managed runtime, not the app's own (unpip-able) interpreter.
    """
    if not is_runtime_ready():
        return False
    result = proc.run(
        [get_runtime_python(), "-c", f"import {group.import_name}"],
        capture_output=True,
    )
    installed = result.returncode == 0
    logger.debug("Dependency group '%s' installed=%s", group.key, installed)
    return installed


def missing_groups(keys: Iterable[str]) -> list[DependencyGroup]:
    groups = get_dependency_groups()
    return [groups[k] for k in keys if k in groups and not is_installed(groups[k])]


def install_group(group: DependencyGroup, on_output: Callable[[str], None] | None = None) -> None:
    runtime_python = ensure_runtime_ready()
    cmd = [runtime_python, "-m", "pip", "install", "--upgrade", *group.packages]
    if group.extra_index_url:
        cmd += ["--extra-index-url", group.extra_index_url]

    logger.info("Installing dependency group '%s': %s", group.key, " ".join(cmd))
    process = proc.popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        logger.debug("[pip:%s] %s", group.key, line)
        if on_output:
            on_output(line)
    process.wait()

    if process.returncode != 0:
        logger.error("Install of '%s' failed with exit code %s", group.key, process.returncode)
        raise RuntimeError(f"Failed to install '{group.label}' (pip exit code {process.returncode}).")
    logger.info("Dependency group '%s' installed successfully", group.key)
