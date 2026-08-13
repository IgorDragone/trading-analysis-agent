#!/usr/bin/env python3
"""
check_sources.py
----------------
Diagnostica delle fonti dati NUOVE (spot + Deribit/GEX), isolate dal resto.
Serve al primo collaudo sul VPS: dice quale fonte risponde e quale no, senza
dover lanciare un briefing completo (e senza spendere API Anthropic).

Uso:
    python3 check_sources.py

Non chiama l'API Anthropic. Usa solo endpoint pubblici (nessuna chiave).
"""

import sys
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def check_spot():
    print("\n--- SPOT (Binance spot + Coinbase) ---")
    try:
        from collectors.spot_client import SpotClient
        sc = SpotClient()
        k = sc.spot_klines("BTCUSDT", "15m", 20)
        print(f"  OK  klines spot: {len(k)} candele, ultimo close {k[-1]['close']}")
        prem = sc.coinbase_premium("BTCUSDT")
        print(f"  OK  premio Coinbase: {prem['premium_pct']:+.4f}% ({prem['direction']})")
        print(f"      Coinbase {prem['coinbase_price']} vs Binance spot {prem['binance_spot_price']}")
        return True
    except Exception as e:
        print(f"  KO  {type(e).__name__}: {e}")
        return False


def check_deribit():
    print("\n--- DERIBIT (catena opzioni + DVOL + GEX) ---")
    try:
        from collectors.deribit_client import DeribitClient
        from engine.gex import build_gamma_block
        dc = DeribitClient()

        spot = dc.index_price("btc_usd")
        print(f"  OK  indice BTC: {spot:,.2f}")

        chain = dc.option_chain("BTC")
        with_oi = [o for o in chain if o["open_interest"] > 0]
        print(f"  OK  catena opzioni: {len(chain)} strumenti ({len(with_oi)} con OI > 0)")
        if not with_oi:
            print("  !!  nessuno strumento con open interest: GEX non calcolabile")
            return False

        hist = dc.dvol_history("BTC", days=120)
        rank = dc.dvol_percentile_rank(hist)
        last = hist[-1]["close"] if hist else None
        print(f"  OK  DVOL: {len(hist)} giorni di storico, ultimo {last}, "
              f"rango percentile {rank}")

        gb = build_gamma_block(chain, spot, dvol_pct_rank=rank,
                               typical_hourly_notional=None)
        agg = gb["aggregate"]
        sig = gb["significance"]
        print(f"\n  GEX totale: {agg['gex_usd_per_1pct']:,.0f} $ per 1%  "
              f"-> regime {agg['regime'].upper()}")
        print(f"  Flip point: {agg['flip_point']} (prezzo {agg['price_vs_flip']}, "
              f"{agg['dist_to_flip_pct']}%)")
        print("  Muri principali:")
        for w in gb["profile"]["cliffs"]:
            print(f"    {w['price']:>10,.0f}  {w['sign']:<9} {w['side']:<6} "
                  f"{w['dist_pct']:+.2f}%")
        print(f"  Scadenza principale: {gb['expiry']['next_major']} "
              f"(tra {gb['expiry']['days_to_next_major']} giorni, "
              f"quota OI {gb['expiry']['oi_share_next_major']})")
        print(f"\n  SIGNIFICATIVITA': {sig['score']}/4 -> {sig['label'].upper()}")
        print(f"  \"{sig['headline']}\"")
        for name, c in sig["components"].items():
            flag = "SI" if c["met"] else "no"
            print(f"    [{flag}] {name:<17} valore={c['value']} soglia={c['threshold']}")
        print("\n  NB: 'market_thinness' qui e' assente perche' serve il volume orario")
        print("      da Binance; nello snapshot completo viene calcolato.")
        return True
    except Exception as e:
        print(f"  KO  {type(e).__name__}: {e}")
        return False


def main():
    print("=" * 62)
    print("DIAGNOSTICA FONTI DATI — nessuna chiave, nessun costo API")
    print("=" * 62)
    ok_spot = check_spot()
    ok_der = check_deribit()
    print("\n" + "=" * 62)
    print(f"  spot (CVD spot + premio Coinbase): {'OK' if ok_spot else 'NON DISPONIBILE'}")
    print(f"  Deribit (GEX + DVOL):              {'OK' if ok_der else 'NON DISPONIBILE'}")
    print("=" * 62)
    print("Le fonti non disponibili non bloccano il sistema: gli agenti")
    print("dichiarano il campo assente e abbassano la fiducia.")
    return 0 if (ok_spot and ok_der) else 1


if __name__ == "__main__":
    sys.exit(main())
