import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';

import '../core/api_service.dart';
import '../core/config.dart';
import '../core/theme.dart';

/// WebView-based login screen — opens /auth/google on SaaS
/// After OAuth completes, captures session cookie and returns to auth flow
class WebViewLoginScreen extends StatefulWidget {
  final VoidCallback onLoginComplete;

  const WebViewLoginScreen({super.key, required this.onLoginComplete});

  @override
  State<WebViewLoginScreen> createState() => _WebViewLoginScreenState();
}

class _WebViewLoginScreenState extends State<WebViewLoginScreen> {
  InAppWebViewController? _controller;
  bool _loading = true;
  bool _capturing = false;
  String? _statusMsg;

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  /// Check if URL indicates post-login state (dashboard or bot route)
  bool _isPostLoginUrl(String? url) {
    if (url == null) return false;
    // After successful login, SaaS redirects to / (home) or /bot/ (dashboard)
    // We exclude /auth/google, /auth/login, /auth/signup, /login, /signup
    if (url.contains('/auth/')) return false;
    if (url.contains('/login') || url.contains('/signup')) return false;
    if (url.contains('/legal') || url.contains('/privacy')) return false;
    if (url.contains('/terms')) return false;
    // Match base URL root or /bot/
    final cleanUrl = url.split('?').first.split('#').first;
    final base = AppConfig.baseUrl;
    if (cleanUrl == base || cleanUrl == '$base/') return true;
    if (cleanUrl.startsWith('$base/bot')) return true;
    return false;
  }

  Future<void> _captureCookieAndFinish() async {
    if (_capturing) return;
    _capturing = true;
    setState(() => _statusMsg = 'Signing you in...');

    try {
      final cookieManager = CookieManager.instance();
      final uri = WebUri(AppConfig.baseUrl);
      final cookies = await cookieManager.getCookies(url: uri);

      String? sessionValue;
      for (final c in cookies) {
        if (c.name == 'session' && c.value.isNotEmpty) {
          sessionValue = c.value;
          break;
        }
      }

      if (sessionValue == null) {
        // Fallback: try getCookies with wildcard
        final allCookies = await cookieManager.getAllCookies();
        for (final c in allCookies) {
          if (c.name == 'session' && c.value.isNotEmpty) {
            sessionValue = c.value;
            break;
          }
        }
      }

      if (sessionValue != null) {
        await ApiService().setSessionCookie(sessionValue);
        if (mounted) {
          setState(() => _statusMsg = '✅ Login successful');
          // Small delay so user sees confirmation
          await Future.delayed(const Duration(milliseconds: 600));
          widget.onLoginComplete();
          if (mounted) Navigator.of(context).pop(true);
        }
      } else {
        // No cookie found — login might have failed
        if (mounted) {
          setState(() {
            _statusMsg = null;
            _capturing = false;
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Login did not complete. Please try again.'),
              backgroundColor: WeexionicTheme.red,
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _statusMsg = null;
          _capturing = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error capturing login: $e'),
            backgroundColor: WeexionicTheme.red,
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      appBar: AppBar(
        backgroundColor: WeexionicTheme.bgSurface,
        elevation: 0,
        title: const Text('Sign in with Google', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        leading: IconButton(
          icon: const Icon(Icons.close, color: WeexionicTheme.textSecondary),
          onPressed: () => Navigator.of(context).pop(false),
        ),
      ),
      body: Stack(
        children: [
          InAppWebView(
            initialUrlRequest: URLRequest(
              url: WebUri('${AppConfig.baseUrl}/auth/google'),
              headers: {'Accept': 'text/html,application/xhtml+xml'},
            ),
            initialSettings: InAppWebViewSettings(
              javaScriptEnabled: true,
              domStorageEnabled: true,
              useShouldOverrideUrlLoading: true,
              useOnLoadResource: false,
              allowFileAccess: false,
              mediaPlaybackRequiresUserGesture: false,
              verticalScrollBarEnabled: false,
            ),
            onWebViewCreated: (controller) {
              _controller = controller;
            },
            onLoadStart: (controller, url) {
              setState(() {
                _loading = true;
                _statusMsg = 'Loading...';
              });
            },
            onLoadStop: (controller, url) async {
              setState(() {
                _loading = false;
                _statusMsg = null;
              });
              // Check if we've reached a post-login URL
              if (_isPostLoginUrl(url.toString())) {
                await _captureCookieAndFinish();
              }
            },
            shouldOverrideUrlLoading: (controller, navigationAction) async {
              final uri = navigationAction.request.url;
              if (uri == null) {
                return NavigationActionPolicy.ALLOW;
              }
              final urlStr = uri.toString();
              // If we're being redirected back to the dashboard after OAuth,
              // allow it but be ready to capture cookie
              if (_isPostLoginUrl(urlStr)) {
                // Let it load, onLoadStop will fire and capture cookie
                return NavigationActionPolicy.ALLOW;
              }
              // Block external links (whatsapp, telegram deep links)
              if (urlStr.startsWith('whatsapp:') || urlStr.startsWith('tg:') || urlStr.startsWith('mailto:')) {
                return NavigationActionPolicy.CANCEL;
              }
              return NavigationActionPolicy.ALLOW;
            },
            onReceivedError: (controller, request, error) {
              setState(() {
                _loading = false;
                _statusMsg = null;
              });
            },
          ),

          // Loading overlay
          if (_loading)
            Container(
              color: WeexionicTheme.bgBase.withOpacity(0.9),
              child: Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: const [
                    CircularProgressIndicator(color: WeexionicTheme.brandGold),
                    SizedBox(height: 12),
                    Text(
                      'Connecting to Google...',
                      style: TextStyle(fontSize: 12, color: WeexionicTheme.textMuted),
                    ),
                  ],
                ),
              ),
            ),

          // Status overlay (when capturing cookie)
          if (_capturing && _statusMsg != null)
            Container(
              color: WeexionicTheme.bgBase.withOpacity(0.95),
              child: Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const SizedBox(
                      width: 32, height: 32,
                      child: CircularProgressIndicator(color: WeexionicTheme.brandGold, strokeWidth: 2.5),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      _statusMsg!,
                      style: const TextStyle(fontSize: 13, color: WeexionicTheme.textPrimary, fontWeight: FontWeight.w500),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}
