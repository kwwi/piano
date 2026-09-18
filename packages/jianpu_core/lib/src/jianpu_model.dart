/// Intermediate representation (IR) for numbered musical notation (jianpu).
///
/// This library is pure Dart (no Flutter imports) so it can be unit-tested
/// without a device and reused on the backend side conceptually. The IR is the
/// single editable source of truth: text input, and (later) image OCR both
/// produce a [JianpuScore], which is then converted to MusicXML for engraving.
library;

/// Explicit accidental applied to a degree, on top of the key signature.
enum Accidental { none, sharp, flat, natural }

/// A single jianpu event: a pitched note or a rest.
class JianpuNote {
  /// Scale degree 1..7 in movable-do; 0 means a rest.
  final int degree;

  /// Relative octave offset from the middle register.
  /// Each `'` above adds 1; each `,` below subtracts 1.
  final int octave;

  /// Explicit accidental (relative to the major scale of the key).
  final Accidental accidental;

  /// Duration measured in quarter notes (a plain number == 1.0).
  /// Underlines halve it, dots multiply by 1.5, and trailing `-` beats add 1.0.
  final double quarterLength;

  /// Optional lyric syllable attached to this note.
  final String? lyric;

  const JianpuNote({
    required this.degree,
    this.octave = 0,
    this.accidental = Accidental.none,
    required this.quarterLength,
    this.lyric,
  });

  bool get isRest => degree == 0;

  JianpuNote copyWith({
    int? degree,
    int? octave,
    Accidental? accidental,
    double? quarterLength,
    String? lyric,
  }) {
    return JianpuNote(
      degree: degree ?? this.degree,
      octave: octave ?? this.octave,
      accidental: accidental ?? this.accidental,
      quarterLength: quarterLength ?? this.quarterLength,
      lyric: lyric ?? this.lyric,
    );
  }

  Map<String, dynamic> toJson() => {
        'degree': degree,
        'octave': octave,
        'accidental': accidental.name,
        'quarterLength': quarterLength,
        if (lyric != null) 'lyric': lyric,
      };

  factory JianpuNote.fromJson(Map<String, dynamic> json) => JianpuNote(
        degree: json['degree'] as int,
        octave: (json['octave'] as int?) ?? 0,
        accidental: Accidental.values.firstWhere(
          (a) => a.name == json['accidental'],
          orElse: () => Accidental.none,
        ),
        quarterLength: (json['quarterLength'] as num).toDouble(),
        lyric: json['lyric'] as String?,
      );
}

/// A measure (bar) is an ordered list of notes/rests.
class JianpuMeasure {
  final List<JianpuNote> notes;
  const JianpuMeasure(this.notes);

  Map<String, dynamic> toJson() =>
      {'notes': notes.map((n) => n.toJson()).toList()};

  factory JianpuMeasure.fromJson(Map<String, dynamic> json) => JianpuMeasure(
        (json['notes'] as List)
            .map((e) => JianpuNote.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// A full jianpu score with header metadata and measures.
class JianpuScore {
  /// Tonic spelling of the key, e.g. `C`, `G`, `F#`, `Bb` (from `1=C`).
  final String tonic;

  /// Time-signature numerator.
  final int beats;

  /// Time-signature denominator.
  final int beatType;

  /// Tempo in quarter-note BPM.
  final int tempo;

  final String? title;
  final String? composer;
  final List<JianpuMeasure> measures;

  const JianpuScore({
    this.tonic = 'C',
    this.beats = 4,
    this.beatType = 4,
    this.tempo = 90,
    this.title,
    this.composer,
    required this.measures,
  });

  JianpuScore copyWith({
    String? tonic,
    int? beats,
    int? beatType,
    int? tempo,
    String? title,
    String? composer,
    List<JianpuMeasure>? measures,
  }) {
    return JianpuScore(
      tonic: tonic ?? this.tonic,
      beats: beats ?? this.beats,
      beatType: beatType ?? this.beatType,
      tempo: tempo ?? this.tempo,
      title: title ?? this.title,
      composer: composer ?? this.composer,
      measures: measures ?? this.measures,
    );
  }

  Map<String, dynamic> toJson() => {
        'tonic': tonic,
        'beats': beats,
        'beatType': beatType,
        'tempo': tempo,
        if (title != null) 'title': title,
        if (composer != null) 'composer': composer,
        'measures': measures.map((m) => m.toJson()).toList(),
      };

  factory JianpuScore.fromJson(Map<String, dynamic> json) => JianpuScore(
        tonic: (json['tonic'] as String?) ?? 'C',
        beats: (json['beats'] as int?) ?? 4,
        beatType: (json['beatType'] as int?) ?? 4,
        tempo: (json['tempo'] as int?) ?? 90,
        title: json['title'] as String?,
        composer: json['composer'] as String?,
        measures: (json['measures'] as List)
            .map((e) => JianpuMeasure.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
