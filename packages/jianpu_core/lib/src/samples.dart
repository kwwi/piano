/// Built-in jianpu samples used to seed the editor and for demos/tests.
class JianpuSamples {
  const JianpuSamples._();

  static const String twinkle = '''
key: 1=C
time: 4/4
tempo: 100
title: 小星星 (Twinkle Twinkle)
composer: Traditional
---
1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -
5 5 4 4 | 3 3 2 - | 5 5 4 4 | 3 3 2 -
1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -
''';

  static const String odeToJoy = '''
key: 1=G
time: 4/4
tempo: 120
title: 欢乐颂 (Ode to Joy)
composer: Beethoven
---
3 3 4 5 | 5 4 3 2 | 1 1 2 3 | 3. 2_ 2 -
3 3 4 5 | 5 4 3 2 | 1 1 2 3 | 2. 1_ 1 -
''';

  static const Map<String, String> all = {
    '小星星': twinkle,
    '欢乐颂': odeToJoy,
  };
}
