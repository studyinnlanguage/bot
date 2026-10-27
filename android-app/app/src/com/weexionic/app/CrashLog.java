package com.weexionic.app;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;

/** Saves crash traces to app-private storage so any future "has stopped" can be diagnosed. */
public class CrashLog {

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
        } catch (Throwable ignore) { }
    }
}
