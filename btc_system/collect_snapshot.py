#!/usr/bin/env python3
"""
collect_snapshot.py
-------------------
Raccolta SILENZIOSA di uno snapshot, pensata per girare in cron (ogni ora).
NON chiama l'Agente 1, NON usa l'API Anthropic, NON stampa report: si limita a
raccogliere i dati Binance, costruire lo snapshot e salvarlo nel database
(data/snapshots.db + JSON), che e' il mattone dello storico.

Differenza dal report on-demand:
  - run_agent1.py  -> lo chiedi TU quando vuoi un briefing (costa una chiamata API)
  - collect_snapshot.py -> gira in sottofondo SEMPRE, riempie solo lo storico

Uso manuale (per provarlo):
    python3 collect_snapshot.py
    python3 collect_snapshot.py --nota "test cron"

In cron non serve --nota: l'annotazione e' per i run umani. Gli snapshot
automatici restano senza nota (campo note = "auto").

Codici di uscita: 0 = ok, 1 = errore (utile a cron per non sovrascrivere log buoni).
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# permette di lanciarlo da qualsiasi cartella (cron parte da home)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_collector import DataCollector


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Raccolta snapshot silenziosa (per cron, senza Agente).")
    parser.add_argument("--nota", type=str, default="auto",
                        help="Annotazione opzionale (default 'auto' per i run schedulati).")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        dc = DataCollector(args.symbol)
        snap = dc.collect(note=args.nota)
        # una riga di log essenziale su stdout (cron la puo' redirigere su file)
        price = snap.get("price")
        sess = snap.get("session", {}).get("name", "?")
        print(f"{ts}  OK  {args.symbol} price={price} session={sess}")
        return 0
    except Exception as e:
        # in caso di errore (rete giu', API Binance lenta) NON crasha rumorosamente:
        # logga e esce con codice 1, cosi' il prossimo run riprova tra un'ora.
        print(f"{ts}  ERRORE  {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
