import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:path_provider/path_provider.dart';

import 'core/theme.dart';
import 'core/auth_provider.dart';
import 'core/bot_provider.dart';
import 'screens/auth_gate.dart';

void main() {
  // Ensure path_provider is initialized for cookie jar storage
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const WeexionicApp());
}

class WeexionicApp extends StatelessWidget {
  const WeexionicApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()),
        ChangeNotifierProvider(create: (_) => BotProvider()),
      ],
      child: MaterialApp(
        title: 'WEEXIONIC',
        debugShowCheckedModeBanner: false,
        theme: WeexionicTheme.darkTheme,
        home: const AuthGate(),
      ),
    );
  }
}
