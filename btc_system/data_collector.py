"""
data_collector.py
-----------------
Cuore del sistema: raccoglie i dati da Binance in UNO snapshot timestamped,
applica il motore di calcolo e salva tutto.

PRINCIPIO: snapshot coerente. Tutti i dati sono raccolti in una finestra
temporale stretta, cosi' che prezzo, CVD, OI, funding e Volume Profile si
riferiscano allo stesso momento di mercato. Gli agenti leggono lo snapshot,
non chiamano le API.

FASE 1 (questa): fonte unica Binance. Lo snapshot alimenta l'Agente 1
("Fotografia del mercato") in pieno, e una prima versione dell'Agente 2 con i
dati di flusso Binance (CVD perp, OI, funding). Spot, premio Coinbase e gamma
arriveranno nelle fasi successive.
"""

import statistics
from datetime import datetime, timezone

from engine.volume_profile import volume_profile, session_profiles, naked_pocs
from engine.regime import classify_regime
from engine.session import classify_session
from engine.semaphores import semaphore
from engine.indicators import (
    vwap_bands, vwap_distance_sigma, cvd_metrics, golden_rule,
    pct_change_24h, volatility_context,
)
from storage.snapshot_store import SnapshotStore

# Finestra breve della Regola d'Oro: 4 candele da 15m = circa 1 ora.
# Prezzo, CVD e OI usano TUTTI la stessa finestra.
LOOKBACK = 4

# Finestra lunga della Regola d'Oro: 16 candele da 15m = circa 4 ore.
# Le due finestre si leggono insieme: concordanza = segnale piu' solido;
# divergenza = il breve termine si muove contro il contesto delle ultime ore.
LOOKBACK_LONG = 16

# Giorni usati per il volume profile "macro" (campo volume_profile.1d).
# 30 giorni = circa un mese di contesto: abbastanza per livelli significativi,
# non tanto da rendere l'area di valore cosi' larga da non dire nulla.
# DA CALIBRARE guardando l'ampiezza dell'area di valore prodotta.
VP_DAILY_LOOKBACK = 30


def build_snapshot(symbol: str, k15: list[dict], k1h: list[dict],
                   k1d: list[dict], flow_raw: dict, note: str | None = None) -> dict:
    """
    Costruisce lo snapshot completo dai dati grezzi (candele + flusso).
    Separato dalla raccolta cosi' da poter essere riusato anche in test offline
    con candele sintetiche.

    flow_raw: dict con funding_rate, open_interest, bsvr, oi_hist (lista).
    """
    ts = datetime.now(timezone.utc).isoformat()
    price = k15[-1]["close"]

    # ---- Volume Profile su 3 timeframe ----
    vp_15 = volume_profile(k15)
    vp_1h = volume_profile(k1h)
    vp_1d = volume_profile(k1d[-VP_DAILY_LOOKBACK:])

    # ---- Session VP + Naked POC (con filtro volume) ----
    sessions = session_profiles(k15)
    naked = naked_pocs(sessions, price)

    # ---- VWAP di sessione (candele del giorno UTC corrente) ----
    today = datetime.fromtimestamp(k15[-1]["time"] / 1000, timezone.utc).strftime("%Y-%m-%d")
    today_candles = [c for c in k15
                     if datetime.fromtimestamp(c["time"] / 1000, timezone.utc).strftime("%Y-%m-%d") == today]
    vwap_session = vwap_bands(today_candles) if today_candles else None
    if vwap_session:
        vwap_session["dist_sigma"] = vwap_distance_sigma(
            price, vwap_session["vwap"], vwap_session["std"])

    # ---- 24h e volatilita' ----
    chg_24h = pct_change_24h(k15)
    vol_ctx = volatility_context(k1d, today_candles)

    # ---- Flusso (per Agente 2 piu' avanti; Agente 1 lo IGNORA) ----
    cvd = cvd_metrics(k15, lookback=LOOKBACK)
    oi_hist = flow_raw.get("oi_hist", [])

    def _rule_for(lb: int) -> dict | None:
        """Regola d'Oro su una finestra di `lb` candele da 15m."""
        if len(k15) <= lb:
            return None
        c = cvd_metrics(k15, lookback=lb)
        price_chg = k15[-1]["close"] - k15[-1 - lb]["close"]
        # OI sulla STESSA finestra di prezzo e CVD. Se non c'e', non inventiamo
        # un delta OI a zero: la regola su quella finestra non e' valutabile.
        if len(oi_hist) <= lb:
            return None
        oi_chg = oi_hist[-1]["oi"] - oi_hist[-1 - lb]["oi"]
        rule = golden_rule(price_chg, c["delta"], oi_chg, ref_price=k15[-1]["close"])
        rule["window"] = f"{lb * 15} minuti"
        return rule

    rule = _rule_for(LOOKBACK)
    rule_long = _rule_for(LOOKBACK_LONG)

    if rule and rule_long and rule.get("applicable") and rule_long.get("applicable"):
        if rule["signal"] == rule_long["signal"]:
            combined = ("concorde", "Le due finestre danno la stessa lettura: segnale piu' solido.")
        else:
            combined = ("divergente",
                        "Le due finestre danno letture diverse: il breve termine "
                        "si muove contro il contesto delle ultime ore.")
    else:
        combined = ("non valutabile",
                    "Una delle due finestre non e' applicabile: movimento sotto "
                    "soglia o dati insufficienti.")

    snapshot = {
        "ts_utc": ts,
        "symbol": symbol,
        "price": price,
        "price_24h_change_pct": chg_24h,
        # annotazione umana del momento del run (es. "pre-London, post-CPI").
        # E' contesto per lo storico/backtest; l'Agente 1 la IGNORA.
        "note": note,
        # ---- per Agente 1 (fotografia) ----
        "metrics": {
            "vwap_session": vwap_session,
            "volume_profile": {
                "15m": {k: vp_15[k] for k in ("poc", "vah", "val", "hi", "lo")},
                "1h": {k: vp_1h[k] for k in ("poc", "vah", "val", "hi", "lo")},
                "1d": {k: vp_1d[k] for k in ("poc", "vah", "val", "hi", "lo")},
            },
            "naked_pocs": naked[:5],          # i 5 magneti piu' vicini
            "volatility": vol_ctx,
        },
        # ---- REGIME (indicatore per Agente 3; Agente 1 lo IGNORA) ----
        # Filtro trend/laterale sul timeframe operativo. Si accumula gia' nello
        # storico; l'Agente 3 lo leggera' per modulare il mean reversion.
        # NOTA: la validazione storica ha mostrato che il regime (ADX+ER) separa
        # i rientri solo debolmente -> e' un input SECONDARIO. Il fattore di
        # contesto piu' forte e' la SESSIONE oraria (campo "session" qui sotto),
        # che l'Agente 3 deve pesare di piu' del regime.
        "regime": {
            "primary": "1h",
            "1h": classify_regime(k1h, "1h"),
            "15m": classify_regime(k15, "15m"),
        },
        # ---- SESSIONE oraria (fattore di contesto PRIMARIO per Agente 3) ----
        # Asia/prima Londra = mean-reverting (favorevole); New York = direzionale
        # (sfavorevole). E' il segnale di contesto piu' robusto emerso dai dati.
        "session": classify_session(k15[-1]),
        # ---- SEMAFORI operativi (engine, deterministici) ----
        # freno di avvicinamento + sensore livelli chiave + veto GEX.
        # gex viene letto dal flow se presente, altrimenti None (-> grigio).
        "semaphores": semaphore(k1h, k1d,
                                gex=(flow_raw.get("gex") if isinstance(flow_raw, dict) else None)),
        # ---- per Agente 2 (chi muove) - Agente 1 NON usa questa sezione ----
        "flow": {
            "funding_rate": flow_raw.get("funding_rate"),
            "open_interest": flow_raw.get("open_interest"),
            "bsvr": flow_raw.get("bsvr"),
            "cvd": cvd,                        # direzione/pendenza/divergenza
            # CVD SPOT e premio Coinbase: presenti solo se le fonti spot hanno
            # risposto. Servono all'Agente 2 per distinguere il denaro reale
            # dalla costruzione a leva (la conferma dello spot).
            **({"cvd_spot": flow_raw["cvd_spot"]} if flow_raw.get("cvd_spot") else {}),
            **({"coinbase_premium": flow_raw["coinbase_premium"]}
               if flow_raw.get("coinbase_premium") else {}),
            "golden_rule": rule,
            **({"golden_rule_long": rule_long} if rule_long else {}),
            "golden_rule_combined": {"status": combined[0], "note": combined[1]},
        },
    }
    return snapshot


class DataCollector:
    def __init__(self, symbol: str = "BTCUSDT", api_key: str | None = None,
                 with_spot: bool = True, with_gamma: bool = True):
        from collectors.binance_client import BinanceClient

        self.symbol = symbol
        self.binance = BinanceClient(api_key=api_key)
        self.store = SnapshotStore()
        # Le fonti aggiuntive sono OPZIONALI e non devono mai far fallire la
        # raccolta: se Coinbase o Deribit non rispondono, lo snapshot esce
        # comunque e gli agenti dichiarano il campo assente.
        self.with_spot = with_spot
        self.with_gamma = with_gamma

    def collect(self, note: str | None = None) -> dict:
        """Raccoglie i dati, costruisce e salva lo snapshot."""
        k15 = self.binance.klines(self.symbol, "15m", 300)
        k1h = self.binance.klines(self.symbol, "1h", 300)
        k1d = self.binance.klines(self.symbol, "1d", 300)

        flow_raw = {
            "funding_rate": self.binance.funding_rate(self.symbol, 1)[-1]["rate"],
            "open_interest": self.binance.open_interest(self.symbol)["oi"],
            "bsvr": (self.binance.taker_ratio(self.symbol, "15m", 5) or [{}])[-1].get("ratio"),
            "oi_hist": self.binance.open_interest_hist(self.symbol, "15m", 40),
        }

        # ---- SPOT (CVD spot + premio Coinbase) - best effort ----
        if self.with_spot:
            try:
                from collectors.spot_client import SpotClient
                sc = SpotClient()
                spot_k15 = sc.spot_klines(self.symbol, "15m", 300)
                flow_raw["cvd_spot"] = cvd_metrics(spot_k15, lookback=LOOKBACK)
                flow_raw["coinbase_premium"] = sc.coinbase_premium(self.symbol)
            except Exception as e:
                print(f"[i] dati spot non disponibili ({type(e).__name__}): "
                      f"l'Agente 2 omettera' le sezioni relative")

        # ---- GAMMA / GEX (Deribit) - best effort ----
        gamma_block = None
        if self.with_gamma:
            try:
                from collectors.deribit_client import DeribitClient
                from engine.gex import build_gamma_block
                dc = DeribitClient()
                chain = dc.option_chain("BTC")
                spot_ref = dc.index_price("btc_usd")
                hist = dc.dvol_history("BTC", days=120)
                rank = dc.dvol_percentile_rank(hist)
                # volume nozionale orario tipico: mediana delle ultime 24 ore
                # (serve alla condizione "quanta liquidita' c'e' dall'altra parte")
                recent = [k["quote_volume"] for k in k1h[-24:] if k.get("quote_volume")]
                typical = statistics.median(recent) if recent else None
                gamma_block = build_gamma_block(chain, spot_ref,
                                                dvol_pct_rank=rank,
                                                typical_hourly_notional=typical)
                flow_raw["gex"] = gamma_block["aggregate"]["gex_usd_per_1pct"]
            except Exception as e:
                print(f"[i] dati gamma/GEX non disponibili ({type(e).__name__}): "
                      f"gli agenti dichiareranno il campo assente")

        snapshot = build_snapshot(self.symbol, k15, k1h, k1d, flow_raw, note=note)
        if gamma_block:
            snapshot["metrics"]["gamma"] = gamma_block
        self.store.save(snapshot)
        return snapshot


if __name__ == "__main__":
    import json
    dc = DataCollector("BTCUSDT")
    snap = dc.collect()
    print(json.dumps(snap, indent=2, default=str))
