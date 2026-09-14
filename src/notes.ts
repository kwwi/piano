export interface Note {
  /** Scientific pitch name, e.g. "C4" or "F#4". */
  name: string;
  /** MIDI note number, used to compute the frequency. */
  midi: number;
  /** True for the black keys (sharps/flats). */
  isSharp: boolean;
  /** Computer-keyboard key bound to this note, if any. */
  keyboardKey?: string;
}

const NOTE_NAMES = [
  "C",
  "C#",
  "D",
  "D#",
  "E",
  "F",
  "F#",
  "G",
  "G#",
  "A",
  "A#",
  "B",
];

/**
 * Convert a MIDI note number to its frequency in Hz using
 * equal temperament tuning with A4 = 440 Hz (MIDI 69).
 */
export function midiToFrequency(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

/**
 * Build a contiguous range of notes between two MIDI numbers (inclusive).
 * The keyboard mapping below spans two octaves so a laptop keyboard can
 * play a comfortable range without modifier keys.
 */
const KEYBOARD_MAP: Record<number, string> = {
  // Lower octave: white keys on the Z row, black keys on the S/D... row.
  48: "z", // C3
  49: "s", // C#3
  50: "x", // D3
  51: "d", // D#3
  52: "c", // E3
  53: "v", // F3
  54: "g", // F#3
  55: "b", // G3
  56: "h", // G#3
  57: "n", // A3
  58: "j", // A#3
  59: "m", // B3
  // Upper octave: white keys on the Q row, black keys on the number row.
  60: "q", // C4
  61: "2", // C#4
  62: "w", // D4
  63: "3", // D#4
  64: "e", // E4
  65: "r", // F4
  66: "5", // F#4
  67: "t", // G4
  68: "6", // G#4
  69: "y", // A4
  70: "7", // A#4
  71: "u", // B4
  72: "i", // C5
};

export function buildNotes(startMidi: number, endMidi: number): Note[] {
  const notes: Note[] = [];
  for (let midi = startMidi; midi <= endMidi; midi += 1) {
    const nameIndex = midi % 12;
    const octave = Math.floor(midi / 12) - 1;
    const baseName = NOTE_NAMES[nameIndex];
    notes.push({
      name: `${baseName}${octave}`,
      midi,
      isSharp: baseName.includes("#"),
      keyboardKey: KEYBOARD_MAP[midi],
    });
  }
  return notes;
}
