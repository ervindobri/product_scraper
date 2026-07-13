import 'package:fluent_ui/fluent_ui.dart';
import 'package:frontend/core/app/app.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: App()));
}
