import 'package:flutter_test/flutter_test.dart';
import 'package:jianpu_staff/src/core/notation/score_export.dart';

void main() {
  test('prepareSvgForPdf does not swallow markup after self-closing text', () {
    const svg = '''
<svg xmlns="http://www.w3.org/2000/svg">
  <g>
    <text x="1" y="2"/>
    <path d="M0 0"/>
  </g>
</svg>
''';
    final out = prepareSvgForPdf(svg);
    expect(out.contains('</g>'), isTrue);
    expect(out.contains('</svg>'), isTrue);
    expect(out.contains('<text'), isFalse);
  });

  test('prepareSvgForPdf strips paired text without breaking groups', () {
    const svg = '''
<svg>
  <g>
    <text x="1">标题</text>
    <path d="M0 0"/>
  </g>
</svg>
''';
    final out = prepareSvgForPdf(svg);
    expect(out.contains('</g>'), isTrue);
    expect(out.contains('标题'), isFalse);
  });
}
