/// Chart data — matches Socket.IO 'chart_data' & 'indicators' events
/// Source: bot-engine/app.py line ~480-500
///
/// Note: emas in chart_data use keys 'ema8','ema13','ema21','ema55' (no underscore)
/// while indicators/signal events use 'ema_8','ema_13','ema_21','ema_55' (underscore).
/// We handle both shapes here.

class Candle {
  final int time;       // unix seconds
  final double open;
  final double high;
  final double low;
  final double close;

  const Candle({
    required this.time,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
  });

  factory Candle.fromJson(Map<String, dynamic> j) => Candle(
    time: (j['time'] ?? 0).toInt(),
    open: _d(j['open']),
    high: _d(j['high']),
    low: _d(j['low']),
    close: _d(j['close']),
  );

  static double _d(dynamic v) {
    if (v == null) return 0;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? 0;
  }

  DateTime get dateTime => DateTime.fromMillisecondsSinceEpoch(time * 1000);
  bool get isBullish => close >= open;
}

class EmaSeries {
  final List<EmaPoint> points;
  const EmaSeries(this.points);

  factory EmaSeries.fromJsonList(List<dynamic>? list) {
    if (list == null) return const EmaSeries([]);
    return EmaSeries(
      list.map((e) {
        if (e is Map) {
          return EmaPoint(
            time: (e['time'] ?? 0).toInt(),
            value: _d(e['value']),
          );
        }
        return const EmaPoint(time: 0, value: 0);
      }).toList(),
    );
  }

  static double _d(dynamic v) {
    if (v == null) return 0;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? 0;
  }
}

class EmaPoint {
  final int time;
  final double value;
  const EmaPoint({required this.time, required this.value});
}

/// Full chart payload from server
class ChartData {
  final String symbol;
  final List<Candle> candles;
  final EmaSeries ema8;
  final EmaSeries ema13;
  final EmaSeries ema21;
  final EmaSeries ema55;

  const ChartData({
    required this.symbol,
    required this.candles,
    required this.ema8,
    required this.ema13,
    required this.ema21,
    required this.ema55,
  });

  factory ChartData.fromJson(Map<String, dynamic> j) {
    final emas = j['emas'];
    Map<String, dynamic> emasMap = {};
    if (emas is Map) {
      emasMap = emas.cast<String, dynamic>();
    }
    return ChartData(
      symbol: (j['symbol'] ?? '').toString(),
      candles: (j['candles'] as List?)
              ?.map((e) => Candle.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      // Try both key styles (ema8 vs ema_8)
      ema8: EmaSeries.fromJsonList(emasMap['ema8'] ?? emasMap['ema_8']),
      ema13: EmaSeries.fromJsonList(emasMap['ema13'] ?? emasMap['ema_13']),
      ema21: EmaSeries.fromJsonList(emasMap['ema21'] ?? emasMap['ema_21']),
      ema55: EmaSeries.fromJsonList(emasMap['ema55'] ?? emasMap['ema_55']),
    );
  }

  static const empty = ChartData(
    symbol: '',
    candles: [],
    ema8: EmaSeries([]),
    ema13: EmaSeries([]),
    ema21: EmaSeries([]),
    ema55: EmaSeries([]),
  );
}

/// Indicators payload from server (live EMA + signal)
class Indicators {
  final String symbol;
  final double ema8;
  final double ema13;
  final double ema21;
  final double ema55;
  final String signal;        // BUY | SELL | HOLD
  final double emaSepPct;
  final double close;
  final double markPrice;
  final String timestamp;

  const Indicators({
    required this.symbol,
    required this.ema8,
    required this.ema13,
    required this.ema21,
    required this.ema55,
    required this.signal,
    required this.emaSepPct,
    required this.close,
    required this.markPrice,
    required this.timestamp,
  });

  factory Indicators.fromJson(Map<String, dynamic> j) => Indicators(
    symbol: (j['symbol'] ?? '').toString(),
    ema8: _d(j['ema_8']),
    ema13: _d(j['ema_13']),
    ema21: _d(j['ema_21']),
    ema55: _d(j['ema_55']),
    signal: (j['signal'] ?? 'HOLD').toString().toUpperCase(),
    emaSepPct: _d(j['ema_sep_pct']),
    close: _d(j['close']),
    markPrice: _d(j['mark_price']),
    timestamp: (j['timestamp'] ?? '').toString(),
  );

  static double _d(dynamic v) {
    if (v == null) return 0;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? 0;
  }

  static const empty = Indicators(
    symbol: '',
    ema8: 0, ema13: 0, ema21: 0, ema55: 0,
    signal: 'HOLD', emaSepPct: 0, close: 0, markPrice: 0, timestamp: '',
  );
}
