"""
binance_client.py
-----------------
Client per i dati di mercato pubblici di Binance Futures (USDM).

Tutti gli endpoint usati qui sono PUBBLICI: non serve API key per i market data.
La key (se presente) alza solo i rate limit. Per iniziare puoi lasciarla vuota.

Endpoint coperti:
  - klines           -> OHLCV (per VWAP, Volume Profile)
  - funding rate     -> regime funding
  - open interest    -> OI corrente + storico
  - taker buy/sell   -> Buy/Sell Volume Ratio (BSVR)
  - aggTrades        -> per CVD ad alta precisione (opzionale)

Docs: https://developers.binance.com/docs/derivatives/usds-margined-futures
"""

import time
import requests
from typing import Optional


class BinanceClient:
    FAPI = "https://fapi.binance.com"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 10):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"X-MBX-APIKEY": api_key})

    # ----------------------------------------------------------------- #
    # Helper interno con retry + gestione errori base
    # ----------------------------------------------------------------- #
    def _get(self, path: str, params: dict, retries: int = 3) -> any:
        url = f"{self.FAPI}{path}"
        last_err = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                # 429 = rate limit, 418 = ban temporaneo: aspetta e riprova
                if r.status_code in (429, 418):
                    wait = int(r.headers.get("Retry-After", 2 ** attempt))
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Binance GET {path} fallito dopo {retries} tentativi: {last_err}")

    # ----------------------------------------------------------------- #
    # OHLCV - il dato fondamentale per Volume Profile e VWAP
    # ----------------------------------------------------------------- #
    def klines(self, symbol: str = "BTCUSDT", interval: str = "15m",
               limit: int = 300) -> list[dict]:
        """
        Restituisce le candele OHLCV.
        interval: 1m,5m,15m,1h,4h,1d,1w ...
        limit: max 1500.

        Ritorna lista di dict con campi gia' convertiti a float:
        time(open_ms), open, high, low, close, volume,
        taker_buy_volume (utile per un CVD approssimato per candela).
        """
        raw = self._get("/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        out = []
        for k in raw:
            out.append({
                "time": int(k[0]),          # open time in ms
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": int(k[6]),
                "quote_volume": float(k[7]),
                "trades": int(k[8]),
                "taker_buy_volume": float(k[9]),
                "taker_buy_quote_volume": float(k[10]),
            })
        return out

    # ----------------------------------------------------------------- #
    # Funding Rate
    # ----------------------------------------------------------------- #
    def funding_rate(self, symbol: str = "BTCUSDT", limit: int = 1) -> list[dict]:
        """Storico funding rate. limit=1 -> ultimo valore."""
        raw = self._get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
        return [{"time": int(x["fundingTime"]),
                 "rate": float(x["fundingRate"])} for x in raw]

    def premium_index(self, symbol: str = "BTCUSDT") -> dict:
        """Mark price + funding rate corrente (previsto)."""
        x = self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        return {
            "mark_price": float(x["markPrice"]),
            "index_price": float(x["indexPrice"]),
            "last_funding_rate": float(x["lastFundingRate"]),
            "time": int(x["time"]),
        }

    # ----------------------------------------------------------------- #
    # Open Interest (corrente e storico)
    # ----------------------------------------------------------------- #
    def open_interest(self, symbol: str = "BTCUSDT") -> dict:
        """OI corrente (in contratti BTC)."""
        x = self._get("/fapi/v1/openInterest", {"symbol": symbol})
        return {"oi": float(x["openInterest"]), "time": int(x["time"])}

    def open_interest_hist(self, symbol: str = "BTCUSDT", period: str = "15m",
                           limit: int = 30) -> list[dict]:
        """
        Storico OI. period: 5m,15m,30m,1h,2h,4h,6h,12h,1d.
        Nota: endpoint /futures/data/ (non /fapi/v1/).
        """
        raw = self._get("/futures/data/openInterestHist", {
            "symbol": symbol, "period": period, "limit": limit
        })
        return [{"time": int(x["timestamp"]),
                 "oi": float(x["sumOpenInterest"]),
                 "oi_value": float(x["sumOpenInterestValue"])} for x in raw]

    # ----------------------------------------------------------------- #
    # Taker Buy/Sell Volume Ratio (BSVR)
    # ----------------------------------------------------------------- #
    def taker_ratio(self, symbol: str = "BTCUSDT", period: str = "15m",
                    limit: int = 30) -> list[dict]:
        """
        Buy/Sell Volume Ratio dei taker (il BSVR del tuo template).
        Ritorna buy_vol, sell_vol e il ratio buy/sell.
        """
        raw = self._get("/futures/data/takerlongshortRatio", {
            "symbol": symbol, "period": period, "limit": limit
        })
        return [{"time": int(x["timestamp"]),
                 "buy_vol": float(x["buyVol"]),
                 "sell_vol": float(x["sellVol"]),
                 "ratio": float(x["buySellRatio"])} for x in raw]

    # ----------------------------------------------------------------- #
    # aggTrades - per un CVD ad alta precisione (opzionale, pesante)
    # ----------------------------------------------------------------- #
    def agg_trades(self, symbol: str = "BTCUSDT", limit: int = 1000) -> list[dict]:
        """
        Trade aggregati recenti. Il flag 'm' indica se il buyer e' market maker:
          m=True  -> trade aggressivo in VENDITA (taker sell)
          m=False -> trade aggressivo in ACQUISTO (taker buy)
        Usato per calcolare il CVD tick-by-tick. limit max 1000.
        """
        raw = self._get("/fapi/v1/aggTrades", {"symbol": symbol, "limit": limit})
        return [{"price": float(x["p"]), "qty": float(x["q"]),
                 "time": int(x["T"]), "is_sell": bool(x["m"])} for x in raw]


if __name__ == "__main__":
    # Smoke test rapido del client
    c = BinanceClient()
    kl = c.klines("BTCUSDT", "15m", 5)
    print("Ultima candela 15m:", kl[-1])
    print("Funding:", c.funding_rate()[-1])
    print("OI:", c.open_interest())
    print("Taker ratio:", c.taker_ratio(limit=1)[-1])
