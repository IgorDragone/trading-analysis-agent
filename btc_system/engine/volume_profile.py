"""
volume_profile.py
-----------------
Motore di calcolo dei Volume Profile a partire da candele OHLCV.

Codice validato contro TradingView (POC/VAH/VAL entro pochi dollari).

  - volume_profile()   -> POC, VAH, VAL di un set di candele (anchored VP)
  - session_profiles() -> un VP per ogni sessione (giorno UTC) -> Session VP
  - naked_pocs()       -> POC di sessioni passate mai piu' testati (magneti)

NOTA METODOLOGICA (FASE 1): naked_pocs() scarta le sessioni a volume troppo
basso, perche' un POC nato da poco volume e' rumore, non un magnete affidabile.
"""

import statistics
from collections import defaultdict
from datetime import datetime, timezone


def volume_profile(candles: list[dict], bins: int = 200,
                   value_area_pct: float = 0.70) -> dict:
    """
    Calcola POC/VAH/VAL su un insieme di candele.
    Il volume di ogni candela e' distribuito sul suo range high-low fra i bin
    che attraversa (approssimazione standard senza dati tick-by-tick).
    Ritorna: poc, vah, val, hi, lo, hist, volume (totale).
    """
    if not candles:
        raise ValueError("Nessuna candela fornita")

    lo = min(c["low"] for c in candles)
    hi = max(c["high"] for c in candles)
    total_volume = sum(c["volume"] for c in candles)

    if hi == lo:
        return {"poc": lo, "vah": hi, "val": lo, "hi": hi, "lo": lo,
                "hist": [], "volume": total_volume}

    width = (hi - lo) / bins
    vol_at = [0.0] * bins

    for c in candles:
        c_lo, c_hi, v = c["low"], c["high"], c["volume"]
        if c_hi == c_lo:
            idx = min(int((c_lo - lo) / width), bins - 1)
            vol_at[idx] += v
            continue
        span = c_hi - c_lo
        first = max(0, int((c_lo - lo) / width))
        last = min(bins - 1, int((c_hi - lo) / width))
        for b in range(first, last + 1):
            b_lo = lo + b * width
            b_hi = b_lo + width
            overlap = max(0.0, min(c_hi, b_hi) - max(c_lo, b_lo))
            if overlap > 0:
                vol_at[b] += v * (overlap / span)

    poc_bin = max(range(bins), key=lambda b: vol_at[b])
    poc = lo + (poc_bin + 0.5) * width

    total = sum(vol_at)
    target = total * value_area_pct
    lo_b = hi_b = poc_bin
    acc = vol_at[poc_bin]
    while acc < target:
        up = vol_at[hi_b + 1] if hi_b + 1 < bins else -1
        dn = vol_at[lo_b - 1] if lo_b - 1 >= 0 else -1
        if up >= dn and hi_b + 1 < bins:
            hi_b += 1
            acc += vol_at[hi_b]
        elif lo_b - 1 >= 0:
            lo_b -= 1
            acc += vol_at[lo_b]
        else:
            break

    return {
        "poc": round(poc, 2),
        "vah": round(lo + (hi_b + 1) * width, 2),
        "val": round(lo + lo_b * width, 2),
        "hi": round(hi, 2),
        "lo": round(lo, 2),
        "hist": vol_at,
        "volume": total_volume,
    }


def _day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def session_profiles(candles: list[dict], bins: int = 80) -> list[dict]:
    """Un Volume Profile per ogni giorno UTC. Include il volume totale di sessione."""
    sessions = defaultdict(list)
    for c in candles:
        sessions[_day_key(c["time"])].append(c)

    out = []
    for day in sorted(sessions.keys()):
        vp = volume_profile(sessions[day], bins=bins)
        vp["day"] = day
        vp["candles"] = len(sessions[day])
        out.append(vp)
    return out


def naked_pocs(session_vps: list[dict], current_price: float,
               min_volume_ratio: float = 0.3) -> list[dict]:
    """
    Identifica i Naked POC: POC di sessioni passate mai piu' toccati da una
    sessione successiva. Sono magneti per la mean reversion.

    FILTRO QUALITA': si scartano le sessioni con volume inferiore a
    min_volume_ratio * (mediana dei volumi di sessione). Un POC nato da poco
    volume non e' un magnete affidabile.
    """
    naked = []
    n = len(session_vps)
    if n < 2:
        return naked

    # mediana dei volumi delle sessioni candidate (escludo l'ultima, in corso)
    vols = [s.get("volume", 0.0) for s in session_vps[:-1]]
    median_vol = statistics.median(vols) if vols else 0.0
    threshold = median_vol * min_volume_ratio

    for i in range(n - 1):  # range arriva a n-2: tutte le sessioni tranne l'ultima
        s_i = session_vps[i]
        if s_i.get("volume", 0.0) < threshold:
            continue  # sessione a volume troppo basso: POC non affidabile
        poc = s_i["poc"]
        touched = any(s["lo"] <= poc <= s["hi"] for s in session_vps[i + 1:])
        if not touched:
            dist_pct = (poc - current_price) / current_price * 100
            naked.append({
                "day": s_i["day"],
                "poc": poc,
                "side": "sopra" if poc > current_price else "sotto",
                "dist_pct": round(dist_pct, 2),
            })
    naked.sort(key=lambda x: abs(x["dist_pct"]))
    return naked


if __name__ == "__main__":
    import random
    base = 73000
    candles = []
    t = 1780000000000
    for i in range(300):
        o = base + random.uniform(-500, 500)
        h = o + random.uniform(0, 300)
        l = o - random.uniform(0, 300)
        c = random.uniform(l, h)
        candles.append({"time": t + i * 900000, "open": o, "high": h,
                        "low": l, "close": c, "volume": random.uniform(100, 5000)})
    vp = volume_profile(candles)
    print("Anchored VP:", {k: vp[k] for k in ("poc", "vah", "val")})
    sp = session_profiles(candles)
    print(f"Session profiles: {len(sp)} giorni")
    print("Naked POC:", naked_pocs(sp, candles[-1]["close"]))
