# Strategy Library

## Three White Soldiers

**Family:** candlestick_reversal | **Direction:** long

**Idea:** Three consecutive bullish bars with strong bodies and rising closes.

**Entry:** Three bull bars: each close > previous close, each open inside previous body, body >= 0.5*range.

**Exit:** Hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Three Black Crows

**Family:** candlestick_reversal | **Direction:** short

**Idea:** Three consecutive bearish bars with strong bodies and falling closes.

**Entry:** Three bear bars: each close < previous close, body >= 0.5*range.

**Exit:** Hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Bullish Engulfing

**Family:** candlestick_reversal | **Direction:** long

**Idea:** A bullish bar completely engulfs the previous bearish bar.

**Entry:** Bear bar followed by a bull bar where O <= prev C and C >= prev O.

**Exit:** Hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Bearish Engulfing

**Family:** candlestick_reversal | **Direction:** short

**Idea:** A bearish bar completely engulfs the previous bullish bar.

**Entry:** Bull bar followed by a bear bar where O >= prev C and C <= prev O.

**Exit:** Hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Hammer

**Family:** candlestick_reversal | **Direction:** long

**Idea:** Small body in upper portion of range, long lower shadow, after downtrend.

**Entry:** Lower shadow >= 2x body, upper shadow <= 10% range, prior 5-bar decline.

**Exit:** Hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Shooting Star

**Family:** candlestick_reversal | **Direction:** short

**Idea:** Small body near lows, long upper shadow, after uptrend.

**Entry:** Upper shadow >= 2x body, lower shadow <= 10% range, prior 5-bar advance.

**Exit:** Hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Golden Cross

**Family:** trend | **Direction:** long

**Idea:** SMA(50) crosses above SMA(200) — bullish trend confirmation.

**Entry:** SMA(50) cross_above SMA(200).

**Exit:** Death cross or hold 20 bars.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## RSI Oversold Bounce

**Family:** mean_reversion | **Direction:** long

**Idea:** Buy when RSI is oversold in an uptrend.

**Entry:** RSI(14) < 30 and Close > SMA(200).

**Exit:** RSI > 50 or hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Bollinger Lower Band Bounce

**Family:** mean_reversion | **Direction:** long

**Idea:** Price touches lower Bollinger Band in uptrend.

**Entry:** Close < lower BB(20,2), next bar closes back inside band.

**Exit:** Middle band touch or hold 10 bars.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Donchian Breakout

**Family:** breakout | **Direction:** long

**Idea:** Close above the highest high of the prior 20 bars.

**Entry:** Close > donchian upper (prior 20 bars).

**Exit:** Close < donchian lower (10 bars) or hold 20 bars.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## ADX Trend Follow

**Family:** trend | **Direction:** long

**Idea:** Strong trend with positive directional movement.

**Entry:** ADX(14) > 25 and +DI > -DI and Close > SMA(50).

**Exit:** Close < SMA(50) or hold 20 bars.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## MACD Signal Cross

**Family:** momentum | **Direction:** long

**Idea:** MACD crosses its signal line from below zero.

**Entry:** MACD line cross_above signal line while MACD < 0.

**Exit:** MACD cross_below signal or hold 15 bars.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Volume Spike Breakout

**Family:** volume_flow | **Direction:** long

**Idea:** Price breaks to new highs on exceptional volume.

**Entry:** rel_volume > 2 and Close > highest high of prior 20 bars.

**Exit:** Hold 10 bars or stop -8%.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## CMF Accumulation

**Family:** volume_flow | **Direction:** long

**Idea:** Positive money flow with uptrend.

**Entry:** CMF(20) > 0.15 and Close > SMA(50).

**Exit:** CMF(20) < 0 or hold 15 bars.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
## Bollinger Squeeze Breakout

**Family:** volatility | **Direction:** long

**Idea:** Low volatility squeeze resolves with a breakout.

**Entry:** Bandwidth in lowest 10% of last 120 bars, then Close > upper band.

**Exit:** Close < middle band or hold 15 bars.

**Why it might work:** 

**Known failure modes:** 

**Source:** seed

---
