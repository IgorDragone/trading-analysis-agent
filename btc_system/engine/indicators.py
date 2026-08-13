"""
indicators.py
-------------
Indicatori derivati dalle candele OHLCV.

  - vwap_bands()        -> VWAP con bande a N deviazioni standard
  - cvd_series()        -> serie cumulata del CVD (uso interno)
  - cvd_metrics()       -> CVD letto SOLO per direzione/pendenza/divergenza
  - golden_rule()       -> applica la "Regola d'Oro" (squeeze vs covering)
  - pct_change_24h()    -> variazione % nelle ultime 24h
  - volatility_context()-> giornata compressa o espansa vs media recente

NOTA METODOLOGICA (FASE 1): del CVD non si usa MAI il valore assoluto, ma solo
direzione, pendenza e divergenza vs prezzo, calcolate sulla STESSA finestra
usata dalla Regola d'Oro. Per questo cvd_metrics() e golden_rule() condividono
lo stesso parametro 'lookback'.
"""

import math


def vwap_bands(candles: list[dict], n_std: tuple = (1, 2, 3)) -> dict:
    """
    VWAP cumulativo sull'insieme di candele + bande a n deviazioni standard.
    Usa il typical price (H+L+C)/3 pesato per volume.

    Per il VWAP di sessione, passare solo le candele della sessione.
    """
    cum_vol = 0.0
    cum_pv = 0.0
    cum_pv2 = 0.0
    vwap = 0.0
    for c in candles:
        tp = (c["high"] + c["low"] + c["close"]) / 3
        v = c["volume"]
        cum_vol += v
        cum_pv += tp * v
        cum_pv2 += (tp ** 2) * v
        if cum_vol > 0:
            vwap = cum_pv / cum_vol

    variance = max(0.0, (cum_pv2 / cum_vol) - vwap ** 2) if cum_vol > 0 else 0.0
    std = math.sqrt(variance)

    bands = {}
    for n in n_std:
        bands[f"upper_{n}"] = round(vwap + n * std, 2)
        bands[f"lower_{n}"] = round(vwap - n * std, 2)

    return {"vwap": round(vwap, 2), "std": round(std, 2), "bands": bands}


def vwap_distance_sigma(price: float, vwap: float, std: float) -> float | None:
    """Quante deviazioni standard separano il prezzo dal VWAP (segno incluso)."""
    if not std or std <= 0:
        return None
    return round((price - vwap) / std, 2)


def cvd_series(candles: list[dict]) -> list[float]:
    """Serie cumulata del CVD (uso interno; il valore assoluto NON va esposto)."""
    cvd = 0.0
    out = []
    for c in candles:
        buy = c.get("taker_buy_volume", c["volume"] / 2)
        sell = c["volume"] - buy
        cvd += (buy - sell)
        out.append(cvd)
    return out


def cvd_metrics(candles: list[dict], lookback: int = 4) -> dict:
    """
    Legge il CVD SOLO per direzione/pendenza/divergenza sulla finestra 'lookback'.
    'lookback' = numero di candele indietro con cui si confronta l'ultima.

    Ritorna: direction (in salita/piatto/in calo), delta sulla finestra,
    e divergence_vs_price (True se prezzo e CVD vanno in direzioni opposte).
    Il valore ASSOLUTO del CVD non viene mai restituito (regola metodologica).
    """
    s = cvd_series(candles)
    if len(s) <= lookback:
        return {"direction": "n/d", "delta": 0.0, "lookback": lookback,
                "price_delta": 0.0, "divergence_vs_price": None}
    delta = s[-1] - s[-1 - lookback]
    price_delta = candles[-1]["close"] - candles[-1 - lookback]["close"]
    if delta > 0:
        direction = "in salita"
    elif delta < 0:
        direction = "in calo"
    else:
        direction = "piatto"
    divergence = (price_delta > 0 and delta < 0) or (price_delta < 0 and delta > 0)
    return {
        "direction": direction,
        "delta": round(delta, 2),
        "lookback": lookback,
        "price_delta": round(price_delta, 2),
        "divergence_vs_price": bool(divergence),
    }


def golden_rule(price_change: float, cvd_change: float, oi_change: float,
                ref_price: float | None = None,
                min_move_pct: float = 0.15) -> dict:
    """
    Applica la Regola d'Oro. IMPORTANTE: price_change, cvd_change e oi_change
    devono essere misurati sulla STESSA finestra temporale (vedi data_collector).

    SOGLIA DI SIGNIFICATIVITA' (ref_price + min_move_pct):
    la Regola d'Oro classifica la NATURA di un movimento, quindi presuppone che
    un movimento ci sia. Se il prezzo si e' spostato meno di `min_move_pct`
    sulla finestra, il segno di price/cvd/oi e' rumore: etichettare quel nulla
    come "trend ribassista genuino" produce diagnosi drammatiche del niente, che
    a valle l'Agente 3 amplifica in verdetti "pericolosi" senza motivo.
    In quel caso signal = "Nessun movimento apprezzabile: Regola d'Oro non
    applicabile" e applicable = False.
    Passare ref_price=None disattiva il controllo (retrocompatibilita').

    min_move_pct = 0.15% e' una soglia INIZIALE DA CALIBRARE sui dati reali.

    MECCANISMO (non sbagliare): l'OI sale solo quando si APRONO posizioni e
    scende quando si CHIUDONO (per liquidazione o volontariamente). Quindi uno
    short squeeze / short covering -> gli short ricomprano -> posizioni CHIUSE
    -> OI in CALO (mai in aumento) e CVD in salita (ricomprare e' acquisto
    aggressivo). Squeeze e covering sono lo stesso fenomeno.

    Le otto combinazioni:
      prezzo UP   + CVD UP   + OI UP   = nuovi long (trend rialzista genuino)
      prezzo UP   + CVD UP   + OI DOWN = short covering / squeeze (ricopertura)
      prezzo UP   + CVD DOWN + OI UP   = nuovi short assorbiti (rialzo non confermato)
      prezzo UP   + CVD DOWN + OI DOWN = chiusure in salita (rialzo debole)
      prezzo DOWN + CVD DOWN + OI UP   = nuovi short (trend ribassista genuino)
      prezzo DOWN + CVD DOWN + OI DOWN = long capitulation (chiusure/liquidazioni)
      prezzo DOWN + CVD UP   + OI DOWN = assorbimento in discesa (divergenza rialzista)
      prezzo DOWN + CVD UP   + OI UP   = accumulo in discesa (nuovi long assorbono)
    """
    p = "up" if price_change > 0 else "down"
    cvd = "up" if cvd_change > 0 else "down"
    oi = "up" if oi_change > 0 else "down"

    move_pct = None
    if ref_price:
        move_pct = round(abs(price_change) / ref_price * 100, 3)
        if move_pct < min_move_pct:
            return {
                "price": p, "cvd": cvd, "oi": oi,
                "applicable": False,
                "move_pct": move_pct,
                "min_move_pct": min_move_pct,
                "signal": (f"Nessun movimento apprezzabile ({move_pct}% sulla finestra, "
                           f"soglia {min_move_pct}%): Regola d'Oro non applicabile"),
            }

    key = (p, cvd, oi)
    interpretations = {
        ("up", "up", "up"): "Nuovi long - trend rialzista genuino",
        ("up", "up", "down"): "Short covering / squeeze - rimbalzo da ricopertura",
        ("up", "down", "up"): "Nuovi short assorbiti - rialzo non confermato dal flusso",
        ("up", "down", "down"): "Chiusure in salita - rialzo debole, poca convinzione",
        ("down", "down", "up"): "Nuovi short - trend ribassista genuino",
        ("down", "down", "down"): "Long capitulation - liquidazioni/chiusure forzate",
        ("down", "up", "down"): "Assorbimento in discesa - vendite in esaurimento",
        ("down", "up", "up"): "Accumulo in discesa - nuovi long che assorbono",
    }
    return {
        "price": p, "cvd": cvd, "oi": oi,
        "applicable": True,
        "move_pct": move_pct,
        "signal": interpretations.get(key, "Combinazione neutra"),
    }


def pct_change_24h(candles_15m: list[dict], bars: int = 96) -> float | None:
    """
    Variazione % nelle ultime 24h. Su candele 15m, 24h = 96 candele.
    """
    if len(candles_15m) <= bars:
        return None
    now = candles_15m[-1]["close"]
    past = candles_15m[-1 - bars]["close"]
    if past <= 0:
        return None
    return round((now - past) / past * 100, 2)


def volatility_context(candles_1d: list[dict], today_candles: list[dict],
                       lookback_days: int = 10) -> dict:
    """
    Confronta l'ampiezza (high-low) della sessione odierna con la media delle
    ampiezze giornaliere degli ultimi 'lookback_days' giorni (esclusa oggi).

    Ritorna: session_range_pct, avg_range_10d_pct, regime ('compressa'/'espansa').
    """
    ranges = []
    # Esclude l'ultima candela giornaliera: oggi puo' essere ancora in formazione.
    for c in candles_1d[-lookback_days - 1:-1]:
        if c["close"] > 0:
            ranges.append((c["high"] - c["low"]) / c["close"] * 100)
    avg = sum(ranges) / len(ranges) if ranges else None

    session = None
    if today_candles:
        hi = max(c["high"] for c in today_candles)
        lo = min(c["low"] for c in today_candles)
        cur = today_candles[-1]["close"]
        if cur > 0:
            session = (hi - lo) / cur * 100

    regime = None
    if avg is not None and session is not None:
        regime = "compressa" if session < avg else "espansa"

    return {
        "session_range_pct": round(session, 2) if session is not None else None,
        "avg_range_10d_pct": round(avg, 2) if avg is not None else None,
        "regime": regime,
    }


if __name__ == "__main__":
    candles = [
        {"high": 73200, "low": 72800, "close": 73000, "volume": 1000, "taker_buy_volume": 600},
        {"high": 73400, "low": 73000, "close": 73300, "volume": 1200, "taker_buy_volume": 500},
    ]
    print("VWAP:", vwap_bands(candles))
    print("CVD metrics:", cvd_metrics(candles * 5))
    print("Regola d'Oro:", golden_rule(+300, -200, +0.5))
