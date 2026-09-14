import { useCallback, useEffect, useMemo, useState } from "react";
import { Piano } from "./Piano";
import { buildNotes } from "./notes";
import { synth } from "./audio";

export default function App() {
  // Three octaves: C3 (MIDI 48) through C5 (MIDI 72).
  const notes = useMemo(() => buildNotes(48, 72), []);
  const [active, setActive] = useState<Set<number>>(() => new Set());
  const [showLabels, setShowLabels] = useState(true);

  const pressNote = useCallback((midi: number) => {
    setActive((prev) => {
      if (prev.has(midi)) return prev;
      synth.noteOn(midi);
      const next = new Set(prev);
      next.add(midi);
      return next;
    });
  }, []);

  const releaseNote = useCallback((midi: number) => {
    setActive((prev) => {
      if (!prev.has(midi)) return prev;
      synth.noteOff(midi);
      const next = new Set(prev);
      next.delete(midi);
      return next;
    });
  }, []);

  useEffect(() => {
    const byKey = new Map<string, number>();
    for (const note of notes) {
      if (note.keyboardKey) byKey.set(note.keyboardKey, note.midi);
    }

    const handleDown = (event: KeyboardEvent) => {
      if (event.repeat || event.metaKey || event.ctrlKey || event.altKey) return;
      const midi = byKey.get(event.key.toLowerCase());
      if (midi !== undefined) {
        event.preventDefault();
        pressNote(midi);
      }
    };

    const handleUp = (event: KeyboardEvent) => {
      const midi = byKey.get(event.key.toLowerCase());
      if (midi !== undefined) {
        event.preventDefault();
        releaseNote(midi);
      }
    };

    window.addEventListener("keydown", handleDown);
    window.addEventListener("keyup", handleUp);
    return () => {
      window.removeEventListener("keydown", handleDown);
      window.removeEventListener("keyup", handleUp);
    };
  }, [notes, pressNote, releaseNote]);

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">Piano</h1>
        <p className="app__subtitle">
          Play with your mouse, touch, or computer keyboard.
        </p>
      </header>

      <Piano
        notes={notes}
        activeNotes={active}
        showLabels={showLabels}
        onNoteDown={pressNote}
        onNoteUp={releaseNote}
      />

      <footer className="app__footer">
        <label className="app__toggle">
          <input
            type="checkbox"
            checked={showLabels}
            onChange={(event) => setShowLabels(event.target.checked)}
          />
          Show key labels
        </label>
        <p className="app__hint">
          Tip: the <kbd>Z</kbd>&ndash;<kbd>M</kbd> and <kbd>Q</kbd>&ndash;<kbd>I</kbd>
          rows map to two octaves.
        </p>
      </footer>
    </div>
  );
}
