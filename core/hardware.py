"""GPU/CPU detection and capability reporting.

Detects what acceleration is available for the ML pipeline (Whisper ASR,
Demucs source separation) so the UI can pick sane default model sizes and
tell the user what to expect before they run a full movie through the
pipeline.

Detection is split into two layers:
  * OS-level GPU inventory (works even before torch is installed) via
    PowerShell CIM query, used to identify vendor.
  * torch-level capability (only meaningful once torch / torch-directml
    are installed, in milestone 4) to confirm the accelerator is actually
    usable by the pipeline, not just present.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum


class Accelerator(str, Enum):
    CUDA = "cuda"
    DIRECTML = "directml"
    CPU = "cpu"


class GpuVendor(str, Enum):
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    UNKNOWN = "unknown"
    NONE = "none"


@dataclass
class GpuInfo:
    name: str
    vendor: GpuVendor


@dataclass
class HardwareReport:
    gpus: list[GpuInfo] = field(default_factory=list)
    torch_installed: bool = False
    cuda_available: bool = False
    directml_available: bool = False
    recommended_accelerator: Accelerator = Accelerator.CPU
    expectation_message: str = ""


def _detect_gpus_via_os() -> list[GpuInfo]:
    """Enumerate GPUs using PowerShell CIM, independent of torch."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    gpus: list[GpuInfo] = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if not name:
            continue
        lowered = name.lower()
        if "nvidia" in lowered:
            vendor = GpuVendor.NVIDIA
        elif "amd" in lowered or "radeon" in lowered:
            vendor = GpuVendor.AMD
        elif "intel" in lowered:
            vendor = GpuVendor.INTEL
        else:
            vendor = GpuVendor.UNKNOWN
        gpus.append(GpuInfo(name=name, vendor=vendor))
    return gpus


def _detect_torch_capabilities() -> tuple[bool, bool, bool]:
    """Returns (torch_installed, cuda_available, directml_available)."""
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return False, False, False

    cuda_available = False
    try:
        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False

    directml_available = False
    try:
        import torch_directml  # noqa: PLC0415

        directml_available = torch_directml.device_count() > 0
    except ImportError:
        directml_available = False
    except Exception:
        directml_available = False

    return True, cuda_available, directml_available


def get_hardware_report() -> HardwareReport:
    gpus = _detect_gpus_via_os()
    torch_installed, cuda_available, directml_available = _detect_torch_capabilities()

    has_nvidia = any(g.vendor == GpuVendor.NVIDIA for g in gpus)
    has_amd = any(g.vendor == GpuVendor.AMD for g in gpus)

    if cuda_available:
        accelerator = Accelerator.CUDA
        message = (
            "NVIDIA GPU detected and usable via CUDA. Expect fast processing "
            "(a feature-length movie's transcription and dialogue separation "
            "should complete in well under the runtime of the movie itself)."
        )
    elif directml_available:
        accelerator = Accelerator.DIRECTML
        message = (
            "GPU acceleration available via DirectML. This is noticeably "
            "slower than NVIDIA/CUDA but still much faster than CPU-only; "
            "expect processing to take roughly the length of the movie or more."
        )
    else:
        accelerator = Accelerator.CPU
        if has_nvidia and not torch_installed:
            message = (
                "NVIDIA GPU detected but torch/CUDA support isn't installed yet "
                "-- once the ML dependencies are installed this will accelerate "
                "automatically. Running on CPU for now, which will be slow "
                "(potentially several hours for a full movie)."
            )
        elif has_amd:
            message = (
                "AMD GPU detected. AMD acceleration on Windows requires "
                "torch-directml; without it, processing falls back to CPU and "
                "will be slow (potentially several hours for a full movie)."
            )
        else:
            message = (
                "No supported GPU detected. Running on CPU only, which will be "
                "significantly slower -- plan for potentially several hours to "
                "process a full-length movie."
            )

    return HardwareReport(
        gpus=gpus,
        torch_installed=torch_installed,
        cuda_available=cuda_available,
        directml_available=directml_available,
        recommended_accelerator=accelerator,
        expectation_message=message,
    )
