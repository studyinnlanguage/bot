package com.weexionic.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.media.AudioAttributes;
import android.media.SoundPool;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
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
 * Weexionic v3.4 — FULLY NATIVE, concept-exact.
 * 5 tabs like the approved mockup: Home / Markets / TRADE (gold FAB) / Wallet / Profile.
 * Everything renders from REAL SaaS + engine APIs:
 *   - /api/auth/me, /api/bot/status, /api/bot/config (GET/POST)
 *   - /api/bot/proxy → engine /api/snapshot, /api/trades, /api/close
 *   - /api/user/referral (wallet balance + share link + commissions)
 * 100% English UI. Server is baked in — nothing for the user to configure.
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
    private View homeView, marketsView, tradeView, walletView, accountView;
    private ImageView icHome, icMarkets, icTrade, icWallet, icAccount;
    private TextView lblHome, lblMarkets, lblTrade, lblWallet, lblAccount;

    // topbar + home
    private TextView tvPill, tvGreet, tvBalance, tvBalanceSub, tvCoins, tvTrades,
            tvLev, tvTf, tvMode, tvHomePill, tvUpdated;
    private Button btnStart, btnStop;
    private View cardWarn;
    private TextView tvWarn;
    private SparkView sparkHome;
    private LinearLayout llHomeCoins;
    private int homeTick = 0;

    // trade tab
    private LinearLayout llChips, llTrades;
    private ChartView chart;
    private TextView tvTradePrice, tvTradeChg, tvEmaLegend, tvSignal,
            tvTradeLevBadge, tvApplyMsg, tvUpdatedTrade, segPositions, segHistory;
    private EditText etSize, etLev, etSl;
    private TextView segDirLong, segDirBoth, segDirShort;
    private Button btnApply;
    private int dir = 2; // 0=long 1=short 2=both (default mirrors server)
    private boolean cfgLoaded = false, applying = false;

    // wallet tab
    private TextView tvWalletBalance, tvWalletSub, tvWalletPending, tvRefLink,
            tvRefCount, tvRefEarned, tvRateYearly, tvRateLifetime;

    // account
    private TextView tvAvatar, tvName, tvEmail, tvPlan, tvExpiry, tvServerHost;

    // caches
    private JSONObject lastBotStatus = null;
    private JSONObject lastSnapshot = null;
    private JSONObject lastReferral = null;
    private double lastBalance = 0;
    private boolean balOk = false;
    private String activeSymbol = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
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
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
            Toast.makeText(this, "Startup error — please reopen the app", Toast.LENGTH_LONG).show();
            finish();
        }
    }

    private void bindViews() {
        homeView = findViewById(R.id.homeView);
        marketsView = findViewById(R.id.marketsView);
        tradeView = findViewById(R.id.tradeView);
        walletView = findViewById(R.id.walletView);
        accountView = findViewById(R.id.accountView);

        icHome = findViewById(R.id.icHome);
        icMarkets = findViewById(R.id.icMarkets);
        icTrade = findViewById(R.id.icTrade);
        icWallet = findViewById(R.id.icWallet);
        icAccount = findViewById(R.id.icAccount);
        lblHome = findViewById(R.id.lblHome);
        lblMarkets = findViewById(R.id.lblMarkets);
        lblTrade = findViewById(R.id.lblTrade);
        lblWallet = findViewById(R.id.lblWallet);
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
        cardWarn = findViewById(R.id.cardWarn);
        tvWarn = findViewById(R.id.tvWarn);
        sparkHome = findViewById(R.id.sparkHome);
        llHomeCoins = findViewById(R.id.llHomeCoins);

        llChips = findViewById(R.id.llChips);
        chart = findViewById(R.id.chart);
        tvTradePrice = findViewById(R.id.tvTradePrice);
        tvTradeChg = findViewById(R.id.tvTradeChg);
        tvEmaLegend = findViewById(R.id.tvEmaLegend);
        tvSignal = findViewById(R.id.tvSignal);
        tvTradeLevBadge = findViewById(R.id.tvTradeLevBadge);
        etSize = findViewById(R.id.etSize);
        etLev = findViewById(R.id.etLev);
        etSl = findViewById(R.id.etSl);
        segDirLong = findViewById(R.id.segDirLong);
        segDirBoth = findViewById(R.id.segDirBoth);
        segDirShort = findViewById(R.id.segDirShort);
        btnApply = findViewById(R.id.btnApply);
        tvApplyMsg = findViewById(R.id.tvApplyMsg);
        segPositions = findViewById(R.id.segPositions);
        segHistory = findViewById(R.id.segHistory);
        llTrades = findViewById(R.id.llTrades);
        tvUpdatedTrade = findViewById(R.id.tvUpdatedTrade);

        tvWalletBalance = findViewById(R.id.tvWalletBalance);
        tvWalletSub = findViewById(R.id.tvWalletSub);
        tvWalletPending = findViewById(R.id.tvWalletPending);
        tvRefLink = findViewById(R.id.tvRefLink);
        tvRefCount = findViewById(R.id.tvRefCount);
        tvRefEarned = findViewById(R.id.tvRefEarned);
        tvRateYearly = findViewById(R.id.tvRateYearly);
        tvRateLifetime = findViewById(R.id.tvRateLifetime);

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
        applyFont(tvTradePrice, fNum);
        applyFont(tvWalletBalance, fNum);

        applyFont(tvName, fBold);
        applyFont(tvSignal, fBold);

        findViewById(R.id.rowSettings).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                playSfx(sTap);
                startActivity(new Intent(MainActivity.this, SettingsActivity.class));
            }
        });
        findViewById(R.id.tvManage).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                playSfx(sTap);
                startActivity(new Intent(MainActivity.this, SettingsActivity.class));
            }
        });
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
        findViewById(R.id.tabTrade).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setTab(2); }
        });
        findViewById(R.id.tabWallet).setOnClickListener(new View.OnClickListener() {
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

        btnApply.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { if (!applying) applyQuickControls(); }
        });
        segDirLong.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setDir(0); }
        });
        segDirBoth.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setDir(2); }
        });
        segDirShort.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { setDir(1); }
        });

        findViewById(R.id.btnCopyLink).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { copyRefLink(); }
        });
        findViewById(R.id.btnShareWhatsApp).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { shareReferral("whatsapp"); }
        });
        findViewById(R.id.btnShareTelegram).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { shareReferral("telegram"); }
        });
    }

    // ---------- Tabs ----------

    private void setTab(int t) {
        if (t != tab) playSfx(sTap);
        tab = t;
        homeView.setVisibility(t == 0 ? View.VISIBLE : View.GONE);
        marketsView.setVisibility(t == 1 ? View.VISIBLE : View.GONE);
        tradeView.setVisibility(t == 2 ? View.VISIBLE : View.GONE);
        walletView.setVisibility(t == 3 ? View.VISIBLE : View.GONE);
        accountView.setVisibility(t == 4 ? View.VISIBLE : View.GONE);

        icHome.setImageResource(t == 0 ? R.drawable.ic_home_on : R.drawable.ic_home_off);
        icMarkets.setImageResource(t == 1 ? R.drawable.ic_markets_on : R.drawable.ic_markets_off);
        icTrade.setImageResource(t == 2 ? R.drawable.ic_trade_on : R.drawable.ic_trade_off);
        icWallet.setImageResource(t == 3 ? R.drawable.ic_wallet_on : R.drawable.ic_wallet_off);
        icAccount.setImageResource(t == 4 ? R.drawable.ic_account_on : R.drawable.ic_account_off);

        lblHome.setTextColor(t == 0 ? GOLD : TDIM);
        lblMarkets.setTextColor(t == 1 ? GOLD : TDIM);
        lblTrade.setTextColor(t == 2 ? GOLD : TDIM);
        lblWallet.setTextColor(t == 3 ? GOLD : TDIM);
        lblAccount.setTextColor(t == 4 ? GOLD : TDIM);

        if (t == 2 && !cfgLoaded) loadQuickControls();
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
                try {
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

                    // 2) bot status + balance + config summary (always — honest state)
                    double bal = 0; boolean bok = false;
                    String exchange = "", mode = "";
                    int coins = 0, trades = 0;
                    String lev = "—", tf = "—";
                    boolean running = botRunning;
                    {
                        ApiClient.Result bs = ApiClient.get(base + "/api/bot/status", ck);
                        if (bs.ok()) {
                            try {
                                JSONObject jb = new JSONObject(bs.body);
                                lastBotStatus = jb;
                                running = jb.optBoolean("running", running);
                                JSONObject st = jb.optJSONObject("bot_status");
                                JSONObject bbal = jb.optJSONObject("balance");
                                JSONObject csm = jb.optJSONObject("config_summary");
                                if (bbal != null && bbal.optBoolean("success", false)) {
                                    bal = bbal.optDouble("balance", 0);
                                    bok = true;
                                    exchange = bbal.optString("exchange", "");
                                    mode = bbal.optBoolean("testnet", true) ? "TESTNET" : "LIVE";
                                }
                                if (st != null) {
                                    // engine TRADING state (process-alive != trading)
                                    running = st.optBoolean("running", running);
                                    trades = st.optInt("trades_today", 0);
                                    if (exchange.isEmpty()) exchange = st.optString("exchange", "");
                                    if (mode.isEmpty()) mode = st.optBoolean("testnet", true) ? "TESTNET" : "LIVE";
                                    JSONArray syms = st.optJSONArray("symbols");
                                    coins = syms == null ? 0 : syms.length();
                                    if (st.optInt("leverage", 0) > 0) lev = st.optInt("leverage", 0) + "x";
                                    String tfs = st.optString("timeframe", "");
                                    if (tfs != null && !tfs.isEmpty()) tf = tfs;
                                }
                                if (csm != null) {
                                    // config summary keeps settings visible even when stopped
                                    if (exchange.isEmpty()) exchange = csm.optString("exchange", "binance");
                                    if (mode.isEmpty()) mode = csm.optBoolean("testnet", false) ? "TESTNET" : "LIVE";
                                    if ("—".equals(lev) && csm.optInt("leverage", 0) > 0)
                                        lev = csm.optInt("leverage", 0) + "x";
                                    if ("—".equals(tf)) {
                                        String t2 = csm.optString("timeframe", "");
                                        if (t2 != null && !t2.isEmpty()) tf = t2;
                                    }
                                    if (!running) coins = csm.optInt("symbols_count", 0);
                                }
                                if (!running) lastSnapshot = null;
                            } catch (Exception ignored) { }
                        }
                    }

                    // 3) snapshot for home-spark / markets / trade tabs
                    JSONObject snap = null;
                    JSONObject hist = null;
                    boolean wantSnap = running && ((curTab >= 0 && curTab <= 2)
                            || (curTab == 2 && curSeg == 0));
                    if (wantSnap) {
                        ApiClient.Result sr = ApiClient.get(base + "/api/bot/proxy?path=/api/snapshot", ck);
                        if (sr.ok()) {
                            try {
                                JSONObject js = new JSONObject(sr.body);
                                if (js.has("chart") || js.has("positions")) snap = js;
                            } catch (Exception ignored) { }
                        }
                        if (snap != null) lastSnapshot = snap;
                    }
                    if (curTab == 2 && curSeg == 1) {
                        ApiClient.Result tr = ApiClient.get(base + "/api/bot/proxy?path=/api/trades", ck);
                        if (tr.ok()) {
                            try {
                                JSONObject jt = new JSONObject(tr.body);
                                if (jt.optBoolean("success", false)) hist = jt;
                            } catch (Exception ignored) { }
                        }
                    }

                    // 4) referral data for wallet tab
                    JSONObject ref = null;
                    if (curTab == 3) {
                        ApiClient.Result rr = ApiClient.get(base + "/api/user/referral", ck);
                        if (rr.ok()) {
                            try {
                                JSONObject jr = new JSONObject(rr.body);
                                if (jr.optBoolean("success", false)) ref = jr;
                            } catch (Exception ignored) { }
                        }
                        if (ref != null) lastReferral = ref;
                    }

                    final double fBal = bal; final boolean fBok = bok;
                    final String fEx = exchange, fMode = mode;
                    final int fCoins = coins, fTrades = trades;
                    final String fLev = lev, fTf = tf;
                    final boolean fRun = running;
                    final JSONObject fUser = user, fSub = sub;
                    final JSONObject fSnap = snap, fHist = hist, fRef = (ref != null ? ref : lastReferral);
                    runOnUiThread(new Runnable() {
                        public void run() {
                            try {
                                ticking = false;
                                renderCommon(fUser, fSub, fRun, fBal, fBok, fEx, fMode, fCoins, fTrades, fLev, fTf);
                                if (fSnap != null) {
                                    if (tab == 0) renderHomeSpark(fSnap);
                                    if (tab == 0) renderHomeCoins(fSnap, fRun);
                                    if (tab == 1) renderMarkets(fSnap);
                                    if (tab == 2) renderTrade(fSnap);
                                    if (tab == 2 && seg == 0) renderPositions(fSnap);
                                } else {
                                    if (tab == 0) renderHomeCoins(null, fRun);
                                    if (tab == 1) renderMarketsEmpty(fRun);
                                    if (tab == 2) {
                                        chart.setData(null, null);
                                        tvTradePrice.setText("—");
                                        tvTradeChg.setText("");
                                        tvEmaLegend.setText("EMA 8 —  •  EMA 13 —  •  EMA 21 —  •  EMA 55 —");
                                        llTrades.removeAllViews();
                                        if (!fRun) llTrades.addView(emptyNote(
                                                "Press START — live prices, signals and positions appear here"));
                                    }
                                }
                                if (tab == 2 && seg == 1) {
                                    if (fHist != null) renderHistory(fHist);
                                    else llTrades.removeAllViews();
                                } else if (fHist != null && tab == 2 && seg == 1) {
                                    renderHistory(fHist);
                                }
                                if (tab == 3 && fRef != null) renderWallet(fRef);
                                scheduleTick();
                            } catch (Throwable t) {
                                try { CrashLog.save(t); } catch (Exception ignore) { }
                                ticking = false;
                                scheduleTick();
                            }
                        }
                    });
                } catch (Throwable t) {
                    try { CrashLog.save(t); } catch (Exception ignore) { }
                    runOnUiThread(new Runnable() {
                        public void run() {
                            ticking = false;
                            scheduleTick();
                        }
                    });
                }
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
        // honest control: while running only STOP, otherwise START
        btnStart.setVisibility(running ? View.GONE : View.VISIBLE);
        btnStop.setVisibility(running ? View.VISIBLE : View.GONE);
        if (bok) {
            tvBalance.setText(String.format(Locale.US, "$%.2f", bal));
            tvBalanceSub.setText((ex.isEmpty() ? "" : ex.toUpperCase(Locale.US) + "  •  ") + mode);
            lastBalance = bal; balOk = true;
        } else {
            tvBalance.setText("$0.00");
            tvBalanceSub.setText(running ? "Exchange balance unavailable"
                    : (ex.isEmpty() ? "" : ex.toUpperCase(Locale.US) + "  •  ") + mode
                    + "  —  balance appears after START");
            balOk = false;
        }
        // honest diagnostics: running but no data = exchange/connection issue
        boolean warn = running && (!bok || coins == 0);
        if (cardWarn != null) {
            cardWarn.setVisibility(warn ? View.VISIBLE : View.GONE);
            if (warn) {
                if (!bok) {
                    tvWarn.setText("Can't reach the exchange — verify your API keys in Bot Settings");
                } else {
                    tvWarn.setText("Engine is running but no coin is live — check coins in Bot Settings");
                }
            }
        }
        tvCoins.setText(coins > 0 ? String.valueOf(coins) : (running ? "0" : "—"));
        tvTrades.setText(running ? String.valueOf(trades) : "—");
        tvLev.setText(lev);
        tvTf.setText(tf);
        tvMode.setText((ex.isEmpty() ? "" : ex.toUpperCase(Locale.US) + " " + mode + "  •  ")
                + "EMA 8/13/21/55  •  strict 1:1 RR");
        String t = new SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date());
        tvUpdated.setText("Updated  " + t);
        if (tvUpdatedTrade != null) tvUpdatedTrade.setText("Updated  " + t);

        if (tvTradeLevBadge != null && !"—".equals(lev)) tvTradeLevBadge.setText(lev);

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

    /** Home hero sparkline — active/first symbol's last closes. */
    private void renderHomeSpark(JSONObject snap) {
        try {
            JSONObject c = snap.optJSONObject("chart");
            if (c == null || c.length() == 0) { sparkHome.setCloses(null); return; }
            String sym = snap.optString("active_symbol", "");
            if (sym == null || sym.isEmpty() || !c.has(sym)) {
                List<String> ks = sortedKeys(c);
                sym = ks.isEmpty() ? null : ks.get(0);
            }
            if (sym == null) { sparkHome.setCloses(null); return; }
            JSONObject cd = c.optJSONObject(sym);
            sparkHome.setCloses(cd == null ? null : cd.optJSONArray("candles"));
        } catch (Exception e) {
            sparkHome.setCloses(null);
        }
    }

    /** Active Coins list — real per-symbol signal + price from engine snapshot. */
    private void renderHomeCoins(JSONObject snap, boolean running) {
        try {
            llHomeCoins.removeAllViews();
            JSONObject ind = snap == null ? null : snap.optJSONObject("indicators");
            JSONObject chartO = snap == null ? null : snap.optJSONObject("chart");
            List<String> syms = sortedKeys(chartO);
            JSONObject csm = lastBotStatus == null ? null : lastBotStatus.optJSONObject("config_summary");

            if (!running) {
                // configured coins shown as STANDBY (from config_summary)
                JSONArray cfgSyms = csm == null ? null : csm.optJSONArray("symbols");
                if (cfgSyms != null && cfgSyms.length() > 0) {
                    for (int i = 0; i < cfgSyms.length() && i < 6; i++) {
                        llHomeCoins.addView(coinRow(cfgSyms.optString(i, ""),
                                "", 0, "STANDBY", TSEC, false));
                    }
                } else {
                    llHomeCoins.addView(emptyNote(
                            "No coins configured yet — add coins in Bot Settings, then press START"));
                }
                return;
            }

            if (syms.isEmpty()) {
                llHomeCoins.addView(emptyNote("Loading live market data…"));
                return;
            }
            for (String sym : syms) {
                JSONObject cd = chartO.optJSONObject(sym);
                JSONArray candles = cd == null ? null : cd.optJSONArray("candles");
                double last = 0, prev = 0;
                if (candles != null && candles.length() >= 2) {
                    last = candles.getJSONObject(candles.length() - 1).optDouble("close", 0);
                    prev = candles.getJSONObject(candles.length() - 2).optDouble("close", last);
                }
                double chg = prev != 0 ? (last - prev) / prev * 100.0 : 0;
                JSONObject ii = ind == null ? null : ind.optJSONObject(sym);
                String signal = ii == null ? "HOLD" : ii.optString("signal", "HOLD");
                int col = signal.equals("BUY") ? GREEN : (signal.equals("SELL") ? RED : TSEC);
                llHomeCoins.addView(coinRow(sym,
                        String.format(Locale.US, "$%.2f", last), chg, signal, col, true));
            }
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
        }
    }

    private LinearLayout coinRow(String sym, String price, double chg, String signal,
                                 int sigCol, boolean live) {
        LinearLayout row = new LinearLayout(this);
        row.setLayoutParams(lp(-1, -2, 0, 0, 0, 8));
        row.setBackgroundResource(R.drawable.bg_card);
        row.setPadding(dp(14), dp(12), dp(14), dp(12));
        row.setGravity(Gravity.CENTER_VERTICAL);

        LinearLayout left = new LinearLayout(this);
        left.setOrientation(LinearLayout.VERTICAL);
        left.setLayoutParams(lp(0, -2, 1f, 0, 0, 0));
        TextView tSym = tv(sym, 14, true, TPRI);
        left.addView(tSym);
        if (live) {
            TextView tSub = tv(price + (chg == 0 ? "" : String.format(Locale.US, "   %+.2f%%", chg)),
                    12, true, chg >= 0 ? GREEN : RED);
            applyFont(tSub, fNum);
            left.addView(tSub);
        } else {
            left.addView(tv("waiting for engine start", 11, false, TDIM));
        }

        TextView badge = tv(signal, 11, true, sigCol);
        badge.setBackgroundResource(R.drawable.bg_chip);
        badge.setPadding(dp(10), dp(4), dp(10), dp(4));
        row.addView(left);
        row.addView(badge);
        return row;
    }

    private void renderMarketsEmpty(boolean running) {
        llMarketsEmpty(running);
    }

    private void llMarketsEmpty(boolean running) {
        LinearLayout ll = findViewById(R.id.llMarkets);
        ll.removeAllViews();
        ll.addView(emptyNote(running
                ? "Loading market data…"
                : "Press START — live markets will appear here"));
    }

    private void renderMarkets(JSONObject snap) {
        try {
            JSONObject c = snap.optJSONObject("chart");
            if (c == null) { renderMarketsEmpty(true); return; }
            List<String> syms = sortedKeys(c);
            LinearLayout ll = findViewById(R.id.llMarkets);
            ll.removeAllViews();
            if (syms.isEmpty()) { renderMarketsEmpty(true); return; }
            for (String sym : syms) {
                JSONObject cd = c.optJSONObject(sym);
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
                ll.addView(row);
            }
        } catch (Exception e) {
            renderMarketsEmpty(true);
        }
    }

    /** Trade tab: symbol chips + price + chart + EMA legend + signal. */
    private void renderTrade(JSONObject snap) {
        try {
            JSONObject chartData = snap.optJSONObject("chart");
            if (chartData == null) return;
            List<String> syms = sortedKeys(chartData);
            if (activeSymbol == null || !syms.contains(activeSymbol)) {
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
                    public void onClick(View v) { activeSymbol = s; renderTrade(lastSnapshot); }
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
            JSONArray candles = cd.optJSONArray("candles");
            chart.setData(candles, cd.optJSONObject("emas"));

            // price header
            double last = 0, prev = 0;
            if (candles != null && candles.length() >= 2) {
                last = candles.getJSONObject(candles.length() - 1).optDouble("close", 0);
                prev = candles.getJSONObject(candles.length() - 2).optDouble("close", last);
            }
            double chg = prev != 0 ? (last - prev) / prev * 100.0 : 0;
            tvTradePrice.setText(last > 0 ? String.format(Locale.US, "$%,.2f", last) : "—");
            tvTradeChg.setText(last > 0 ? String.format(Locale.US, "%s%.2f%%  1 candle", chg >= 0 ? "+" : "", chg) : "");
            tvTradeChg.setTextColor(chg >= 0 ? GREEN : RED);

            // indicators + legend + signal
            JSONObject ind = snap.optJSONObject("indicators");
            JSONObject ii = ind == null ? null : ind.optJSONObject(activeSymbol);
            String signal = ii == null ? "HOLD" : ii.optString("signal", "HOLD");
            int sigCol = signal.equals("BUY") ? GREEN : (signal.equals("SELL") ? RED : TSEC);
            tvSignal.setText(signal);
            tvSignal.setTextColor(sigCol);

            if (ii != null) {
                tvEmaLegend.setText(String.format(Locale.US,
                        "EMA 8 %s  •  EMA 13 %s  •  EMA 21 %s  •  EMA 55 %s",
                        num(ii.optDouble("ema_8", Double.NaN)),
                        num(ii.optDouble("ema_13", Double.NaN)),
                        num(ii.optDouble("ema_21", Double.NaN)),
                        num(ii.optDouble("ema_55", Double.NaN))));
            }
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
        }
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
                    final String sym = p.optString("symbol", "");

                    LinearLayout card = new LinearLayout(this);
                    card.setOrientation(LinearLayout.VERTICAL);
                    card.setLayoutParams(lp(-1, -2, 0, 0, 0, 10));
                    card.setBackgroundResource(R.drawable.bg_card);
                    card.setPadding(dp(16), dp(14), dp(16), dp(14));

                    LinearLayout h = new LinearLayout(this);
                    h.setGravity(Gravity.CENTER_VERTICAL);
                    TextView tSym = tv(sym, 14, true, TPRI);
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
                    TextView pnlL = tv("Unrealized PnL", 12, true, TSEC);
                    pnlL.setLayoutParams(lp(0, -2, 1f, dp(8), 0, 0));
                    pnlV.setTextColor(col);
                    LinearLayout pr = new LinearLayout(this);
                    pr.setGravity(Gravity.CENTER_VERTICAL);
                    pr.addView(pnlL);
                    pr.addView(pnlV);

                    Button btnClose = new Button(this);
                    btnClose.setText("CLOSE");
                    btnClose.setTextSize(11);
                    btnClose.setTextColor(RED);
                    btnClose.setBackgroundResource(R.drawable.btn_red_outline);
                    btnClose.setStateListAnimator(null);
                    btnClose.setAllCaps(true);
                    LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(-2, dp(36));
                    clp.leftMargin = dp(10);
                    btnClose.setLayoutParams(clp);
                    btnClose.setOnClickListener(new View.OnClickListener() {
                        public void onClick(View v) { confirmClose(sym); }
                    });
                    pr.addView(btnClose);

                    card.addView(pr);
                    llTrades.addView(card);
                }
            }
            if (!any) llTrades.addView(emptyNote(
                    "No open positions — the bot is waiting for a fresh EMA crossover"));
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
            llTrades.addView(emptyNote("Couldn't load positions"));
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
            if (shown == 0) llTrades.addView(emptyNote("No closed trades yet"));
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
            llTrades.addView(emptyNote("Couldn't load history"));
        }
    }

    /** Wallet tab — real referral data. */
    private void renderWallet(JSONObject ref) {
        try {
            double avail = ref.optDouble("available_balance", 0);
            double earned = ref.optDouble("referral_earnings", 0);
            double withdrawn = ref.optDouble("total_withdrawn", 0);
            double pending = ref.optDouble("pending_payout", 0);
            int count = ref.optInt("referral_count", 0);
            String link = ref.optString("referral_link", "");
            JSONObject rates = ref.optJSONObject("bonus_rates");

            applyFont(tvWalletBalance, fNum);
            tvWalletBalance.setText(String.format(Locale.US, "$%.2f", avail));
            tvWalletSub.setText(String.format(Locale.US,
                    "Lifetime earnings $%.2f  •  Withdrawn $%.2f", earned, withdrawn));
            tvWalletPending.setVisibility(pending > 0 ? View.VISIBLE : View.GONE);
            if (pending > 0) {
                tvWalletPending.setText(String.format(Locale.US,
                        "Pending payout: $%.2f (under review)", pending));
            }
            if (link.length() > 0) tvRefLink.setText(link.replace("https://", "").replace("http://", ""));
            tvRefCount.setText(String.valueOf(count));
            tvRefEarned.setText(String.format(Locale.US, "$%.2f", earned));
            double rY = rates == null ? 10 : rates.optDouble("yearly", 10);
            double rL = rates == null ? 50 : rates.optDouble("lifetime", 50);
            tvRateYearly.setText(String.format(Locale.US, "+$%.2f", rY));
            tvRateLifetime.setText(String.format(Locale.US, "+$%.2f", rL));
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
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

    // ---------- Quick controls (real /api/bot/config) ----------

    private void setDir(int d) {
        dir = d;
        segDirLong.setBackgroundResource(d == 0 ? R.drawable.bg_seg_active : R.drawable.bg_seg);
        segDirShort.setBackgroundResource(d == 1 ? R.drawable.bg_seg_active : R.drawable.bg_seg);
        segDirBoth.setBackgroundResource(d == 2 ? R.drawable.bg_seg_active : R.drawable.bg_seg);
    }

    private void loadQuickControls() {
        final String base = session.server(), ck = session.cookie();
        new Thread(new Runnable() {
            public void run() {
                ApiClient.Result r = ApiClient.get(base + "/api/bot/config", ck);
                JSONObject cfg = null;
                try {
                    cfg = new JSONObject(r.body).optJSONObject("config");
                } catch (Exception ignore) { }
                if (cfg == null) return;
                final JSONObject fCfg = cfg;
                runOnUiThread(new Runnable() {
                    public void run() {
                        try {
                            String am = fCfg.optString("amount_mode", "fixed");
                            double amt = fCfg.optDouble("amount", 100);
                            double lev = fCfg.optDouble("leverage", 20);
                            double sl = fCfg.optDouble("stop_loss_pct", 2.5);
                            String m = fCfg.optString("mode", "both");
                            if (amt > 0) etSize.setText(trimNum(amt));
                            if (lev > 0) etLev.setText(trimNum(lev));
                            if (sl > 0) etSl.setText(trimNum(sl));
                            setDir("long".equals(m) ? 0 : ("short".equals(m) ? 1 : 2));
                            cfgLoaded = true;
                        } catch (Exception ignore) { }
                    }
                });
            }
        }).start();
    }

    private void applyQuickControls() {
        String sSize = etSize.getText().toString().trim();
        String sLev = etLev.getText().toString().trim();
        String sSl = etSl.getText().toString().trim();
        double amt, lev, sl;
        try { amt = Double.parseDouble(sSize); } catch (Exception e) { amt = 0; }
        try { lev = Double.parseDouble(sLev); } catch (Exception e) { lev = 0; }
        try { sl = Double.parseDouble(sSl); } catch (Exception e) { sl = 0; }
        if (amt <= 0) { toastMsg("Order size must be a positive number"); return; }
        if (lev < 1 || lev > 125) { toastMsg("Leverage must be between 1x and 125x"); return; }
        if (sl < 0.5 || sl > 50) { toastMsg("Stop Loss must be between 0.5% and 50%"); return; }

        try {
            JSONObject body = new JSONObject();
            body.put("amount_mode", "fixed");
            body.put("amount", amt);
            body.put("leverage", (int) lev);
            body.put("stop_loss_pct", sl);
            body.put("mode", dir == 0 ? "long" : (dir == 1 ? "short" : "both"));

            applying = true;
            btnApply.setEnabled(false);
            btnApply.setAlpha(0.55f);
            btnApply.setText("Saving…");
            tvApplyMsg.setVisibility(View.GONE);
            final String payload = body.toString();
            final String base = session.server(), ck = session.cookie();
            new Thread(new Runnable() {
                public void run() {
                    final ApiClient.Result r = ApiClient.post(base + "/api/bot/config", payload, ck);
                    runOnUiThread(new Runnable() {
                        public void run() {
                            applying = false;
                            btnApply.setEnabled(true);
                            btnApply.setAlpha(1f);
                            btnApply.setText("Apply & Save");
                            boolean ok = false;
                            String emsg = "Save failed — please try again";
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
                            tvApplyMsg.setVisibility(View.VISIBLE);
                            if (ok) {
                                playSfx(sTap);
                                tvApplyMsg.setTextColor(GREEN);
                                tvApplyMsg.setText("Saved — the engine will use these on its next entries");
                            } else {
                                playSfx(sErr);
                                tvApplyMsg.setTextColor(RED);
                                tvApplyMsg.setText(emsg);
                            }
                        }
                    });
                }
            }).start();
        } catch (Throwable t) {
            try { CrashLog.save(t); } catch (Exception ignore) { }
            toastMsg("Something looked wrong — check the fields");
        }
    }

    // ---------- Wallet actions ----------

    private void copyRefLink() {
        try {
            String link = tvRefLink.getText().toString().trim();
            if (link.length() == 0) { toastMsg("Link is not loaded yet"); return; }
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("Weexionic referral", link));
            playSfx(sTap);
            Toast.makeText(this, "Link copied — share it anywhere", Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            toastMsg("Couldn't copy — long-press the link instead");
        }
    }

    private void shareReferral(String app) {
        try {
            String link = session.server() + "/?ref="
                    + (lastReferral != null ? lastReferral.optString("referral_code", "") : "");
            String text = "Automated futures trading with military-grade 1:1 risk discipline — join Weexionic: " + link;
            Uri uri = null;
            if ("whatsapp".equals(app)) {
                uri = Uri.parse("https://wa.me/?text=" + android.net.Uri.encode(text));
            } else if ("telegram".equals(app)) {
                uri = Uri.parse("https://t.me/share/url?url="
                        + android.net.Uri.encode(link) + "&text=" + android.net.Uri.encode(text));
            }
            Intent i = new Intent(Intent.ACTION_VIEW, uri);
            startActivity(i);
        } catch (Throwable t) {
            // fallback: generic share sheet
            try {
                Intent s = new Intent(Intent.ACTION_SEND);
                s.setType("text/plain");
                s.putExtra(Intent.EXTRA_TEXT, "Join me on Weexionic — " + tvRefLink.getText().toString());
                startActivity(Intent.createChooser(s, "Share invite"));
            } catch (Exception ignore) { }
        }
    }

    // ---------- Session / lifecycle helpers ----------

    private void expire() {
        runOnUiThread(new Runnable() {
            public void run() {
                Toast.makeText(MainActivity.this, "Session expired — please log in again", Toast.LENGTH_LONG).show();
                toLogin();
            }
        });
    }

    /** 401 ran out — try silent relogin first (Remember me), else login screen. */
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
        return tv(v, 12, true, TPRI);
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

    private void toastMsg(String m) {
        Toast.makeText(this, m, Toast.LENGTH_LONG).show();
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

    private static String num(double v) {
        if (v != v) return "—";
        if (Math.abs(v) >= 1000) return String.format(Locale.US, "%,.0f", v);
        return String.format(Locale.US, "%.2f", v);
    }

    private static String trimNum(double v) {
        if (v == Math.floor(v)) return String.valueOf((long) v);
        return String.valueOf(v);
    }

    // ---------- Actions ----------

    private void confirmBot(final boolean start) {
        AlertDialog d = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle(start ? "Start Bot?" : "Stop Bot?")
            .setMessage(start
                ? "The engine will start trading with your saved settings (coins, leverage, order size)."
                : "The bot will stop. Open positions stay open — you can close them from the Trade tab.")
            .setPositiveButton(start ? "START" : "STOP", new DialogInterface.OnClickListener() {
                public void onClick(DialogInterface di, int w) { botAction(start); }
            })
            .setNegativeButton("CANCEL", null)
            .show();
        d.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(GOLD);
        d.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(TSEC);
    }

    /** START failed because of config — offer Bot Settings directly. */
    private void showSettingsNeeded(String why) {
        AlertDialog d = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle("Settings Required")
            .setMessage(why + "\n\nOpen Bot Settings now?")
            .setPositiveButton("BOT SETTINGS", new DialogInterface.OnClickListener() {
                public void onClick(DialogInterface di, int w) {
                    startActivity(new Intent(MainActivity.this, SettingsActivity.class));
                }
            })
            .setNegativeButton("LATER", null)
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
                        if (ok) {
                            Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
                            if (start) verifyStart();
                        } else {
                            // config issue → offer Settings directly (never a silent no-op)
                            String low = msg == null ? "" : msg.toLowerCase();
                            boolean cfgIssue = low.contains("api key") || low.contains("coin")
                                    || low.contains("passphrase") || low.contains("settings")
                                    || low.contains("license");
                            if (cfgIssue) {
                                showSettingsNeeded(msg);
                            } else {
                                Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
                            }
                        }
                        ticking = false;
                        tickNow();
                    }
                });
            }
        }).start();
    }

    /** After START: confirm the engine REALLY reached trading state (honest, no fake). */
    private void verifyStart() {
        final String base = session.server(), ck = session.cookie();
        new Thread(new Runnable() {
            public void run() {
                boolean really = false;
                int coins = 0;
                for (int i = 0; i < 5 && !really; i++) {
                    try { Thread.sleep(2000); } catch (Exception ignore) { }
                    ApiClient.Result s = ApiClient.get(base + "/api/bot/status", ck);
                    try {
                        JSONObject jb = new JSONObject(s.body);
                        really = jb.optBoolean("running", false);
                        JSONObject st = jb.optJSONObject("bot_status");
                        JSONArray syms = st == null ? null : st.optJSONArray("symbols");
                        coins = syms == null ? 0 : syms.length();
                    } catch (Exception ignore) { }
                }
                final boolean fReally = really;
                final int fCoins = coins;
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (!fReally) {
                            Toast.makeText(MainActivity.this,
                                "Start accepted but engine is still booting — status will update in a few seconds",
                                Toast.LENGTH_LONG).show();
                        } else if (fCoins == 0) {
                            Toast.makeText(MainActivity.this,
                                "Bot is RUNNING — add coins in Bot Settings to begin trading",
                                Toast.LENGTH_LONG).show();
                        } else {
                            Toast.makeText(MainActivity.this,
                                "Bot is RUNNING — watching " + fCoins + " coin"
                                    + (fCoins == 1 ? "" : "s") + " for fresh signals",
                                Toast.LENGTH_LONG).show();
                        }
                    }
                });
            }
        }).start();
    }

    private void confirmClose(final String sym) {
        AlertDialog d = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle("Close Position?")
            .setMessage("Market-close the " + sym + " position on the exchange now?")
            .setPositiveButton("CLOSE", new DialogInterface.OnClickListener() {
                public void onClick(DialogInterface di, int w) { closePosition(sym); }
            })
            .setNegativeButton("CANCEL", null)
            .show();
        d.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(RED);
        d.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(TSEC);
    }

    private void closePosition(final String sym) {
        if (sym == null || sym.length() == 0) return;
        toastMsg("Closing " + sym + "…");
        new Thread(new Runnable() {
            public void run() {
                String b = "{}";
                try { b = new JSONObject().put("symbol", sym).toString(); } catch (Exception ignore) { }
                final ApiClient.Result r = ApiClient.post(
                        session.server() + "/api/bot/proxy?path=/api/close", b, session.cookie());
                runOnUiThread(new Runnable() {
                    public void run() {
                        String msg = "Close request sent";
                        boolean ok = false;
                        try {
                            JSONObject jo = new JSONObject(r.body);
                            ok = r.ok() && jo.optBoolean("success", false);
                            msg = ok ? (sym + " closed") : jo.optString("error", msg);
                        } catch (Exception e) {
                            if (r.error != null) msg = r.error;
                        }
                        playSfx(ok ? sStop : sErr);
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
            .setMessage("Logging out also STOPS your bot on the server. Continue?")
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
