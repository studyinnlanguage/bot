import 'dart:convert';
import 'package:http/http.dart' as http;
import '../core/config.dart';

/// REST API client for bot-engine
/// All endpoints match bot-engine/app.py exactly
/// Sends 'X-Bot-Token' header if AppConfig.botToken is non-empty
class ApiService {
  static final ApiService _i = ApiService._();
  factory ApiService() => _i;
  ApiService._();

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (AppConfig.botToken.isNotEmpty) 'X-Bot-Token': AppConfig.botToken,
  };

  String _url(String endpoint) => '${AppConfig.apiBase}$endpoint';

  Future<Map<String, dynamic>> _get(String endpoint, {Map<String, String?>? q}) async {
    final uri = Uri.parse(_url(endpoint)).replace(queryParameters: q?.map((k, v) => MapEntry(k, v?.toString())));
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode == 403) {
      throw Exception('Unauthorized — X-Bot-Token rejected (403)');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> _post(String endpoint, {Map<String, dynamic>? body}) async {
    final r = await http.post(
      Uri.parse(_url(endpoint)),
      headers: _headers,
      body: body == null ? '{}' : jsonEncode(body),
    );
    if (r.statusCode == 403) {
      throw Exception('Unauthorized — X-Bot-Token rejected (403)');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  // ============ Config & Settings ============
  Future<Map<String, dynamic>> getConfig() => _get(AppConfig.epConfig);

  Future<Map<String, dynamic>> saveConfig(Map<String, dynamic> cfg) =>
      _post(AppConfig.epConfig, body: cfg);

  Future<Map<String, dynamic>> setLeverage(int leverage, {String? symbol}) =>
      _post(AppConfig.epLeverage, body: {'leverage': leverage, if (symbol != null) 'symbol': symbol});

  Future<Map<String, dynamic>> testNotification() => _post(AppConfig.epTestNotification);

  // ============ Bot Lifecycle ============
  Future<Map<String, dynamic>> startBot() => _post(AppConfig.epStart);
  Future<Map<String, dynamic>> stopBot() => _post(AppConfig.epStop);
  Future<Map<String, dynamic>> forceStop() => _post(AppConfig.epForceStop);
  Future<Map<String, dynamic>> setActiveSymbol(String symbol) =>
      _post(AppConfig.epActiveSymbol, body: {'symbol': symbol});
  Future<Map<String, dynamic>> getStatus() => _get(AppConfig.epStatus);

  // ============ Positions & Trading ============
  Future<Map<String, dynamic>> getPositions({String? symbol}) =>
      _get(AppConfig.epPositions, q: {if (symbol != null) 'symbol': symbol});
  Future<Map<String, dynamic>> closePosition(String symbol) =>
      _post(AppConfig.epClose, body: {'symbol': symbol});
  Future<Map<String, dynamic>> closeAll() => _post(AppConfig.epCloseAll);

  // ============ Market Data ============
  Future<Map<String, dynamic>> getPrice(String symbol) =>
      _get(AppConfig.epPrice, q: {'symbol': symbol});
  Future<Map<String, dynamic>> getSymbols() => _get(AppConfig.epSymbols);
  Future<Map<String, dynamic>> getTestChart(String symbol) =>
      _get(AppConfig.epTestChart, q: {'symbol': symbol});

  // ============ History & Balance ============
  Future<Map<String, dynamic>> getTrades({int limit = 100, String? symbol}) =>
      _get(AppConfig.epTrades, q: {
        'limit': limit.toString(),
        if (symbol != null) 'symbol': symbol,
      });
  Future<Map<String, dynamic>> clearTrades() => _post(AppConfig.epTradesClear);
  Future<Map<String, dynamic>> getBalance() => _get(AppConfig.epBalance);
  Future<Map<String, dynamic>> testConnection() => _post(AppConfig.epTestConnection);
  Future<Map<String, dynamic>> startMonitor() => _post(AppConfig.epPreview);
}
