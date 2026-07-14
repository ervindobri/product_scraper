import 'package:davi/davi.dart';
import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/core/app/app.dart';
import 'package:frontend/features/domain/models/product.dart';
import 'package:frontend/features/domain/models/query.dart';
import 'package:frontend/features/domain/repositories/product_repository.dart';
import 'package:frontend/features/products/presentation/products_view.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

class FakeProductRepository implements IProductRepository {
  @override
  Future<ProductList?> search({required String query}) async {
    return ProductList(
      total: 1,
      items: [
        Product(
          store: '1',
          name: 'Test product',
          url: 'https://example.com',
          price: 9.99,
          priceHuf: 3990,
          currency: 'HUF',
          score: 80,
        ),
      ],
    );
  }

  @override
  Future<QueriesList?> lastQueries() {
    // TODO: implement lastQueries
    throw UnimplementedError();
  }
}

void main() {
  Future<void> pumpApp(WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          productRepositoryProvider.overrideWith(
            (ref) => FakeProductRepository(),
          ),
        ],
        child: const App(),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('searching renders the results table', (
    WidgetTester tester,
  ) async {
    await pumpApp(tester);

    expect(find.byType(HomeShell), findsOneWidget);
    expect(find.byType(ProductsView), findsOneWidget);
    // nothing searched yet
    expect(find.text('Search across stores'), findsOneWidget);

    await tester.enterText(find.byType(TextBox), 'mac mini');
    await tester.tap(find.text('Search'));
    await tester.pumpAndSettle();

    expect(find.byType(Davi<Product>), findsOneWidget);
  });

  testWidgets('phone width uses the card list instead of the table', (
    WidgetTester tester,
  ) async {
    // iPhone-ish logical size; overflows throw in tests, so this also
    // guards the compact layout against regressions
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await pumpApp(tester);

    await tester.enterText(find.byType(TextBox), 'mac mini');
    await tester.tap(find.text('Search'));
    await tester.pumpAndSettle();

    expect(find.byType(Davi<Product>), findsNothing);
    expect(find.text('Test product'), findsOneWidget);
  });
}
