"""Piano arrangement: lead sheet → playable grand-staff MIDI."""

from .api import ArrangePianoError, arrange_for_piano

__all__ = ["ArrangePianoError", "arrange_for_piano"]
