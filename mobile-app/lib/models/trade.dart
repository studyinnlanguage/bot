/// Trade history record — matches bot-engine GET /api/trades & 'trades_updated' event
/// Source: bot-engine/bot/history.py record_open() + get_stats()
class Trade {
  final String id;
  final String symbol;
  final String side;          // 'LONG' | 'SHORT'
  final String orderType;     // 'maker' | 'market'
  final double entryPrice;
  final double? exitPrice;
  final double qty;
  final int leverage;
  final double margin;
  final double? initialSl;
  final double? initialTp;
  final String openedAt;      // ISO 8601
  final int openedTs;         // unix sec
  final String? closedAt;
  final int? closedTs;
  final String status;        // 'OPEN' | 'CLOSED'
  final String? closeReason;
  final double pnl;
  final double roePct;
  final double feeEst;
  final int trailingStage;
  final double highestRoe;

  const Trade({
    required this.id,
    required this.symbol,
    required this.side,
    required this.orderType,
    required this.entryPrice,
    this.exitPrice,
    required this.qty,
    required this.leverage,
    required this.margin,
    this.initialSl,
    this.initialTp,
    required this.openedAt,
    required this.openedTs,
    this.closedAt,
    this.closedTs,
    required this.status,
    this.closeReason,
    required this.pnl,
    required this.roePct,
    required this.feeEst,
    this.trailingStage = 1,
    this.highestRoe = 0,
  });

  factory Trade.fromJson(Map<String, dynamic> j) => Trade(
    id: (j['id'] ?? '').toString(),
    symbol: (j['symbol'] ?? '').toString().toUpperCase(),
    side: (j['side'] ?? '').toString().toUpperCase(),
    orderType: (j['order_type'] ?? 'market').toString(),
    entryPrice: _d(j['entry_price']),
    exitPrice: j['exit_price'] == null ? null : _d(j['exit_price']),
    qty: _d(j['qty']),
    leverage: (j['leverage'] ?? 1).toInt(),
    margin: _d(j['margin']),
    initialSl: j['initial_sl'] == null ? null : _d(j['initial_sl']),
    initialTp: j['initial_tp'] == null ? null : _d(j['initial_tp']),
    openedAt: (j['opened_at'] ?? '').toString(),
    openedTs: (j['opened_ts'] ?? 0).toInt(),
    closedAt: j['closed_at']?.toString(),
    closedTs: j['closed_ts']?.toInt(),
    status: (j['status'] ?? 'OPEN').toString().toUpperCase(),
    closeReason: j['close_reason']?.toString(),
    pnl: _d(j['pnl']),
    roePct: _d(j['roe_pct']),
    feeEst: _d(j['fee_est']),
    trailingStage: (j['trailing_stage'] ?? 1).toInt(),
    highestRoe: _d(j['highest_roe']),
  );

  static double _d(dynamic v, {double fallback = 0}) {
    if (v == null) return fallback;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? fallback;
  }

  bool get isOpen => status == 'OPEN';
  bool get isClosed => status == 'CLOSED';
  bool get isLong => side == 'LONG';
  bool get isWin => pnl > 0;

  DateTime? get openedDateTime =>
      DateTime.tryParse(openedAt)?.toLocal();

  String get openedTimeStr {
    final dt = openedDateTime;
    if (dt == null) return '';
    return '${dt.day.toString().padLeft(2, '0')}/${dt.month.toString().padLeft(2, '0')} '
           '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }
}

/// Trade stats — matches stats object in 'trades_updated' & GET /api/trades
class TradeStats {
  final int totalTrades;
  final int wins;
  final int losses;
  final double winRatePct;
  final double totalPnl;
  final double totalFees;
  final double netPnl;
  final double bestPnl;
  final double worstPnl;
  final double avgTradePnl;

  const TradeStats({
    this.totalTrades = 0,
    this.wins = 0,
    this.losses = 0,
    this.winRatePct = 0,
    this.totalPnl = 0,
    this.totalFees = 0,
    this.netPnl = 0,
    this.bestPnl = 0,
    this.worstPnl = 0,
    this.avgTradePnl = 0,
  });

  factory TradeStats.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const TradeStats();
    return TradeStats(
      totalTrades: (j['total_trades'] ?? 0).toInt(),
      wins: (j['wins'] ?? 0).toInt(),
      losses: (j['losses'] ?? 0).toInt(),
      winRatePct: _d(j['win_rate_pct']),
      totalPnl: _d(j['total_pnl']),
      totalFees: _d(j['total_fees']),
      netPnl: _d(j['net_pnl']),
      bestPnl: _d(j['best_pnl']),
      worstPnl: _d(j['worst_pnl']),
      avgTradePnl: _d(j['avg_trade_pnl']),
    );
  }

  static double _d(dynamic v, {double fallback = 0}) {
    if (v == null) return fallback;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? fallback;
  }

  static const empty = TradeStats();
}
