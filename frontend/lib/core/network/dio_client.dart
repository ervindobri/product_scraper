import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'dio_client.g.dart';

@riverpod
Dio dioClient(Ref ref) {
  // TODO: change after deploy
  return Dio(BaseOptions(baseUrl: "http://127.0.0.1:8000/api/"));
}
