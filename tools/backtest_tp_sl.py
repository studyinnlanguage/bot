"""
Backtest Verification Script:
Validates that EMA Quad Strategy executes with:
- Take Profit (TP) = 1.0%
- Stop Loss (SL)   = 0.2%
"""
import sys
import os
from pathlib import Path
import json
import urllib.request
import pandas as pd
import numpy as np

# Add bot-engine to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot-engine"))

from bot.strategy import EMAQuadStrategy, Signal


def fetch_binance_klines(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "count", "taker_buy_volume",
                "taker_buy_quote_volume", "ignore"
            ])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            return df
    except Exception as e:
        print(f"⚠️ Could not fetch live Binance klines ({e}). Generating realistic market walk...")
        np.random.seed(42)
        n = 1000
        dates = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="5min")
        returns = np.random.normal(0.0001, 0.0025, n)
        price = 68000.0 * np.cumprod(1 + returns)
        high = price * (1 + np.abs(np.random.normal(0.001, 0.001, n)))
        low = price * (1 - np.abs(np.random.normal(0.001, 0.001, n)))
        open_p = price * (1 + np.random.normal(0, 0.0008, n))
        return pd.DataFrame({
            "open_time": dates,
            "open": open_p,
            "high": high,
            "low": low,
            "close": price,
            "volume": np.random.uniform(10, 500, n)
        })


def run_backtest(df, tp_pct=1.0, sl_pct=0.2):
    strat = EMAQuadStrategy(min_spread_pct=0.15, fresh_window=8)
    trades = []
    active_trade = None

    # Warmup with 70 candles so EMA55 is stable
    warmup = 70
    for i in range(warmup, len(df)):
        window = df.iloc[:i+1]
        candle = df.iloc[i]
        result = strat.analyze(window)
        if result is None:
            continue

        # 1) If in active trade, check exit on this candle
        if active_trade is not None:
            side = active_trade["side"]
            entry = active_trade["entry_price"]
            tp = active_trade["tp_price"]
            sl = active_trade["sl_price"]
            high = candle["high"]
            low = candle["low"]

            exit_trade = False
            exit_reason = ""
            exit_price = 0.0

            if side == "LONG":
                # Check SL hit
                if low <= sl:
                    exit_trade = True
                    exit_reason = "⚡ SL HIT (-0.2%)"
                    exit_price = sl
                # Check TP hit
                elif high >= tp:
                    exit_trade = True
                    exit_reason = "🎯 TP HIT (+1.0%)"
                    exit_price = tp
            else:  # SHORT
                # Check SL hit
                if high >= sl:
                    exit_trade = True
                    exit_reason = "⚡ SL HIT (-0.2%)"
                    exit_price = sl
                # Check TP hit
                elif low <= tp:
                    exit_trade = True
                    exit_reason = "🎯 TP HIT (+1.0%)"
                    exit_price = tp

            if exit_trade:
                pnl = ((exit_price - entry) / entry * 100) if side == "LONG" else ((entry - exit_price) / entry * 100)
                active_trade["exit_time"] = candle["open_time"]
                active_trade["exit_price"] = exit_price
                active_trade["exit_reason"] = exit_reason
                active_trade["pnl_pct"] = pnl
                trades.append(active_trade)
                active_trade = None
                strat.reset_cross_state()

        # 2) If no active trade, look for entry signal
        if active_trade is None and result.just_crossed and result.signal in (Signal.BUY, Signal.SELL):
            entry_price = candle["close"]
            if result.signal == Signal.BUY:
                side = "LONG"
                sl_price = entry_price * (1.0 - (sl_pct / 100.0))
                tp_price = entry_price * (1.0 + (tp_pct / 100.0))
            else:
                side = "SHORT"
                sl_price = entry_price * (1.0 + (sl_pct / 100.0))
                tp_price = entry_price * (1.0 - (tp_pct / 100.0))

            active_trade = {
                "id": len(trades) + 1,
                "side": side,
                "entry_time": candle["open_time"],
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "sl_pct_target": sl_pct,
                "tp_pct_target": tp_pct,
            }
            strat.mark_trade_entered()

    return trades


def print_report(trades, title):
    print("=" * 85)
    print(f"  {title}")
    print("=" * 85)
    if not trades:
        print("  No completed trades.")
        return

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    total_pnl = sum(t["pnl_pct"] for t in trades)
    win_rate = (len(wins) / len(trades) * 100) if trades else 0

    print(f"  Total Trades Opened & Closed : {len(trades)}")
    print(f"  Winning Trades (TP Hit)     : {len(wins)} ({win_rate:.1f}%)")
    print(f"  Losing Trades (SL Hit)      : {len(losses)} ({100 - win_rate:.1f}%)")
    print(f"  Total Cumulative PnL         : {total_pnl:+.2f}%")
    print(f"  Target TP Per Win           : +{trades[0]['tp_pct_target']:.2f}%")
    print(f"  Target SL Per Loss          : -{trades[0]['sl_pct_target']:.2f}%")
    print(f"  Reward-to-Risk Ratio        : {trades[0]['tp_pct_target'] / trades[0]['sl_pct_target']:.1f} : 1")
    print("-" * 85)
    print(f"  {'#':<3} {'Side':<6} {'Entry':<12} {'SL (-0.2%)':<14} {'TP (+1.0%)':<14} {'Exit':<12} {'PnL %':<8} {'Outcome'}")
    print("-" * 85)
    for t in trades[:15]:  # print first 15 trades
        print(f"  {t['id']:<3} {t['side']:<6} ${t['entry_price']:<11.2f} ${t['sl_price']:<13.2f} ${t['tp_price']:<13.2f} ${t['exit_price']:<11.2f} {t['pnl_pct']:>+6.2f}%  {t['exit_reason']}")
    if len(trades) > 15:
        print(f"  ... and {len(trades) - 15} more trades.")
    print("=" * 85 + "\n")


if __name__ == "__main__":
    symbol = "BTCUSDT"
    print(f"Fetching real 5-minute candle data for {symbol}...")
    df = fetch_binance_klines(symbol=symbol, interval="5m", limit=1000)
    print(f"Loaded {len(df)} candles from {df['open_time'].iloc[0]} to {df['open_time'].iloc[-1]}.\n")

    # Backtest with New Settings: TP = 1.0%, SL = 0.2%
    trades_new = run_backtest(df, tp_pct=1.0, sl_pct=0.2)
    print_report(trades_new, "BACKTEST REPORT: NEW SETTINGS (TP: 1.0% | SL: 0.2%)")

    # Comparison with Old 1:1 Settings: TP = 1.0%, SL = 1.0%
    trades_old = run_backtest(df, tp_pct=1.0, sl_pct=1.0)
    print_report(trades_old, "BACKTEST REPORT: OLD 1:1 SETTINGS (TP: 1.0% | SL: 1.0%)")
