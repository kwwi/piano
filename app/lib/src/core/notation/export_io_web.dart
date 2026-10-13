import 'dart:html' as html;
import 'dart:typed_data';

/// Trigger a browser download for [bytes] as [filename].
Future<String> saveOrDownloadBytes({
  required String filename,
  required List<int> bytes,
}) async {
  final data = bytes is Uint8List ? bytes : Uint8List.fromList(bytes);
  final blob = html.Blob([data]);
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.AnchorElement(href: url)
    ..setAttribute('download', filename)
    ..click();
  html.Url.revokeObjectUrl(url);
  return '已下载 $filename';
}
