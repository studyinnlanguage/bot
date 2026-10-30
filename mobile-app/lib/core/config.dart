/// WEEXIONIC App Configuration
/// Backend: https://weexionic.duckdns.org (production)
/// Bot engine runs under /bot/ prefix (SaaS proxy mode)

class AppConfig {
  AppConfig._();

  // === Backend Configuration ===
  /// Base URL of your deployed bot (no trailing slash)
  static const String baseUrl = 'https://weexionic.duckdns.org';

  /// Bot engine prefix (since bot is served at /bot/ on your VPS)
  /// All API endpoints become: baseUrl + botPrefix + '/api/...'
  static const String botPrefix = '/bot';

  // === Derived URLs ===
  static String get apiBase => '$baseUrl$botPrefix/api';

  /// Socket.IO connects to the bot path (no /socket.io suffix - library adds it)
  static String get socketUrl => '$baseUrl$botPrefix';

  // === Optional auth token (if BOT_ENGINE_TOKEN is set on server) ===
  /// Leave empty if your server has BOT_ENGINE_TOKEN unset (open access)
  /// If set, paste the value here. Sent as 'X-Bot-Token' header on REST calls.
  static const String botToken = '';

  // === App identity ===
  static const String appName = 'WEEXIONIC';
  static const String appTagline = 'FUTURES BOT';
  static const String appVersion = '1.0.0';

  // === API Endpoints (matches bot-engine/app.py exactly) ===
  // Config & settings
  static const String epConfig = '/config';
  static const String epLeverage = '/leverage';
  static const String epTestNotification = '/test_notification';

  // Bot lifecycle
  static const String epStart = '/start';
  static const String epStop = '/stop';
  static const String epForceStop = '/force_stop';
  static const String epActiveSymbol = '/active_symbol';
  static const String epStatus = '/status';

  // Positions & trading
  static const String epPositions = '/positions';
  static const String epClose = '/close';
  static const String epCloseAll = '/close_all';

  // Market data
  static const String epPrice = '/price';
  static const String epSymbols = '/symbols';
  static const String epTestChart = '/test_chart';

  // History & balance
  static const String epTrades = '/trades';
  static const String epTradesClear = '/trades/clear';
  static const String epBalance = '/balance';
  static const String epTestConnection = '/test_connection';
  static const String epPreview = '/preview';
}

/// Socket.IO event names (matches engine.py emits exactly)
class SocketEvents {
  SocketEvents._();

  // Built-in
  static const String connect = 'connect';
  static const String disconnect = 'disconnect';
  static const String connectError = 'connect_error';
  static const String reconnect = 'reconnect';
  static const String reconnectError = 'reconnect_error';

  // Server → Client (data events)
  static const String log = 'log';                 // {level, msg}
  static const String status = 'status';           // full status dict
  static const String indicators = 'indicators';   // EMA + signal
  static const String chartData = 'chart_data';    // candles + EMAs
  static const String signal = 'signal';           // {symbol, signal, reason, emas, just_crossed?}
  static const String position = 'position';       // position dict
  static const String balance = 'balance';         // {balance, exchange, testnet}
  static const String tradesUpdated = 'trades_updated'; // {trades[], stats{}}
}

/// Log level enum matching server emits
enum LogLevel { info, warn, error, success }

extension LogLevelX on LogLevel {
  String get name => toString().split('.').last;
  static LogLevel fromString(String? s) {
    switch (s?.toLowerCase()) {
      case 'warn': return LogLevel.warn;
      case 'error': return LogLevel.error;
      case 'success': return LogLevel.success;
      default: return LogLevel.info;
    }
  }
}
