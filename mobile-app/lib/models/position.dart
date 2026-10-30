/// Position model — matches bot-engine Socket.IO 'position' event & GET /api/positions response
/// Source: bot-engine/app.py line 432-445 + engine.py line 705-718
class Position {
  final String symbol;
  final String side;          // 'LONG' | 'SHORT' | 'NONE'
  final double size;          // signed: +long, -short
  final double entryPrice;
  final double markPrice;
  final double unrealizedPnl;
  final int leverage;
  final int tpStage;
  final double tpPrice;
  final double slPrice;
  final double targetRoe;
  final String tpMode;        // 'fixed' | 'trailing' | 'ema_reversal'

  const Position({
    required this.symbol,
    required this.side,
    required this.size,
    required this.entryPrice,
    required this.markPrice,
    required this.unrealizedPnl,
    required this.leverage,
    this.tpStage = 0,
    this.tpPrice = 0,
    this.slPrice = 0,
    this.targetRoe = 100,
    this.tpMode = 'fixed',
  });

  factory Position.fromJson(Map<String, dynamic> j) => Position(
    symbol: (j['symbol'] ?? '').toString(),
    side: (j['side'] ?? 'NONE').toString().toUpperCase(),
    size: _d(j['size']),
    entryPrice: _d(j['entry_price']),
    markPrice: _d(j['mark_price']),
    unrealizedPnl: _d(j['unrealized_pnl']),
    leverage: (j['leverage'] ?? 1).toInt(),
    tpStage: (j['tp_stage'] ?? 0).toInt(),
    tpPrice: _d(j['tp_price']),
    slPrice: _d(j['sl_price']),
    targetRoe: _d(j['target_roe'], fallback: 100),
    tpMode: (j['tp_mode'] ?? 'fixed').toString(),
  );

  static double _d(dynamic v, {double fallback = 0}) {
    if (v == null) return fallback;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? fallback;
  }

  bool get isFlat => side == 'NONE' || size.abs() < 0.0000001;
  bool get isLong => side == 'LONG';
  bool get isShort => side == 'SHORT';

  double get roePct {
    if (entryPrice == 0 || leverage == 0 || size.abs() == 0) return 0;
    final diff = (markPrice - entryPrice) * (isLong ? 1 : -1);
    return (diff / entryPrice) * leverage * 100;
  }

  Map<String, dynamic> toJson() => {
    'symbol': symbol,
    'side': side,
    'size': size,
    'entry_price': entryPrice,
    'mark_price': markPrice,
    'unrealized_pnl': unrealizedPnl,
    'leverage': leverage,
    'tp_stage': tpStage,
    'tp_price': tpPrice,
    'sl_price': slPrice,
    'target_roe': targetRoe,
    'tp_mode': tpMode,
  };

  static const empty = Position(
    symbol: '', side: 'NONE', size: 0, entryPrice: 0,
    markPrice: 0, unrealizedPnl: 0, leverage: 1,
  );
}
