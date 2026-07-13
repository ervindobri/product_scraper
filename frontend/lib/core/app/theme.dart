import 'package:fluent_ui/fluent_ui.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

abstract final class AppTheme {
  static final AccentColor accent = Colors.blue;

  static final FluentThemeData light = FluentThemeData(
    brightness: Brightness.light,
    accentColor: accent,
    visualDensity: VisualDensity.standard,
  );

  static final FluentThemeData dark = FluentThemeData(
    brightness: Brightness.dark,
    accentColor: accent,
    visualDensity: VisualDensity.standard,
  );
}

final themeModeProvider = NotifierProvider<ThemeModeNotifier, ThemeMode>(
  ThemeModeNotifier.new,
);

class ThemeModeNotifier extends Notifier<ThemeMode> {
  @override
  ThemeMode build() {
    // deep link / debugging override: /?theme=light or /?theme=dark
    return switch (Uri.base.queryParameters['theme']) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
  }

  void set(ThemeMode mode) => state = mode;

  void toggle() {
    state = switch (state) {
      ThemeMode.light => ThemeMode.dark,
      _ => ThemeMode.light,
    };
  }
}
