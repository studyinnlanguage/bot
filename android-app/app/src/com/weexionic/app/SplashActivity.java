package com.weexionic.app;

import android.app.Activity;
import android.animation.ValueAnimator;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.widget.TextView;

/**
 * Branded splash (v3.6: wordmark-only — the badge logo lives ONLY on the login
 * screen, per the user's design brief). Routes to Main (session) or Login.
 */
public class SplashActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.splash);

        TextView title = findViewById(R.id.tvSplashTitle);
        ValueAnimator pulse = ValueAnimator.ofFloat(1f, 1.06f, 1f);
        pulse.setDuration(1100);
        pulse.setRepeatCount(ValueAnimator.INFINITE);
        pulse.setInterpolator(new AccelerateDecelerateInterpolator());
        pulse.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            public void onAnimationUpdate(ValueAnimator a) {
                float s = (Float) a.getAnimatedValue();
                title.setScaleX(s);
                title.setScaleY(s);
            }
        });
        pulse.start();

        new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
            @Override
            public void run() {
                Session s = new Session(SplashActivity.this);
                Intent i = s.hasSession()
                        ? new Intent(SplashActivity.this, MainActivity.class)
                        : new Intent(SplashActivity.this, LoginActivity.class);
                startActivity(i);
                finish();
            }
        }, 1200);
    }
}
