
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:frontend/core/network/dio_client.dart';
import 'package:frontend/features/domain/models/product.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';


part 'product_repository.g.dart';

abstract class IProductRepository {
  Future<ProductList?> search({required String query});
}


class ProductRepository implements IProductRepository {
  ProductRepository({required this.client});
  
  final Dio client;

  @override
  Future<ProductList?> search({required String query}) async {
    try {
      final result = await client.get(
        'queries/search/',
        queryParameters: {'query': query},
      );
      // Dio already decodes application/json responses into a Map
      final data = result.data;
      if (data is Map<String, dynamic>) {
        return ProductList.from(data);
      }

      return null;
    } catch (e, _) {
      if (kDebugMode) {
        print(e);
      }
      rethrow;
    }
  }

}


@riverpod
IProductRepository productRepository(Ref ref){
  return ProductRepository(client: ref.watch(dioClientProvider));
}