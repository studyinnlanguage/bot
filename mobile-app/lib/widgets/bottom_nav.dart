import 'package:flutter/material.dart';
import '../core/theme.dart';

/// Main bottom navigation bar — 5 items matching mockups
class WeexionicBottomNav extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;

  const WeexionicBottomNav({super.key, required this.currentIndex, required this.onTap});

  static const _items = [
    _NavItem(icon: Icons.home_filled, label: 'Home'),
    _NavItem(icon: Icons.show_chart, label: 'Terminal'),
    _NavItem(icon: Icons.dashboard_outlined, label: 'Positions'),
    _NavItem(icon: Icons.history, label: 'History'),
    _NavItem(icon: Icons.settings, label: 'Settings'),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 64,
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(top: BorderSide(color: WeexionicTheme.border, width: 1)),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          children: List.generate(_items.length, (i) {
            final item = _items[i];
            final active = i == currentIndex;
            return Expanded(
              child: InkWell(
                onTap: () => onTap(i),
                child: Stack(
                  children: [
                    if (active)
                      Positioned(
                        top: 0,
                        left: 0, right: 0,
                        child: Center(
                          child: Container(
                            width: 32, height: 3,
                            decoration: BoxDecoration(
                              gradient: WeexionicTheme.brandGradient,
                              borderRadius: const BorderRadius.vertical(bottom: Radius.circular(4)),
                            ),
                          ),
                        ),
                      ),
                    Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            item.icon,
                            size: 22,
                            color: active ? WeexionicTheme.brandGold : WeexionicTheme.textFaint,
                          ),
                          const SizedBox(height: 3),
                          Text(
                            item.label,
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w500,
                              color: active ? WeexionicTheme.brandGold : WeexionicTheme.textFaint,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            );
          }),
        ),
      ),
    );
  }
}

class _NavItem {
  final IconData icon;
  final String label;
  const _NavItem({required this.icon, required this.label});
}

/// FAB-style floating action button — gold gradient
class WeexionicFab extends StatelessWidget {
  final IconData icon;
  final VoidCallback onPressed;
  final String? tooltip;

  const WeexionicFab({
    super.key,
    required this.icon,
    required this.onPressed,
    this.tooltip,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        gradient: WeexionicTheme.brandGradient,
        boxShadow: [
          BoxShadow(
            color: WeexionicTheme.brandGold.withOpacity(0.4),
            blurRadius: 20,
            offset: const Offset(0, 6),
          ),
        ],
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
}
