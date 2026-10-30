import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:cookie_jar/cookie_jar.dart';
import 'package:path_provider/path_provider.dart';
import '../core/config.dart';

/// REST API client — uses dio with persistent cookie jar
/// Auth: Flask session cookie (set by /api/auth/login, persisted across app launches)
/// All bot-engine endpoints under /bot/api/* require this cookie (SaaS proxy enforces)
class ApiService {
  static final ApiService _i = ApiService._();
  factory ApiService() => _i;
  ApiService._();

  late final Dio _dio;
  late final PersistCookieJar _cookieJar;
  bool _initialized = false;

  Future<void> init() async {
    if (_initialized) return;
    final appDir = await getApplicationDocumentsDirectory();
    final cookiePath = '${appDir.path}/.cookies/';
    _cookieJar = PersistCookieJar(
      storage: FileStorage(cookiePath),
      ignoreExpires: false,
    );

    _dio = Dio(BaseOptions(
      baseUrl: AppConfig.baseUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 30),
      followRedirects: false, // SaaS returns 302 on auth fail — we want to catch it
      validateStatus: (status) => status != null && status < 400, // accept 2xx + 3xx
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    ));

    _dio.interceptors.add(CookieManager(_cookieJar));
    _initialized = true;
  }

  /// Returns true if we have a session cookie (doesn't guarantee it's valid)
  Future<bool> hasSessionCookie() async {
    await init();
    final uri = Uri.parse(AppConfig.baseUrl);
    final cookies = await _cookieJar.loadForRequest(uri);
    return cookies.any((c) => c.name == 'session');
  }

  Future<void> clearCookies() async {
    await init();
    await _cookieJar.deleteAll();
  }

  /// Manually inject a session cookie captured from WebView login flow
  /// Used after Google OAuth completes in InAppWebView
  Future<void> setSessionCookie(String cookieValue) async {
    await init();
    final uri = Uri.parse(AppConfig.baseUrl);
    final cookie = Cookie('session', cookieValue);
    cookie.domain = uri.host;
    cookie.path = '/';
    cookie.httpOnly = true;
    await _cookieJar.saveFromResponse(uri, [cookie]);
  }

  // ============ SaaS Auth API ============

  /// POST /api/auth/login — sets Flask session cookie via Set-Cookie header
  Future<Map<String, dynamic>> login(String email, String password) async {
    await init();
    final r = await _dio.post(
      '${AppConfig.saasApiBase}${AppConfig.epAuthLogin}',
      data: jsonEncode({'email': email, 'password': password}),
    );
    return _parseJson(r);
  }

  Future<Map<String, dynamic>> signup({
    required String name,
    required String email,
    required String password,
    String? referralCode,
  }) async {
    await init();
    final r = await _dio.post(
      '${AppConfig.saasApiBase}${AppConfig.epAuthSignup}',
      data: jsonEncode({
        'name': name,
        'email': email,
        'password': password,
        if (referralCode != null && referralCode.isNotEmpty) 'referral_code': referralCode,
      }),
    );
    return _parseJson(r);
  }

  Future<Map<String, dynamic>> logout() async {
    await init();
    final r = await _dio.post('${AppConfig.saasApiBase}${AppConfig.epAuthLogout}');
    await _cookieJar.deleteAll();
    return _parseJson(r);
  }

  /// GET /api/auth/me — verify session, get user + subscription + license info
  Future<Map<String, dynamic>> me() async {
    await init();
    final r = await _dio.get('${AppConfig.saasApiBase}${AppConfig.epAuthMe}');
    return _parseJson(r);
  }

  /// POST /api/license/activate — activate TRDBOT-XXXX-XXXX-XXXX-XXXX
  Future<Map<String, dynamic>> activateLicense(String key) async {
    await init();
    final r = await _dio.post(
      '${AppConfig.saasApiBase}${AppConfig.epLicenseActivate}',
      data: jsonEncode({'key': key.toUpperCase()}),
    );
    return _parseJson(r);
  }

  // ============ Bot Engine API (under /bot/api/*) ============

  Future<Map<String, dynamic>> _botGet(String endpoint, {Map<String, String?>? q}) async {
    await init();
    final uri = '${AppConfig.botApiBase}$endpoint';
    final r = await _dio.get(uri, queryParameters: q?.map((k, v) => MapEntry(k, v?.toString())));
    return _parseJson(r);
  }

  Future<Map<String, dynamic>> _botPost(String endpoint, {Map<String, dynamic>? body}) async {
    await init();
    final r = await _dio.post(
      '${AppConfig.botApiBase}$endpoint',
      data: body == null ? '{}' : jsonEncode(body),
    );
    return _parseJson(r);
  }

  // Config & settings
  Future<Map<String, dynamic>> getConfig() => _botGet(AppConfig.epConfig);
  Future<Map<String, dynamic>> saveConfig(Map<String, dynamic> cfg) =>
      _botPost(AppConfig.epConfig, body: cfg);
  Future<Map<String, dynamic>> setLeverage(int leverage, {String? symbol}) =>
      _botPost(AppConfig.epLeverage, body: {'leverage': leverage, if (symbol != null) 'symbol': symbol});
  Future<Map<String, dynamic>> testNotification() => _botPost(AppConfig.epTestNotification);

  // Bot lifecycle
  Future<Map<String, dynamic>> startBot() => _botPost(AppConfig.epStart);
  Future<Map<String, dynamic>> stopBot() => _botPost(AppConfig.epStop);
  Future<Map<String, dynamic>> forceStop() => _botPost(AppConfig.epForceStop);
  Future<Map<String, dynamic>> setActiveSymbol(String symbol) =>
      _botPost(AppConfig.epActiveSymbol, body: {'symbol': symbol});
  Future<Map<String, dynamic>> getStatus() => _botGet(AppConfig.epStatus);

  // Positions & trading
  Future<Map<String, dynamic>> getPositions({String? symbol}) =>
      _botGet(AppConfig.epPositions, q: {if (symbol != null) 'symbol': symbol});
  Future<Map<String, dynamic>> closePosition(String symbol) =>
      _botPost(AppConfig.epClose, body: {'symbol': symbol});
  Future<Map<String, dynamic>> closeAll() => _botPost(AppConfig.epCloseAll);

  // Market data
  Future<Map<String, dynamic>> getPrice(String symbol) =>
      _botGet(AppConfig.epPrice, q: {'symbol': symbol});
  Future<Map<String, dynamic>> getSymbols() => _botGet(AppConfig.epSymbols);
  Future<Map<String, dynamic>> getTestChart(String symbol) =>
      _botGet(AppConfig.epTestChart, q: {'symbol': symbol});

  // History & balance
  Future<Map<String, dynamic>> getTrades({int limit = 100, String? symbol}) =>
      _botGet(AppConfig.epTrades, q: {
        'limit': limit.toString(),
        if (symbol != null) 'symbol': symbol,
      });
  Future<Map<String, dynamic>> clearTrades() => _botPost(AppConfig.epTradesClear);
  Future<Map<String, dynamic>> getBalance() => _botGet(AppConfig.epBalance);
  Future<Map<String, dynamic>> testConnection() => _botPost(AppConfig.epTestConnection);
  Future<Map<String, dynamic>> startMonitor() => _botPost(AppConfig.epPreview);

  // ============ Helpers ============

  /// Parse JSON response — handles Dio's auto-decoded Map + detects HTML/redirect
  Map<String, dynamic> _parseJson(Response r) {
    // Dio auto-parses JSON when content-type is application/json — r.data is already a Map
    if (r.data is Map) {
      return Map<String, dynamic>.from(r.data as Map);
    }
    if (r.data is List) {
      return {'success': true, 'data': r.data};
    }

    final body = r.data?.toString() ?? '';
    final contentType = r.headers.value('content-type') ?? '';

    // SaaS returns HTML redirect page when not authenticated
    if (contentType.contains('text/html') ||
        body.startsWith('<!doctype') ||
        body.startsWith('<html') ||
        body.startsWith('<!DOCTYPE')) {
      throw AuthRequiredException('Authentication required — server returned HTML');
    }

    // Check for redirect (302) — indicates auth failure
    if (r.statusCode == 302 || r.statusCode == 301) {
      final loc = r.headers.value('location') ?? '/';
      if (loc == '/' || loc.contains('login')) {
        throw AuthRequiredException('Session expired — redirect to login');
      }
    }

    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) return decoded;
      if (decoded is Map) return Map<String, dynamic>.from(decoded);
      if (decoded is List) return {'success': true, 'data': decoded};
      throw ApiException('Unexpected response shape: ${decoded.runtimeType}');
    } catch (e) {
      if (e is AuthRequiredException || e is ApiException) rethrow;
      throw ApiException(
        'JSON parse failed. Body: ${body.length > 200 ? body.substring(0, 200) : body}',
      );
    }
  }
}

/// Thrown when server returns HTML or redirect — means session expired or not logged in
class AuthRequiredException implements Exception {
  final String message;
  AuthRequiredException(this.message);
  @override
  String toString() => 'AuthRequiredException: $message';
}

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => 'ApiException: $message';
}
