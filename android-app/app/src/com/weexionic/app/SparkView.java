package com.weexionic.app;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.util.AttributeSet;
import android.view.View;

import org.json.JSONArray;

/** Tiny native sparkline (last closes) for market rows. */
public class SparkView extends View {

    private final Paint pLine = new Paint(Paint.ANTI_ALIAS_FLAG);
    private double[] vals = null;

    public SparkView(Context c) { this(c, null); }
    public SparkView(Context c, AttributeSet a) { this(c, a, 0); }
    public SparkView(Context c, AttributeSet a, int st) {
        super(c, a, st);
        pLine.setStyle(Paint.Style.STROKE);
        pLine.setStrokeWidth(2.2f);
        pLine.setStrokeCap(Paint.Cap.ROUND);
        pLine.setStrokeJoin(Paint.Join.ROUND);
    }

    public void setCloses(JSONArray candles) {
        try {
            int n = candles == null ? 0 : candles.length();
            int take = Math.min(n, 40);
            if (take < 2) { vals = null; invalidate(); return; }
            vals = new double[take];
            for (int i = 0; i < take; i++) {
                vals[i] = candles.getJSONObject(n - take + i).optDouble("close", 0);
            }
            boolean upTrend = vals[take - 1] >= vals[0];
            pLine.setColor(upTrend ? 0xFF2EBD85 : 0xFFF6465D);
            invalidate();
        } catch (Exception e) {
            vals = null;
            invalidate();
        }
    }

    @Override
    protected void onDraw(Canvas cv) {
        super.onDraw(cv);
        if (vals == null || vals.length < 2 || getWidth() < 10) return;
        double mn = Double.MAX_VALUE, mx = -Double.MAX_VALUE;
        for (double v : vals) { if (v < mn) mn = v; if (v > mx) mx = v; }
        double r = (mx - mn);
        if (r <= 0) r = 1;
        float pad = 4f;
        float W = getWidth() - pad * 2, H = getHeight() - pad * 2;
        Path path = new Path();
        for (int i = 0; i < vals.length; i++) {
            float x = pad + W * i / (vals.length - 1);
            float y = (float) (pad + (1 - (vals[i] - mn) / r) * H);
            if (i == 0) path.moveTo(x, y); else path.lineTo(x, y);
        }
        cv.drawPath(path, pLine);
    }
}
