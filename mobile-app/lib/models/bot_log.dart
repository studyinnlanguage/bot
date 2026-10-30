import '../core/config.dart';

/// Bot log entry — matches Socket.IO 'log' event payload {level, msg}
/// Note: server emits NO timestamp/symbol — we add a client-side timestamp
/// and parse symbol from msg text if present ([BTCUSDT] ...).
class BotLog {
  final DateTime timestamp;  // client-side on receipt
  final LogLevel level;
  final String message;
  final String? symbol;      // parsed from [SYMBOL] prefix in msg

  BotLog({
    required this.timestamp,
    required this.level,
    required this.message,
    this.symbol,
  });

  factory BotLog.fromSocket(Map<String, dynamic> data) {
    final msg = (data['msg'] ?? '').toString();
    final levelStr = (data['level'] ?? 'info').toString();
    // Parse [SYMBOL] prefix
    final m = RegExp(r'^\[([A-Z]+/USD[A-Z]*|[A-Z]+USDT)\]').firstMatch(msg);
    return BotLog(
      timestamp: DateTime.now().toLocal(),
      level: LogLevelX.fromString(levelStr),
      message: msg,
      symbol: m?.group(1),
    );
  }

  String get timeStr {
    final h = timestamp.hour.toString().padLeft(2, '0');
    final m = timestamp.minute.toString().padLeft(2, '0');
    final s = timestamp.second.toString().padLeft(2, '0');
    return '$h:$m:$s';
  }
}
