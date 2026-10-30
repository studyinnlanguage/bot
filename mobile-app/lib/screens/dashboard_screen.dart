import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../widgets/candlestick_chart.dart';
import '../widgets/premium.dart';
import '../widgets/stat_card.dart';
import '../widgets/status_chip.dart';
import 'alerts_screen.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.watch<BotProvider>();

    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: Column(
          children: [
            _buildHeader(context, p),
            Expanded(
              child: RefreshIndicator(
                color: WeexionicTheme.brandGold,
                onRefresh: () => p.refreshAll(),
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(14, 12, 14, 90),
                  children: [
                    _BalanceHero(p: p),
                    const SizedBox(height: 14),
                    _ActionButtons(p: p),
                    const SizedBox(height: 14),
                    _PairChartCard(p: p),
                    const SizedBox(height: 14),
                    _PositionCard(p: p),
                    const SizedBox(height: 14),
                    _StrategyCard(p: p),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context, BotProvider p) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(
          bottom: BorderSide(color: WeexionicTheme.brandGold.withOpacity(0.1)),
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 38, height: 38,
            decoration: BoxDecoration(
              gradient: WeexionicTheme.brandGradient,
              borderRadius: BorderRadius.circular(10),
              boxShadow: WeexionicTheme.goldGlow,
            ),
            child: const Icon(
              Icons.show_chart_rounded,
              color: WeexionicTheme.bgBase,
              size: 22,
            ),
          ),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const WeexionicLogo(size: 18),
              const SizedBox(height: 1),
              Text(
                'FUTURES BOT',
                style: TextStyle(
                  fontSize: 8,
                  color: WeexionicTheme.textMuted,
                  letterSpacing: 2,
                ),
              ),
            ],
          ),
          const Spacer(),
          // Status chip with pulsing dot
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: p.isRunning
                  ? WeexionicTheme.green.withOpacity(0.12)
                  : WeexionicTheme.textMuted.withOpacity(0.12),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(
                color: p.isRunning
                    ? WeexionicTheme.green.withOpacity(0.3)
                    : WeexionicTheme.textMuted.withOpacity(0.3),
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                PulsingGlowDot(
                  color: p.isRunning ? WeexionicTheme.green : WeexionicTheme.textMuted,
                  size: 6,
                ),
                const SizedBox(width: 6),
                Text(
                  p.isRunning ? 'RUNNING' : 'STOPPED',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: p.isRunning ? WeexionicTheme.green : WeexionicTheme.textMuted,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Stack(
            children: [
              IconButton(
                icon: const Icon(Icons.notifications_outlined, size: 22, color: WeexionicTheme.textSecondary),
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AlertsScreen()),
                  );
                },
              ),
              Positioned(
                top: 10, right: 10,
                child: Container(
                  width: 8, height: 8,
                  decoration: const BoxDecoration(
                    color: WeexionicTheme.red,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _BalanceHero extends StatelessWidget {
  final BotProvider p;
  const _BalanceHero({required this.p});

  @override
  Widget build(BuildContext context) {
    final pnl = p.stats.netPnl;
    final pnlColor = pnl > 0 ? WeexionicTheme.green : (pnl < 0 ? WeexionicTheme.red : WeexionicTheme.textMuted);
    final pnlStr = (pnl >= 0 ? '+' : '') + '\$${pnl.toStringAsFixed(2)}';
    final loading = p.loading && p.balance == 0;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF1E2329), Color(0xFF0B0E11)],
        ),
        border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.2)),
        boxShadow: [
          BoxShadow(
            color: WeexionicTheme.brandGold.withOpacity(0.08),
            blurRadius: 30,
            spreadRadius: -10,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(
                            color: WeexionicTheme.brandGold.withOpacity(0.15),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            'TOTAL BALANCE',
                            style: TextStyle(
                              fontSize: 9,
                              color: WeexionicTheme.brandGold,
                              letterSpacing: 1,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          'USDT',
                          style: TextStyle(
                            fontSize: 9,
                            color: WeexionicTheme.textMuted,
                            letterSpacing: 1,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    loading
                        ? ShimmerPlaceholder(width: 180, height: 32)
                        : Text(
                            '\$${p.balance.toStringAsFixed(2)}',
                            style: TextStyle(
                              fontSize: 32,
                              fontWeight: FontWeight.w800,
                              letterSpacing: -0.5,
                              color: WeexionicTheme.textPrimary,
                              shadows: pnlColor != WeexionicTheme.textMuted
                                  ? [Shadow(color: pnlColor.withOpacity(0.4), blurRadius: 16)]
                                  : null,
                            ),
                          ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Icon(
                          pnl >= 0 ? Icons.trending_up_rounded : Icons.trending_down_rounded,
                          size: 14,
                          color: pnlColor,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          '$pnlStr today',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            color: pnlColor,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          '(${p.stats.winRatePct.toStringAsFixed(1)}% win)',
                          style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: WeexionicTheme.bgBase.withOpacity(0.5),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.15)),
                ),
                child: Column(
                  children: [
                    Text(
                      'COINS',
                      style: TextStyle(
                        fontSize: 9,
                        color: WeexionicTheme.textMuted,
                        letterSpacing: 1,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${p.status.symbols.length}',
                      style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                        color: WeexionicTheme.brandGold,
                        shadows: [Shadow(color: WeexionicTheme.brandGold.withOpacity(0.4), blurRadius: 8)],
                      ),
                    ),
                    Text(
                      "${p.status.tradesToday} today",
                      style: const TextStyle(fontSize: 9, color: WeexionicTheme.textMuted),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
            decoration: BoxDecoration(
              color: WeexionicTheme.bgBase.withOpacity(0.4),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              children: [
                Expanded(child: _StatPill(
                  value: '${p.positions.values.where((x) => !x.isFlat).length}',
                  label: 'OPEN',
                  color: WeexionicTheme.cyan,
                )),
                Container(width: 1, height: 24, color: WeexionicTheme.border),
                Expanded(child: _StatPill(
                  value: '${p.stats.winRatePct.toStringAsFixed(1)}%',
                  label: 'WIN RATE',
                  color: WeexionicTheme.brandGold,
                )),
                Container(width: 1, height: 24, color: WeexionicTheme.border),
                Expanded(child: _StatPill(
                  value: pnlStr,
                  label: 'NET P&L',
                  color: pnlColor,
                )),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatPill extends StatelessWidget {
  final String value;
  final String label;
  final Color color;
  const _StatPill({required this.value, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          value,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w800,
            color: color,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: const TextStyle(
            fontSize: 8,
            color: WeexionicTheme.textMuted,
            letterSpacing: 0.5,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _ActionButtons extends StatelessWidget {
  final BotProvider p;
  const _ActionButtons({required this.p});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _ActionBtn(
            label: 'START',
            icon: Icons.play_arrow_rounded,
            gradient: WeexionicTheme.neonGreenGradient,
            glow: WeexionicTheme.greenGlow,
            disabled: p.isRunning,
            onPressed: p.isRunning ? null : () => p.startBot(),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _ActionBtn(
            label: 'STOP',
            icon: Icons.stop_rounded,
            gradient: WeexionicTheme.neonRedGradient,
            glow: WeexionicTheme.redGlow,
            disabled: !p.isRunning,
            onPressed: p.isRunning ? () => p.stopBot() : null,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _ActionBtn(
            label: 'RESET',
            icon: Icons.restart_alt_rounded,
            gradient: WeexionicTheme.brandGradient,
            glow: WeexionicTheme.goldGlow,
            disabled: false,
            onPressed: () => p.forceReset(),
          ),
        ),
      ],
    );
  }
}

class _ActionBtn extends StatelessWidget {
  final String label;
  final IconData icon;
  final Gradient gradient;
  final List<BoxShadow> glow;
  final bool disabled;
  final VoidCallback? onPressed;

  const _ActionBtn({
    required this.label,
    required this.icon,
    required this.gradient,
    required this.glow,
    required this.disabled,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedOpacity(
      duration: const Duration(milliseconds: 200),
      opacity: disabled ? 0.4 : 1.0,
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          gradient: disabled ? null : gradient,
          color: disabled ? WeexionicTheme.bgElevated : null,
          boxShadow: disabled ? null : glow,
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: disabled ? null : onPressed,
            borderRadius: BorderRadius.circular(12),
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Column(
                children: [
                  Icon(icon, size: 18, color: WeexionicTheme.bgBase),
                  const SizedBox(height: 4),
                  Text(
                    label,
                    style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: WeexionicTheme.bgBase,
                      letterSpacing: 1,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PairChartCard extends StatelessWidget {
  final BotProvider p;
  const _PairChartCard({required this.p});

  @override
  Widget build(BuildContext context) {
    // FIX: fallback to indicators.markPrice or fetch via API
    final lastCandle = p.chart.candles.isNotEmpty ? p.chart.candles.last : null;
    final markPrice = p.activePosition.markPrice > 0
        ? p.activePosition.markPrice
        : (lastCandle?.close ?? p.indicators.markPrice);
    final hasData = markPrice > 0;
    final signal = p.indicators.signal;
    final signalColor = signal == 'BUY'
        ? WeexionicTheme.green
        : signal == 'SELL'
            ? WeexionicTheme.red
            : WeexionicTheme.textMuted;

    return GlassCard(
      padding: const EdgeInsets.all(14),
      borderColor: WeexionicTheme.border,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _CoinIcon(symbol: p.activeSymbol),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          p.activeSymbol,
                          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(width: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                          decoration: BoxDecoration(
                            color: WeexionicTheme.brandGold.withOpacity(0.15),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            p.config.timeframe.toUpperCase(),
                            style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
                          ),
                        ),
                      ],
                    ),
                    Text(
                      '${p.config.exchange.toUpperCase()} Futures · ${p.config.testnet ? "TESTNET" : "LIVE"}',
                      style: const TextStyle(fontSize: 9, color: WeexionicTheme.textMuted),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  hasData
                      ? Text(
                          '\$${_fmtPrice(markPrice)}',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w800,
                            color: WeexionicTheme.textPrimary,
                            fontFamily: 'RobotoMono',
                            shadows: [Shadow(color: signalColor.withOpacity(0.3), blurRadius: 8)],
                          ),
                        )
                      : ShimmerPlaceholder(width: 90, height: 18),
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      if (signal != 'HOLD')
                        PulsingGlowDot(color: signalColor, size: 5)
                      else
                        Container(width: 5, height: 5),
                      const SizedBox(width: 4),
                      Text(
                        '${p.indicators.emaSepPct.toStringAsFixed(2)}% spread',
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: signalColor,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 10),
          _TimeframeRow(active: p.config.timeframe),
          const SizedBox(height: 10),
          // Chart with proper handling of empty state
          hasData && p.chart.candles.isNotEmpty
              ? CandlestickChart(data: p.chart, height: 140)
              : Container(
                  height: 140,
                  decoration: BoxDecoration(
                    color: const Color(0xFF06080C),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: WeexionicTheme.border),
                  ),
                  child: Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.candlestick_chart_outlined, size: 32, color: WeexionicTheme.textFaint),
                        const SizedBox(height: 6),
                        const Text(
                          'Waiting for chart data...',
                          style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Tap START to begin streaming',
                          style: TextStyle(fontSize: 10, color: WeexionicTheme.textFaint),
                        ),
                      ],
                    ),
                  ),
                ),
        ],
      ),
    );
  }

  String _fmtPrice(double v) {
    if (v == 0) return '0.00';
    if (v >= 1000) return v.toStringAsFixed(2);
    if (v >= 1) return v.toStringAsFixed(2);
    return v.toStringAsFixed(4);
  }
}

class _TimeframeRow extends StatelessWidget {
  final String active;
  const _TimeframeRow({required this.active});

  static const _tfs = ['1m', '5m', '15m', '1h', '4h', '1d'];

  @override
  Widget build(BuildContext context) {
    return Row(
      children: _tfs.map((tf) {
        final a = tf == active;
        return Expanded(
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 2),
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(
              color: a ? WeexionicTheme.brandGold.withOpacity(0.15) : Colors.transparent,
              borderRadius: BorderRadius.circular(6),
              border: a ? Border.all(color: WeexionicTheme.brandGold.withOpacity(0.4)) : null,
            ),
            child: Text(
              tf,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: a ? WeexionicTheme.brandGold : WeexionicTheme.textMuted,
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}

class _CoinIcon extends StatelessWidget {
  final String symbol;
  const _CoinIcon({required this.symbol});

  @override
  Widget build(BuildContext context) {
    final code = symbol.replaceAll('USDT', '').replaceAll('SUSDT', '');
    final display = code.length > 3 ? code.substring(0, 3) : code;
    return Container(
      width: 32, height: 32,
      decoration: BoxDecoration(
        gradient: WeexionicTheme.brandGradient,
        shape: BoxShape.circle,
        boxShadow: WeexionicTheme.goldGlow,
      ),
      child: Center(
        child: Text(
          display,
          style: const TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w900,
            color: WeexionicTheme.bgBase,
          ),
        ),
      ),
    );
  }
}

class _PositionCard extends StatelessWidget {
  final BotProvider p;
  const _PositionCard({required this.p});

  @override
  Widget build(BuildContext context) {
    final pos = p.activePosition;
    // FIX: leverage fallback to config when position is flat
    final leverage = pos.isFlat ? p.config.leverage : pos.leverage;
    final isActive = !pos.isFlat;
    final pnlColor = pos.unrealizedPnl > 0
        ? WeexionicTheme.green
        : pos.unrealizedPnl < 0
            ? WeexionicTheme.red
            : WeexionicTheme.textMuted;

    return GlassCard(
      padding: const EdgeInsets.all(14),
      borderColor: isActive
          ? (pos.isLong ? WeexionicTheme.green.withOpacity(0.4) : WeexionicTheme.red.withOpacity(0.4))
          : WeexionicTheme.border,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    width: 3, height: 14,
                    decoration: BoxDecoration(
                      gradient: WeexionicTheme.brandGradient,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                  const SizedBox(width: 6),
                  const Text(
                    'CURRENT POSITION',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: WeexionicTheme.textSecondary,
                      letterSpacing: 0.5,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  gradient: WeexionicTheme.brandGradient,
                  borderRadius: BorderRadius.circular(6),
                  boxShadow: WeexionicTheme.goldGlow,
                ),
                child: Text(
                  '${leverage}X',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w900,
                    color: WeexionicTheme.bgBase,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Direction badge - prominent
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 10),
            decoration: BoxDecoration(
              color: isActive
                  ? (pos.isLong ? WeexionicTheme.green.withOpacity(0.1) : WeexionicTheme.red.withOpacity(0.1))
                  : WeexionicTheme.bgElevated,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: isActive
                    ? (pos.isLong ? WeexionicTheme.green.withOpacity(0.3) : WeexionicTheme.red.withOpacity(0.3))
                    : WeexionicTheme.border,
              ),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  pos.isFlat ? Icons.pause_circle_outline : (pos.isLong ? Icons.trending_up : Icons.trending_down),
                  size: 16,
                  color: isActive ? (pos.isLong ? WeexionicTheme.green : WeexionicTheme.red) : WeexionicTheme.textMuted,
                ),
                const SizedBox(width: 6),
                Text(
                  pos.isFlat ? 'NO ACTIVE POSITION' : '${pos.side} · ${pos.size.abs().toStringAsFixed(4)}',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: isActive ? (pos.isLong ? WeexionicTheme.green : WeexionicTheme.red) : WeexionicTheme.textMuted,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          // Grid 2 cols
          Row(
            children: [
              Expanded(child: _GridItem(label: 'Entry', value: pos.entryPrice > 0 ? '\$${pos.entryPrice.toStringAsFixed(2)}' : '—', muted: pos.entryPrice == 0)),
              const SizedBox(width: 14),
              Expanded(child: _GridItem(label: 'Mark', value: pos.markPrice > 0 ? '\$${pos.markPrice.toStringAsFixed(2)}' : '—', muted: pos.markPrice == 0)),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(child: _GridItem(
                label: 'Unrealized PnL',
                value: '${pos.unrealizedPnl >= 0 ? '+' : ''}\$${pos.unrealizedPnl.toStringAsFixed(2)}',
                valueColor: pnlColor,
                subValue: '(${pos.roePct.toStringAsFixed(2)}% ROE)',
              )),
              const SizedBox(width: 14),
              Expanded(child: _GridItem(
                label: 'SL / TP',
                value: '1:1 Auto',
                valueColor: WeexionicTheme.blue,
                subValue: '${p.config.stopLossPct.toStringAsFixed(1)}% / ${p.config.takeProfitPct.toStringAsFixed(1)}%',
              )),
            ],
          ),
        ],
      ),
    );
  }
}

class _GridItem extends StatelessWidget {
  final String label;
  final String value;
  final String? subValue;
  final bool muted;
  final Color? valueColor;

  const _GridItem({required this.label, required this.value, this.subValue, this.muted = false, this.valueColor});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label.toUpperCase(),
          style: const TextStyle(
            fontSize: 9,
            color: WeexionicTheme.textMuted,
            letterSpacing: 0.5,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 3),
        Text(
          value,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w800,
            fontFamily: 'RobotoMono',
            color: valueColor ?? (muted ? WeexionicTheme.textMuted : WeexionicTheme.textPrimary),
          ),
        ),
        if (subValue != null) ...[
          const SizedBox(height: 1),
          Text(
            subValue!,
            style: const TextStyle(
              fontSize: 10,
              color: WeexionicTheme.textMuted,
              fontFamily: 'RobotoMono',
            ),
          ),
        ],
      ],
    );
  }
}

class _StrategyCard extends StatelessWidget {
  final BotProvider p;
  const _StrategyCard({required this.p});

  @override
  Widget build(BuildContext context) {
    final signal = p.indicators.signal;
    final signalColor = signal == 'BUY'
        ? WeexionicTheme.green
        : signal == 'SELL'
            ? WeexionicTheme.red
            : WeexionicTheme.textMuted;

    return GlassCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    width: 3, height: 14,
                    decoration: BoxDecoration(
                      gradient: WeexionicTheme.brandGradient,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                  const SizedBox(width: 6),
                  const Text(
                    'ACTIVE STRATEGY',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: WeexionicTheme.textSecondary,
                      letterSpacing: 0.5,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: WeexionicTheme.bgElevated,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: const Text(
                  'EMA 8,13,21,55',
                  style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Signal badge - prominent
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 14),
            decoration: BoxDecoration(
              color: signal != 'HOLD'
                  ? signalColor.withOpacity(0.1)
                  : WeexionicTheme.bgElevated,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: signal != 'HOLD'
                    ? signalColor.withOpacity(0.3)
                    : WeexionicTheme.border,
              ),
            ),
            child: Row(
              children: [
                if (signal != 'HOLD')
                  PulsingGlowDot(color: signalColor, size: 8)
                else
                  Container(
                    width: 8, height: 8,
                    decoration: BoxDecoration(
                      color: WeexionicTheme.textMuted,
                      shape: BoxShape.circle,
                    ),
                  ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'CURRENT SIGNAL',
                        style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, letterSpacing: 0.5, fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        signal,
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                          color: signalColor,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    const Text(
                      'SPREAD',
                      style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, letterSpacing: 0.5, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${p.indicators.emaSepPct.toStringAsFixed(2)}%',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w800,
                        color: signalColor,
                        fontFamily: 'RobotoMono',
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _MiniStat(label: 'Timeframe', value: '${p.config.timeframe} · 120s')),
              Expanded(child: _MiniStat(label: 'Mode', value: p.config.mode == 'both' ? 'Both' : p.config.mode)),
              Expanded(child: _MiniStat(label: 'Max', value: '${p.config.maxConcurrentTrades}T')),
            ],
          ),
        ],
      ),
    );
  }
}

class _MiniStat extends StatelessWidget {
  final String label;
  final String value;
  const _MiniStat({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label.toUpperCase(),
          style: const TextStyle(fontSize: 8, color: WeexionicTheme.textMuted, letterSpacing: 0.5, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: WeexionicTheme.textSecondary),
        ),
      ],
    );
  }
}
