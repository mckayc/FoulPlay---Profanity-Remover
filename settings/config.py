"""User settings, persisted as JSON under %APPDATA%\\FoulPlay\\config.json.

Covers the word list (defaults + user additions), per-word replacement
pools, audio edit treatment, and subtitle behavior -- all the knobs
described in the app's Settings section.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

APP_NAME = "FoulPlay"
_DEFAULT_WORDLIST_PATH = Path(__file__).resolve().parent.parent / "data" / "default_wordlist.json"


def get_config_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    config_dir = root / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


class AudioEditMode(str, Enum):
    SILENCE = "silence"
    VOLUME = "volume"
    BEEP = "beep"


class SubtitleTextMode(str, Enum):
    WORD_ONLY = "word_only"
    FULL_SENTENCE = "full_sentence"


# Severity tiers, loosely following common content-rating conventions, so a
# whole tier can be toggled at once (e.g. leave "mild" alone for older kids
# but still filter "strong"). "custom" is the default bucket for words the
# user adds themselves.
WORD_CATEGORIES = ["mild", "moderate", "strong", "religious", "sexual", "custom"]
WORD_CATEGORY_LABELS = {
    "mild": "Mild",
    "moderate": "Moderate",
    "strong": "Strong",
    "religious": "Religious",
    "sexual": "Sexual",
    "custom": "Custom (your additions)",
}


class WordEntry(BaseModel):
    word: str
    replacements: list[str] = Field(default_factory=list)
    enabled: bool = True
    category: str = "custom"


class AudioEditSettings(BaseModel):
    mode: AudioEditMode = AudioEditMode.SILENCE
    volume_db: float = -60.0  # used when mode == VOLUME (0 dB = no change)
    beep_frequency_hz: float = 1000.0  # used when mode == BEEP
    pad_before_ms: float = 50.0  # extends the edited window before the word's detected start
    pad_after_ms: float = 50.0  # extends the edited window after the word's detected end
    fade_ms: float = 8.0  # fade in/out duration applied at the (padded) window's edges


class SubtitleSettings(BaseModel):
    # All three subtitle tracks (unedited / substituted / substitute-only)
    # are always generated -- this only controls what the substitute-only
    # ("forced") track shows during an edited line.
    forced_text_mode: SubtitleTextMode = SubtitleTextMode.WORD_ONLY


WHISPER_MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]


class PerformanceSettings(BaseModel):
    whisper_model_size: str = "medium"
    # Only used as the full-video baseline pass when prioritize_speed is
    # on -- otherwise whisper_model_size runs everywhere and this is
    # unused. Kept deliberately separate from "a subtitle was supplied":
    # trading full-video accuracy for speed should be something a user
    # opts into, not something that silently kicks in just because they
    # attached a subtitle for the (independent) safety-net feature.
    whisper_fast_model_size: str = "small"
    prioritize_speed: bool = False
    # Forcing a known language skips language-detection and biases decoding,
    # which is both faster and more accurate than auto-detect for movies we
    # already know are in English. Empty string = auto-detect.
    whisper_language: str = "en"
    # Voice Activity Detection: skips music/effects-only stretches instead of
    # feeding them to the model, which reduces hallucinated "words" during
    # non-speech audio -- common in movies, rare in the clean speech Whisper
    # is usually benchmarked on.
    whisper_vad_filter: bool = True
    whisper_beam_size: int = 5
    prefer_gpu: bool = True


class AppSettings(BaseModel):
    words: list[WordEntry] = Field(default_factory=list)
    audio_edit: AudioEditSettings = Field(default_factory=AudioEditSettings)
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)


def _load_default_wordlist() -> list[WordEntry]:
    with open(_DEFAULT_WORDLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [WordEntry(**entry) for entry in data["words"]]


def get_default_settings() -> AppSettings:
    return AppSettings(words=_load_default_wordlist())


def load_settings() -> AppSettings:
    path = get_config_path()
    if not path.exists():
        settings = AppSettings(words=_load_default_wordlist())
        save_settings(settings)
        return settings

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return AppSettings.model_validate(raw)


def save_settings(settings: AppSettings) -> None:
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(settings.model_dump_json(indent=2))
