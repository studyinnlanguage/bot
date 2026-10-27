package com.weexionic.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.media.AudioAttributes;
import android.media.SoundPool;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;

/**
 * Weexionic v3 — FULLY NATIVE app. No WebView anywhere.
 * 5 tabs: Home / Markets / Chart / Trades / Account, all rendered natively
 * from SaaS JSON APIs (auth/me, bot/status, bot/proxy snapshot+trades).
 */
public class MainActivity extends Activity {

    private static final long TICK_MS = 4000;
    private static final int GOLD = 0xFFF0B90B, GREEN = 0xFF0ECB81, RED = 0xFFF6465D;
    private static final int TPRI = 0xFFF2F4F7, TSEC = 0xFF8A93A5, TDIM = 0xFF5B6472;

    private Session session;
    private Handler ui;
    private boolean ticking = false, tickScheduled = false;
    private int tab = 0, seg = 0;
    private int failStreak = 0;
    private boolean busyAction = false;
    private int reloginTries = 0;
    private long lastReloginMs = 0;

    private Typeface fBold, fMed, fNum;

    // sfx
    private SoundPool sfx;
    private int sTap, sStart, sStop, sErr;
    private boolean sfxReady = false;

    // tab roots
    private View homeView, marketsView, chartViewRoot, tradesView, accountView;
    private ImageView icHome, icMarkets, icChart, icTrades, icAccount;
    private TextView lblHome, lblMarkets, lblChart, lblTrades, lblAccount;

    // topbar + home
    private TextView tvPill, tvGreet, tvBalance, tvBalanceSub, tvCoins, tvTrades,
            tvLev, tvTf, tvMode, tvHomePill, tvUpdated;
    private Button btnStart, btnStop;

    // markets / chart / trades
    private LinearLayout llMarkets, llChips, llIndicators, llTrades;
    private ChartView chart;
    private TextView tvMarkPrice, segPositions, segHistory;

    // account
    private TextView tvAvatar, tvName, tvEmail, tvPlan, tvExpiry, tvServerHost;

    // caches
    private JSONObject lastBotStatus = null;
    private JSONObject lastSnapshot = null;
    private double lastBalance = 0;
    private boolean balOk = false;
    private String activeSymbol = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        session = new Session(this);
        if (!session.hasSession()) { toLogin(); return; }
        setContentView(R.layout.main);
        ui = new Handler(Looper.getMainLooper());

        try {
            fBold = Typeface.createFromAsset(getAssets(), "SpaceGrotesk-Bold.ttf");
            fMed = Typeface.createFromAsset(getAssets(), "SpaceGrotesk-Medium.ttf");
            fNum = Typeface.createFromAsset(getAssets(), "JetBrainsMono-Bold.ttf");
        } catch (Exception e) {
            fBold = fMed = fNum = null;
        }
        initSfx();

        bindViews();
        wireActions();
        setTab(0);
    }

    private void bindViews() {
        homeView = findViewById(R.id.homeView);
        marketsView = findViewById(R.id.marketsView);
        chartViewRoot = findViewById(R.id.chartViewRoot);
        tradesView = findViewById(R.id.tradesView);
        accountView = findViewById(R.id.accountView);

        icHome = findViewById(R.id.icHome);
        icMarkets = findViewById(R.id.icMarkets);
        icChart = findViewById(R.id.icChart);
        icTrades = findViewById(R.id.icTrades);
        icAccount = findViewById(R.id.icAccount);
        lblHome = findViewById(R.id.lblHome);
        lblMarkets = findViewById(R.id.lblMarkets);
        lblChart = findViewById(R.id.lblChart);
        lblTrades = findViewById(R.id.lblTrades);
        lblAccount = findViewById(R.id.lblAccount);

        tvPill = findViewById(R.id.tvPill);
        tvGreet = findViewById(R.id.tvGreet);
        tvBalance = findViewById(R.id.tvBalance);
        tvBalanceSub = findViewById(R.id.tvBalanceSub);
        tvCoins = findViewById(R.id.tvCoins);
        tvTrades = findViewById(R.id.tvTrades);
        tvLev = findViewById(R.id.tvLev);
        tvTf = findViewById(R.id.tvTf);
        tvMode = findViewById(R.id.tvMode);
        tvHomePill = findViewById(R.id.tvHomePill);
        tvUpdated = findViewById(R.id.tvUpdated);
        btnStart = findViewById(R.id.btnStart);
        btnStop = findViewById(R.id.btnStop);

        llMarkets = findViewById(R.id.llMarkets);
        llChips = findViewById(R.id.llChips);
        llIndicators = findViewById(R.id.llIndicators);
        chart = findViewById(R.id.chart);
        tvMarkPrice = findViewById(R.id.tvMarkPrice);
        segPositions = findViewById(R.id.segPositions);
        segHistory = findViewById(R.id.segHistory);
        llTrades = findViewById(R.id.llTrades);

        tvAvatar = findViewById(R.id.tvAvatar);
        tvName = findViewById(R.id.tvName);
        tvEmail = findViewById(R.id.tvEmail);
        tvPlan = findViewById(R.id.tvPlan);
        tvExpiry = findViewById(R.id.tvExpiry);
        tvServerHost = findViewById(R.id.tvServerHost);

        tvServerHost.setText(ApiClient.hostOf(session.server()));
        String nm = session.name();
        if (nm != null && !nm.isEmpty()) {
            tvName.setText(nm);
            tvAvatar.setText(nm.substring(0, 1).toUpperCase(Locale.US));
            tvGreet.setText("Welcome back, " + nm);
        }
        tvEmail.setText(session.email());
        applyFont(tvBalance, fNum);
        applyFont(tvGreet, fMed);
        applyFont(tvMarkPrice, fNum);
    }

    private void applyFont(TextView v, Typeface f) {
        if (v != null && f != null) v.setTypeface(f);
    }

    private void initSfx() {
        try {
            AudioAttributes aa = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build();
            sfx = new SoundPool.Builder().setMaxStreams(4).setAudioAttributes(aa).build();
            sTap = sfx.load(this, R.raw.snd_tap, 1);
            sStart = sfx.load(this, R.raw.snd_start, 1);
            sStop = sfx.load(this, R.raw.snd_stop, 1);
            sErr = sfx.load(this, R.raw.snd_error, 1);
            sfx.setOnLoadCompleteListener(new SoundPool.OnLoadCompleteListener() {
                public void onLoadComplete(SoundPool sp, int id, int status) { sfxReady = true; }
            });
        } catch (Exception e) {
            sfx = null;
        }
    }

    private void playSfx(int id) {
        if (sfx != null && sfxReady && id > 0) {
            try { sfx.play(id, 0.85f, 0.85f, 1, 0, 1f); } catch (Exception ignore) {}
        }
    }

    private void wireActions() {
        findViewById(R.id.tabHome).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTab(0); }
        });
        findViewById(R.id.tabMarkets).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTab(1); }
        });
        findViewById(R.id.tabChart).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTab(2); }
        });
        findViewById(R.id.tabTrades).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTab(3); }
        });
        findViewById(R.id.tabAccount).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTab(4); }
        });

        segPositions.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { seg = 0; styleSeg(); renderTrades(); tickNow(); }
        });
        segHistory.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { seg = 1; styleSeg(); renderTrades(); tickNow(); }
        });

        btnStart.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { if (!busyAction) confirmBot(true); }
        });
        btnStop.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { if (!busyAction) confirmBot(false); }
        });
        findViewById(R.id.btnLogout).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { confirmLogout(); }
        });
    }

    // ---------- Tabs ----------

    private void setTab(int t) {
        if (t != tab) playSfx(sTap);
        tab = t;
        homeView.setVisibility(t == 0 ? View.VISIBLE : View.GONE);
        marketsView.setVisibility(t == 1 ? View.VISIBLE : View.GONE);
        chartViewRoot.setVisibility(t == 2 ? View.VISIBLE : View.GONE);
        tradesView.setVisibility(t == 3 ? View.VISIBLE : View.GONE);
        accountView.setVisibility(t == 4 ? View.VISIBLE : View.GONE);

        icHome.setImageResource(t == 0 ? R.drawable.ic_home_on : R.drawable.ic_home_off);
        icMarkets.setImageResource(t == 1 ? R.drawable.ic_markets_on : R.drawable.ic_markets_off);
        icChart.setImageResource(t == 2 ? R.drawable.ic_chart_on : R.drawable.ic_chart_off);
        icTrades.setImageResource(t == 3 ? R.drawable.ic_trades_on : R.drawable.ic_trades_off);
        icAccount.setImageResource(t == 4 ? R.drawable.ic_account_on : R.drawable.ic_account_off);
        lblHome.setTextColor(t == 0 ? GOLD : TDIM);
        lblMarkets.setTextColor(t == 1 ? GOLD : TDIM);
        lblChart.setTextColor(t == 2 ? GOLD : TDIM);
        lblTrades.setTextColor(t == 3 ? GOLD : TDIM);
        lblAccount.setTextColor(t == 4 ? GOLD : TDIM);

        tickNow();
    }

    @Override
    public void onBackPressed() {
        moveTaskToBack(true);
    }

    // ---------- Polling ----------

    @Override
    protected void onResume() {
        super.onResume();
        tickNow();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (ui != null) ui.removeCallbacksAndMessages(null);
        tickScheduled = false;
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (sfx != null) { try { sfx.release(); } catch (Exception ignore) {} sfx = null; }
    }

    private void scheduleTick() {
        if (!tickScheduled && ui != null) {
            tickScheduled = true;
            ui.postDelayed(new Runnable() {
                public void run() {
                    tickScheduled = false;
                    tickNow();
                }
            }, TICK_MS);
        }
    }

    private void tickNow() {
        if (ticking || session == null || !session.hasSession()) return;
        ticking = true;
        final int curTab = tab;
        final int curSeg = seg;
        new Thread(new Runnable() {
            public void run() {
                String base = session.server();
                String ck = session.cookie();

                // 1) session check
                ApiClient.Result me = ApiClient.get(base + "/api/auth/me", ck);
                boolean loggedIn = false;
                JSONObject user = null, sub = null;
                boolean botRunning = false;
                if (me.ok()) {
                    try {
                        JSONObject jm = new JSONObject(me.body);
                        loggedIn = jm.optBoolean("success", false);
                        if (loggedIn) {
                            user = jm.optJSONObject("user");
                            sub = jm.optJSONObject("subscription");
                            botRunning = jm.optBoolean("bot_running", false);
                            String nck = me.setCookie;
                            if (nck != null && nck.startsWith("session=")) session.cookie(nck);
                        }
                    } catch (Exception ignored) { }
                }
                if (!loggedIn) {
                    failStreak++;
                    if (failStreak >= 3) { onAuthExpired(); return; }
                    runOnUiThread(new Runnable() {
                        public void run() {
                            ticking = false;
                            setPill(0);
                            scheduleTick();
                        }
                    });
                    return;
                }
                failStreak = 0;
                reloginTries = 0;

                // 2) bot status + balance
                double bal = 0; boolean bok = false;
                String exchange = "", mode = "";
                int coins = 0, trades = 0;
                String lev = "—", tf = "—";
                boolean running = botRunning;
                if (running) {
                    ApiClient.Result bs = ApiClient.get(base + "/api/bot/status", ck);
                    if (bs.ok()) {
                        try {
                            JSONObject jb = new JSONObject(bs.body);
                            lastBotStatus = jb;
                            JSONObject st = jb.optJSONObject("bot_status");
                            JSONObject bbal = jb.optJSONObject("balance");
                            if (bbal != null && bbal.optBoolean("success", false)) {
                                bal = bbal.optDouble("balance", 0);
                                bok = true;
                                exchange = bbal.optString("exchange", "");
                                mode = bbal.optBoolean("testnet", true) ? "TESTNET" : "LIVE";
                            }
                            if (st != null) {
                                running = st.optBoolean("running", running);
                                trades = st.optInt("trades_today", 0);
                                if (exchange.isEmpty()) exchange = st.optString("exchange", "");
                                if (mode.isEmpty()) mode = st.optBoolean("testnet", true) ? "TESTNET" : "LIVE";
                                JSONArray syms = st.optJSONArray("symbols");
                                coins = syms == null ? 0 : syms.length();
                                lev = st.optInt("leverage", 0) > 0 ? st.optInt("leverage", 0) + "x" : "—";
                                tf = st.optString("timeframe", "");
                                if (tf == null || tf.isEmpty()) tf = "—";
                            }
                        } catch (Exception ignored) { }
                    }
                } else {
                    lastBotStatus = null;
                    lastSnapshot = null;
                }

                // 3) snapshot for markets/chart/trades tabs
                JSONObject snap = null;
                JSONObject hist = null;
                if (running && curTab >= 1 && curTab <= 3) {
                    ApiClient.Result sr = ApiClient.get(base + "/api/bot/proxy?path=/api/snapshot", ck);
                    if (sr.ok()) {
                        try {
                            JSONObject js = new JSONObject(sr.body);
                            if (js.has("chart") || js.has("positions")) snap = js;
                        } catch (Exception ignored) { }
                    }
                    if (snap != null) lastSnapshot = snap;
                    if (curTab == 3 && curSeg == 1) {
                        ApiClient.Result tr = ApiClient.get(base + "/api/bot/proxy?path=/api/trades", ck);
                        if (tr.ok()) {
                            try {
                                JSONObject jt = new JSONObject(tr.body);
                                if (jt.optBoolean("success", false)) hist = jt;
                            } catch (Exception ignored) { }
                        }
                    }
                }

                final double fBal = bal; final boolean fBok = bok;
                final String fEx = exchange, fMode = mode;
                final int fCoins = coins, fTrades = trades;
                final String fLev = lev, fTf = tf;
                final boolean fRun = running;
                final JSONObject fUser = user, fSub = sub;
                final JSONObject fSnap = snap, fHist = hist;
                runOnUiThread(new Runnable() {
                    public void run() {
                        ticking = false;
                        renderCommon(fUser, fSub, fRun, fBal, fBok, fEx, fMode, fCoins, fTrades, fLev, fTf);
                        if (fSnap != null) {
                            if (tab == 1) renderMarkets(fSnap);
                            if (tab == 2) renderChart(fSnap);
                            if (tab == 3 && seg == 0) renderPositions(fSnap);
                        } else if (tab >= 1 && tab <= 3) {
                            if (tab == 1) renderMarketsEmpty(fRun);
                            if (tab == 2) { chart.setData(null, null); tvMarkPrice.setText("Mark price —"); llIndicators.removeAllViews(); }
                            if (tab == 3) llTrades.removeAllViews();
                        }
                        if (tab == 3 && seg == 1 && fHist != null) renderHistory(fHist);
                        scheduleTick();
                    }
                });
            }
        }).start();
    }

    // ---------- Renderers ----------

    private void renderCommon(JSONObject user, JSONObject sub, boolean running,
                              double bal, boolean bok, String ex, String mode,
                              int coins, int trades, String lev, String tf) {
        setPill(running ? 1 : 2);
        tvHomePill.setBackgroundResource(running ? R.drawable.bg_pill_green : R.drawable.bg_pill_gray);
        tvHomePill.setTextColor(running ? GREEN : TSEC);
        tvHomePill.setText(running ? "RUNNING" : "STOPPED");
        if (bok) {
            tvBalance.setText(String.format(Locale.US, "$%.2f", bal));
            tvBalanceSub.setText((ex.isEmpty() ? "" : ex.toUpperCase(Locale.US) + "  •  ") + mode);
            lastBalance = bal; balOk = true;
        } else {
            tvBalance.setText("$0.00");
            tvBalanceSub.setText(running ? "Exchange balance unavailable" : "Bot start karein — balance yahan aayega");
            balOk = false;
        }
        tvCoins.setText(running ? String.valueOf(coins) : "—");
        tvTrades.setText(running ? String.valueOf(trades) : "—");
        tvLev.setText(running ? lev : "—");
        tvTf.setText(running ? tf : "—");
        tvMode.setText(running
                ? (ex.isEmpty() ? "" : ex.toUpperCase(Locale.US) + " " + mode + "  •  ") + "EMA 8/13/21/55  •  strict 1:1 RR"
                : "EMA 8/13/21/55  •  strict 1:1 RR");
        String t = new SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date());
        tvUpdated.setText("Updated  " + t);

        if (user != null) {
            String nm = user.optString("name", "");
            if (!nm.isEmpty()) tvName.setText(nm);
            String em = user.optString("email", "");
            if (!em.isEmpty()) tvEmail.setText(em);
        }
        if (sub != null) {
            String p = sub.optString("plan", "—");
            tvPlan.setText("•  " + (p.isEmpty() ? "—" : p.toUpperCase(Locale.US)));
            tvExpiry.setText(fmtExpiry(sub.optString("expires_at", "")));
        }
    }

    private void renderMarketsEmpty(boolean running) {
        llMarkets.removeAllViews();
        llMarkets.addView(emptyNote(running
                ? "Market data load ho rahi hai…"
                : "Bot start karein — markets yahan live aayenge"));
    }

    private void renderMarkets(JSONObject snap) {
        try {
            JSONObject chart = snap.optJSONObject("chart");
            if (chart == null) { renderMarketsEmpty(true); return; }
            List<String> syms = sortedKeys(chart);
            llMarkets.removeAllViews();
            if (syms.isEmpty()) { renderMarketsEmpty(true); return; }
            for (String sym : syms) {
                JSONObject cd = chart.optJSONObject(sym);
                if (cd == null) continue;
                JSONArray candles = cd.optJSONArray("candles");
                double last = 0, prev = 0;
                if (candles != null && candles.length() >= 2) {
                    last = candles.getJSONObject(candles.length() - 1).optDouble("close", 0);
                    prev = candles.getJSONObject(candles.length() - 2).optDouble("close", last);
                }
                double chg = prev != 0 ? (last - prev) / prev * 100.0 : 0;
                int col = chg >= 0 ? GREEN : RED;

                LinearLayout row = new LinearLayout(this);
                row.setLayoutParams(lp(-1, -2, 0, 0, 0, 10));
                row.setBackgroundResource(R.drawable.bg_card);
                row.setPadding(dp(16), dp(14), dp(16), dp(14));
                row.setGravity(Gravity.CENTER_VERTICAL);

                LinearLayout left = new LinearLayout(this);
                left.setLayoutParams(lp(0, -2, 1f, 0, 0, 0));
                left.setOrientation(LinearLayout.VERTICAL);

                TextView tSym = tv(sym, 14, true, TPRI);
                left.addView(tSym);
                TextView tPrice = tv(String.format(Locale.US, "$%.2f", last), 16, true, col);
                applyFont(tPrice, fNum);
                left.addView(tPrice);

                SparkView spark = new SparkView(this);
                spark.setLayoutParams(lp(dp(78), dp(30), 0, 0, 0, 0));
                spark.setCloses(candles);

                TextView tChg = tv((chg >= 0 ? "+" : "") + String.format(Locale.US, "%.2f%%", chg), 13, true, col);
                tChg.setGravity(Gravity.END);
                LinearLayout right = new LinearLayout(this);
                right.setLayoutParams(lp(0, -2, 0, 0, 0, 0));
                right.setOrientation(LinearLayout.VERTICAL);
                right.setGravity(Gravity.END);
                right.addView(tChg);

                row.addView(left);
                row.addView(spark);
                LinearLayout mid = new LinearLayout(this);
                mid.setLayoutParams(lp(dp(12), 1, 0, 0, 0, 0));
                row.addView(mid);
                row.addView(right);
                llMarkets.addView(row);
            }
        } catch (Exception e) {
            renderMarketsEmpty(true);
        }
    }

    private void renderChart(JSONObject snap) {
        try {
            JSONObject chartData = snap.optJSONObject("chart");
            if (chartData == null) return;
            List<String> syms = sortedKeys(chartData);
            if (activeSymbol == null || !syms.contains(activeSymbol)) {
                // prefer active_symbol from snapshot, else first
                String as = snap.optString("active_symbol", "");
                activeSymbol = syms.contains(as) ? as : (syms.isEmpty() ? null : syms.get(0));
            }
            if (activeSymbol == null) return;

            // chips
            llChips.removeAllViews();
            for (final String s : syms) {
                TextView chip = tv(s.replace("USDT", ""), 12, true,
                        s.equals(activeSymbol) ? GOLD : TSEC);
                chip.setBackgroundResource(s.equals(activeSymbol)
                        ? R.drawable.bg_chip_active : R.drawable.bg_chip);
                chip.setPadding(dp(16), dp(8), dp(16), dp(8));
                chip.setGravity(Gravity.CENTER);
                chip.setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) { activeSymbol = s; renderChart(lastSnapshot); }
                });
                LinearLayout wrap = new LinearLayout(this);
                LinearLayout.LayoutParams wlp = new LinearLayout.LayoutParams(-2, -2);
                wlp.rightMargin = dp(8);
                wrap.setLayoutParams(wlp);
                wrap.addView(chip);
                llChips.addView(wrap);
            }

            JSONObject cd = chartData.optJSONObject(activeSymbol);
            if (cd == null) return;
            chart.setData(cd.optJSONArray("candles"), cd.optJSONObject("emas"));

            // indicators
            llIndicators.removeAllViews();
            JSONObject ind = snap.optJSONObject("indicators");
            JSONObject ii = ind == null ? null : ind.optJSONObject(activeSymbol);
            String signal = "HOLD";
            if (ii != null) signal = ii.optString("signal", "HOLD");
            int sigCol = signal.equals("BUY") ? GREEN : (signal.equals("SELL") ? RED : TSEC);

            LinearLayout sigRow = new LinearLayout(this);
            sigRow.setLayoutParams(lp(-1, -2, 0, 0, 0, 10));
            sigRow.setBackgroundResource(R.drawable.bg_card);
            sigRow.setPadding(dp(16), dp(14), dp(16), dp(14));
            sigRow.setGravity(Gravity.CENTER_VERTICAL);
            TextView sigLbl = tv("Quad-Trend Signal", 13, true, TPRI);
            sigLbl.setLayoutParams(lp(0, -2, 1f, 0, 0, 0));
            TextView sigVal = tv(signal, 16, true, sigCol);
            applyFont(sigVal, fBold);
            sigRow.addView(sigLbl);
            sigRow.addView(sigVal);
            llIndicators.addView(sigRow);

            if (ii != null) {
                addIndRow("EMA 8", money(ii.optDouble("ema_8", Double.NaN)));
                addIndRow("EMA 13", money(ii.optDouble("ema_13", Double.NaN)));
                addIndRow("EMA 21", money(ii.optDouble("ema_21", Double.NaN)));
                addIndRow("EMA 55", money(ii.optDouble("ema_55", Double.NaN)));
                addIndRow("EMA Separation", String.format(Locale.US, "%.3f%%", ii.optDouble("ema_sep_pct", 0)));
                double mp = ii.optDouble("close", Double.NaN);
                tvMarkPrice.setText("Mark price  " + (mp == mp ? String.format(Locale.US, "$%.2f", mp) : "—"));
            } else {
                tvMarkPrice.setText("Mark price —");
            }
        } catch (Exception ignored) { }
    }

    private void addIndRow(String k, String v) {
        LinearLayout r = new LinearLayout(this);
        r.setLayoutParams(lp(-1, -2, 0, 0, 0, 6));
        r.setBackgroundResource(R.drawable.bg_card);
        r.setPadding(dp(16), dp(12), dp(16), dp(12));
        r.setGravity(Gravity.CENTER_VERTICAL);
        TextView a = tv(k, 12, true, TSEC);
        a.setLayoutParams(lp(0, -2, 1f, 0, 0, 0));
        TextView b = tv(v, 13, true, TPRI);
        r.addView(a);
        r.addView(b);
        llIndicators.addView(r);
    }

    private void renderPositions(JSONObject snap) {
        try {
            llTrades.removeAllViews();
            JSONArray pos = snap.optJSONArray("positions");
            boolean any = false;
            if (pos != null) {
                for (int i = 0; i < pos.length(); i++) {
                    JSONObject p = pos.getJSONObject(i);
                    String side = p.optString("side", "NONE");
                    if (side.equals("NONE")) continue;
                    any = true;
                    double pnl = p.optDouble("unrealized_pnl", 0);
                    double entry = p.optDouble("entry_price", 0);
                    double size = p.optDouble("size", 0);
                    int levN = p.optInt("leverage", 1);
                    double margin = (entry > 0 && size > 0 && levN > 0) ? (entry * size) / levN : 0;
                    double roe = margin > 0 ? pnl / margin * 100.0 : 0;
                    int col = pnl >= 0 ? GREEN : RED;
                    LinearLayout card = new LinearLayout(this);
                    card.setOrientation(LinearLayout.VERTICAL);
                    card.setLayoutParams(lp(-1, -2, 0, 0, 0, 10));
                    card.setBackgroundResource(R.drawable.bg_card);
                    card.setPadding(dp(16), dp(14), dp(16), dp(14));

                    LinearLayout h = new LinearLayout(this);
                    h.setGravity(Gravity.CENTER_VERTICAL);
                    TextView tSym = tv(p.optString("symbol", ""), 14, true, TPRI);
                    tSym.setLayoutParams(lp(0, -2, 1f, 0, 0, 0));
                    TextView badge = tv(side, 11, true, side.equals("LONG") ? GREEN : RED);
                    badge.setBackgroundResource(side.equals("LONG")
                            ? R.drawable.bg_badge_long : R.drawable.bg_badge_short);
                    badge.setPadding(dp(10), dp(3), dp(10), dp(3));
                    TextView tLev = tv("  " + p.optInt("leverage", 1) + "x", 12, true, TSEC);
                    h.addView(tSym);
                    h.addView(badge);
                    h.addView(tLev);
                    card.addView(h);

                    card.addView(kvRow("Size", String.valueOf(size)));
                    card.addView(kvRow("Entry", money(entry)));
                    card.addView(kvRow("Mark", money(p.optDouble("mark_price", 0))));
                    TextView pnlV = kvVal(String.format(Locale.US, "%s$%.2f  (%.2f%%)",
                            pnl >= 0 ? "+" : "", pnl, roe));
                    // roe fallback: use pnl / (entry*size/lev)
                    TextView pnlL = tv("Unrealized PnL", 12, true, TSEC);
                    pnlL.setLayoutParams(lp(0, -2, 1f, dp(8), 0, 0));
                    pnlV.setTextColor(col);
                    LinearLayout pr = new LinearLayout(this);
                    pr.setGravity(Gravity.CENTER_VERTICAL);
                    pr.addView(pnlL);
                    pr.addView(pnlV);
                    card.addView(pr);
                    llTrades.addView(card);
                }
            }
            if (!any) llTrades.addView(emptyNote("Koi open position nahi — bot entry ka wait kar raha hai"));
        } catch (Exception e) {
            llTrades.addView(emptyNote("Positions load nahi ho saki"));
        }
    }

    private void renderHistory(JSONObject hist) {
        try {
            llTrades.removeAllViews();
            JSONArray arr = hist.optJSONArray("trades");
            int shown = 0;
            if (arr != null) {
                for (int i = arr.length() - 1; i >= 0 && shown < 40; i--) {
                    JSONObject t = arr.getJSONObject(i);
                    if (!"CLOSED".equals(t.optString("status"))) continue;
                    shown++;
                    double pnl = t.optDouble("pnl", 0);
                    int col = pnl >= 0 ? GREEN : RED;
                    String reason = t.optString("close_reason", "");
                    String when = t.optString("closed_at", "");
                    if (when.length() >= 16) when = when.substring(0, 16).replace("T", " ");

                    LinearLayout card = new LinearLayout(this);
                    card.setOrientation(LinearLayout.VERTICAL);
                    card.setLayoutParams(lp(-1, -2, 0, 0, 0, 8));
                    card.setBackgroundResource(R.drawable.bg_card);
                    card.setPadding(dp(16), dp(12), dp(16), dp(12));

                    LinearLayout h = new LinearLayout(this);
                    h.setGravity(Gravity.CENTER_VERTICAL);
                    TextView tSym = tv(t.optString("symbol", "") + "  " + t.optString("side", ""),
                            13, true, TPRI);
                    tSym.setLayoutParams(lp(0, -2, 1f, 0, 0, 0));
                    TextView tPnl = tv(String.format(Locale.US, "%s$%.2f", pnl >= 0 ? "+" : "", pnl), 14, true, col);
                    applyFont(tPnl, fNum);
                    h.addView(tSym);
                    h.addView(tPnl);
                    card.addView(h);

                    String line = String.format(Locale.US, "%s → %s  •  %s  •  ROE %.2f%%",
                            money(t.optDouble("entry_price", 0)),
                            money(t.optDouble("exit_price", 0)),
                            reason.isEmpty() ? "closed" : reason,
                            t.optDouble("roe_pct", 0));
                    TextView tvLine = tv(line, 11, false, TSEC);
                    tvLine.setLayoutParams(lp(-1, -2, 0, dp(4), 0, 0));
                    card.addView(tvLine);
                    if (!when.isEmpty()) {
                        TextView tvWhen = tv(when, 10, false, TDIM);
                        tvWhen.setLayoutParams(lp(-1, -2, 0, dp(2), 0, 0));
                        card.addView(tvWhen);
                    }
                    llTrades.addView(card);
                }
            }
            if (shown == 0) llTrades.addView(emptyNote("Abhi tak koi closed trade nahi"));
        } catch (Exception e) {
            llTrades.addView(emptyNote("History load nahi hui"));
        }
    }

    private void styleSeg() {
        segPositions.setBackgroundResource(seg == 0 ? R.drawable.bg_seg_active : R.drawable.bg_seg);
        segPositions.setTextColor(seg == 0 ? GOLD : TDIM);
        segHistory.setBackgroundResource(seg == 1 ? R.drawable.bg_seg_active : R.drawable.bg_seg);
        segHistory.setTextColor(seg == 1 ? GOLD : TDIM);
    }

    private void renderTrades() {
        if (seg == 0 && lastSnapshot != null) {
            renderPositions(lastSnapshot);
        } else if (seg == 1) {
            // history refreshes on next tick
        } else {
            llTrades.removeAllViews();
        }
    }

    private void expire() {
        runOnUiThread(new Runnable() {
            public void run() {
                Toast.makeText(MainActivity.this, "Session khatam — dobara login karein", Toast.LENGTH_LONG).show();
                toLogin();
            }
        });
    }

    /** 401 bhaag gaya — pehle silent relogin try karo (Remember me), warna login screen. */
    private void onAuthExpired() {
        if (session.hasSavedLogin() && reloginTries < 3
                && System.currentTimeMillis() - lastReloginMs > 5000) {
            silentRelogin();
            return;
        }
        expire();
    }

    private void silentRelogin() {
        reloginTries++;
        lastReloginMs = System.currentTimeMillis();
        final String email = session.email();
        final String pass = session.savedPass();
        final String base = session.server();
        new Thread(new Runnable() {
            public void run() {
                String b = "{}";
                try {
                    JSONObject jo = new JSONObject();
                    jo.put("email", email);
                    jo.put("password", pass);
                    b = jo.toString();
                } catch (Exception ignore) { }
                final ApiClient.Result r = ApiClient.post(base + "/api/auth/login", b, null);
                boolean ok = false;
                String ck = r.setCookie == null ? "" : r.setCookie;
                if (r.ok() && ck.startsWith("session=")) {
                    ApiClient.Result me = ApiClient.get(base + "/api/auth/me", ck);
                    try {
                        ok = me.ok() && new JSONObject(me.body).optBoolean("success", false);
                    } catch (Exception ignore) { }
                }
                if (ok) {
                    session.cookie(ck);
                    reloginTries = 0;
                    ticking = false;
                    tickNow();
                } else {
                    expire();
                }
            }
        }).start();
    }

    // ---------- View factories ----------

    private TextView tv(String text, int sp, boolean bold, int color) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(sp);
        t.setTypeface(bold ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        t.setTextColor(color);
        return t;
    }

    private TextView kvVal(String v) {
        TextView t = tv(v, 12, true, TPRI);
        return t;
    }

    private LinearLayout kvRow(String k, String v) {
        LinearLayout r = new LinearLayout(this);
        r.setGravity(Gravity.CENTER_VERTICAL);
        TextView a = tv(k, 12, true, TSEC);
        a.setLayoutParams(lp(0, -2, 1f, dp(6), 0, 0));
        TextView b = tv(v, 12, true, TPRI);
        b.setLayoutParams(new LinearLayout.LayoutParams(-2, -2, 0));
        r.addView(a);
        r.addView(b);
        return r;
    }

    private TextView emptyNote(String msg) {
        TextView t = tv(msg, 13, false, TDIM);
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(20), dp(40), dp(20), dp(40));
        return t;
    }

    private LinearLayout.LayoutParams lp(int w, int h, float weight, int l, int t, int b) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(w, h, weight);
        p.leftMargin = l; p.topMargin = t; p.bottomMargin = b;
        return p;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private static List<String> sortedKeys(JSONObject o) {
        List<String> out = new ArrayList<String>();
        if (o == null) return out;
        Iterator<String> it = o.keys();
        while (it.hasNext()) out.add(it.next());
        Collections.sort(out);
        return out;
    }

    private static String money(double v) {
        if (v != v) return "—";
        return String.format(Locale.US, "$%.2f", v);
    }

    // ---------- Actions ----------

    private void confirmBot(final boolean start) {
        AlertDialog d = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle(start ? "Start Bot?" : "Stop Bot?")
            .setMessage(start
                ? "Trading engine start ho jayega — live positions manage hongi."
                : "Bot ruk jayega. Khuli positions open reh sakti hain — manual manage karna paray ga.")
            .setPositiveButton(start ? "START" : "STOP", new DialogInterface.OnClickListener() {
                public void onClick(DialogInterface di, int w) { botAction(start); }
            })
            .setNegativeButton("CANCEL", null)
            .show();
        d.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(GOLD);
        d.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(TSEC);
    }

    private void botAction(final boolean start) {
        busyAction = true;
        btnStart.setEnabled(false); btnStop.setEnabled(false);
        btnStart.setAlpha(0.55f); btnStop.setAlpha(0.55f);
        Toast.makeText(this, start ? "Starting bot…" : "Stopping bot…", Toast.LENGTH_SHORT).show();
        new Thread(new Runnable() {
            public void run() {
                final ApiClient.Result r = ApiClient.post(
                    session.server() + (start ? "/api/bot/start" : "/api/bot/stop"),
                    "{}", session.cookie());
                runOnUiThread(new Runnable() {
                    public void run() {
                        busyAction = false;
                        btnStart.setEnabled(true); btnStop.setEnabled(true);
                        btnStart.setAlpha(1f); btnStop.setAlpha(1f);
                        String msg;
                        boolean ok = false;
                        try {
                            JSONObject jo = new JSONObject(r.body);
                            ok = r.ok() && jo.optBoolean("success", false);
                            if (ok) {
                                msg = start ? "Bot STARTED" : "Bot STOPPED";
                            } else {
                                msg = jo.optString("error", "Action failed (" + r.code + ")");
                            }
                        } catch (Exception e) {
                            msg = r.error != null ? r.error : "Action failed";
                        }
                        playSfx(ok ? (start ? sStart : sStop) : sErr);
                        Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
                        ticking = false;
                        tickNow();
                    }
                });
            }
        }).start();
    }

    private void confirmLogout() {
        AlertDialog d = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle("Log Out?")
            .setMessage("Logout karne par server aap ka bot bhi STOP kar deta hai. Continue?")
            .setPositiveButton("LOG OUT", new DialogInterface.OnClickListener() {
                public void onClick(DialogInterface di, int w) { doLogout(); }
            })
            .setNegativeButton("CANCEL", null)
            .show();
        d.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(RED);
        d.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(TSEC);
    }

    private void doLogout() {
        new Thread(new Runnable() {
            public void run() {
                ApiClient.post(session.server() + "/api/auth/logout", "{}", session.cookie());
                runOnUiThread(new Runnable() {
                    public void run() {
                        session.logout();
                        toLogin();
                    }
                });
            }
        }).start();
    }

    private void toLogin() {
        startActivity(new Intent(this, LoginActivity.class));
        finish();
    }

    private void setPill(int state) {
        if (state == 1) {
            tvPill.setBackgroundResource(R.drawable.bg_pill_green);
            tvPill.setTextColor(GREEN);
            tvPill.setText("•  RUNNING");
        } else if (state == 2) {
            tvPill.setBackgroundResource(R.drawable.bg_pill_red);
            tvPill.setTextColor(RED);
            tvPill.setText("•  STOPPED");
        } else {
            tvPill.setBackgroundResource(R.drawable.bg_pill_gray);
            tvPill.setTextColor(TSEC);
            tvPill.setText("•  SYNC…");
        }
    }

    private String fmtExpiry(String iso) {
        if (iso == null || iso.length() < 10) return "";
        if (iso.startsWith("9999")) return "Lifetime";
        try {
            SimpleDateFormat in = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
            SimpleDateFormat out = new SimpleDateFormat("dd MMM yyyy", Locale.US);
            return "till " + out.format(in.parse(iso.substring(0, 10)));
        } catch (Exception e) {
            return "";
        }
    }
}
