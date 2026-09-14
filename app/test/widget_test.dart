import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:jianpu_staff/src/app.dart';

void main() {
  testWidgets('home screen shows the three feature entries',
      (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: JianpuStaffApp()));
    await tester.pumpAndSettle();

    expect(find.text('简谱转五线谱'), findsOneWidget);
    expect(find.text('听音转五线谱'), findsOneWidget);
    expect(find.text('上传音频/视频转五线谱'), findsOneWidget);
  });
}
