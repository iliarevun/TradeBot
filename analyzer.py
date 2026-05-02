"""
Market Analyzer v2 — повний технічний аналіз
"""
import asyncio
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
from data_provider import DataProvider
from config import (
    EMA_FAST, EMA_SLOW, EMA_TREND, RSI_PERIOD,
    RSI_OVERSOLD, RSI_OVERBOUGHT, ATR_PERIOD,
    ATR_SL_MULTIPLIER, MIN_RR, CONTEXT_TIMEFRAMES, REQUEST_DELAY
)

logger = logging.getLogger(__name__)

PATTERN_NAMES = {
    "bullish_pinbar": "Бичачий пін-бар 📍",
    "bearish_pinbar": "Ведмежий пін-бар 📍",
    "bullish_engulfing": "Бичаче поглинання 🟢",
    "bearish_engulfing": "Ведмеже поглинання 🔴",
    "doji": "Доджі ➕",
    "inside_bar": "Inside Bar 📦",
    "morning_star": "Ранкова зірка ⭐",
    "evening_star": "Вечірня зірка ⭐",
    "hammer": "Молот 🔨",
    "shooting_star": "Падаюча зірка 💫",
}


class MarketAnalyzer:

    def __init__(self):
        self.dp = DataProvider()

    # ── Indicators ────────────────────────────────────────────────────────────

    def _ema(self, s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    def _rsi(self, close: pd.Series, n=14) -> pd.Series:
        d = close.diff()
        g = d.clip(lower=0).ewm(span=n, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(span=n, adjust=False).mean()
        return 100 - 100 / (1 + g / l.replace(0, np.nan))

    def _atr(self, df: pd.DataFrame, n=14) -> pd.Series:
        h, l, pc = df["high"], df["low"], df["close"].shift(1)
        tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
        return tr.ewm(span=n, adjust=False).mean()

    def _macd(self, close: pd.Series):
        fast = self._ema(close, 12)
        slow = self._ema(close, 26)
        macd = fast - slow
        signal = self._ema(macd, 9)
        return macd, signal, macd - signal

    def _bollinger(self, close: pd.Series, n=20, k=2):
        mid = close.rolling(n).mean()
        std = close.rolling(n).std()
        return mid + k*std, mid, mid - k*std

    # ── Support / Resistance ─────────────────────────────────────────────────

    def _find_levels(self, df: pd.DataFrame, window=8) -> dict:
        h = df["high"].values
        l = df["low"].values
        close = df["close"].iloc[-1]
        supports, resistances = [], []

        for i in range(window, len(df)-window):
            if h[i] == max(h[i-window:i+window+1]):
                resistances.append(h[i])
            if l[i] == min(l[i-window:i+window+1]):
                supports.append(l[i])

        def cluster(levels, tol=0.0015):
            if not levels:
                return []
            levels = sorted(set(levels))
            result = [levels[0]]
            for v in levels[1:]:
                if (v - result[-1]) / result[-1] > tol:
                    result.append(v)
                else:
                    result[-1] = (result[-1] + v) / 2
            return result

        sup = cluster(supports)
        res = cluster(resistances)
        ns = max([s for s in sup if s < close], default=None)
        nr = min([r for r in res if r > close], default=None)

        # Strength: how many times price touched level
        def strength(level, prices, tol=0.002):
            return sum(1 for p in prices if abs(p-level)/level < tol)

        return {
            "supports": sup, "resistances": res,
            "nearest_support": ns, "nearest_resistance": nr,
            "support_strength": strength(ns, l) if ns else 0,
            "resistance_strength": strength(nr, h) if nr else 0,
        }

    # ── Candlestick Patterns ─────────────────────────────────────────────────

    def _patterns(self, df: pd.DataFrame) -> list:
        found = []
        if len(df) < 3:
            return found

        c0 = df.iloc[-1]   # current
        c1 = df.iloc[-2]   # previous
        c2 = df.iloc[-3]   # 2 back

        def body(c): return abs(c["close"] - c["open"])
        def rng(c):  return c["high"] - c["low"]
        def upper_wick(c): return c["high"] - max(c["open"], c["close"])
        def lower_wick(c): return min(c["open"], c["close"]) - c["low"]
        def bull(c): return c["close"] > c["open"]
        def bear(c): return c["close"] < c["open"]

        r0 = rng(c0)
        if r0 < 1e-10:
            return found

        # Pin bar
        if lower_wick(c0) >= 0.6*r0 and body(c0) <= 0.3*r0:
            found.append("bullish_pinbar")
        if upper_wick(c0) >= 0.6*r0 and body(c0) <= 0.3*r0:
            found.append("bearish_pinbar")

        # Hammer / Shooting Star
        if (lower_wick(c0) >= 2*body(c0) and upper_wick(c0) < 0.1*r0
                and body(c0) > 0):
            found.append("hammer")
        if (upper_wick(c0) >= 2*body(c0) and lower_wick(c0) < 0.1*r0
                and body(c0) > 0):
            found.append("shooting_star")

        # Engulfing
        if (bear(c1) and bull(c0)
                and c0["open"] < c1["close"] and c0["close"] > c1["open"]
                and body(c0) > body(c1) * 1.1):
            found.append("bullish_engulfing")
        if (bull(c1) and bear(c0)
                and c0["open"] > c1["close"] and c0["close"] < c1["open"]
                and body(c0) > body(c1) * 1.1):
            found.append("bearish_engulfing")

        # Doji
        if body(c0) <= 0.08 * r0:
            found.append("doji")

        # Inside bar
        if c0["high"] <= c1["high"] and c0["low"] >= c1["low"]:
            found.append("inside_bar")

        # Morning Star (3 candles)
        if (bear(c2) and body(c2) > 0.5*rng(c2)
                and body(c1) < 0.3*rng(c1)
                and bull(c0) and c0["close"] > (c2["open"]+c2["close"])/2):
            found.append("morning_star")

        # Evening Star
        if (bull(c2) and body(c2) > 0.5*rng(c2)
                and body(c1) < 0.3*rng(c1)
                and bear(c0) and c0["close"] < (c2["open"]+c2["close"])/2):
            found.append("evening_star")

        return found

    # ── Trend detection ──────────────────────────────────────────────────────

    def _trend(self, df: pd.DataFrame) -> dict:
        close = df["close"]
        e21 = self._ema(close, EMA_FAST)
        e50 = self._ema(close, EMA_SLOW)
        e200 = self._ema(close, EMA_TREND)

        lc, l21, l50, l200 = close.iloc[-1], e21.iloc[-1], e50.iloc[-1], e200.iloc[-1]
        p21, p50 = e21.iloc[-2], e50.iloc[-2]

        if l21 > l50 > l200 and lc > l21:
            direction, strength = "bullish", "strong"
        elif l21 > l50 and lc > l50:
            direction, strength = "bullish", "moderate"
        elif l21 < l50 < l200 and lc < l21:
            direction, strength = "bearish", "strong"
        elif l21 < l50 and lc < l50:
            direction, strength = "bearish", "moderate"
        else:
            direction, strength = "sideways", "weak"

        crossover = "none"
        if p21 <= p50 and l21 > l50: crossover = "bullish_cross"
        elif p21 >= p50 and l21 < l50: crossover = "bearish_cross"

        return {
            "direction": direction, "strength": strength,
            "ema21": l21, "ema50": l50, "ema200": l200, "crossover": crossover,
        }

    def _structure(self, df: pd.DataFrame) -> dict:
        h = df["high"].values[-20:]
        l = df["low"].values[-20:]
        m = len(h)//2
        hh = h[m:].max() > h[:m].max()
        hl = l[m:].min() > l[:m].min()
        ll = l[m:].min() < l[:m].min()
        lh = h[m:].max() < h[:m].max()

        if hh and hl: st = "uptrend"
        elif ll and lh: st = "downtrend"
        else: st = "ranging"
        return {"structure": st, "hh": hh, "hl": hl}

    # ── Strategies ────────────────────────────────────────────────────────────

    def _s1_level_bounce(self, df, levels, trend) -> dict:
        close = df["close"].iloc[-1]
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        pats = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        at_sup = ns and abs(close-ns)/close < 0.015
        at_res = nr and abs(close-nr)/close < 0.015

        if at_sup:
            score += 20
            signals.append(f"✅ Ціна біля підтримки {ns:.5f}")
            direction = "BUY"
            if "bullish_pinbar" in pats or "hammer" in pats:
                score += 40; signals.append("✅ Бичачий пін-бар / молот на підтримці")
            if "bullish_engulfing" in pats:
                score += 35; signals.append("✅ Бичаче поглинання на підтримці")
            if "morning_star" in pats:
                score += 30; signals.append("✅ Ранкова зірка на підтримці")
            if levels["support_strength"] >= 3:
                score += 10; signals.append(f"✅ Сильний рівень (3+ дотики)")

        elif at_res:
            score += 20
            signals.append(f"✅ Ціна біля опору {nr:.5f}")
            direction = "SELL"
            if "bearish_pinbar" in pats or "shooting_star" in pats:
                score += 40; signals.append("✅ Ведмежий пін-бар / зірка на опорі")
            if "bearish_engulfing" in pats:
                score += 35; signals.append("✅ Ведмеже поглинання на опорі")
            if "evening_star" in pats:
                score += 30; signals.append("✅ Вечірня зірка на опорі")
            if levels["resistance_strength"] >= 3:
                score += 10; signals.append("✅ Сильний рівень (3+ дотики)")

        if trend["direction"] == "bullish" and direction == "BUY":
            score += 15; signals.append("✅ Тренд підтверджує напрямок")
        elif trend["direction"] == "bearish" and direction == "SELL":
            score += 15; signals.append("✅ Тренд підтверджує напрямок")

        return {"name": "Відбій від рівня", "score": min(score,100),
                "direction": direction, "signals": signals}

    def _s2_breakout(self, df, levels, trend) -> dict:
        close, prev = df["close"].iloc[-1], df["close"].iloc[-2]
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        score, signals, direction = 0, [], "NEUTRAL"

        if nr and prev < nr <= close:
            score += 45; signals.append("✅ Пробій рівня опору"); direction = "BUY"
            if abs(close-nr)/close < 0.003:
                score += 30; signals.append("✅ Ретест рівня (опір → підтримка)")
        elif ns and prev > ns >= close:
            score += 45; signals.append("✅ Пробій рівня підтримки"); direction = "SELL"
            if abs(close-ns)/close < 0.003:
                score += 30; signals.append("✅ Ретест рівня (підтримка → опір)")

        vol = df["volume"]
        if len(vol) > 2 and vol.iloc[-1] > vol.iloc[-6:-1].mean() * 1.5:
            score += 15; signals.append("✅ Підвищений обсяг на пробої")

        if trend["direction"] == "bullish" and direction == "BUY":
            score += 10
        elif trend["direction"] == "bearish" and direction == "SELL":
            score += 10

        return {"name": "Пробій + ретест", "score": min(score,100),
                "direction": direction, "signals": signals}

    def _s3_trend_pullback(self, df, trend, levels) -> dict:
        close = df["close"].iloc[-1]
        e21, e50 = trend["ema21"], trend["ema50"]
        pats = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        if trend["direction"] == "bullish" and trend["strength"] in ("strong","moderate"):
            score += 25; signals.append("✅ Висхідний тренд"); direction = "BUY"
            if abs(close-e21)/close < 0.008:
                score += 30; signals.append("✅ Корекція до EMA 21")
            elif abs(close-e50)/close < 0.012:
                score += 20; signals.append("✅ Корекція до EMA 50 (глибока)")
            if any(p in pats for p in ("bullish_pinbar","bullish_engulfing","hammer","morning_star")):
                score += 25; signals.append("✅ Паттерн підтверджує відновлення")

        elif trend["direction"] == "bearish" and trend["strength"] in ("strong","moderate"):
            score += 25; signals.append("✅ Низхідний тренд"); direction = "SELL"
            if abs(close-e21)/close < 0.008:
                score += 30; signals.append("✅ Корекція до EMA 21")
            elif abs(close-e50)/close < 0.012:
                score += 20; signals.append("✅ Корекція до EMA 50 (глибока)")
            if any(p in pats for p in ("bearish_pinbar","bearish_engulfing","shooting_star","evening_star")):
                score += 25; signals.append("✅ Паттерн підтверджує відновлення")

        return {"name": "Тренд + корекція", "score": min(score,100),
                "direction": direction, "signals": signals}

    def _s4_range(self, df, levels, structure) -> dict:
        close = df["close"].iloc[-1]
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        pats = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        if structure["structure"] != "ranging":
            return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                    "signals": ["❌ Ринок не у флеті"]}

        if ns and nr:
            rng_size = (nr - ns) / ns
            if rng_size < 0.005:
                return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                        "signals": ["❌ Діапазон занадто вузький"]}
            score += 30; signals.append("✅ Ринок у флеті (діапазон)")

            pos_in_range = (close - ns) / (nr - ns)
            if pos_in_range < 0.2:
                score += 40; signals.append("✅ Ціна біля нижньої межі → BUY"); direction = "BUY"
            elif pos_in_range > 0.8:
                score += 40; signals.append("✅ Ціна біля верхньої межі → SELL"); direction = "SELL"

            if direction != "NEUTRAL":
                if any(p in pats for p in ("bullish_engulfing","bearish_engulfing","doji")):
                    score += 20; signals.append("✅ Паттерн підтверджує розворот")

        return {"name": "Діапазон (флет)", "score": min(score,100),
                "direction": direction, "signals": signals}

    def _s5_ema_cross(self, df, trend) -> dict:
        pats = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        if trend["crossover"] == "bullish_cross":
            score += 55; signals.append("✅ Бичачий перетин EMA 21 × EMA 50"); direction = "BUY"
        elif trend["crossover"] == "bearish_cross":
            score += 55; signals.append("✅ Ведмежий перетин EMA 21 × EMA 50"); direction = "SELL"
        else:
            if trend["ema21"] > trend["ema50"]:
                score += 20; signals.append("ℹ️ EMA 21 > EMA 50 (бичача)"); direction = "BUY"
            elif trend["ema21"] < trend["ema50"]:
                score += 20; signals.append("ℹ️ EMA 21 < EMA 50 (ведмежа)"); direction = "SELL"

        if direction != "NEUTRAL":
            if any(p in pats for p in ("bullish_pinbar","bullish_engulfing","hammer")):
                score += 25; signals.append("✅ Бичачий паттерн підтверджує")
            elif any(p in pats for p in ("bearish_pinbar","bearish_engulfing","shooting_star")):
                score += 25; signals.append("✅ Ведмежий паттерн підтверджує")

            macd, macd_sig, hist = self._macd(df["close"])
            if direction == "BUY" and hist.iloc[-1] > 0:
                score += 10; signals.append("✅ MACD бичачий")
            elif direction == "SELL" and hist.iloc[-1] < 0:
                score += 10; signals.append("✅ MACD ведмежий")

        return {"name": "EMA Crossover", "score": min(score,100),
                "direction": direction, "signals": signals}

    # ── Main analyze ──────────────────────────────────────────────────────────

    async def analyze(self, symbol: str, tf: str, strategy: str = "all") -> dict:
        df = await self.dp.get_ohlcv(symbol, tf)
        if df is None or len(df) < 30:
            raise ValueError(f"Недостатньо даних для {symbol} на {tf}. "
                             "Спробуйте інший таймфрейм або пару.")

        ctx_tf = CONTEXT_TIMEFRAMES.get(tf, "1d")
        df_ctx = await self.dp.get_ohlcv(symbol, ctx_tf)

        close = df["close"]
        rsi_s  = self._rsi(close, RSI_PERIOD)
        atr_s  = self._atr(df, ATR_PERIOD)
        macd_l, macd_sig, macd_hist = self._macd(close)
        bb_up, bb_mid, bb_low = self._bollinger(close)

        trend   = self._trend(df)
        ctx_trend = self._trend(df_ctx) if df_ctx is not None and len(df_ctx)>=20 else trend
        levels  = self._find_levels(df)
        struct  = self._structure(df)
        pats    = self._patterns(df)

        last_close = close.iloc[-1]
        last_rsi   = rsi_s.iloc[-1]
        last_atr   = atr_s.iloc[-1]

        all_strats = {
            "s1": self._s1_level_bounce(df, levels, trend),
            "s2": self._s2_breakout(df, levels, trend),
            "s3": self._s3_trend_pullback(df, trend, levels),
            "s4": self._s4_range(df, levels, struct),
            "s5": self._s5_ema_cross(df, trend),
        }

        strats = {strategy: all_strats[strategy]} if strategy in all_strats else all_strats

        best = max(strats.values(), key=lambda x: x["score"])

        buy_s  = sum(s["score"] for s in strats.values() if s["direction"]=="BUY")
        sell_s = sum(s["score"] for s in strats.values() if s["direction"]=="SELL")
        total  = buy_s + sell_s

        if total == 0:
            direction, confidence = "NEUTRAL", 0
        elif buy_s > sell_s:
            direction = "BUY"
            confidence = int(buy_s / total * 100)
        else:
            direction = "SELL"
            confidence = int(sell_s / total * 100)

        # RSI adjustment
        if last_rsi < RSI_OVERSOLD and direction == "BUY":
            confidence = min(confidence+10, 100)
        elif last_rsi > RSI_OVERBOUGHT and direction == "SELL":
            confidence = min(confidence+10, 100)

        # Context TF conflict
        if (ctx_trend["direction"] not in (trend["direction"], "sideways")
                and direction != "NEUTRAL"):
            confidence = max(confidence-15, 0)

        # SL / TP
        sl_dist = last_atr * ATR_SL_MULTIPLIER
        if direction == "BUY":
            sl  = last_close - sl_dist
            tp1 = last_close + sl_dist * MIN_RR
            tp2 = last_close + sl_dist * 3.0
            if levels["nearest_resistance"]:
                tp1 = min(tp1, levels["nearest_resistance"])
        elif direction == "SELL":
            sl  = last_close + sl_dist
            tp1 = last_close - sl_dist * MIN_RR
            tp2 = last_close - sl_dist * 3.0
            if levels["nearest_support"]:
                tp1 = max(tp1, levels["nearest_support"])
        else:
            sl = tp1 = tp2 = last_close

        rr = abs(tp1-last_close) / abs(sl-last_close) if sl!=last_close else 0

        return {
            "symbol": symbol, "timeframe": tf, "context_tf": ctx_tf,
            "price": last_close, "direction": direction, "confidence": confidence,
            "best_strategy": best, "all_strategies": all_strats,
            "trend": trend, "ctx_trend": ctx_trend,
            "levels": levels, "structure": struct,
            "rsi": last_rsi, "atr": last_atr,
            "macd_hist": float(macd_hist.iloc[-1]),
            "bb_upper": float(bb_up.iloc[-1]),
            "bb_lower": float(bb_low.iloc[-1]),
            "sl": sl, "tp1": tp1, "tp2": tp2, "rr": rr,
            "candle_patterns": pats,
            "timestamp": datetime.now(),
            "candles": df.tail(50).to_dict("records"),  # для Mini App
        }

    async def scan_market(self, symbols: list, tf="1h") -> list:
        results = []
        for sym in symbols:
            try:
                r = await self.analyze(sym, tf, "all")
                results.append({
                    "symbol": sym, "signal": r["direction"],
                    "confidence": r["confidence"],
                    "best_strategy": r["best_strategy"]["name"],
                    "rsi": round(r["rsi"], 1), "price": r["price"],
                    "rr": round(r["rr"], 2), "trend": r["trend"]["direction"],
                    "patterns": r["candle_patterns"],
                })
                await asyncio.sleep(REQUEST_DELAY)
            except Exception as e:
                logger.warning(f"Scan fail {sym}: {e}")
                results.append({
                    "symbol": sym, "signal": "ERROR", "confidence": 0,
                    "best_strategy": "N/A", "rsi": 50, "price": 0,
                    "rr": 0, "trend": "unknown", "patterns": [],
                })

        results.sort(key=lambda x: (0 if x["signal"] in ("BUY","SELL") else 1, -x["confidence"]))
        return results
