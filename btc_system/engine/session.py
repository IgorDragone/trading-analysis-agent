"""
session.py
----------
Fascia oraria di SESSIONE (engine, deterministico). Restituisce in quale
sessione di mercato cade lo snapshot e quanto quella fascia e' favorevole al
mean reversion intraday.

PERCHE' ESISTE
La validazione statistica su dati storici BTC ha mostrato che il fattore di
contesto piu' forte per il mean reversion NON e' il regime detector (ADX+ER,
risultato debole) ma la FASCIA ORARIA:
  - Asia e prima Londra  -> il prezzo rientra verso il VWAP molto piu' spesso
    (chop mean-reverting).
  - New York             -> flusso direzionale reale, le estensioni proseguono
    (rientro sfavorito).
Questo modulo incarna quel fattore e lo mette nello snapshot, cosi' l'Agente 3
puo' pesarlo PIU' del regime, come da sue istruzioni.

NON e' un trigger di trade: e' contesto che modula la fiducia nel rientro.
Pure Python, nessuna dipendenza.

NOTA sui confini: le fasce sono in UTC e sono APPROSSIMAZIONI operative, non
orari ufficiali di borsa (il cripto e' 24/7). I confini default riflettono la
finestra usata nell'analisi (ingressi 00-07 UTC = Asia). Sono scelte da tarare,
non verita'; marcati sotto.
"""

from datetime import datetime, timezone


# Confini di sessione in ora UTC (scelte operative, da tarare).
# Ogni voce: (ora_inizio_inclusa, ora_fine_esclusa, nome, contesto_mean_reversion)
# Le fasce coprono le 24h senza buchi ne' sovrapposizioni.
_SESSIONS = [
    (0, 7, "asia", "favorevole"),      # chop notturno: rientri frequenti
    (7, 13, "london", "favorevole"),   # prima Londra ancora mean-reverting
    (13, 21, "ny", "sfavorevole"),     # flusso direzionale USA: estensioni proseguono
    (21, 24, "late", "neutro"),        # tarda sera USA / pre-Asia: incerto
]


def _hour_utc(candle: dict) -> int:
    """Ora UTC (0-23) di una candela con campo 'time' in ms."""
    t = candle["time"]
    if t > 1e14:            # microsecondi -> ms (sicurezza, come negli altri moduli)
        t //= 1000
    return datetime.fromtimestamp(t / 1000, timezone.utc).hour


def classify_session(candle: dict | None = None, *, hour: int | None = None) -> dict:
    """
    Classifica la sessione di mercato di uno snapshot.

    Si puo' passare:
      - una `candle` (con 'time' in ms), tipicamente l'ultima dello snapshot; oppure
      - direttamente `hour` (0-23 UTC), utile nei test.
    Se entrambi assenti, usa l'ora UTC corrente.

    Ritorna:
      {
        "name": "asia"|"london"|"ny"|"late",
        "hour_utc": int,
        "mean_reversion_context": "favorevole"|"sfavorevole"|"neutro",
        "in_entry_window": bool,   # True se dentro 00-07 UTC (finestra della macchina H)
        "rationale": str
      }
    """
    if hour is None:
        if candle is not None:
            hour = _hour_utc(candle)
        else:
            hour = datetime.now(timezone.utc).hour
    hour = int(hour) % 24

    name, context = "late", "neutro"
    for start, end, nm, ctx in _SESSIONS:
        if start <= hour < end:
            name, context = nm, ctx
            break

    in_entry_window = 0 <= hour < 7

    pretty = {
        "favorevole": "fascia mean-reverting: rientri verso il VWAP piu' frequenti",
        "sfavorevole": "fascia direzionale: le estensioni tendono a proseguire",
        "neutro": "fascia incerta: nessun bias chiaro di rientro",
    }[context]
    rationale = f"Sessione {name} ({hour:02d}:00 UTC) - {pretty}."

    return {
        "name": name,
        "hour_utc": hour,
        "mean_reversion_context": context,
        "in_entry_window": in_entry_window,
        "rationale": rationale,
    }


# --- demo / sanity check rapido ---
if __name__ == "__main__":
    for h in (2, 5, 9, 15, 22):
        s = classify_session(hour=h)
        print(f"h{h:02d} UTC -> {s['name']:<7} "
              f"context={s['mean_reversion_context']:<12} "
              f"entry_window={s['in_entry_window']}")
