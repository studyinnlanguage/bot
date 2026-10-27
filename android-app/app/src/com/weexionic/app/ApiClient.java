package com.weexionic.app;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/** Minimal JSON HTTP client on HttpURLConnection (no external deps). */
public class ApiClient {

    public static class Result {
        public int code = 0;
        public String body = "";
        public String setCookie = "";
        public String error = null;
        public boolean ok() { return error == null && code >= 200 && code < 300; }
    }

    private static final int CONNECT_TIMEOUT = 12000;
    private static final int READ_TIMEOUT = 15000;

    public static Result request(String url, String method, String jsonBody, String cookie) {
        Result r = new Result();
        HttpURLConnection conn = null;
        try {
            URL u = new URL(url);
            conn = (HttpURLConnection) u.openConnection();
            conn.setConnectTimeout(CONNECT_TIMEOUT);
            conn.setReadTimeout(READ_TIMEOUT);
            conn.setRequestMethod(method);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("User-Agent", "WeexionicApp/3.2 (Android)");
            if (cookie != null && cookie.length() > 0) {
                conn.setRequestProperty("Cookie", cookie);
            }
            if (jsonBody != null) {
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                conn.setDoOutput(true);
                OutputStream os = conn.getOutputStream();
                os.write(jsonBody.getBytes(StandardCharsets.UTF_8));
                os.flush();
                os.close();
            }
            r.code = conn.getResponseCode();
            InputStream is = (r.code >= 200 && r.code < 400) ? conn.getInputStream() : conn.getErrorStream();
            if (is != null) {
                StringBuilder sb = new StringBuilder();
                BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
                String line;
                while ((line = br.readLine()) != null) sb.append(line).append('\n');
                br.close();
                r.body = sb.toString();
            }
            Map<String, List<String>> hdrs = conn.getHeaderFields();
            if (hdrs != null) {
                List<String> sc = hdrs.get("set-cookie");
                if (sc == null) sc = hdrs.get("Set-Cookie");
                if (sc != null && !sc.isEmpty()) {
                    String first = sc.get(0);
                    int semi = first.indexOf(';');
                    r.setCookie = (semi > 0 ? first.substring(0, semi) : first).trim();
                }
            }
        } catch (Exception e) {
            r.error = friendly(e);
        } finally {
            if (conn != null) conn.disconnect();
        }
        return r;
    }

    public static Result get(String url, String cookie) {
        return request(url, "GET", null, cookie);
    }

    public static Result post(String url, String json, String cookie) {
        return request(url, "POST", json == null ? "{}" : json, cookie);
    }

    /** Extract host(:port) for display. */
    public static String hostOf(String server) {
        try {
            URL u = new URL(server);
            int port = u.getPort();
            if (port > 0) return u.getHost() + ":" + port;
            return u.getHost();
        } catch (Exception e) {
            return server;
        }
    }

    private static String friendly(Exception e) {
        String m = String.valueOf(e.getMessage());
        if (m == null) m = "";
        if (m.contains("UnknownHost") || m.contains("resolve")) return "Server not found — check your internet connection";
        if (m.contains("timeout") || m.contains("Timeout")) return "Connection timed out — please try again";
        if (m.contains("Connect")) return "Could not reach the server";
        return "Network error: " + m;
    }
}
