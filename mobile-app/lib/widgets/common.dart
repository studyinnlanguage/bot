import 'package:flutter/material.dart';
import '../core/theme.dart';

/// Empty state widget — icon + title + subtitle
class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? subtitle;
  final Color? iconColor;

  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.iconColor,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 30, horizontal: 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 56, height: 56,
            decoration: BoxDecoration(
              color: WeexionicTheme.bgElevated,
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: iconColor ?? WeexionicTheme.textFaint, size: 28),
          ),
          const SizedBox(height: 12),
          Text(
            title,
            style: const TextStyle(
              fontSize: 13,
              color: WeexionicTheme.textSecondary,
              fontWeight: FontWeight.w500,
            ),
            textAlign: TextAlign.center,
          ),
          if (subtitle != null) ...[
            const SizedBox(height: 4),
            Text(
              subtitle!,
              style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted),
              textAlign: TextAlign.center,
            ),
          ],
        ],
      ),
    );
  }
}

/// Compact info row — label + value
class InfoRow extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  final Widget? trailing;

  const InfoRow({
    super.key,
    required this.label,
    required this.value,
    this.valueColor,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
          ),
          if (trailing != null) trailing!,
          if (trailing == null)
            Text(
              value,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: valueColor ?? WeexionicTheme.textPrimary,
                fontFamily: 'RobotoMono',
              ),
            ),
        ],
      ),
    );
  }
}

/// Section title — with gold accent bar
class SectionTitle extends StatelessWidget {
  final String title;
  final Widget? trailing;

  const SectionTitle({super.key, required this.title, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 10),
      child: Row(
        children: [
          Container(
            width: 3, height: 16,
            decoration: const BoxDecoration(gradient: WeexionicTheme.brandGradient),
          ),
          const SizedBox(width: 8),
          Text(
            title,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: WeexionicTheme.textPrimary,
              letterSpacing: 0.3,
            ),
          ),
          const Spacer(),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

/// Segmented control — Material 3 style
class SegmentedControl<T> extends StatelessWidget {
  final List<T> options;
  final T selected;
  final ValueChanged<T> onChanged;
  final List<String>? labels;

  const SegmentedControl({
    super.key,
    required this.options,
    required this.selected,
    required this.onChanged,
    this.labels,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: WeexionicTheme.bgElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: Row(
        children: List.generate(options.length, (i) {
          final opt = options[i];
          final active = opt == selected;
          return Expanded(
            child: GestureDetector(
              onTap: () => onChanged(opt),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 8),
                decoration: BoxDecoration(
                  color: active ? null : Colors.transparent,
                  gradient: active ? WeexionicTheme.brandGradient : null,
                  borderRadius: BorderRadius.circular(7),
                ),
                child: Text(
                  labels != null ? labels![i] : opt.toString(),
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: active ? WeexionicTheme.bgBase : WeexionicTheme.textMuted,
                  ),
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}
