"""
Technical Indicators Module
Calculates Exponential Moving Averages (EMA) for the strategy.
"""
import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA) for a given period.

    Args:
        series: Pandas Series of closing prices.
        period: EMA period (number of candles).

    Returns:
        Pandas Series containing EMA values.
    """
    if len(series) < period:
        return pd.Series([np.nan] * len(series), index=series.index)
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR) - volatility indicator.
    Used by IndicatorSet for chart display.
    """
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Average Directional Index (ADX) - trend strength indicator.
    ADX < 20 indicates weak trend / chop.
    """
    up_move = high - high.shift()
    down_move = low.shift() - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    tr_smooth = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_dm_series = pd.Series(plus_dm, index=high.index)
    minus_dm_series = pd.Series(minus_dm, index=high.index)

    plus_dm_smooth = plus_dm_series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    minus_dm_smooth = minus_dm_series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    plus_di = 100.0 * (plus_dm_smooth / tr_smooth.replace(0, np.nan))
    minus_di = 100.0 * (minus_dm_smooth / tr_smooth.replace(0, np.nan))

    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = 100.0 * (di_diff / di_sum.replace(0, np.nan))

    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx.fillna(0.0)


class IndicatorSet:
    """Container holding all indicators required by the strategy."""

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55):
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all indicators on a DataFrame containing 'close' (and optionally 'high','low','open').

        Args:
            df: DataFrame with columns ['open','high','low','close','volume'] indexed by datetime.

        Returns:
            DataFrame with extra EMA, ADX, and slope columns appended.
        """
        df = df.copy()
        df["ema_8"] = calculate_ema(df["close"], self.ema_short)
        df["ema_13"] = calculate_ema(df["close"], self.ema_mid1)
        df["ema_21"] = calculate_ema(df["close"], self.ema_mid2)
        df["ema_55"] = calculate_ema(df["close"], self.ema_long)

        # EMA21 slope over last 6 candles (% change)
        df["ema_21_slope"] = (df["ema_21"] - df["ema_21"].shift(6)) / df["ema_21"].shift(6) * 100.0

        if {"high", "low"}.issubset(df.columns):
            df["atr"] = calculate_atr(df["high"], df["low"], df["close"])
            df["adx_14"] = calculate_adx(df["high"], df["low"], df["close"], period=14)
            df["candle_hl_pct"] = ((df["high"] - df["low"]) / df["low"]) * 100.0

        if "open" in df.columns:
            df["candle_move_pct"] = ((df["close"] - df["open"]).abs() / df["open"]) * 100.0

        return df
