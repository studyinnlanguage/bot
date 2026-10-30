import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../models/trade.dart';
import '../widgets/stat_card.dart';
import '../widgets/common.dart';

class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.watch<BotProvider>();
    final stats = p.stats;
    final trades = p.trades;

    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(context, p),
            Expanded(
              child: RefreshIndicator(
                color: WeexionicTheme.brandGold,
                onRefresh: () => p.fetchTrades(),
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
                  children: [
                    // Stats grid
                    StatCard(
                      label: 'Total Trades',
                      value: '${stats.totalTrades}',
                      subtitle: '${stats.wins} Wins · ${stats.losses} Losses',
                      gradient: true,
                      valueColor: WeexionicTheme.brandGold,
                      full: true,
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(child: StatCard(label: 'Win Rate', value: '${stats.winRatePct.toStringAsFixed(1)}%', valueColor: WeexionicTheme.brandGold)),
                        const SizedBox(width: 10),
                        Expanded(child: StatCard(label: 'Net P&L', value: '${stats.netPnl >= 0 ? "+" : ""}\$${stats.netPnl.toStringAsFixed(2)}', valueColor: stats.netPnl >= 0 ? WeexionicTheme.green : WeexionicTheme.red)),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(child: StatCard(label: 'Est. Fees', value: '\$${stats.totalFees.toStringAsFixed(2)}')),
                        const SizedBox(width: 10),
                        Expanded(
                          child: StatCard(
                            label: 'Best / Worst',
                            value: '',
                            subtitle: '+${stats.bestPnl.toStringAsFixed(2)} / ${stats.worstPnl.toStringAsFixed(2)}',
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    // Filters
                    const _FiltersCard(),
                    const SizedBox(height: 12),
                    // Trades table
                    _TradesTable(trades: trades),
                    const SizedBox(height: 12),
                    // Export buttons
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () {},
                            icon: const Icon(Icons.download, size: 16),
                            label: const Text('Export CSV', style: TextStyle(fontSize: 11)),
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
                            icon: const Icon(Icons.picture_as_pdf, size: 16),
                            label: const Text('Export PDF', style: TextStyle(fontSize: 11)),
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
          const Icon(Icons.history, color: WeexionicTheme.textSecondary, size: 22),
          const SizedBox(width: 12),
          const Expanded(
            child: Text('Trade History', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          ),
          IconButton(
            icon: const Icon(Icons.filter_list, size: 22),
            onPressed: () {},
          ),
        ],
      ),
    );
  }
}

class _FiltersCard extends StatelessWidget {
  const _FiltersCard();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: WeexionicTheme.bgSurface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: Column(
        children: [
          Row(
            children: const [
              Expanded(child: _FilterItem(label: 'FROM', value: '2025-10-01')),
              SizedBox(width: 10),
              Expanded(child: _FilterItem(label: 'TO', value: '2025-10-30')),
              SizedBox(width: 10),
              Expanded(child: _FilterItem(label: 'DIR', value: 'All')),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: const [
              Expanded(child: _FilterItem(label: 'SYMBOL', value: 'All symbols')),
              SizedBox(width: 10),
              Expanded(child: _FilterItem(label: 'TYPE', value: 'All')),
            ],
          ),
        ],
      ),
    );
  }
}

class _FilterItem extends StatelessWidget {
  final String label;
  final String value;
  const _FilterItem({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
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
            children: [
              Text(
                label,
                style: const TextStyle(fontSize: 9, color: WeexionicTheme.textMuted),
              ),
              const SizedBox(height: 2),
              Text(
                value,
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const Icon(Icons.keyboard_arrow_down, size: 14, color: WeexionicTheme.textMuted),
        ],
      ),
    );
  }
}

class _TradesTable extends StatelessWidget {
  final List<Trade> trades;
  const _TradesTable({required this.trades});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: WeexionicTheme.bgSurface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
            decoration: const BoxDecoration(
              color: WeexionicTheme.bgElevated,
              borderRadius: BorderRadius.vertical(top: Radius.circular(12)),
              border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
            ),
            child: Row(
              children: const [
                Expanded(flex: 2, child: Text('TIME', style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w600, letterSpacing: 0.4))),
                Expanded(flex: 2, child: Text('PAIR', style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w600, letterSpacing: 0.4))),
                Expanded(flex: 2, child: Text('DIR', style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w600, letterSpacing: 0.4))),
                Expanded(flex: 2, child: Text('TYPE', style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w600, letterSpacing: 0.4))),
                Expanded(flex: 3, child: Text('ENTRY→EXIT', style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w600, letterSpacing: 0.4))),
                Expanded(flex: 2, child: Text('PNL', style: TextStyle(fontSize: 9, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w600, letterSpacing: 0.4), textAlign: TextAlign.right)),
              ],
            ),
          ),
          if (trades.isEmpty)
            const EmptyState(
              icon: Icons.receipt_long,
              title: 'No trades matching current filters',
              subtitle: 'Once the bot starts executing trades, they will appear here with full details.',
            )
          else
            ...trades.map((t) => _TradeRow(trade: t)),
        ],
      ),
    );
  }
}

class _TradeRow extends StatelessWidget {
  final Trade trade;
  const _TradeRow({required this.trade});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        children: [
          Expanded(
            flex: 2,
            child: Text(
              trade.openedTimeStr,
              style: const TextStyle(fontSize: 10, color: WeexionicTheme.textSecondary, fontFamily: 'RobotoMono'),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              trade.symbol,
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
            ),
          ),
          Expanded(
            flex: 2,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: trade.isLong ? WeexionicTheme.green.withValues(alpha: 0.12) : WeexionicTheme.red.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                trade.side,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 9,
                  fontWeight: FontWeight.w700,
                  color: trade.isLong ? WeexionicTheme.green : WeexionicTheme.red,
                ),
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              trade.orderType,
              style: const TextStyle(fontSize: 10, color: WeexionicTheme.textSecondary),
            ),
          ),
          Expanded(
            flex: 3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '\$${_fmt(trade.entryPrice)}',
                  style: const TextStyle(fontSize: 10, color: WeexionicTheme.textSecondary, fontFamily: 'RobotoMono'),
                ),
                Text(
                  trade.exitPrice != null ? '→ \$${_fmt(trade.exitPrice!)}' : '→ OPEN',
                  style: TextStyle(
                    fontSize: 10,
                    color: trade.exitPrice != null ? WeexionicTheme.textSecondary : WeexionicTheme.brandGold,
                    fontFamily: 'RobotoMono',
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              '${trade.pnl >= 0 ? '+' : ''}\$${trade.pnl.toStringAsFixed(2)}',
              textAlign: TextAlign.right,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                fontFamily: 'RobotoMono',
                color: trade.pnl > 0
                    ? WeexionicTheme.green
                    : trade.pnl < 0
                        ? WeexionicTheme.red
                        : WeexionicTheme.textMuted,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _fmt(double v) {
    if (v >= 1000) return v.toStringAsFixed(1);
    if (v >= 1) return v.toStringAsFixed(2);
    return v.toStringAsFixed(4);
  }
}
