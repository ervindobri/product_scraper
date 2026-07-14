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

class HomeShell extends HookConsumerWidget {
  const HomeShell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = FluentTheme.of(context);
    final isDark = FluentTheme.of(context).brightness == Brightness.dark;
    final width = MediaQuery.sizeOf(context).width;

    return ScaffoldPage(
      padding: EdgeInsets.zero,
      header: Container(
        color: theme.scaffoldBackgroundColor,
        width: width > 1280 ? 1080 : width - 300,
        padding: const EdgeInsets.all(32.0),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Row(
              spacing: 24,
              children: [
                const Icon(FluentIcons.product_catalog),
                Text('Product Scanner', style: theme.typography.title),
              ],
            ),
            Padding(
              padding: const EdgeInsetsDirectional.only(
                start: 24,
                end: 8,
              ),
              child: Tooltip(
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
            ),
          ],
        ),
      ),
      content: Container(
        decoration: BoxDecoration(
          color: theme.scaffoldBackgroundColor,
        ),
        width: width > 1280 ? 1080 : width - 300,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Expanded(
              child: const ProductsView(),
            ),
          ],
        ),
      ),
    );
  }
}
