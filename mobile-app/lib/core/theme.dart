import 'package:flutter/material.dart';

/// WEEXIONIC Design System — Material 3 + Custom Dark Charcoal + Gold theme
/// Matches the mobile mockups exactly
class WeexionicTheme {
  WeexionicTheme._();

  // === Brand Colors (matches mockups) ===
  static const Color bgBase = Color(0xFF0A0E14);
  static const Color bgSurface = Color(0xFF131722);
  static const Color bgElevated = Color(0xFF1B2028);
  static const Color bgHover = Color(0xFF232831);

  static const Color border = Color(0xFF2B3139);
  static const Color borderLight = Color(0xFF363D4A);

  // Brand: gold/amber gradient
  static const Color brandGold = Color(0xFFF5B800);
  static const Color brandAmber = Color(0xFFFF8A00);
  static const Color brandDeep = Color(0xFFD4A017);

  static const Color green = Color(0xFF0ECB81);    // success / LONG
  static const Color red = Color(0xFFF6465D);      // danger / SHORT
  static const Color blue = Color(0xFF4A8CFF);     // info / testnet
  static const Color purple = Color(0xFFA471FF);

  // Text
  static const Color textPrimary = Color(0xFFFFFFFF);
  static const Color textSecondary = Color(0xFFB7BDC6);
  static const Color textMuted = Color(0xFF848E9C);
  static const Color textFaint = Color(0xFF5E6673);

  // === Gradients ===
  static const LinearGradient brandGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [brandGold, brandAmber],
  );

  static const LinearGradient brandGradientSoft = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0x26F5B800), Color(0x14FF8A00)],
  );

  // === ThemeData ===
  static ThemeData get darkTheme {
    final base = ThemeData.dark(useMaterial3: true);
    return base.copyWith(
      scaffoldBackgroundColor: bgBase,
      canvasColor: bgBase,
      primaryColor: brandGold,
      colorScheme: base.colorScheme.copyWith(
        primary: brandGold,
        secondary: brandAmber,
        surface: bgSurface,
        background: bgBase,
        error: red,
        onPrimary: bgBase,
        onSurface: textPrimary,
        onBackground: textPrimary,
        brightness: Brightness.dark,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: bgSurface,
        foregroundColor: textPrimary,
        elevation: 0,
        centerTitle: false,
        titleSpacing: 0,
        iconTheme: IconThemeData(color: textSecondary, size: 22),
      ),
      cardTheme: CardTheme(
        color: bgSurface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: border, width: 1),
        ),
        margin: EdgeInsets.zero,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: bgElevated,
        hintStyle: const TextStyle(color: textMuted, fontSize: 13),
        labelStyle: const TextStyle(color: textMuted, fontSize: 11),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: brandGold),
        ),
      ),
      dividerTheme: const DividerThemeData(color: border, thickness: 1, space: 1),
      iconTheme: const IconThemeData(color: textSecondary, size: 22),
      textTheme: const TextTheme(
        displayLarge: TextStyle(fontSize: 32, fontWeight: FontWeight.w700, color: textPrimary),
        headlineMedium: TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: textPrimary),
        titleLarge: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: textPrimary),
        titleMedium: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: textPrimary),
        bodyLarge: TextStyle(fontSize: 14, color: textPrimary),
        bodyMedium: TextStyle(fontSize: 12, color: textSecondary),
        bodySmall: TextStyle(fontSize: 11, color: textMuted),
        labelSmall: TextStyle(fontSize: 10, color: textMuted, letterSpacing: 0.5),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: brandGold),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: brandGold,
          foregroundColor: bgBase,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          textStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
        ),
      ),
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: bgSurface,
        selectedItemColor: brandGold,
        unselectedItemColor: textFaint,
        type: BottomNavigationBarType.fixed,
        showUnselectedLabels: true,
        selectedLabelStyle: TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
        unselectedLabelStyle: TextStyle(fontSize: 10),
      ),
    );
  }

  // === Reusable helpers ===
  static LinearGradient pnlGradient(double pnl) {
    if (pnl >= 0) {
      return LinearGradient(colors: [green.withValues(alpha: 0.15), green.withValues(alpha: 0.05)]);
    }
    return LinearGradient(colors: [red.withValues(alpha: 0.15), red.withValues(alpha: 0.05)]);
  }
}

/// Brand widget: gradient text logo
class WeexionicLogo extends StatelessWidget {
  final double size;
  const WeexionicLogo({super.key, this.size = 20});

  @override
  Widget build(BuildContext context) {
    return ShaderMask(
      shaderCallback: (bounds) => WeexionicTheme.brandGradient.createShader(bounds),
      child: Text(
        'WEEXIONIC',
        style: TextStyle(
          fontSize: size,
          fontWeight: FontWeight.w900,
          letterSpacing: 1,
          color: Colors.white,
        ),
      ),
    );
  }
}
