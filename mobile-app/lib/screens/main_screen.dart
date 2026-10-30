import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../widgets/bottom_nav.dart';
import 'dashboard_screen.dart';
import 'terminal_screen.dart';
import 'positions_screen.dart';
import 'history_screen.dart';
import 'settings_screen.dart';

/// Main app shell — bottom nav (5 items) + IndexedStack
/// Alerts screen accessed via Settings → "Alerts & Channels" shortcut
class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _index = 0;

  late final List<Widget> _screens;

  @override
  void initState() {
    super.initState();
    _screens = const [
      DashboardScreen(),
      TerminalScreen(),
      PositionsScreen(),
      HistoryScreen(),
      SettingsScreen(),
    ];
    // Trigger initial data fetch
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<BotProvider>().refreshAll();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: IndexedStack(
        index: _index,
        children: _screens,
      ),
      bottomNavigationBar: WeexionicBottomNav(
        currentIndex: _index,
        onTap: (i) => setState(() => _index = i),
      ),
    );
  }
}
