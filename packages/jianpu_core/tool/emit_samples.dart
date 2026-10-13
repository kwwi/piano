// Emits MusicXML and MIDI for the built-in samples so the engine output can be
// engraved (e.g. with Verovio) and inspected. Usage:
//   dart run tool/emit_samples.dart <out_dir>
import 'dart:io';

import 'package:jianpu_core/jianpu_core.dart';

void main(List<String> args) {
  final outDir = Directory(args.isNotEmpty ? args[0] : 'out')
    ..createSync(recursive: true);
  const parser = JianpuParser();
  const xmlBuilder = MusicXmlBuilder();
  const midiBuilder = MidiBuilder();

  JianpuSamples.all.forEach((name, dsl) {
    final score = parser.parse(dsl);
    final slug = _slug(score.title ?? name);
    File('${outDir.path}/$slug.musicxml')
        .writeAsStringSync(xmlBuilder.build(score));
    File('${outDir.path}/$slug.mid')
        .writeAsBytesSync(midiBuilder.build(score));
    stdout.writeln('wrote ${outDir.path}/$slug.musicxml (+ .mid) '
        '[${score.measures.length} measures]');
  });
}

String _slug(String name) {
  final ascii = name.replaceAll(RegExp(r'[^A-Za-z0-9]+'), '_');
  final trimmed = ascii.replaceAll(RegExp(r'^_+|_+$'), '');
  return trimmed.isEmpty ? 'sample' : trimmed.toLowerCase();
}
