import 'dart:async';
import 'package:socket_io_client/socket_io_client.dart' as IO;
import '../core/config.dart';
import '../core/api_service.dart';
import '../models/bot_log.dart';

/// Real-time Socket.IO client — connects to bot-engine
/// CRITICAL: must use polling transport + pass session cookie (SaaS proxy requires auth)
class SocketService {
  IO.Socket? _socket;
  bool _connected = false;

  // Stream controllers for each event type
  final _logCtrl = StreamController<BotLog>.broadcast();
  final _statusCtrl = StreamController<Map<String, dynamic>>.broadcast();
  final _indicatorsCtrl = StreamController<Map<String, dynamic>>.broadcast();
  final _chartDataCtrl = StreamController<Map<String, dynamic>>.broadcast();
  final _signalCtrl = StreamController<Map<String, dynamic>>.broadcast();
  final _positionCtrl = StreamController<Map<String, dynamic>>.broadcast();
  final _balanceCtrl = StreamController<Map<String, dynamic>>.broadcast();
  final _tradesCtrl = StreamController<Map<String, dynamic>>.broadcast();
  final _connectionCtrl = StreamController<bool>.broadcast();

  // Exposed streams
  Stream<BotLog> get logs => _logCtrl.stream;
  Stream<Map<String, dynamic>> get status => _statusCtrl.stream;
  Stream<Map<String, dynamic>> get indicators => _indicatorsCtrl.stream;
  Stream<Map<String, dynamic>> get chartData => _chartDataCtrl.stream;
  Stream<Map<String, dynamic>> get signal => _signalCtrl.stream;
  Stream<Map<String, dynamic>> get position => _positionCtrl.stream;
  Stream<Map<String, dynamic>> get balance => _balanceCtrl.stream;
  Stream<Map<String, dynamic>> get trades => _tradesCtrl.stream;
  Stream<bool> get connection => _connectionCtrl.stream;

  bool get isConnected => _connected;
  IO.Socket? get socket => _socket;

  /// Connect to bot-engine Socket.IO server with session cookie
  Future<void> connect() async {
    if (_socket != null) return;

    // Fetch session cookie from PersistCookieJar (set during login)
    final cookieValue = await ApiService().getSessionCookieValue();
    final Map<String, dynamic> extraHeaders = {
      'Accept': 'text/html,application/xhtml+xml',
      if (cookieValue != null) 'Cookie': 'session=$cookieValue',
    };

    _socket = IO.io(
      AppConfig.socketUrl,
      IO.OptionBuilder()
        .setTransports(['polling'])     // ← CRITICAL: polling only (matches web client)
        .disableAutoConnect()
        .enableReconnection()
        .setReconnectionAttempts(1000000)
        .setReconnectionDelay(1000)
        .setReconnectionDelayMax(5000)
        .setTimeout(25000)
        .setExtraHeaders(extraHeaders)
        .build(),
    );

    _socket!.onConnect((_) {
      _connected = true;
      _connectionCtrl.add(true);
      print('✅ Socket connected to bot stream');
    });

    _socket!.onDisconnect((_) {
      _connected = false;
      _connectionCtrl.add(false);
      print('🔌 Socket disconnected');
    });

    _socket!.onConnectError((e) {
      print('⚠️ Socket connect error: $e');
    });

    _socket!.onReconnect((_) => print('🔄 Socket reconnected'));
    _socket!.onReconnectError((e) => print('⚠️ Reconnect error: $e'));

    // Data event subscriptions
    _socket!.on(SocketEvents.log, (data) {
      if (data is Map<String, dynamic>) {
        _logCtrl.add(BotLog.fromSocket(data));
      }
    });

    _socket!.on(SocketEvents.status, (data) {
      if (data is Map<String, dynamic>) _statusCtrl.add(data);
    });

    _socket!.on(SocketEvents.indicators, (data) {
      if (data is Map<String, dynamic>) _indicatorsCtrl.add(data);
    });

    _socket!.on(SocketEvents.chartData, (data) {
      if (data is Map<String, dynamic>) _chartDataCtrl.add(data);
    });

    _socket!.on(SocketEvents.signal, (data) {
      if (data is Map<String, dynamic>) _signalCtrl.add(data);
    });

    _socket!.on(SocketEvents.position, (data) {
      if (data is Map<String, dynamic>) _positionCtrl.add(data);
    });

    _socket!.on(SocketEvents.balance, (data) {
      if (data is Map<String, dynamic>) _balanceCtrl.add(data);
    });

    _socket!.on(SocketEvents.tradesUpdated, (data) {
      if (data is Map<String, dynamic>) _tradesCtrl.add(data);
    });

    _socket!.connect();
  }

  void disconnect() {
    _socket?.disconnect();
    _socket?.dispose();
    _socket = null;
    _connected = false;
  }

  void dispose() {
    disconnect();
    _logCtrl.close();
    _statusCtrl.close();
    _indicatorsCtrl.close();
    _chartDataCtrl.close();
    _signalCtrl.close();
    _positionCtrl.close();
    _balanceCtrl.close();
    _tradesCtrl.close();
    _connectionCtrl.close();
  }
}
