import 'package:flutter/material.dart';
import '../core/theme.dart';

/// Stat card — small bordered card with label + value
class StatCard extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  final String? subtitle;
  final bool gradient;
  final bool full;

  const StatCard({
    super.key,
    required this.label,
    required this.value,
    this.valueColor,
    this.subtitle,
    this.gradient = false,
    this.full = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: full ? double.infinity : null,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: gradient ? WeexionicTheme.bgElevated : WeexionicTheme.bgSurface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: WeexionicTheme.border),
        gradient: gradient ? WeexionicTheme.brandGradientSoft : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label.toUpperCase(),
            style: const TextStyle(
              fontSize: 10,
              color: WeexionicTheme.textMuted,
              letterSpacing: 0.5,
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: valueColor ?? WeexionicTheme.textPrimary,
              fontFamily: 'RobotoMono',
            ),
          ),
          if (subtitle != null) ...[
            const SizedBox(height: 2),
            Text(
              subtitle!,
              style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
            ),
          ],
        ],
      ),
    );
  }
}

/// Compact stat — used in 3-column grids on dashboard hero
class CompactStat extends StatelessWidget {
  final String value;
  final String label;
  final Color? valueColor;

  const CompactStat({super.key, required this.value, required this.label, this.valueColor});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
      decoration: BoxDecoration(
        color: WeexionicTheme.bgSurface.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        children: [
          Text(
            value,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: valueColor ?? WeexionicTheme.textPrimary,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            label.toUpperCase(),
            style: const TextStyle(
              fontSize: 9,
              color: WeexionicTheme.textMuted,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}
