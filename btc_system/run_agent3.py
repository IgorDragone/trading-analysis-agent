"""
run_agent3.py
-------------
Il BRIEFING COMPLETO a tre voci. Questo runner e' l'orchestratore minimo:
raccoglie lo snapshot, genera in sequenza Agente 1 (fotografia), Agente 2
(chi muove) e Agente 3 (condizioni), passando i primi due report al terzo,
e compone il briefing unito, stampato e salvato in data/reports/.

Uso:
  python3 run_agent3.py --nota "apertura Asia"     # briefing completo 1+2+3
  python3 run_agent3.py --solo                     # solo Agente 3 (degradato:
                                                   #  senza i report 1 e 2)
  python3 run_agent3.py --source synthetic --no-agent   # vista + input assenti,
                                                        #  senza chiamare l'API

Opzioni:
  --nota "<testo>"   Annotazione del momento del run (salvata e mostrata).
  --source synthetic Dati FINTI per testare la pipeline senza Binance.
  --no-agent         Mostra la vista snapshot dell'Agente 3 e gli input assenti,
                     senza chiamare l'API.
  --solo             Salta gli Agenti 1 e 2: l'Agente 3 lavora in modalita'
                     degradata dichiarata (fiducia abbassata). Utile per test
                     economici; il briefing vero e' quello completo.

Richiede ANTHROPIC_API_KEY (tranne con --no-agent).

NOTA (versione attuale): confluence_zones e gamma non sono ancora nel collector:
l'Agente 3 li dichiara assenti e abbassa la fiducia. E' il comportamento
previsto dal suo prompt, non un errore. Quando il modulo confluenze e il
collector GEX verranno attivati, il verdetto si rafforzera' da solo.
"""

import json
import argparse
from datetime import datetime, timezone

from run_agent2 import save_report  # riusa slugify/salvataggio


def get_snapshot(source: str, note: str | None) -> dict:
    if source == "synthetic":
        from collectors.synthetic import synthetic_snapshot
        print("[!] MODALITA' SINTETICA: numeri finti, solo test della pipeline.\n")
        return synthetic_snapshot("BTCUSDT", note=note)
    from data_collector import DataCollector
    return DataCollector("BTCUSDT").collect(note=note)


def main():
    parser = argparse.ArgumentParser(
        description="Agente 3 - Condizioni mean reversion (briefing completo)")
    parser.add_argument("--nota", type=str, default=None)
    parser.add_argument("--source", choices=["binance", "synthetic"], default="binance")
    parser.add_argument("--no-agent", action="store_true",
                        help="Mostra la vista dell'Agente 3 senza chiamare l'API")
    parser.add_argument("--solo", action="store_true",
                        help="Solo Agente 3, senza generare i report 1 e 2 (degradato)")
    args = parser.parse_args()

    snapshot = get_snapshot(args.source, args.nota)

    if args.no_agent:
        from agents.agent3 import build_agent3_view, missing_inputs
        print(json.dumps(build_agent3_view(snapshot), indent=2, default=str))
        assenti = missing_inputs(snapshot, None, None)
        print("\n[i] Input che l'Agente 3 dichiarera' assenti in questo run:")
        for a in assenti:
            print(f"    - {a}")
        print("\n[i] Con --solo mancherebbero anche i report 1 e 2 (fiducia abbassata).")
        return

    report1 = report2 = None
    blocks = []
    if not args.solo:
        from agents.agent1 import run_agent1
        from agents.agent2 import run_agent2
        print("[1/3] Agente 1 - fotografia...")
        report1 = run_agent1(snapshot)
        blocks.append(("AGENTE 1 - Fotografia del mercato", report1))
        print("[2/3] Agente 2 - chi muove...")
        report2 = run_agent2(snapshot)
        blocks.append(("AGENTE 2 - Chi muove il prezzo", report2))
        print("[3/3] Agente 3 - condizioni...\n")
    else:
        print("[--solo] Agente 3 in modalita' degradata (senza report 1 e 2)...\n")

    from agents.agent3 import run_agent3
    report3 = run_agent3(snapshot, report1, report2)
    blocks.append(("AGENTE 3 - Condizioni mean reversion", report3))

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

    prefix = "briefing3" if not args.solo else "agente3"
    path = save_report(full, snapshot.get("symbol", "BTCUSDT"), args.nota, prefix)
    print(f"\nBriefing salvato in: {path}")


if __name__ == "__main__":
    main()
