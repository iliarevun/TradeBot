"""
Market Analyzer v4 — Professional Grade Algorithm
══════════════════════════════════════════════════
Нові можливості:
  • Multi-Timeframe Confluence (MTF) — аналіз 3 ТФ одночасно
  • Order Flow Imbalance — виявлення дисбалансу попиту/пропозиції
  • Volume Profile — Point of Control (POC), Value Area
  • Smart Money Concepts (SMC) — Break of Structure, Change of Character
  • Liquidity Sweeps — виявлення зон ліквідності
  • Divergence Detection — RSI та MACD дивергенція
  • Dynamic Support/Resistance з силою (touches × volume)
  • Optimal Entry Zone (OEZ) — точна зона входу
  • Probability Score — статистична ймовірність руху
  • Risk-adjusted confidence з урахуванням всіх факторів
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

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _safe(v, default=0.0):
    try:
        f = float(v)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except Exception:
        return default

def _ok(df) -> bool:
    return df is not None and isinstance(df, pd.DataFrame) and len(df) >= 20

def _col(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s.astype(float)

def _arr(df, col):
    return _col(df, col).values.astype(float)


# ══════════════════════════════════════════════════════════════════════════════
#  MARKET ANALYZER v4
# ══════════════════════════════════════════════════════════════════════════════

class MarketAnalyzer:

    def __init__(self):
        self.dp = DataProvider()

    # ─────────────────────────────────────────────────────────────────────────
    #  БАЗОВІ ІНДИКАТОРИ
    # ─────────────────────────────────────────────────────────────────────────

    def _ema(self, s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    def _sma(self, s: pd.Series, n: int) -> pd.Series:
        return s.rolling(window=n, min_periods=1).mean()

    def _rsi(self, close: pd.Series, n=14) -> pd.Series:
        d = close.diff()
        g = d.clip(lower=0).ewm(span=n, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(span=n, adjust=False).mean()
        return (100 - 100 / (1 + g / l.replace(0, np.nan))).fillna(50)

    def _stoch_rsi(self, close: pd.Series, n=14, k=3, d=3):
        rsi = self._rsi(close, n)
        rmin = rsi.rolling(n, min_periods=1).min()
        rmax = rsi.rolling(n, min_periods=1).max()
        diff = (rmax - rmin).replace(0, np.nan)
        k_line = ((rsi - rmin) / diff * 100).fillna(50)
        d_line = k_line.rolling(d, min_periods=1).mean()
        return k_line, d_line

    def _atr(self, df: pd.DataFrame, n=14) -> pd.Series:
        h, l, pc = _col(df,"high"), _col(df,"low"), _col(df,"close").shift(1)
        tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
        return tr.ewm(span=n, adjust=False).mean()

    def _adx(self, df: pd.DataFrame, n=14) -> dict:
        h = _arr(df, "high"); l = _arr(df, "low"); c = _arr(df, "close")
        sz = len(c)
        pdm = np.zeros(sz); mdm = np.zeros(sz); tr = np.zeros(sz)
        for i in range(1, sz):
            up = h[i]-h[i-1]; dn = l[i-1]-l[i]
            pdm[i] = up if (up > dn and up > 0) else 0.0
            mdm[i] = dn if (dn > up and dn > 0) else 0.0
            tr[i]  = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))

        def _w(arr, p):
            r = np.zeros(len(arr))
            if p < len(arr): r[p] = arr[1:p+1].mean()
            for i in range(p+1, len(arr)):
                r[i] = (r[i-1]*(p-1)+arr[i])/p
            return r

        atr_w=_w(tr,n); pdm_w=_w(pdm,n); mdm_w=_w(mdm,n)
        with np.errstate(divide='ignore', invalid='ignore'):
            pdi = np.where(atr_w>1e-10, 100*pdm_w/atr_w, 0.0)
            mdi = np.where(atr_w>1e-10, 100*mdm_w/atr_w, 0.0)
            sm  = pdi+mdi
            dx  = np.where(sm>1e-10, 100*np.abs(pdi-mdi)/sm, 0.0)
        adx_arr = _w(dx, n)
        last_adx = _safe(adx_arr[-1])
        last_pdi = _safe(pdi[-1]); last_mdi = _safe(mdi[-1])
        return {"adx": last_adx, "plus_di": last_pdi, "minus_di": last_mdi,
                "strong": last_adx >= 25,
                "direction": "bullish" if last_pdi > last_mdi else "bearish"}

    def _macd(self, close: pd.Series):
        fast=self._ema(close,12); slow=self._ema(close,26)
        macd=fast-slow; signal=self._ema(macd,9)
        return macd, signal, macd-signal

    def _bollinger(self, close: pd.Series, n=20, k=2):
        mid=close.rolling(n,min_periods=1).mean()
        std=close.rolling(n,min_periods=1).std().fillna(0)
        return mid+k*std, mid, mid-k*std

    def _vwap(self, df: pd.DataFrame) -> Optional[float]:
        vol = _col(df, "volume")
        if vol.sum() < 1: return None
        tp = (_col(df,"high")+_col(df,"low")+_col(df,"close"))/3
        return _safe((tp*vol).sum()/vol.sum())

    def _williams_r(self, df: pd.DataFrame, n=14) -> pd.Series:
        h = _col(df,"high").rolling(n,min_periods=1).max()
        l = _col(df,"low").rolling(n,min_periods=1).min()
        diff = (h-l).replace(0, np.nan)
        return -100*(h-_col(df,"close"))/diff

    def _cci(self, df: pd.DataFrame, n=20) -> pd.Series:
        tp = (_col(df,"high")+_col(df,"low")+_col(df,"close"))/3
        ma = tp.rolling(n,min_periods=1).mean()
        md = tp.rolling(n,min_periods=1).apply(lambda x: np.abs(x-x.mean()).mean(), raw=True)
        return (tp-ma)/(0.015*md.replace(0,np.nan))

    # ─────────────────────────────────────────────────────────────────────────
    #  SMART MONEY CONCEPTS (SMC)
    # ─────────────────────────────────────────────────────────────────────────

    def _market_structure(self, df: pd.DataFrame) -> dict:
        """
        Break of Structure (BOS) та Change of Character (CHoCH).
        BOS = ціна пробиває попередній swing high/low в напрямку тренду.
        CHoCH = ціна пробиває структуру ПРОТИ тренду → розворот.
        """
        h = _arr(df, "high"); l = _arr(df, "low"); c = _arr(df, "close")
        n = len(c)
        if n < 20:
            return {"structure":"unknown","bos":False,"choch":False,"bias":"neutral"}

        # Знаходимо swing highs/lows (локальні екстремуми)
        swing_highs, swing_lows = [], []
        for i in range(3, n-3):
            if h[i] == max(h[i-3:i+4]):
                swing_highs.append((i, h[i]))
            if l[i] == min(l[i-3:i+4]):
                swing_lows.append((i, l[i]))

        if not swing_highs or not swing_lows:
            return {"structure":"unknown","bos":False,"choch":False,"bias":"neutral"}

        last_sh = swing_highs[-1][1] if swing_highs else h[-1]
        prev_sh = swing_highs[-2][1] if len(swing_highs)>1 else last_sh
        last_sl = swing_lows[-1][1]  if swing_lows  else l[-1]
        prev_sl = swing_lows[-2][1]  if len(swing_lows)>1  else last_sl

        last_close = c[-1]

        # Higher Highs + Higher Lows = uptrend
        hh = last_sh > prev_sh
        hl = last_sl > prev_sl
        # Lower Highs + Lower Lows = downtrend
        lh = last_sh < prev_sh
        ll = last_sl < prev_sl

        if hh and hl:   structure = "uptrend"
        elif lh and ll: structure = "downtrend"
        else:           structure = "ranging"

        # BOS: пробиття останнього swing high (bullish BOS) або low (bearish BOS)
        bos_bull = last_close > last_sh
        bos_bear = last_close < last_sl
        bos = bos_bull or bos_bear

        # CHoCH: зміна характеру ринку
        choch = False
        if structure == "uptrend"   and lh: choch = True  # попередній хай нижчий
        if structure == "downtrend" and hl: choch = True  # попередній лоу вищий

        # Order Blocks (останній великий рух перед BOS)
        ob_bull = None; ob_bear = None
        if bos_bull and len(swing_lows) >= 2:
            ob_bull = (last_sl, swing_lows[-2][1])  # зона між двома лоу
        if bos_bear and len(swing_highs) >= 2:
            ob_bear = (swing_highs[-2][1], last_sh)  # зона між двома хаями

        bias = "bullish" if (hh and hl) else ("bearish" if (lh and ll) else "neutral")

        return {
            "structure": structure, "bos": bos, "choch": choch, "bias": bias,
            "last_swing_high": last_sh, "last_swing_low": last_sl,
            "hh": hh, "hl": hl, "lh": lh, "ll": ll,
            "bos_bull": bos_bull, "bos_bear": bos_bear,
            "order_block_bull": ob_bull, "order_block_bear": ob_bear,
        }

    def _liquidity_zones(self, df: pd.DataFrame) -> dict:
        """
        Зони ліквідності: рівні де накопичились стопи (під swing lows / над swing highs).
        Smart money swept liquidity = сильний сигнал для розвороту.
        """
        h = _arr(df, "high"); l = _arr(df, "low"); c = _arr(df, "close")
        n = len(c); last_close = c[-1]; last_atr = _safe(self._atr(df).iloc[-1])

        # Збираємо всі swing highs/lows як зони ліквідності
        liq_highs, liq_lows = [], []
        for i in range(5, n-5):
            if h[i] == max(h[i-5:i+6]):
                liq_highs.append(h[i])
            if l[i] == min(l[i-5:i+6]):
                liq_lows.append(l[i])

        # Equal Highs/Lows (подвійна ліквідність) — найважливіші
        def find_equal(levels, tol=0.0005):
            equal = []
            for i in range(len(levels)-1):
                for j in range(i+1, len(levels)):
                    if abs(levels[i]-levels[j])/max(levels[i],1e-10) < tol:
                        equal.append((levels[i]+levels[j])/2)
            return equal

        eq_highs = find_equal(liq_highs[-10:])
        eq_lows  = find_equal(liq_lows[-10:])

        # Liquidity sweep: ціна вийшла за рівень ліквідності і повернулась
        swept_high = False; swept_low = False
        if liq_highs:
            recent_high = max(liq_highs[-5:])
            if h[-2] > recent_high and c[-1] < recent_high:  # spike and close below
                swept_high = True
        if liq_lows:
            recent_low = min(liq_lows[-5:])
            if l[-2] < recent_low and c[-1] > recent_low:  # spike and close above
                swept_low = True

        # Nearest liquidity above/below
        liq_above = min([x for x in liq_highs if x > last_close], default=None)
        liq_below = max([x for x in liq_lows  if x < last_close], default=None)

        return {
            "liq_above":    liq_above,
            "liq_below":    liq_below,
            "swept_high":   swept_high,   # ціна sweep вгорі → розворот вниз
            "swept_low":    swept_low,    # ціна sweep внизу → розворот вгору
            "equal_highs":  eq_highs,
            "equal_lows":   eq_lows,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  VOLUME PROFILE
    # ─────────────────────────────────────────────────────────────────────────

    def _volume_profile(self, df: pd.DataFrame, bins=20) -> dict:
        """
        Point of Control (POC) — ціновий рівень з найбільшим обсягом.
        Value Area High/Low (VAH/VAL) — 70% всього обсягу.
        """
        vol = _col(df, "volume")
        if vol.sum() < 1:
            return {"poc": None, "vah": None, "val": None, "above_poc": None}

        high = _col(df, "high"); low = _col(df, "low")
        price_min = float(low.min()); price_max = float(high.max())
        if price_max <= price_min:
            return {"poc": None, "vah": None, "val": None, "above_poc": None}

        bin_size = (price_max - price_min) / bins
        vol_profile = np.zeros(bins)

        for i in range(len(df)):
            v = float(vol.iloc[i])
            if v <= 0: continue
            h_i = float(high.iloc[i]); l_i = float(low.iloc[i])
            b_low  = max(0, int((l_i - price_min) / bin_size))
            b_high = min(bins-1, int((h_i - price_min) / bin_size))
            spread = b_high - b_low + 1
            for b in range(b_low, b_high+1):
                vol_profile[b] += v / spread

        poc_bin = int(np.argmax(vol_profile))
        poc = price_min + (poc_bin + 0.5) * bin_size

        # Value Area: 70% від загального обсягу навколо POC
        total_vol = vol_profile.sum()
        target = total_vol * 0.70
        va_low_bin = poc_bin; va_high_bin = poc_bin
        accumulated = vol_profile[poc_bin]
        while accumulated < target:
            expand_low  = va_low_bin  > 0
            expand_high = va_high_bin < bins-1
            if not expand_low and not expand_high: break
            add_low  = vol_profile[va_low_bin-1]  if expand_low  else 0
            add_high = vol_profile[va_high_bin+1] if expand_high else 0
            if add_high >= add_low and expand_high:
                va_high_bin += 1; accumulated += add_high
            elif expand_low:
                va_low_bin -= 1; accumulated += add_low
            else:
                va_high_bin += 1; accumulated += add_high

        vah = price_min + (va_high_bin+1)*bin_size
        val = price_min + va_low_bin*bin_size
        last_close = _safe(_col(df,"close").iloc[-1])

        return {
            "poc":        poc,
            "vah":        vah,
            "val":        val,
            "above_poc":  last_close > poc,
            "in_value":   val <= last_close <= vah,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  DIVERGENCE DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _divergence(self, df: pd.DataFrame) -> dict:
        """
        RSI та MACD дивергенція.
        Bullish: ціна робить нижчий лоу, RSI/MACD — вищий лоу → розворот вгору.
        Bearish: ціна робить вищий хай, RSI/MACD — нижчий хай → розворот вниз.
        """
        close = _col(df, "close")
        rsi   = self._rsi(close, 14)
        _, _, hist = self._macd(close)
        price = close.values; rsi_v = rsi.values; hist_v = hist.values
        n = len(price)

        bull_div_rsi = False; bear_div_rsi = False
        bull_div_macd= False; bear_div_macd= False

        if n >= 20:
            # Порівнюємо останні 2 значущі лоу/хаї
            seg1 = slice(n-20, n-10)
            seg2 = slice(n-10, n)

            # Bullish RSI divergence
            if (price[seg2].min() < price[seg1].min()
                    and rsi_v[seg2].min() > rsi_v[seg1].min()
                    and rsi_v[n-1] < 50):
                bull_div_rsi = True

            # Bearish RSI divergence
            if (price[seg2].max() > price[seg1].max()
                    and rsi_v[seg2].max() < rsi_v[seg1].max()
                    and rsi_v[n-1] > 50):
                bear_div_rsi = True

            # Bullish MACD divergence
            if (price[seg2].min() < price[seg1].min()
                    and hist_v[seg2].min() > hist_v[seg1].min()):
                bull_div_macd = True

            # Bearish MACD divergence
            if (price[seg2].max() > price[seg1].max()
                    and hist_v[seg2].max() < hist_v[seg1].max()):
                bear_div_macd = True

        return {
            "bull_rsi":  bull_div_rsi,
            "bear_rsi":  bear_div_rsi,
            "bull_macd": bull_div_macd,
            "bear_macd": bear_div_macd,
            "any_bull":  bull_div_rsi or bull_div_macd,
            "any_bear":  bear_div_rsi or bear_div_macd,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  ORDER FLOW IMBALANCE
    # ─────────────────────────────────────────────────────────────────────────

    def _order_flow(self, df: pd.DataFrame) -> dict:
        """
        Buying/Selling pressure через співвідношення тіл та тіней свічок.
        Висхідний дисбаланс = більше зеленого обсягу.
        """
        o = _arr(df,"open"); h = _arr(df,"high"); l = _arr(df,"low"); c = _arr(df,"close")
        vol = _arr(df,"volume")
        n = min(20, len(c))  # останні 20 свічок

        buy_vol  = 0.0; sell_vol = 0.0
        for i in range(-n, 0):
            v = vol[i] if vol[i] > 0 else 1.0
            rng = max(h[i]-l[i], 1e-10)
            # Частка бичачого руху
            bull_frac = (c[i]-l[i])/rng
            buy_vol  += v * bull_frac
            sell_vol += v * (1-bull_frac)

        total = buy_vol + sell_vol
        delta = (buy_vol - sell_vol) / max(total, 1e-10)  # -1..+1

        # Consecutive closes
        bull_streak = 0; bear_streak = 0
        for i in range(-1, -6, -1):
            if c[i] > o[i]: bull_streak += 1
            else: break
        for i in range(-1, -6, -1):
            if c[i] < o[i]: bear_streak += 1
            else: break

        # Large candle detection (останні 3 свічки)
        avg_body = np.mean([abs(c[i]-o[i]) for i in range(-10,-1)])
        last_body = abs(c[-1]-o[-1])
        large_candle = last_body > avg_body * 1.8
        large_bull   = large_candle and c[-1] > o[-1]
        large_bear   = large_candle and c[-1] < o[-1]

        return {
            "delta":        delta,          # >0 = buying pressure
            "bull_streak":  bull_streak,
            "bear_streak":  bear_streak,
            "large_bull":   large_bull,
            "large_bear":   large_bear,
            "bias": "bullish" if delta > 0.15 else ("bearish" if delta < -0.15 else "neutral"),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  DYNAMIC SUPPORT / RESISTANCE
    # ─────────────────────────────────────────────────────────────────────────

    def _find_levels(self, df: pd.DataFrame, window=8) -> dict:
        h = _arr(df,"high"); l = _arr(df,"low"); c = _arr(df,"close")
        vol = _arr(df,"volume"); total_vol = max(vol.sum(), 1.0)
        close = _safe(_col(df,"close").iloc[-1])

        supports, resistances = [], []
        for i in range(window, len(df)-window):
            vol_w = vol[max(0,i-2):i+3].sum() / total_vol
            if h[i] == float(np.max(h[i-window:i+window+1])):
                resistances.append({"price": float(h[i]), "vol_weight": vol_w})
            if l[i] == float(np.min(l[i-window:i+window+1])):
                supports.append({"price": float(l[i]), "vol_weight": vol_w})

        def cluster(raw, tol=0.0015):
            if not raw: return []
            raw.sort(key=lambda x: x["price"])
            result = [{"price": raw[0]["price"], "touches": 1, "strength": raw[0]["vol_weight"]}]
            for item in raw[1:]:
                ref = result[-1]["price"]
                if ref < 1e-10 or (item["price"]-ref)/ref > tol:
                    result.append({"price": item["price"], "touches": 1, "strength": item["vol_weight"]})
                else:
                    result[-1]["price"]    = (ref + item["price"]) / 2
                    result[-1]["touches"] += 1
                    result[-1]["strength"] += item["vol_weight"]
            return result

        sup_cl = cluster(supports); res_cl = cluster(resistances)

        sup_below = [s for s in sup_cl if s["price"] < close]
        res_above = [r for r in res_cl if r["price"] > close]
        ns_obj = max(sup_below, key=lambda x: x["price"]) if sup_below else None
        nr_obj = min(res_above, key=lambda x: x["price"]) if res_above else None

        ns = ns_obj["price"] if ns_obj else None
        nr = nr_obj["price"] if nr_obj else None

        # Fibonacci
        fib = {}
        if ns and nr and nr > ns and (nr-ns)/max(ns,1e-10) > 0.001:
            diff = nr - ns
            for ratio, lbl in [(0.236,"23.6%"),(0.382,"38.2%"),(0.500,"50.0%"),(0.618,"61.8%"),(0.786,"78.6%")]:
                fib[lbl] = ns + diff * ratio

        # Знаходимо 2-й рівень підтримки/опору (для TP2)
        ns2_obj = (sorted([s for s in sup_below if s["price"] < (ns or 0)],
                           key=lambda x: x["price"], reverse=True) or [None])[0]
        nr2_obj = (sorted([r for r in res_above if r["price"] > (nr or float("inf"))],
                           key=lambda x: x["price"]) or [None])[0]

        return {
            "supports":            [s["price"] for s in sup_cl],
            "resistances":         [r["price"] for r in res_cl],
            "nearest_support":     ns,
            "nearest_resistance":  nr,
            "support_strength":    ns_obj["touches"] if ns_obj else 0,
            "resistance_strength": nr_obj["touches"] if nr_obj else 0,
            "support2":            ns2_obj["price"] if ns2_obj else None,
            "resistance2":         nr2_obj["price"] if nr2_obj else None,
            "fib_levels":          fib,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  CANDLESTICK PATTERNS (14 штук)
    # ─────────────────────────────────────────────────────────────────────────

    def _patterns(self, df: pd.DataFrame) -> list:
        found = []
        if len(df) < 3: return found
        o=_arr(df,"open"); h=_arr(df,"high"); l=_arr(df,"low"); c=_arr(df,"close")
        n = len(c)-1
        def body(i): return abs(c[i]-o[i])
        def rng(i):  return h[i]-l[i]
        def up(i):   return h[i]-max(o[i],c[i])
        def dn(i):   return min(o[i],c[i])-l[i]
        def bull(i): return c[i]>o[i]
        def bear(i): return c[i]<o[i]
        if rng(n)<1e-10: return found
        if dn(n)>=0.6*rng(n) and body(n)<=0.35*rng(n): found.append("bullish_pinbar")
        if up(n)>=0.6*rng(n) and body(n)<=0.35*rng(n): found.append("bearish_pinbar")
        if body(n)>0 and dn(n)>=2*body(n) and up(n)<=0.15*rng(n): found.append("hammer")
        if body(n)>0 and up(n)>=2*body(n) and dn(n)<=0.15*rng(n): found.append("shooting_star")
        if (n>=1 and bear(n-1) and bull(n) and o[n]<=c[n-1] and c[n]>=o[n-1] and body(n)>body(n-1)*1.05):
            found.append("bullish_engulfing")
        if (n>=1 and bull(n-1) and bear(n) and o[n]>=c[n-1] and c[n]<=o[n-1] and body(n)>body(n-1)*1.05):
            found.append("bearish_engulfing")
        if body(n)<=0.07*rng(n): found.append("doji")
        if n>=1 and h[n]<=h[n-1] and l[n]>=l[n-1]: found.append("inside_bar")
        if (n>=2 and bear(n-2) and body(n-2)>0.5*rng(n-2) and body(n-1)<0.3*rng(n-1)
                and bull(n) and c[n]>(o[n-2]+c[n-2])/2): found.append("morning_star")
        if (n>=2 and bull(n-2) and body(n-2)>0.5*rng(n-2) and body(n-1)<0.3*rng(n-1)
                and bear(n) and c[n]<(o[n-2]+c[n-2])/2): found.append("evening_star")
        if (n>=2 and all(bull(n-i) for i in range(3)) and c[n]>c[n-1]>c[n-2]
                and all(body(n-i)>0.5*rng(n-i) for i in range(3))): found.append("three_white")
        if (n>=2 and all(bear(n-i) for i in range(3)) and c[n]<c[n-1]<c[n-2]
                and all(body(n-i)>0.5*rng(n-i) for i in range(3))): found.append("three_black")
        if (n>=1 and bear(n-1) and bull(n) and abs(l[n]-l[n-1])/max(rng(n),1e-10)<0.05):
            found.append("tweezer_bottom")
        if (n>=1 and bull(n-1) and bear(n) and abs(h[n]-h[n-1])/max(rng(n),1e-10)<0.05):
            found.append("tweezer_top")
        return found

    # ─────────────────────────────────────────────────────────────────────────
    #  TREND
    # ─────────────────────────────────────────────────────────────────────────

    def _trend(self, df: pd.DataFrame) -> dict:
        close=_col(df,"close")
        e21=self._ema(close,21); e50=self._ema(close,50); e200=self._ema(close,200)
        lc=_safe(close.iloc[-1]); l21=_safe(e21.iloc[-1]); l50=_safe(e50.iloc[-1]); l200=_safe(e200.iloc[-1])
        p21=_safe(e21.iloc[-2]); p50=_safe(e50.iloc[-2])
        e21_5=_safe(e21.iloc[-5]) if len(e21)>=5 else l21
        slope=(l21-e21_5)/max(e21_5,1e-10)*100

        if l21>l50>l200 and lc>l21:   direction,strength="bullish","strong"
        elif l21>l50 and lc>l50:       direction,strength="bullish","moderate"
        elif l21<l50<l200 and lc<l21:  direction,strength="bearish","strong"
        elif l21<l50 and lc<l50:       direction,strength="bearish","moderate"
        else:                           direction,strength="sideways","weak"

        crossover="none"
        if p21<=p50 and l21>l50:   crossover="bullish_cross"
        elif p21>=p50 and l21<l50: crossover="bearish_cross"

        return {"direction":direction,"strength":strength,"ema21":l21,"ema50":l50,
                "ema200":l200,"crossover":crossover,"slope_pct":slope}

    # ─────────────────────────────────────────────────────────────────────────
    #  MULTI-TIMEFRAME CONFLUENCE
    # ─────────────────────────────────────────────────────────────────────────

    def _mtf_score(self, trend_w: dict, trend_m: dict, trend_e: dict) -> dict:
        """
        Оцінка збігу трьох таймфреймів.
        trend_w = Weekly/Daily (старший)
        trend_m = H4/H1 (робочий)
        trend_e = H1/M30 (вхідний)
        """
        dirs = [trend_w["direction"], trend_m["direction"], trend_e["direction"]]
        bull_count = dirs.count("bullish")
        bear_count = dirs.count("bearish")

        if bull_count == 3: return {"score": 100, "direction": "BUY",   "label": "🟢 Всі 3 ТФ бичачі"}
        if bear_count == 3: return {"score": 100, "direction": "SELL",  "label": "🔴 Всі 3 ТФ ведмежі"}
        if bull_count == 2: return {"score": 65,  "direction": "BUY",   "label": "🟡 2/3 ТФ бичачі"}
        if bear_count == 2: return {"score": 65,  "direction": "SELL",  "label": "🟠 2/3 ТФ ведмежі"}
        return {"score": 0, "direction": "NEUTRAL", "label": "⚪ ТФ суперечать"}

    # ─────────────────────────────────────────────────────────────────────────
    #  OPTIMAL ENTRY ZONE (OEZ) — точка входу
    # ─────────────────────────────────────────────────────────────────────────

    def _optimal_entry(self, df: pd.DataFrame, direction: str, levels: dict,
                       trend: dict, vol_profile: dict, liq: dict) -> dict:
        """
        Розраховує оптимальну точку входу, SL та TP.

        Пріоритет для входу:
        1. Order Block (зона де Smart Money входили)
        2. Fibonacci 50-61.8% рівень (golden zone)
        3. EMA 21 (динамічна підтримка/опір)
        4. Найближчий рівень підтримки/опору
        5. Value Area Low/High (з Volume Profile)
        """
        close = _safe(_col(df,"close").iloc[-1])
        atr   = _safe(self._atr(df).iloc[-1])
        e21   = trend["ema21"]
        e50   = trend["ema50"]
        ns    = levels["nearest_support"]
        nr    = levels["nearest_resistance"]
        fib   = levels.get("fib_levels", {})
        poc   = vol_profile.get("poc")
        val   = vol_profile.get("val")
        vah   = vol_profile.get("vah")

        entry_zones = []  # список можливих зон входу (ціна, пріоритет, причина)

        if direction == "BUY":
            # 1. Golden Fib zone (50-61.8%)
            if "50.0%" in fib and "61.8%" in fib:
                mid = (fib["50.0%"]+fib["61.8%"])/2
                entry_zones.append((mid, 5, f"Golden Zone Fib 50-61.8% ({mid:.5f})"))

            # 2. EMA 21 як динамічна підтримка
            if e21 < close and abs(close-e21)/max(close,1e-10) < 0.015:
                entry_zones.append((e21, 4, f"EMA 21 підтримка ({e21:.5f})"))

            # 3. Value Area Low (покупець в зоні вартості)
            if val and val < close and abs(close-val)/max(close,1e-10) < 0.02:
                entry_zones.append((val, 4, f"Volume Value Area Low ({val:.5f})"))

            # 4. POC (Point of Control) — магнетична ціна
            if poc and poc < close:
                entry_zones.append((poc, 3, f"Volume POC ({poc:.5f})"))

            # 5. Nearest Support
            if ns:
                entry_zones.append((ns, 3, f"Підтримка ({ns:.5f})"))

            # 6. EMA 50
            if e50 < close:
                entry_zones.append((e50, 2, f"EMA 50 ({e50:.5f})"))

            # 7. Liquidity Below (зона де стопи зібрані)
            if liq.get("swept_low"):
                entry_zones.append((close, 5, "✅ Ліквідність знизу зібрана — сильний BUY"))

            # Обираємо найближчу зону до поточної ціни з найвищим пріоритетом
            if entry_zones:
                entry_zones.sort(key=lambda x: (-x[1], abs(close-x[0])))
                best_entry = entry_zones[0][0]
                entry_reason = entry_zones[0][2]
            else:
                best_entry = close
                entry_reason = "Поточна ціна"

            # SL: нижче найближчої підтримки + буфер 0.3 ATR
            if ns:
                sl = min(ns - atr*0.3, best_entry - atr*1.5)
            else:
                sl = best_entry - atr * 1.5

            sl_dist = abs(best_entry - sl)

            # TP1: наступний опір або 2R
            if nr:
                tp1 = min(best_entry + sl_dist*2, nr*0.999)
            else:
                tp1 = best_entry + sl_dist*2

            # TP2: другий опір або 3R
            nr2 = levels.get("resistance2")
            if nr2:
                tp2 = min(best_entry + sl_dist*3, nr2*0.999)
            else:
                tp2 = best_entry + sl_dist*3

            # TP3: 5R (swing high / повний рух)
            tp3 = best_entry + sl_dist*5

        else:  # SELL
            # 1. Golden Fib zone
            if "50.0%" in fib and "61.8%" in fib:
                mid = (fib["50.0%"]+fib["61.8%"])/2
                entry_zones.append((mid, 5, f"Golden Zone Fib 50-61.8% ({mid:.5f})"))

            # 2. EMA 21 як динамічний опір
            if e21 > close and abs(close-e21)/max(close,1e-10) < 0.015:
                entry_zones.append((e21, 4, f"EMA 21 опір ({e21:.5f})"))

            # 3. Value Area High
            if vah and vah > close and abs(close-vah)/max(close,1e-10) < 0.02:
                entry_zones.append((vah, 4, f"Volume Value Area High ({vah:.5f})"))

            # 4. POC
            if poc and poc > close:
                entry_zones.append((poc, 3, f"Volume POC ({poc:.5f})"))

            # 5. Nearest Resistance
            if nr:
                entry_zones.append((nr, 3, f"Опір ({nr:.5f})"))

            # 6. EMA 50
            if e50 > close:
                entry_zones.append((e50, 2, f"EMA 50 ({e50:.5f})"))

            # 7. Liquidity Sweep Above
            if liq.get("swept_high"):
                entry_zones.append((close, 5, "✅ Ліквідність зверху зібрана — сильний SELL"))

            if entry_zones:
                entry_zones.sort(key=lambda x: (-x[1], abs(close-x[0])))
                best_entry = entry_zones[0][0]
                entry_reason = entry_zones[0][2]
            else:
                best_entry = close
                entry_reason = "Поточна ціна"

            if nr:
                sl = max(nr + atr*0.3, best_entry + atr*1.5)
            else:
                sl = best_entry + atr*1.5

            sl_dist = abs(sl - best_entry)

            if ns:
                tp1 = max(best_entry - sl_dist*2, ns*1.001)
            else:
                tp1 = best_entry - sl_dist*2

            ns2 = levels.get("support2")
            if ns2:
                tp2 = max(best_entry - sl_dist*3, ns2*1.001)
            else:
                tp2 = best_entry - sl_dist*3

            tp3 = best_entry - sl_dist*5

        rr1 = abs(tp1-best_entry)/max(abs(sl-best_entry),1e-10)
        rr2 = abs(tp2-best_entry)/max(abs(sl-best_entry),1e-10)

        # Визначаємо тип входу
        dist_pct = abs(close-best_entry)/max(close,1e-10)*100
        if dist_pct < 0.1:
            entry_type = "MARKET"      # вхід за ринком зараз
            entry_label = "🔴 ЗАРАЗ (Market Order)"
        elif dist_pct < 0.5:
            entry_type = "LIMIT_CLOSE"  # лімітний ордер близько
            entry_label = f"🟡 LIMIT ордер ({best_entry:.5f})"
        else:
            entry_type = "LIMIT_WAIT"  # чекати відкату
            entry_label = f"⏳ ЧЕКАТИ відкату до {best_entry:.5f}"

        return {
            "entry":        best_entry,
            "entry_type":   entry_type,
            "entry_label":  entry_label,
            "entry_reason": entry_reason,
            "sl":           sl,
            "tp1":          tp1,
            "tp2":          tp2,
            "tp3":          tp3,
            "rr1":          rr1,
            "rr2":          rr2,
            "sl_pips":      abs(best_entry-sl)*10000,
            "zones":        [(z[0], z[2]) for z in entry_zones[:3]],
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  PROBABILITY SCORE
    # ─────────────────────────────────────────────────────────────────────────

    def _probability(self, signals: dict) -> dict:
        """
        Комплексна оцінка ймовірності руху на основі всіх сигналів.
        Кожен фактор має вагу, підсумок нормалізується до 0-100%.
        """
        score = 0; max_score = 0; factors = []

        def add(weight, condition, true_label, false_label=None, bonus=False):
            nonlocal score, max_score
            max_score += weight
            if condition:
                score += weight
                if true_label: factors.append(("✅", true_label, weight))
            elif false_label and not bonus:
                factors.append(("❌", false_label, 0))

        direction = signals.get("direction","NEUTRAL")
        trend     = signals.get("trend",{})
        ctx       = signals.get("ctx_trend",{})
        adx       = signals.get("adx",{})
        rsi       = signals.get("rsi",50)
        stoch_k   = signals.get("stoch_k",50)
        pats      = signals.get("patterns",[])
        div       = signals.get("divergence",{})
        smc       = signals.get("smc",{})
        liq       = signals.get("liquidity",{})
        of        = signals.get("order_flow",{})
        mtf       = signals.get("mtf",{})
        entry     = signals.get("entry",{})

        if direction == "NEUTRAL":
            return {"probability": 0, "factors": [], "grade": "F"}

        is_buy = direction == "BUY"

        # ── TREND ALIGNMENT (вага 25) ─────────────────────────────────────────
        add(15, trend["direction"]==(  "bullish" if is_buy else "bearish"),
            f"Тренд {'висхідний' if is_buy else 'низхідний'}", "Тренд проти напрямку")
        add(10, trend["strength"] in ("strong","moderate"),
            f"Сила тренду: {trend.get('strength','')}", "Тренд слабкий")

        # ── MTF CONFLUENCE (вага 20) ──────────────────────────────────────────
        mtf_dir = mtf.get("direction","NEUTRAL")
        mtf_scr = mtf.get("score",0)
        add(20, mtf_dir==direction and mtf_scr>=65,
            f"Multi-TF confluence: {mtf.get('label','')}", "Multi-TF не збігаються")

        # ── SMART MONEY (вага 15) ─────────────────────────────────────────────
        add(8, smc.get("bias")==("bullish" if is_buy else "bearish"),
            "SMC bias підтверджує")
        add(7, liq.get("swept_low" if is_buy else "swept_high", False),
            "✅ Ліквідність зібрана (Liquidity Sweep)")

        # ── ADX (вага 10) ─────────────────────────────────────────────────────
        add(10, adx.get("adx",0) >= 20,
            f"ADX {adx.get('adx',0):.0f} — тренд підтверджено", "ADX < 20 (слабкий)")

        # ── OSCILLATORS (вага 15) ─────────────────────────────────────────────
        add(8,  (rsi < 40 if is_buy else rsi > 60),
            f"RSI {rsi:.0f} {'перепроданий' if is_buy else 'перекуплений'}")
        add(7,  (stoch_k < 30 if is_buy else stoch_k > 70),
            f"Stoch RSI {stoch_k:.0f} — підтвердження")

        # ── DIVERGENCE (вага 10) ──────────────────────────────────────────────
        add(10, (div.get("any_bull") if is_buy else div.get("any_bear")),
            "Дивергенція RSI/MACD підтверджує розворот")

        # ── CANDLESTICK PATTERNS (вага 10) ────────────────────────────────────
        bull_strong = any(p in pats for p in ["bullish_engulfing","morning_star","three_white","bullish_pinbar","hammer"])
        bear_strong = any(p in pats for p in ["bearish_engulfing","evening_star","three_black","bearish_pinbar","shooting_star"])
        add(10, (bull_strong if is_buy else bear_strong),
            f"Сильний {'бичачий' if is_buy else 'ведмежий'} паттерн")

        # ── ORDER FLOW (вага 10) ──────────────────────────────────────────────
        add(6, of.get("bias")==("bullish" if is_buy else "bearish"),
            f"Order Flow дисбаланс {'купівля' if is_buy else 'продаж'}")
        add(4, (of.get("large_bull") if is_buy else of.get("large_bear")),
            "Велика імпульсна свічка підтверджує")

        # ── VOLUME PROFILE (вага 5) ───────────────────────────────────────────
        add(5, (entry.get("rr1",0) >= 2.0),
            f"RR ≥ 1:2 (RR = 1:{entry.get('rr1',0):.1f})", "RR < 1:2 — невигідно")

        probability = int(score / max(max_score,1) * 100)

        # Grade
        if probability >= 80: grade = "A+ (Відмінний сигнал)"
        elif probability >= 65: grade = "A  (Сильний сигнал)"
        elif probability >= 50: grade = "B  (Помірний сигнал)"
        elif probability >= 35: grade = "C  (Слабкий сигнал)"
        else:                   grade = "D  (Не торгувати)"

        return {
            "probability": probability,
            "score":       score,
            "max_score":   max_score,
            "factors":     factors,
            "grade":       grade,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  SESSION
    # ─────────────────────────────────────────────────────────────────────────

    def _session(self) -> dict:
        hour = datetime.now(timezone.utc).hour
        if 7 <= hour < 10:   name="London Open 🇬🇧 (найкращий час)";   quality=100
        elif 12 <= hour < 16: name="NY Session 🗽 (відмінний час)";     quality=95
        elif 10 <= hour < 12: name="London+NY Overlap 🔥 (пік)";        quality=100
        elif 0 <= hour < 7:   name="Азіатська сесія 🌏 (тихо)";         quality=60
        elif 16 <= hour < 21: name="NY Afternoon (помірно)";             quality=70
        else:                  name="Міжсесійний час 😴 (уникати)";      quality=30
        return {"name": name, "quality": quality, "hour_utc": hour}

    # ─────────────────────────────────────────────────────────────────────────
    #  MAIN ANALYZE
    # ─────────────────────────────────────────────────────────────────────────

    async def analyze(self, symbol: str, tf: str, strategy: str = "all") -> dict:
        # ── Дані: 3 таймфрейми ───────────────────────────────────────────────
        df = await self.dp.get_ohlcv(symbol, tf)
        if not _ok(df):
            raise ValueError(f"Недостатньо даних для {symbol} на {tf}.")

        ctx_tf   = CONTEXT_TIMEFRAMES.get(tf, "1d")
        df_ctx   = await self.dp.get_ohlcv(symbol, ctx_tf)

        # Третій ТФ (ще старший) для MTF
        ctx2_tf_map = {"1h":"1wk","4h":"1wk","1d":"1wk","15m":"1d","30m":"1d","5m":"4h"}
        ctx2_tf  = ctx2_tf_map.get(tf, "1wk")
        df_ctx2  = await self.dp.get_ohlcv(symbol, ctx2_tf)

        close = _col(df, "close")

        # ── Всі індикатори ────────────────────────────────────────────────────
        rsi_s            = self._rsi(close, RSI_PERIOD)
        stoch_k, stoch_d = self._stoch_rsi(close)
        atr_s            = self._atr(df, ATR_PERIOD)
        _, _, hist       = self._macd(close)
        bb_up,bb_mid,bb_low = self._bollinger(close)
        adx_d            = self._adx(df)
        willy            = self._williams_r(df)
        cci_s            = self._cci(df)
        vwap_val         = self._vwap(df)

        trend     = self._trend(df)
        ctx_trend = self._trend(df_ctx)  if _ok(df_ctx)  else trend
        ctx2_trend= self._trend(df_ctx2) if _ok(df_ctx2) else ctx_trend
        levels    = self._find_levels(df)
        pats      = self._patterns(df)
        smc       = self._market_structure(df)
        liq       = self._liquidity_zones(df)
        vol_prof  = self._volume_profile(df)
        div       = self._divergence(df)
        of        = self._order_flow(df)
        session   = self._session()

        last_close  = _safe(close.iloc[-1])
        last_rsi    = _safe(rsi_s.iloc[-1], 50)
        last_stoch  = _safe(stoch_k.iloc[-1], 50)
        last_atr    = _safe(atr_s.iloc[-1])
        last_hist   = _safe(hist.iloc[-1])
        last_willy  = _safe(willy.iloc[-1], -50)
        last_cci    = _safe(cci_s.iloc[-1], 0)

        # ── MTF confluence ────────────────────────────────────────────────────
        mtf = self._mtf_score(ctx2_trend, ctx_trend, trend)

        # ── Визначення напрямку через всі сигнали ─────────────────────────────
        buy_signals  = 0; sell_signals = 0

        # Trend (вага 3)
        if trend["direction"] == "bullish":    buy_signals  += 3
        elif trend["direction"] == "bearish":  sell_signals += 3

        # SMC bias (вага 3)
        if smc["bias"] == "bullish":   buy_signals  += 3
        elif smc["bias"] == "bearish": sell_signals += 3

        # MTF (вага 4)
        if mtf["direction"] == "BUY":    buy_signals  += 4
        elif mtf["direction"] == "SELL": sell_signals += 4

        # ADX direction (вага 2)
        if adx_d["direction"] == "bullish":   buy_signals  += 2
        elif adx_d["direction"] == "bearish": sell_signals += 2

        # Oscillators (вага 2)
        if last_rsi < 45:    buy_signals  += 2
        elif last_rsi > 55:  sell_signals += 2
        if last_stoch < 40:  buy_signals  += 1
        elif last_stoch > 60: sell_signals += 1

        # MACD (вага 2)
        if last_hist > 0:  buy_signals  += 2
        elif last_hist < 0: sell_signals += 2

        # Divergence (вага 3)
        if div["any_bull"]: buy_signals  += 3
        if div["any_bear"]: sell_signals += 3

        # Liquidity sweep (вага 4 — найсильніший)
        if liq["swept_low"]:  buy_signals  += 4
        if liq["swept_high"]: sell_signals += 4

        # Order flow (вага 2)
        if of["bias"] == "bullish":   buy_signals  += 2
        elif of["bias"] == "bearish": sell_signals += 2

        # Patterns (вага 2)
        bull_pats = ("bullish_pinbar","bullish_engulfing","hammer","morning_star","three_white","tweezer_bottom")
        bear_pats = ("bearish_pinbar","bearish_engulfing","shooting_star","evening_star","three_black","tweezer_top")
        if any(p in pats for p in bull_pats): buy_signals  += 2
        if any(p in pats for p in bear_pats): sell_signals += 2

        # Williams %R (вага 1)
        if last_willy < -80:  buy_signals  += 1
        elif last_willy > -20: sell_signals += 1

        # CCI (вага 1)
        if last_cci < -100:  buy_signals  += 1
        elif last_cci > 100: sell_signals += 1

        total_sig = buy_signals + sell_signals
        if total_sig == 0:
            direction = "NEUTRAL"; raw_conf = 0
        elif buy_signals > sell_signals:
            direction = "BUY";  raw_conf = int(buy_signals/total_sig*100)
        else:
            direction = "SELL"; raw_conf = int(sell_signals/total_sig*100)

        # ── Optimal Entry ─────────────────────────────────────────────────────
        if direction != "NEUTRAL":
            entry_data = self._optimal_entry(df, direction, levels, trend, vol_prof, liq)
        else:
            entry_data = {
                "entry": last_close, "entry_type": "NONE",
                "entry_label": "Немає входу", "entry_reason": "",
                "sl": last_close, "tp1": last_close, "tp2": last_close, "tp3": last_close,
                "rr1": 0, "rr2": 0, "sl_pips": 0, "zones": [],
            }

        # ── Probability Score ─────────────────────────────────────────────────
        prob_input = {
            "direction": direction, "trend": trend, "ctx_trend": ctx_trend,
            "adx": adx_d, "rsi": last_rsi, "stoch_k": last_stoch,
            "patterns": pats, "divergence": div, "smc": smc,
            "liquidity": liq, "order_flow": of, "mtf": mtf,
            "entry": entry_data,
        }
        prob = self._probability(prob_input)

        # ── Confidence (фінальна впевненість) ─────────────────────────────────
        confidence = prob["probability"]

        # Штраф за погану сесію
        if session["quality"] < 60 and direction != "NEUTRAL":
            confidence = max(confidence - 15, 0)
        elif session["quality"] < 80:
            confidence = max(confidence - 5, 0)

        # Бонус за BOS (Break of Structure)
        if smc["bos"] and direction != "NEUTRAL":
            confidence = min(confidence + 8, 100)

        # CHoCH — підвищений ризик розвороту
        if smc["choch"]:
            confidence = max(confidence - 10, 0)

        # Штраф за поганий RR
        if entry_data["rr1"] < 1.5:
            confidence = max(confidence - 20, 0)

        return {
            # Основні
            "symbol": symbol, "timeframe": tf, "context_tf": ctx_tf,
            "price": last_close, "direction": direction, "confidence": confidence,

            # Індикатори
            "trend": trend, "ctx_trend": ctx_trend, "ctx2_trend": ctx2_trend,
            "adx": adx_d, "rsi": last_rsi, "stoch_k": last_stoch,
            "stoch_d": _safe(stoch_d.iloc[-1], 50),
            "macd_hist": last_hist, "williams_r": last_willy, "cci": last_cci,
            "bb_upper": _safe(bb_up.iloc[-1]), "bb_lower": _safe(bb_low.iloc[-1]),
            "vwap": vwap_val, "atr": last_atr,

            # Аналіз
            "levels": levels, "vol_profile": vol_prof,
            "smc": smc, "liquidity": liq, "divergence": div, "order_flow": of,
            "mtf": mtf, "session": session,
            "candle_patterns": pats,

            # Вхід
            "entry": entry_data,
            "sl":  entry_data["sl"],
            "tp1": entry_data["tp1"],
            "tp2": entry_data["tp2"],
            "tp3": entry_data["tp3"],
            "rr":  entry_data["rr1"],

            # Ймовірність
            "probability": prob,

            "timestamp": datetime.now(),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  SCAN
    # ─────────────────────────────────────────────────────────────────────────

    async def scan_market(self, symbols: list, tf="1h") -> list:
        results = []
        for sym in symbols:
            try:
                r = await self.analyze(sym, tf, "all")
                results.append({
                    "symbol":      sym,
                    "signal":      r["direction"],
                    "confidence":  r["confidence"],
                    "probability": r["probability"]["probability"],
                    "grade":       r["probability"]["grade"],
                    "entry":       r["entry"]["entry"],
                    "entry_label": r["entry"]["entry_label"],
                    "sl":          r["sl"], "tp1": r["tp1"],
                    "rr":          round(r["rr"],2),
                    "rsi":         round(r["rsi"],1),
                    "adx":         round(r["adx"]["adx"],1),
                    "trend":       r["trend"]["direction"],
                    "patterns":    r["candle_patterns"],
                    "liq_sweep":   r["liquidity"]["swept_low"] or r["liquidity"]["swept_high"],
                    "divergence":  r["divergence"]["any_bull"] or r["divergence"]["any_bear"],
                    "mtf":         r["mtf"]["label"],
                })
                await asyncio.sleep(REQUEST_DELAY)
            except Exception as e:
                logger.warning(f"Scan fail {sym}: {e}")
                results.append({
                    "symbol": sym, "signal": "ERROR", "confidence": 0,
                    "probability": 0, "grade": "—", "entry": 0,
                    "entry_label": "—", "sl": 0, "tp1": 0, "rr": 0,
                    "rsi": 50, "adx": 0, "trend": "unknown",
                    "patterns": [], "liq_sweep": False, "divergence": False, "mtf": "—",
                })
        results.sort(key=lambda x: (
            0 if x["signal"] in ("BUY","SELL") else 1,
            -x["probability"]
        ))
        return results
