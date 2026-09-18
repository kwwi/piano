import 'dart:typed_data';

/// A single sounding note extracted from a Standard MIDI File.
class MidiNoteEvent {
  final int midi;
  final double startSec;
  final double durationSec;

  const MidiNoteEvent({
    required this.midi,
    required this.startSec,
    required this.durationSec,
  });
}

/// Result of parsing an SMF (format 0 or 1) into timed note events.
class ParsedMidi {
  /// Tempo in BPM from the first set-tempo meta event (default 120).
  final double tempoBpm;
  final List<MidiNoteEvent> notes;

  const ParsedMidi({required this.tempoBpm, required this.notes});
}

/// Minimal Standard MIDI File parser for preview / export helpers.
///
/// Handles format 0 and 1, tempo meta events, and note on/off (including
/// note-on with velocity 0). Enough for Basic Pitch / MT3 transcription MIDI.
ParsedMidi parseMidiSmf(Uint8List bytes) {
  final data = ByteData.sublistView(bytes);
  if (bytes.length < 14 ||
      !_asciiEq(bytes, 0, 'MThd') ||
      data.getUint32(4) != 6) {
    throw FormatException('Not a Standard MIDI File');
  }
  final format = data.getUint16(8);
  final nTracks = data.getUint16(10);
  final division = data.getUint16(12);
  if (division & 0x8000 != 0) {
    throw FormatException('SMPTE MIDI timing is not supported');
  }
  final tpq = division; // ticks per quarter
  if (format > 1) {
    throw FormatException('MIDI format $format is not supported');
  }

  var offset = 14;
  var usPerQuarter = 500000; // 120 BPM
  final notes = <MidiNoteEvent>[];

  for (var t = 0; t < nTracks && offset + 8 <= bytes.length; t++) {
    if (!_asciiEq(bytes, offset, 'MTrk')) {
      throw FormatException('Missing MTrk at offset $offset');
    }
    final trackLen = data.getUint32(offset + 4);
    offset += 8;
    final trackEnd = offset + trackLen;
    var tick = 0;
    var runningStatus = 0;
    // key -> (startTick, velocity)
    final active = <int, ({int start, int vel})>{};

    while (offset < trackEnd) {
      final delta = _readVarLen(bytes, offset);
      offset = delta.next;
      tick += delta.value;
      if (offset >= trackEnd) break;

      var status = bytes[offset];
      if (status & 0x80 != 0) {
        offset++;
        runningStatus = status;
      } else {
        status = runningStatus;
      }
      if (status == 0xFF) {
        // Meta event.
        if (offset >= trackEnd) break;
        final type = bytes[offset++];
        final len = _readVarLen(bytes, offset);
        offset = len.next;
        final payload = bytes.sublist(offset, offset + len.value);
        offset += len.value;
        if (type == 0x51 && len.value == 3) {
          usPerQuarter =
              (payload[0] << 16) | (payload[1] << 8) | payload[2];
        }
        continue;
      }
      if (status == 0xF0 || status == 0xF7) {
        final len = _readVarLen(bytes, offset);
        offset = len.next + len.value;
        continue;
      }

      final cmd = status & 0xF0;
      if (cmd == 0x90 || cmd == 0x80) {
        if (offset + 1 >= trackEnd) break;
        final key = bytes[offset++];
        final vel = bytes[offset++];
        final isOn = cmd == 0x90 && vel > 0;
        if (isOn) {
          active[key] = (start: tick, vel: vel);
        } else {
          final started = active.remove(key);
          if (started != null) {
            final startSec = started.start * usPerQuarter / (tpq * 1e6);
            final endSec = tick * usPerQuarter / (tpq * 1e6);
            final dur = (endSec - startSec).clamp(0.02, 30.0);
            notes.add(MidiNoteEvent(
              midi: key,
              startSec: startSec,
              durationSec: dur,
            ));
          }
        }
      } else if (cmd == 0xC0 || cmd == 0xD0) {
        offset += 1; // program / channel pressure
      } else {
        offset += 2; // most other channel messages
      }
    }
    // Close any hanging notes at end of track.
    for (final entry in active.entries) {
      final startSec = entry.value.start * usPerQuarter / (tpq * 1e6);
      final endSec = tick * usPerQuarter / (tpq * 1e6);
      notes.add(MidiNoteEvent(
        midi: entry.key,
        startSec: startSec,
        durationSec: (endSec - startSec).clamp(0.02, 30.0),
      ));
    }
    offset = trackEnd;
  }

  notes.sort((a, b) => a.startSec.compareTo(b.startSec));
  final bpm = 60000000 / usPerQuarter;
  return ParsedMidi(tempoBpm: bpm, notes: notes);
}

bool _asciiEq(Uint8List bytes, int offset, String s) {
  if (offset + s.length > bytes.length) return false;
  for (var i = 0; i < s.length; i++) {
    if (bytes[offset + i] != s.codeUnitAt(i)) return false;
  }
  return true;
}

({int value, int next}) _readVarLen(Uint8List bytes, int offset) {
  var value = 0;
  var i = offset;
  while (i < bytes.length) {
    final b = bytes[i++];
    value = (value << 7) | (b & 0x7F);
    if (b & 0x80 == 0) break;
  }
  return (value: value, next: i);
}
