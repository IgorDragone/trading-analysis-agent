"""
spot_client.py
--------------
Client per i dati SPOT, che completano il quadro dei derivati.

Perche' serve: il CVD sui perpetual dice come si muove la leva, non se c'e'
denaro reale dietro. La conferma (o la divergenza) dello spot e' l'elemento che
distingue un trend genuino da una costruzione speculativa — ed e' esattamente
quello che l'Agente 2 oggi non puo' verificare.

Due fonti, entrambe PUBBLICHE (nessuna API key):
  - Binance SPOT  -> klines spot, per il CVD spot
  - Coinbase      -> prezzo BTC-USD, per il premio Coinbase

Il PREMIO COINBASE e' la differenza percentuale tra il prezzo su Coinbase (dove
comprano prevalentemente istituzionali e retail USA) e quello su Binance spot.
Positivo = domanda USA/istituzionale presente; negativo = possibile distribuzione.

Docs:
  https://developers.binance.com/docs/binance-spot-api-docs
  https://docs.cdp.coinbase.com/exchange/reference
"""

import time
import requests


class SpotClient:
    BINANCE_SPOT = "https://api.binance.com"
    COINBASE = "https://api.exchange.coinbase.com"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()

    # ----------------------------------------------------------------- #
    def _get(self, base: str, path: str, params: dict | None = None,
             retries: int = 3):
        url = f"{base}{path}"
        last_err = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params or {}, timeout=self.timeout)
                if r.status_code in (429, 418):
                    wait = int(r.headers.get("Retry-After", 2 ** attempt))
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"GET {url} fallito dopo {retries} tentativi: {last_err}")

    # ----------------------------------------------------------------- #
    # Binance SPOT: stesse candele del perp, ma sul mercato a pronti
    # ----------------------------------------------------------------- #
    def spot_klines(self, symbol: str = "BTCUSDT", interval: str = "15m",
                    limit: int = 300) -> list[dict]:
        """
        Candele SPOT nello stesso formato di BinanceClient.klines(), cosi' i
        moduli engine (cvd_metrics, ecc.) funzionano senza modifiche.
        """
        raw = self._get(self.BINANCE_SPOT, "/api/v3/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        out = []
        for k in raw:
            out.append({
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": int(k[6]),
                "quote_volume": float(k[7]),
                "trades": int(k[8]),
                "taker_buy_volume": float(k[9]),
                "taker_buy_quote": float(k[10]),
            })
        return out

    def spot_price(self, symbol: str = "BTCUSDT") -> float:
        d = self._get(self.BINANCE_SPOT, "/api/v3/ticker/price", {"symbol": symbol})
        return float(d["price"])

    # ----------------------------------------------------------------- #
    # Coinbase: prezzo di riferimento per il premio
    # ----------------------------------------------------------------- #
    def coinbase_price(self, product: str = "BTC-USD") -> float:
        d = self._get(self.COINBASE, f"/products/{product}/ticker")
        return float(d["price"])

    # ----------------------------------------------------------------- #
    def coinbase_premium(self, symbol: str = "BTCUSDT",
                         product: str = "BTC-USD") -> dict:
        """
        Premio Coinbase in percentuale.

        NOTA sull'accuratezza: Binance quota in USDT e Coinbase in USD. Il
        depeg di USDT (di norma pochi centesimi di punto) entra quindi nel
        numero. Va letto come indicatore di DIREZIONE e di variazione nel
        tempo, non come misura assoluta al decimale.
        """
        cb = self.coinbase_price(product)
        bn = self.spot_price(symbol)
        premium_pct = (cb - bn) / bn * 100 if bn else 0.0
        return {
            "coinbase_price": cb,
            "binance_spot_price": bn,
            "premium_pct": round(premium_pct, 4),
            "direction": "positivo" if premium_pct > 0 else ("negativo" if premium_pct < 0 else "neutro"),
        }
