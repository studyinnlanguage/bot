package com.weexionic.app;

import android.app.Activity;
import android.graphics.Typeface;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * Bot Settings — web dashboard jaisa poora control, ab app ke andar:
 * exchange, testnet, API credentials, coins, timeframe, leverage,
 * order size, stop-loss, TP mode, direction, max concurrent trades.
 * Server: GET/POST /api/bot/config (sirf filled keys overwrite hoti hain).
 */
public class SettingsActivity extends Activity {

    private Session session;
    private Typeface fBold, fMed, fNum;

    private String exchange = "binance", timeframe = "1d", amountMode = "fixed",
                   tpMode = "both", mode = "both";
    private boolean testnet = false;
    private boolean hasKey = false, hasPass = false;

    private TextView btnExWeex, btnExBinance, btnAmtFixed, btnAmtPct,
            btnTpFixed, btnTpEma, btnTpBoth, btnModeLong, btnModeShort, btnModeBoth;
    private TextView[] tfBtns;
    private String[] tfVals = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"};
    private Switch swTestnet;
    private EditText etApiKey, etApiSecret, etPassphrase, etSymbols, etLeverage,
            etAmount, etAmountPct, etSl, etMaxTrades;
    private TextView tvKeyState;
    private Button btnSaveMain, btnSaveTop;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);

        try {
            fBold = Typeface.createFromAsset(getAssets(), "SpaceGrotesk-Bold.ttf");
            fMed = Typeface.createFromAsset(getAssets(), "SpaceGrotesk-Medium.ttf");
            fNum = Typeface.createFromAsset(getAssets(), "JetBrainsMono-Bold.ttf");
        } catch (Exception e) {
            fBold = fMed = fNum = null;
        }

        session = new Session(this);

        TextView btnBack = findViewById(R.id.btnBack);
        btnSaveTop = findViewById(R.id.btnSaveTop);
        btnSaveMain = findViewById(R.id.btnSaveMain);
        btnExWeex = findViewById(R.id.btnExWeex);
        btnExBinance = findViewById(R.id.btnExBinance);
        btnAmtFixed = findViewById(R.id.btnAmtFixed);
        btnAmtPct = findViewById(R.id.btnAmtPct);
        btnTpFixed = findViewById(R.id.btnTpFixed);
        btnTpEma = findViewById(R.id.btnTpEma);
        btnTpBoth = findViewById(R.id.btnTpBoth);
        btnModeLong = findViewById(R.id.btnModeLong);
        btnModeShort = findViewById(R.id.btnModeShort);
        btnModeBoth = findViewById(R.id.btnModeBoth);
        swTestnet = findViewById(R.id.swTestnet);
        etApiKey = findViewById(R.id.etApiKey);
        etApiSecret = findViewById(R.id.etApiSecret);
        etPassphrase = findViewById(R.id.etPassphrase);
        etSymbols = findViewById(R.id.etSymbols);
        etLeverage = findViewById(R.id.etLeverage);
        etAmount = findViewById(R.id.etAmount);
        etAmountPct = findViewById(R.id.etAmountPct);
        etSl = findViewById(R.id.etSl);
        etMaxTrades = findViewById(R.id.etMaxTrades);
        tvKeyState = findViewById(R.id.tvKeyState);

        tfBtns = new TextView[]{
                findViewById(R.id.btnTf1m), findViewById(R.id.btnTf5m),
                findViewById(R.id.btnTf15m), findViewById(R.id.btnTf1h),
                findViewById(R.id.btnTf4h), findViewById(R.id.btnTf1d),
                findViewById(R.id.btnTf1w)
        };

        applyFont((TextView) findViewById(R.id.btnBack), fBold);
        applyFont((TextView) findViewById(R.id.btnSaveTop), fBold);
        applyFont(btnSaveMain, fBold);

        btnBack.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { finish(); }
        });
        btnSaveTop.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { save(); }
        });
        btnSaveMain.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { save(); }
        });

        btnExWeex.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setExchange("weex"); }
        });
        btnExBinance.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setExchange("binance"); }
        });
        for (int i = 0; i < tfBtns.length; i++) {
            final int idx = i;
            tfBtns[i].setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) { setTimeframe(tfVals[idx]); }
            });
        }
        btnAmtFixed.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setAmountMode("fixed"); }
        });
        btnAmtPct.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setAmountMode("percent"); }
        });
        btnTpFixed.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTpMode("fixed"); }
        });
        btnTpEma.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTpMode("ema_reversal"); }
        });
        btnTpBoth.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTpMode("both"); }
        });
        btnModeLong.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setMode("long"); }
        });
        btnModeShort.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setMode("short"); }
        });
        btnModeBoth.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setMode("both"); }
        });

        // default visual states
        setExchange("binance");
        setTimeframe("1d");
        setAmountMode("fixed");
        setTpMode("both");
        setMode("both");

        load();
    }

    private void applyFont(TextView v, Typeface f) {
        if (v != null && f != null) v.setTypeface(f);
    }

    private void setSel(TextView chip, boolean sel) {
        chip.setBackgroundResource(sel ? R.drawable.bg_chip_active : R.drawable.bg_chip);
        chip.setTextColor(sel ? getResources().getColor(R.color.gold)
                : getResources().getColor(R.color.text_sec));
    }

    private void setExchange(String ex) {
        exchange = ex;
        setSel(btnExWeex, "weex".equals(ex));
        setSel(btnExBinance, "binance".equals(ex));
    }

    private void setTimeframe(String tf) {
        timeframe = tf;
        for (int i = 0; i < tfBtns.length; i++) setSel(tfBtns[i], tfVals[i].equals(tf));
    }

    private void setAmountMode(String m) {
        amountMode = m;
        setSel(btnAmtFixed, "fixed".equals(m));
        setSel(btnAmtPct, "percent".equals(m));
    }

    private void setTpMode(String m) {
        tpMode = m;
        setSel(btnTpFixed, "fixed".equals(m));
        setSel(btnTpEma, "ema_reversal".equals(m));
        setSel(btnTpBoth, "both".equals(m));
    }

    private void setMode(String m) {
        mode = m;
        setSel(btnModeLong, "long".equals(m));
        setSel(btnModeShort, "short".equals(m));
        setSel(btnModeBoth, "both".equals(m));
    }

    private void load() {
        new Thread(new Runnable() {
            public void run() {
                final ApiClient.Result r = ApiClient.get(
                        session.server() + "/api/bot/config", session.cookie());
                if (!r.ok()) {
                    runOnUiThread(new Runnable() {
                        public void run() {
                            Toast.makeText(SettingsActivity.this,
                                    "Settings load nahi hui — dobara koshish karein",
                                    Toast.LENGTH_SHORT).show();
                        }
                    });
                    return;
                }
                try {
                    final JSONObject cfg = new JSONObject(r.body)
                            .optJSONObject("config");
                    if (cfg == null) return;
                    runOnUiThread(new Runnable() {
                        public void run() {
                            prefill(cfg);
                        }
                    });
                } catch (Exception ignored) { }
            }
        }).start();
    }

    private void prefill(JSONObject cfg) {
        try {
            setExchange(cfg.optString("exchange", "binance"));
            setTimeframe(cfg.optString("timeframe", "1d"));
            setAmountMode(cfg.optString("amount_mode", "fixed"));
            setTpMode(cfg.optString("tp_mode", "both"));
            setMode(cfg.optString("mode", "both"));
            testnet = cfg.optBoolean("testnet", false);
            swTestnet.setChecked(testnet);
            hasKey = cfg.optBoolean("has_api_key", false);
            hasPass = cfg.optBoolean("has_passphrase", false);

            StringBuilder sb = new StringBuilder();
            org.json.JSONArray syms = cfg.optJSONArray("symbols_list");
            if (syms == null) syms = cfg.optJSONArray("symbols");
            if (syms != null) {
                for (int i = 0; i < syms.length(); i++) {
                    if (i > 0) sb.append(", ");
                    sb.append(syms.optString(i, ""));
                }
            }
            if (sb.length() > 0) etSymbols.setText(sb.toString());
            int lev = cfg.optInt("leverage", 0);
            if (lev > 0) etLeverage.setText(String.valueOf(lev));
            double amt = cfg.optDouble("amount", 0);
            if (amt > 0) etAmount.setText(trimNum(amt));
            double pct = cfg.optDouble("amount_pct", 0);
            if (pct > 0) etAmountPct.setText(trimNum(pct));
            double sl = cfg.optDouble("stop_loss_pct", 0);
            if (sl > 0) etSl.setText(trimNum(sl));
            int mct = cfg.optInt("max_concurrent_trades", 0);
            if (mct > 0) etMaxTrades.setText(String.valueOf(mct));

            tvKeyState.setText(hasKey
                    ? "Saved API key: YES — khaali chhoda to wahi rahegi"
                    : "Saved API key: NAHI — pehli bar keys add karein");
            tvKeyState.setTextColor(getResources().getColor(
                    hasKey ? R.color.green : R.color.gold));
        } catch (Exception ignored) { }
    }

    private static String trimNum(double v) {
        if (v == Math.floor(v)) return String.valueOf((long) v);
        return String.valueOf(v);
    }

    private void save() {
        try {
            JSONObject body = new JSONObject();

            body.put("exchange", exchange);
            testnet = swTestnet.isChecked();
            body.put("testnet", testnet);

            String k = etApiKey.getText().toString().trim();
            String s = etApiSecret.getText().toString().trim();
            String p = etPassphrase.getText().toString().trim();
            if (k.length() > 0) body.put("api_key", k);
            if (s.length() > 0) body.put("api_secret", s);
            if (p.length() > 0) body.put("api_passphrase", p);

            String symRaw = etSymbols.getText().toString().trim();
            if (symRaw.length() == 0) {
                err("Kam az kam ek coin add karein (jaise BTCUSDT)");
                return;
            }
            org.json.JSONArray arr = new org.json.JSONArray();
            for (String part : symRaw.split("[,\\s]+")) {
                if (part.trim().length() > 0) arr.put(part.trim().toUpperCase());
            }
            if (arr.length() == 0) {
                err("Kam az kam ek coin add karein (jaise BTCUSDT)");
                return;
            }
            body.put("symbols_list", arr);

            int lev = parseIntSafe(etLeverage.getText().toString().trim(), 0);
            if (lev > 0) body.put("leverage", lev);
            else if ("binance".equals(exchange)) body.put("leverage", 10);

            body.put("amount_mode", amountMode);
            if ("fixed".equals(amountMode)) {
                double amt = parseDblSafe(etAmount.getText().toString().trim(), 0);
                if (amt <= 0) { err("FIXED mode mein order size (USDT) likhein"); return; }
                body.put("amount", amt);
            } else {
                double pct = parseDblSafe(etAmountPct.getText().toString().trim(), 0);
                if (pct <= 0 || pct > 100) { err("Percent mode mein 1-100 ke beech value likhein"); return; }
                body.put("amount_pct", pct);
            }

            String slRaw = etSl.getText().toString().trim();
            if (slRaw.length() > 0) {
                double sl = parseDblSafe(slRaw, 0);
                if (sl < 0.5 || sl > 50) { err("Stop Loss 0.5% se 50% ke beech rakhein"); return; }
                body.put("stop_loss_pct", sl);
            }

            body.put("tp_mode", tpMode);
            body.put("mode", mode);

            int mct = parseIntSafe(etMaxTrades.getText().toString().trim(), 0);
            if (mct > 0) body.put("max_concurrent_trades", mct);

            busy(true);
            final String payload = body.toString();
            new Thread(new Runnable() {
                public void run() {
                    final ApiClient.Result r = ApiClient.post(
                            session.server() + "/api/bot/config", payload, session.cookie());
                    runOnUiThread(new Runnable() {
                        public void run() {
                            busy(false);
                            boolean ok = false;
                            String emsg = "Save nahi hua — dobara koshish karein";
                            try {
                                JSONObject jo = new JSONObject(r.body);
                                ok = r.ok() && jo.optBoolean("success", false);
                                if (!ok) {
                                    String e2 = jo.optString("error", "");
                                    if (e2.length() > 0) emsg = e2;
                                }
                            } catch (Exception e) {
                                if (r.error != null) emsg = r.error;
                            }
                            if (ok) {
                                Toast.makeText(SettingsActivity.this,
                                        "Settings saved — ab START dabao",
                                        Toast.LENGTH_LONG).show();
                                finish();
                            } else {
                                err(emsg);
                            }
                        }
                    });
                }
            }).start();
        } catch (Exception e) {
            err("Kuch galat tha — fields check karein");
        }
    }

    private void busy(boolean b) {
        btnSaveMain.setEnabled(!b);
        btnSaveTop.setEnabled(!b);
        btnSaveMain.setAlpha(b ? 0.55f : 1f);
        btnSaveMain.setText(b ? "Saving…" : "Save Settings");
    }

    private void err(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }

    private static int parseIntSafe(String s, int def) {
        try { return Integer.parseInt(s); } catch (Exception e) { return def; }
    }

    private static double parseDblSafe(String s, double def) {
        try { return Double.parseDouble(s); } catch (Exception e) { return def; }
    }
}
