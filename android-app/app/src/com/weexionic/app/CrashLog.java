package com.weexionic.app;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;

/** Saves crash traces to app-private storage AND posts them to the SaaS server
 *  (/api/client/crash) so phone-side crashes/errors are visible in VPS logs. */
public class CrashLog {

    /** App version tag attached to every remote report. */
    public static final String VERSION = "v3.6";

    @SuppressWarnings("ResultOfMethodCallIgnored")
    static void save(Throwable t) {
        try {
            Context c = App.ctx();
            if (c == null || t == null) return;
            StringWriter sw = new StringWriter();
            t.printStackTrace(new PrintWriter(sw));
            String trace = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.US)
                    .format(new java.util.Date()) + "\n" + sw + "\n\n";
            File f = new File(c.getFilesDir(), "crash_last.txt");
            FileOutputStream fo = new FileOutputStream(f, true);
            fo.write(trace.getBytes("UTF-8"));
            fo.close();
            // keep the file small: last 20KB
            if (f.length() > 20480) {
                java.io.RandomAccessFile raf = new java.io.RandomAccessFile(f, "rw");
                raf.seek(f.length() - 20480);
                byte[] tail = new byte[20480];
                raf.readFully(tail);
                raf.close();
                FileOutputStream fo2 = new FileOutputStream(f, false);
                fo2.write(tail);
                fo2.close();
            }
            report(null, "crash", trace);
        } catch (Throwable ignore) { }
    }

    /**
     * Fire-and-forget POST of an error/crash trace to the server. Safe to call
     * from any thread (spawns a short daemon thread); never throws.
     */
    public static void report(final Session session, final String tag, final String detail) {
        try {
            Thread th = new Thread(new Runnable() {
                public void run() {
                    try {
                        Context c = App.ctx();
                        if (c == null) return;
                        final Session s = session != null ? session : new Session(c);
                        String server = s.hasServer() ? s.server() : Session.DEFAULT_SERVER;
                        if (server == null || server.length() == 0) return;
                        org.json.JSONObject jo = new org.json.JSONObject();
                        jo.put("kind", tag != null && tag.startsWith("crash") ? "crash" : "error");
                        jo.put("tag", tag + " " + VERSION);
                        jo.put("message", detail == null ? "" : detail);
                        ApiClient.post(server + "/api/client/crash", jo.toString(), s.cookie());
                    } catch (Throwable ignore) { }
                }
            });
            th.setDaemon(true);
            th.start();
            if ("crash".equals(tag)) {
                try { th.join(2500); } catch (InterruptedException ignore) { }
            }
        } catch (Throwable ignore) { }
    }
}
