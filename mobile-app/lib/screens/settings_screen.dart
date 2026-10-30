import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../models/bot_config.dart';
import '../widgets/common.dart';

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
            color: active ? WeexionicTheme.brandGold.withValues(alpha: 0.12) : WeexionicTheme.bgElevated,
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

  static const _allCoins = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'SUI'];

  @override
  Widget build(BuildContext context) {
    final selected = cfg.symbolsList.map((s) => s.replaceAll('USDT', '').replaceAll('SUSDT', '')).toList();

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
                  color: WeexionicTheme.brandGold.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '${selected.length} SELECTED',
                  style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
                ),
              ),
            ),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: _allCoins.map((c) {
                final isOn = selected.contains(c);
                return GestureDetector(
                  onTap: () {
                    final newList = List<String>.from(cfg.symbolsList);
                    final symbol = '$c${cfg.exchange == 'weex' ? 'SUSDT' : 'USDT'}';
                    if (isOn) {
                      newList.remove(symbol);
                    } else {
                      if (newList.length >= 3) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Max 3 coins allowed'),
                            backgroundColor: WeexionicTheme.brandGold,
                            duration: Duration(seconds: 1),
                          ),
                        );
                        return;
                      }
                      newList.add(symbol);
                    }
                    onChanged(cfg
                      ..symbolsList = newList
                      ..symbol = newList.isNotEmpty ? newList.first : 'BTCUSDT');
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      color: isOn ? WeexionicTheme.brandGold : WeexionicTheme.bgElevated,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: WeexionicTheme.border),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          c,
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            color: isOn ? WeexionicTheme.bgBase : WeexionicTheme.textMuted,
                          ),
                        ),
                        if (isOn) ...[
                          const SizedBox(width: 4),
                          Icon(Icons.check, size: 10, color: WeexionicTheme.bgBase),
                        ],
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: WeexionicTheme.bgElevated,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: WeexionicTheme.border, style: BorderStyle.solid),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Icon(Icons.add, size: 12, color: WeexionicTheme.textMuted),
                  SizedBox(width: 4),
                  Text('Add', style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: WeexionicTheme.textMuted)),
                ],
              ),
            ),
          ],
        ),
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
                            color: active ? WeexionicTheme.bgBase.withValues(alpha: 0.7) : WeexionicTheme.textMuted,
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
                border: Border.all(color: WeexionicTheme.brandGold.withValues(alpha: 0.3)),
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
