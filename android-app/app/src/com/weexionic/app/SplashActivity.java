package com.weexionic.app;

import android.app.Activity;
import android.animation.ValueAnimator;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.widget.ImageView;

/** Branded splash with pulsing logo; routes to Main (session) or Login. */
public class SplashActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.splash);

        ImageView logo = findViewById(R.id.imgSplashLogo);
        ValueAnimator pulse = ValueAnimator.ofFloat(1f, 1.08f, 1f);
        pulse.setDuration(1100);
        pulse.setRepeatCount(ValueAnimator.INFINITE);
        pulse.setInterpolator(new AccelerateDecelerateInterpolator());
        pulse.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            public void onAnimationUpdate(ValueAnimator a) {
                float s = (Float) a.getAnimatedValue();
                logo.setScaleX(s);
                logo.setScaleY(s);
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
