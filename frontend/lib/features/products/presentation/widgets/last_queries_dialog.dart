import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter/material.dart' hide Colors;
import 'package:frontend/features/products/presentation/state/queries_provider.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:intl/intl.dart';

class LastQueriesDialog extends ConsumerWidget {
  const LastQueriesDialog({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final lastQueries = ref.watch(queriesProvider);
    final theme = FluentTheme.of(context);
    return ContentDialog(
      title: Text("Last queries"),
      // cap at 500 but let the dialog shrink on phone-width screens
      constraints: const BoxConstraints(maxWidth: 500),
      content: Material(
        color: Colors.transparent,
        child: ClipRRect(
          child: lastQueries.when(
            data: (data) => data == null
                ? const SizedBox()
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Text(
                          "total: ${data.totalCount}",
                          style: theme.typography.caption,
                        ),
                      ),
                      DefaultTextStyle(
                        style: theme.typography.caption!.copyWith(
                          color: theme.activeColor.withValues(alpha: 0.5),
                        ),
                        child: Row(
                          children: [
                            Expanded(child: Text('query')),
                            Expanded(child: Text('resultCount')),
                            Expanded(child: Text('lastSearchedDate')),
                          ],
                        ),
                      ),
                      ...data.items.map(
                        (e) => DefaultTextStyle(
                          style: theme.typography.body!,
                          child: InkWell(
                            onTap: () {
                              Navigator.pop(context, e);
                            },

                            child: Padding(
                              padding: const EdgeInsets.all(4.0),
                              child: Row(
                                children: [
                                  Expanded(child: Text(e.query)),
                                  Expanded(
                                    child: Text(e.resultCount.toString()),
                                  ),
                                  Expanded(
                                    child: Text(
                                      e.lastSearchedDate
                                              ?.toLocal()
                                              .formatReadable ??
                                          'Never',
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
            error: (Object error, StackTrace stackTrace) {
              return Text(
                error.toString(),
                style: theme.typography.bodyStrong!.copyWith(
                  color: Colors.errorPrimaryColor,
                ),
              );
            },
            loading: () => Center(
              child: CircularProgressIndicator(),
            ),
          ),
        ),
      ),
    );
  }
}

extension on DateTime {
  String get formatReadable {
    final format = DateFormat.yMMMMEEEEd();
    return format.format(this);
  }
}
