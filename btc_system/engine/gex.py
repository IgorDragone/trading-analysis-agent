"""
gex.py
------
Calcolo della Gamma Exposure (GEX) dalla catena opzioni. Matematica pura:
nessuna rete, tutto testabile offline. Il modulo di rete e' collectors/deribit_client.py.

COSA PRODUCE (i due oggetti da non confondere mai):
  - AGGREGATE = "il numero": GEX scalare al prezzo corrente. Tracciato nel tempo
    diventa la serie storica -> il DIARIO (in che regime siamo stati e siamo).
  - PROFILE   = "la curva": GEX calcolato per ogni livello di prezzo -> la MAPPA
    condizionale (dove sono i muri, cosa succederebbe altrove).
Il numero non contiene i muri; il profilo non contiene la storia. Servono entrambi.

Piu' il punteggio di SIGNIFICATIVITA': non basta sapere il regime, serve sapere
se OGGI il flusso di copertura pesa abbastanza da contare.

=========================== ASSUNZIONI DICHIARATE ===========================
1. SEGNO. Il posizionamento reale dei dealer non e' pubblicato da nessuno.
   Si usa la convenzione standard: dealer LONG le call, SHORT le put.
   E' un'assunzione, non un dato. Cambiabile con dealer_convention.
2. GAMMA. Calcolato con Black-Scholes dalla IV di mark, tasso 0 (standard cripto).
3. PROFILO. Ricalcolando la curva a prezzi diversi si tiene la IV FISSA. In
   realta' la superficie di volatilita' si muove col prezzo: la curva e' quindi
   un'approssimazione, tanto piu' grossolana quanto piu' ci si allontana.
4. NON confrontare mai questi numeri con quelli di un altro fornitore: assunzioni
   diverse producono flip in punti diversi. Confrontare questa fonte con se
   stessa nel tempo.
============================================================================
"""

import math
from datetime import datetime, timezone

# Su Deribit un contratto opzione BTC = 1 BTC di sottostante.
CONTRACT_SIZE = 1.0


# --------------------------------------------------------------------- #
# Black-Scholes: gamma
# --------------------------------------------------------------------- #
def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_gamma(spot: float, strike: float, iv: float, t_years: float) -> float:
    """
    Gamma di Black-Scholes (identica per call e put), tasso r = 0.
        gamma = N'(d1) / (S * sigma * sqrt(T))
    Ritorna 0 per input degeneri (scadenza passata, IV nulla).
    """
    if spot <= 0 or strike <= 0 or iv <= 0 or t_years <= 0:
        return 0.0
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / (iv * sqrt_t)
    return _norm_pdf(d1) / (spot * iv * sqrt_t)


def years_to_expiry(expiry_ms: int, now_ms: int | None = None) -> float:
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    return max(0.0, (expiry_ms - now_ms) / (1000 * 60 * 60 * 24 * 365.25))


# --------------------------------------------------------------------- #
# GEX per singolo strumento e aggregato
# --------------------------------------------------------------------- #
def instrument_gex(opt: dict, spot: float, now_ms: int | None = None,
                   dealer_convention: str = "long_calls_short_puts") -> float:
    """
    GEX di un singolo strumento, in DOLLARI per un movimento dell'1%.

        gex = segno * gamma * OI * contract_size * spot^2 * 0.01

    `opt` deve avere: strike, option_type ("call"/"put"), open_interest,
    iv (decimale, es. 0.55), expiry_ms.
    """
    iv = opt.get("iv") or 0.0
    oi = opt.get("open_interest") or 0.0
    if iv <= 0 or oi <= 0:
        return 0.0
    t = years_to_expiry(opt["expiry_ms"], now_ms)
    g = bs_gamma(spot, opt["strike"], iv, t)
    if g == 0.0:
        return 0.0
    if dealer_convention == "long_calls_short_puts":
        sign = 1.0 if opt["option_type"] == "call" else -1.0
    elif dealer_convention == "all_long":
        sign = 1.0
    else:
        raise ValueError(f"convenzione sconosciuta: {dealer_convention}")
    return sign * g * oi * CONTRACT_SIZE * (spot ** 2) * 0.01


def aggregate_gex(chain: list[dict], spot: float, now_ms: int | None = None,
                  dealer_convention: str = "long_calls_short_puts") -> float:
    """GEX totale al prezzo `spot`, in dollari per 1% di movimento."""
    return sum(instrument_gex(o, spot, now_ms, dealer_convention) for o in chain)


# --------------------------------------------------------------------- #
# Il PROFILO: la curva per livello di prezzo
# --------------------------------------------------------------------- #
def gex_profile(chain: list[dict], spot: float, range_pct: float = 10.0,
                step_pct: float = 0.25, now_ms: int | None = None,
                dealer_convention: str = "long_calls_short_puts") -> list[dict]:
    """
    Calcola il GEX per una griglia di prezzi attorno allo spot.
    ATTENZIONE: la IV resta fissa (vedi assunzione 3 in testa al modulo).
    """
    points = []
    n = int(range_pct / step_pct)
    for i in range(-n, n + 1):
        p = spot * (1 + i * step_pct / 100.0)
        points.append({
            "price": round(p, 2),
            "gex": round(aggregate_gex(chain, p, now_ms, dealer_convention), 2),
        })
    return points


def find_flip_point(points: list[dict], spot: float) -> float | None:
    """
    Il flip e' il prezzo dove la curva attraversa lo zero: separa il regime che
    comprime da quello che amplifica. NON e' un supporto: e' un confine di
    COMPORTAMENTO, e si sposta al variare di IV, tempo e posizionamento.
    Se ci sono piu' attraversamenti si restituisce il piu' vicino allo spot.
    """
    crossings = []
    for a, b in zip(points, points[1:]):
        ga, gb = a["gex"], b["gex"]
        if ga == 0:
            crossings.append(a["price"])
        elif (ga < 0) != (gb < 0):
            # interpolazione lineare tra i due punti
            frac = abs(ga) / (abs(ga) + abs(gb)) if (abs(ga) + abs(gb)) else 0.5
            crossings.append(a["price"] + frac * (b["price"] - a["price"]))
    if not crossings:
        return None
    return round(min(crossings, key=lambda p: abs(p - spot)), 2)


def gamma_walls(chain: list[dict], spot: float, top_n: int = 4,
                now_ms: int | None = None,
                dealer_convention: str = "long_calls_short_puts") -> list[dict]:
    """
    I "muri": gli strike con la maggiore concentrazione di gamma exposure.
    Attenzione al segno: uno strike a gamma POSITIVO frena il prezzo (barriera),
    lo stesso strike a gamma NEGATIVO lo accelera. Non e' sempre un ostacolo.
    """
    by_strike: dict[float, float] = {}
    for o in chain:
        g = instrument_gex(o, spot, now_ms, dealer_convention)
        if g:
            by_strike[o["strike"]] = by_strike.get(o["strike"], 0.0) + g
    walls = sorted(by_strike.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_n]
    out = []
    for strike, gex in sorted(walls, key=lambda kv: kv[0]):
        out.append({
            "price": strike,
            "gex": round(gex, 2),
            "sign": "positivo" if gex > 0 else "negativo",
            "side": "sopra" if strike > spot else "sotto",
            "dist_pct": round((strike - spot) / spot * 100, 2),
        })
    return out


# --------------------------------------------------------------------- #
# SIGNIFICATIVITA': oggi il gamma conta o dorme?
# --------------------------------------------------------------------- #
# SOGLIE INIZIALI, DA CALIBRARE sui dati reali (vedi schema_gamma_significativita.md).
TH_WALL_PCT = 2.0        # muro entro il 2% dal prezzo
TH_EXPIRY_DAYS = 5       # scadenza rilevante entro 5 giorni
TH_EXPIRY_OI_SHARE = 0.25
TH_IV_RANK = 0.40        # DVOL nel 40esimo percentile o sotto
TH_THINNESS = 0.15       # hedge per 1% >= 15% del volume orario tipico


def significance(walls: list[dict], days_to_major_expiry: float | None,
                 oi_share_major: float | None, dvol_pct_rank: float | None,
                 gex_abs_usd_per_1pct: float, typical_hourly_notional: float | None) -> dict:
    """
    Punteggio 0-4 delle quattro condizioni che decidono se il flusso di copertura
    e' abbastanza grande da contare oggi. Calcolo DETERMINISTICO: se lo lasciassimo
    interpretare al modello, gli stessi numeri darebbero letture diverse ogni run.

    GATE: la vicinanza ai muri e' condizione necessaria. Un posizionamento enorme
    concentrato dove il prezzo NON e' non produce flusso: se manca, il punteggio
    e' limitato a 1 qualunque siano le altre condizioni.
    """
    nearest = min((abs(w["dist_pct"]) for w in walls), default=None)
    wall_met = nearest is not None and nearest <= TH_WALL_PCT

    expiry_met = (days_to_major_expiry is not None
                  and days_to_major_expiry <= TH_EXPIRY_DAYS
                  and (oi_share_major or 0) >= TH_EXPIRY_OI_SHARE)

    iv_met = dvol_pct_rank is not None and dvol_pct_rank <= TH_IV_RANK

    ratio = None
    if typical_hourly_notional:
        ratio = gex_abs_usd_per_1pct / typical_hourly_notional
    thin_met = ratio is not None and ratio >= TH_THINNESS

    score = sum((wall_met, expiry_met, iv_met, thin_met))
    if not wall_met:
        score = min(score, 1)   # il gate

    label, headline = {
        4: ("dominante",
            "Il gamma e' oggi il fattore dominante sull'azione del prezzo."),
        3: ("rilevante",
            "Il gamma e' oggi un fattore rilevante, probabilmente il principale."),
        2: ("secondario",
            "Il gamma e' un fattore secondario, non il motore principale."),
    }.get(score, ("irrilevante",
                  "Il posizionamento in opzioni oggi e' verosimilmente irrilevante: "
                  "altri fattori (flusso, macro, liquidazioni) contano di piu'."))

    return {
        "score": score,
        "label": label,
        "headline": headline,
        "components": {
            "wall_proximity": {"met": wall_met, "value": nearest,
                               "unit": "%", "threshold": TH_WALL_PCT,
                               "note": "condizione necessaria (gate)"},
            "expiry_pressure": {"met": expiry_met, "value": days_to_major_expiry,
                                "unit": "giorni", "threshold": TH_EXPIRY_DAYS},
            "iv_compression": {"met": iv_met, "value": dvol_pct_rank,
                               "unit": "pct_rank", "threshold": TH_IV_RANK,
                               "note": "IV BASSA concentra il gamma e rafforza l'effetto"},
            "market_thinness": {"met": thin_met,
                                "value": round(ratio, 4) if ratio is not None else None,
                                "unit": "ratio", "threshold": TH_THINNESS},
        },
    }


# --------------------------------------------------------------------- #
# Assemblaggio del blocco completo per lo snapshot
# --------------------------------------------------------------------- #
def build_gamma_block(chain: list[dict], spot: float,
                      dvol_pct_rank: float | None = None,
                      typical_hourly_notional: float | None = None,
                      now_ms: int | None = None,
                      dealer_convention: str = "long_calls_short_puts") -> dict:
    """Costruisce metrics.gamma completo (aggregate + profile + expiry + significance)."""
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    total = aggregate_gex(chain, spot, now_ms, dealer_convention)
    points = gex_profile(chain, spot, now_ms=now_ms, dealer_convention=dealer_convention)
    flip = find_flip_point(points, spot)
    walls = gamma_walls(chain, spot, now_ms=now_ms, dealer_convention=dealer_convention)

    # scadenza principale = quella con piu' open interest tra le future
    oi_by_exp: dict[int, float] = {}
    for o in chain:
        if o["expiry_ms"] > now_ms:
            oi_by_exp[o["expiry_ms"]] = oi_by_exp.get(o["expiry_ms"], 0.0) + (o.get("open_interest") or 0.0)
    days_major = share_major = next_major = None
    if oi_by_exp:
        exp_ms = max(oi_by_exp, key=lambda k: oi_by_exp[k])
        tot_oi = sum(oi_by_exp.values())
        days_major = round((exp_ms - now_ms) / (1000 * 60 * 60 * 24), 2)
        share_major = round(oi_by_exp[exp_ms] / tot_oi, 3) if tot_oi else None
        next_major = datetime.fromtimestamp(exp_ms / 1000, timezone.utc).strftime("%Y-%m-%d")

    return {
        "as_of": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
        "source": "deribit",
        "spot_ref": round(spot, 2),
        "dealer_convention": dealer_convention,
        "aggregate": {
            "gex_usd_per_1pct": round(total, 2),
            "regime": "positivo" if total > 0 else "negativo",
            "flip_point": flip,
            "price_vs_flip": (None if flip is None
                              else ("sopra" if spot > flip else "sotto")),
            "dist_to_flip_pct": (None if flip is None
                                 else round((spot - flip) / spot * 100, 2)),
        },
        "profile": {"grid_step_pct": 0.25, "range_pct": 10.0,
                    "points": points, "cliffs": walls},
        "expiry": {"next_major": next_major,
                   "days_to_next_major": days_major,
                   "oi_share_next_major": share_major},
        "significance": significance(walls, days_major, share_major, dvol_pct_rank,
                                     abs(total), typical_hourly_notional),
    }
