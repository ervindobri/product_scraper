// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'products_provider.dart';

// **************************************************************************
// RiverpodGenerator
// **************************************************************************

// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, type=warning

@ProviderFor(products)
const productsProvider = ProductsFamily._();

final class ProductsProvider
    extends
        $FunctionalProvider<
          AsyncValue<ProductList?>,
          ProductList?,
          FutureOr<ProductList?>
        >
    with $FutureModifier<ProductList?>, $FutureProvider<ProductList?> {
  const ProductsProvider._({
    required ProductsFamily super.from,
    required String super.argument,
  }) : super(
         retry: null,
         name: r'productsProvider',
         isAutoDispose: true,
         dependencies: null,
         $allTransitiveDependencies: null,
       );

  @override
  String debugGetCreateSourceHash() => _$productsHash();

  @override
  String toString() {
    return r'productsProvider'
        ''
        '($argument)';
  }

  @$internal
  @override
  $FutureProviderElement<ProductList?> $createElement(
    $ProviderPointer pointer,
  ) => $FutureProviderElement(pointer);

  @override
  FutureOr<ProductList?> create(Ref ref) {
    final argument = this.argument as String;
    return products(ref, argument);
  }

  @override
  bool operator ==(Object other) {
    return other is ProductsProvider && other.argument == argument;
  }

  @override
  int get hashCode {
    return argument.hashCode;
  }
}

String _$productsHash() => r'90e289b858d9a036a497bcdb040ee587702587eb';

final class ProductsFamily extends $Family
    with $FunctionalFamilyOverride<FutureOr<ProductList?>, String> {
  const ProductsFamily._()
    : super(
        retry: null,
        name: r'productsProvider',
        dependencies: null,
        $allTransitiveDependencies: null,
        isAutoDispose: true,
      );

  ProductsProvider call(String query) =>
      ProductsProvider._(argument: query, from: this);

  @override
  String toString() => r'productsProvider';
}
