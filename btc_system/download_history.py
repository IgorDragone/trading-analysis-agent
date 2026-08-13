"""
download_history.py
-------------------
Scarica la storia profonda di BTCUSDT (o altro simbolo) dagli archivi pubblici
di Binance, per i timeframe scelti. Niente chiave API.

Uso:
  python3 download_history.py --symbol BTCUSDT --intervals 1h 15m 1d --start 2020-01 --end 2026-05
  python3 download_history.py                 # default: BTCUSDT 1h/15m/1d, 2020-01 -> mese scorso
  python3 download_history.py --no-verify     # salta la verifica checksum (piu' veloce)
"""

import sys
import argparse
from datetime import datetime, timezone

from collectors.historical_downloader import download_klines


def parse_ym(s: str) -> tuple[int, int]:
    y, m = s.split("-")
    return (int(y), int(m))


def main():
    p = argparse.ArgumentParser(description="Scarico storia klines da data.binance.vision")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--intervals", nargs="+", default=["1h", "15m", "1d"])
    p.add_argument("--start", default="2020-01", help="AAAA-MM (incluso)")
    p.add_argument("--end", default=None, help="AAAA-MM (incluso). Default: mese scorso")
    p.add_argument("--no-verify", action="store_true", help="salta verifica checksum")
    args = p.parse_args()

    start = parse_ym(args.start)
    if args.end:
        end = parse_ym(args.end)
    else:
        now = datetime.now(timezone.utc)
        y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        end = (y, m)

    print(f"Simbolo {args.symbol} | intervalli {args.intervals} | {start} -> {end}\n")
    for interval in args.intervals:
        print(f"== {interval} ==")
        download_klines(args.symbol, interval, start, end,
                        verify=not args.no_verify)
        print()


if __name__ == "__main__":
    main()
