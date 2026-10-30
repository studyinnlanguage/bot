import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/theme.dart';
import 'webview_login_screen.dart';

/// Login screen — single Google sign-in button (no email/password forms)
/// Tapping opens WebView to /auth/google → captures session cookie after OAuth
class LoginScreen extends StatelessWidget {
  const LoginScreen({super.key});

  Future<void> _signInWithGoogle(BuildContext context) async {
    final auth = context.read<AuthProvider>();
    final result = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => WebViewLoginScreen(
          onLoginComplete: () async {
            // Cookie captured — fetch user profile + license status
            await auth.refresh();
          },
        ),
      ),
    );

    // If refresh didn't transition to authenticated state, show error
    if (result == true && auth.state == AuthState.unauthenticated && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Login succeeded but no active license found. Please activate a license.'),
          backgroundColor: WeexionicTheme.brandGold,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(flex: 2),

              // Logo
              Center(
                child: Column(
                  children: [
                    ShaderMask(
                      shaderCallback: (b) => WeexionicTheme.brandGradient.createShader(b),
                      child: const Text(
                        'WEEXIONIC',
                        style: TextStyle(
                          fontSize: 40,
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
                    Container(
                      width: 80, height: 80,
                      decoration: BoxDecoration(
                        gradient: WeexionicTheme.brandGradientSoft,
                        borderRadius: BorderRadius.circular(24),
                        border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.3)),
                      ),
                      child: const Icon(
                        Icons.show_chart,
                        size: 44,
                        color: WeexionicTheme.brandGold,
                      ),
                    ),
                    const SizedBox(height: 24),
                    const Text(
                      'Trade smarter with EMA 8/13/21/55',
                      style: TextStyle(fontSize: 13, color: WeexionicTheme.textSecondary),
                      textAlign: TextAlign.center,
                    ),
                  ],
                ),
              ),

              const Spacer(flex: 3),

              // Google sign-in button
              _GoogleSignInButton(
                onTap: () => _signInWithGoogle(context),
              ),
              const SizedBox(height: 16),

              // License info
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: WeexionicTheme.bgSurface,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: WeexionicTheme.border),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.vpn_key_outlined, size: 16, color: WeexionicTheme.brandGold),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: const [
                          Text(
                            'License Required',
                            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
                          ),
                          SizedBox(height: 2),
                          Text(
                            'After signing in with Google, you\'ll need a license key (TRDBOT-XXXX-XXXX-XXXX-XXXX) to access the bot. Get it from your admin.',
                            style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, height: 1.5),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),

              // Terms
              Center(
                child: Text(
                  'By continuing you agree to our\nTerms of Service & Risk Disclaimer',
                  style: TextStyle(fontSize: 10, color: WeexionicTheme.textFaint, height: 1.5),
                  textAlign: TextAlign.center,
                ),
              ),

              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}

/// Google sign-in button — official Google colors
class _GoogleSignInButton extends StatelessWidget {
  final VoidCallback onTap;
  const _GoogleSignInButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          height: 54,
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Google "G" logo (multi-color SVG-ish via Stack)
              _GoogleLogo(),
              const SizedBox(width: 14),
              const Text(
                'Continue with Google',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF1F1F1F),
                  fontFamily: 'Roboto',
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Simplified Google "G" logo using Container widgets (no asset needed)
class _GoogleLogo extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 22, height: 22,
      child: CustomPaint(painter: _GoogleLogoPainter()),
    );
  }
}

class _GoogleLogoPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final cx = w / 2;
    final cy = h / 2;
    final r = w * 0.46;

    // White background circle
    final bgPaint = Paint()..color = Colors.white;
    canvas.drawCircle(Offset(cx, cy), r, bgPaint);

    // Multi-color arcs (simplified Google G)
    final strokeW = w * 0.13;
    final rect = Rect.fromCircle(center: Offset(cx, cy), radius: r - strokeW / 2);

    // Blue (bottom-right) — 50%
    canvas.drawArc(
      rect,
      0,
      3.14,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeW
        ..color = const Color(0xFF4285F4),
    );
    // Red (top-left quarter)
    canvas.drawArc(
      rect,
      3.14,
      0.78,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeW
        ..color = const Color(0xFFEA4335),
    );
    // Yellow (left quarter)
    canvas.drawArc(
      rect,
      3.92,
      0.78,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeW
        ..color = const Color(0xFFFBBC05),
    );
    // Green (bottom-left quarter)
    canvas.drawArc(
      rect,
      4.70,
      0.78,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeW
        ..color = const Color(0xFF34A853),
    );

    // Inner horizontal bar (the G's crossbar) — blue
    canvas.drawRect(
      Rect.fromLTWH(cx - strokeW * 0.3, cy - strokeW / 2, w * 0.42, strokeW),
      Paint()..color = const Color(0xFF4285F4),
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
