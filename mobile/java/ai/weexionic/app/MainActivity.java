package ai.weexionic.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.http.SslError;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

/**
 * WEEXIONIC mobile client.
 * Native launcher (server URL entry) + fullscreen WebView that renders the
 * WEEXIONIC dashboard served by the user's own bot-engine / SaaS server.
 */
public class MainActivity extends Activity {

    private SharedPreferences prefs;
    private WebView web;
    private View launcher;
    private EditText urlBox;
    private CheckBox trustSsl;
    private TextView status;

    private boolean trustSslEnabled = true;
    private boolean mainFrameError = false;
    private boolean connected = false;
    private String serverUrl = "";

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences("weexionic", MODE_PRIVATE);
        web = findViewById(R.id.web);
        launcher = findViewById(R.id.launcher);
        urlBox = findViewById(R.id.url);
        trustSsl = findViewById(R.id.trust_ssl);
        status = findViewById(R.id.status);

        String saved = prefs.getString("server_url", "");
        if (!saved.isEmpty()) urlBox.setText(saved);
        trustSsl.setEnabled(true);
        trustSsl.setChecked(prefs.getBoolean("trust_ssl", true));

        findViewById(R.id.connect).setOnClickListener(v -> connect());
        urlBox.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_GO) {
                connect();
                return true;
            }
            return false;
        });

        setupWebView();

        if (!saved.isEmpty()) {
            connect(); // auto-reconnect to last server
        }
    }

    private void setupWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        // Strip the "; wv" marker so Google sign-in treats the WebView like Chrome
        String ua = s.getUserAgentString();
        if (ua != null && ua.contains("; wv)")) {
            s.setUserAgentString(ua.replace("; wv)", ")"));
        }

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, true);
        cm.flush();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                // keep everything inside the app (http/https only)
                String scheme = url.startsWith("https:") ? "https" : (url.startsWith("http:") ? "http" : "");
                return scheme.isEmpty(); // open foreign schemes externally via default handling
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (mainFrameError) {
                    showLauncher("Could not reach the server. Check the URL / your internet and try again.");
                } else {
                    connected = true;
                    showWeb();
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request != null && request.isForMainFrame()) {
                    mainFrameError = true;
                }
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                if (trustSslEnabled) {
                    handler.proceed(); // user opted to trust own VPS certificate
                } else {
                    handler.cancel();
                    mainFrameError = true;
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (!connected && newProgress < 100) {
                    status.setText("Connecting… " + newProgress + "%");
                }
            }
        });
    }

    private void connect() {
        String raw = urlBox.getText().toString().trim();
        if (raw.isEmpty()) {
            status.setText("Please enter your bot server URL first.");
            return;
        }
        if (!raw.startsWith("http://") && !raw.startsWith("https://")) {
            raw = "http://" + raw;
        }
        while (raw.endsWith("/")) {
            raw = raw.substring(0, raw.length() - 1);
        }
        serverUrl = raw;
        trustSslEnabled = trustSsl.isChecked();

        prefs.edit().putString("server_url", serverUrl)
                .putBoolean("trust_ssl", trustSslEnabled).apply();

        mainFrameError = false;
        connected = false;
        status.setText("Connecting…");
        web.loadUrl(serverUrl);
    }

    private void showWeb() {
        web.setVisibility(View.VISIBLE);
        launcher.setVisibility(View.GONE);
    }

    private void showLauncher(String message) {
        web.setVisibility(View.GONE);
        web.stopLoading();
        launcher.setVisibility(View.VISIBLE);
        status.setText(message);
        Toast.makeText(this, "Connection failed", Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onBackPressed() {
        if (web.getVisibility() == View.VISIBLE && web.canGoBack()) {
            web.goBack();
        } else {
            moveTaskToBack(true); // keep session alive instead of killing the app
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }
}
