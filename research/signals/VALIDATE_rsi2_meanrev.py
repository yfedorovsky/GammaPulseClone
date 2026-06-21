"""Validation signal: reproduce _qqq_rsi2_meanrev (Connors RSI2 mean-reversion).
Event = RSI(2)<5 AND close>200-SMA -> LONG, 3-day horizon. Used only to confirm
the engine's event_study matches the existing standalone script's numbers."""
import numpy as np

SPEC = dict(
    id="VALIDATE_rsi2_meanrev",
    name="Connors RSI(2)<5 in uptrend (validation)",
    category="B2",
    description="RSI(2)<5 AND close>200SMA, long 3d. Reproduces _qqq_rsi2_meanrev.",
    side="long", horizon=3, tickers=["QQQ"], cross=False, requires=[],
)


def signal(H, df):
    close = df["close"].to_numpy()
    rsi2 = H.rsi(close, 2)
    sma200 = H.sma(close, 200)
    return (rsi2 < 5) & (close > sma200) & np.isfinite(sma200)
