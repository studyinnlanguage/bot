/// User + Subscription models — matches SaaS app.py /api/auth/me response
/// Source: root app.py (SaaS) check_subscription() + current_user()

class User {
  final String id;
  final String email;
  final String name;
  final String? role;        // 'admin' or null (regular user)
  final String referralCode;
  final String? referredBy;
  final String? licenseKey;
  final Subscription subscription;
  final BotConfigSnapshot botConfig;
  final bool botRunning;

  const User({
    required this.id,
    required this.email,
    required this.name,
    this.role,
    required this.referralCode,
    this.referredBy,
    this.licenseKey,
    required this.subscription,
    required this.botConfig,
    this.botRunning = false,
  });

  factory User.fromJson(Map<String, dynamic> j) => User(
    id: (j['id'] ?? '').toString(),
    email: (j['email'] ?? '').toString(),
    name: (j['name'] ?? '').toString(),
    role: j['role']?.toString(),
    referralCode: (j['referral_code'] ?? '').toString(),
    referredBy: j['referred_by']?.toString(),
    licenseKey: j['license_key']?.toString(),
    subscription: Subscription.fromJson(j['subscription'] as Map<String, dynamic>?),
    botConfig: BotConfigSnapshot.fromJson(j['bot_config'] as Map<String, dynamic>?),
    botRunning: j['bot_running'] ?? false,
  );

  bool get isAdmin => role == 'admin';
}

class Subscription {
  final bool active;
  final String status;       // 'active' | 'expired' | 'none' | 'error'
  final int daysLeft;
  final String plan;         // 'yearly' | 'lifetime' | 'basic' | 'none' | etc.
  final String? expiresAt;   // ISO 8601

  const Subscription({
    this.active = false,
    this.status = 'none',
    this.daysLeft = 0,
    this.plan = 'none',
    this.expiresAt,
  });

  factory Subscription.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const Subscription();
    return Subscription(
      active: j['active'] ?? false,
      status: (j['status'] ?? 'none').toString(),
      daysLeft: (j['days_left'] ?? 0).toInt(),
      plan: (j['plan'] ?? 'none').toString(),
      expiresAt: j['expires_at']?.toString(),
    );
  }

  bool get isLifetime => plan == 'lifetime' || daysLeft >= 9999;
  bool get isExpired => status == 'expired' || status == 'none' || !active;
  bool get isActive => active && status == 'active';

  String get displayPlan {
    if (isLifetime) return 'Lifetime';
    if (plan == 'yearly') return '1-Year';
    if (plan == 'basic') return 'Basic';
    return plan.isNotEmpty ? plan : 'None';
  }

  String get displayDaysLeft {
    if (isLifetime) return 'Lifetime';
    if (daysLeft <= 0) return 'Expired';
    return '$daysLeft days left';
  }
}

/// Lightweight snapshot of bot_config from /api/auth/me
/// (Full config fetched separately via GET /bot/api/config)
class BotConfigSnapshot {
  final String exchange;
  final bool testnet;
  final List<String> symbolsList;
  final String timeframe;
  final int leverage;
  final String amountMode;
  final double amount;
  final double amountPct;
  final double stopLossPct;
  final double takeProfitPct;
  final String mode;
  final int maxConcurrentTrades;
  final bool hasApiKey;
  final bool hasPassphrase;

  const BotConfigSnapshot({
    this.exchange = 'binance',
    this.testnet = true,
    this.symbolsList = const [],
    this.timeframe = '5m',
    this.leverage = 50,
    this.amountMode = 'percent',
    this.amount = 100,
    this.amountPct = 10,
    this.stopLossPct = 2,
    this.takeProfitPct = 2,
    this.mode = 'both',
    this.maxConcurrentTrades = 1,
    this.hasApiKey = false,
    this.hasPassphrase = false,
  });

  factory BotConfigSnapshot.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const BotConfigSnapshot();
    return BotConfigSnapshot(
      exchange: (j['exchange'] ?? 'binance').toString(),
      testnet: j['testnet'] ?? true,
      symbolsList: (j['symbols_list'] as List?)?.map((e) => e.toString()).toList() ?? [],
      timeframe: (j['timeframe'] ?? '5m').toString(),
      leverage: (j['leverage'] ?? 50).toInt(),
      amountMode: (j['amount_mode'] ?? 'percent').toString(),
      amount: _d(j['amount'], fallback: 100),
      amountPct: _d(j['amount_pct'], fallback: 10),
      stopLossPct: _d(j['stop_loss_pct'], fallback: 2),
      takeProfitPct: _d(j['take_profit_pct'], fallback: 2),
      mode: (j['mode'] ?? 'both').toString(),
      maxConcurrentTrades: (j['max_concurrent_trades'] ?? 1).toInt(),
      hasApiKey: j['has_api_key'] ?? false,
      hasPassphrase: j['has_passphrase'] ?? false,
    );
  }

  static double _d(dynamic v, {double fallback = 0}) {
    if (v == null) return fallback;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? fallback;
  }
}
