package com.weexionic.app;

import android.content.Context;
import android.content.SharedPreferences;

/** Tiny session/prefs store for Weexionic app. */
public class Session {
    /**
     * Production server — baked into the app. Binance-grade UX: the user NEVER
     * types a server address (v3.4 change: SERVER SETTINGS removed from login).
     */
    public static final String DEFAULT_SERVER = "https://weexionic.duckdns.org";

    private static final String PREFS = "weexionic";
    private static final String K_SERVER = "server";
    private static final String K_COOKIE = "cookie";
    private static final String K_EMAIL = "email";
    private static final String K_NAME = "name";
    private static final String K_PLAN = "plan";
    private static final String K_EXPIRY = "expiry";
    private static final String K_PASSX = "passx";
    private static final String K_REMEMBER = "remember";

    private final SharedPreferences p;

    public Session(Context c) {
        p = c.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        // Auto-bake the production server on first run (and after reinstalls).
        if (server().trim().length() == 0) server(DEFAULT_SERVER);
    }

    public String server() { return p.getString(K_SERVER, ""); }
    public void server(String v) { p.edit().putString(K_SERVER, v).apply(); }

    public String cookie() { return p.getString(K_COOKIE, ""); }
    public void cookie(String v) { p.edit().putString(K_COOKIE, v).apply(); }

    public String email() { return p.getString(K_EMAIL, ""); }
    public void email(String v) { p.edit().putString(K_EMAIL, v).apply(); }

    public String name() { return p.getString(K_NAME, ""); }
    public void name(String v) { p.edit().putString(K_NAME, v).apply(); }

    public String plan() { return p.getString(K_PLAN, ""); }
    public void plan(String v) { p.edit().putString(K_PLAN, v).apply(); }

    public String expiry() { return p.getString(K_EXPIRY, ""); }
    public void expiry(String v) { p.edit().putString(K_EXPIRY, v).apply(); }

    public boolean hasServer() { return server().trim().length() > 0; }
    public boolean hasSession() { return hasServer() && cookie().length() > 0; }

    public boolean remember() { return p.getBoolean(K_REMEMBER, true); }
    public void remember(boolean v) { p.edit().putBoolean(K_REMEMBER, v).apply(); }

    /** Obfuscated (XOR+Base64) password for silent auto-relogin. Private-mode prefs only. */
    public String savedPass() {
        String s = p.getString(K_PASSX, "");
        if (s == null || s.length() == 0) return "";
        try {
            byte[] b = android.util.Base64.decode(s, android.util.Base64.NO_WRAP);
            byte[] k = "WeexionicSfx".getBytes("UTF-8");
            for (int i = 0; i < b.length; i++) b[i] ^= k[i % k.length];
            return new String(b, "UTF-8");
        } catch (Exception e) { return ""; }
    }

    public void savedPass(String v) {
        try {
            if (v == null || v.length() == 0) { p.edit().remove(K_PASSX).apply(); return; }
            byte[] b = v.getBytes("UTF-8");
            byte[] k = "WeexionicSfx".getBytes("UTF-8");
            for (int i = 0; i < b.length; i++) b[i] ^= k[i % k.length];
            p.edit().putString(K_PASSX, android.util.Base64.encodeToString(b, android.util.Base64.NO_WRAP)).apply();
        } catch (Exception e) { }
    }

    public boolean hasSavedLogin() { return email().length() > 0 && savedPass().length() > 0; }

    public void logout() {
        p.edit().remove(K_COOKIE).remove(K_EMAIL).remove(K_NAME).remove(K_PLAN).remove(K_EXPIRY).apply();
    }

    /** Normalize user-entered server URL: trims, adds scheme, strips trailing slash. */
    public static String normalizeServer(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.length() == 0) return "";
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            s = "http://" + s;
        }
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }
}
