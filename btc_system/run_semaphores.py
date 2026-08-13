"""
run_semaphores.py
-----------------
Mostra in chiaro i semafori operativi (freno, livelli chiave, veto GEX).
Uso:
  python3 run_semaphores.py                    # dati reali Binance
  python3 run_semaphores.py --source synthetic # dati finti (test)
Non chiama l'API Anthropic: solo l'engine.
"""
import sys

def main():
    syn = "--source" in sys.argv and "synthetic" in sys.argv
    if syn:
        from collectors.synthetic import synthetic_snapshot
        print("[!] MODALITA' SINTETICA: numeri finti (GEX assente -> grigio).\n")
        snap = synthetic_snapshot("BTCUSDT")
    else:
        from data_collector import DataCollector
        snap = DataCollector("BTCUSDT").collect()

    s = snap["semaphores"]
    icon = {"VERDE": "🟢", "FRENO": "🟡", "GRIGIO": "⚪"}.get(s["state"], "")
    print(f"SEMAFORO  {icon} {s['state']}   ({snap['symbol']} @ {snap['price']:.0f})")
    print(f"  {s['reason']}\n")
    print(f"  GEX  : {s['gex']['reason']}")
    print(f"  Freno: {s['brake']['reason']}")
    n = s.get("nearest", {})
    if n.get("above"): print(f"  Livello sopra: {n['above']['level']} a +{n['above']['dist_pct']:.2f}%")
    if n.get("below"): print(f"  Livello sotto: {n['below']['level']} a -{n['below']['dist_pct']:.2f}%")

if __name__ == "__main__":
    main()
