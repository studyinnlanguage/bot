import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../models/position.dart';
import '../widgets/status_chip.dart';
import '../widgets/premium.dart';
import '../widgets/common.dart';

class PositionsScreen extends StatelessWidget {
  const PositionsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.watch<BotProvider>();

    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(context, p),
            _buildPairSelector(context, p),
            Expanded(
              child: RefreshIndicator(
                color: WeexionicTheme.brandGold,
                onRefresh: () => p.fetchPositions(),
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
                  children: [
                    _PositionCard(p: p),
                    const SizedBox(height: 12),
                    _ActionButtons(p: p),
                    const SizedBox(height: 12),
                    _MonitorTable(p: p),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAppBar(BuildContext context, BotProvider p) {
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        children: [
          const Icon(Icons.dashboard_outlined, color: WeexionicTheme.textSecondary, size: 22),
          const SizedBox(width: 12),
          const Expanded(
            child: Text('Open Positions', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          ),
          // Live indicator (no manual refresh — auto-polls every 5s)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: p.socketConnected
                  ? WeexionicTheme.green.withOpacity(0.12)
                  : WeexionicTheme.brandGold.withOpacity(0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                PulsingGlowDot(
                  color: p.socketConnected ? WeexionicTheme.green : WeexionicTheme.brandGold,
                  size: 5,
                ),
                const SizedBox(width: 4),
                Text(
                  p.socketConnected ? 'LIVE' : 'AUTO',
                  style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    color: p.socketConnected ? WeexionicTheme.green : WeexionicTheme.brandGold,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPairSelector(BuildContext context, BotProvider p) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        children: [
          _CoinIcon(symbol: p.activeSymbol),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GestureDetector(
                  onTap: () => _showSymbolPicker(context, p),
                  child: Row(
                    children: [
                      Text(p.activeSymbol, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                      const Icon(Icons.keyboard_arrow_down, color: WeexionicTheme.textMuted, size: 20),
                    ],
                  ),
                ),
                Text(
                  '${p.config.exchange.toUpperCase()} Futures · ${p.config.testnet ? "TESTNET" : "LIVE"}',
                  style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Text('Mark Price', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted)),
              Text(
                '\$${_fmt(p.getMarkPriceFor(p.activeSymbol))}',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, fontFamily: 'RobotoMono'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _showSymbolPicker(BuildContext context, BotProvider p) {
    showModalBottomSheet(
      context: context,
      backgroundColor: WeexionicTheme.bgSurface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Select Symbol', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            ),
            ...p.config.symbolsList.map(
              (s) => ListTile(
                leading: _CoinIcon(symbol: s, size: 28),
                title: Text(s),
                trailing: p.activeSymbol == s
                    ? const Icon(Icons.check, color: WeexionicTheme.brandGold)
                    : null,
                onTap: () {
                  p.setActiveSymbol(s);
                  Navigator.pop(context);
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _fmt(double v) {
    if (v == 0) return '0.00';
    if (v >= 1000) return v.toStringAsFixed(2);
    if (v >= 1) return v.toStringAsFixed(2);
    return v.toStringAsFixed(4);
  }

  String _fmtMarkPrice(double v) {
    return _fmtMarkPriceStatic(v);
  }

  static String _fmtMarkPriceStatic(double v) {
    if (v == 0) return '—';
    if (v >= 1000) return '\$${v.toStringAsFixed(2)}';
    if (v >= 1) return '\$${v.toStringAsFixed(2)}';
    return '\$${v.toStringAsFixed(4)}';
  }
}

class _PositionCard extends StatelessWidget {
  final BotProvider p;
  const _PositionCard({required this.p});

  @override
  Widget build(BuildContext context) {
    final pos = p.activePosition;
    final pnlColor = pos.unrealizedPnl > 0
        ? WeexionicTheme.green
        : pos.unrealizedPnl < 0
            ? WeexionicTheme.red
            : WeexionicTheme.textMuted;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [WeexionicTheme.bgElevated, WeexionicTheme.bgSurface],
        ),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: WeexionicTheme.textMuted.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.circle, size: 8, color: pos.isFlat ? WeexionicTheme.textMuted : (pos.isLong ? WeexionicTheme.green : WeexionicTheme.red)),
                    const SizedBox(width: 4),
                    Text(
                      pos.isFlat ? 'NONE / FLAT' : pos.side,
                      style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: WeexionicTheme.textMuted, letterSpacing: 0.5),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: WeexionicTheme.brandGold.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: WeexionicTheme.brandGold.withOpacity(0.3)),
                ),
                child: Text(
                  '${p.getLeverageFor(p.activeSymbol)}X LEVERAGE',
                  style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          // PnL block
          Container(
            padding: const EdgeInsets.symmetric(vertical: 14),
            decoration: const BoxDecoration(
              border: Border(
                top: BorderSide(color: WeexionicTheme.border, width: 1, style: BorderStyle.solid),
                bottom: BorderSide(color: WeexionicTheme.border, width: 1, style: BorderStyle.solid),
              ),
            ),
            child: Column(
              children: [
                const Text(
                  'UNREALIZED PNL',
                  style: TextStyle(fontSize: 10, color: WeexionicTheme.textMuted, letterSpacing: 1),
                ),
                const SizedBox(height: 4),
                Text(
                  '${pos.unrealizedPnl >= 0 ? '+' : ''}\$${pos.unrealizedPnl.toStringAsFixed(2)}',
                  style: TextStyle(fontSize: 28, fontWeight: FontWeight.w700, fontFamily: 'RobotoMono', color: pnlColor),
                ),
                const SizedBox(height: 4),
                Text(
                  'ROE: ${pos.roePct.toStringAsFixed(2)}% · ${pos.isFlat ? "No active position" : "Live tracking"}',
                  style: const TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          // Grid 2 cols
          Row(
            children: [
              Expanded(child: _GridItem(label: 'CONTRACT QTY', value: '${pos.size.abs().toStringAsFixed(4)} ${pos.symbol.replaceAll('USDT', '')}')),
              const SizedBox(width: 14),
              Expanded(child: _GridItem(label: 'ENTRY PRICE', value: pos.entryPrice > 0 ? '\$${pos.entryPrice.toStringAsFixed(2)}' : '—', muted: pos.entryPrice == 0)),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _GridItem(
                label: 'MARK PRICE',
                value: PositionsScreen._fmtMarkPriceStatic(p.getMarkPriceFor(p.activeSymbol)),
                valueColor: WeexionicTheme.textPrimary,
              )),
              const SizedBox(width: 14),
              Expanded(child: _GridItem(label: 'LIQ. PRICE', value: '—', muted: true)),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _GridItem(label: 'MARGIN', value: '—', muted: true)),
              const SizedBox(width: 14),
              Expanded(child: _GridItem(
                label: 'CONFIG. LEVERAGE',
                value: '${p.getLeverageFor(p.activeSymbol)}x',
                valueColor: WeexionicTheme.brandGold,
              )),
            ],
          ),
          const SizedBox(height: 14),
          // SL / TP / Reversal
          Row(
            children: [
              Expanded(child: _SlTpPill(label: 'STOP LOSS', value: '${p.config.stopLossPct.toStringAsFixed(1)}%', color: WeexionicTheme.red)),
              const SizedBox(width: 8),
              Expanded(child: _SlTpPill(label: 'TAKE PROFIT', value: '${p.config.takeProfitPct.toStringAsFixed(1)}% (1:1)', color: WeexionicTheme.green)),
              const SizedBox(width: 8),
              Expanded(child: _SlTpPill(label: 'AUTO-REVERSAL', value: 'ON', color: WeexionicTheme.blue)),
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
  final bool muted;
  final Color? valueColor;

  const _GridItem({required this.label, required this.value, this.muted = false, this.valueColor});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted, letterSpacing: 0.5),
        ),
        const SizedBox(height: 3),
        Text(
          value,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            fontFamily: 'RobotoMono',
            color: valueColor ?? (muted ? WeexionicTheme.textMuted : WeexionicTheme.textPrimary),
          ),
        ),
      ],
    );
  }
}

class _SlTpPill extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _SlTpPill({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: WeexionicTheme.bgElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: Column(
        children: [
          Text(label, style: const TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, letterSpacing: 0.5)),
          const SizedBox(height: 3),
          Text(value, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: color)),
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
          child: _Btn(
            label: 'Close ${p.activeSymbol.substring(0, 3)}',
            icon: Icons.close,
            primary: true,
            color: WeexionicTheme.red,
            onPressed: p.activePosition.isFlat ? null : () => p.closePosition(p.activeSymbol),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _Btn(
            label: 'CLOSE ALL',
            icon: Icons.cancel_outlined,
            primary: true,
            color: WeexionicTheme.red,
            onPressed: () => _confirmCloseAll(context, p),
          ),
        ),
      ],
    );
  }

  void _confirmCloseAll(BuildContext context, BotProvider p) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: WeexionicTheme.bgSurface,
        title: const Text('Close All Positions?'),
        content: const Text('This will close all open positions across all symbols. This action cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: WeexionicTheme.red),
            onPressed: () {
              Navigator.pop(context);
              p.closeAllPositions();
            },
            child: const Text('Close All'),
          ),
        ],
      ),
    );
  }
}

class _Btn extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool primary;
  final Color? color;
  final VoidCallback? onPressed;

  const _Btn({required this.label, required this.icon, required this.primary, this.color, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    final disabled = onPressed == null;
    if (primary) {
      final c = color ?? WeexionicTheme.brandGold;
      return Material(
        color: disabled ? c.withOpacity(0.3) : c,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 9),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(icon, size: 14, color: disabled ? WeexionicTheme.textMuted : Colors.white),
                const SizedBox(width: 4),
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: disabled ? WeexionicTheme.textMuted : Colors.white,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 9),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: WeexionicTheme.borderLight),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 14, color: WeexionicTheme.textSecondary),
              const SizedBox(width: 4),
              Text(label, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: WeexionicTheme.textSecondary)),
            ],
          ),
        ),
      ),
    );
  }
}

class _MonitorTable extends StatelessWidget {
  final BotProvider p;
  const _MonitorTable({required this.p});

  @override
  Widget build(BuildContext context) {
    final symbols = p.config.symbolsList;
    return Container(
      decoration: BoxDecoration(
        color: WeexionicTheme.bgSurface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'MULTI-COIN MONITOR',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: WeexionicTheme.textMuted, letterSpacing: 0.8),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: WeexionicTheme.blue.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '${symbols.length} PAIRS',
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: WeexionicTheme.blue),
                  ),
                ),
              ],
            ),
          ),
          // Header
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
            ),
            child: Row(
              children: const [
                Expanded(flex: 4, child: Text('SYMBOL', style: TextStyle(fontSize: 9.5, color: WeexionicTheme.textMuted, letterSpacing: 0.5, fontWeight: FontWeight.w500))),
                Expanded(flex: 3, child: Text('STATUS', style: TextStyle(fontSize: 9.5, color: WeexionicTheme.textMuted, letterSpacing: 0.5, fontWeight: FontWeight.w500))),
                Expanded(flex: 4, child: Text('MARK PRICE', style: TextStyle(fontSize: 9.5, color: WeexionicTheme.textMuted, letterSpacing: 0.5, fontWeight: FontWeight.w500))),
                Expanded(flex: 2, child: Text('POS', style: TextStyle(fontSize: 9.5, color: WeexionicTheme.textMuted, letterSpacing: 0.5, fontWeight: FontWeight.w500), textAlign: TextAlign.right)),
              ],
            ),
          ),
          // Rows
          ...symbols.map((s) {
            final pos = p.positions[s];
            return _MonitorRow(symbol: s, position: pos, markPrice: p.getMarkPriceFor(s));
          }),
        ],
      ),
    );
  }
}

class _MonitorRow extends StatelessWidget {
  final String symbol;
  final Position? position;
  final double markPrice;
  const _MonitorRow({required this.symbol, required this.position, required this.markPrice});

  @override
  Widget build(BuildContext context) {
    final isFlat = position == null || position!.isFlat;
    final code = symbol.replaceAll('USDT', '').replaceAll('SUSDT', '');

    return InkWell(
      onTap: () => context.read<BotProvider>().setActiveSymbol(symbol),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
        ),
        child: Row(
          children: [
            Expanded(
              flex: 4,
              child: Row(
                children: [
                  _CoinIcon(symbol: symbol, size: 18),
                  const SizedBox(width: 6),
                  Text(
                    symbol,
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ],
              ),
            ),
            Expanded(
              flex: 3,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: isFlat
                      ? WeexionicTheme.textMuted.withOpacity(0.15)
                      : (position!.isLong ? WeexionicTheme.green.withOpacity(0.12) : WeexionicTheme.red.withOpacity(0.12)),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  isFlat ? 'FLAT' : position!.side,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    color: isFlat ? WeexionicTheme.textMuted : (position!.isLong ? WeexionicTheme.green : WeexionicTheme.red),
                  ),
                ),
              ),
            ),
            Expanded(
              flex: 4,
              child: Text(
                markPrice > 0 ? '\$${_fmtPrice(markPrice)}' : '—',
                style: const TextStyle(fontSize: 11.5, color: WeexionicTheme.textSecondary, fontFamily: 'RobotoMono'),
              ),
            ),
            Expanded(
              flex: 2,
              child: Text(
                isFlat ? '0' : position!.size.abs().toStringAsFixed(3),
                textAlign: TextAlign.right,
                style: const TextStyle(fontSize: 11.5, color: WeexionicTheme.textSecondary, fontFamily: 'RobotoMono'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _fmtPrice(double v) {
    if (v >= 1000) return v.toStringAsFixed(2);
    if (v >= 1) return v.toStringAsFixed(2);
    return v.toStringAsFixed(4);
  }
}

class _CoinIcon extends StatelessWidget {
  final String symbol;
  final double size;
  const _CoinIcon({required this.symbol, this.size = 28});

  @override
  Widget build(BuildContext context) {
    final code = symbol.replaceAll('USDT', '').replaceAll('SUSDT', '');
    final display = code.length > 3 ? code.substring(0, 3) : code;
    return Container(
      width: size, height: size,
      decoration: const BoxDecoration(gradient: WeexionicTheme.brandGradient, shape: BoxShape.circle),
      child: Center(
        child: Text(
          display,
          style: TextStyle(
            fontSize: size * 0.32,
            fontWeight: FontWeight.w900,
            color: WeexionicTheme.bgBase,
          ),
        ),
      ),
    );
  }
}
