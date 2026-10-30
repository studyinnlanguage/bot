import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/theme.dart';
import '../models/user.dart';

/// Buy Package screen — shown when user has no active license
/// Allows: (1) Buy subscription, (2) Activate existing license key
class BuyPackageScreen extends StatefulWidget {
  const BuyPackageScreen({super.key});

  @override
  State<BuyPackageScreen> createState() => _BuyPackageScreenState();
}

class _BuyPackageScreenState extends State<BuyPackageScreen> {
  String? _selectedPackageId;
  final _licenseKeyCtrl = TextEditingController();
  final _txHashCtrl = TextEditingController();
  bool _showActivateSection = false;
  final _licenseFormKey = GlobalKey<FormState>();

  // Default wallet — user can update via admin panel
  static const String _usdtWallet = 'TQn9Y2khEsLJW7B7Pm3VwBta3sBnXhXH8X';
  static const String _usdtNetwork = 'TRC20 (Tron)';

  @override
  void dispose() {
    _licenseKeyCtrl.dispose();
    _txHashCtrl.dispose();
    super.dispose();
  }

  Future<void> _activateLicense() async {
    if (!_licenseFormKey.currentState!.validate()) return;
    final auth = context.read<AuthProvider>();
    final success = await auth.activateLicense(_licenseKeyCtrl.text.trim());
    if (!success && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(auth.error ?? 'License activation failed'),
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

  void _copyWallet() {
    Clipboard.setData(const ClipboardData(text: _usdtWallet));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('📋 Wallet address copied'),
        backgroundColor: WeexionicTheme.green,
        behavior: SnackBarBehavior.floating,
        duration: Duration(seconds: 2),
      ),
    );
  }

  Future<void> _logout() async {
    await context.read<AuthProvider>().logout();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final user = auth.user;

    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        automaticallyImplyLeading: false,
        title: const Text('Choose Your Plan', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout, color: WeexionicTheme.textMuted, size: 20),
            onPressed: _logout,
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // User greeting
              if (user != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: WeexionicTheme.bgSurface,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: WeexionicTheme.border),
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 36, height: 36,
                        decoration: const BoxDecoration(
                          gradient: WeexionicTheme.brandGradient,
                          shape: BoxShape.circle,
                        ),
                        child: Center(
                          child: Text(
                            (user.name.isNotEmpty ? user.name[0] : '?').toUpperCase(),
                            style: const TextStyle(
                              fontSize: 14, fontWeight: FontWeight.w900, color: WeexionicTheme.bgBase,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(user.email, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                            const Text(
                              'No active subscription',
                              style: TextStyle(fontSize: 10, color: WeexionicTheme.red),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
              ],

              // Heading
              const Text(
                'Activate your bot',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 4),
              const Text(
                'Pick a plan below, pay USDT, and get instant access.',
                style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
              ),
              const SizedBox(height: 20),

              // Package: 1-Year
              _PackageCard(
                packageId: 'yearly',
                title: '1-Year Subscription',
                price: '\$79',
                currency: 'USDT',
                period: '/ year',
                features: const [
                  'Full bot access for 365 days',
                  'All exchanges (Binance, WEEX, PrimeXBT)',
                  'Real-time alerts (Telegram, Email, WhatsApp)',
                  'EMA 8/13/21/55 strategy',
                  'Up to 10 monitoring coins',
                  'Priority support',
                ],
                badge: 'POPULAR',
                selected: _selectedPackageId == 'yearly',
                onTap: () => setState(() => _selectedPackageId = 'yearly'),
              ),
              const SizedBox(height: 12),

              // Package: Lifetime
              _PackageCard(
                packageId: 'lifetime',
                title: 'Lifetime Access',
                price: '\$500',
                currency: 'USDT',
                period: 'one-time',
                features: const [
                  'Everything in 1-Year plan',
                  'Lifetime access — no renewals',
                  'Early access to new features',
                  'Referral bonus: \$50 per signup',
                  'Premium support channel',
                ],
                badge: 'BEST VALUE',
                highlight: true,
                selected: _selectedPackageId == 'lifetime',
                onTap: () => setState(() => _selectedPackageId = 'lifetime'),
              ),
              const SizedBox(height: 22),

              // Payment instructions (visible only when package selected)
              if (_selectedPackageId != null) ...[
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: WeexionicTheme.bgSurface,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.3)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: const [
                          Icon(Icons.account_balance_wallet, size: 16, color: WeexionicTheme.brandGold),
                          SizedBox(width: 8),
                          Text(
                            'PAYMENT INSTRUCTIONS',
                            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold, letterSpacing: 0.5),
                          ),
                        ],
                      ),
                      const SizedBox(height: 14),
                      const Text('Send USDT to:', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted)),
                      const SizedBox(height: 6),
                      Row(
                        children: [
                          Expanded(
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                              decoration: BoxDecoration(
                                color: WeexionicTheme.bgElevated,
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(color: WeexionicTheme.border),
                              ),
                              child: Text(
                                _usdtWallet,
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontFamily: 'RobotoMono',
                                  color: WeexionicTheme.textPrimary,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          IconButton(
                            onPressed: _copyWallet,
                            icon: const Icon(Icons.copy, size: 18, color: WeexionicTheme.brandGold),
                            style: IconButton.styleFrom(
                              backgroundColor: WeexionicTheme.brandGold.withOpacity(0.1),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          const Text('Network: ', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted)),
                          Text(_usdtNetwork, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: WeexionicTheme.cyan)),
                        ],
                      ),
                      const SizedBox(height: 12),
                      const Divider(color: WeexionicTheme.border),
                      const SizedBox(height: 12),
                      // Steps
                      _StepRow(num: '1', text: 'Send USDT (\$${_selectedPackageId == 'lifetime' ? '500' : '79'}) to the wallet above'),
                      _StepRow(num: '2', text: 'Take a screenshot of the transaction'),
                      _StepRow(num: '3', text: 'Contact admin on WhatsApp with your email + screenshot'),
                      _StepRow(num: '4', text: 'Admin verifies + issues license key via email'),
                      _StepRow(num: '5', text: 'Activate license key below ↓'),
                    ],
                  ),
                ),
                const SizedBox(height: 14),

                // Contact admin button
                SizedBox(
                  height: 48,
                  child: ElevatedButton.icon(
                    onPressed: () {
                      // TODO: open WhatsApp/Telegram deep link
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('Contact admin via WhatsApp: +92XXX-XXXXXXX'),
                          backgroundColor: WeexionicTheme.green,
                        ),
                      );
                    },
                    icon: const Icon(Icons.support_agent, size: 18),
                    label: const Text('CONTACT ADMIN', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, letterSpacing: 0.5)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: WeexionicTheme.green,
                      foregroundColor: WeexionicTheme.bgBase,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                ),
                const SizedBox(height: 20),
              ],

              // License activation toggle
              GestureDetector(
                onTap: () => setState(() => _showActivateSection = !_showActivateSection),
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: WeexionicTheme.bgSurface,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: WeexionicTheme.border),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.vpn_key_outlined, size: 18, color: WeexionicTheme.brandGold),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Text(
                          'Already have a license key?',
                          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                        ),
                      ),
                      Icon(
                        _showActivateSection ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                        color: WeexionicTheme.textMuted,
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),

              // License activation section
              if (_showActivateSection) ...[
                Form(
                  key: _licenseFormKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextFormField(
                        controller: _licenseKeyCtrl,
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
                      const SizedBox(height: 12),
                      SizedBox(
                        height: 48,
                        child: ElevatedButton.icon(
                          onPressed: auth.loading ? null : _activateLicense,
                          icon: auth.loading
                              ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: WeexionicTheme.bgBase))
                              : const Icon(Icons.check_circle, size: 18),
                          label: Text(
                            auth.loading ? 'Activating...' : 'ACTIVATE LICENSE',
                            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, letterSpacing: 0.5),
                          ),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: WeexionicTheme.brandGold,
                            foregroundColor: WeexionicTheme.bgBase,
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 20),
              ],

              // Sign out
              Center(
                child: TextButton(
                  onPressed: _logout,
                  child: const Text('Sign out', style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted)),
                ),
              ),
              const SizedBox(height: 20),
            ],
          ),
        ),
      ),
    );
  }
}

class _PackageCard extends StatelessWidget {
  final String packageId;
  final String title;
  final String price;
  final String currency;
  final String period;
  final List<String> features;
  final String badge;
  final bool highlight;
  final bool selected;
  final VoidCallback onTap;

  const _PackageCard({
    required this.packageId,
    required this.title,
    required this.price,
    required this.currency,
    required this.period,
    required this.features,
    required this.badge,
    this.highlight = false,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: WeexionicTheme.bgSurface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: selected
                ? WeexionicTheme.brandGold
                : (highlight ? WeexionicTheme.brandGold.withOpacity(0.3) : WeexionicTheme.border),
            width: selected ? 2 : 1,
          ),
          boxShadow: selected ? WeexionicTheme.goldGlow : null,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    gradient: highlight ? WeexionicTheme.brandGradient : null,
                    color: highlight ? null : WeexionicTheme.brandGold.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    badge,
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w800,
                      color: highlight ? WeexionicTheme.bgBase : WeexionicTheme.brandGold,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  price,
                  style: const TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                    color: WeexionicTheme.brandGold,
                  ),
                ),
                const SizedBox(width: 4),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    currency,
                    style: const TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
                  ),
                ),
                const SizedBox(width: 4),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    period,
                    style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ...features.map((f) => Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.check_circle, size: 14, color: WeexionicTheme.green),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      f,
                      style: const TextStyle(fontSize: 11, color: WeexionicTheme.textSecondary, height: 1.4),
                    ),
                  ),
                ],
              ),
            )),
          ],
        ),
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  final String num;
  final String text;
  const _StepRow({required this.num, required this.text});

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
