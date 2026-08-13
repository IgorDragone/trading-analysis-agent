"""
deribit_client.py
-----------------
Client per i dati pubblici di Deribit: catena opzioni BTC (per il GEX) e DVOL
(indice di volatilita' implicita a 30 giorni, il "VIX di Bitcoin").

Tutti gli endpoint usati sono PUBBLICI: nessuna API key, nessun account.

Endpoint:
  /public/get_book_summary_by_currency  -> tutte le opzioni con OI e mark IV,
                                           in UNA sola chiamata (efficiente)
  /public/get_index_price               -> prezzo indice BTC
  /public/get_volatility_index_data     -> storico DVOL

CADENZA: il GEX si muove lentamente (il posizionamento in opzioni cambia in ore,
non in secondi). Una raccolta ogni ora e' abbondante; ogni 6h sarebbe accettabile.
Non ha senso interrogarlo a ogni tick.

Docs: https://docs.deribit.com/
"""

import time
import requests
from datetime import datetime, timezone


class DeribitClient:
    BASE = "https://www.deribit.com/api/v2"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path: str, params: dict | None = None, retries: int = 3):
        url = f"{self.BASE}{path}"
        last_err = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params or {}, timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", 2 ** attempt)))
                    continue
                r.raise_for_status()
                return r.json().get("result")
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Deribit GET {path} fallito dopo {retries} tentativi: {last_err}")

    # ----------------------------------------------------------------- #
    def index_price(self, index_name: str = "btc_usd") -> float:
        d = self._get("/public/get_index_price", {"index_name": index_name})
        return float(d["index_price"])

    # ----------------------------------------------------------------- #
    def option_chain(self, currency: str = "BTC") -> list[dict]:
        """
        Catena opzioni completa, normalizzata per engine/gex.py.

        Ogni elemento: instrument, strike, option_type, expiry_ms,
                       open_interest, iv (decimale), mark_price.

        Il nome strumento Deribit ha forma  BTC-27JUN26-80000-C
        Da li' si ricavano scadenza, strike e tipo senza una seconda chiamata.
        """
        raw = self._get("/public/get_book_summary_by_currency",
                        {"currency": currency, "kind": "option"})
        out = []
        for it in raw or []:
            name = it.get("instrument_name", "")
            parsed = self._parse_instrument(name)
            if not parsed:
                continue
            iv = it.get("mark_iv")
            out.append({
                "instrument": name,
                "strike": parsed["strike"],
                "option_type": parsed["option_type"],
                "expiry_ms": parsed["expiry_ms"],
                "open_interest": float(it.get("open_interest") or 0.0),
                # Deribit espone mark_iv in PERCENTUALE (es. 55.2) -> decimale
                "iv": (float(iv) / 100.0) if iv else 0.0,
                "mark_price": float(it.get("mark_price") or 0.0),
            })
        return out

    @staticmethod
    def _parse_instrument(name: str) -> dict | None:
        """BTC-27JUN26-80000-C -> {expiry_ms, strike, option_type}"""
        parts = name.split("-")
        if len(parts) != 4:
            return None
        _, expiry_s, strike_s, cp = parts
        try:
            # scadenza Deribit: 08:00 UTC del giorno indicato
            dt = datetime.strptime(expiry_s, "%d%b%y").replace(
                hour=8, tzinfo=timezone.utc)
            return {
                "expiry_ms": int(dt.timestamp() * 1000),
                "strike": float(strike_s),
                "option_type": "call" if cp.upper() == "C" else "put",
            }
        except ValueError:
            return None

    # ----------------------------------------------------------------- #
    def dvol_history(self, currency: str = "BTC", days: int = 120) -> list[dict]:
        """
        Storico DVOL giornaliero. Serve per il rango percentile usato dalla
        condizione "IV compressa" del punteggio di significativita'.
        """
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - days * 24 * 60 * 60 * 1000
        d = self._get("/public/get_volatility_index_data", {
            "currency": currency, "start_timestamp": start_ms,
            "end_timestamp": now_ms, "resolution": "86400",
        })
        out = []
        for row in (d or {}).get("data", []):
            # [timestamp, open, high, low, close]
            out.append({"time": int(row[0]), "open": float(row[1]),
                        "high": float(row[2]), "low": float(row[3]),
                        "close": float(row[4])})
        return out

    @staticmethod
    def dvol_percentile_rank(history: list[dict], current: float | None = None) -> float | None:
        """
        Rango percentile del DVOL corrente nella sua storia recente (0 = minimo
        del periodo, 1 = massimo). IV BASSA (rango basso) concentra il gamma e
        RAFFORZA l'effetto: e' contro-intuitivo ma corretto.
        """
        closes = [h["close"] for h in history if h.get("close")]
        if not closes:
            return None
        cur = current if current is not None else closes[-1]
        below = sum(1 for c in closes if c < cur)
        return round(below / len(closes), 3)
