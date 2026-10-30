import 'package:flutter/material.dart';
import '../core/theme.dart';

/// Binance-style bottom nav — glow on active, sharper icons, premium feel
class WeexionicBottomNav extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;

  const WeexionicBottomNav({super.key, required this.currentIndex, required this.onTap});

  static const _items = [
    _NavItem(icon: Icons.home_rounded, label: 'Home', activeIcon: Icons.home),
    _NavItem(icon: Icons.terminal_outlined, label: 'Terminal', activeIcon: Icons.terminal),
    _NavItem(icon: Icons.account_balance_wallet_outlined, label: 'Positions', activeIcon: Icons.account_balance_wallet),
    _NavItem(icon: Icons.history_rounded, label: 'History', activeIcon: Icons.history),
    _NavItem(icon: Icons.tune_rounded, label: 'Settings', activeIcon: Icons.tune),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(
          top: BorderSide(
            color: WeexionicTheme.brandGold.withOpacity(0.15),
            width: 1,
          ),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.5),
            blurRadius: 12,
            offset: const Offset(0, -4),
          ),
        ],
      ),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 60,
          child: Row(
            children: List.generate(_items.length, (i) {
              final item = _items[i];
              final active = i == currentIndex;
              return Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onTap(i),
                  child: _NavTab(item: item, active: active),
                ),
              );
            }),
          ),
        ),
      ),
    );
  }
}

class _NavTab extends StatelessWidget {
  final _NavItem item;
  final bool active;
  const _NavTab({required this.item, required this.active});

  @override
  Widget build(BuildContext context) {
    return Stack(
      alignment: Alignment.topCenter,
      children: [
        // Active glow indicator on top
        if (active)
          Positioned(
            top: 0,
            child: Container(
              width: 40,
              height: 3,
              decoration: BoxDecoration(
                gradient: WeexionicTheme.brandGradient,
                borderRadius: const BorderRadius.vertical(bottom: Radius.circular(4)),
                boxShadow: [
                  BoxShadow(
                    color: WeexionicTheme.brandGold.withOpacity(0.6),
                    blurRadius: 8,
                    spreadRadius: 0,
                  ),
                ],
              ),
            ),
          ),
        // Icon + label
        Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ShaderMask(
                shaderCallback: active
                    ? (b) => WeexionicTheme.brandGradient.createShader(b)
                    : (b) => LinearGradient(colors: [WeexionicTheme.textFaint, WeexionicTheme.textFaint]).createShader(b),
                child: Icon(
                  active ? item.activeIcon : item.icon,
                  size: 22,
                  color: Colors.white,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                item.label,
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                  color: active ? WeexionicTheme.brandGold : WeexionicTheme.textFaint,
                  letterSpacing: 0.3,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _NavItem {
  final IconData icon;
  final IconData activeIcon;
  final String label;
  const _NavItem({required this.icon, required this.activeIcon, required this.label});
}

/// FAB-style floating action button — gold gradient + neon glow
class WeexionicFab extends StatelessWidget {
  final IconData icon;
  final VoidCallback onPressed;
  final String? tooltip;
  final FabStyle style;

  const WeexionicFab({
    super.key,
    required this.icon,
    required this.onPressed,
    this.tooltip,
    this.style = FabStyle.gold,
  });

  @override
  Widget build(BuildContext context) {
    final (gradient, glow) = _styleData();
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        gradient: gradient,
        boxShadow: glow,
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(18),
          child: SizedBox(
            width: 56, height: 56,
            child: Icon(icon, color: WeexionicTheme.bgBase, size: 24),
          ),
        ),
      ),
    );
  }

  (LinearGradient, List<BoxShadow>) _styleData() {
    switch (style) {
      case FabStyle.gold:
        return (WeexionicTheme.brandGradient, WeexionicTheme.goldGlow);
      case FabStyle.green:
        return (WeexionicTheme.neonGreenGradient, WeexionicTheme.greenGlow);
      case FabStyle.red:
        return (WeexionicTheme.neonRedGradient, WeexionicTheme.redGlow);
    }
  }
}

enum FabStyle { gold, green, red }
