"""
historical_downloader.py
------------------------
Scarica la STORIA PROFONDA delle candele da data.binance.vision (archivi
pubblici, gratuiti, niente chiave API), la verifica, la normalizza e la unisce
in un unico CSV per timeframe, pronto per le analisi statistiche.

Uso tipico: scarico massiccio UNA volta della storia completa di BTCUSDT sui
timeframe operativi. Gli aggiornamenti quotidiani li fa invece il collector via
API (binance_client.py). Due strumenti, due scopi.

Schema URL (mensile, futures USDT-Margined):
  https://data.binance.vision/data/futures/um/monthly/klines/SIMBOLO/INTERVALLO/
      SIMBOLO-INTERVALLO-ANNO-MESE.zip

Dipendenze: solo 'requests' (gia' nel progetto) + libreria standard.
"""

import io
import csv
import time
import zipfile
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import requests

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
# Spot archive base, kept as reference for future extensions.
# BASE = "https://data.binance.vision/data/spot/monthly/klines"

# Colonne delle klines Binance (i file non hanno intestazione)
KLINE_COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
                 "close_time", "quote_volume", "count",
                 "taker_buy_base", "taker_buy_quote", "ignore"]


def month_url(symbol: str, interval: str, year: int, month: int) -> tuple[str, str]:
    fn = f"{symbol}-{interval}-{year}-{month:02d}.zip"
    return f"{BASE}/{symbol}/{interval}/{fn}", fn


def _download(url: str, retries: int = 3, timeout: int = 60) -> bytes | None:
    """Scarica un URL. Ritorna None se 404 (file non disponibile). Retry con backoff."""
    for i in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))
    return None


def _verify_checksum(zip_bytes: bytes, checksum_text: str) -> bool:
    """Il file .CHECKSUM contiene '<sha256>  <nomefile>'. Verifica l'hash."""
    expected = checksum_text.split()[0].strip().lower()
    actual = hashlib.sha256(zip_bytes).hexdigest()
    return expected == actual


def _normalize_ts(v) -> int:
    """
    Normalizza a MILLISECONDI. Alcuni archivi Binance recenti usano microsecondi:
    un valore troppo grande viene riportato a ms.
    """
    v = int(v)
    if v > 1e14:        # microsecondi -> millisecondi
        v = v // 1000
    return v


def _read_zip_csv(zip_bytes: bytes) -> list[list]:
    """Estrae il CSV dallo zip, saltando un'eventuale riga di intestazione."""
    rows = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
            for row in reader:
                if not row:
                    continue
                try:
                    float(row[0])
                except ValueError:
                    continue
                rows.append(row)
    return rows


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    months = []
    y, m = start
    while (y, m) <= end:
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def download_klines(symbol: str, interval: str, start: tuple[int, int],
                    end: tuple[int, int], out_dir: str = "data/historical",
                    verify: bool = True) -> Path:
    """
    Scarica e unisce le klines mensili di 'symbol'/'interval' da start a end
    (inclusi, come (anno, mese)). Salva un CSV unito, ordinato e deduplicato.
    """
    symbol = symbol.upper()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    merged: dict[int, list] = {}

    for (yy, mm) in _months_between(start, end):
        url, fn = month_url(symbol, interval, yy, mm)
        data = _download(url)
        if data is None:
            print(f"  [skip] {fn} non disponibile")
            continue
        if verify:
            cs = _download(url + ".CHECKSUM")
            if cs and not _verify_checksum(data, cs.decode()):
                print(f"  [WARN] checksum non valido per {fn}, salto")
                continue
        for row in _read_zip_csv(data):
            ot = _normalize_ts(row[0])
            ct = _normalize_ts(row[6])
            merged[ot] = [ot, row[1], row[2], row[3], row[4], row[5], ct,
                          row[7], row[8], row[9], row[10],
                          row[11] if len(row) > 11 else ""]
        print(f"  [ok] {fn}")

    out_file = out / f"{symbol}_{interval}.csv"
    with open(out_file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time_ms", "datetime_utc"] + KLINE_COLUMNS[1:])
        for ot in sorted(merged):
            r = merged[ot]
            dt = datetime.fromtimestamp(ot / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([r[0], dt] + r[1:])
    print(f"  -> salvato {out_file}  ({len(merged)} candele)")
    return out_file
