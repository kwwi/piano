import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

import '../jianpu/jianpu.dart';
import 'export_io_stub.dart'
    if (dart.library.html) 'export_io_web.dart'
    if (dart.library.io) 'export_io_io.dart';

/// Handles saving/sharing of a score in the three supported formats.
///
/// * MusicXML — produced by [MusicXmlBuilder].
/// * MIDI — produced by [MidiBuilder].
/// * PDF — engraved Verovio SVG embedded via `pdf`/`printing`.
///
/// On **web**, files are downloaded through the browser (no `path_provider`).
/// On **mobile/desktop**, they are written under the app documents directory.
class ScoreExport {
  const ScoreExport();

  /// ASCII-safe basename so OS / browser download APIs do not reject the name.
  static String safeName(String name) {
    final cleaned = name.replaceAll(RegExp(r'[^\w\-]+'), '_');
    return cleaned.isEmpty ? 'score' : cleaned;
  }

  Future<String> saveMusicXml(JianpuScore score, {String name = 'score'}) {
    final xml = const MusicXmlBuilder().build(score);
    return saveMusicXmlText(xml, name: name);
  }

  /// Save an already-produced MusicXML string (e.g. backend job result).
  Future<String> saveMusicXmlText(String xml, {String name = 'score'}) {
    return saveOrDownloadBytes(
      filename: '${safeName(name)}.musicxml',
      bytes: utf8.encode(xml),
    );
  }

  Future<String> saveMidi(JianpuScore score, {String name = 'score'}) {
    final bytes = const MidiBuilder().build(score);
    return saveMidiBytes(bytes, name: name);
  }

  /// Save raw Standard MIDI File bytes (e.g. backend transcription.mid).
  Future<String> saveMidiBytes(List<int> bytes, {String name = 'score'}) {
    return saveOrDownloadBytes(
      filename: '${safeName(name)}.mid',
      bytes: bytes is Uint8List ? bytes : Uint8List.fromList(bytes),
    );
  }

  /// Save standard ABC notation text.
  Future<String> saveAbcText(String abc, {String name = 'score'}) {
    return saveOrDownloadBytes(
      filename: '${safeName(name)}.abc',
      bytes: utf8.encode(abc),
    );
  }

  /// Build a PDF from one or more engraved Verovio SVG pages.
  Future<Uint8List> pdfFromSvgs(List<String> svgs) async {
    if (svgs.isEmpty) {
      throw StateError('no SVG pages to export');
    }
    final doc = pw.Document();
    for (final svg in svgs) {
      final prepared = prepareSvgForPdf(svg);
      doc.addPage(
        pw.Page(
          build: (context) => pw.Center(
            child: pw.SvgImage(svg: prepared, fit: pw.BoxFit.contain),
          ),
        ),
      );
    }
    return doc.save();
  }

  /// Build a single-page PDF from an already-engraved [svg] string.
  Future<Uint8List> pdfFromSvg(String svg) => pdfFromSvgs([svg]);

  /// Present the OS share sheet, or download on web, for a PDF from [svg].
  Future<String> sharePdf(String svg, {String name = 'score'}) {
    return sharePdfPages([svg], name: name);
  }

  /// Multi-page PDF export (one Verovio SVG page → one PDF page).
  Future<String> sharePdfPages(List<String> svgs, {String name = 'score'}) async {
    final bytes = await pdfFromSvgs(svgs);
    final filename = '${safeName(name)}.pdf';
    // Chrome / Flutter web: browser download is more reliable than sharePdf.
    if (kIsWeb) {
      return saveOrDownloadBytes(filename: filename, bytes: bytes);
    }
    await Printing.sharePdf(bytes: bytes, filename: filename);
    return filename;
  }
}

/// Strip SVG content that the `pdf` package cannot embed.
///
/// Verovio draws notes/staves as `<path>`/`<use>`, which survive. Title text,
/// tempo glyphs and footer labels often contain Unicode (CJK / SMuFL / ▯
/// placeholders) that trigger
/// `Invalid argument (string): Contains invalid characters`.
///
/// Important: remove **self-closing** `<text …/>` first. A naive
/// `<text>…</text>` regex would treat `<text …/>` as an opener and swallow
/// following markup (including `</g>`), which breaks PDF embedding with
/// `XmlTagException: Expected </g>, but found </svg>`.
String prepareSvgForPdf(String svg) {
  var out = svg;
  // Self-closing metadata / text nodes (must run before paired-tag removal).
  out = out.replaceAll(
    RegExp(r'<(text|title|desc|tspan)\b[^>]*/>', caseSensitive: false),
    '',
  );
  out = out.replaceAll(
    RegExp(r'<text\b[^>]*>[\s\S]*?</text>', caseSensitive: false),
    '',
  );
  out = out.replaceAll(
    RegExp(r'<tspan\b[^>]*>[\s\S]*?</tspan>', caseSensitive: false),
    '',
  );
  out = out.replaceAll(
    RegExp(r'<title\b[^>]*>[\s\S]*?</title>', caseSensitive: false),
    '',
  );
  out = out.replaceAll(
    RegExp(r'<desc\b[^>]*>[\s\S]*?</desc>', caseSensitive: false),
    '',
  );
  out = out.replaceAll(RegExp(r'[\u0000-\u0008\u000B\u000C\u000E-\u001F]'), '');
  out = out.replaceAll('▯', '');
  out = out.replaceAll('\uFFFD', '');
  return out;
}
