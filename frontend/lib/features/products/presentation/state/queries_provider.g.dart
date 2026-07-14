// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'queries_provider.dart';

// **************************************************************************
// RiverpodGenerator
// **************************************************************************

// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, type=warning

@ProviderFor(queries)
const queriesProvider = QueriesProvider._();

final class QueriesProvider
    extends
        $FunctionalProvider<
          AsyncValue<QueriesList?>,
          QueriesList?,
          FutureOr<QueriesList?>
        >
    with $FutureModifier<QueriesList?>, $FutureProvider<QueriesList?> {
  const QueriesProvider._()
    : super(
        from: null,
        argument: null,
        retry: null,
        name: r'queriesProvider',
        isAutoDispose: true,
        dependencies: null,
        $allTransitiveDependencies: null,
      );

  @override
  String debugGetCreateSourceHash() => _$queriesHash();

  @$internal
  @override
  $FutureProviderElement<QueriesList?> $createElement(
    $ProviderPointer pointer,
  ) => $FutureProviderElement(pointer);

  @override
  FutureOr<QueriesList?> create(Ref ref) {
    return queries(ref);
  }
}

String _$queriesHash() => r'c5c75ff57751f4b668f58ed26c4f8ec44977f1e4';
