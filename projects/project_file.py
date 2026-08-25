"""FoulPlay project files (.fpproj): JSON snapshots of the transcript and
sentence edit decisions so a review session can resume without redoing
transcription, matching, or dialogue separation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.sentence_edit import SentenceEdit
from core.transcript import Sentence, Transcript, Word

logger = logging.getLogger(__name__)

FORMAT_VERSION = 3


@dataclass
class ProjectData:
    source_video: Path
    transcript: Transcript
    sentence_edits: dict[int, SentenceEdit] = field(default_factory=dict)


def _sentence_edit_to_dict(edit: SentenceEdit) -> dict:
    data = asdict(edit)
    data["excluded_word_indices"] = sorted(edit.excluded_word_indices)
    return data


def _sentence_edit_from_dict(data: dict) -> SentenceEdit:
    return SentenceEdit(
        sentence_id=data["sentence_id"],
        edit_enabled=data.get("edit_enabled", True),
        mirror=data.get("mirror", True),
        flagged_spans=[tuple(span) for span in data.get("flagged_spans", [])],
        excluded_word_indices=set(data.get("excluded_word_indices", [])),
        custom_subtitle_text=data.get("custom_subtitle_text"),
        needs_verification=data.get("needs_verification", False),
    )


def save_project(
    path: Path,
    source_video: Path,
    transcript: Transcript,
    sentence_edits: dict[int, SentenceEdit] | None = None,
) -> None:
    data = {
        "version": FORMAT_VERSION,
        "source_video": str(source_video),
        "transcript": {
            "source_language": transcript.source_language,
            "sentences": [asdict(s) for s in transcript.sentences],
            "words": [asdict(w) for w in transcript.words],
        },
        "sentence_edits": {
            str(sentence_id): _sentence_edit_to_dict(edit) for sentence_id, edit in (sentence_edits or {}).items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_project(path: Path) -> ProjectData:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    version = data.get("version")
    if version not in (1, 2, 3):
        raise ValueError(f"Unsupported project file version: {version!r}")

    transcript = Transcript(
        words=[Word(**w) for w in data["transcript"]["words"]],
        sentences=[Sentence(**s) for s in data["transcript"]["sentences"]],
        source_language=data["transcript"]["source_language"],
    )

    if version < 3:
        # Older project files used a different, incompatible per-word edit
        # format. The transcript is still fully usable -- only the saved
        # review decisions are lost, and Review will just recompute fresh
        # defaults from the transcript + current word list.
        logger.warning("Project file %s is format version %d; discarding incompatible saved edits.", path, version)
        return ProjectData(source_video=Path(data["source_video"]), transcript=transcript, sentence_edits={})

    sentence_edits = {
        int(sentence_id): _sentence_edit_from_dict(edit_data)
        for sentence_id, edit_data in data.get("sentence_edits", {}).items()
    }
    return ProjectData(source_video=Path(data["source_video"]), transcript=transcript, sentence_edits=sentence_edits)


def default_project_path(source_video: Path) -> Path:
    return source_video.with_suffix(".fpproj")
