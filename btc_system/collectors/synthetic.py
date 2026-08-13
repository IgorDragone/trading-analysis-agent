"""
synthetic.py
------------
Genera uno snapshot FINTO con candele casuali, per testare la pipeline
(collector -> snapshot -> Agente 1) SENZA connessione a Binance.

Serve solo a verificare che il "tubo" funzioni e che l'Agente 1 produca un
report. I numeri NON sono reali: non usarlo per analisi, solo per collaudo.
"""

import random
from datetime import datetime, timezone

from data_collector import build_snapshot


def _make_candles(n: int, interval_ms: int, base: float, end_ms: int) -> list[dict]:
    candles = []
    price = base
    start = end_ms - n * interval_ms
    for i in range(n):
        drift = random.uniform(-0.004, 0.004)
        price = max(1000.0, price * (1 + drift))
        o = price
        h = o * (1 + random.uniform(0, 0.005))
        l = o * (1 - random.uniform(0, 0.005))
        c = random.uniform(l, h)
        vol = random.uniform(100, 5000)
        candles.append({
            "time": start + i * interval_ms,
            "open": round(o, 2), "high": round(h, 2), "low": round(l, 2),
            "close": round(c, 2), "volume": round(vol, 2),
            "taker_buy_volume": round(vol * random.uniform(0.4, 0.6), 2),
        })
    return candles


def synthetic_snapshot(symbol: str = "BTCUSDT", base: float = 68000.0, note: str | None = None) -> dict:
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    k15 = _make_candles(300, 15 * 60 * 1000, base, now)
    k1h = _make_candles(300, 60 * 60 * 1000, base, now)
    k1d = _make_candles(300, 24 * 60 * 60 * 1000, base, now)

    # Storico OI finto coerente con le finestre LOOKBACK/LOOKBACK_LONG.
    oi_hist = [{"time": now - (40 - i) * 900000, "oi": 80000 + random.uniform(-2000, 2000)}
               for i in range(40)]
    flow_raw = {
        "funding_rate": round(random.uniform(-0.0001, 0.0001), 6),
        "open_interest": oi_hist[-1]["oi"],
        "bsvr": round(random.uniform(0.85, 1.15), 3),
        "oi_hist": oi_hist,
    }
    return build_snapshot(symbol, k15, k1h, k1d, flow_raw, note=note)


if __name__ == "__main__":
    import json
    print(json.dumps(synthetic_snapshot(), indent=2, default=str))
