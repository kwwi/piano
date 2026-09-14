import { midiToFrequency } from "./notes";

/**
 * A small Web Audio synthesizer that produces a plucked, piano-like tone.
 *
 * Browsers require audio to be created after a user gesture, so the
 * AudioContext is lazily instantiated (and resumed) on the first note.
 */
class PianoSynth {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private active = new Map<number, { osc: OscillatorNode[]; gain: GainNode }>();

  private ensureContext(): AudioContext {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.8;
      this.master.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") {
      void this.ctx.resume();
    }
    return this.ctx;
  }

  noteOn(midi: number): void {
    const ctx = this.ensureContext();
    if (!this.master || this.active.has(midi)) return;

    const now = ctx.currentTime;
    const frequency = midiToFrequency(midi);
    const gain = ctx.createGain();
    gain.connect(this.master);

    // Two detuned oscillators give the tone a little warmth/body.
    const oscillators: OscillatorNode[] = [];
    const partials: Array<{ type: OscillatorType; detune: number; level: number }> = [
      { type: "triangle", detune: 0, level: 0.6 },
      { type: "sine", detune: 4, level: 0.4 },
    ];

    for (const partial of partials) {
      const osc = ctx.createOscillator();
      osc.type = partial.type;
      osc.frequency.value = frequency;
      osc.detune.value = partial.detune;
      const partialGain = ctx.createGain();
      partialGain.gain.value = partial.level;
      osc.connect(partialGain);
      partialGain.connect(gain);
      osc.start(now);
      oscillators.push(osc);
    }

    // Percussive attack followed by a gentle decay toward a sustain level.
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.9, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.3, now + 0.3);

    this.active.set(midi, { osc: oscillators, gain });
  }

  noteOff(midi: number): void {
    if (!this.ctx) return;
    const voice = this.active.get(midi);
    if (!voice) return;
    this.active.delete(midi);

    const now = this.ctx.currentTime;
    const release = 0.35;
    voice.gain.gain.cancelScheduledValues(now);
    voice.gain.gain.setValueAtTime(Math.max(voice.gain.gain.value, 0.0001), now);
    voice.gain.gain.exponentialRampToValueAtTime(0.0001, now + release);

    for (const osc of voice.osc) {
      osc.stop(now + release + 0.02);
    }
  }
}

export const synth = new PianoSynth();
