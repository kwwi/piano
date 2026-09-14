import 'dart:io';
import 'dart:typed_data';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

import '../jianpu/jianpu.dart';

/// Handles saving/sharing of a score in the three supported formats.
///
/// * MusicXML — produced by [MusicXmlBuilder] (also the on-device edit format).
/// * MIDI — produced by [MidiBuilder] (pure Dart, no plugin needed).
/// * PDF — rendered from the engraved Verovio SVG via the `pdf`/`printing`
///   packages (`pw.SvgImage` embeds the vector SVG at full quality).
class ScoreExport {
  const ScoreExport();

  Future<File> _writeBytes(String filename, List<int> bytes) async {
    final dir = await getApplicationDocumentsDirectory();
    final file = File(p.join(dir.path, filename));
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }

  Future<File> saveMusicXml(JianpuScore score, {String name = 'score'}) {
    final xml = const MusicXmlBuilder().build(score);
    return _writeBytes('$name.musicxml', xml.codeUnits);
  }

  Future<File> saveMidi(JianpuScore score, {String name = 'score'}) {
    final bytes = const MidiBuilder().build(score);
    return _writeBytes('$name.mid', bytes);
  }

  /// Build a single-page PDF from an already-engraved [svg] string.
  Future<Uint8List> pdfFromSvg(String svg) async {
    final doc = pw.Document();
    doc.addPage(
      pw.Page(
        build: (context) => pw.Center(child: pw.SvgImage(svg: svg)),
      ),
    );
    return doc.save();
  }

  /// Present the OS share/print sheet for a PDF built from [svg].
  Future<void> sharePdf(String svg, {String name = 'score'}) async {
    final bytes = await pdfFromSvg(svg);
    await Printing.sharePdf(bytes: bytes, filename: '$name.pdf');
  }
}
