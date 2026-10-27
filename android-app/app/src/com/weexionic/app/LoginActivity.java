package com.weexionic.app;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * Concept-exact login (v3.4): "Log in. Let the bot do the watching."
 * Server is baked in (Session.DEFAULT_SERVER) — the user never types an address.
 * Google sign-in = one-time browser OAuth round-trip via weexionic://oauth deep link.
 * v3.4: 100% English UI, crash-proof deep-link + JSON handling.
 */
public class LoginActivity extends Activity {

    private Session session;
    private EditText etEmail, etPassword;
    private TextView tvError, btnEye;
    private LinearLayout btnGoogle;
    private CheckBox chkRemember;
    private Button btnLogin;
    private boolean busy = false;
    private boolean busyExchange = false;
    private boolean pwVisible = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            setContentView(R.layout.login);
            session = new Session(this);

            etEmail = findViewById(R.id.etEmail);
            etPassword = findViewById(R.id.etPassword);
            tvError = findViewById(R.id.tvError);
            btnEye = findViewById(R.id.btnEye);
            btnLogin = findViewById(R.id.btnLogin);
            chkRemember = findViewById(R.id.chkRemember);
            btnGoogle = findViewById(R.id.btnGoogle);

            if (session.remember()) {
                String se = session.email();
                if (se.length() > 0) etEmail.setText(se);
                String sp = session.savedPass();
                if (sp.length() > 0) etPassword.setText(sp);
            }

            btnEye.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    pwVisible = !pwVisible;
                    etPassword.setInputType(pwVisible ? 145 : 129);
                    btnEye.setText(pwVisible ? "HIDE" : "SHOW");
                    etPassword.setSelection(etPassword.getText().length());
                }
            });

            btnLogin.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    if (!busy && !busyExchange) doLogin();
                }
            });

            btnGoogle.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    if (!busy && !busyExchange) doGoogle();
                }
            });

            handleDeepLink(getIntent());
        } catch (Throwable t) {
            // Never hard-crash the login screen — surface a clean message instead.
            try {
                CrashLog.save(t);
                Toast.makeText(this, "Startup error — please reopen the app", Toast.LENGTH_LONG).show();
            } catch (Exception ignore) { }
            finish();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleDeepLink(intent);
    }

    private void showErr(String msg) {
        tvError.setTextColor(0xFFF6465D);
        tvError.setText(msg);
        tvError.setVisibility(View.VISIBLE);
    }

    private void showInfo(String msg) {
        tvError.setTextColor(0xFF0ECB81);
        tvError.setText(msg);
        tvError.setVisibility(View.VISIBLE);
    }

    // ---------- Google OAuth (browser round-trip) ----------

    private void doGoogle() {
        final String srv = session.hasServer() ? session.server() : Session.DEFAULT_SERVER;
        showInfo("Opening Google — pick your account and the app returns automatically");
        try {
            Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(srv + "/auth/google?app=1"));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
        } catch (Throwable t) {
            showErr("Couldn't open the browser — please try again");
        }
    }

    private void handleDeepLink(Intent i) {
        try {
            if (i == null || i.getData() == null) return;
            Uri d = i.getData();
            if (d == null || !"weexionic".equals(d.getScheme()) || !"oauth".equals(d.getHost())) return;
            String token = d.getQueryParameter("token");
            if (token != null && token.length() > 0 && !busyExchange) doExchange(token);
        } catch (Throwable t) {
            // Bad deep link must never crash the app.
            try { CrashLog.save(t); } catch (Exception ignore) { }
            showErr("Sign-in link was invalid — please try again");
        }
    }

    private void doExchange(final String token) {
        final String srv = session.hasServer() ? session.server() : Session.DEFAULT_SERVER;
        busyExchange = true;
        busy = true;
        btnLogin.setEnabled(false);
        btnLogin.setText("Signing In…");
        showInfo("Verifying your Google account…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                String b = "{}";
                try {
                    JSONObject jo = new JSONObject();
                    jo.put("token", token);
                    b = jo.toString();
                } catch (Exception ignore) { }
                final ApiClient.Result r = ApiClient.post(srv + "/api/auth/exchange", b, null);
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        busyExchange = false;
                        busy = false;
                        btnLogin.setEnabled(true);
                        btnLogin.setText("Log In to Terminal");
                        finishLogin(r, srv, null); // google login: password is never saved
                    }
                });
            }
        }).start();
    }

    // ---------- Email + password login ----------

    private void doLogin() {
        InputMethodManager im = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (im != null && getCurrentFocus() != null) {
            im.hideSoftInputFromWindow(getCurrentFocus().getWindowToken(), 0);
        }

        final String server = session.hasServer() ? session.server() : Session.DEFAULT_SERVER;
        final String email = etEmail.getText().toString().trim();
        final String pass = etPassword.getText().toString();

        if (TextUtils.isEmpty(email) || !email.contains("@")) {
            showErr("Please enter a valid email address");
            return;
        }
        if (pass.length() == 0) {
            showErr("Please enter your password");
            return;
        }

        tvError.setVisibility(View.GONE);
        busy = true;
        btnLogin.setEnabled(false);
        btnLogin.setAlpha(0.55f);
        btnLogin.setText("Logging In…");

        String b;
        try {
            JSONObject jo = new JSONObject();
            jo.put("email", email);
            jo.put("password", pass);
            b = jo.toString();
        } catch (Exception e) {
            b = "{}";
        }
        final String body = b;

        new Thread(new Runnable() {
            @Override
            public void run() {
                final ApiClient.Result r = ApiClient.post(server + "/api/auth/login", body, null);
                boolean verified = false;
                String cookie = r.setCookie == null ? "" : r.setCookie;
                if (r.ok() && cookie.startsWith("session=")) {
                    ApiClient.Result me = ApiClient.get(server + "/api/auth/me", cookie);
                    try {
                        verified = me.ok() && new JSONObject(me.body).optBoolean("success", false);
                    } catch (Exception ignored) { }
                }
                final boolean ok = verified;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        btnLogin.setEnabled(true);
                        btnLogin.setAlpha(1f);
                        btnLogin.setText("Log In to Terminal");
                        if (!ok) {
                            String msg;
                            try {
                                JSONObject jo = new JSONObject(r.body);
                                msg = jo.optString("error", null);
                            } catch (Exception e) { msg = null; }
                            if (msg == null || msg.isEmpty()) {
                                msg = r.error != null ? r.error
                                        : "Login failed — check your connection and try again";
                            }
                            showErr(msg);
                            return;
                        }
                        finishLogin(r, server, pass);
                    }
                });
            }
        }).start();
    }

    /** Shared login/exchange finisher: save session + optional password, go to Main. */
    private void finishLogin(ApiClient.Result r, String server, String passForSave) {
        try {
            if (r == null || !r.ok() || r.setCookie == null || !r.setCookie.startsWith("session=")) {
                String msg;
                try {
                    JSONObject jo = new JSONObject(r == null ? "" : r.body);
                    msg = jo.optString("error", null);
                } catch (Exception e) { msg = null; }
                if (msg == null || msg.isEmpty()) {
                    msg = (r != null && r.error != null) ? r.error
                            : "Login failed — please try again";
                }
                showErr(msg);
                return;
            }
            JSONObject jo = new JSONObject(r.body);
            if (!jo.optBoolean("success", false)) {
                showErr(jo.optString("error", "Login failed — please try again"));
                return;
            }
            session.server(server);
            session.cookie(r.setCookie);
            JSONObject user = jo.optJSONObject("user");
            if (user != null) {
                session.email(user.optString("email", ""));
                session.name(user.optString("name", "Trader"));
            }
            JSONObject sub = jo.optJSONObject("subscription");
            if (sub != null) {
                session.plan(sub.optString("plan", "—"));
                session.expiry(sub.optString("expires_at", ""));
            }
            // Remember me: password is stored only for email/password logins.
            if (passForSave != null && passForSave.length() > 0) {
                session.remember(true);
                session.savedPass(passForSave);
                session.email(user == null ? "" : user.optString("email", session.email()));
            } else if (!chkRemember.isChecked()) {
                session.remember(false);
                session.savedPass("");
            } else {
                session.remember(true);
            }
            Toast.makeText(LoginActivity.this, "Welcome, " + session.name() + "!", Toast.LENGTH_SHORT).show();
            startActivity(new Intent(LoginActivity.this, MainActivity.class));
            finish();
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
            showErr("Unexpected server response — please try again");
        }
    }
}
