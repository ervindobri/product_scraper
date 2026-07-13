import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
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
    final selectedIndex = useState(0);
    final isDark = FluentTheme.of(context).brightness == Brightness.dark;

    return NavigationView(
      titleBar: TitleBar(
        icon: const Icon(FluentIcons.product_catalog),
        title: const Text('Product Scanner'),
        isBackButtonVisible: false,
        endHeader: Padding(
          padding: const EdgeInsetsDirectional.only(end: 8),
          child: Tooltip(
            message: isDark ? 'Switch to light theme' : 'Switch to dark theme',
            child: IconButton(
              icon: Icon(isDark ? FluentIcons.sunny : FluentIcons.clear_night),
              onPressed: () => ref.read(themeModeProvider.notifier).toggle(),
            ),
          ),
        ),
      ),
      pane: NavigationPane(
        selected: selectedIndex.value,
        onChanged: (index) => selectedIndex.value = index,
        displayMode: PaneDisplayMode.compact,
        items: [
          PaneItem(
            icon: const Icon(FluentIcons.product_catalog),
            title: const Text('Products'),
            body: const ProductsView(),
          ),
        ],
      ),
    );
  }
}
