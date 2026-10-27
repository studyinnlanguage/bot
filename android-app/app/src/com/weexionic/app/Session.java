package com.weexionic.app;

import android.content.Context;
import android.content.SharedPreferences;

/** Tiny session/prefs store for Weexionic app. */
public class Session {
    private static final String PREFS = "weexionic";
    private static final String K_SERVER = "server";
    private static final String K_COOKIE = "cookie";
    private static final String K_EMAIL = "email";
    private static final String K_NAME = "name";
    private static final String K_PLAN = "plan";
    private static final String K_EXPIRY = "expiry";

    private final SharedPreferences p;

    public Session(Context c) {
        p = c.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
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
