# BTC Multi-Agent System

Sistema multi-agent di analisi BTC. Tre agenti rispondono, in ordine, a tre domande:

```
Agente 1  ->  DOVE siamo      (fotografia: prezzo, VWAP, Volume Profile, volatilita')
Agente 2  ->  CHI muove       (flusso spot/perp, OI/funding, gamma dei MM)
Agente 3  ->  CHE CONDIZIONI  (c'e' una condizione di mean reversion intraday?)
```

Architettura a tre livelli, da tenere sempre separati:

```
Collector (raccolta dati via API)  ->  Engine (calcolo metriche)  ->  Agenti (ragionamento via API Anthropic)
```

Gli agenti leggono lo SNAPSHOT prodotto dal collector, non chiamano mai le API
di mercato direttamente. Questo evita dati disallineati e rate limit sprecati.

## Stato attuale

Il sistema include collector Binance futures, integrazioni best-effort per spot
e Deribit/GEX, tre agenti specializzati e test offline della pipeline.

Avvio rapido:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="..."
python3 run_agent1.py                      # report reale
python3 run_agent1.py --source synthetic --no-agent   # test offline della pipeline
python3 run_agent2.py --source synthetic --no-agent   # vista Agente 2 senza API
python3 run_agent3.py --source synthetic --no-agent   # vista Agente 3 senza API
python3 check_sources.py                   # diagnostica spot + Deribit/GEX
```

I report vengono salvati in `data/reports/`, mentre gli snapshot finiscono come
JSON e record SQLite in `data/`. Le directory runtime sono ignorate da Git.

## Dati storici (per le analisi statistiche)

Per scaricare la storia profonda delle candele futures USDT-Margined dagli
archivi pubblici di Binance (`data.binance.vision`, gratis, senza chiave API):

```bash
python3 download_history.py --symbol BTCUSDT --intervals 1h 15m 1d --start 2020-01
```

Salva un CSV unito, ordinato e con date UTC leggibili, in `data/historical/`.
Lo usa una volta per lo scarico massivo; gli aggiornamenti quotidiani li fa il
collector via API. Gestisce la verifica checksum e la conversione dei timestamp
quando gli archivi Binance usano microsecondi. Modulo:
`collectors/historical_downloader.py`.

## Roadmap

- [x] **Fase 1**: collector Binance completo + Agente 1 funzionante
- [x] **Agente 2 v1** (solo Binance): flusso, OI/funding, taker ratio, Regola d'Oro.
      `run_agent2.py`. Le sezioni spot/gamma/heatmap si popolano da sole in v2.
- [x] **Agente 3 (versione degradata dichiarata)**: verdetto di condizioni da
      snapshot + report 1 e 2. `run_agent3.py` orchestra il briefing completo
      a tre voci. Finche' mancano confluenze e gamma/GEX abbassa la fiducia e
      lo dichiara nel report, come da prompt.
- [x] **Fase 2 / Collector v2 spot**: Binance spot + Coinbase -> CVD spot e
      premio Coinbase nello snapshot, in modalita' best-effort.
- [x] **Fase 3 / Collector v2 Deribit**: catena opzioni -> GEX/gamma calcolato
      in casa con curva, flip, muri, DVOL e punteggio di significativita'.
      Diagnostica: `python3 check_sources.py`.
- [ ] **Fase 4**: modulo confluenze nell'engine -> rafforza l'Agente 3
      (indicatore di REGIME trend/laterale gia' presente: `engine/regime.py`;
      da includere anche un tasso di reazione per zona vs baseline casuale)
- [ ] **Fase 5**: orchestratore + scheduler + invio briefing (es. Telegram)

## Note di design

- **Snapshot coerente**: mai far chiamare le API ai singoli agenti.
- **Un agente = una domanda.** Ogni agente resta nel suo ruolo: l'Agente 1
  descrive e basta, l'Agente 3 e' l'unico che esprime un verdetto di condizioni.
- **Tutto in UTC.** Snapshot, sessioni e scheduler usano UTC, di proposito.
- **CVD**: solo direzione/pendenza/divergenza, mai valore assoluto.
- **OI**: sale solo quando si aprono posizioni, scende quando si chiudono.
- **Semafori** (`engine/semaphores.py`): freno di avvicinamento ai max/min
  settimanali e mensili, sensore livelli chiave, veto GEX (>soglia). Deterministici,
  nello snapshot (`semaphores`). Demo: `run_semaphores.py`. Soglie da tarare.
- **Regime** (`engine/regime.py`): ADX + Efficiency Ratio sul timeframe operativo
  (15m/1h) classificano trend vs laterale. E' un input di contesto SECONDARIO e
  debole per l'Agente 3 (la validazione storica ha mostrato che separa i rientri
  solo marginalmente), non un trigger; gia' loggato nello snapshot (campo
  `regime`). Vedi `run_regime.py`.
- **Sessione** (`engine/session.py`): fascia oraria UTC (Asia/Londra/NY/late) col
  contesto mean-reversion. E' il fattore di contesto PRIMARIO per l'Agente 3 —
  l'analisi statistica ha indicato l'ora del giorno come il segnale piu' robusto
  (Asia/prima Londra favorevoli al rientro, NY sfavorevole), piu' del regime
  detector. Nello snapshot (campo `session`). Demo: `python3 engine/session.py`.
- I file di istruzioni dei singoli agenti (prompt) stanno accanto al codice
  dell'agente, es. `agents/agent1_prompt.md`, e sono modificabili senza toccare
  il codice Python.
