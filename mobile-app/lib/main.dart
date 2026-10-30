import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/theme.dart';
import 'core/bot_provider.dart';
import 'screens/main_screen.dart';

void main() {
  runApp(const WeexionicApp());
}

class WeexionicApp extends StatelessWidget {
  const WeexionicApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => BotProvider(),
      child: MaterialApp(
        title: 'WEEXIONIC',
        debugShowCheckedModeBanner: false,
        theme: WeexionicTheme.darkTheme,
        home: const MainScreen(),
      ),
    );
  }
}
