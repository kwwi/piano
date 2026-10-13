import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('简谱 · 听音 · 音频 转五线谱')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _FeatureCard(
            icon: Icons.piano,
            title: '简谱转五线谱',
            subtitle: '输入或粘贴简谱，实时预览并编辑、导出五线谱',
            color: const Color(0xFF5B4BFF),
            onTap: () => context.go('/jianpu'),
          ),
          _FeatureCard(
            icon: Icons.mic,
            title: '听音转五线谱',
            subtitle: '打开麦克风，实时识别单音旋律生成五线谱',
            color: const Color(0xFF00A88F),
            onTap: () => context.go('/listen'),
          ),
          _FeatureCard(
            icon: Icons.upload_file,
            title: '上传音频/视频转五线谱',
            subtitle: '上传文件（自动提取音轨、去除人声）云端转录成谱',
            color: const Color(0xFFE0663A),
            onTap: () => context.go('/upload'),
          ),
        ],
      ),
    );
  }
}

class _FeatureCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Color color;
  final VoidCallback onTap;

  const _FeatureCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              CircleAvatar(
                radius: 28,
                backgroundColor: color.withValues(alpha: 0.15),
                child: Icon(icon, color: color, size: 30),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      subtitle,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}
