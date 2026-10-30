import 'dart:async';
import 'dart:collection';
import 'package:flutter/foundation.dart';
import 'api_service.dart';
import 'socket_service.dart';
import '../core/config.dart';
import '../models/bot_log.dart';
import '../models/bot_config.dart';
import '../models/bot_status.dart';
import '../models/position.dart';
import '../models/trade.dart';
import '../models/chart_data.dart';

/// Central app state — Provider pattern
/// Holds: config, status, positions, trades, logs, chart data, balance
/// Wires Socket.IO streams + REST API together
class BotProvider extends ChangeNotifier {
  final ApiService _api = ApiService();
  final SocketService _socket = SocketService();

  // === State ===
  BotConfig _config = BotConfig();
  BotStatus _status = BotStatus.empty;
  TradeStats _stats = TradeStats.empty;
  List<Trade> _trades = [];
  Map<String, Position> _positions = {};   // keyed by symbol
  List<BotLog> _logs = [];
  final StreamController<BotLog> _logCtrl = StreamController<BotLog>.broadcast();
  ChartData _chart = ChartData.empty;
  Indicators _indicators = Indicators.empty;
  double _balance = 0;
  String _activeSymbol = 'BTCUSDT';
  bool _socketConnected = false;
  bool _loading = false;
  String? _error;

  // All available symbols from exchange (fetched from /api/symbols)
  List<String> _availableSymbols = [];
  bool _symbolsLoaded = false;
  // Per-symbol chart data cache for multi-coin view
  final Map<String, ChartData> _chartCache = {};

  // Auto-polling timer — fallback when Socket.IO is not connected
  // Polls every 5s when socket down, 30s when socket up
  Timer? _pollTimer;
  Timer? _chartPollTimer;
  DateTime? _lastPollTime;

  // Getters
  BotConfig get config => _config;
  BotStatus get status => _status;
  TradeStats get stats => _stats;
  List<Trade> get trades => _trades;
  Map<String, Position> get positions => _positions;
  List<BotLog> get logs => UnmodifiableListView(_logs);
  /// Stream of newly-arrived log entries (for terminal auto-scroll)
  Stream<BotLog> get logStream => _logCtrl.stream;
  ChartData get chart => _chart;
  Indicators get indicators => _indicators;
  double get balance => _balance;
  String get activeSymbol => _activeSymbol;
  bool get socketConnected => _socketConnected;
  bool get loading => _loading;
  String? get error => _error;
  bool get isRunning => _status.running;

  /// All available symbols from the exchange (fetched from /api/symbols)
  List<String> get availableSymbols => _availableSymbols;
  bool get symbolsLoaded => _symbolsLoaded;

  /// Per-symbol chart cache for multi-coin view
  ChartData? getChartFor(String symbol) => _chartCache[symbol];

  /// Get mark price for a symbol — falls back to chart cache if position.markPrice is 0
  /// This ensures prices always show even when bot returns 0 for FLAT positions
  double getMarkPriceFor(String symbol) {
    // 1. Try position mark_price
    final pos = _positions[symbol];
    if (pos != null && pos.markPrice > 0) return pos.markPrice;
    // 2. Try chart cache (last candle close)
    final cd = _chartCache[symbol];
    if (cd != null && cd.candles.isNotEmpty) {
      return cd.candles.last.close;
    }
    // 3. Try indicators
    if (_indicators.symbol == symbol && _indicators.markPrice > 0) {
      return _indicators.markPrice;
    }
    return 0;
  }

  /// Get leverage for a symbol — falls back to config when position is FLAT
  int getLeverageFor(String symbol) {
    final pos = _positions[symbol];
    if (pos != null && !pos.isFlat) return pos.leverage;
    return _config.leverage;
  }

  Position get activePosition => _positions[_activeSymbol] ?? Position.empty;

  List<BotLog> filteredLogs({LogLevel? level, String? symbol}) {
    return _logs.where((l) {
      if (level != null && l.level != level) return false;
      if (symbol != null && l.symbol != symbol) return false;
      return true;
    }).toList();
  }

  // === Stream subscriptions ===
  final List<StreamSubscription> _subs = [];

  BotProvider() {
    // Don't auto-connect on construction — wait until user is authenticated
    // (Socket.IO + REST both require auth cookie via SaaS proxy)
  }

  /// Called by main_screen once auth is confirmed
  Future<void> start() async {
    if (_started) return;
    _started = true;
    _init();
  }

  /// Called on logout — disconnect socket, clear state
  Future<void> stop() async {
    _pollTimer?.cancel();
    _chartPollTimer?.cancel();
    for (final s in _subs) {
      s.cancel();
    }
    _subs.clear();
    _socket.disconnect();
    _started = false;
    _config = BotConfig();
    _status = BotStatus.empty;
    _stats = TradeStats.empty;
    _trades = [];
    _positions = {};
    _logs = [];
    _chart = ChartData.empty;
    _indicators = Indicators.empty;
    _balance = 0;
    notifyListeners();
  }

  bool _started = false;

  void _init() {
    // Socket.IO subscriptions
    _subs.add(_socket.connection.listen((connected) {
      _socketConnected = connected;
      notifyListeners();
      if (connected) {
        // Socket up — slow down polling (only as backup)
        _restartPolling(intervalSeconds: 30);
        // On connect, fetch initial state
        refreshAll();
      } else {
        // Socket down — speed up polling for real-time feel
        _restartPolling(intervalSeconds: 5);
      }
    }));

    _subs.add(_socket.logs.listen((log) {
      _logs.add(log);
      // Cap logs to last 500
      if (_logs.length > 500) {
        _logs.removeRange(0, _logs.length - 500);
      }
      _logCtrl.add(log);
      notifyListeners();
    }));

    _subs.add(_socket.status.listen((data) {
      _status = BotStatus.fromJson(data);
      notifyListeners();
    }));

    _subs.add(_socket.indicators.listen((data) {
      _indicators = Indicators.fromJson(data);
      notifyListeners();
    }));

    _subs.add(_socket.chartData.listen((data) {
      final cd = ChartData.fromJson(data);
      // Cache per-symbol for multi-coin view
      if (cd.symbol.isNotEmpty) {
        _chartCache[cd.symbol] = cd;
      }
      if (cd.symbol == _activeSymbol || cd.symbol.isNotEmpty) {
        _chart = cd;
        notifyListeners();
      }
    }));

    _subs.add(_socket.position.listen((data) {
      final pos = Position.fromJson(data.cast<String, dynamic>());
      _positions[pos.symbol] = pos;
      notifyListeners();
    }));

    _subs.add(_socket.balance.listen((data) {
      _balance = (data['balance'] ?? 0).toDouble();
      notifyListeners();
    }));

    _subs.add(_socket.trades.listen((data) {
      final tList = data['trades'];
      if (tList is List) {
        _trades = tList.map((e) => Trade.fromJson(e as Map<String, dynamic>)).toList();
      }
      final stats = data['stats'];
      if (stats is Map<String, dynamic>) {
        _stats = TradeStats.fromJson(stats);
      }
      notifyListeners();
    }));

    // Connect socket (async — fetches session cookie first)
    _socket.connect();

    // Initial fetch
    refreshAll();

    // Start auto-polling (5s initially since socket not yet connected)
    _restartPolling(intervalSeconds: 5);

    // Start chart polling for active symbol (fetches from /api/test_chart)
    _startChartPolling();

    // Immediately fetch charts for ALL monitored coins (don't wait for first poll)
    _fetchAllCharts();
  }

  /// Fetch charts for all monitored coins immediately (called on startup)
  Future<void> _fetchAllCharts() async {
    for (final sym in _config.symbolsList) {
      if (sym.isNotEmpty) {
        _fetchChartForSymbol(sym);
      }
    }
  }

  /// Restart polling with new interval
  void _restartPolling({required int intervalSeconds}) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(Duration(seconds: intervalSeconds), (_) {
      _pollLoop();
    });
  }

  /// Polling loop — fetches status, positions, balance, trades
  /// Called automatically every 5s (socket down) or 30s (socket up)
  void _pollLoop() {
    if (_loading) return;  // skip if a manual refresh is in progress
    _lastPollTime = DateTime.now();
    // Fetch in parallel — don't block UI
    fetchStatus();
    fetchPositions();
    fetchBalance();
    // Trades less frequently (only if socket hasn't updated them)
    if (_trades.isEmpty || !_socketConnected) {
      fetchTrades();
    }
  }

  /// Start chart polling — fetches candlestick data for ALL monitored symbols via REST
  /// Active symbol polled every 15s, all others every 60s
  void _startChartPolling() {
    _chartPollTimer?.cancel();
    int tick = 0;
    _chartPollTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      // Active symbol — fetch every tick (15s)
      _fetchChartForSymbol(_activeSymbol);
      // All monitored coins — fetch every 4th tick (60s)
      tick++;
      if (tick % 4 == 0) {
        for (final sym in _config.symbolsList) {
          if (sym != _activeSymbol && sym.isNotEmpty) {
            _fetchChartForSymbol(sym);
          }
        }
      }
    });
  }

  /// Fetch chart data for a symbol via REST (/api/test_chart)
  /// Used as fallback when socket chart_data isn't working
  Future<void> _fetchChartForSymbol(String symbol) async {
    if (symbol.isEmpty) return;
    try {
      final r = await _api.getTestChart(symbol);
      final candles = r['candles'];
      if (candles is List && candles.isNotEmpty) {
        // Build ChartData from REST response
        final candleList = candles
            .map((e) => Candle.fromJson(e as Map<String, dynamic>))
            .toList();
        // Calculate EMAs from candle closes (simple SMA fallback if not in response)
        final cd = ChartData(
          symbol: symbol,
          candles: candleList,
          ema8: _calcEma(candleList, 8),
          ema13: _calcEma(candleList, 13),
          ema21: _calcEma(candleList, 21),
          ema55: _calcEma(candleList, 55),
        );
        _chartCache[symbol] = cd;
        if (symbol == _activeSymbol) {
          _chart = cd;
          notifyListeners();
        }
      }
    } catch (e) {
      debugPrint('chart fetch error for $symbol: $e');
    }
  }

  /// Calculate EMA series from candle list
  EmaSeries _calcEma(List<Candle> candles, int period) {
    if (candles.length < period) return const EmaSeries([]);
    final points = <EmaPoint>[];
    double multiplier = 2 / (period + 1);
    double? ema;
    for (var i = 0; i < candles.length; i++) {
      final close = candles[i].close;
      if (i < period - 1) continue;
      if (ema == null) {
        // SMA for first EMA value
        double sum = 0;
        for (var j = i - period + 1; j <= i; j++) {
          sum += candles[j].close;
        }
        ema = sum / period;
      } else {
        ema = (close - ema) * multiplier + ema;
      }
      points.add(EmaPoint(time: candles[i].time, value: ema));
    }
    return EmaSeries(points);
  }

  // === Actions ===

  Future<void> refreshAll() async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      await Future.wait([
        fetchConfig(),
        fetchStatus(),
        fetchPositions(),
        fetchTrades(),
        fetchBalance(),
        fetchSymbols(),
      ]);
    } catch (e) {
      _error = e.toString();
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  /// Fetch all available symbols from exchange (replaces hardcoded list)
  /// Calls GET /api/symbols — returns 200+ coins for Binance, etc.
  Future<void> fetchSymbols() async {
    try {
      final r = await _api.getSymbols();
      final list = r['symbols'];
      if (list is List) {
        _availableSymbols = list.map((e) => e.toString()).toList();
        _symbolsLoaded = true;
        notifyListeners();
      }
    } catch (e) {
      debugPrint('fetchSymbols error: $e');
      // Fallback to default popular coins
      if (_availableSymbols.isEmpty) {
        _availableSymbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'SUIUSDT'];
        _symbolsLoaded = true;
        notifyListeners();
      }
    }
  }

  Future<void> fetchConfig() async {
    try {
      final r = await _api.getConfig();
      if (r['config'] is Map) {
        _config = BotConfig.fromJson(r['config'] as Map<String, dynamic>);
      } else if (r.isNotEmpty) {
        _config = BotConfig.fromJson(r);
      }
      // Update active symbol from config
      if (_config.symbol.isNotEmpty) _activeSymbol = _config.symbol;
      notifyListeners();
    } catch (e) {
      _error = 'config: $e';
      debugPrint('fetchConfig error: $e');
    }
  }

  Future<void> fetchStatus() async {
    try {
      final r = await _api.getStatus();
      if (r.isNotEmpty && r.containsKey('running')) {
        _status = BotStatus.fromJson(r);
        notifyListeners();
      }
    } catch (e) {
      debugPrint('fetchStatus error: $e');
    }
  }

  Future<void> fetchPositions() async {
    try {
      final r = await _api.getPositions();
      final list = r['positions'];
      if (list is List) {
        _positions = {
          for (var p in list)
            if (p is Map) p['symbol'].toString(): Position.fromJson(p.cast<String, dynamic>()),
        };
        notifyListeners();
      }
    } catch (e) {
      debugPrint('fetchPositions error: $e');
    }
  }

  Future<void> fetchTrades() async {
    try {
      final r = await _api.getTrades();
      final list = r['trades'];
      if (list is List) {
        _trades = list.map((e) => Trade.fromJson(e as Map<String, dynamic>)).toList();
      }
      final stats = r['stats'];
      if (stats is Map<String, dynamic>) {
        _stats = TradeStats.fromJson(stats);
      }
      notifyListeners();
    } catch (e) {
      debugPrint('fetchTrades error: $e');
    }
  }

  Future<void> fetchBalance() async {
    try {
      final r = await _api.getBalance();
      _balance = (r['balance'] ?? 0).toDouble();
      notifyListeners();
    } catch (e) {
      debugPrint('fetchBalance error: $e');
    }
  }

  // === Bot control ===

  Future<void> startBot() async {
    try {
      await _api.startBot();
      await fetchStatus();
    } catch (e) {
      _error = 'start: $e';
      notifyListeners();
    }
  }

  Future<void> stopBot() async {
    try {
      await _api.stopBot();
      await fetchStatus();
    } catch (e) {
      _error = 'stop: $e';
      notifyListeners();
    }
  }

  Future<void> forceReset() async {
    try {
      await _api.forceStop();
      await Future.delayed(const Duration(milliseconds: 500));
      await fetchStatus();
      await fetchPositions();
    } catch (e) {
      _error = 'force_reset: $e';
      notifyListeners();
    }
  }

  Future<void> closePosition(String symbol) async {
    try {
      await _api.closePosition(symbol);
      await fetchPositions();
    } catch (e) {
      _error = 'close: $e';
      notifyListeners();
    }
  }

  Future<void> closeAllPositions() async {
    try {
      await _api.closeAll();
      await fetchPositions();
    } catch (e) {
      _error = 'close_all: $e';
      notifyListeners();
    }
  }

  Future<void> setActiveSymbol(String symbol) async {
    _activeSymbol = symbol;
    notifyListeners();
    try {
      await _api.setActiveSymbol(symbol);
      // Immediately fetch chart for new symbol (don't wait for next poll)
      _fetchChartForSymbol(symbol);
    } catch (e) {
      debugPrint('setActiveSymbol error: $e');
    }
  }

  Future<void> saveConfig(BotConfig newConfig) async {
    try {
      await _api.saveConfig(newConfig.toJson());
      _config = newConfig;
      notifyListeners();
    } catch (e) {
      _error = 'save_config: $e';
      notifyListeners();
      rethrow;
    }
  }

  Future<void> setLeverage(int leverage) async {
    try {
      await _api.setLeverage(leverage, symbol: _activeSymbol);
      await fetchConfig();
    } catch (e) {
      _error = 'leverage: $e';
      notifyListeners();
    }
  }

  Future<Map<String, dynamic>> testConnection() async {
    return await _api.testConnection();
  }

  Future<Map<String, dynamic>> testNotifications() async {
    return await _api.testNotification();
  }

  Future<void> clearTradeHistory() async {
    try {
      await _api.clearTrades();
      await fetchTrades();
    } catch (e) {
      _error = 'clear_trades: $e';
      notifyListeners();
    }
  }

  void clearLogs() {
    _logs.clear();
    notifyListeners();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _chartPollTimer?.cancel();
    for (final s in _subs) {
      s.cancel();
    }
    _socket.dispose();
    _logCtrl.close();
    super.dispose();
  }
}
