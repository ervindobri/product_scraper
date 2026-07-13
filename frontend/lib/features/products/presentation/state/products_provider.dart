
import 'package:frontend/features/domain/models/product.dart';
import 'package:frontend/features/domain/repositories/product_repository.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'products_provider.g.dart';

@riverpod
Future<ProductList?> products(Ref ref, String query){
  return ref.watch(productRepositoryProvider).search(query: query);
}