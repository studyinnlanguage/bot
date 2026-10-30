/// Bot status — matches GET /api/status & Socket.IO 'status' event
/// Source: bot-engine/bot/engine.py line 2131-2178
class BotStatus {
  final bool running;
  final int tradesToday;
  final String exchange;
  final List<String> symbols;
  final String timeframe;
  final int leverage;
  final String amountMode;
  final double amount;
  final double amountPct;
  final double stopLossPct;
  final double takeProfitPct;
  final String tpMode;
  final String mode;
  final bool testnet;
  final Map<String, WorkerStatus> workers;

  const BotStatus({
    this.running = false,
    this.tradesToday = 0,
    this.exchange = 'binance',
    this.symbols = const [],
    this.timeframe = '5m',
    this.leverage = 50,
    this.amountMode = 'percent',
    this.amount = 100,
    this.amountPct = 10,
    this.stopLossPct = 2,
    this.takeProfitPct = 2,
    this.tpMode = 'fixed',
    this.mode = 'both',
    this.testnet = true,
    this.workers = const {},
  });

  factory BotStatus.fromJson(Map<String, dynamic> j) {
    final workersMap = <String, WorkerStatus>{};
    final w = j['workers'];
    if (w is Map) {
      w.forEach((key, val) {
        if (val is Map) {
          workersMap[key.toString()] = WorkerStatus.fromJson(val.cast<String, dynamic>());
        }
      });
    }
    return BotStatus(
      running: j['running'] ?? false,
      tradesToday: (j['trades_today'] ?? 0).toInt(),
      exchange: (j['exchange'] ?? 'binance').toString(),
      symbols: (j['symbols'] as List?)?.map((e) => e.toString()).toList() ?? [],
      timeframe: (j['timeframe'] ?? '5m').toString(),
      leverage: (j['leverage'] ?? 50).toInt(),
      amountMode: (j['amount_mode'] ?? 'percent').toString(),
      amount: _d(j['amount'], fallback: 100),
      amountPct: _d(j['amount_pct'], fallback: 10),
      stopLossPct: _d(j['stop_loss_pct'], fallback: 2),
      takeProfitPct: _d(j['take_profit_pct'], fallback: 2),
      tpMode: (j['tp_mode'] ?? 'fixed').toString(),
      mode: (j['mode'] ?? 'both').toString(),
      testnet: j['testnet'] ?? true,
      workers: workersMap,
    );
  }

  static double _d(dynamic v, {double fallback = 0}) {
    if (v == null) return fallback;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? fallback;
  }

  static const empty = BotStatus();
}

class WorkerStatus {
  final int candlesProcessed;
  final int tradesToday;
  final String lastSignal;       // BUY | SELL | HOLD
  final String? lastTradeSide;   // LONG | SHORT | null
  final String lastCheck;        // ISO
  final bool alive;

  const WorkerStatus({
    this.candlesProcessed = 0,
    this.tradesToday = 0,
    this.lastSignal = 'HOLD',
    this.lastTradeSide,
    this.lastCheck = '',
    this.alive = false,
  });

  factory WorkerStatus.fromJson(Map<String, dynamic> j) => WorkerStatus(
    candlesProcessed: (j['candles_processed'] ?? 0).toInt(),
    tradesToday: (j['trades_today'] ?? 0).toInt(),
    lastSignal: (j['last_signal'] ?? 'HOLD').toString().toUpperCase(),
    lastTradeSide: j['last_trade_side']?.toString().toUpperCase(),
    lastCheck: (j['last_check'] ?? '').toString(),
    alive: j['alive'] ?? false,
  );
}
