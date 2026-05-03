"""
Market Analyzer v3 — виправлений, синхронізований з webapp
Зміни:
  - Виправлено RuntimeWarning: divide by zero в cluster()
  - _find_levels повністю переписаний (безпечний)
  - _col() helper для захисту від MultiIndex DataFrame
  - _safe() для захисту від NaN/inf скрізь
  - Алгоритм ІДЕНТИЧНИЙ до webapp/index.html (JS)
"""
import asyncio
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional
from data_provider import DataProvider
from config import (
    EMA_FAST, EMA_SLOW, EMA_TREND, RSI_PERIOD,
    RSI_OVERSOLD, RSI_OVERBOUGHT, ATR_PERIOD,
    ATR_SL_MULTIPLIER, MIN_RR, CONTEXT_TIMEFRAMES, REQUEST_DELAY
)

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(v, default=0.0):
    try:
        f = float(v)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except Exception:
        return default

def _ok(df) -> bool:
    return df is not None and isinstance(df, pd.DataFrame) and len(df) >= 20

def _col(df: pd.DataFrame, col: str) -> pd.Series:
    """Завжди повертає Series навіть при MultiIndex"""
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s.astype(float)

PATTERN_NAMES = {
    "bullish_pinbar":    "Бичачий пін-бар 📍",
    "bearish_pinbar":    "Ведмежий пін-бар 📍",
    "bullish_engulfing": "Бичаче поглинання 🟢",
    "bearish_engulfing": "Ведмеже поглинання 🔴",
    "doji":              "Доджі ➕",
    "inside_bar":        "Inside Bar 📦",
    "morning_star":      "Ранкова зірка ⭐",
    "evening_star":      "Вечірня зірка ⭐",
    "hammer":            "Молот 🔨",
    "shooting_star":     "Падаюча зірка 💫",
    "three_white":       "3 білих солдати 🟢",
    "three_black":       "3 чорних ворони 🔴",
    "tweezer_bottom":    "Пінцет знизу 🔧",
    "tweezer_top":       "Пінцет зверху 🔧",
}


class MarketAnalyzer:

    def __init__(self):
        self.dp = DataProvider()

    # ══════════════════════════════════════════════════════════════════════════
    #  INDICATORS
    # ══════════════════════════════════════════════════════════════════════════

    def _ema(self, s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    def _rsi(self, close: pd.Series, n=14) -> pd.Series:
        d = close.diff()
        g = d.clip(lower=0).ewm(span=n, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(span=n, adjust=False).mean()
        rs = g / l.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50)

    def _atr(self, df: pd.DataFrame, n=14) -> pd.Series:
        h  = _col(df, "high")
        l  = _col(df, "low")
        pc = _col(df, "close").shift(1)
        tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
        return tr.ewm(span=n, adjust=False).mean()

    def _adx(self, df: pd.DataFrame, n=14) -> dict:
        h  = _col(df, "high").values.astype(float)
        l  = _col(df, "low").values.astype(float)
        c  = _col(df, "close").values.astype(float)
        sz = len(c)

        plus_dm  = np.zeros(sz)
        minus_dm = np.zeros(sz)
        tr_arr   = np.zeros(sz)

        for i in range(1, sz):
            up   = h[i] - h[i-1]
            dn   = l[i-1] - l[i]
            plus_dm[i]  = up  if (up > dn and up > 0)   else 0.0
            minus_dm[i] = dn  if (dn > up and dn > 0)   else 0.0
            tr_arr[i]   = max(h[i]-l[i],
                              abs(h[i]-c[i-1]),
                              abs(l[i]-c[i-1]))

        def _wilder(arr, period):
            result = np.zeros(len(arr))
            result[period] = arr[1:period+1].mean()
            for i in range(period+1, len(arr)):
                result[i] = (result[i-1]*(period-1) + arr[i]) / period
            return result

        atr_w = _wilder(tr_arr, n)
        pdm_w = _wilder(plus_dm, n)
        mdm_w = _wilder(minus_dm, n)

        # Захист від ділення на нуль
        with np.errstate(divide='ignore', invalid='ignore'):
            pdi = np.where(atr_w > 1e-10, 100 * pdm_w / atr_w, 0.0)
            mdi = np.where(atr_w > 1e-10, 100 * mdm_w / atr_w, 0.0)
            sm  = pdi + mdi
            dx  = np.where(sm > 1e-10, 100 * np.abs(pdi - mdi) / sm, 0.0)

        adx_arr = _wilder(dx, n)

        last_adx = _safe(adx_arr[-1])
        last_pdi = _safe(pdi[-1])
        last_mdi = _safe(mdi[-1])

        return {
            "adx":      last_adx,
            "plus_di":  last_pdi,
            "minus_di": last_mdi,
            "strong":   last_adx >= 25,
            "direction": "bullish" if last_pdi > last_mdi else "bearish",
        }

    def _macd(self, close: pd.Series):
        fast   = self._ema(close, 12)
        slow   = self._ema(close, 26)
        macd   = fast - slow
        signal = self._ema(macd, 9)
        return macd, signal, macd - signal

    def _bollinger(self, close: pd.Series, n=20, k=2):
        mid = close.rolling(n, min_periods=1).mean()
        std = close.rolling(n, min_periods=1).std().fillna(0)
        return mid + k*std, mid, mid - k*std

    # ══════════════════════════════════════════════════════════════════════════
    #  SUPPORT / RESISTANCE — без RuntimeWarning
    # ══════════════════════════════════════════════════════════════════════════

    def _find_levels(self, df: pd.DataFrame, window=8) -> dict:
        h     = _col(df, "high").values.astype(float)
        l     = _col(df, "low").values.astype(float)
        close = _safe(_col(df, "close").iloc[-1])

        supports, resistances = [], []

        for i in range(window, len(df) - window):
            if h[i] == float(np.max(h[i-window: i+window+1])):
                resistances.append(float(h[i]))
            if l[i] == float(np.min(l[i-window: i+window+1])):
                supports.append(float(l[i]))

        def cluster(raw: list, tol=0.0015) -> list:
            """Повертає список dict {price, touches}. БЕЗ ділення на нуль."""
            if not raw:
                return []
            raw_sorted = sorted(set(raw))
            result = [{"price": raw_sorted[0], "touches": 1}]
            for v in raw_sorted[1:]:
                ref = result[-1]["price"]
                # Захист: ref може бути 0 якщо дані некоректні
                if ref < 1e-10:
                    result.append({"price": v, "touches": 1})
                    continue
                if (v - ref) / ref > tol:
                    result.append({"price": v, "touches": 1})
                else:
                    # Проста середня (НЕ зважена — без ділення на вагу)
                    result[-1]["price"] = (ref + v) / 2
                    result[-1]["touches"] += 1
            return result

        sup_cl = cluster(supports)
        res_cl = cluster(resistances)

        # Найближчі до поточної ціни
        sup_below = [s for s in sup_cl if s["price"] < close]
        res_above = [r for r in res_cl if r["price"] > close]

        ns_obj = max(sup_below, key=lambda x: x["price"]) if sup_below else None
        nr_obj = min(res_above, key=lambda x: x["price"]) if res_above else None

        ns = ns_obj["price"] if ns_obj else None
        nr = nr_obj["price"] if nr_obj else None
        ns_strength = ns_obj["touches"] if ns_obj else 0
        nr_strength = nr_obj["touches"] if nr_obj else 0

        # Fibonacci між ns та nr
        fib_levels = {}
        if ns and nr and nr > ns and (nr - ns) / max(ns, 1e-10) > 0.001:
            diff = nr - ns
            for ratio, label in [
                (0.236, "Fib 23.6%"), (0.382, "Fib 38.2%"),
                (0.500, "Fib 50.0%"), (0.618, "Fib 61.8%"),
                (0.786, "Fib 78.6%"),
            ]:
                fib_levels[label] = ns + diff * ratio

        return {
            "supports":            [s["price"] for s in sup_cl],
            "resistances":         [r["price"] for r in res_cl],
            "nearest_support":     ns,
            "nearest_resistance":  nr,
            "support_strength":    ns_strength,
            "resistance_strength": nr_strength,
            "fib_levels":          fib_levels,
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  CANDLESTICK PATTERNS (14 штук)
    # ══════════════════════════════════════════════════════════════════════════

    def _patterns(self, df: pd.DataFrame) -> list:
        found = []
        if len(df) < 3:
            return found

        o = _col(df, "open").values.astype(float)
        h = _col(df, "high").values.astype(float)
        l = _col(df, "low").values.astype(float)
        c = _col(df, "close").values.astype(float)

        def body(i):  return abs(c[i] - o[i])
        def rng(i):   return h[i] - l[i]
        def upper(i): return h[i] - max(o[i], c[i])
        def lower(i): return min(o[i], c[i]) - l[i]
        def bull(i):  return c[i] > o[i]
        def bear(i):  return c[i] < o[i]

        n = len(c) - 1
        if rng(n) < 1e-10:
            return found

        # Pin bar
        if lower(n) >= 0.6*rng(n) and body(n) <= 0.35*rng(n):
            found.append("bullish_pinbar")
        if upper(n) >= 0.6*rng(n) and body(n) <= 0.35*rng(n):
            found.append("bearish_pinbar")

        # Hammer / Shooting Star
        if body(n) > 0 and lower(n) >= 2*body(n) and upper(n) <= 0.15*rng(n):
            found.append("hammer")
        if body(n) > 0 and upper(n) >= 2*body(n) and lower(n) <= 0.15*rng(n):
            found.append("shooting_star")

        # Engulfing
        if (n >= 1 and bear(n-1) and bull(n)
                and o[n] <= c[n-1] and c[n] >= o[n-1]
                and body(n) > body(n-1) * 1.05):
            found.append("bullish_engulfing")
        if (n >= 1 and bull(n-1) and bear(n)
                and o[n] >= c[n-1] and c[n] <= o[n-1]
                and body(n) > body(n-1) * 1.05):
            found.append("bearish_engulfing")

        # Doji
        if body(n) <= 0.07 * rng(n):
            found.append("doji")

        # Inside Bar
        if n >= 1 and h[n] <= h[n-1] and l[n] >= l[n-1]:
            found.append("inside_bar")

        # Morning / Evening Star
        if (n >= 2 and bear(n-2) and body(n-2) > 0.5*rng(n-2)
                and body(n-1) < 0.3*rng(n-1)
                and bull(n) and c[n] > (o[n-2]+c[n-2])/2):
            found.append("morning_star")
        if (n >= 2 and bull(n-2) and body(n-2) > 0.5*rng(n-2)
                and body(n-1) < 0.3*rng(n-1)
                and bear(n) and c[n] < (o[n-2]+c[n-2])/2):
            found.append("evening_star")

        # 3 White Soldiers / 3 Black Crows
        if (n >= 2 and all(bull(n-i) for i in range(3))
                and c[n] > c[n-1] > c[n-2]
                and all(body(n-i) > 0.5*rng(n-i) for i in range(3))):
            found.append("three_white")
        if (n >= 2 and all(bear(n-i) for i in range(3))
                and c[n] < c[n-1] < c[n-2]
                and all(body(n-i) > 0.5*rng(n-i) for i in range(3))):
            found.append("three_black")

        # Tweezer
        if (n >= 1 and bear(n-1) and bull(n)
                and abs(l[n]-l[n-1]) / max(rng(n), 1e-10) < 0.05):
            found.append("tweezer_bottom")
        if (n >= 1 and bull(n-1) and bear(n)
                and abs(h[n]-h[n-1]) / max(rng(n), 1e-10) < 0.05):
            found.append("tweezer_top")

        return found

    # ══════════════════════════════════════════════════════════════════════════
    #  TREND & STRUCTURE
    # ══════════════════════════════════════════════════════════════════════════

    def _trend(self, df: pd.DataFrame) -> dict:
        close = _col(df, "close")
        e21   = self._ema(close, EMA_FAST)
        e50   = self._ema(close, EMA_SLOW)
        e200  = self._ema(close, EMA_TREND)

        lc   = _safe(close.iloc[-1])
        l21  = _safe(e21.iloc[-1])
        l50  = _safe(e50.iloc[-1])
        l200 = _safe(e200.iloc[-1])
        p21  = _safe(e21.iloc[-2])
        p50  = _safe(e50.iloc[-2])

        e21_5ago = _safe(e21.iloc[-5]) if len(e21) >= 5 else l21
        slope_pct = (l21 - e21_5ago) / max(e21_5ago, 1e-10) * 100

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
        if p21 <= p50 and l21 > l50:  crossover = "bullish_cross"
        elif p21 >= p50 and l21 < l50: crossover = "bearish_cross"

        return {
            "direction": direction, "strength": strength,
            "ema21": l21, "ema50": l50, "ema200": l200,
            "crossover": crossover, "slope_pct": slope_pct,
        }

    def _structure(self, df: pd.DataFrame) -> dict:
        h = _col(df, "high").values[-30:].astype(float)
        l = _col(df, "low").values[-30:].astype(float)
        m = len(h) // 2
        hh = float(h[m:].max()) > float(h[:m].max())
        hl = float(l[m:].min()) > float(l[:m].min())
        ll = float(l[m:].min()) < float(l[:m].min())
        lh = float(h[m:].max()) < float(h[:m].max())
        if hh and hl:   st = "uptrend"
        elif ll and lh: st = "downtrend"
        else:           st = "ranging"
        return {"structure": st, "hh": hh, "hl": hl}

    def _market_session(self) -> str:
        hour = datetime.now(timezone.utc).hour
        if 7 <= hour < 12:  return "london"
        if 12 <= hour < 17: return "new_york"
        if 0 <= hour < 8:   return "asia"
        return "off_hours"

    # ══════════════════════════════════════════════════════════════════════════
    #  STRATEGIES
    # ══════════════════════════════════════════════════════════════════════════

    def _s1_level_bounce(self, df, levels, trend, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        pats = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        at_sup = ns and abs(close - ns) / max(close, 1e-10) < 0.012
        at_res = nr and abs(close - nr) / max(close, 1e-10) < 0.012

        if at_sup:
            score += 25; signals.append(f"✅ Ціна біля підтримки {ns:.5f}"); direction = "BUY"
            st = levels["support_strength"]
            if st >= 4:   score += 20; signals.append(f"✅ Дуже сильний рівень ({st} дотиків)")
            elif st >= 2: score += 10; signals.append(f"✅ Підтверджений рівень ({st} дотики)")
            if "bullish_pinbar" in pats or "hammer" in pats:
                score += 35; signals.append("✅ Бичачий пін-бар / молот")
            if "bullish_engulfing" in pats:
                score += 30; signals.append("✅ Бичаче поглинання")
            if "morning_star" in pats or "three_white" in pats:
                score += 25; signals.append("✅ Сильний розворотний паттерн")
            if "tweezer_bottom" in pats:
                score += 20; signals.append("✅ Пінцет знизу")
            if adx["adx"] < 20:
                score += 10; signals.append("✅ ADX низький — відбій ймовірний")
        elif at_res:
            score += 25; signals.append(f"✅ Ціна біля опору {nr:.5f}"); direction = "SELL"
            st = levels["resistance_strength"]
            if st >= 4:   score += 20; signals.append(f"✅ Дуже сильний рівень ({st} дотиків)")
            elif st >= 2: score += 10; signals.append(f"✅ Підтверджений рівень ({st} дотики)")
            if "bearish_pinbar" in pats or "shooting_star" in pats:
                score += 35; signals.append("✅ Ведмежий пін-бар / зірка")
            if "bearish_engulfing" in pats:
                score += 30; signals.append("✅ Ведмеже поглинання")
            if "evening_star" in pats or "three_black" in pats:
                score += 25; signals.append("✅ Сильний розворотний паттерн")
            if "tweezer_top" in pats:
                score += 20; signals.append("✅ Пінцет зверху")
            if adx["adx"] < 20:
                score += 10; signals.append("✅ ADX низький — відбій ймовірний")

        if trend["direction"] == "bullish" and direction == "BUY":
            score += 15; signals.append("✅ Тренд підтверджує лонг")
        elif trend["direction"] == "bearish" and direction == "SELL":
            score += 15; signals.append("✅ Тренд підтверджує шорт")
        elif direction != "NEUTRAL":
            score -= 10; signals.append("⚠️ Торгівля проти тренду")

        return {"name": "Відбій від рівня",
                "score": min(max(score, 0), 100), "direction": direction, "signals": signals}

    def _s2_breakout(self, df, levels, trend, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        prev  = _safe(_col(df, "close").iloc[-2])
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        vol = _col(df, "volume")
        score, signals, direction = 0, [], "NEUTRAL"

        if nr and prev < nr and close > nr:
            score += 40; signals.append("✅ Пробій рівня опору (закриття вище)"); direction = "BUY"
            if (close - nr) / max(nr, 1e-10) * 100 < 0.3:
                score += 25; signals.append("✅ Ретест рівня")
            if adx["adx"] > 20:
                score += 15; signals.append(f"✅ ADX {adx['adx']:.0f} — тренд набирає силу")
        elif ns and prev > ns and close < ns:
            score += 40; signals.append("✅ Пробій рівня підтримки (закриття нижче)"); direction = "SELL"
            if (ns - close) / max(ns, 1e-10) * 100 < 0.3:
                score += 25; signals.append("✅ Ретест рівня")
            if adx["adx"] > 20:
                score += 15; signals.append(f"✅ ADX {adx['adx']:.0f} — тренд набирає силу")

        if direction != "NEUTRAL" and len(vol) >= 10:
            avg_vol  = float(vol.iloc[-10:-1].mean())
            last_vol = float(vol.iloc[-1])
            if avg_vol > 0 and last_vol > avg_vol * 1.3:
                score += 20; signals.append(f"✅ Обсяг вищий за середній на {(last_vol/avg_vol-1)*100:.0f}%")

        if trend["direction"] == "bullish" and direction == "BUY":   score += 10
        elif trend["direction"] == "bearish" and direction == "SELL": score += 10

        return {"name": "Пробій + ретест",
                "score": min(max(score, 0), 100), "direction": direction, "signals": signals}

    def _s3_trend_pullback(self, df, trend, levels, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        e21, e50 = trend["ema21"], trend["ema50"]
        pats = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        if adx["adx"] < 15:
            return {"name": "Тренд + корекція", "score": 0, "direction": "NEUTRAL",
                    "signals": [f"❌ ADX {adx['adx']:.0f} — тренд занадто слабкий"]}

        bull_pats = ("bullish_pinbar","bullish_engulfing","hammer","morning_star","tweezer_bottom","three_white")
        bear_pats = ("bearish_pinbar","bearish_engulfing","shooting_star","evening_star","tweezer_top","three_black")

        if trend["direction"] == "bullish" and trend["strength"] in ("strong","moderate"):
            score += 25; signals.append(f"✅ Висхідний тренд (ADX {adx['adx']:.0f})"); direction = "BUY"
            if trend.get("slope_pct", 0) > 0.1:
                score += 10; signals.append("✅ EMA 21 нахилена вгору")
            d21 = abs(close - e21) / max(close, 1e-10) * 100
            d50 = abs(close - e50) / max(close, 1e-10) * 100
            if d21 < 0.8:   score += 35; signals.append("✅ Корекція до EMA 21 — ідеальна зона")
            elif d21 < 1.5: score += 20; signals.append("✅ Корекція до EMA 21")
            elif d50 < 1.2: score += 15; signals.append("✅ Корекція до EMA 50")
            if any(p in pats for p in bull_pats):
                score += 25; signals.append("✅ Паттерн підтверджує відновлення")

        elif trend["direction"] == "bearish" and trend["strength"] in ("strong","moderate"):
            score += 25; signals.append(f"✅ Низхідний тренд (ADX {adx['adx']:.0f})"); direction = "SELL"
            if trend.get("slope_pct", 0) < -0.1:
                score += 10; signals.append("✅ EMA 21 нахилена вниз")
            d21 = abs(close - e21) / max(close, 1e-10) * 100
            d50 = abs(close - e50) / max(close, 1e-10) * 100
            if d21 < 0.8:   score += 35; signals.append("✅ Корекція до EMA 21 — зона продажу")
            elif d21 < 1.5: score += 20; signals.append("✅ Корекція до EMA 21")
            elif d50 < 1.2: score += 15; signals.append("✅ Корекція до EMA 50")
            if any(p in pats for p in bear_pats):
                score += 25; signals.append("✅ Паттерн підтверджує продовження")

        return {"name": "Тренд + корекція",
                "score": min(max(score, 0), 100), "direction": direction, "signals": signals}

    def _s4_range(self, df, levels, structure, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        pats = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        is_flat = structure["structure"] == "ranging" or adx["adx"] < 20
        if not is_flat:
            return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                    "signals": [f"❌ ADX {adx['adx']:.0f} — ринок у тренді"]}
        if not (ns and nr):
            return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                    "signals": ["❌ Рівні не визначено"]}

        rng_size = (nr - ns) / max(ns, 1e-10)
        if rng_size < 0.005:
            return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                    "signals": ["❌ Діапазон занадто вузький (<0.5%)"]}

        score += 30; signals.append(f"✅ Флет підтверджено (ADX {adx['adx']:.0f})")
        pos = (close - ns) / max(nr - ns, 1e-10)

        bull_pats = ("bullish_pinbar","hammer","bullish_engulfing","morning_star","tweezer_bottom")
        bear_pats = ("bearish_pinbar","shooting_star","bearish_engulfing","evening_star","tweezer_top")

        if pos < 0.2:
            score += 40; signals.append("✅ Ціна біля нижньої межі → BUY"); direction = "BUY"
            if any(p in pats for p in bull_pats):
                score += 25; signals.append("✅ Бичачий паттерн підтверджує розворот")
        elif pos > 0.8:
            score += 40; signals.append("✅ Ціна біля верхньої межі → SELL"); direction = "SELL"
            if any(p in pats for p in bear_pats):
                score += 25; signals.append("✅ Ведмежий паттерн підтверджує розворот")
        else:
            signals.append(f"ℹ️ Ціна в середині діапазону ({pos*100:.0f}%) — очікуйте меж")

        return {"name": "Діапазон (флет)",
                "score": min(max(score, 0), 100), "direction": direction, "signals": signals}

    def _s5_ema_cross(self, df, trend, adx) -> dict:
        close = _col(df, "close")
        pats  = self._patterns(df)
        _, _, hist = self._macd(close)
        last_hist = _safe(hist.iloc[-1])
        prev_hist = _safe(hist.iloc[-2])
        score, signals, direction = 0, [], "NEUTRAL"

        if trend["crossover"] == "bullish_cross":
            score += 50; signals.append("✅ Бичачий перетин EMA 21×EMA 50"); direction = "BUY"
        elif trend["crossover"] == "bearish_cross":
            score += 50; signals.append("✅ Ведмежий перетин EMA 21×EMA 50"); direction = "SELL"
        else:
            if trend["ema21"] > trend["ema50"]:
                score += 20; signals.append("ℹ️ EMA 21 > EMA 50 (бичача)"); direction = "BUY"
            elif trend["ema21"] < trend["ema50"]:
                score += 20; signals.append("ℹ️ EMA 21 < EMA 50 (ведмежа)"); direction = "SELL"

        if direction != "NEUTRAL":
            if direction == "BUY" and last_hist > 0:
                score += 15; signals.append("✅ MACD бичачий")
                if prev_hist < 0 < last_hist: score += 10; signals.append("✅ MACD перетнув нуль вгору")
            elif direction == "SELL" and last_hist < 0:
                score += 15; signals.append("✅ MACD ведмежий")
                if prev_hist > 0 > last_hist: score += 10; signals.append("✅ MACD перетнув нуль вниз")
            if adx["adx"] > 25:
                score += 10; signals.append(f"✅ ADX {adx['adx']:.0f} — сильний тренд")

            bull_pats = ("bullish_pinbar","bullish_engulfing","hammer","morning_star")
            bear_pats = ("bearish_pinbar","bearish_engulfing","shooting_star","evening_star")
            if direction == "BUY"  and any(p in pats for p in bull_pats):
                score += 20; signals.append("✅ Бичачий паттерн підтверджує")
            elif direction == "SELL" and any(p in pats for p in bear_pats):
                score += 20; signals.append("✅ Ведмежий паттерн підтверджує")

        return {"name": "EMA Crossover + MACD",
                "score": min(max(score, 0), 100), "direction": direction, "signals": signals}

    # ══════════════════════════════════════════════════════════════════════════
    #  MAIN ANALYZE
    # ══════════════════════════════════════════════════════════════════════════

    async def analyze(self, symbol: str, tf: str, strategy: str = "all") -> dict:
        df = await self.dp.get_ohlcv(symbol, tf)
        if not _ok(df):
            raise ValueError(f"Недостатньо даних для {symbol} на {tf}.")

        ctx_tf  = CONTEXT_TIMEFRAMES.get(tf, "1d")
        df_ctx  = await self.dp.get_ohlcv(symbol, ctx_tf)

        close = _col(df, "close")
        rsi_s = self._rsi(close, RSI_PERIOD)
        atr_s = self._atr(df, ATR_PERIOD)
        _, _, hist = self._macd(close)
        adx_d = self._adx(df)

        trend     = self._trend(df)
        ctx_trend = self._trend(df_ctx) if _ok(df_ctx) else trend
        levels    = self._find_levels(df)
        struct    = self._structure(df)
        pats      = self._patterns(df)
        session   = self._market_session()

        last_close = _safe(close.iloc[-1])
        last_rsi   = _safe(rsi_s.iloc[-1], 50)
        last_atr   = _safe(atr_s.iloc[-1])
        last_hist  = _safe(hist.iloc[-1])

        all_strats = {
            "s1": self._s1_level_bounce(df, levels, trend, adx_d),
            "s2": self._s2_breakout(df, levels, trend, adx_d),
            "s3": self._s3_trend_pullback(df, trend, levels, adx_d),
            "s4": self._s4_range(df, levels, struct, adx_d),
            "s5": self._s5_ema_cross(df, trend, adx_d),
        }

        strats = {strategy: all_strats[strategy]} if strategy in all_strats else all_strats
        best   = max(strats.values(), key=lambda x: x["score"])

        # Зважений vote — ІДЕНТИЧНО до JS
        WEIGHTS = {"s1": 1.2, "s2": 1.1, "s3": 1.3, "s4": 0.9, "s5": 1.0}
        buy_s  = sum(s["score"] * WEIGHTS.get(k,1.0) for k,s in all_strats.items() if s["direction"]=="BUY")
        sell_s = sum(s["score"] * WEIGHTS.get(k,1.0) for k,s in all_strats.items() if s["direction"]=="SELL")
        total  = buy_s + sell_s

        if total < 1:
            direction, confidence = "NEUTRAL", 0
        elif buy_s > sell_s:
            direction = "BUY";  confidence = int(min(buy_s/total*100, 100))
        else:
            direction = "SELL"; confidence = int(min(sell_s/total*100, 100))

        # Adjustments — ІДЕНТИЧНО до JS
        if last_rsi < RSI_OVERSOLD  and direction == "BUY":   confidence = min(confidence+8, 100)
        elif last_rsi > RSI_OVERBOUGHT and direction == "SELL": confidence = min(confidence+8, 100)
        if adx_d["adx"] > 30 and direction != "NEUTRAL": confidence = min(confidence+7, 100)
        elif adx_d["adx"] < 15:                           confidence = max(confidence-5, 0)
        if direction == "BUY"  and last_hist > 0: confidence = min(confidence+5, 100)
        elif direction == "SELL" and last_hist < 0: confidence = min(confidence+5, 100)
        if (direction != "NEUTRAL"
                and ctx_trend["direction"] not in (trend["direction"], "sideways")):
            confidence = max(confidence-20, 0)
        if session == "off_hours" and "USD" in symbol:
            confidence = max(confidence-10, 0)

        # SL / TP — ІДЕНТИЧНО до JS
        sl_dist = last_atr * ATR_SL_MULTIPLIER
        if direction == "BUY":
            sl  = (min(levels["nearest_support"] - last_atr*0.3, last_close - sl_dist)
                   if levels["nearest_support"] else last_close - sl_dist)
            tp1 = last_close + abs(last_close - sl) * MIN_RR
            tp2 = last_close + abs(last_close - sl) * 3.0
            if levels["nearest_resistance"]:
                tp1 = min(tp1, levels["nearest_resistance"] * 0.999)
        elif direction == "SELL":
            sl  = (max(levels["nearest_resistance"] + last_atr*0.3, last_close + sl_dist)
                   if levels["nearest_resistance"] else last_close + sl_dist)
            tp1 = last_close - abs(sl - last_close) * MIN_RR
            tp2 = last_close - abs(sl - last_close) * 3.0
            if levels["nearest_support"]:
                tp1 = max(tp1, levels["nearest_support"] * 1.001)
        else:
            sl = tp1 = tp2 = last_close

        rr = abs(tp1 - last_close) / max(abs(sl - last_close), 1e-10)
        if rr < 1.5 and direction != "NEUTRAL":
            confidence = max(confidence-15, 0)

        return {
            "symbol": symbol, "timeframe": tf, "context_tf": ctx_tf,
            "price": last_close, "direction": direction, "confidence": confidence,
            "best_strategy": best, "all_strategies": all_strats,
            "trend": trend, "ctx_trend": ctx_trend,
            "levels": levels, "structure": struct, "adx": adx_d,
            "rsi": last_rsi, "atr": last_atr, "macd_hist": last_hist,
            "session": session,
            "sl": sl, "tp1": tp1, "tp2": tp2, "rr": rr,
            "candle_patterns": pats,
            "timestamp": datetime.now(),
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  SCAN
    # ══════════════════════════════════════════════════════════════════════════

    async def scan_market(self, symbols: list, tf="1h") -> list:
        results = []
        for sym in symbols:
            try:
                r = await self.analyze(sym, tf, "all")
                results.append({
                    "symbol": sym, "signal": r["direction"],
                    "confidence": r["confidence"],
                    "best_strategy": r["best_strategy"]["name"],
                    "rsi": round(r["rsi"], 1), "adx": round(r["adx"]["adx"], 1),
                    "price": r["price"], "rr": round(r["rr"], 2),
                    "trend": r["trend"]["direction"],
                    "patterns": r["candle_patterns"],
                })
                await asyncio.sleep(REQUEST_DELAY)
            except Exception as e:
                logger.warning(f"Scan fail {sym}: {e}")
                results.append({
                    "symbol": sym, "signal": "ERROR", "confidence": 0,
                    "best_strategy": "N/A", "rsi": 50, "adx": 0,
                    "price": 0, "rr": 0, "trend": "unknown", "patterns": [],
                })

        results.sort(key=lambda x: (
            0 if x["signal"] in ("BUY","SELL") else 1, -x["confidence"]
        ))
        return results
