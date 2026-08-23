"""FoulPlay project files (.fpproj): JSON snapshots of the transcript and
edit decisions so a review session can resume without redoing
transcription, matching, or (from milestone 4) dialogue separation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.transcript import Sentence, Transcript, Word

FORMAT_VERSION = 2


@dataclass
class EditDecision:
    word_index: int  # index into transcript.words
    include: bool
    replacement: str


@dataclass
class ProjectData:
    source_video: Path
    transcript: Transcript
    edits: list[EditDecision] = field(default_factory=list)


def save_project(
    path: Path,
    source_video: Path,
    transcript: Transcript,
    edits: list[EditDecision] | None = None,
) -> None:
    data = {
        "version": FORMAT_VERSION,
        "source_video": str(source_video),
        "transcript": {
            "source_language": transcript.source_language,
            "sentences": [asdict(s) for s in transcript.sentences],
            "words": [asdict(w) for w in transcript.words],
        },
        "edits": [asdict(e) for e in (edits or [])],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_project(path: Path) -> ProjectData:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("version") not in (1, 2):
        raise ValueError(f"Unsupported project file version: {data.get('version')!r}")

    transcript = Transcript(
        words=[Word(**w) for w in data["transcript"]["words"]],
        sentences=[Sentence(**s) for s in data["transcript"]["sentences"]],
        source_language=data["transcript"]["source_language"],
    )
    edits = [EditDecision(**e) for e in data.get("edits", [])]
    return ProjectData(source_video=Path(data["source_video"]), transcript=transcript, edits=edits)


def default_project_path(source_video: Path) -> Path:
    return source_video.with_suffix(".fpproj")
