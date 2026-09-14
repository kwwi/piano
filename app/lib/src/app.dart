import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'features/home/home_screen.dart';
import 'features/jianpu/jianpu_screen.dart';
import 'features/listen/listen_screen.dart';
import 'features/upload/upload_screen.dart';

final _router = GoRouter(
  initialLocation: '/',
  routes: [
    GoRoute(path: '/', builder: (context, state) => const HomeScreen()),
    GoRoute(path: '/jianpu', builder: (context, state) => const JianpuScreen()),
    GoRoute(path: '/listen', builder: (context, state) => const ListenScreen()),
    GoRoute(path: '/upload', builder: (context, state) => const UploadScreen()),
  ],
);

class JianpuStaffApp extends StatelessWidget {
  const JianpuStaffApp({super.key});

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF5B4BFF),
      brightness: Brightness.light,
    );
    return MaterialApp.router(
      title: '简谱转五线谱',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: scheme,
        useMaterial3: true,
        appBarTheme: AppBarTheme(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
        ),
      ),
      routerConfig: _router,
    );
  }
}
