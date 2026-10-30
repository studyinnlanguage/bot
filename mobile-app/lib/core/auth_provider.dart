import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'api_service.dart';
import '../models/user.dart';

/// Auth state machine
enum AuthState {
  initializing,      // app starting up, checking session
  unauthenticated,   // no session / login failed
  authenticatedNoLicense,  // logged in but subscription inactive
  authenticated,     // logged in + active license → can use bot
}

/// Central auth state — Provider pattern
/// Handles: login, signup, license activation, logout, session persistence
class AuthProvider extends ChangeNotifier {
  final ApiService _api = ApiService();
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();

  AuthState _state = AuthState.initializing;
  User? _user;
  String? _error;
  bool _loading = false;

  AuthState get state => _state;
  User? get user => _user;
  String? get error => _error;
  bool get loading => _loading;
  bool get isAuthenticated => _state == AuthState.authenticated;
  bool get needsLicense => _state == AuthState.authenticatedNoLicense;

  AuthProvider() {
    _init();
  }

  Future<void> _init() async {
    try {
      await _api.init();
      final hasCookie = await _api.hasSessionCookie();
      if (hasCookie) {
        await _fetchMe();
      } else {
        _state = AuthState.unauthenticated;
      }
    } catch (e) {
      debugPrint('AuthProvider init error: $e');
      _state = AuthState.unauthenticated;
    } finally {
      notifyListeners();
    }
  }

  /// GET /api/auth/me — fetch current user profile + check subscription
  Future<void> _fetchMe() async {
    try {
      final r = await _api.me();
      if (r['success'] == true && r['user'] != null) {
        _user = User.fromJson(r as Map<String, dynamic>);
        if (_user!.subscription.isActive) {
          _state = AuthState.authenticated;
        } else {
          _state = AuthState.authenticatedNoLicense;
        }
      } else {
        // Session invalid → clear and go to login
        await _api.clearCookies();
        _user = null;
        _state = AuthState.unauthenticated;
        _error = r['error']?.toString();
      }
    } catch (e) {
      debugPrint('me() error: $e');
      // AuthRequiredException → session expired
      if (e is AuthRequiredException) {
        await _api.clearCookies();
        _user = null;
        _state = AuthState.unauthenticated;
      }
      // Other errors (network) → keep state, show error
      _error = e.toString();
    }
    notifyListeners();
  }

  // ============ Auth Actions ============

  Future<bool> login({required String email, required String password}) async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      final r = await _api.login(email.trim(), password);
      if (r['success'] == true) {
        await _fetchMe();
        return true;
      } else {
        _error = r['error']?.toString() ?? 'Login failed';
        _state = AuthState.unauthenticated;
        return false;
      }
    } catch (e) {
      _error = _friendlyError(e);
      _state = AuthState.unauthenticated;
      return false;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<bool> signup({
    required String name,
    required String email,
    required String password,
    String? referralCode,
  }) async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      final r = await _api.signup(
        name: name.trim(),
        email: email.trim(),
        password: password,
        referralCode: referralCode?.trim(),
      );
      if (r['success'] == true) {
        await _fetchMe();
        return true;
      } else {
        _error = r['error']?.toString() ?? 'Signup failed';
        return false;
      }
    } catch (e) {
      _error = _friendlyError(e);
      return false;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<bool> activateLicense(String key) async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      final r = await _api.activateLicense(key.trim());
      if (r['success'] == true) {
        await _fetchMe();
        return true;
      } else {
        _error = r['error']?.toString() ?? 'License activation failed';
        return false;
      }
    } catch (e) {
      _error = _friendlyError(e);
      return false;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    _loading = true;
    notifyListeners();
    try {
      await _api.logout();
    } catch (_) {}
    _user = null;
    _state = AuthState.unauthenticated;
    _loading = false;
    notifyListeners();
  }

  /// Refresh user data (e.g., after bot_config changes via /bot/api/config)
  Future<void> refresh() async {
    await _fetchMe();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }

  String _friendlyError(dynamic e) {
    final s = e.toString();
    if (s.contains('AuthRequiredException')) return 'Session expired. Please login again.';
    if (s.contains('SocketException') || s.contains('HandshakeException')) return 'Network error. Check your internet.';
    if (s.contains('Connection refused') || s.contains('Connection timed out')) return 'Cannot reach server. Try again later.';
    return s.replaceAll('Exception: ', '').replaceAll('DioException', 'Network error');
  }
}
