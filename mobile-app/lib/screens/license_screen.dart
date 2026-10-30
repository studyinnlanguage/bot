import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/theme.dart';
import '../models/user.dart';

class LicenseScreen extends StatefulWidget {
  const LicenseScreen({super.key});

  @override
  State<LicenseScreen> createState() => _LicenseScreenState();
}

class _LicenseScreenState extends State<LicenseScreen> {
  final _keyCtrl = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  @override
  void dispose() {
    _keyCtrl.dispose();
    super.dispose();
  }

  Future<void> _activate() async {
    if (!_formKey.currentState!.validate()) return;
    final auth = context.read<AuthProvider>();
    final success = await auth.activateLicense(_keyCtrl.text);
    if (!success && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(auth.error ?? 'Activation failed'),
          backgroundColor: WeexionicTheme.red,
          behavior: SnackBarBehavior.floating,
        ),
      );
    } else if (success && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('✅ License activated! Welcome to WEEXIONIC.'),
          backgroundColor: WeexionicTheme.green,
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  Future<void> _logout() async {
    await context.read<AuthProvider>().logout();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final user = auth.user;
    final sub = user?.subscription;

    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.logout, color: WeexionicTheme.textSecondary, size: 20),
            onPressed: _logout,
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Header
                Center(
                  child: Column(
                    children: [
                      Container(
                        width: 72, height: 72,
                        decoration: BoxDecoration(
                          gradient: WeexionicTheme.brandGradientSoft,
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.3)),
                        ),
                        child: const Icon(Icons.vpn_key, size: 36, color: WeexionicTheme.brandGold),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Activate Your License',
                        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Welcome, ${user?.name ?? "Trader"}!',
                        style: const TextStyle(fontSize: 13, color: WeexionicTheme.textSecondary),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        user?.email ?? '',
                        style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 32),

                // Status card
                if (sub != null) ...[
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: WeexionicTheme.bgSurface,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(
                        color: sub.isExpired
                            ? WeexionicTheme.red.withOpacity(0.3)
                            : WeexionicTheme.brandGold.withOpacity(0.3),
                      ),
                    ),
                    child: Column(
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text('Current Status', style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted)),
                            _StatusBadge(status: sub.status, active: sub.active),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text('Plan', style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted)),
                            Text(sub.displayPlan, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text('Remaining', style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted)),
                            Text(
                              sub.displayDaysLeft,
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                                color: sub.isLifetime ? WeexionicTheme.brandGold : (sub.daysLeft < 7 ? WeexionicTheme.red : WeexionicTheme.green),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),
                ],

                // License key input
                const _Label('License Key'),
                TextFormField(
                  controller: _keyCtrl,
                  textCapitalization: TextCapitalization.characters,
                  style: const TextStyle(fontSize: 14, color: WeexionicTheme.textPrimary, fontFamily: 'RobotoMono', letterSpacing: 1),
                  decoration: const InputDecoration(
                    hintText: 'TRDBOT-XXXX-XXXX-XXXX-XXXX',
                    prefixIcon: Icon(Icons.vpn_key_outlined, size: 18, color: WeexionicTheme.textMuted),
                  ),
                  validator: (v) {
                    if (v == null || v.trim().isEmpty) return 'License key is required';
                    final cleaned = v.trim().toUpperCase();
                    if (!RegExp(r'^TRDBOT-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}$').hasMatch(cleaned)) {
                      return 'Format: TRDBOT-XXXX-XXXX-XXXX-XXXX';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 24),

                // Activate button
                SizedBox(
                  height: 50,
                  child: ElevatedButton.icon(
                    onPressed: auth.loading ? null : _activate,
                    icon: auth.loading
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: WeexionicTheme.bgBase))
                        : const Icon(Icons.check_circle, size: 18),
                    label: Text(
                      auth.loading ? 'Activating...' : 'ACTIVATE LICENSE',
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 1),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: WeexionicTheme.brandGold,
                      foregroundColor: WeexionicTheme.bgBase,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
                const SizedBox(height: 28),

                // Help card
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: WeexionicTheme.bgSurface,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: WeexionicTheme.border),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'HOW TO GET A LICENSE',
                        style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold, letterSpacing: 0.5),
                      ),
                      const SizedBox(height: 10),
                      _HelpStep(num: '1', text: 'Purchase 1-Year (\$79 USDT) or Lifetime (\$500 USDT) plan from your admin.'),
                      _HelpStep(num: '2', text: 'You\'ll receive a license key via email in TRDBOT-XXXX-XXXX-XXXX-XXXX format.'),
                      _HelpStep(num: '3', text: 'Paste the key above and tap Activate.'),
                      _HelpStep(num: '4', text: 'License is bound to your account — single use only.'),
                    ],
                  ),
                ),
                const SizedBox(height: 20),

                // Logout
                Center(
                  child: TextButton(
                    onPressed: _logout,
                    child: const Text(
                      'Sign out',
                      style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
                    ),
                  ),
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

class _StatusBadge extends StatelessWidget {
  final String status;
  final bool active;
  const _StatusBadge({required this.status, required this.active});

  @override
  Widget build(BuildContext context) {
    Color color;
    String label;
    if (active) {
      color = WeexionicTheme.green;
      label = 'ACTIVE';
    } else if (status == 'expired') {
      color = WeexionicTheme.red;
      label = 'EXPIRED';
    } else {
      color = WeexionicTheme.textMuted;
      label = 'INACTIVE';
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color),
      ),
    );
  }
}

class _HelpStep extends StatelessWidget {
  final String num;
  final String text;
  const _HelpStep({required this.num, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 18, height: 18,
            decoration: const BoxDecoration(
              gradient: WeexionicTheme.brandGradient,
              shape: BoxShape.circle,
            ),
            child: Center(
              child: Text(
                num,
                style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w900, color: WeexionicTheme.bgBase),
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 11, color: WeexionicTheme.textSecondary, height: 1.5),
            ),
          ),
        ],
      ),
    );
  }
}
