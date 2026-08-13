"""
test_offline.py
---------------
Test della pipeline SENZA rete (ne' Binance ne' API Anthropic).
Verifica che engine + costruzione snapshot funzionino e che lo schema sia
quello atteso dall'Agente 1.

Uso:  python3 tests/test_offline.py
(eseguire dalla cartella btc_system)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.synthetic import synthetic_snapshot
from engine.indicators import golden_rule, cvd_metrics
from engine.session import classify_session


def test_golden_rule_windows():
    # finestre coerenti: prezzo giu' + CVD giu' + OI su = nuovi short
    r = golden_rule(-100, -50, +200)
    assert r["signal"].startswith("Nuovi short"), r
    print("OK  golden_rule classifica i nuovi short")


def test_cvd_only_direction():
    candles = [{"high": 100, "low": 99, "close": 100, "volume": 10,
                "taker_buy_volume": 7} for _ in range(10)]
    m = cvd_metrics(candles)
    # cvd_metrics non deve esporre un valore assoluto del CVD
    assert "cvd" not in m and "direction" in m and "divergence_vs_price" in m
    print("OK  cvd_metrics espone solo direzione/divergenza, non il valore assoluto")


def test_snapshot_schema():
    snap = synthetic_snapshot()
    # campi che l'Agente 1 si aspetta
    assert snap["price"] > 0
    assert "price_24h_change_pct" in snap
    m = snap["metrics"]
    assert "vwap_session" in m and "dist_sigma" in m["vwap_session"]
    assert set(m["volume_profile"].keys()) == {"15m", "1h", "1d"}
    assert "naked_pocs" in m and "volatility" in m
    # la sezione flow esiste ma e' separata (Agente 1 la ignora)
    assert "flow" in snap and "golden_rule" in snap["flow"]
    # il regime e' presente (indicatore per Agente 3)
    assert "regime" in snap and snap["regime"]["primary"] == "1h"
    assert snap["regime"]["1h"]["state"] in ("trend", "laterale", "transizione", "n/d")
    assert snap["regime"]["1h"]["mean_reversion_context"] in ("favorevole", "sfavorevole", "neutro", "n/d")
    print("OK  lo snapshot ha lo schema atteso dall'Agente 1")
    print("OK  il regime e' presente nello snapshot (per l'Agente 3)")
    # la sessione e' presente (fattore di contesto primario per l'Agente 3)
    assert "session" in snap
    s = snap["session"]
    assert s["name"] in ("asia", "london", "ny", "late")
    assert s["mean_reversion_context"] in ("favorevole", "sfavorevole", "neutro")
    assert isinstance(s["in_entry_window"], bool)
    print("OK  la sessione oraria e' presente nello snapshot (per l'Agente 3)")
    assert "semaphores" in snap and snap["semaphores"]["state"] in ("VERDE","FRENO","GRIGIO")
    assert "key_levels" in snap["semaphores"]
    print("OK  i semafori operativi sono presenti nello snapshot")


def test_session_windows():
    # confini chiave: Asia favorevole e dentro la finestra d'ingresso 00-07
    asia = classify_session(hour=3)
    assert asia["name"] == "asia"
    assert asia["mean_reversion_context"] == "favorevole"
    assert asia["in_entry_window"] is True
    # New York sfavorevole e fuori dalla finestra d'ingresso
    ny = classify_session(hour=15)
    assert ny["name"] == "ny"
    assert ny["mean_reversion_context"] == "sfavorevole"
    assert ny["in_entry_window"] is False
    # le 7:00 escono dalla finestra d'ingresso (Asia 00-07 esclusa la 7)
    assert classify_session(hour=7)["in_entry_window"] is False
    print("OK  classify_session distingue Asia (favorevole) da New York (sfavorevole)")


def test_golden_rule_mechanics():
    # Uno squeeze/covering CHIUDE posizioni -> OI in CALO, CVD in salita.
    # Non deve MAI comparire "squeeze" con OI in aumento.
    sq = golden_rule(price_change=+1, cvd_change=+1, oi_change=-1)
    assert "covering" in sq["signal"].lower() or "squeeze" in sq["signal"].lower()
    nonsq = golden_rule(price_change=+1, cvd_change=-1, oi_change=+1)
    assert "squeeze" not in nonsq["signal"].lower(), "squeeze non puo' avere OI in aumento"
    assert "assorbit" in nonsq["signal"].lower()
    # La capitolazione dei long e' vendita aggressiva -> CVD in CALO.
    cap = golden_rule(price_change=-1, cvd_change=-1, oi_change=-1)
    assert "capitulation" in cap["signal"].lower()
    absorb = golden_rule(price_change=-1, cvd_change=+1, oi_change=-1)
    assert "capitulation" not in absorb["signal"].lower(), "CVD in salita = assorbimento, non capitolazione"
    assert "assorbimento" in absorb["signal"].lower()
    print("OK  Regola d'Oro: squeeze con OI in calo, capitolazione con CVD in calo")


def test_agent2_view():
    from agents.agent2 import build_agent2_view
    snap = synthetic_snapshot("BTCUSDT", note="t")
    view = build_agent2_view(snap)
    # deve vedere il flusso e il posizionamento
    assert "flow" in view
    assert "golden_rule" in view["flow"]
    assert "cvd" in view["flow"]
    # NON deve vedere cio' che e' di competenza degli altri agenti
    assert "metrics" not in view or "volume_profile" not in view.get("metrics", {})
    assert "semaphores" not in view, "i semafori non sono competenza dell'Agente 2"
    assert "regime" not in view and "session" not in view, "regime/session sono per l'Agente 3"
    # i campi della Versione 2 non ci sono ancora: l'agente li omettera'
    assert "gamma" not in view.get("metrics", {})
    print("OK  la vista dell'Agente 2 contiene il flusso e rispetta i confini")


def test_golden_rule_two_windows():
    from agents.agent2 import build_agent2_view
    snap = synthetic_snapshot("BTCUSDT", note="t")
    flow = snap["flow"]
    assert flow["golden_rule"]["window"] == "60 minuti"
    assert flow["golden_rule_long"]["window"] == "240 minuti"
    assert flow["golden_rule_combined"]["status"] in (
        "concorde", "divergente", "non valutabile")
    view = build_agent2_view(snap)
    assert "golden_rule" in view["flow"]
    assert "golden_rule_long" in view["flow"]
    assert "golden_rule_combined" in view["flow"]
    print("OK  Regola d'Oro: doppia finestra 1h+4h presente nella vista Agente 2")


def test_gamma_compacted_for_agents():
    from agents.agent2 import build_agent2_view
    from agents.agent3 import build_agent3_view
    snap = synthetic_snapshot("BTCUSDT", note="t")
    snap["metrics"]["gamma"] = {
        "aggregate": {"regime": "positivo", "flip_point": 65000},
        "profile": {
            "grid_step_pct": 0.25,
            "range_pct": 10.0,
            "points": [{"price": 64000, "gex": 1}, {"price": 64100, "gex": 2}],
            "cliffs": [{"price": 65000, "gex": 10}],
        },
        "expiry": {"next_major": "2026-09-25"},
        "significance": {"score": 2, "label": "secondario"},
    }
    for view in (build_agent2_view(snap), build_agent3_view(snap)):
        gamma = view["metrics"]["gamma"]
        assert "points" not in gamma["profile"], "la curva completa resta nello snapshot, non nel prompt"
        assert "cliffs" in gamma["profile"]
        assert "significance" in gamma
    print("OK  gamma compatto nelle viste agenti: niente curva completa nel prompt")


def test_agent3_view_and_message():
    from agents.agent3 import build_agent3_view, build_user_message, missing_inputs
    snap = synthetic_snapshot("BTCUSDT", note="t")
    view = build_agent3_view(snap)
    # deve vedere i LIVELLI e il CONTESTO
    assert "metrics" in view and "vwap_session" in view["metrics"]
    assert "regime" in view and "session" in view
    # NON deve vedere il flusso grezzo (arriva interpretato dal report Agente 2)
    assert "flow" not in view, "il flusso e' competenza dell'Agente 2"
    # input assenti dichiarati correttamente
    assenti = missing_inputs(snap, None, None)
    assert any("confluenza" in a for a in assenti)
    assert any("gamma" in a for a in assenti)
    # il messaggio etichetta i report e segnala la degradazione
    msg = build_user_message(snap, "report uno", None)
    assert "REPORT AGENTE 1" in msg and "report uno" in msg
    assert "(non disponibile)" in msg
    assert "INPUT NON DISPONIBILI" in msg
    print("OK  la vista dell'Agente 3 ha livelli+contesto e dichiara gli input assenti")


def test_golden_rule_significance():
    # movimento minuscolo (20$ su 65.000 = 0,03%): NON deve produrre etichette
    # drammatiche tipo "trend ribassista genuino"
    r = golden_rule(price_change=-20, cvd_change=-194, oi_change=+500,
                    ref_price=65000)
    assert r["applicable"] is False
    assert "non applicabile" in r["signal"].lower()
    assert "trend" not in r["signal"].lower()
    # movimento vero (300$ su 65.000 = 0,46%): la regola si applica
    r2 = golden_rule(price_change=-300, cvd_change=-194, oi_change=+500,
                     ref_price=65000)
    assert r2["applicable"] is True
    assert "trend ribassista" in r2["signal"].lower()
    # senza ref_price il controllo e' disattivato (retrocompatibilita')
    r3 = golden_rule(-20, -194, +500)
    assert r3["applicable"] is True
    print("OK  Regola d'Oro: soglia di significativita' blocca le diagnosi del rumore")


def test_gex_math():
    from engine.gex import (bs_gamma, build_gamma_block, find_flip_point,
                            aggregate_gex)
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    spot = 65000.0
    # gamma massima ATM e crescente verso la scadenza (proprieta' note)
    assert bs_gamma(spot, 65000, 0.5, 3/365) > bs_gamma(spot, 75000, 0.5, 3/365)
    assert bs_gamma(spot, 65000, 0.5, 1/365) > bs_gamma(spot, 65000, 0.5, 30/365)
    # input degeneri non esplodono
    assert bs_gamma(spot, 65000, 0.5, 0) == 0.0
    assert bs_gamma(spot, 65000, 0, 0.1) == 0.0

    exp = int((now + timedelta(days=3)).timestamp() * 1000)
    chain = [
        {"strike": 66000, "option_type": "call", "expiry_ms": exp,
         "open_interest": 2000, "iv": 0.50},
        {"strike": 64000, "option_type": "put", "expiry_ms": exp,
         "open_interest": 300, "iv": 0.52},
    ]
    b = build_gamma_block(chain, spot, dvol_pct_rank=0.30,
                          typical_hourly_notional=300_000_000, now_ms=now_ms)
    # struttura completa: numero + curva, entrambi presenti
    assert b["aggregate"]["regime"] in ("positivo", "negativo")
    assert len(b["profile"]["points"]) > 10
    assert b["profile"]["cliffs"], "i muri devono essere individuati"
    # convenzione del segno: call = dealer long gamma (positivo)
    only_call = [chain[0]]
    assert aggregate_gex(only_call, spot, now_ms) > 0
    only_put = [chain[1]]
    assert aggregate_gex(only_put, spot, now_ms) < 0
    # il flip separa i due regimi
    pts = [{"price": 100, "gex": -5}, {"price": 110, "gex": 5}]
    assert 100 < find_flip_point(pts, 105) < 110
    # significativita': con muro lontano scatta il GATE (score max 1)
    far = [{"strike": 90000, "option_type": "call", "expiry_ms": exp,
            "open_interest": 9000, "iv": 0.5}]
    b2 = build_gamma_block(far, spot, dvol_pct_rank=0.1,
                           typical_hourly_notional=1000, now_ms=now_ms)
    assert b2["significance"]["score"] <= 1
    assert b2["significance"]["label"] == "irrilevante"
    print("OK  GEX: gamma BS corretta, curva+flip+muri, gate della significativita'")


if __name__ == "__main__":
    test_golden_rule_windows()
    test_cvd_only_direction()
    test_snapshot_schema()
    test_session_windows()
    test_golden_rule_mechanics()
    test_golden_rule_significance()
    test_agent2_view()
    test_golden_rule_two_windows()
    test_gamma_compacted_for_agents()
    test_agent3_view_and_message()
    test_gex_math()
    print("\nTutti i test offline superati.")
