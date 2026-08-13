"""
regime.py
---------
Indicatore di REGIME di mercato: dice se il timeframe e' in TREND o LATERALE.

Serve come FILTRO per il mean reversion (Agente 3): il rientro verso la media e'
favorito in regime laterale e sconsigliato in trend forte. NON e' un trigger: e'
contesto che modula il giudizio dell'Agente 3.

Usa due metodi indipendenti, e li fa concordare:
  - ADX (Average Directional Index, Wilder): misura la FORZA della direzione.
  - Efficiency Ratio (Kaufman): quanto del movimento e' "netto" vs rumore.

Tutto in Python puro (nessuna dipendenza), coerente con gli altri moduli engine.

NOTA METODOLOGICA: il regime e' specifico del TIMEFRAME. Lo stesso mercato puo'
essere in trend sul settimanale e laterale sul 15m. Per il mean reversion
intraday conta il regime intraday (15m / 1h), non quello macro.
"""


def _wilder_rma(values: list[float], n: int) -> list:
    """Media mobile di Wilder (RMA). Ritorna lista con None finche' non c'e' n dati."""
    out = [None] * len(values)
    if len(values) < n:
        return out
    seed = sum(values[:n]) / n
    out[n - 1] = seed
    prev = seed
    for i in range(n, len(values)):
        prev = (prev * (n - 1) + values[i]) / n
        out[i] = prev
    return out
def adx(candles: list[dict], n: int = 14) -> dict:
    """
    Calcola ADX, +DI, -DI (Wilder) e ne restituisce gli ultimi valori.
    Richiede high/low/close. Ritorna None sui valori se i dati sono insufficienti.
    """
    if len(candles) < 2 * n + 1:
        return {"adx": None, "plus_di": None, "minus_di": None}

    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        ph, pl, pc = candles[i - 1]["high"], candles[i - 1]["low"], candles[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)

    atr = _wilder_rma(tr, n)
    pdm = _wilder_rma(plus_dm, n)
    mdm = _wilder_rma(minus_dm, n)

    dx = []
    for i in range(len(tr)):
        if atr[i] and atr[i] > 0 and pdm[i] is not None and mdm[i] is not None:
            pdi = 100 * pdm[i] / atr[i]
            mdi = 100 * mdm[i] / atr[i]
            denom = pdi + mdi
            dx.append(100 * abs(pdi - mdi) / denom if denom > 0 else 0.0)
        else:
            dx.append(None)

    dx_valid = [v for v in dx if v is not None]
    adx_series = _wilder_rma(dx_valid, n)
    last_adx = adx_series[-1] if adx_series and adx_series[-1] is not None else None

    # ultimi +DI / -DI
    last_pdi = last_mdi = None
    if atr[-1] and atr[-1] > 0:
        last_pdi = 100 * pdm[-1] / atr[-1] if pdm[-1] is not None else None
        last_mdi = 100 * mdm[-1] / atr[-1] if mdm[-1] is not None else None

    return {
        "adx": round(last_adx, 1) if last_adx is not None else None,
        "plus_di": round(last_pdi, 1) if last_pdi is not None else None,
        "minus_di": round(last_mdi, 1) if last_mdi is not None else None,
    }


def efficiency_ratio(candles: list[dict], n: int = 14) -> float | None:
    """
    Efficiency Ratio di Kaufman su n periodi: |variazione netta| / somma |variazioni|.
    Vicino a 1 = movimento direzionale pulito; vicino a 0 = lateralita'/rumore.
    Misura la "efficienza" del movimento: quanto del movimento e' "netto" vs rumore. Se il prezzo si muove in una direzione con forza, l'efficiency ratio sarà vicino a 1. Se il prezzo oscilla senza una direzione chiara, l'efficiency ratio sarà vicino a 0.
    Movimento Netto / Movimento Totale = |Prezzo Finale - Prezzo Iniziale| / Somma(|Prezzo[i] - Prezzo[i-1]|)
    Esempio: 100 -> 101 -> 102 -> 103 -> 104: ER = |104-100| / (|101-100| + |102-101| + |103-102| + |104-103|) = 4/4 = 1.0 (trend perfetto)
    Esempio: 100 -> 101 -> 100 -> 101 -> 100: ER = |100-100| / (|101-100| + |100-101| + |101-100| + |100-101|) = 0/4 = 0.0 (lateralita' pura)
    """
    closes = [c["close"] for c in candles]
    if len(closes) <= n:
        return None
    change = abs(closes[-1] - closes[-1 - n])
    vol = sum(abs(closes[i] - closes[i - 1]) for i in range(len(closes) - n, len(closes)))
    if vol <= 0:
        return None
    return round(change / vol, 3)


def classify_regime(candles: list[dict], timeframe: str,
                    adx_period: int = 14, er_period: int = 14,
                    adx_trend: float = 25.0, adx_range: float = 20.0,
                    er_trend: float = 0.30) -> dict:
    """
    Classifica il regime combinando ADX ed Efficiency Ratio.

    state: 'trend' (entrambi d'accordo sulla direzionalita'),
           'laterale' (entrambi d'accordo sulla lateralita'),
           'transizione' (i due metodi non concordano: incerto).
    mean_reversion_context: 'favorevole' (laterale) / 'sfavorevole' (trend) /
           'neutro' (transizione).
    """
    a = adx(candles, adx_period)
    er = efficiency_ratio(candles, er_period)

    if a["adx"] is None or er is None:
        return {"timeframe": timeframe, "state": "n/d", "adx": a["adx"],
                "efficiency_ratio": er, "direction": None,
                "mean_reversion_context": "n/d",
                "rationale": "dati insufficienti per calcolare il regime"}

    adx_trending = a["adx"] >= adx_trend
    adx_ranging = a["adx"] <= adx_range
    er_trending = er >= er_trend

    if adx_trending and er_trending:
        state = "trend"
    elif adx_ranging and not er_trending:
        state = "laterale"
    else:
        state = "transizione"

    direction = None
    if state == "trend" and a["plus_di"] is not None and a["minus_di"] is not None:
        direction = "rialzo" if a["plus_di"] > a["minus_di"] else "ribasso"

    context = {"trend": "sfavorevole", "laterale": "favorevole",
               "transizione": "neutro"}[state]

    rationale = (f"ADX {a['adx']} ed Efficiency Ratio {er}: "
                 + {"trend": f"alta direzionalita'{' al ' + direction if direction else ''} "
                            f"-> contesto SFAVOREVOLE al mean reversion",
                    "laterale": "bassa direzionalita' -> contesto FAVOREVOLE al mean reversion",
                    "transizione": "i due metodi non concordano -> regime incerto, prudenza"}[state])

    return {
        "timeframe": timeframe,
        "state": state,
        "adx": a["adx"],
        "plus_di": a["plus_di"],
        "minus_di": a["minus_di"],
        "efficiency_ratio": er,
        "direction": direction,
        "mean_reversion_context": context,
        "rationale": rationale,
    }


if __name__ == "__main__":
    import random
    # demo: serie con trend vs serie laterale
    def mk(trending):
        out = []
        p = 68000.0
        t = 1780000000000
        for i in range(300):
            drift = 0.004 if trending else random.uniform(-0.002, 0.002)
            p = p * (1 + drift)
            h = p * 1.003
            l = p * 0.997
            out.append({"time": t + i * 3600000, "open": p, "high": h, "low": l,
                        "close": random.uniform(l, h), "volume": 100})
        return out
    for label, trending in [("TREND  ", True), ("LATERALE", False)]:
        r = classify_regime(mk(trending), "1h")
        print(f"Serie {label}: state={r['state']:<12} context={r['mean_reversion_context']:<12} ADX={r['adx']} ER={r['efficiency_ratio']}")
