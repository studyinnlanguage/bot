import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/auth_provider.dart';
import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../models/bot_config.dart';
import '../widgets/common.dart';
import '../widgets/premium.dart';
import 'alerts_screen.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late BotConfig _cfg;
  bool _initialized = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_initialized) {
      _cfg = context.read<BotProvider>().config;
      _initialized = true;
    }
  }

  void _save() async {
    final p = context.read<BotProvider>();
    try {
      await p.saveConfig(_cfg);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('✅ Settings saved! Bot will apply on next start.'),
            backgroundColor: WeexionicTheme.green,
            duration: Duration(seconds: 3),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ Save failed: $e'), backgroundColor: WeexionicTheme.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(context),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
                children: [
                  // Account info card
                  _AccountCard(),
                  const SizedBox(height: 12),
                  // Alerts shortcut
                  _AlertsShortcut(),
                  const SizedBox(height: 12),
                  _ExchangeSection(cfg: _cfg, onChanged: _update),
                  const SizedBox(height: 12),
                  _CoinsSection(cfg: _cfg, onChanged: _update),
                  const SizedBox(height: 12),
                  _StrategySection(cfg: _cfg, onChanged: _update),
                  const SizedBox(height: 12),
                  _RiskSection(cfg: _cfg, onChanged: _update),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: _save,
                      icon: const Icon(Icons.save, size: 18),
                      label: const Text('SAVE SETTINGS', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _update(BotConfig newCfg) {
    setState(() => _cfg = newCfg);
  }

  Widget _buildAppBar(BuildContext context) {
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        children: [
          const Icon(Icons.settings, color: WeexionicTheme.textSecondary, size: 22),
          const SizedBox(width: 12),
          const Expanded(
            child: Text('Strategy & Settings', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          ),
          IconButton(
            icon: const Icon(Icons.save, color: WeexionicTheme.brandGold, size: 22),
            onPressed: _save,
          ),
        ],
      ),
    );
  }
}

/// Premium account card — gradient avatar + plan badge + days-left progress bar
class _AccountCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    final user = auth.user;
    if (user == null) return const SizedBox.shrink();
    final sub = user.subscription;

    // Progress bar: days remaining / total plan days
    double progress;
    if (sub.isLifetime) {
      progress = 1.0;
    } else if (sub.plan == 'yearly') {
      progress = (sub.daysLeft / 365).clamp(0.0, 1.0);
    } else {
      progress = (sub.daysLeft / 30).clamp(0.0, 1.0);
    }
    if (!sub.isActive) progress = 0;

    final progressColor = sub.isLifetime
        ? WeexionicTheme.brandGold
        : (sub.daysLeft < 7 ? WeexionicTheme.red : WeexionicTheme.green);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF1E2329), Color(0xFF181A20)],
        ),
        border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.25)),
        boxShadow: [
          BoxShadow(
            color: WeexionicTheme.brandGold.withOpacity(0.06),
            blurRadius: 24,
            spreadRadius: -8,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 52, height: 52,
                decoration: BoxDecoration(
                  gradient: WeexionicTheme.brandGradient,
                  shape: BoxShape.circle,
                  boxShadow: WeexionicTheme.goldGlow,
                ),
                child: Center(
                  child: Text(
                    (user.name.isNotEmpty ? user.name[0] : '?').toUpperCase(),
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: WeexionicTheme.bgBase,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            user.name,
                            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        const SizedBox(width: 6),
                        if (user.isAdmin)
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                            decoration: BoxDecoration(
                              gradient: WeexionicTheme.brandGradient,
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: const Text(
                              'ADMIN',
                              style: TextStyle(fontSize: 8, fontWeight: FontWeight.w800, color: WeexionicTheme.bgBase, letterSpacing: 0.5),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      user.email,
                      style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: () async {
                  final confirmed = await showDialog<bool>(
                    context: context,
                    builder: (_) => AlertDialog(
                      backgroundColor: WeexionicTheme.bgSurface,
                      title: const Text('Sign Out?'),
                      content: const Text('You\'ll need to sign in again to access the bot.'),
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
                    await auth.logout();
                  }
                },
                icon: const Icon(Icons.logout_rounded, size: 18, color: WeexionicTheme.red),
                style: IconButton.styleFrom(
                  backgroundColor: WeexionicTheme.red.withOpacity(0.1),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  minimumSize: const Size(36, 36),
                ),
              ),
            ],
         ),
          const SizedBox(height: 14),
          // Plan + days remaining
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'PLAN',
                    style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, letterSpacing: 1, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: WeexionicTheme.brandGold.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.3)),
                        ),
                        child: Text(
                          sub.displayPlan.toUpperCase(),
                          style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: WeexionicTheme.brandGold, letterSpacing: 0.5),
                        ),
                      ),
                      const SizedBox(width: 6),
                      if (sub.isActive)
                        Row(
                          children: [
                            PulsingGlowDot(color: WeexionicTheme.green, size: 5),
                            const SizedBox(width: 4),
                            const Text('ACTIVE', style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: WeexionicTheme.green, letterSpacing: 0.5)),
                          ],
                        ),
                    ],
                  ),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  const Text(
                    'REMAINING',
                    style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, letterSpacing: 1, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    sub.displayDaysLeft,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      color: progressColor,
                      fontFamily: 'RobotoMono',
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 10),
          // Progress bar
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: Stack(
              children: [
                Container(
                  height: 5,
                  color: WeexionicTheme.bgElevated,
                ),
                FractionallySizedBox(
                  widthFactor: progress,
                  child: Container(
                    height: 5,
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: [progressColor, progressColor.withOpacity(0.7)],
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: progressColor.withOpacity(0.4),
                          blurRadius: 6,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Shortcut tile to open Alerts & Channels screen
class _AlertsShortcut extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final cfg = context.read<BotProvider>().config;
    final activeCount = [
      cfg.telegramEnabled,
      cfg.emailEnabled,
      cfg.whatsappEnabled,
    ].where((b) => b).length;

    return Material(
      color: WeexionicTheme.bgSurface,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () {
          Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => const AlertsScreen(),
              settings: const RouteSettings(name: '/alerts'),
            ),
          );
        },
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: WeexionicTheme.border),
            gradient: WeexionicTheme.brandGradientSoft,
          ),
          child: Row(
            children: [
              Container(
                width: 40, height: 40,
                decoration: BoxDecoration(
                  gradient: WeexionicTheme.brandGradient,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(Icons.notifications_active, color: WeexionicTheme.bgBase, size: 22),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Alerts & Channels', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                    Text(
                      'Telegram · Email · WhatsApp  •  $activeCount/3 active',
                      style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: WeexionicTheme.brandGold, size: 24),
            ],
          ),
        ),
      ),
    );
  }
}

// ===================== Exchange Section =====================
class _ExchangeSection extends StatelessWidget {
  final BotConfig cfg;
  final ValueChanged<BotConfig> onChanged;
  const _ExchangeSection({required this.cfg, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionTitle(title: 'Exchange & Environment'),
            Row(
              children: [
                _ExchangeCard(name: 'Binance', desc: 'Futures USDT-M', code: 'B', active: cfg.exchange == 'binance',
                  onTap: () => onChanged(cfg..exchange = 'binance')),
                const SizedBox(width: 8),
                _ExchangeCard(name: 'WEEX', desc: 'Futures', code: 'W', active: cfg.exchange == 'weex',
                  onTap: () => onChanged(cfg..exchange = 'weex')),
                const SizedBox(width: 8),
                _ExchangeCard(name: 'PrimeXBT', desc: 'Futures', code: 'P', active: cfg.exchange == 'primexbt',
                  onTap: () => onChanged(cfg..exchange = 'primexbt')),
              ],
            ),
            const SizedBox(height: 12),
            const Text('ENVIRONMENT', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            const SizedBox(height: 6),
            SegmentedControl<String>(
              options: ['demo', 'live'],
              selected: cfg.testnet ? 'demo' : 'live',
              labels: ['Demo / Testnet', 'Live / Mainnet'],
              onChanged: (v) => onChanged(cfg..testnet = v == 'demo'),
            ),
            const SizedBox(height: 12),
            const Text('TRADE MODE', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            const SizedBox(height: 6),
            SegmentedControl<String>(
              options: ['long', 'short', 'both'],
              selected: cfg.mode,
              labels: ['Long Only', 'Short Only', 'Both'],
              onChanged: (v) => onChanged(cfg..mode = v),
            ),
            const SizedBox(height: 12),
            _InputField(label: 'API Key', value: cfg.apiKey, hint: '••••••••••••••••',
              onChanged: (v) => onChanged(cfg..apiKey = v)),
            const SizedBox(height: 10),
            _InputField(label: 'API Secret', value: cfg.apiSecret, hint: '••••••••••••••••••••••', obscure: true,
              onChanged: (v) => onChanged(cfg..apiSecret = v)),
            if (cfg.exchange == 'weex') ...[
              const SizedBox(height: 10),
              _InputField(label: 'API Passphrase (WEEX only)', value: cfg.apiPassphrase,
                onChanged: (v) => onChanged(cfg..apiPassphrase = v)),
            ],
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () async {
                      final p = context.read<BotProvider>();
                      try {
                        final r = await p.testConnection();
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text(r['success'] == true ? '✅ ${r["message"]}' : '❌ ${r["error"] ?? "Failed"}'),
                            backgroundColor: r['success'] == true ? WeexionicTheme.green : WeexionicTheme.red,
                          ),
                        );
                      } catch (e) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('❌ $e'), backgroundColor: WeexionicTheme.red),
                        );
                      }
                    },
                    icon: const Icon(Icons.link, size: 16),
                    label: const Text('Test Connection', style: TextStyle(fontSize: 11)),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: WeexionicTheme.textSecondary,
                      side: const BorderSide(color: WeexionicTheme.borderLight),
                      padding: const EdgeInsets.symmetric(vertical: 9),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () {},
                    icon: const Icon(Icons.edit, size: 16),
                    label: const Text('Edit Keys', style: TextStyle(fontSize: 11)),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: WeexionicTheme.textSecondary,
                      side: const BorderSide(color: WeexionicTheme.borderLight),
                      padding: const EdgeInsets.symmetric(vertical: 9),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ExchangeCard extends StatelessWidget {
  final String name;
  final String desc;
  final String code;
  final bool active;
  final VoidCallback onTap;
  const _ExchangeCard({required this.name, required this.desc, required this.code, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
          decoration: BoxDecoration(
            color: active ? WeexionicTheme.brandGold.withOpacity(0.12) : WeexionicTheme.bgElevated,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: active ? WeexionicTheme.brandGold : WeexionicTheme.border),
          ),
          child: Column(
            children: [
              Container(
                width: 28, height: 28,
                decoration: BoxDecoration(
                  color: WeexionicTheme.bgSurface,
                  shape: BoxShape.circle,
                ),
                child: Center(
                  child: Text(
                    code,
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w900,
                      color: active ? WeexionicTheme.brandGold : WeexionicTheme.textMuted,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 4),
              Text(
                name,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: active ? WeexionicTheme.brandGold : WeexionicTheme.textPrimary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                desc,
                style: const TextStyle(fontSize: 9, color: WeexionicTheme.textMuted),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ===================== Coins Section =====================
class _CoinsSection extends StatelessWidget {
  final BotConfig cfg;
  final ValueChanged<BotConfig> onChanged;
  const _CoinsSection({required this.cfg, required this.onChanged});

  /// Server allows max 10 monitoring coins
  static const int _maxCoins = 10;

  @override
  Widget build(BuildContext context) {
    final p = context.watch<BotProvider>();
    final selected = cfg.symbolsList;
    // Show selected coins as chips (with remove buttons)
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionTitle(
              title: 'Monitoring Coins',
              trailing: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: selected.length >= _maxCoins
                      ? WeexionicTheme.green.withOpacity(0.15)
                      : WeexionicTheme.brandGold.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '${selected.length} / $_maxCoins',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    color: selected.length >= _maxCoins ? WeexionicTheme.green : WeexionicTheme.brandGold,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Tap + to browse all ${p.symbolsLoaded ? p.availableSymbols.length : "200+"} coins on ${cfg.exchange.toUpperCase()}',
              style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
            ),
            const SizedBox(height: 10),
            // Selected coins as removable chips
            if (selected.isEmpty)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 16),
                decoration: BoxDecoration(
                  color: WeexionicTheme.bgElevated,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: WeexionicTheme.border, style: BorderStyle.solid),
                ),
                child: const Center(
                  child: Text(
                    'No coins selected — tap below to add',
                    style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
                  ),
                ),
              )
            else
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: selected.map((symbol) {
                  final code = symbol.replaceAll('USDT', '').replaceAll('SUSDT', '');
                  return GestureDetector(
                    onTap: () {
                      final newList = List<String>.from(cfg.symbolsList)..remove(symbol);
                      onChanged(cfg
                        ..symbolsList = newList
                        ..symbol = newList.isNotEmpty ? newList.first : 'BTCUSDT');
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        gradient: WeexionicTheme.brandGradient,
                        borderRadius: BorderRadius.circular(14),
                        boxShadow: WeexionicTheme.goldGlow,
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            code,
                            style: const TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w800,
                              color: WeexionicTheme.bgBase,
                            ),
                          ),
                          const SizedBox(width: 4),
                          const Icon(Icons.close, size: 12, color: WeexionicTheme.bgBase),
                        ],
                      ),
                    ),
                  );
                }).toList(),
              ),
            const SizedBox(height: 10),
            // "Add Coins" button — opens searchable picker
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: selected.length >= _maxCoins
                    ? null
                    : () => _showCoinPicker(context, p),
                icon: selected.length >= _maxCoins
                    ? const Icon(Icons.check_circle, size: 16, color: WeexionicTheme.green)
                    : const Icon(Icons.add_circle_outline, size: 16, color: WeexionicTheme.brandGold),
                label: Text(
                  selected.length >= _maxCoins
                      ? 'MAX REACHED ($_maxCoins coins)'
                      : 'ADD COINS FROM EXCHANGE',
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.5),
                ),
                style: OutlinedButton.styleFrom(
                  foregroundColor: WeexionicTheme.textSecondary,
                  side: BorderSide(
                    color: selected.length >= _maxCoins
                        ? WeexionicTheme.green.withOpacity(0.3)
                        : WeexionicTheme.brandGold.withOpacity(0.3),
                  ),
                  padding: const EdgeInsets.symmetric(vertical: 11),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _showCoinPicker(BuildContext context, BotProvider p) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: WeexionicTheme.bgSurface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => _CoinPickerSheet(
        available: p.availableSymbols,
        selected: cfg.symbolsList,
        maxCoins: _maxCoins,
        onToggle: (symbol, isSelected) {
          final newList = List<String>.from(cfg.symbolsList);
          if (isSelected) {
            newList.remove(symbol);
          } else {
            if (newList.length >= _maxCoins) return false;
            newList.add(symbol);
          }
          onChanged(cfg
            ..symbolsList = newList
            ..symbol = newList.isNotEmpty ? newList.first : 'BTCUSDT');
          return true;
        },
      ),
    );
  }
}

/// Searchable coin picker bottom sheet — shows all available exchange coins
class _CoinPickerSheet extends StatefulWidget {
  final List<String> available;
  final List<String> selected;
  final int maxCoins;
  /// Returns true if toggle succeeded (false if max reached)
  final bool Function(String symbol, bool isSelected) onToggle;

  const _CoinPickerSheet({
    required this.available,
    required this.selected,
    required this.maxCoins,
    required this.onToggle,
  });

  @override
  State<_CoinPickerSheet> createState() => _CoinPickerSheetState();
}

class _CoinPickerSheetState extends State<_CoinPickerSheet> {
  final _searchCtrl = TextEditingController();
  String _query = '';

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  List<String> get _filtered {
    if (_query.isEmpty) return widget.available;
    final q = _query.toUpperCase();
    return widget.available.where((s) => s.contains(q)).toList();
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filtered;
    final height = MediaQuery.of(context).size.height * 0.85;

    return SizedBox(
      height: height,
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
            decoration: const BoxDecoration(
              color: WeexionicTheme.bgSurface,
              border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 36, height: 4,
                    decoration: BoxDecoration(
                      color: WeexionicTheme.borderLight,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Select Coins',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: WeexionicTheme.brandGold.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        '${widget.selected.length} / ${widget.maxCoins}',
                        style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                // Search field
                TextField(
                  controller: _searchCtrl,
                  style: const TextStyle(fontSize: 13, color: WeexionicTheme.textPrimary),
                  decoration: InputDecoration(
                    hintText: 'Search BTC, ETH, SOL...',
                    hintStyle: const TextStyle(color: WeexionicTheme.textMuted, fontSize: 12),
                    prefixIcon: const Icon(Icons.search, size: 18, color: WeexionicTheme.textMuted),
                    suffixIcon: _query.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear, size: 16, color: WeexionicTheme.textMuted),
                            onPressed: () {
                              _searchCtrl.clear();
                              setState(() => _query = '');
                            },
                          )
                        : null,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  ),
                  onChanged: (v) => setState(() => _query = v),
                ),
                const SizedBox(height: 6),
                Text(
                  '${widget.available.length} coins available · ${filtered.length} shown',
                  style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
                ),
              ],
            ),
          ),
          // List
          Expanded(
            child: filtered.isEmpty
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.search_off, size: 36, color: WeexionicTheme.textFaint),
                        const SizedBox(height: 8),
                        Text(
                          'No coins match "$_query"',
                          style: const TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
                        ),
                      ],
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    itemCount: filtered.length,
                    itemBuilder: (_, i) {
                      final symbol = filtered[i];
                      final isSelected = widget.selected.contains(symbol);
                      final code = symbol.replaceAll('USDT', '').replaceAll('SUSDT', '');
                      final maxReached = widget.selected.length >= widget.maxCoins && !isSelected;

                      return ListTile(
                        onTap: maxReached
                            ? null
                            : () {
                                final ok = widget.onToggle(symbol, isSelected);
                                if (!ok && mounted) {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                      content: Text('Max ${widget.maxCoins} coins reached'),
                                      backgroundColor: WeexionicTheme.brandGold,
                                      duration: const Duration(seconds: 1),
                                    ),
                                  );
                                }
                                setState(() {});
                              },
                        enabled: !maxReached,
                        dense: true,
                        leading: Container(
                          width: 32, height: 32,
                          decoration: BoxDecoration(
                            color: isSelected
                                ? WeexionicTheme.brandGold
                                : WeexionicTheme.bgElevated,
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: isSelected
                                  ? WeexionicTheme.brandGold
                                  : WeexionicTheme.border,
                            ),
                          ),
                          child: Center(
                            child: Text(
                              code.length > 3 ? code.substring(0, 3) : code,
                              style: TextStyle(
                                fontSize: 9,
                                fontWeight: FontWeight.w900,
                                color: isSelected ? WeexionicTheme.bgBase : WeexionicTheme.textMuted,
                              ),
                            ),
                          ),
                        ),
                        title: Text(
                          symbol,
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: isSelected ? FontWeight.w800 : FontWeight.w600,
                            color: isSelected ? WeexionicTheme.brandGold : WeexionicTheme.textPrimary,
                          ),
                        ),
                        trailing: isSelected
                            ? const Icon(Icons.check_circle, color: WeexionicTheme.brandGold, size: 20)
                            : (maxReached
                                ? const Icon(Icons.lock, color: WeexionicTheme.textFaint, size: 16)
                                : const Icon(Icons.add, color: WeexionicTheme.textMuted, size: 18)),
                      );
                    },
                  ),
          ),
          // Done button
          Container(
            padding: const EdgeInsets.all(14),
            decoration: const BoxDecoration(
              color: WeexionicTheme.bgSurface,
              border: Border(top: BorderSide(color: WeexionicTheme.border)),
            ),
            child: SizedBox(
              width: double.infinity,
              height: 44,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(context),
                style: ElevatedButton.styleFrom(
                  backgroundColor: WeexionicTheme.brandGold,
                  foregroundColor: WeexionicTheme.bgBase,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                child: const Text(
                  'DONE',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, letterSpacing: 1),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ===================== Strategy Section =====================
class _StrategySection extends StatelessWidget {
  final BotConfig cfg;
  final ValueChanged<BotConfig> onChanged;
  const _StrategySection({required this.cfg, required this.onChanged});

  static const _tfs = [
    ('1m', 'scalp'),
    ('5m', 'HIGH FREQ'),
    ('15m', 'intraday'),
    ('1h', 'intraday'),
    ('4h', 'swing'),
    ('1d', 'position'),
  ];

  static const _levPresets = [5, 10, 25, 50, 75, 100, 125];

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionTitle(title: 'Strategy Configuration'),
            const Text('TIMEFRAME', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            const SizedBox(height: 6),
            GridView.count(
              shrinkWrap: true,
              crossAxisCount: 6,
              mainAxisSpacing: 6,
              crossAxisSpacing: 6,
              childAspectRatio: 0.85,
              physics: const NeverScrollableScrollPhysics(),
              children: _tfs.map((t) {
                final active = cfg.timeframe == t.$1;
                return GestureDetector(
                  onTap: () => onChanged(cfg..timeframe = t.$1),
                  child: Container(
                    decoration: BoxDecoration(
                      color: active ? WeexionicTheme.brandGold : WeexionicTheme.bgElevated,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: WeexionicTheme.border),
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          t.$1,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            color: active ? WeexionicTheme.bgBase : WeexionicTheme.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          t.$2,
                          style: TextStyle(
                            fontSize: 8,
                            color: active ? WeexionicTheme.bgBase.withOpacity(0.7) : WeexionicTheme.textMuted,
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: 14),
            const Text('LEVERAGE', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 12),
              decoration: BoxDecoration(
                gradient: WeexionicTheme.brandGradientSoft,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.3)),
              ),
              child: Column(
                children: [
                  ShaderMask(
                    shaderCallback: (b) => WeexionicTheme.brandGradient.createShader(b),
                    child: Text(
                      '${cfg.leverage}X',
                      style: const TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                      ),
                    ),
                  ),
                  const Text('ADJUSTABLE 5X – 125X', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted, letterSpacing: 1)),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: _levPresets.map((lev) {
                final active = cfg.leverage == lev;
                return Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(right: 4),
                    child: GestureDetector(
                      onTap: () => onChanged(cfg..leverage = lev),
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        decoration: BoxDecoration(
                          color: active ? WeexionicTheme.brandGold : WeexionicTheme.bgElevated,
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(color: WeexionicTheme.border),
                        ),
                        child: Text(
                          '${lev}x',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            color: active ? WeexionicTheme.bgBase : WeexionicTheme.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }
}

// ===================== Risk Section =====================
class _RiskSection extends StatelessWidget {
  final BotConfig cfg;
  final ValueChanged<BotConfig> onChanged;
  const _RiskSection({required this.cfg, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionTitle(title: 'Position & Risk Management'),
            const Text('POSITION SIZING MODE', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            const SizedBox(height: 6),
            SegmentedControl<String>(
              options: ['percent', 'fixed'],
              selected: cfg.amountMode,
              labels: ['% of Wallet', 'Fixed Amount'],
              onChanged: (v) => onChanged(cfg..amountMode = v),
            ),
            const SizedBox(height: 14),
            Text(
              'AMOUNT PER TRADE — ${cfg.amountPct.toStringAsFixed(0)}%',
              style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500),
            ),
            Slider(
              value: cfg.amountPct,
              min: 1, max: 100,
              divisions: 99,
              activeColor: WeexionicTheme.brandGold,
              inactiveColor: WeexionicTheme.borderLight,
              onChanged: (v) => onChanged(cfg..amountPct = v),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: const [
                Text('1%', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted)),
                Text('25%', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted)),
                Text('50%', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted)),
                Text('75%', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted)),
                Text('100%', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted)),
              ],
            ),
            const SizedBox(height: 14),
            const Text('AUTO SL / TP (1:1 STRICT)', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: WeexionicTheme.bgElevated,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: WeexionicTheme.border),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Enable 1:1 Risk Management', style: TextStyle(fontSize: 12)),
                  Switch(
                    value: true, // always on (server-enforced)
                    onChanged: null,
                    activeColor: WeexionicTheme.brandGold,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: _NumberInput(
                    label: 'STOP LOSS',
                    value: cfg.stopLossPct,
                    suffix: '%',
                    onChanged: (v) {
                      cfg.stopLossPct = v;
                      cfg.takeProfitPct = v; // server forces equal
                      onChanged(cfg);
                    },
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _NumberInput(
                    label: 'TAKE PROFIT',
                    value: cfg.takeProfitPct,
                    suffix: '%',
                    onChanged: (v) {
                      cfg.takeProfitPct = v;
                      cfg.stopLossPct = v;
                      onChanged(cfg);
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: WeexionicTheme.bgElevated,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: WeexionicTheme.border),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Text('Auto-Reversal', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                      Text('Flip position on SL hit', style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted)),
                    ],
                  ),
                  Switch(
                    value: cfg.tpMode == 'ema_reversal',
                    onChanged: (v) => onChanged(cfg..tpMode = v ? 'ema_reversal' : 'fixed'),
                    activeColor: WeexionicTheme.brandGold,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            const Text('SIMULTANEOUS ACTIVE TRADES', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            const SizedBox(height: 6),
            SegmentedControl<int>(
              options: [1, 2, 3],
              selected: cfg.maxConcurrentTrades,
              labels: ['1 Trade', '2 Trades', '3 Trades'],
              onChanged: (v) => onChanged(cfg..maxConcurrentTrades = v),
            ),
          ],
        ),
      ),
    );
  }
}

// ===================== Shared Inputs =====================
class _InputField extends StatelessWidget {
  final String label;
  final String value;
  final String? hint;
  final bool obscure;
  final ValueChanged<String> onChanged;
  const _InputField({required this.label, required this.value, this.hint, this.obscure = false, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
        const SizedBox(height: 6),
        TextFormField(
          initialValue: value,
          obscureText: obscure,
          style: const TextStyle(fontSize: 13, fontFamily: 'RobotoMono', color: WeexionicTheme.textPrimary),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: const TextStyle(color: WeexionicTheme.textFaint),
            suffixIcon: obscure
                ? const Icon(Icons.visibility_off, size: 16, color: WeexionicTheme.textMuted)
                : const Icon(Icons.visibility, size: 16, color: WeexionicTheme.textMuted),
          ),
          onChanged: onChanged,
        ),
      ],
    );
  }
}

class _NumberInput extends StatelessWidget {
  final String label;
  final double value;
  final String suffix;
  final ValueChanged<double> onChanged;
  const _NumberInput({required this.label, required this.value, required this.suffix, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
        const SizedBox(height: 6),
        Container(
          decoration: BoxDecoration(
            color: WeexionicTheme.bgElevated,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: WeexionicTheme.border),
          ),
          child: Row(
            children: [
              Expanded(
                child: TextFormField(
                  initialValue: value.toStringAsFixed(1),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  style: const TextStyle(fontSize: 13, fontFamily: 'RobotoMono', color: WeexionicTheme.textPrimary),
                  decoration: const InputDecoration(
                    border: InputBorder.none,
                    contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  ),
                  onChanged: (v) {
                    final d = double.tryParse(v);
                    if (d != null) onChanged(d);
                  },
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: const BoxDecoration(
                  color: WeexionicTheme.bgSurface,
                  border: Border(left: BorderSide(color: WeexionicTheme.border)),
                ),
                child: Text(suffix, style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w700)),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
