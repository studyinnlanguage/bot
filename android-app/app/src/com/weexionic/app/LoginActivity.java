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
 * Native Binance-style login: email + password (Remember me = silent auto-relogin)
 * + Google sign-in (browser OAuth round-trip via weexionic://oauth deep link).
 */
public class LoginActivity extends Activity {

    private Session session;
    private EditText etEmail, etPassword, etServer;
    private TextView tvError, btnEye, btnServerToggle;
    private LinearLayout llServer, btnGoogle;
    private CheckBox chkRemember;
    private Button btnLogin;
    private boolean busy = false;
    private boolean busyExchange = false;
    private boolean pwVisible = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.login);
        session = new Session(this);

        etEmail = findViewById(R.id.etEmail);
        etPassword = findViewById(R.id.etPassword);
        etServer = findViewById(R.id.etServer);
        tvError = findViewById(R.id.tvError);
        btnEye = findViewById(R.id.btnEye);
        btnServerToggle = findViewById(R.id.btnServerToggle);
        llServer = findViewById(R.id.llServer);
        btnLogin = findViewById(R.id.btnLogin);
        chkRemember = findViewById(R.id.chkRemember);
        btnGoogle = findViewById(R.id.btnGoogle);

        etServer.setText(session.server());
        if (!session.hasServer()) {
            llServer.setVisibility(View.VISIBLE);
            btnServerToggle.setText("SERVER SETTINGS  ▴");
        }
        chkRemember.setChecked(session.remember());
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

        btnServerToggle.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                boolean vis = llServer.getVisibility() == View.VISIBLE;
                llServer.setVisibility(vis ? View.GONE : View.VISIBLE);
                btnServerToggle.setText(vis ? "SERVER SETTINGS  ▾" : "SERVER SETTINGS  ▴");
            }
        });

        btnLogin.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (!busy) doLogin();
            }
        });

        btnGoogle.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (!busy && !busyExchange) doGoogle();
            }
        });

        handleDeepLink(getIntent());
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
        String srv = Session.normalizeServer(etServer.getText().toString());
        if (srv.length() == 0) {
            llServer.setVisibility(View.VISIBLE);
            btnServerToggle.setText("SERVER SETTINGS  ▴");
            showErr("Google login ke liye pehle SERVER SETTINGS mein server address darj karein");
            return;
        }
        session.server(srv);
        showInfo("Google page khul raha hai — account choose karo, app khud wapas aa jayegi");
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(srv + "/auth/google?app=1")));
        } catch (Exception e) {
            showErr("Browser nahi khul saka — dobara koshish karein");
        }
    }

    private void handleDeepLink(Intent i) {
        if (i == null || i.getData() == null) return;
        Uri d = i.getData();
        if (!"weexionic".equals(d.getScheme()) || !"oauth".equals(d.getHost())) return;
        String token = d.getQueryParameter("token");
        if (token != null && token.length() > 0 && !busyExchange) doExchange(token);
    }

    private void doExchange(final String token) {
        final String srv = session.hasServer()
                ? session.server() : Session.normalizeServer(etServer.getText().toString());
        if (srv.length() == 0) {
            showErr("Server address nahi mila — SERVER SETTINGS set karein");
            return;
        }
        session.server(srv);
        busyExchange = true;
        busy = true;
        btnLogin.setEnabled(false);
        btnLogin.setText("Google Login…");
        showInfo("Google account verify ho raha hai…");
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
                        btnLogin.setText("Log In");
                        finishLogin(r, srv, null); // google login: password save nahi hota
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

        final String server = Session.normalizeServer(etServer.getText().toString());
        final String email = etEmail.getText().toString().trim();
        final String pass = etPassword.getText().toString();

        if (server.length() == 0) {
            showErr("Server address darj karein (SERVER SETTINGS kholein)");
            return;
        }
        if (TextUtils.isEmpty(email) || !email.contains("@")) {
            showErr("Sahi email darj karein");
            return;
        }
        if (pass.length() == 0) {
            showErr("Password darj karein");
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
                        btnLogin.setText("Log In");
                        if (!ok) {
                            String msg;
                            try {
                                JSONObject jo = new JSONObject(r.body);
                                msg = jo.optString("error", null);
                            } catch (Exception e) { msg = null; }
                            if (msg == null || msg.isEmpty()) {
                                msg = r.error != null ? r.error : "Login nahi ho saka — server/address check karein";
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
        if (!r.ok() || r.setCookie == null || !r.setCookie.startsWith("session=")) {
            String msg;
            try {
                JSONObject jo = new JSONObject(r.body);
                msg = jo.optString("error", null);
            } catch (Exception e) { msg = null; }
            if (msg == null || msg.isEmpty()) {
                msg = r.error != null ? r.error : "Login nahi ho saka — dobara koshish karein";
            }
            showErr(msg);
            return;
        }
        try {
            JSONObject jo = new JSONObject(r.body);
            if (!jo.optBoolean("success", false)) {
                showErr(jo.optString("error", "Login fail — dobara koshish karein"));
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
            // Remember me: sirf email/password login par password save hota hai
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
        } catch (Exception e) {
            showErr("Server response samajh nahi aaya");
        }
    }
}
