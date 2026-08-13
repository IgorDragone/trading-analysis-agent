# Agente 2 — "Chi muove il prezzo"

## A cosa serve questo file

È il **testo di istruzioni** (system prompt) da dare all'IA che trasforma lo
*snapshot* JSON nel report dell'Agente 2. L'Agente 2 risponde a una sola
domanda: **chi sta muovendo il prezzo oggi e quanto è solido il movimento.**

Lo fa guardando il flusso (CVD spot vs perp, premio Coinbase), il
posizionamento a leva (open interest, funding, aggressività dei taker) e
l'esposizione gamma dei market maker (GEX), che dice **con che intensità i MM
difenderanno determinati livelli**.

L'Agente 2 **NON** descrive i livelli di prezzo (è l'Agente 1) e **NON** dice
se operare (è l'Agente 3). Identifica chi spinge e quanta resistenza trova.

## Costruzione in due tempi (importante)

- **Versione 1 (subito, solo Binance):** CVD perp, open interest, funding,
  taker ratio, Regola d'Oro. È già quasi tutta nel collector attuale.
- **Versione 2 (quando si agganciano spot + Deribit):** si aggiungono CVD
  spot, premio Coinbase e la **sezione gamma (GEX)**.

Il prompt è scritto per funzionare in entrambe le versioni: se una sezione di
dati non è ancora nello snapshot, l'agente la salta e lo segnala. Non serve
aspettare il GEX per avere un Agente 2 utile.

### Come si usa (nota per lo sviluppatore)

1. Il collector produce lo `snapshot`.
2. Chiamata all'API: `system` = il blocco qui sotto; `user` = snapshot in JSON.
3. La risposta è già il report.

Modello consigliato: a differenza dell'Agente 1 (che descrive numeri),
l'Agente 2 RAGIONA su flusso, posizionamento e gamma. Conviene un modello più
capace, non il più economico.

Il GEX si **calcola** in un modulo collector dedicato (opzioni Deribit, con la
sua cadenza lenta ~6h) e il risultato viene messo nello snapshot. Un conto è
dove il dato si raccoglie, un altro è in quale report si legge: il gamma si
raccoglie a parte, ma si **legge qui**, perché è parte di "chi muove".

---

## Istruzioni per l'agente

Il testo del system prompt vive in `agents/agent2_prompt.md`, che
contiene SOLO il prompt (nessuna nota per lo sviluppatore: quel file
viene caricato integralmente e inviato al modello).
Le modifiche al comportamento dell'agente si fanno LI', non qui.


---

## Campi dello snapshot che l'Agente 2 legge

Presenti nello snapshot:

- `flow.funding_rate` — funding.
- `flow.open_interest` — open interest corrente.
- `flow.bsvr` — taker buy/sell ratio.
- `flow.cvd` — CVD perp (l'agente ne usa la PENDENZA, non il valore assoluto).
- `flow.golden_rule` — Regola d'Oro sulla finestra breve (~1h).
- `flow.golden_rule_long` — Regola d'Oro sulla finestra lunga (~4h), se
  calcolabile.
- `flow.golden_rule_combined` — concordanza/divergenza/non valutabile tra le
  due finestre.

Presenti solo se le fonti pubbliche rispondono:

- `flow.cvd_spot` — pendenza del CVD da Binance spot.
- `flow.coinbase_premium` — Coinbase spot vs Binance spot, in %.
- `metrics.gamma` — blocco gamma Deribit con aggregate, profilo, flip point,
  muri principali, scadenza e `significance`.
- **Heatmap di liquidazione (best-effort, QUALITATIVA)** — non è un dato
  numerico: è una lettura testuale estratta via vision da uno screenshot
  Coinglass. Nello snapshot sta come stringa descrittiva dei cluster, es.
  `metrics.liq_heatmap = "cluster denso 65,0-65,3k sotto; secondario 64,8k; rado sopra fino a 67k"`.
  Modulo dedicato best-effort: se lo screenshot fallisce (o la sessione è
  scaduta) il campo è assente e l'agente lo segnala, senza bloccare il report.

## Promemoria di metodo (i tuoi vincoli, già dentro il prompt)

- CVD: solo direzione / pendenza / divergenza. Mai valore assoluto, mai
  confronto tra finestre o timeframe.
- OI: sale solo quando si aprono posizioni, scende quando si chiudono
  (liquidazione o chiusura volontaria).
- GEX positivo = MM frenano; GEX negativo = MM amplificano in entrambe le
  direzioni. Il GEX descrive intensità e livelli, non prevede la direzione;
  la Change Table è storica e non direzionale.
- Il gamma MODULA gli altri segnali (contesto frenante/amplificante), non si
  somma come punteggio.
- Dato numerico vs qualitativo: quasi tutti i campi sono numeri calcolati
  dall'engine. La heatmap di liquidazione, se presente, è invece una STRINGA
  estratta da screenshot via vision: va letta come zona qualitativa, mai usata
  per calcoli o confronti numerici precisi. È contesto, non si punteggia.
