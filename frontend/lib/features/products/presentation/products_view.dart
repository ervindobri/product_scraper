import 'package:davi/davi.dart';
import 'package:fluent_ui/fluent_ui.dart'
    hide FilledButton, Colors, SliderThemeData;
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' hide IconButton, ButtonStyle, Checkbox;
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:frontend/core/app/app.dart';
import 'package:frontend/features/domain/models/product.dart';
import 'package:frontend/features/domain/models/query.dart';
import 'package:frontend/features/products/presentation/state/products_provider.dart';
import 'package:frontend/features/products/presentation/widgets/last_queries_dialog.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:url_launcher/url_launcher_string.dart';

class ProductsView extends HookConsumerWidget {
  const ProductsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // deep link: /?q=mac+mini+m4 starts with a search already submitted
    final initialQuery = Uri.base.queryParameters['q']?.trim() ?? '';
    final controller = useTextEditingController(text: initialQuery);
    final submittedQuery = useState(initialQuery);
    final minScore = useState(0);
    final priceRange = useState(RangeValues(0, 1000000));

    void search() {
      final query = controller.text.trim();
      if (query.isEmpty) return;
      submittedQuery.value = query;
      // force a refetch when the same query is searched again
      ref.invalidate(productsProvider(query));
    }

    Future<void> showHistory() async {
      final selected = await showGeneralDialog<Query?>(
        context: context,
        barrierDismissible: true,
        barrierLabel: '',
        pageBuilder: (_, anim1, anim2) => LastQueriesDialog(),
      );

      if (selected != null) {
        controller.text = selected.query;
        search();
      }
    }

    final compact = isCompactLayout(context);

    final searchBox = TextBox(
      controller: controller,
      placeholder: 'Search products…',
      prefix: const Padding(
        padding: EdgeInsetsDirectional.only(start: 10),
        child: Icon(FluentIcons.search, size: 14),
      ),
      onSubmitted: (_) => search(),
    );

    return ScaffoldPage(
      content: Padding(
        padding: EdgeInsets.all(compact ? 12 : 24),
        child: Column(
          children: [
            if (compact)
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 8,
                children: [
                  Row(
                    spacing: 8,
                    children: [
                      Expanded(child: searchBox),
                      FilledButton(
                        onPressed: search,
                        child: const Text('Search'),
                      ),
                      IconButton(
                        icon: const Icon(FluentIcons.history, size: 20),
                        onPressed: showHistory,
                      ),
                    ],
                  ),
                  Filters(
                    minScore: minScore,
                    priceRange: priceRange,
                  ),
                ],
              )
            else
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Expanded bounds the Wrap in Filters so it reflows
                  // instead of overflowing the row
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      spacing: 12,
                      children: [
                        Row(
                          spacing: 8,
                          children: [
                            SizedBox(width: 360, child: searchBox),
                            FilledButton(
                              onPressed: search,
                              child: const Text('Search'),
                            ),
                          ],
                        ),
                        Filters(
                          minScore: minScore,
                          priceRange: priceRange,
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    iconButtonMode: IconButtonMode.large,
                    style: ButtonStyle(),
                    icon: Icon(
                      FluentIcons.history,
                      size: 32,
                    ),
                    onPressed: showHistory,
                  ),
                ],
              ),
            const SizedBox(height: 8),
            Expanded(
              child: Products(
                query: submittedQuery.value,
                minScore: minScore.value,
                priceRange: priceRange.value,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class Filters extends HookWidget {
  const Filters({super.key, required this.minScore, required this.priceRange});

  final ValueNotifier<int> minScore;
  final ValueNotifier<RangeValues> priceRange;

  static const _options = [('All', 0), ('Score 50+', 50), ('Score 75+', 75)];

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    const rangeMax = 1000000.0;
    final range = useState(RangeValues(0, rangeMax));
    // Wrap so the filter row reflows instead of overflowing on narrow screens
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Text('Quick filters', style: theme.typography.caption),
        for (final (label, threshold) in _options)
          ToggleButton(
            checked: minScore.value == threshold,
            onChanged: (_) => minScore.value = threshold,
            child: Text(label),
          ),
        Row(
          mainAxisSize: MainAxisSize.min,
          spacing: 8,
          children: [
            const SizedBox(
              width: 4,
            ),
            Material(
              color: Colors.transparent,
              child: Theme(
                data: ThemeData(
                  sliderTheme: SliderThemeData(
                    valueIndicatorTextStyle: theme.typography.caption,
                    thumbColor: theme.accentColor,
                    inactiveTrackColor: theme.cardColor,
                    trackHeight: 4,
                    padding: EdgeInsets.zero,
                    thumbSize: WidgetStatePropertyAll(Size.fromWidth(12)),
                    activeTrackColor: theme.accentColor,
                  ),
                ),
                child: Column(
                  children: [
                    RangeSlider(
                      min: 0,
                      divisions: 10000,
                      max: rangeMax,
                      values: range.value,
                      onChanged: (r) {
                        range.value = r;
                      },
                    ),
                    SizedBox(
                      height: 24,
                      width: 180,
                      child: DefaultTextStyle(
                        style: theme.typography.caption!.copyWith(
                          fontSize: 10,
                          color: theme.typography.caption?.color?.withAlpha(
                            128,
                          ),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          spacing: 48,
                          children: [
                            Text(range.value.start.format),
                            Text(range.value.end.format),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            TextButton(
              onPressed: () {
                priceRange.value = range.value;
                if (kDebugMode) {
                  print("set to ${range.value}");
                }
              },
              child: Text("Apply"),
            ),
          ],
        ),
      ],
    );
  }
}

class Products extends HookConsumerWidget {
  const Products({
    super.key,
    required this.query,
    this.minScore = 0,
    this.priceRange = const RangeValues(0, 1000000000),
  });

  final String query;
  final int minScore;
  final RangeValues priceRange;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // null = no store filter applied (every store shown)
    final selectedStores = useState<Set<String>?>(null);

    if (query.isEmpty) {
      return const _CenteredState(
        icon: FluentIcons.search_and_apps,
        title: 'Search across stores',
        message: 'Type a product name and press Search to compare prices.',
      );
    }

    final products = ref.watch(productsProvider(query));
    return products.when(
      data: (list) {
        if (list == null || list.items.isEmpty) {
          return _CenteredState(
            icon: FluentIcons.search,
            title: 'No results',
            message: 'Nothing matched "$query". Try a different search.',
          );
        }
        final availableStores = list.items.map((p) => p.store).toSet().toList()
          ..sort();
        final storeFiltered = selectedStores.value == null
            ? list.items
            : list.items
                  .where((p) => selectedStores.value!.contains(p.store))
                  .toList();
        final items =
            (minScore == 0
                    ? storeFiltered
                    : storeFiltered.where((p) => p.score > minScore).toList())
                .where(
                  (p) =>
                      p.priceHuf >= priceRange.start &&
                      p.priceHuf < priceRange.end,
                )
                .toList()
              ..sort((a, b) => a.priceHuf > b.priceHuf ? -1 : 1);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _StoreFilterButton(
                available: availableStores,
                selected: selectedStores,
              ),
            ),
            Expanded(
              child: isCompactLayout(context)
                  ? _ResultsList(list: list, items: items, minScore: minScore)
                  : _ResultsTable(
                      list: list,
                      items: items,
                      minScore: minScore,
                      priceRange: priceRange,
                    ),
            ),
          ],
        );
      },
      error: (error, _) => _CenteredState(
        icon: FluentIcons.error_badge,
        title: 'Could not load products',
        message: 'Check that the API server is running, then try again.',
        action: Button(
          onPressed: () => ref.invalidate(productsProvider(query)),
          child: const Text('Try again'),
        ),
      ),
      loading: () => _CenteredState.progress(
        title: 'Searching for "$query"…',
        message:
            'A first-time search scrapes every store and can take a while.',
      ),
    );
  }
}

/// Phone-width results: one tappable card per product instead of the table.
class _ResultsList extends StatelessWidget {
  const _ResultsList({
    required this.list,
    required this.items,
    required this.minScore,
  });

  final ProductList list;
  final List<Product> items;
  final int minScore;

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    final res = theme.resources;
    final formatter = NumberFormat.decimalPattern('en_US');
    final caption = theme.typography.caption?.copyWith(
      color: res.textFillColorSecondary,
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 8,
      children: [
        Text(
          minScore == 0
              ? '${formatter.format(list.total)} results'
              : '${formatter.format(list.total)} results · showing '
                    '${formatter.format(items.length)} with score over $minScore',
          style: caption,
        ),
        Expanded(
          child: ListView.separated(
            itemCount: items.length,
            separatorBuilder: (_, _) => const SizedBox(height: 8),
            itemBuilder: (context, index) {
              final product = items[index];
              return GestureDetector(
                onTap: () => launchUrlString(product.url),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: res.cardBackgroundFillColorDefault,
                    border: Border.all(color: res.cardStrokeColorDefault),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    spacing: 6,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(product.store, style: caption),
                          ),
                          Text('#${index + 1}', style: caption),
                        ],
                      ),
                      Text(
                        product.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.typography.body,
                      ),
                      Row(
                        children: [
                          SizedBox(
                            width: 130,
                            child: _ScoreMeter(score: product.score),
                          ),
                          const Spacer(),
                          Text(
                            '${product.price.format} ${product.currency}',
                            style: theme.typography.bodyStrong,
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _ResultsTable extends StatelessWidget {
  const _ResultsTable({
    required this.list,
    required this.items,
    required this.minScore,
    required this.priceRange,
  });

  final ProductList list;
  final List<Product> items;
  final int minScore;
  final RangeValues priceRange;

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    final res = theme.resources;
    final formatter = NumberFormat.decimalPattern('en_US');
    final caption = theme.typography.caption?.copyWith(
      color: res.textFillColorSecondary,
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 8,
      children: [
        Text(
          minScore == 0
              ? '${formatter.format(list.total)} results'
              : '${formatter.format(list.total)} results · showing '
                    '${formatter.format(items.length)} with score over $minScore',
          style: caption,
        ),
        Expanded(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final tableWidth = constraints.maxWidth;
              return Container(
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(
                  color: res.cardBackgroundFillColorDefault,
                  border: Border.all(color: res.cardStrokeColorDefault),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: DaviTheme(
                  data: DaviThemeData(
                    decoration: null,
                    columnDividerColor: Colors.transparent,
                    columnDividerFillHeight: false,
                    header: HeaderThemeData(
                      color: Colors.transparent,
                      columnDividerColor: Colors.transparent,
                      bottomBorderColor: res.cardStrokeColorDefault,
                    ),
                    headerCell: HeaderCellThemeData(
                      height: 40,
                      textStyle: theme.typography.bodyStrong,
                    ),
                    row: RowThemeData(
                      fillHeight: false,
                      dividerThickness: 1,
                      dividerColor: res.dividerStrokeColorDefault,
                      hoverBackground: (index) => res.subtleFillColorSecondary,
                    ),
                    cell: CellThemeData(
                      contentHeight: 36,
                      textStyle: theme.typography.body,
                      nullValueColor: (index, hover) =>
                          res.textFillColorSecondary,
                    ),
                  ),
                  child: Davi<Product>(
                    onRowTap: (product) => launchUrlString(product.url),
                    DaviModel<Product>(
                      rows: items, // already sorted by priceHuf in Products
                      multiSortEnabled: true,
                      columns: [
                        DaviColumn(
                          name: '#',
                          width: 44,
                          resizable: false,
                          sortable: false,
                          pinStatus: PinStatus.left,
                          cellTextStyle: (params) => caption,
                          cellValue: (params) => params.rowIndex + 1,
                        ),
                        DaviColumn(
                          name: 'Store',
                          width: 140,
                          pinStatus: PinStatus.left,
                          cellValue: (params) => params.data.store,
                        ),
                        DaviColumn(
                          name: 'Product name',
                          width: tableWidth / 2.5 - 32,
                          grow: 1,
                          cellValue: (params) => params.data.name,
                        ),
                        DaviColumn(
                          name: 'Price',
                          width: 140,
                          resizable: false,
                          cellAlignment: Alignment.centerRight,
                          headerAlignment: Alignment.centerRight,
                          // sort on the HUF-normalized price so mixed
                          // currencies order correctly
                          dataComparator: (a, b, rowA, rowB) =>
                              rowA.priceHuf.compareTo(rowB.priceHuf),
                          cellValue: (params) =>
                              '${params.data.price.format} ${params.data.currency}',
                        ),
                        DaviColumn(
                          name: 'Score',
                          width: 150,
                          resizable: false,
                          dataComparator: (a, b, rowA, rowB) =>
                              rowA.score.compareTo(rowB.score),
                          cellWidget: (params) =>
                              _ScoreMeter(score: params.data.score),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

/// Quick filter button: pick which stores' results stay visible.
/// `selected.value == null` means no filter is applied (every store shown).
class _StoreFilterButton extends StatelessWidget {
  const _StoreFilterButton({required this.available, required this.selected});

  final List<String> available;
  final ValueNotifier<Set<String>?> selected;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<Set<String>?>(
      valueListenable: selected,
      builder: (context, value, _) {
        return DropDownButton(
          leading: const Icon(FluentIcons.filter, size: 14),
          title: Text(
            value == null
                ? 'Stores: All'
                : 'Stores: ${value.length}/${available.length}',
          ),
          items: [
            MenuFlyoutItemBuilder(
              builder: (context) =>
                  _StoreChecklist(available: available, selected: selected),
            ),
          ],
        );
      },
    );
  }
}

/// The flyout's content. It listens to [selected] directly (rather than
/// relying on the opener rebuilding) because a fluent_ui flyout is pushed
/// as its own route — it won't otherwise pick up state changes made while
/// it's open, which would make checkbox taps look like they do nothing.
class _StoreChecklist extends StatelessWidget {
  const _StoreChecklist({required this.available, required this.selected});

  final List<String> available;
  final ValueNotifier<Set<String>?> selected;

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    return ValueListenableBuilder<Set<String>?>(
      valueListenable: selected,
      builder: (context, value, _) {
        return SizedBox(
          width: 220,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Stores', style: theme.typography.bodyStrong),
                    HyperlinkButton(
                      onPressed: value == null
                          ? null
                          : () => selected.value = null,
                      child: const Text('Reset'),
                    ),
                  ],
                ),
              ),
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 280),
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      for (final store in available)
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          child: Checkbox(
                            checked: value?.contains(store) ?? true,
                            onChanged: (checked) {
                              final next = Set<String>.from(
                                value ?? available,
                              );
                              if (checked == true) {
                                next.add(store);
                              } else {
                                next.remove(store);
                              }
                              selected.value = next;
                            },
                            content: Text(store),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

/// Compact meter: the score as text plus a colored bar, using the theme's
/// semantic status colors (success / caution / critical).
class _ScoreMeter extends StatelessWidget {
  const _ScoreMeter({required this.score});

  final int score;

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    final res = theme.resources;
    final color = score > 75
        ? res.systemFillColorSuccess
        : score > 50
        ? res.systemFillColorCaution
        : res.systemFillColorCritical;

    return Row(
      spacing: 8,
      children: [
        SizedBox(
          width: 24,
          child: Text(
            '$score',
            textAlign: TextAlign.right,
            style: theme.typography.caption,
          ),
        ),
        Expanded(
          child: Container(
            height: 4,
            alignment: AlignmentDirectional.centerStart,
            decoration: BoxDecoration(
              color: res.controlStrokeColorDefault,
              borderRadius: BorderRadius.circular(2),
            ),
            child: FractionallySizedBox(
              widthFactor: score.clamp(0, 100) / 100,
              heightFactor: 1,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: color,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// Centered placeholder for the initial / loading / empty / error states.
class _CenteredState extends StatelessWidget {
  const _CenteredState({
    required this.title,
    required this.message,
    this.icon,
    this.action,
  }) : progress = false;

  const _CenteredState.progress({required this.title, required this.message})
    : icon = null,
      action = null,
      progress = true;

  final IconData? icon;
  final String title;
  final String message;
  final Widget? action;
  final bool progress;

  @override
  Widget build(BuildContext context) {
    final theme = FluentTheme.of(context);
    final res = theme.resources;

    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        spacing: 8,
        children: [
          if (progress)
            const Padding(
              padding: EdgeInsets.only(bottom: 8),
              child: ProgressRing(),
            )
          else if (icon != null)
            Icon(icon, size: 36, color: res.textFillColorSecondary),
          Text(title, style: theme.typography.subtitle),
          Text(
            message,
            textAlign: TextAlign.center,
            style: theme.typography.body?.copyWith(
              color: res.textFillColorSecondary,
            ),
          ),
          if (action != null)
            Padding(padding: const EdgeInsets.only(top: 8), child: action),
        ],
      ),
    );
  }
}

extension on double {
  String get format => NumberFormat('#,##0.##', 'en_US').format(this);
}
