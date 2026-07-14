import 'package:fluent_ui/fluent_ui.dart';
import 'package:frontend/core/app/theme.dart';
import 'package:frontend/features/products/presentation/products_view.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

class App extends ConsumerWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeMode = ref.watch(themeModeProvider);

    return FluentApp(
      title: 'Product Scanner',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: themeMode,
      home: const HomeShell(),
    );
  }
}

/// Below this width the app switches to the phone layout (stacked search
/// header, result cards instead of the table).
const kCompactBreakpoint = 700.0;

bool isCompactLayout(BuildContext context) =>
    MediaQuery.sizeOf(context).width < kCompactBreakpoint;

class HomeShell extends HookConsumerWidget {
  const HomeShell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = FluentTheme.of(context);
    final isDark = FluentTheme.of(context).brightness == Brightness.dark;
    final compact = isCompactLayout(context);

    return ScaffoldPage(
      padding: EdgeInsets.zero,
      header: Container(
        color: theme.scaffoldBackgroundColor,
        alignment: Alignment.center,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1080),
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: compact ? 12 : 32,
              vertical: compact ? 12 : 32,
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  spacing: compact ? 12 : 24,
                  children: [
                    const Icon(FluentIcons.product_catalog),
                    Text(
                      'Product Scanner',
                      style: compact
                          ? theme.typography.subtitle
                          : theme.typography.title,
                    ),
                  ],
                ),
                Tooltip(
                  message: isDark
                      ? 'Switch to light theme'
                      : 'Switch to dark theme',
                  child: IconButton(
                    icon: Icon(
                      isDark ? FluentIcons.sunny : FluentIcons.clear_night,
                    ),
                    onPressed: () =>
                        ref.read(themeModeProvider.notifier).toggle(),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      content: Container(
        color: theme.scaffoldBackgroundColor,
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1080),
          child: const ProductsView(),
        ),
      ),
    );
  }
}
