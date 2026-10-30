import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../widgets/bottom_nav.dart';
import 'dashboard_screen.dart';
import 'terminal_screen.dart';
import 'positions_screen.dart';
import 'history_screen.dart';
import 'settings_screen.dart';

/// Main app shell — shown only when user is authenticated + license active
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
    // Trigger initial data fetch on bot provider (auth confirmed by auth_gate)
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<BotProvider>().start();
    });
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: WeexionicTheme.bgSurface,
        title: const Text('Sign Out?'),
        content: const Text('You\'ll need to sign in again to access the bot. Your settings will be saved.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: WeexionicTheme.red),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Sign Out'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await context.read<BotProvider>().stop();
      await context.read<AuthProvider>().logout();
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final user = auth.user;

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
