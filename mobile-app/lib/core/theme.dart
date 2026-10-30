import 'package:flutter/material.dart';

/// WEEXIONIC Design System — Binance-style + Neon glow
class WeexionicTheme {
  WeexionicTheme._();

  // === Binance Colors ===
  static const Color bgBase = Color(0xFF0B0E11);       // Binance deep black
  static const Color bgSurface = Color(0xFF181A20);    // Binance dark surface
  static const Color bgElevated = Color(0xFF1E2329);   // Binance elevated
  static const Color bgHover = Color(0xFF2B3139);

  static const Color border = Color(0xFF2B3139);
  static const Color borderLight = Color(0xFF363D4A);

  // Brand: Binance yellow + neon glow
  static const Color brandGold = Color(0xFFF0B90B);    // Binance yellow
  static const Color brandAmber = Color(0xFFFFC000);
  static const Color brandDeep = Color(0xFFE0A800);

  // Neon accents
  static const Color green = Color(0xFF02C076);        // Binance neon green
  static const Color red = Color(0xFFF6465D);          // Binance neon red
  static const Color blue = Color(0xFF1E9EFF);         // Binance blue
  static const Color purple = Color(0xFFB07AFF);
  static const Color cyan = Color(0xFF00E5FF);         // neon cyan
  static const Color pink = Color(0xFFFF3D8B);         // neon pink

  // Text
  static const Color textPrimary = Color(0xFFFFFFFF);
  static const Color textSecondary = Color(0xFFEAECEF);
  static const Color textMuted = Color(0xFF848E9C);
  static const Color textFaint = Color(0xFF5E6673);

  // === Gradients ===
  static const LinearGradient brandGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFF0B90B), Color(0xFFFFC000)],
  );

  static const LinearGradient brandGradientSoft = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0x1FF0B90B), Color(0x14FFC000)],
  );

  static const LinearGradient neonGreenGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF02C076), Color(0xFF00E8B5)],
  );

  static const LinearGradient neonRedGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFF6465D), Color(0xFFFF3D8B)],
  );

  static const LinearGradient darkCardGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF1E2329), Color(0xFF181A20)],
  );

  // === Neon Glow Effects ===
  static List<BoxShadow> get goldGlow => [
    BoxShadow(
      color: brandGold.withOpacity(0.4),
      blurRadius: 20,
      spreadRadius: -2,
      offset: const Offset(0, 6),
    ),
  ];

  static List<BoxShadow> get greenGlow => [
    BoxShadow(
      color: green.withOpacity(0.4),
      blurRadius: 20,
      spreadRadius: -2,
      offset: const Offset(0, 6),
    ),
  ];

  static List<BoxShadow> get redGlow => [
    BoxShadow(
      color: red.withOpacity(0.4),
      blurRadius: 20,
      spreadRadius: -2,
      offset: const Offset(0, 6),
    ),
  ];

  static List<BoxShadow> get cyanGlow => [
    BoxShadow(
      color: cyan.withOpacity(0.3),
      blurRadius: 16,
      spreadRadius: -2,
      offset: const Offset(0, 4),
    ),
  ];

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
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: brandGold, width: 1.5),
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
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
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

  // === Helpers ===
  static LinearGradient pnlGradient(double pnl) {
    if (pnl >= 0) {
      return LinearGradient(colors: [green.withOpacity(0.15), green.withOpacity(0.05)]);
    }
    return LinearGradient(colors: [red.withOpacity(0.15), red.withOpacity(0.05)]);
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
