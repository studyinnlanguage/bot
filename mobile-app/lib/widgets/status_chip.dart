import 'package:flutter/material.dart';
import '../core/theme.dart';

/// Status chip — colored pill with optional pulsing dot
class StatusChip extends StatelessWidget {
  final String label;
  final StatusChipType type;
  final bool pulsing;
  final IconData? icon;

  const StatusChip({
    super.key,
    required this.label,
    required this.type,
    this.pulsing = false,
    this.icon,
  });

  factory StatusChip.running({bool running = true}) => StatusChip(
    label: running ? 'RUNNING' : 'STOPPED',
    type: running ? StatusChipType.success : StatusChipType.danger,
    pulsing: running,
  );

  factory StatusChip.testnet() => const StatusChip(
    label: 'TESTNET',
    type: StatusChipType.info,
  );

  factory StatusChip.live() => const StatusChip(
    label: 'LIVE SOCKET',
    type: StatusChipType.danger,
    pulsing: true,
  );

  @override
  Widget build(BuildContext context) {
    final (fg, bg, border) = _colors();
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: border, width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (pulsing)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: _PulsingDot(color: fg),
            ),
          if (icon != null)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Icon(icon, size: 12, color: fg),
            ),
          Text(
            label,
            style: TextStyle(
              color: fg,
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }

  (Color, Color, Color) _colors() {
    switch (type) {
      case StatusChipType.success:
        return (WeexionicTheme.green, WeexionicTheme.green.withOpacity(0.12), WeexionicTheme.green.withOpacity(0.3));
      case StatusChipType.danger:
        return (WeexionicTheme.red, WeexionicTheme.red.withOpacity(0.12), WeexionicTheme.red.withOpacity(0.3));
      case StatusChipType.info:
        return (WeexionicTheme.blue, WeexionicTheme.blue.withOpacity(0.12), WeexionicTheme.blue.withOpacity(0.3));
      case StatusChipType.gold:
        return (WeexionicTheme.brandGold, WeexionicTheme.brandGold.withOpacity(0.15), WeexionicTheme.brandGold.withOpacity(0.3));
      case StatusChipType.flat:
        return (WeexionicTheme.textMuted, WeexionicTheme.textMuted.withOpacity(0.15), Colors.transparent);
    }
  }
}

enum StatusChipType { success, danger, info, gold, flat }

class _PulsingDot extends StatefulWidget {
  final Color color;
  const _PulsingDot({required this.color});

  @override
  State<_PulsingDot> createState() => _PulsingDotState();
}

class _PulsingDotState extends State<_PulsingDot> with SingleTickerProviderStateMixin {
  late AnimationController _c;
  late Animation<double> _a;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1500));
    _a = Tween<double>(begin: 1.0, end: 0.4).animate(CurvedAnimation(parent: _c, curve: Curves.easeInOut));
    _c.repeat(reverse: true);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _a,
      builder: (_, __) => Opacity(
        opacity: _a.value,
        child: Container(
          width: 6, height: 6,
          decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle),
        ),
      ),
    );
  }
}
