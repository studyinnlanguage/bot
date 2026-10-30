import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../widgets/candlestick_chart.dart';
import '../widgets/stat_card.dart';
import '../widgets/status_chip.dart';
import '../widgets/common.dart';

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
                  padding: const EdgeInsets.fromLTRB(14, 8, 14, 20),
                  children: [
                    _BalanceHero(p: p),
                    const SizedBox(height: 12),
                    _ActionButtons(p: p),
                    const SizedBox(height: 12),
                    _PairChartCard(p: p),
                    const SizedBox(height: 12),
                    _PositionCard(p: p),
                    const SizedBox(height: 12),
                    _StrategyCard(p: p),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => p.refreshAll(),
        backgroundColor: WeexionicTheme.brandGold,
        child: const Icon(Icons.refresh, color: WeexionicTheme.bgBase),
      ),
    );
  }

  Widget _buildHeader(BuildContext context, BotProvider p) {
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
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
          StatusChip.running(running: p.isRunning),
          const SizedBox(width: 8),
          IconButton(
            icon: const Icon(Icons.notifications_outlined, size: 22),
            onPressed: () {},
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

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [WeexionicTheme.bgElevated, WeexionicTheme.bgSurface],
        ),
        border: Border.all(color: WeexionicTheme.border),
        boxShadow: [
          BoxShadow(
            color: WeexionicTheme.brandGold.withValues(alpha: 0.08),
            blurRadius: 30,
            spreadRadius: -10,
            offset: const Offset(0, 4),
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
                    const Text(
                      'TOTAL BALANCE (USDT)',
                      style: TextStyle(
                        fontSize: 11,
                        color: WeexionicTheme.textMuted,
                        letterSpacing: 1,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '\$${p.balance.toStringAsFixed(2)}',
                      style: const TextStyle(
                        fontSize: 32,
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.5,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Icon(
                          pnl >= 0 ? Icons.trending_up : Icons.trending_down,
                          size: 12,
                          color: pnlColor,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          '$pnlStr today (${p.stats.winRatePct.toStringAsFixed(1)}%)',
                          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500, color: pnlColor),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  const Text(
                    'ACTIVE COINS',
                    style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, letterSpacing: 1),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${p.status.symbols.length}',
                    style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
                  ),
                  Text(
                    "Today: ${p.status.tradesToday}",
                    style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(child: CompactStat(value: '${p.positions.values.where((x) => !x.isFlat).length}', label: 'Open')),
              const SizedBox(width: 8),
              Expanded(child: CompactStat(value: '${p.stats.winRatePct.toStringAsFixed(1)}%', label: 'Win Rate')),
              const SizedBox(width: 8),
              Expanded(child: CompactStat(value: pnlStr, label: 'Net P&L', valueColor: pnlColor)),
            ],
          ),
        ],
      ),
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
            icon: Icons.play_arrow,
            color: WeexionicTheme.green,
            onPressed: p.isRunning ? null : () => p.startBot(),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _ActionBtn(
            label: 'STOP',
            icon: Icons.stop,
            color: WeexionicTheme.red,
            onPressed: p.isRunning ? () => p.stopBot() : null,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _ActionBtn(
            label: 'RESET',
            icon: Icons.restart_alt,
            color: WeexionicTheme.brandGold,
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
  final Color color;
  final VoidCallback? onPressed;

  const _ActionBtn({
    required this.label,
    required this.icon,
    required this.color,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final disabled = onPressed == null;
    return Material(
      color: disabled ? color.withValues(alpha: 0.3) : color,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 16, color: disabled ? WeexionicTheme.textMuted : WeexionicTheme.bgBase),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: disabled ? WeexionicTheme.textMuted : WeexionicTheme.bgBase,
                  letterSpacing: 0.5,
                ),
              ),
            ],
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
    final lastCandle = p.chart.candles.isNotEmpty ? p.chart.candles.last : null;
    final markPrice = p.activePosition.markPrice > 0
        ? p.activePosition.markPrice
        : (lastCandle?.close ?? p.indicators.markPrice);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
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
                      Text(
                        p.activeSymbol,
                        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
                      ),
                      Text(
                        '${p.config.exchange.toUpperCase()} Futures · ${p.config.timeframe}',
                        style: const TextStyle(fontSize: 9, color: WeexionicTheme.textMuted),
                      ),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '\$${_fmtPrice(markPrice)}',
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, fontFamily: 'RobotoMono'),
                    ),
                    Text(
                      '${p.indicators.signal == "BUY" ? "+" : p.indicators.signal == "SELL" ? "-" : ""}${p.indicators.emaSepPct.toStringAsFixed(2)}%',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: p.indicators.signal == 'BUY'
                            ? WeexionicTheme.green
                            : p.indicators.signal == 'SELL'
                                ? WeexionicTheme.red
                                : WeexionicTheme.textMuted,
                      ),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 12),
            _TimeframeRow(active: p.config.timeframe),
            const SizedBox(height: 8),
            CandlestickChart(data: p.chart, height: 130),
          ],
        ),
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
              color: a ? WeexionicTheme.brandGold.withValues(alpha: 0.15) : Colors.transparent,
              borderRadius: BorderRadius.circular(6),
              border: a ? Border.all(color: WeexionicTheme.brandGold.withValues(alpha: 0.3)) : null,
            ),
            child: Text(
              tf,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
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
    final code = symbol.replaceAll('USDT', '').replaceAll('SUSDT', '').substring(0, symbol.length > 4 ? 3 : 2);
    return Container(
      width: 32, height: 32,
      decoration: const BoxDecoration(
        gradient: WeexionicTheme.brandGradient,
        shape: BoxShape.circle,
      ),
      child: Center(
        child: Text(
          code,
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
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'CURRENT POSITION',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: WeexionicTheme.textMuted, letterSpacing: 0.8),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: WeexionicTheme.brandGold.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: WeexionicTheme.brandGold.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    '${pos.leverage}X',
                    style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
                  ),
                ),
              ],
            ),
            const Divider(height: 16),
            InfoRow(
              label: 'Direction',
              value: pos.side,
              trailing: pos.isFlat
                  ? const _Badge(text: 'NONE / FLAT', color: WeexionicTheme.textMuted)
                  : pos.isLong
                      ? const _Badge(text: 'LONG', color: WeexionicTheme.green)
                      : const _Badge(text: 'SHORT', color: WeexionicTheme.red),
            ),
            InfoRow(label: 'Contract Qty', value: '${pos.size.abs().toStringAsFixed(4)} ${pos.symbol.replaceAll('USDT', '')}'),
            InfoRow(label: 'Entry Price', value: pos.entryPrice > 0 ? '\$${pos.entryPrice.toStringAsFixed(2)}' : '—'),
            InfoRow(label: 'Mark Price', value: pos.markPrice > 0 ? '\$${pos.markPrice.toStringAsFixed(2)}' : '—'),
            InfoRow(
              label: 'Unrealized PnL',
              value: '\$${pos.unrealizedPnl.toStringAsFixed(2)} (${pos.roePct.toStringAsFixed(2)}% ROE)',
              valueColor: pos.unrealizedPnl > 0
                  ? WeexionicTheme.green
                  : pos.unrealizedPnl < 0
                      ? WeexionicTheme.red
                      : WeexionicTheme.textMuted,
            ),
            InfoRow(
              label: 'SL / TP',
              value: '',
              trailing: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: WeexionicTheme.blue.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '1:1 AUTO · ${p.config.stopLossPct.toStringAsFixed(1)}%',
                  style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: WeexionicTheme.blue),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String text;
  final Color color;
  const _Badge({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        text,
        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: color),
      ),
    );
  }
}

class _StrategyCard extends StatelessWidget {
  final BotProvider p;
  const _StrategyCard({required this.p});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'ACTIVE STRATEGY',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: WeexionicTheme.textMuted, letterSpacing: 0.8),
                ),
                Text(
                  'EMA 8,13,21,55',
                  style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
                ),
              ],
            ),
            const Divider(height: 16),
            InfoRow(
              label: 'Signal',
              value: p.indicators.signal,
              trailing: _Badge(
                text: p.indicators.signal,
                color: p.indicators.signal == 'BUY'
                    ? WeexionicTheme.green
                    : p.indicators.signal == 'SELL'
                        ? WeexionicTheme.red
                        : WeexionicTheme.textMuted,
              ),
            ),
            InfoRow(label: 'Timeframe', value: '${p.config.timeframe} · Polling 120s'),
            InfoRow(label: 'Mode', value: p.config.mode == 'both' ? 'Both (Long/Short)' : p.config.mode),
            InfoRow(label: 'Max Concurrent', value: '${p.config.maxConcurrentTrades} trade(s)'),
          ],
        ),
      ),
    );
  }
}
