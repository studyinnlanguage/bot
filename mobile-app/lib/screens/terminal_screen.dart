import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/config.dart';
import '../core/theme.dart';
import '../models/bot_log.dart';
import '../widgets/status_chip.dart';
import '../widgets/common.dart';

class TerminalScreen extends StatefulWidget {
  const TerminalScreen({super.key});

  @override
  State<TerminalScreen> createState() => _TerminalScreenState();
}

class _TerminalScreenState extends State<TerminalScreen> {
  LogLevel? _filter;
  bool _autoScroll = true;
  final _scrollCtrl = ScrollController();
  StreamSubscription? _logSub;
  BotProvider? _prov;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _prov ??= context.read<BotProvider>();
    _logSub ??= _prov!.logStream.listen((_) {
      if (_autoScroll && _scrollCtrl.hasClients) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _scrollCtrl.animateTo(
            _scrollCtrl.position.maxScrollExtent,
            duration: const Duration(milliseconds: 100),
            curve: Curves.easeOut,
          );
        });
      }
    });
  }

  @override
  void dispose() {
    _logSub?.cancel();
    _scrollCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.watch<BotProvider>();
    final logs = p.filteredLogs(level: _filter);

    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(p),
            _buildFilterTabs(),
            Expanded(child: _buildTerminal(logs, p)),
            _buildControls(),
          ],
        ),
      ),
    );
  }

  Widget _buildAppBar(BotProvider p) {
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        children: [
          const Icon(Icons.terminal, color: WeexionicTheme.textSecondary, size: 22),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Text('Live Terminal', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                Row(
                  children: [
                    StatusChip.live(),
                    const SizedBox(width: 8),
                    if (p.socketConnected)
                      const Text('● Connected', style: TextStyle(fontSize: 10, color: WeexionicTheme.green))
                    else
                      const Text('● Disconnected', style: TextStyle(fontSize: 10, color: WeexionicTheme.red)),
                  ],
                ),
              ],
            ),
          ),
          StatusChip.testnet(),
        ],
      ),
    );
  }

  Widget _buildFilterTabs() {
    final counts = {
      LogLevel.info: context.read<BotProvider>().logs.where((l) => l.level == LogLevel.info).length,
      LogLevel.success: context.read<BotProvider>().logs.where((l) => l.level == LogLevel.success).length,
      LogLevel.warn: context.read<BotProvider>().logs.where((l) => l.level == LogLevel.warn).length,
      LogLevel.error: context.read<BotProvider>().logs.where((l) => l.level == LogLevel.error).length,
    };
    final all = counts.values.fold(0, (a, b) => a + b);

    final tabs = [
      ('All', null, all),
      ('Info', LogLevel.info, counts[LogLevel.info]!),
      ('Success', LogLevel.success, counts[LogLevel.success]!),
      ('Warning', LogLevel.warn, counts[LogLevel.warn]!),
      ('Error', LogLevel.error, counts[LogLevel.error]!),
    ];

    return Container(
      height: 50,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      color: WeexionicTheme.bgBase,
      child: ListView(
        scrollDirection: Axis.horizontal,
        children: tabs.map((t) {
          final active = _filter == t.$2;
          return Padding(
            padding: const EdgeInsets.only(right: 6),
            child: GestureDetector(
              onTap: () => setState(() => _filter = t.$2),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                decoration: BoxDecoration(
                  color: active ? WeexionicTheme.brandGold : WeexionicTheme.bgElevated,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: WeexionicTheme.border),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      t.$1,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: active ? WeexionicTheme.bgBase : WeexionicTheme.textMuted,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${t.$3}',
                      style: TextStyle(
                        fontSize: 10,
                        color: active ? WeexionicTheme.bgBase.withOpacity(0.7) : WeexionicTheme.textFaint,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildTerminal(List<BotLog> logs, BotProvider p) {
    if (logs.isEmpty) {
      return Container(
        margin: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: const Color(0xFF06080C),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: WeexionicTheme.border),
        ),
        child: _AnimatedEmptyTerminal(connected: p.socketConnected),
      );
    }

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 14),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF06080C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: ListView.builder(
        controller: _scrollCtrl,
        itemCount: logs.length,
        itemBuilder: (_, i) {
          final log = logs[i];
          return _LogLine(log: log);
        },
      ),
    );
  }

  Widget _buildControls() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      color: WeexionicTheme.bgBase,
      child: Row(
        children: [
          Expanded(
            child: _CtrlBtn(
              icon: _autoScroll ? Icons.vertical_align_bottom : Icons.pause,
              label: 'Auto-scroll',
              active: _autoScroll,
              onTap: () => setState(() => _autoScroll = !_autoScroll),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _CtrlBtn(
              icon: Icons.delete_outline,
              label: 'Clear',
              active: false,
              onTap: () => context.read<BotProvider>().clearLogs(),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _CtrlBtn(
              icon: Icons.download,
              label: 'Export',
              active: false,
              onTap: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Log export coming soon')),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _LogLine extends StatelessWidget {
  final BotLog log;
  const _LogLine({required this.log});

  @override
  Widget build(BuildContext context) {
    final (color, _) = _levelStyle();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            log.timeStr,
            style: const TextStyle(
              color: WeexionicTheme.textFaint,
              fontSize: 10.5,
              fontFamily: 'RobotoMono',
            ),
          ),
          const SizedBox(width: 6),
          if (log.symbol != null) ...[
            Text(
              '[${log.symbol}]',
              style: const TextStyle(color: WeexionicTheme.blue, fontSize: 10.5, fontFamily: 'RobotoMono', fontWeight: FontWeight.w600),
            ),
            const SizedBox(width: 6),
          ],
          Expanded(
            child: Text(
              log.message,
              style: TextStyle(
                color: color,
                fontSize: 10.5,
                fontFamily: 'RobotoMono',
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }

  (Color, String) _levelStyle() {
    switch (log.level) {
      case LogLevel.success:
        return (WeexionicTheme.green, '✓');
      case LogLevel.error:
        return (WeexionicTheme.red, '✗');
      case LogLevel.warn:
        return (WeexionicTheme.brandGold, '⚠');
      case LogLevel.info:
      default:
        return (WeexionicTheme.textSecondary, 'ℹ');
    }
  }
}

class _CtrlBtn extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback onTap;

  const _CtrlBtn({
    required this.icon,
    required this.label,
    required this.active,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: WeexionicTheme.bgElevated,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: active ? WeexionicTheme.green : WeexionicTheme.border,
            ),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 14, color: active ? WeexionicTheme.green : WeexionicTheme.textSecondary),
              const SizedBox(width: 4),
              Text(
                label,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: active ? WeexionicTheme.green : WeexionicTheme.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Animated empty terminal state — pulsing icon + blinking cursor
class _AnimatedEmptyTerminal extends StatefulWidget {
  final bool connected;
  const _AnimatedEmptyTerminal({required this.connected});

  @override
  State<_AnimatedEmptyTerminal> createState() => _AnimatedEmptyTerminalState();
}

class _AnimatedEmptyTerminalState extends State<_AnimatedEmptyTerminal>
    with TickerProviderStateMixin {
  late AnimationController _pulseCtrl;
  late AnimationController _blinkCtrl;
  late Animation<double> _pulseAnim;
  late Animation<double> _blinkAnim;

  @override
  void initState() {
    super.initState();
    _pulseCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);
    _pulseAnim = Tween<double>(begin: 0.5, end: 1.0).animate(
      CurvedAnimation(parent: _pulseCtrl, curve: Curves.easeInOut),
    );

    _blinkCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat();
    _blinkAnim = Tween<double>(begin: 1.0, end: 0.0).animate(
      CurvedAnimation(parent: _blinkCtrl, curve: Curves.linear),
    );
  }

  @override
  void dispose() {
    _pulseCtrl.dispose();
    _blinkCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 20),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          AnimatedBuilder(
            animation: _pulseAnim,
            builder: (_, __) {
              return Container(
                width: 64, height: 64,
                decoration: BoxDecoration(
                  color: WeexionicTheme.bgElevated,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: widget.connected
                        ? WeexionicTheme.green.withOpacity(_pulseAnim.value * 0.6)
                        : WeexionicTheme.textMuted.withOpacity(_pulseAnim.value * 0.4),
                    width: 1.5,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: widget.connected
                          ? WeexionicTheme.green.withOpacity(_pulseAnim.value * 0.3)
                          : WeexionicTheme.textMuted.withOpacity(_pulseAnim.value * 0.2),
                      blurRadius: 20,
                      spreadRadius: 0,
                    ),
                  ],
                ),
                child: Icon(
                  Icons.terminal,
                  size: 28,
                  color: widget.connected
                      ? WeexionicTheme.green
                      : WeexionicTheme.textMuted,
                ),
              );
            },
          ),
          const SizedBox(height: 16),
          Text(
            widget.connected ? "Waiting for logs..." : "Live stream offline",
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: widget.connected ? WeexionicTheme.textPrimary : WeexionicTheme.textMuted,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            widget.connected
                ? "Tap START on the home screen to begin streaming bot activity."
                : "Bot data is still updating via auto-polling.\nLive logs require socket connection — reconnecting...",
            style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, height: 1.5),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 14),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                "> ",
                style: TextStyle(
                  fontSize: 14,
                  color: WeexionicTheme.brandGold,
                  fontFamily: "RobotoMono",
                  fontWeight: FontWeight.w700,
                ),
              ),
              AnimatedBuilder(
                animation: _blinkAnim,
                builder: (_, __) {
                  return Opacity(
                    opacity: _blinkAnim.value,
                    child: Container(
                      width: 8, height: 14,
                      color: WeexionicTheme.brandGold,
                    ),
                  );
                },
              ),
            ],
          ),
        ],
      ),
    );
  }
}

