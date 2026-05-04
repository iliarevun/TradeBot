"""
Data Provider v2 — з rate limiting та кешуванням
Ліміт Twelve Data Free: 8 req/хв → черга + затримка
"""
import asyncio, aiohttp, logging, time
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
from config import TWELVE_DATA_KEY, ALPHA_VANTAGE_KEY, CANDLES_COUNT

logger = logging.getLogger(__name__)

TD_TF  = {"5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h","1d":"1day","1wk":"1week"}
AV_TF  = {"5m":"5min","15m":"15min","30m":"30min","1h":"60min"}
YF_TF  = {"5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1wk":"1wk"}
YF_PER = {"5m":"5d","15m":"15d","30m":"30d","1h":"60d","4h":"180d","1d":"365d","1wk":"730d"}

def _ok(df) -> bool:
    return df is not None and isinstance(df, pd.DataFrame) and len(df) >= 20

def _sanitize(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1) if df.columns.nlevels == 2 else df
    df.columns = [str(c).lower() for c in df.columns]
    df = df.rename(columns={
        "1. open":"open","2. high":"high","3. low":"low","4. close":"close",
        "adj close":"close","adjclose":"close",
    })
    for col in ["open","high","low","close"]:
        if col not in df.columns: return None
    if "volume" not in df.columns: df["volume"] = 0.0
    df = df[["open","high","low","close","volume"]].copy()
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open","high","low","close"])
    if len(df) < 20: return None
    return df.reset_index(drop=True).tail(CANDLES_COUNT)

def normalize_symbol(symbol: str, provider: str) -> str:
    YF_MAP = {
        "EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X",
        "USDCHF":"USDCHF=X","AUDUSD":"AUDUSD=X","NZDUSD":"NZDUSD=X",
        "USDCAD":"USDCAD=X","EURGBP":"EURGBP=X",
    }
    base = symbol.replace("=X","").replace("-USD","").replace("/","").upper()
    if provider == "yfinance":
        return YF_MAP.get(base, symbol)
    if provider in ("twelvedata","alphavantage"):
        crypto = ("BTC","ETH","BNB","SOL","XRP","ADA","DOT","AVAX")
        forex  = ("EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","EURGBP")
        if any(base.startswith(c) for c in crypto): return base[:3]+"/USD"
        if base in forex: return base[:3]+"/"+base[3:]
        if base in ("GCF","GCUSD","XAU"): return "XAU/USD"
        return base
    return symbol


class DataProvider:
    # ── Rate limiter для Twelve Data (8 req/хв) ──────────────────────────────
    _td_timestamps: list = []
    _td_lock = asyncio.Lock()
    TD_MAX_PER_MIN = 7  # залишаємо запас 1

    def __init__(self):
        self._cache: dict = {}
        self._cache_time: dict = {}

    def _cache_key(self, sym, tf): return f"{sym}_{tf}"

    def _is_cached(self, key, ttl=300):
        if key in self._cache and key in self._cache_time:
            return (datetime.now()-self._cache_time[key]).total_seconds() < ttl
        return False

    async def _td_rate_limit(self):
        """Чекаємо якщо перевищено ліміт Twelve Data"""
        async with DataProvider._td_lock:
            now = time.time()
            # Прибираємо старіші за 60 сек
            DataProvider._td_timestamps = [t for t in DataProvider._td_timestamps if now-t < 60]
            if len(DataProvider._td_timestamps) >= self.TD_MAX_PER_MIN:
                oldest = DataProvider._td_timestamps[0]
                wait   = 61 - (now - oldest)
                if wait > 0:
                    logger.info(f"TwelveData rate limit: чекаємо {wait:.1f}s")
                    await asyncio.sleep(wait)
                DataProvider._td_timestamps = []
            DataProvider._td_timestamps.append(time.time())

    async def get_ohlcv(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        key = self._cache_key(symbol, tf)
        ttl = 300 if tf in ("5m","15m","30m") else 1800
        if self._is_cached(key, ttl):
            return self._cache[key]
        df = None

        # ── Twelve Data ──────────────────────────────────────────────────────
        if TWELVE_DATA_KEY:
            try:
                await self._td_rate_limit()
                raw = await self._twelve_data(symbol, tf)
                df  = _sanitize(raw)
                if _ok(df): logger.info(f"TwelveData OK: {symbol} {tf} ({len(df)} bars)")
                else:        df = None
            except Exception as e:
                logger.warning(f"TwelveData fail {symbol}: {e}")
                df = None

        # ── Alpha Vantage ────────────────────────────────────────────────────
        if ALPHA_VANTAGE_KEY and not _ok(df) and tf in AV_TF:
            try:
                raw = await self._alpha_vantage(symbol, tf)
                df  = _sanitize(raw)
                if _ok(df): logger.info(f"AlphaVantage OK: {symbol} {tf}")
                else:        df = None
            except Exception as e:
                logger.warning(f"AlphaVantage fail {symbol}: {e}")
                df = None

        # ── yfinance fallback ────────────────────────────────────────────────
        if not _ok(df):
            try:
                raw = await self._yfinance(symbol, tf)
                df  = _sanitize(raw)
                if _ok(df): logger.info(f"yfinance OK: {symbol} {tf}")
                else:        df = None
            except Exception as e:
                logger.warning(f"yfinance fail {symbol}: {e}")
                df = None

        if _ok(df):
            self._cache[key] = df
            self._cache_time[key] = datetime.now()
        return df if _ok(df) else None

    async def _twelve_data(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        sym = normalize_symbol(symbol, "twelvedata")
        url = (f"https://api.twelvedata.com/time_series"
               f"?symbol={sym}&interval={TD_TF.get(tf,'1h')}"
               f"&outputsize={CANDLES_COUNT}&apikey={TWELVE_DATA_KEY}&format=JSON")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url) as resp:
                data = await resp.json()
        if "values" not in data:
            raise ValueError(f"TD error: {data.get('message','no values')}")
        rows = [{"open":float(v["open"]),"high":float(v["high"]),"low":float(v["low"]),
                 "close":float(v["close"]),"volume":float(v.get("volume",0))}
                for v in reversed(data["values"])]
        return pd.DataFrame(rows)

    async def _alpha_vantage(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        sym      = normalize_symbol(symbol, "alphavantage")
        interval = AV_TF.get(tf,"60min")
        base     = symbol.replace("=X","").replace("-USD","").upper()
        is_forex = base in ("EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","EURGBP")
        if is_forex and tf == "1d":
            f_s, t_s = sym[:3], sym[4:]
            url = (f"https://www.alphavantage.co/query?function=FX_DAILY"
                   f"&from_symbol={f_s}&to_symbol={t_s}&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}")
            ts_key = "Time Series FX (Daily)"
        elif is_forex:
            f_s, t_s = sym[:3], sym[4:]
            url = (f"https://www.alphavantage.co/query?function=FX_INTRADAY"
                   f"&from_symbol={f_s}&to_symbol={t_s}&interval={interval}&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}")
            ts_key = f"Time Series FX ({interval})"
        else:
            return None
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url) as resp:
                data = await resp.json()
        if ts_key not in data:
            raise ValueError(f"AV: {list(data.keys())}")
        rows = [{"open":float(v.get("1. open",v.get("open",0))),
                 "high":float(v.get("2. high",v.get("high",0))),
                 "low":float(v.get("3. low",v.get("low",0))),
                 "close":float(v.get("4. close",v.get("close",0))),
                 "volume":0.0} for _,v in sorted(data[ts_key].items())]
        return pd.DataFrame(rows)

    async def _yfinance(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._yf_dl, symbol, tf)

    def _yf_dl(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            sym = normalize_symbol(symbol, "yfinance")
            df  = yf.Ticker(sym).history(period=YF_PER.get(tf,"60d"), interval=YF_TF.get(tf,"1h"))
            if df is None or (isinstance(df,pd.DataFrame) and df.empty): return None
            if tf == "4h":
                df = df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            return df
        except Exception as e:
            logger.error(f"yf {symbol} {tf}: {e}")
            return None

    def clear_cache(self): self._cache.clear(); self._cache_time.clear()
