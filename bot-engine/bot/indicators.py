"""
Technical Indicators Module
Calculates Exponential Moving Averages (EMA 8, 13, 21, 55) for the strategy.
Unused legacy indicators (ATR, ADX, Slope) removed to streamline execution.
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


class IndicatorSet:
    """Container holding EMA indicators required by the strategy."""

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55):
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute EMA indicators on a DataFrame containing 'close'.

        Args:
            df: DataFrame with 'close' column indexed by datetime.

        Returns:
            DataFrame with 'ema_8', 'ema_13', 'ema_21', 'ema_55' columns appended.
        """
        df = df.copy()
        df["ema_8"] = calculate_ema(df["close"], self.ema_short)
        df["ema_13"] = calculate_ema(df["close"], self.ema_mid1)
        df["ema_21"] = calculate_ema(df["close"], self.ema_mid2)
        df["ema_55"] = calculate_ema(df["close"], self.ema_long)
        return df
