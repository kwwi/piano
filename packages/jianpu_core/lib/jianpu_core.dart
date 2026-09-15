/// Pure-Dart engine for numbered musical notation (jianpu).
///
/// Provides the editable IR ([JianpuScore]), a text-DSL [JianpuParser],
/// pitch resolution ([spell]), and exporters to MusicXML ([MusicXmlBuilder])
/// and Standard MIDI ([MidiBuilder]), plus a monophonic [MelodyTranscriber]
/// for the listen-to-staff feature.
library;

export 'src/jianpu_model.dart';
export 'src/jianpu_parser.dart';
export 'src/jianpu_dsl_writer.dart';
export 'src/musicxml_builder.dart';
export 'src/midi_builder.dart';
export 'src/pitch.dart';
export 'src/samples.dart';
export 'src/transcription.dart';
