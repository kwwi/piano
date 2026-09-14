import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:verovio_flutter/verovio_flutter.dart';

/// Thin wrapper around [VerovioAsyncService] that lazily boots the toolkit on a
/// worker isolate and engraves MusicXML/MEI into SVG on-device (offline).
class VerovioRenderer {
  VerovioAsyncService? _service;
  Future<VerovioAsyncService>? _boot;

  Future<VerovioAsyncService> _ensure() {
    return _boot ??= _spawn();
  }

  Future<VerovioAsyncService> _spawn() async {
    final resourcePath = await VerovioResourceManager.ensureVerovioAssetsReady();
    final service = await VerovioAsyncService.spawn(resourcePath: resourcePath);
    _service = service;
    return service;
  }

  /// Load [data] (MusicXML, MEI, ABC, …) and return the SVG for [page].
  Future<String> render(String data, {int page = 1}) async {
    final service = await _ensure();
    await service.loadData(data);
    return service.renderToSvg(page);
  }

  void dispose() {
    _service?.dispose();
    _service = null;
    _boot = null;
  }
}

/// App-wide singleton renderer. Kept alive for the whole session so the toolkit
/// isolate is only spawned once.
final verovioRendererProvider = Provider<VerovioRenderer>((ref) {
  final renderer = VerovioRenderer();
  ref.onDispose(renderer.dispose);
  return renderer;
});
