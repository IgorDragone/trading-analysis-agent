"""
run_agent1.py
-------------
Esegue un ciclo completo: raccoglie lo snapshot, genera il report dell'Agente 1,
lo stampa a video e lo salva in data/reports/.

Uso:
  python3 run_agent1.py
  python3 run_agent1.py --nota "pre-London, post-CPI"
  python3 run_agent1.py --source synthetic --no-agent
  python3 run_agent1.py --no-agent

Opzioni:
  --nota "<testo>"   Annotazione del momento del run (perche' lo stai lanciando).
                     Viene salvata nello snapshot (storico/backtest), mostrata in
                     testa al report e aggiunta al nome del file. L'Agente 1 NON
                     la interpreta: resta contesto umano.
  --source synthetic Usa dati FINTI per testare la pipeline senza Binance.
  --no-agent         Genera solo lo snapshot, senza chiamare l'API Anthropic.

Richiede ANTHROPIC_API_KEY nell'ambiente (tranne con --no-agent).
"""

import re
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

REPORTS_DIR = Path("data/reports")


def slugify(text: str, maxlen: int = 30) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s[:maxlen].strip("-")


def save_report(text: str, symbol: str, note: str | None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    suffix = f"_{slugify(note)}" if note else ""
    path = REPORTS_DIR / f"agente1_{ts}_{symbol}{suffix}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def get_snapshot(source: str, note: str | None) -> dict:
    if source == "synthetic":
        from collectors.synthetic import synthetic_snapshot
        print("[!] MODALITA' SINTETICA: numeri finti, solo test della pipeline.\n")
        return synthetic_snapshot("BTCUSDT", note=note)
    from data_collector import DataCollector
    dc = DataCollector("BTCUSDT")
    return dc.collect(note=note)


def main():
    parser = argparse.ArgumentParser(description="Agente 1 - Fotografia del mercato")
    parser.add_argument("--nota", type=str, default=None,
                        help="Annotazione del momento del run (es. 'pre-London, post-CPI')")
    parser.add_argument("--source", choices=["binance", "synthetic"], default="binance",
                        help="Fonte dati (default: binance)")
    parser.add_argument("--no-agent", action="store_true",
                        help="Solo snapshot, senza chiamare l'API")
    args = parser.parse_args()

    snapshot = get_snapshot(args.source, args.nota)

    if args.no_agent:
        print(json.dumps(snapshot, indent=2, default=str))
        return

    from agents.agent1 import run_agent1
    report = run_agent1(snapshot)

    # intestazione con la nota (aggiunta da noi, non dall'IA)
    header_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"RUN: {header_ts}"
    if args.nota:
        header += f"  |  Nota: {args.nota}"
    full = f"{header}\n{'-' * 60}\n{report}"

    print("=" * 60)
    print(full)
    print("=" * 60)
    path = save_report(full, snapshot.get("symbol", "BTCUSDT"), args.nota)
    print(f"\nReport salvato in: {path}")


if __name__ == "__main__":
    main()
