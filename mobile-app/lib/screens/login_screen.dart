import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/theme.dart';
import 'signup_screen.dart';
import 'webview_login_screen.dart';

/// Login screen — Email/Password + Google sign-in
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _obscure = true;
  final _formKey = GlobalKey<FormState>();

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  Future<void> _signIn() async {
    if (!_formKey.currentState!.validate()) return;
    final auth = context.read<AuthProvider>();
    final success = await auth.login(
      email: _emailCtrl.text.trim(),
      password: _passwordCtrl.text,
    );
    if (!success && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(auth.error ?? 'Login failed'),
          backgroundColor: WeexionicTheme.red,
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  Future<void> _signInWithGoogle() async {
    final auth = context.read<AuthProvider>();
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => WebViewLoginScreen(
          onLoginComplete: () async {
            await auth.refresh();
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Logo header
                Center(
                  child: Column(
                    children: [
                      // Logo placeholder (user will provide later)
                      Container(
                        width: 72, height: 72,
                        decoration: BoxDecoration(
                          gradient: WeexionicTheme.brandGradient,
                          borderRadius: BorderRadius.circular(20),
                          boxShadow: WeexionicTheme.goldGlow,
                        ),
                        child: const Icon(
                          Icons.show_chart_rounded,
                          size: 44,
                          color: WeexionicTheme.bgBase,
                        ),
                      ),
                      const SizedBox(height: 16),
                      const WeexionicLogo(size: 28),
                      const SizedBox(height: 6),
                      const Text(
                        'FUTURES BOT',
                        style: TextStyle(
                          fontSize: 10,
                          color: WeexionicTheme.textMuted,
                          letterSpacing: 4,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const SizedBox(height: 24),
                      const Text(
                        'Welcome back',
                        style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'Sign in to continue trading',
                        style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 32),

                // Email
                _Label('Email'),
                TextFormField(
                  controller: _emailCtrl,
                  keyboardType: TextInputType.emailAddress,
                  style: const TextStyle(fontSize: 14, color: WeexionicTheme.textPrimary),
                  decoration: const InputDecoration(
                    hintText: 'you@example.com',
                    prefixIcon: Icon(Icons.email_outlined, size: 18, color: WeexionicTheme.textMuted),
                  ),
                  validator: (v) {
                    if (v == null || v.trim().isEmpty) return 'Email is required';
                    if (!RegExp(r'^[^@]+@[^@]+\.[^@]+').hasMatch(v.trim())) return 'Enter a valid email';
                    return null;
                  },
                ),
                const SizedBox(height: 14),

                // Password
                _Label('Password'),
                TextFormField(
                  controller: _passwordCtrl,
                  obscureText: _obscure,
                  style: const TextStyle(fontSize: 14, color: WeexionicTheme.textPrimary),
                  decoration: InputDecoration(
                    hintText: '••••••••',
                    prefixIcon: const Icon(Icons.lock_outline, size: 18, color: WeexionicTheme.textMuted),
                    suffixIcon: IconButton(
                      icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility, size: 18, color: WeexionicTheme.textMuted),
                      onPressed: () => setState(() => _obscure = !_obscure),
                    ),
                  ),
                  validator: (v) {
                    if (v == null || v.isEmpty) return 'Password is required';
                    if (v.length < 8) return 'Min 8 characters';
                    return null;
                  },
                ),
                const SizedBox(height: 24),

                // Sign In button — Binance yellow with glow
                SizedBox(
                  height: 52,
                  child: ElevatedButton(
                    onPressed: auth.loading ? null : _signIn,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: WeexionicTheme.brandGold,
                      foregroundColor: WeexionicTheme.bgBase,
                      elevation: 0,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      padding: EdgeInsets.zero,
                    ),
                    child: auth.loading
                        ? const SizedBox(
                            width: 22, height: 22,
                            child: CircularProgressIndicator(strokeWidth: 2.5, color: WeexionicTheme.bgBase),
                          )
                        : const Text(
                            'SIGN IN',
                            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, letterSpacing: 1.2),
                          ),
                  ),
                ),
                const SizedBox(height: 18),

                // Divider
                Row(
                  children: const [
                    Expanded(child: Divider(color: WeexionicTheme.border)),
                    Padding(
                      padding: EdgeInsets.symmetric(horizontal: 12),
                      child: Text('OR', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted, letterSpacing: 1)),
                    ),
                    Expanded(child: Divider(color: WeexionicTheme.border)),
                  ],
                ),
                const SizedBox(height: 18),

                // Google button
                SizedBox(
                  height: 52,
                  child: Material(
                    color: WeexionicTheme.bgElevated,
                    borderRadius: BorderRadius.circular(12),
                    child: InkWell(
                      onTap: auth.loading ? null : _signInWithGoogle,
                      borderRadius: BorderRadius.circular(12),
                      child: Container(
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: WeexionicTheme.borderLight),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            _GoogleLogo(size: 20),
                            const SizedBox(width: 12),
                            const Text(
                              'Continue with Google',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w600,
                                color: WeexionicTheme.textPrimary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 24),

                // Sign up link
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Text(
                      "Don't have an account? ",
                      style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
                    ),
                    GestureDetector(
                      onTap: () {
                        Navigator.of(context).push(
                          MaterialPageRoute(builder: (_) => const SignupScreen()),
                        );
                      },
                      child: const Text(
                        'Sign up',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: WeexionicTheme.brandGold,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Label extends StatelessWidget {
  final String text;
  const _Label(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 6),
      child: Text(
        text,
        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: WeexionicTheme.textSecondary),
      ),
    );
  }
}

/// Google "G" logo (multi-color, no asset needed)
class _GoogleLogo extends StatelessWidget {
  final double size;
  const _GoogleLogo({required this.size});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size, height: size,
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

    canvas.drawCircle(Offset(cx, cy), r, Paint()..color = Colors.white);

    final strokeW = w * 0.13;
    final rect = Rect.fromCircle(center: Offset(cx, cy), radius: r - strokeW / 2);

    canvas.drawArc(rect, 0, 3.14, false, Paint()..style = PaintingStyle.stroke..strokeWidth = strokeW..color = const Color(0xFF4285F4));
    canvas.drawArc(rect, 3.14, 0.78, false, Paint()..style = PaintingStyle.stroke..strokeWidth = strokeW..color = const Color(0xFFEA4335));
    canvas.drawArc(rect, 3.92, 0.78, false, Paint()..style = PaintingStyle.stroke..strokeWidth = strokeW..color = const Color(0xFFFBBC05));
    canvas.drawArc(rect, 4.70, 0.78, false, Paint()..style = PaintingStyle.stroke..strokeWidth = strokeW..color = const Color(0xFF34A853));

    canvas.drawRect(
      Rect.fromLTWH(cx - strokeW * 0.3, cy - strokeW / 2, w * 0.42, strokeW),
      Paint()..color = const Color(0xFF4285F4),
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
