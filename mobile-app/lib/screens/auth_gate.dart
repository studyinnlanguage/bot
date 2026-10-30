import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/bot_provider.dart';
import '../core/theme.dart';
import 'login_screen.dart';
import 'license_screen.dart';
import 'main_screen.dart';

/// Auth gate — decides which screen to show based on auth state
/// initializing → splash
/// unauthenticated → login screen
/// authenticatedNoLicense → license activation screen
/// authenticated → main bot app
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
        return const LicenseScreen();

      case AuthState.authenticated:
        // Start the bot provider (connects socket + fetches initial data)
        return _AuthenticatedShell();
    }
  }
}

class _AuthenticatedShell extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final bot = context.read<BotProvider>();
    // Start the bot provider once — fire and forget
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
            // Logo
            ShaderMask(
              shaderCallback: (bounds) => WeexionicTheme.brandGradient.createShader(bounds),
              child: const Text(
                'WEEXIONIC',
                style: TextStyle(
                  fontSize: 36,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 2,
                  color: Colors.white,
                ),
              ),
            ),
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
              width: 32, height: 32,
              child: CircularProgressIndicator(
                color: WeexionicTheme.brandGold,
                strokeWidth: 2.5,
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              'Connecting...',
              style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
            ),
          ],
        ),
      ),
    );
  }
}
