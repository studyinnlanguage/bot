import 'package:flutter/material.dart';
import '../core/theme.dart';

/// Glassmorphism card — gradient background + subtle blur effect + neon border option
class GlassCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets? padding;
  final EdgeInsets? margin;
  final BorderRadius? radius;
  final Color? borderColor;
  final Gradient? gradient;
  final List<BoxShadow>? shadows;
  final VoidCallback? onTap;

  const GlassCard({
    super.key,
    required this.child,
    this.padding,
    this.margin,
    this.radius,
    this.borderColor,
    this.gradient,
    this.shadows,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: margin,
      decoration: BoxDecoration(
        borderRadius: radius ?? BorderRadius.circular(16),
        gradient: gradient ?? WeexionicTheme.darkCardGradient,
        border: Border.all(
          color: borderColor ?? WeexionicTheme.border,
          width: 1,
        ),
        boxShadow: shadows,
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: radius ?? BorderRadius.circular(16),
          child: Padding(
            padding: padding ?? const EdgeInsets.all(16),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// Neon button — gradient background with glow shadow
class NeonButton extends StatelessWidget {
  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final NeonButtonStyle style;
  final bool loading;
  final double height;
  final double fontSize;

  const NeonButton({
    super.key,
    required this.label,
    this.icon,
    required this.onPressed,
    this.style = NeonButtonStyle.gold,
    this.loading = false,
    this.height = 50,
    this.fontSize = 14,
  });

  @override
  Widget build(BuildContext context) {
    final disabled = onPressed == null || loading;
    final (gradient, glow, fgColor) = _styleData();

    return SizedBox(
      height: height,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          gradient: disabled ? null : gradient,
          color: disabled ? WeexionicTheme.bgElevated : null,
          boxShadow: disabled ? null : glow,
          border: Border.all(
            color: disabled ? WeexionicTheme.border : Colors.transparent,
          ),
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: disabled ? null : onPressed,
            borderRadius: BorderRadius.circular(12),
            child: Center(
              child: loading
                  ? SizedBox(
                      width: 22, height: 22,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.5,
                        color: fgColor,
                      ),
                    )
                  : Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (icon != null) ...[
                          Icon(icon, size: 18, color: fgColor),
                          const SizedBox(width: 8),
                        ],
                        Text(
                          label,
                          style: TextStyle(
                            fontSize: fontSize,
                            fontWeight: FontWeight.w800,
                            color: fgColor,
                            letterSpacing: 1.2,
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

  (LinearGradient, List<BoxShadow>, Color) _styleData() {
    switch (style) {
      case NeonButtonStyle.gold:
        return (WeexionicTheme.brandGradient, WeexionicTheme.goldGlow, WeexionicTheme.bgBase);
      case NeonButtonStyle.green:
        return (WeexionicTheme.neonGreenGradient, WeexionicTheme.greenGlow, WeexionicTheme.bgBase);
      case NeonButtonStyle.red:
        return (WeexionicTheme.neonRedGradient, WeexionicTheme.redGlow, Colors.white);
      case NeonButtonStyle.outline:
        return (LinearGradient(colors: [Colors.transparent, Colors.transparent]), [], WeexionicTheme.textPrimary);
    }
  }
}

enum NeonButtonStyle { gold, green, red, outline }

/// Shimmer placeholder — animated loading state for numbers/text
class ShimmerPlaceholder extends StatefulWidget {
  final double width;
  final double height;
  final BorderRadius borderRadius;

  const ShimmerPlaceholder({
    super.key,
    this.width = double.infinity,
    this.height = 14,
    this.borderRadius = const BorderRadius.all(Radius.circular(4)),
  });

  @override
  State<ShimmerPlaceholder> createState() => _ShimmerPlaceholderState();
}

class _ShimmerPlaceholderState extends State<ShimmerPlaceholder>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
    _animation = Tween<double>(begin: -1, end: 1).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (_, __) {
        final sign = _animation.value.sign;
        final abs = _animation.value.abs();
        return Container(
          width: widget.width,
          height: widget.height,
          decoration: BoxDecoration(
            borderRadius: widget.borderRadius,
            gradient: LinearGradient(
              begin: Alignment(sign * -1, 0),
              end: Alignment(sign * 1, 0),
              colors: [
                WeexionicTheme.bgElevated,
                WeexionicTheme.bgHover.withOpacity(0.4 + abs * 0.5),
                WeexionicTheme.bgElevated,
              ],
              stops: const [0, 0.5, 1],
            ),
          ),
        );
      },
    );
  }
}

/// Gradient progress bar — for license days remaining, balance trend, etc.
class GradientProgressBar extends StatelessWidget {
  final double progress;  // 0.0 - 1.0
  final Gradient? gradient;
  final Color? trackColor;
  final double height;
  final BorderRadius? borderRadius;

  const GradientProgressBar({
    super.key,
    required this.progress,
    this.gradient,
    this.trackColor,
    this.height = 6,
    this.borderRadius,
  });

  @override
  Widget build(BuildContext context) {
    final clamped = progress.clamp(0.0, 1.0);
    return ClipRRect(
      borderRadius: borderRadius ?? BorderRadius.circular(height / 2),
      child: Stack(
        children: [
          Container(
            height: height,
            color: trackColor ?? WeexionicTheme.bgElevated,
          ),
          FractionallySizedBox(
            widthFactor: clamped,
            child: Container(
              height: height,
              decoration: BoxDecoration(
                gradient: gradient ?? WeexionicTheme.brandGradient,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Pulsing glow dot — for live status indicators
class PulsingGlowDot extends StatefulWidget {
  final Color color;
  final double size;
  final bool active;

  const PulsingGlowDot({
    super.key,
    required this.color,
    this.size = 8,
    this.active = true,
  });

  @override
  State<PulsingGlowDot> createState() => _PulsingGlowDotState();
}

class _PulsingGlowDotState extends State<PulsingGlowDot>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _animation = Tween<double>(begin: 0.5, end: 1.0).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
    if (widget.active) _controller.repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.active) {
      return Container(
        width: widget.size,
        height: widget.size,
        decoration: BoxDecoration(
          color: widget.color,
          shape: BoxShape.circle,
        ),
      );
    }
    return AnimatedBuilder(
      animation: _animation,
      builder: (_, __) {
        return Container(
          width: widget.size,
          height: widget.size,
          decoration: BoxDecoration(
            color: widget.color.withOpacity(_animation.value),
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: widget.color.withOpacity(_animation.value * 0.6),
                blurRadius: widget.size * 1.5,
                spreadRadius: 0,
              ),
            ],
          ),
        );
      },
    );
  }
}

/// Section header with gold accent bar + icon + title
class SectionHeader extends StatelessWidget {
  final String title;
  final IconData? icon;
  final Widget? trailing;
  final Color? accentColor;

  const SectionHeader({
    super.key,
    required this.title,
    this.icon,
    this.trailing,
    this.accentColor,
  });

  @override
  Widget build(BuildContext context) {
    final color = accentColor ?? WeexionicTheme.brandGold;
    return Padding(
      padding: const EdgeInsets.only(top: 14, bottom: 10),
      child: Row(
        children: [
          Container(
            width: 3, height: 14,
            decoration: BoxDecoration(
              gradient: WeexionicTheme.brandGradient,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          if (icon != null) ...[
            Icon(icon, size: 14, color: color),
            const SizedBox(width: 6),
          ],
          Text(
            title,
            style: TextStyle(
              fontSize: 13,
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
