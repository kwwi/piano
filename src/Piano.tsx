import type { PointerEvent as ReactPointerEvent } from "react";
import type { Note } from "./notes";

interface PianoProps {
  notes: Note[];
  activeNotes: Set<number>;
  showLabels: boolean;
  onNoteDown: (midi: number) => void;
  onNoteUp: (midi: number) => void;
}

/**
 * Renders a piano keyboard. White keys flow in normal document order while
 * black keys are absolutely positioned so they straddle adjacent white keys.
 */
export function Piano({
  notes,
  activeNotes,
  showLabels,
  onNoteDown,
  onNoteUp,
}: PianoProps) {
  const whiteNotes = notes.filter((note) => !note.isSharp);
  const whiteWidth = 100 / whiteNotes.length;

  const whiteIndexByMidi = new Map<number, number>();
  whiteNotes.forEach((note, index) => whiteIndexByMidi.set(note.midi, index));

  const handleDown = (event: ReactPointerEvent<HTMLButtonElement>, midi: number) => {
    // Capture the pointer so dragging off the key still triggers note-off.
    event.currentTarget.setPointerCapture(event.pointerId);
    onNoteDown(midi);
  };

  return (
    <div className="piano" role="group" aria-label="Piano keyboard">
      <div className="piano__keys">
        {whiteNotes.map((note) => {
          const isActive = activeNotes.has(note.midi);
          return (
            <button
              key={note.midi}
              type="button"
              className={`key key--white${isActive ? " key--active" : ""}`}
              style={{ width: `${whiteWidth}%` }}
              aria-label={note.name}
              aria-pressed={isActive}
              onPointerDown={(event) => handleDown(event, note.midi)}
              onPointerUp={() => onNoteUp(note.midi)}
              onPointerCancel={() => onNoteUp(note.midi)}
              onPointerLeave={(event) => {
                if (event.buttons > 0) onNoteUp(note.midi);
              }}
            >
              {showLabels && (
                <span className="key__label">
                  <span className="key__note">{note.name}</span>
                  {note.keyboardKey && (
                    <span className="key__hint">{note.keyboardKey.toUpperCase()}</span>
                  )}
                </span>
              )}
            </button>
          );
        })}

        {notes
          .filter((note) => note.isSharp)
          .map((note) => {
            const leftWhiteIndex = whiteIndexByMidi.get(note.midi - 1);
            if (leftWhiteIndex === undefined) return null;
            const isActive = activeNotes.has(note.midi);
            const left = (leftWhiteIndex + 1) * whiteWidth;
            return (
              <button
                key={note.midi}
                type="button"
                className={`key key--black${isActive ? " key--active" : ""}`}
                style={{
                  left: `${left}%`,
                  width: `${whiteWidth * 0.6}%`,
                  marginLeft: `${-whiteWidth * 0.3}%`,
                }}
                aria-label={note.name}
                aria-pressed={isActive}
                onPointerDown={(event) => handleDown(event, note.midi)}
                onPointerUp={() => onNoteUp(note.midi)}
                onPointerCancel={() => onNoteUp(note.midi)}
                onPointerLeave={(event) => {
                  if (event.buttons > 0) onNoteUp(note.midi);
                }}
              >
                {showLabels && note.keyboardKey && (
                  <span className="key__hint key__hint--black">
                    {note.keyboardKey.toUpperCase()}
                  </span>
                )}
              </button>
            );
          })}
      </div>
    </div>
  );
}
