package com.weexionic.app;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/** Native Binance-style login: email + password, gold CTA, optional server field. */
public class LoginActivity extends Activity {

    private Session session;
    private EditText etEmail, etPassword, etServer;
    private TextView tvError, btnEye, btnServerToggle;
    private LinearLayout llServer;
    private Button btnLogin;
    private boolean busy = false;
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

        etServer.setText(session.server());
        if (!session.hasServer()) {
            llServer.setVisibility(View.VISIBLE);
            btnServerToggle.setText("SERVER SETTINGS  ▴");
        }

        btnEye.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                pwVisible = !pwVisible;
                etPassword.setInputType(pwVisible ? 145 : 129); // visiblePassword : textPassword
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
    }

    private void showErr(String msg) {
        tvError.setText(msg);
        tvError.setVisibility(View.VISIBLE);
    }

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
                // login OK hai to session ko turant validate karo (double-check)
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
                        try {
                            JSONObject jo = new JSONObject(r.body);
                            session.server(server);
                            session.cookie(r.setCookie);
                            JSONObject user = jo.optJSONObject("user");
                            if (user != null) {
                                session.email(user.optString("email", email));
                                session.name(user.optString("name", "Trader"));
                            }
                            JSONObject sub = jo.optJSONObject("subscription");
                            if (sub != null) {
                                session.plan(sub.optString("plan", "—"));
                                session.expiry(sub.optString("expires_at", ""));
                            }
                            Toast.makeText(LoginActivity.this, "Welcome, " + session.name() + "!", Toast.LENGTH_SHORT).show();
                            startActivity(new Intent(LoginActivity.this, MainActivity.class));
                            finish();
                        } catch (Exception e) {
                            showErr("Server response samajh nahi aaya");
                        }
                    }
                });
            }
        }).start();
    }
}
