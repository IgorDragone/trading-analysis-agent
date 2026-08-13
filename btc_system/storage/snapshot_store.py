"""
snapshot_store.py
-----------------
Persistenza degli snapshot. Ogni run del collector produce uno snapshot
timestamped che viene salvato in due forme:
  1. file JSON datato (leggibile, comodo per debug)
  2. record in SQLite (per query storiche e backtest futuro)

Lo storico accumulato e' un asset: permettera' di fare backtest e di
ricostruire l'evoluzione di GEX/prezzo/CVD nel tempo, gratis.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SnapshotStore:
    def __init__(self, data_dir: str = "data", db_name: str = "snapshots.db"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / db_name
        self._init_db()

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc    TEXT NOT NULL,
                symbol    TEXT NOT NULL,
                price     REAL,
                payload   TEXT NOT NULL
            )
        """)
        con.commit()
        con.close()

    def save(self, snapshot: dict) -> str:
        """Salva snapshot in JSON datato + SQLite. Ritorna il path del JSON."""
        ts = snapshot.get("ts_utc") or datetime.now(timezone.utc).isoformat()
        symbol = snapshot.get("symbol", "BTCUSDT")
        price = snapshot.get("price")

        # 1. JSON file
        fname = f"snapshot_{ts.replace(':', '-')}_{symbol}.json"
        fpath = self.data_dir / fname
        with open(fpath, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)

        # 2. SQLite
        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT INTO snapshots (ts_utc, symbol, price, payload) VALUES (?,?,?,?)",
            (ts, symbol, price, json.dumps(snapshot, default=str)),
        )
        con.commit()
        con.close()
        return str(fpath)

    def latest(self, symbol: str = "BTCUSDT") -> dict | None:
        """Recupera l'ultimo snapshot salvato (per gli agenti)."""
        con = sqlite3.connect(self.db_path)
        row = con.execute(
            "SELECT payload FROM snapshots WHERE symbol=? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        con.close()
        return json.loads(row[0]) if row else None

    def history(self, symbol: str = "BTCUSDT", limit: int = 100) -> list[dict]:
        """Ultimi N snapshot (per backtest / analisi temporale)."""
        con = sqlite3.connect(self.db_path)
        rows = con.execute(
            "SELECT payload FROM snapshots WHERE symbol=? ORDER BY id DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        con.close()
        return [json.loads(r[0]) for r in rows]
