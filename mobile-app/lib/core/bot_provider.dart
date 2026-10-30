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
        // On connect, fetch initial state
        refreshAll();
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

    // Connect socket immediately
    _socket.connect();

    // Initial fetch
    refreshAll();
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
      ]);
    } catch (e) {
      _error = e.toString();
    } finally {
      _loading = false;
      notifyListeners();
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
    for (final s in _subs) {
      s.cancel();
    }
    _socket.dispose();
    _logCtrl.close();
    super.dispose();
  }
}
