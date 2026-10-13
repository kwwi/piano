/// Fallback stub used by the analyzer when neither `dart:html` nor `dart:io`
/// is selected. Real implementations live in `export_io_web.dart` /
/// `export_io_io.dart`.
Future<String> saveOrDownloadBytes({
  required String filename,
  required List<int> bytes,
}) {
  throw UnsupportedError(
    'saveOrDownloadBytes is not available on this platform',
  );
}
