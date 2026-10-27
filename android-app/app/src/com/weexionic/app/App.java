package com.weexionic.app;

import android.app.Application;
import android.content.Context;

/**
 * Application-level crash guard: any uncaught exception is logged to
 * crash_last.txt (private storage) before the system handles it, so
 * "Weexionic has stopped" reports always come with a trace we can read.
 */
public class App extends Application {

    private static Context appCtx;

    public static Context ctx() { return appCtx; }

    @Override
    public void onCreate() {
        super.onCreate();
        appCtx = getApplicationContext();
        final Thread.UncaughtExceptionHandler system =
                Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
            @Override
            public void uncaughtException(Thread thread, Throwable throwable) {
                try { CrashLog.save(throwable); } catch (Throwable ignore) { }
                if (system != null) system.uncaughtException(thread, throwable);
            }
        });
    }
}
