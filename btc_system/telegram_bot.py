#!/usr/bin/env python3
"""
telegram_bot.py
---------------
Bot Telegram che permette di chiedere i briefing da telefono, senza terminale.

COME FUNZIONA
Il bot NON espone nessun server: usa il "long polling", cioe' chiede lui a
Telegram "ci sono messaggi nuovi?" ogni pochi secondi. Quindi niente webhook,
niente dominio, niente certificato SSL, niente porte aperte sul firewall.
Gira come processo sempre attivo sul VPS.

COMANDI
  /report [nota]   briefing completo (Agente 1 + 2 + 3). La nota e' opzionale e
                   finisce nello snapshot: "/report pre-Londra dopo il dato USA"
  /flusso [nota]   solo Agente 1 + 2 (piu' rapido e meno costoso: 2 chiamate)
  /stato           quanti snapshot in archivio, ultimo prezzo, ultima raccolta
  /aiuto           elenco comandi

SICUREZZA (importante)
Chiunque conosca il nome del bot puo' scrivergli. Ogni briefing costa chiamate
API a pagamento. Per questo il bot risponde SOLO ai chat id nella whitelist
TELEGRAM_ALLOWED_IDS: a chiunque altro risponde con un rifiuto e logga il
tentativo. Senza whitelist configurata il bot NON parte.

VARIABILI D'AMBIENTE
  TELEGRAM_BOT_TOKEN     token dato da @BotFather
  TELEGRAM_ALLOWED_IDS   chat id autorizzati, separati da virgola (es. "12345,67890")
  ANTHROPIC_API_KEY      chiave per gli agenti

AVVIO
  python3 telegram_bot.py
"""

import html
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    RequestException = requests.RequestException
except ModuleNotFoundError:
    requests = None
    RequestException = Exception

sys.path.insert(0, str(Path(__file__).resolve().parent))

API = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_MAX_CHARS = 4096
POLL_TIMEOUT = 30


def _call(token: str, method: str, **params):
    if requests is None:
        raise RuntimeError("Il pacchetto 'requests' non e' installato")
    r = requests.post(API.format(token=token, method=method),
                      json=params, timeout=POLL_TIMEOUT + 15)
    r.raise_for_status()
    return r.json()


def split_message(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """
    Telegram rifiuta i messaggi oltre ~4096 caratteri. Spezza il testo cercando
    di preservare righe intere; se una riga supera il limite, la taglia.
    """
    if len(text) <= limit:
        return [text]
    parti, buf = [], ""
    for riga in text.split("\n"):
        while len(riga) > limit:
            if buf:
                parti.append(buf)
                buf = ""
            parti.append(riga[:limit])
            riga = riga[limit:]
        if len(buf) + len(riga) + 1 > limit:
            parti.append(buf)
            buf = riga
        else:
            buf = f"{buf}\n{riga}" if buf else riga
    if buf:
        parti.append(buf)
    return parti


def send(token: str, chat_id: int, text: str):
    """Invia un testo, spezzandolo se necessario. Numera le parti se piu' di una."""
    parti = split_message(text)
    for i, p in enumerate(parti, 1):
        intestazione = f"({i}/{len(parti)})\n" if len(parti) > 1 else ""
        try:
            _call(token, "sendMessage", chat_id=chat_id, text=intestazione + p)
        except Exception as e:
            print(f"[!] invio parte {i} fallito: {type(e).__name__}: {e}")
        time.sleep(0.3)


AIUTO = """Comandi disponibili:

/report [nota]  - briefing completo (Agente 1 + 2 + 3)
/flusso [nota]  - solo fotografia e flusso (Agente 1 + 2), piu' rapido
/stato          - stato dell'archivio snapshot
/aiuto          - questo messaggio

La nota e' facoltativa e viene salvata nello snapshot:
  /report pre-Londra, dopo il dato USA

Un briefing richiede circa mezzo minuto: il bot avvisa quando parte."""


def cmd_stato() -> str:
    """Stato dell'archivio: utile per capire se il cron sta raccogliendo."""
    try:
        from storage.snapshot_store import SnapshotStore
        store = SnapshotStore()
        righe = ["Stato del sistema", ""]
        try:
            import sqlite3
            db = getattr(store, "db_path", "data/snapshots.db")
            con = sqlite3.connect(str(db))
            n = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            ultimo = con.execute(
                "SELECT ts_utc, price FROM snapshots ORDER BY ts_utc DESC LIMIT 1"
            ).fetchone()
            con.close()
            righe.append(f"Snapshot in archivio: {n}")
            if ultimo:
                righe.append(f"Ultimo: {ultimo[0]} - prezzo {ultimo[1]}")
        except Exception as e:
            righe.append(f"Archivio non leggibile: {type(e).__name__}")
        righe.append("")
        righe.append(f"Ora UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")
        return "\n".join(righe)
    except Exception as e:
        return f"Errore nel leggere lo stato: {type(e).__name__}: {e}"


def genera_briefing(nota: str | None, completo: bool = True) -> str:
    """
    Esegue la stessa pipeline dei runner da terminale.
    completo=True  -> Agente 1 + 2 + 3
    completo=False -> Agente 1 + 2
    """
    from agents.agent1 import run_agent1
    from agents.agent2 import run_agent2
    from data_collector import DataCollector

    snapshot = DataCollector("BTCUSDT").collect(note=nota)
    blocchi = []
    r1 = run_agent1(snapshot)
    blocchi.append(("AGENTE 1 - Fotografia del mercato", r1))
    r2 = run_agent2(snapshot)
    blocchi.append(("AGENTE 2 - Chi muove il prezzo", r2))
    if completo:
        from agents.agent3 import run_agent3
        r3 = run_agent3(snapshot, r1, r2)
        blocchi.append(("AGENTE 3 - Condizioni mean reversion", r3))

    testa = f"RUN: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    if nota:
        testa += f"  |  Nota: {nota}"
    parti = [testa, "-" * 40]
    for titolo, testo in blocchi:
        parti += [f"\n### {titolo}\n", testo]
    return "\n".join(parti)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERRORE: manca TELEGRAM_BOT_TOKEN")
        return 1

    grezzi = os.environ.get("TELEGRAM_ALLOWED_IDS", "").strip()
    if not grezzi:
        print("ERRORE: manca TELEGRAM_ALLOWED_IDS.\n"
              "Senza whitelist chiunque potrebbe far spendere le tue chiamate API.\n"
              "Scrivi /start al bot e leggi il chat id nei log, poi impostalo.")
        return 1
    autorizzati = {int(x) for x in grezzi.replace(" ", "").split(",") if x}
    print(f"Bot avviato. Chat autorizzate: {sorted(autorizzati)}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[!] ATTENZIONE: ANTHROPIC_API_KEY non impostata: i briefing falliranno.")

    offset = None
    occupato = False

    while True:
        try:
            res = _call(token, "getUpdates", offset=offset, timeout=POLL_TIMEOUT)
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg or "text" not in msg:
                    continue
                chat_id = msg["chat"]["id"]
                testo = msg["text"].strip()

                if chat_id not in autorizzati:
                    utente = msg.get("from", {}).get("username", "?")
                    print(f"[!] accesso negato: chat_id={chat_id} utente=@{utente}")
                    send(token, chat_id,
                         "Questo bot e' privato. Se sei il proprietario, aggiungi "
                         f"questo chat id alla whitelist: {chat_id}")
                    continue

                comando, _, resto = testo.partition(" ")
                comando = comando.split("@")[0].lower()
                nota = resto.strip() or None

                if comando in ("/start", "/aiuto", "/help"):
                    send(token, chat_id, AIUTO)

                elif comando == "/stato":
                    send(token, chat_id, cmd_stato())

                elif comando in ("/report", "/flusso"):
                    if occupato:
                        send(token, chat_id,
                             "Sto gia' preparando un briefing, attendi qualche secondo.")
                        continue
                    completo = (comando == "/report")
                    occupato = True
                    etichetta = "completo" if completo else "flusso"
                    send(token, chat_id,
                         f"Preparo il briefing {etichetta}... (circa 30 secondi)")
                    try:
                        testo_report = genera_briefing(nota, completo=completo)
                        send(token, chat_id, testo_report)
                        print(f"[ok] briefing {etichetta} inviato a {chat_id}"
                              + (f" (nota: {nota})" if nota else ""))
                    except Exception as e:
                        traceback.print_exc()
                        send(token, chat_id,
                             f"Errore nella generazione del briefing:\n"
                             f"{type(e).__name__}: {html.escape(str(e))[:500]}")
                    finally:
                        occupato = False

                else:
                    send(token, chat_id,
                         "Comando non riconosciuto. Scrivi /aiuto per l'elenco.")

        except RequestException as e:
            print(f"[!] rete: {type(e).__name__}: {e}. Riprovo tra 5s.")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nBot fermato.")
            return 0
        except Exception as e:
            traceback.print_exc()
            print(f"[!] errore inatteso: {type(e).__name__}. Riprovo tra 5s.")
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
