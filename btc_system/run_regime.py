"""
run_regime.py
-------------
Mostra in chiaro il REGIME di mercato (trend / laterale) sul timeframe operativo,
cosi' puoi vedere subito l'indicatore al lavoro.

Uso:
  python3 run_regime.py                    # dati reali Binance
  python3 run_regime.py --source synthetic # dati finti (test)

Non chiama l'API Anthropic: e' solo l'indicatore dell'engine.
"""

import sys


def main():
    source = "synthetic" if "--source" in sys.argv and "synthetic" in sys.argv else "binance"
    if source == "synthetic":
        from collectors.synthetic import synthetic_snapshot
        print("[!] MODALITA' SINTETICA: numeri finti.\n")
        snap = synthetic_snapshot("BTCUSDT")
    else:
        from data_collector import DataCollector
        snap = DataCollector("BTCUSDT").collect()

    reg = snap["regime"]
    print(f"REGIME DI MERCATO  ({snap['symbol']}  prezzo {snap['price']:.0f})")
    print("=" * 60)
    for tf in ("1h", "15m"):
        r = reg[tf]
        star = "  <- primario" if reg["primary"] == tf else ""
        print(f"[{tf}]{star}")
        print(f"   stato: {r['state'].upper()}   "
              f"(ADX {r['adx']}, Efficiency Ratio {r['efficiency_ratio']})")
        print(f"   mean reversion: {r['mean_reversion_context'].upper()}")
        print(f"   {r['rationale']}")
        print()


if __name__ == "__main__":
    main()
