"""
run_agent2.py
-------------
Esegue un ciclo completo: raccoglie lo snapshot, genera il report dell'Agente 2
("Chi muove il prezzo"), lo stampa a video e lo salva in data/reports/.

Uso:
  python3 run_agent2.py
  python3 run_agent2.py --nota "dopo il dato USA"
  python3 run_agent2.py --con-agente1          # briefing: Agente 1 + Agente 2
  python3 run_agent2.py --source synthetic --no-agent
  python3 run_agent2.py --source synthetic     # prova la chiamata su dati finti

Opzioni:
  --nota "<testo>"   Annotazione del momento del run (perche' lo stai lanciando).
                     Viene salvata nello snapshot e mostrata in testa al report.
  --source synthetic Usa dati FINTI per testare la pipeline senza Binance.
  --no-agent         Mostra solo la porzione di snapshot che l'Agente 2 leggerebbe,
                     senza chiamare l'API. Utile per verificare quali sezioni
                     saranno omesse (dati mancanti).
  --con-agente1      Genera prima l'Agente 1 e poi l'Agente 2, concatenati.

Richiede ANTHROPIC_API_KEY nell'ambiente (tranne con --no-agent).

NOTA sulla Versione 1: finche' il collector non raccoglie spot/Deribit, l'Agente 2
omettera' le sezioni CVD spot, premio Coinbase, gamma (GEX) e heatmap, segnalando
che i dati non sono disponibili. E' il comportamento previsto, non un errore.
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


def save_report(text: str, symbol: str, note: str | None, prefix: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    suffix = f"_{slugify(note)}" if note else ""
    path = REPORTS_DIR / f"{prefix}_{ts}_{symbol}{suffix}.txt"
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
    parser = argparse.ArgumentParser(description="Agente 2 - Chi muove il prezzo")
    parser.add_argument("--nota", type=str, default=None,
                        help="Annotazione del momento del run")
    parser.add_argument("--source", choices=["binance", "synthetic"], default="binance",
                        help="Fonte dati (default: binance)")
    parser.add_argument("--no-agent", action="store_true",
                        help="Mostra solo la vista snapshot dell'Agente 2, senza chiamare l'API")
    parser.add_argument("--con-agente1", action="store_true",
                        help="Genera anche l'Agente 1 e concatena i due report")
    args = parser.parse_args()

    snapshot = get_snapshot(args.source, args.nota)

    if args.no_agent:
        from agents.agent2 import build_agent2_view
        view = build_agent2_view(snapshot)
        print(json.dumps(view, indent=2, default=str))
        # segnala esplicitamente cosa manca per la Versione 2
        flow = view.get("flow", {})
        metrics = view.get("metrics", {})
        mancanti = [n for n, ok in (
            ("CVD spot", "cvd_spot" in flow),
            ("premio Coinbase", "coinbase_premium" in flow),
            ("gamma (GEX)", "gamma" in metrics),
            ("heatmap liquidazione", "liq_heatmap" in metrics),
        ) if not ok]
        if mancanti:
            print("\n[i] Sezioni che l'Agente 2 omettera' (dati non ancora raccolti):")
            for m in mancanti:
                print(f"    - {m}")
        return

    blocks = []
    if args.con_agente1:
        from agents.agent1 import run_agent1
        blocks.append(("AGENTE 1 - Fotografia del mercato", run_agent1(snapshot)))

    from agents.agent2 import run_agent2
    blocks.append(("AGENTE 2 - Chi muove il prezzo", run_agent2(snapshot)))

    header_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"RUN: {header_ts}"
    if args.nota:
        header += f"  |  Nota: {args.nota}"

    parts = [header, "-" * 60]
    for title, text in blocks:
        parts += [f"\n### {title}\n", text]
    full = "\n".join(parts)

    print("=" * 60)
    print(full)
    print("=" * 60)

    prefix = "briefing" if args.con_agente1 else "agente2"
    path = save_report(full, snapshot.get("symbol", "BTCUSDT"), args.nota, prefix)
    print(f"\nReport salvato in: {path}")


if __name__ == "__main__":
    main()
