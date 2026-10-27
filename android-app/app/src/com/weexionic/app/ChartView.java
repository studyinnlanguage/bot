package com.weexionic.app;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.util.AttributeSet;
import android.view.View;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Native candlestick chart — candles + 4 EMA overlays + grid + price axis.
 * Pure Canvas drawing, zero web tech. Binance Futures style.
 */
public class ChartView extends View {

    private static final int MAX_VISIBLE = 90;

    private final Paint pWickUp = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pWickDn = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pBodyUp = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pBodyDn = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pGrid = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pTextPrice = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pLast = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pTag = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pTagText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint[] pEma = new Paint[4];

    private double[] open, high, low, close;
    private double[][] ema = new double[4][];
    private double min = 0, max = 1;
    private double lastClose = 0;
    private boolean up = true;
    private boolean hasData = false;

    private static final int[] EMA_COLORS = {
            0xFFF0B90B, 0xFF4A9EFF, 0xFFB388FF, 0xFFF2F4F7
    };

    public ChartView(Context c) { this(c, null); }

    public ChartView(Context c, AttributeSet a) { this(c, a, 0); }

    public ChartView(Context c, AttributeSet a, int st) {
        super(c, a, st);
        float d = getResources().getDisplayMetrics().density;
        int upC = 0xFF0ECB81, dnC = 0xFFF6465D;
        pWickUp.setColor(upC); pWickUp.setStrokeWidth(Math.max(1f, d));
        pWickDn.setColor(dnC); pWickDn.setStrokeWidth(Math.max(1f, d));
        pBodyUp.setColor(upC);
        pBodyDn.setColor(dnC);
        pGrid.setColor(0xFF161B26); pGrid.setStrokeWidth(d);
        pText.setColor(0xFF5B6472); pText.setTextSize(10f * d);
        pTextPrice.setColor(0xFF8A93A5); pTextPrice.setTextSize(9f * d);
        pLast.setColor(0xFFF2F4F7); pLast.setStrokeWidth(d);
        pLast.setStyle(Paint.Style.STROKE);
        pLast.setPathEffect(new DashPathEffect(new float[]{4 * d, 4 * d}, 0));
        pTag.setColor(0xFFF2F4F7);
        pTagText.setColor(0xFF141414); pTagText.setTextSize(9.5f * d); pTagText.setFakeBoldText(true);
        for (int i = 0; i < 4; i++) {
            pEma[i] = new Paint(Paint.ANTI_ALIAS_FLAG);
            pEma[i].setColor(EMA_COLORS[i]);
            pEma[i].setStrokeWidth(1.4f * d);
            pEma[i].setStyle(Paint.Style.STROKE);
        }
    }

    /** @param emas JSONObject with keys ema8/ema13/ema21/ema55 -> [{time,value}] */
    public void setData(JSONArray candles, JSONObject emas) {
        try {
            int n = candles == null ? 0 : candles.length();
            if (n == 0) { hasData = false; invalidate(); return; }
            int start = Math.max(0, n - MAX_VISIBLE);
            int m = n - start;
            open = new double[m]; high = new double[m]; low = new double[m]; close = new double[m];
            for (int i = 0; i < m; i++) {
                JSONObject c = candles.getJSONObject(start + i);
                open[i] = c.optDouble("open", 0);
                high[i] = c.optDouble("high", 0);
                low[i] = c.optDouble("low", 0);
                close[i] = c.optDouble("close", 0);
            }
            lastClose = close[m - 1];
            up = m > 1 && close[m - 1] >= open[m - 1];

            for (int e = 0; e < 4; e++) ema[e] = null;
            if (emas != null) {
                String[] keys = {"ema8", "ema13", "ema21", "ema55"};
                for (int e = 0; e < 4; e++) {
                    JSONArray arr = emas.optJSONArray(keys[e]);
                    if (arr == null) continue;
                    // keep only points inside the visible window (match by time range)
                    double[] vals = new double[m];
                    boolean[] seen = new boolean[m];
                    // map time -> index
                    java.util.HashMap<Long, Integer> tmap = new java.util.HashMap<Long, Integer>();
                    // need candle times: not stored — approximate by positional tail
                    int n2 = arr.length();
                    int s2 = Math.max(0, n2 - m);
                    for (int i = s2; i < n2; i++) {
                        JSONObject p = arr.getJSONObject(i);
                        vals[i - s2] = p.optDouble("value", Double.NaN);
                        seen[i - s2] = true;
                    }
                    double[] packed = new double[m];
                    for (int i = 0; i < m; i++) packed[i] = seen[i] ? vals[i] : Double.NaN;
                    ema[e] = packed;
                }
            }

            min = Double.MAX_VALUE; max = -Double.MAX_VALUE;
            for (int i = 0; i < m; i++) {
                if (high[i] > max) max = high[i];
                if (low[i] < min) min = low[i];
            }
            for (int e = 0; e < 4; e++) {
                if (ema[e] == null) continue;
                for (int i = 0; i < m; i++) {
                    double v = ema[e][i];
                    if (v == v && v != Double.POSITIVE_INFINITY) {
                        if (v > max) max = v;
                        if (v < min) min = v;
                    }
                }
            }
            double pad = (max - min) * 0.08;
            if (pad <= 0) pad = max * 0.01 + 1;
            min -= pad; max += pad;
            hasData = true;
            invalidate();
        } catch (Exception e) {
            hasData = false;
            invalidate();
        }
    }

    @Override
    protected void onDraw(Canvas cv) {
        super.onDraw(cv);
        int W = getWidth(), H = getHeight();
        float d = getResources().getDisplayMetrics().density;
        cv.drawColor(Color.TRANSPARENT);

        if (!hasData || W < 40 || H < 40) {
            pText.setTextAlign(Paint.Align.CENTER);
            cv.drawText(hasData ? "" : "Press START — the live chart appears here",
                    W / 2f, H / 2f, pText);
            pText.setTextAlign(Paint.Align.LEFT);
            return;
        }

        int m = close.length;
        float axisW = 52f * d;
        float plotW = W - axisW;
        float top = 8f * d, bot = H - 8f * d;
        float range = (float) (max - min);
        if (range <= 0) range = 1;

        // grid + price labels (5 lines)
        pText.setTextAlign(Paint.Align.LEFT);
        for (int g = 0; g <= 4; g++) {
            float y = top + (bot - top) * g / 4f;
            cv.drawLine(0, y, plotW, y, pGrid);
            double price = max - range * g / 4.0;
            cv.drawText(fmt(price), plotW + 5 * d, y + 3.5f * d, pText);
        }

        float slot = plotW / m;
        float bodyW = Math.max(2f, slot * 0.62f);

        for (int i = 0; i < m; i++) {
            float x = slot * i + slot / 2f;
            boolean green = close[i] >= open[i];
            float yH = y(high[i], top, bot, range);
            float yL = y(low[i], top, bot, range);
            float yO = y(open[i], top, bot, range);
            float yC = y(close[i], top, bot, range);
            cv.drawLine(x, yH, x, yL, green ? pWickUp : pWickDn);
            float bTop = Math.min(yO, yC);
            float bH = Math.max(Math.abs(yC - yO), 1.2f * d);
            cv.drawRect(x - bodyW / 2f, bTop, x + bodyW / 2f, bTop + bH,
                    green ? pBodyUp : pBodyDn);
        }

        // EMA overlays
        for (int e = 0; e < 4; e++) {
            if (ema[e] == null) continue;
            Path path = new Path();
            boolean started = false;
            for (int i = 0; i < m; i++) {
                double v = ema[e][i];
                if (v != v) continue; // NaN
                float x = slot * i + slot / 2f;
                float yy = y(v, top, bot, range);
                if (!started) { path.moveTo(x, yy); started = true; }
                else path.lineTo(x, yy);
            }
            if (started) cv.drawPath(path, pEma[e]);
        }

        // last price line + tag
        float yl = y(lastClose, top, bot, range);
        cv.drawLine(0, yl, plotW, yl, pLast);
        String tag = fmt(lastClose);
        float tw = pTagText.measureText(tag);
        pTag.setColor(up ? 0xFF0ECB81 : 0xFFF6465D);
        cv.drawRect(plotW + 1, yl - 9 * d, W - 1, yl + 9 * d, pTag);
        pTagText.setColor(0xFF141414);
        pTagText.setTextAlign(Paint.Align.CENTER);
        cv.drawText(tag, plotW + (axisW - 2 * d) / 2f, yl + 3.5f * d, pTagText);
        pTagText.setTextAlign(Paint.Align.LEFT);
    }

    private float y(double v, float top, float bot, float range) {
        return (float) (top + (max - v) / range * (bot - top));
    }

    private static String fmt(double v) {
        if (v >= 1000) return String.format(java.util.Locale.US, "%.0f", v);
        if (v >= 10) return String.format(java.util.Locale.US, "%.2f", v);
        return String.format(java.util.Locale.US, "%.4f", v);
    }
}
