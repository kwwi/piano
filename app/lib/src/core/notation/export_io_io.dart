import 'dart:io';
import 'dart:typed_data';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// Write [bytes] into the app documents directory and return the path.
Future<String> saveOrDownloadBytes({
  required String filename,
  required List<int> bytes,
}) async {
  final dir = await getApplicationDocumentsDirectory();
  final file = File(p.join(dir.path, filename));
  await file.writeAsBytes(
    bytes is Uint8List ? bytes : Uint8List.fromList(bytes),
    flush: true,
  );
  return file.path;
}
