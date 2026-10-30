import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/bot_provider.dart';
import '../core/theme.dart';
import 'login_screen.dart';
import 'buy_package_screen.dart';
import 'main_screen.dart';

/// Auth gate — decides which screen to show based on auth state
/// initializing       → splash
/// unauthenticated    → login screen
/// authenticatedNoLicense → buy package screen (new signups / expired licenses)
/// authenticated      → main bot app (has active license)
class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();

    switch (auth.state) {
      case AuthState.initializing:
        return const _SplashScreen();

      case AuthState.unauthenticated:
        return const LoginScreen();

      case AuthState.authenticatedNoLicense:
        return const BuyPackageScreen();

      case AuthState.authenticated:
        return _AuthenticatedShell();
    }
  }
}

class _AuthenticatedShell extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final bot = context.read<BotProvider>();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      bot.start();
    });
    return const MainScreen();
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 80, height: 80,
              decoration: BoxDecoration(
                gradient: WeexionicTheme.brandGradient,
                borderRadius: BorderRadius.circular(24),
                boxShadow: WeexionicTheme.goldGlow,
              ),
              child: const Icon(
                Icons.show_chart_rounded,
                size: 44,
                color: WeexionicTheme.bgBase,
              ),
            ),
            const SizedBox(height: 20),
            const WeexionicLogo(size: 28),
            const SizedBox(height: 8),
            const Text(
              'FUTURES BOT',
              style: TextStyle(
                fontSize: 11,
                color: WeexionicTheme.textMuted,
                letterSpacing: 4,
                fontWeight: FontWeight.w500,
              ),
            ),
            const SizedBox(height: 32),
            const SizedBox(
              width: 28, height: 28,
              child: CircularProgressIndicator(
                color: WeexionicTheme.brandGold,
                strokeWidth: 2.5,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
