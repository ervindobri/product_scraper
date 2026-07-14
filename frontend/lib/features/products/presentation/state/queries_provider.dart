import 'package:frontend/features/domain/models/query.dart';
import 'package:frontend/features/domain/repositories/product_repository.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'queries_provider.g.dart';

@riverpod
Future<QueriesList?> queries(Ref ref) {
  return ref.watch(productRepositoryProvider).lastQueries();
}
