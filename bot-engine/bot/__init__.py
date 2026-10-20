from .engine import BotEngine, get_trader
from .strategy import EMAQuadStrategy, Signal, StrategyResult
from .trader import BinanceFuturesTrader, Position
from .weex_trader import WEEXFuturesTrader, WEEXPosition
try:
    from .primexbt_trader import PrimeXBTTrader, PrimeXBTPosition
except Exception:
    PrimeXBTTrader = None
    PrimeXBTPosition = None
from .notifier import Notifier
from .indicators import IndicatorSet, calculate_ema
