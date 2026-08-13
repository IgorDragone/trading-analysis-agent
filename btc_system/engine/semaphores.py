"""
semaphores.py
-------------
Semafori operativi DETERMINISTICI (engine, non agente). Tre componenti:

1. key_levels()      -> livelli chiave: max/min settimanale e mensile (precedenti
                        e correnti). Sono i "muri" verso cui il prezzo corre.
2. approach_brake()  -> FRENO: scatta quando il prezzo si dirige CON FORZA verso
                        un livello chiave vicino. Dice "smetti di inseguire,
                        aspetta che il mercato decida". NON e' un segnale di
                        ingresso: e' un freno all'averaging-down.
3. gex_veto()        -> VETO generale: grigio (non operare) se il GEX e' sotto
                        soglia. Il valore GEX arriva dallo snapshot (calcolo live
                        Deribit), qui si applica solo la soglia.

semaphore() li combina in un unico stato: GRIGIO (veto), FRENO (non aggiungere),
o VERDE (condizioni ok). Pure Python, nessuna dipendenza.

NOTA: le soglie (prossimita', forza, soglia GEX) sono scelte di trading da
tarare, non verita'. Default ragionevoli, marcati sotto.
"""

from datetime import datetime, timezone


def _dt(candle):
    t = candle["time"]
    if t > 1e14:        # microsecondi -> ms (sicurezza)
        t //= 1000
    return datetime.fromtimestamp(t / 1000, timezone.utc)


def key_levels(daily: list[dict]) -> dict:
    """
    Da candele GIORNALIERE (ordinate, con time/high/low) ricava i livelli chiave.
    'prev' = ultimo periodo CHIUSO; 'curr' = periodo in corso (finora).
    """
    weeks, months = {}, {}
    for c in daily:
        d = _dt(c)
        wk = (d.isocalendar().year, d.isocalendar().week)
        mo = (d.year, d.month)
        for key, group in ((wk, weeks), (mo, months)):
            g = group.setdefault(key, {"high": c["high"], "low": c["low"]})
            g["high"] = max(g["high"], c["high"])
            g["low"] = min(g["low"], c["low"])

    def prev_curr(group):
        keys = sorted(group)
        if len(keys) < 2:
            return None, None
        return group[keys[-2]], group[keys[-1]]

    pw, cw = prev_curr(weeks)
    pm, cm = prev_curr(months)
    out = {}
    if pw: out["prev_week_high"], out["prev_week_low"] = pw["high"], pw["low"]
    if cw: out["curr_week_high"], out["curr_week_low"] = cw["high"], cw["low"]
    if pm: out["prev_month_high"], out["prev_month_low"] = pm["high"], pm["low"]
    if cm: out["curr_month_high"], out["curr_month_low"] = cm["high"], cm["low"]
    return out


def nearest_levels(price: float, levels: dict) -> dict:
    """Trova il livello chiave piu' vicino SOPRA e SOTTO il prezzo, con distanza %."""
    above = {k: v for k, v in levels.items() if v > price}
    below = {k: v for k, v in levels.items() if v < price}
    res = {"above": None, "below": None}
    if above:
        k = min(above, key=lambda x: above[x]); res["above"] = {"level": k, "price": above[k], "dist_pct": (above[k] / price - 1) * 100}
    if below:
        k = max(below, key=lambda x: below[x]); res["below"] = {"level": k, "price": below[k], "dist_pct": (1 - below[k] / price) * 100}
    return res


def approach_brake(intraday: list[dict], levels: dict,
                   proximity_pct: float = 0.5, lookback: int = 4,
                   force_pct: float = 0.3) -> dict:
    """
    FRENO. Scatta se il prezzo e' entro 'proximity_pct'% da un livello chiave E si
    sta muovendo VERSO di esso, nelle ultime 'lookback' barre, di almeno 'force_pct'%.

    Default (da tarare): prossimita' 0.5%, finestra 4 barre, forza 0.3%.
    """
    if len(intraday) < lookback + 1:
        return {"brake": False, "reason": "dati insufficienti"}
    price = intraday[-1]["close"]
    move = (price / intraday[-1 - lookback]["close"] - 1) * 100   # +sale / -scende
    near = nearest_levels(price, levels)

    # sta salendo verso un livello sopra?
    if move >= force_pct and near["above"] and near["above"]["dist_pct"] <= proximity_pct:
        L = near["above"]
        return {"brake": True, "direction": "su",
                "reason": f"prezzo sale con forza ({move:+.1f}%) verso {L['level']} "
                          f"a {L['dist_pct']:.2f}% -> non inseguire, aspetta la reazione"}
    # sta scendendo verso un livello sotto?
    if move <= -force_pct and near["below"] and near["below"]["dist_pct"] <= proximity_pct:
        L = near["below"]
        return {"brake": True, "direction": "giu",
                "reason": f"prezzo scende con forza ({move:+.1f}%) verso {L['level']} "
                          f"a {L['dist_pct']:.2f}% -> non inseguire, aspetta la reazione"}
    return {"brake": False, "reason": "nessun livello chiave imminente"}


def gex_veto(gex, threshold: float = 100e6) -> dict:
    """VETO. Grigio se GEX assente o sotto soglia (default 100M)."""
    if gex is None:
        return {"veto": True, "reason": "GEX non disponibile"}
    if gex < threshold:
        return {"veto": True, "reason": f"GEX {gex/1e6:.0f}M sotto soglia ({threshold/1e6:.0f}M)"}
    return {"veto": False, "reason": f"GEX {gex/1e6:.0f}M sopra soglia"}


def semaphore(intraday: list[dict], daily: list[dict], gex=None,
              gex_threshold: float = 100e6, **brake_kwargs) -> dict:
    """
    Combina i tre semafori in un unico stato:
      - GRIGIO  : veto attivo (GEX sotto soglia) -> non operare
      - FRENO   : livello chiave imminente       -> non aggiungere, aspetta
      - VERDE   : condizioni ok                   -> setup ammessi
    Restituisce sempre i dettagli (livelli, distanze, motivazioni).
    """
    levels = key_levels(daily)
    price = intraday[-1]["close"] if intraday else None
    near = nearest_levels(price, levels) if price else {}
    veto = gex_veto(gex, gex_threshold)
    brake = approach_brake(intraday, levels, **brake_kwargs) if levels else {"brake": False, "reason": "nessun livello"}

    if veto["veto"]:
        state, why = "GRIGIO", veto["reason"]
    elif brake["brake"]:
        state, why = "FRENO", brake["reason"]
    else:
        state, why = "VERDE", "nessun veto, nessun livello imminente"

    return {"state": state, "reason": why, "gex": veto, "brake": brake,
            "key_levels": levels, "nearest": near}


if __name__ == "__main__":
    import random
    # giornaliero finto: 60 giorni
    daily = []
    p = 60000.0; t = 1700000000000
    for i in range(60):
        p *= (1 + random.uniform(-0.02, 0.02))
        daily.append({"time": t + i * 86400000, "high": p * 1.02, "low": p * 0.98, "close": p})
    # intraday che sale con forza
    intr = [{"time": t, "close": c} for c in [60000, 60200, 60500, 60900, 61400]]
    lv = key_levels(daily)
    print("livelli chiave:", {k: round(v) for k, v in lv.items()})
    print("vicini al prezzo 61400:", nearest_levels(61400, lv))
    print("\nsemaforo (GEX 150M):", semaphore(intr, daily, gex=150e6)["state"])
    print("semaforo (GEX 40M) :", semaphore(intr, daily, gex=40e6)["state"], "->", semaphore(intr, daily, gex=40e6)["reason"])
