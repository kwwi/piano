"""MIDI → MusicXML via MIDI2ScoreTransformer (pitched) + music21 rules (drums)."""
from .client import M2SError, midi_to_musicxml_m2s
from .musicxml_merge import MergeError, merge_musicxml
from .router import (
    ScoreRouteError,
    build_score_xml,
    build_score_xml_from_midi,
    mode_supports_part_filter,
    normalize_score_mode,
    reshape_midi_for_score_mode,
)

__all__ = [
    "M2SError",
    "MergeError",
    "ScoreRouteError",
    "build_score_xml",
    "build_score_xml_from_midi",
    "merge_musicxml",
    "midi_to_musicxml_m2s",
    "mode_supports_part_filter",
    "normalize_score_mode",
    "reshape_midi_for_score_mode",
]
