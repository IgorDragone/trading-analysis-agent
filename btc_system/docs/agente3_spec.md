# Agente 3 — "Condizioni mean reversion intraday"

## A cosa serve questo file

È il **testo di istruzioni** (system prompt) per l'IA che produce il report
dell'Agente 3. A differenza dei primi due, l'Agente 3 **non raccoglie e non
calcola nulla di nuovo**: legge la fotografia (Agente 1) e il "chi muove"
(Agente 2) e dice se insieme formano una **condizione di mean reversion
intraday** verso l'equilibrio (VWAP/POC).

È l'unico dei tre agenti che esprime un verdetto operativo, ma resta sempre un
verdetto di **condizioni e livelli di riferimento**, non un ordine. La
decisione e l'esecuzione restano al trader.

## Cosa legge (nota per lo sviluppatore)

L'Agente 3 riceve tre input insieme:

1. lo **snapshot** JSON (per i livelli precisi: VWAP, bande, POC/area di valore,
   Flip Point e Gamma Cliff se presenti, naked POC);
2. le **zone di confluenza** già calcolate dall'engine e messe nello snapshot
   (vedi sotto): l'agente NON le calcola, le legge e le interpreta;
   inoltre il campo **regime** (snapshot["regime"]) con il filtro trend/laterale
   già calcolato dall'engine (ADX + Efficiency Ratio sul timeframe operativo);
3. i **due report già prodotti** dagli Agenti 1 e 2 (testo), per le
   interpretazioni già fatte (distanza in sigma, natura del flusso, regime gamma).

Costruzione: l'Agente 3 può partire anche con il solo Agente 1 + una versione
ridotta dell'Agente 2 (senza gamma) e senza zone di confluenza. In quel caso
DEVE abbassare la fiducia del verdetto e segnalare cosa manca. Più input
affidabili ha, più il verdetto è solido.

### Le zone di confluenza si CALCOLANO nell'engine, non qui

Importante: individuare i prezzi dove più livelli si sovrappongono è un
**calcolo geometrico**, non un ragionamento. Lo fa un modulo dell'engine (in
codice), che raggruppa tutti i livelli vicini tra loro (es. entro 0,3-0,5%) in
"zone" e assegna a ciascuna una forza. L'IA NON deve confrontare numeri a mano
per indovinare quali sono vicini: riceve le zone già pronte nello snapshot, es.:

  metrics.confluence_zones = [
    { "price": 67450, "strength": "forte", "n_levels": 4,
      "levels": ["VWAP -2σ", "VAL giornaliero", "SMA50 daily", "Gamma Cliff supporto"],
      "side": "sotto", "dist_pct": -0.5, "low_quality_flag": false },
    ...
  ]

Il compito dell'IA è interpretarle (quale conta per il rientro, come si lega al
flusso), non costruirle.

NOTA — la heatmap di liquidazione NON entra nelle confluence_zones. Le zone di
confluenza sono un calcolo geometrico su livelli NUMERICI precisi (VWAP, POC,
SMA, Gamma Cliff) raggruppati entro 0,3-0,5%. La heatmap, quando presente,
arriva come lettura QUALITATIVA estratta da screenshot (una fascia, non un
prezzo esatto): non si fonde con gli altri livelli nel calcolo, altrimenti
genera confluenze finte. L'Agente 3 la legge come overlay di contesto dal
report dell'Agente 2 (dove sta il magnete di liquidità più vicino), utile per
bersaglio/invalidazione, MAI come livello da inserire nelle confluenze.

### Come si usa

Chiamata all'API: `system` = il blocco qui sotto; `user` = snapshot JSON
(incluse le `confluence_zones`) + report Agente 1 + report Agente 2
(concatenati, etichettati chiaramente).

Modello consigliato: l'Agente 3 sintetizza e dà il verdetto, è il ragionamento
più delicato dei tre. Usa il modello più capace di cui disponi, non quello
economico adatto all'Agente 1.

---

## Istruzioni per l'agente

Il testo del system prompt vive in `agents/agent3_prompt.md`, che
contiene SOLO il prompt (nessuna nota per lo sviluppatore: quel file
viene caricato integralmente e inviato al modello).
Le modifiche al comportamento dell'agente si fanno LI', non qui.


---

## Promemoria di metodo (i tuoi vincoli, già dentro il prompt)

- Mean reversion = distanza dall'equilibrio **E** assenza di trend genuino.
  Mai la distanza da sola.
- GEX positivo = MM frenano e rischio di CODA ridotto (contesto più sicuro), NON
  garanzia che il rientro riesca; GEX negativo = MM amplificano in entrambe le
  direzioni (fattore di rischio serio). Il GEX non prevede la direzione né la
  riuscita del rientro: modula la sicurezza del contesto e la dimensione della
  coda. (Verifica aperta: confronto GEX vs DVOL quando ci sarà storico live.)
- Livello di invalidazione SEMPRE presente: è ciò che protegge dal caso
  peggiore (credere nel rientro mentre il mercato è passato in GEX negativo e
  accelera).
- L'Agente 3 dà condizioni e livelli, non esegue: la decisione resta al trader.
- Il regime (trend/laterale, engine/regime.py, ADX+ER sul timeframe operativo) è
  un input di contesto DEBOLE, non il filtro di fondo: la validazione storica
  mostra che separa i rientri solo marginalmente. Il contesto più forte è la
  FASCIA ORARIA (Asia/prima Londra = mean-reverting; New York = direzionale):
  pesala più del regime detector. Entrambi modulano il verdetto, non lo innescano.
- Le zone di confluenza sono CALCOLO (engine), non ragionamento (agente). Si
  pesano per qualità dei livelli, non solo per numero: un cluster gonfiato da
  anchor di volume profile a volume quasi-zero dà falsa fiducia. Questa pulizia
  va fatta nel modulo engine che costruisce le zone.

## Come si compone il briefing finale

I tre report, concatenati, formano il briefing mattutino completo:

  Agente 1  →  DOVE siamo        (fotografia: prezzo, VWAP, livelli, volatilità)
  Agente 2  →  CHI muove         (flusso spot/perp, OI/funding, gamma dei MM)
  Agente 3  →  CHE CONDIZIONI    (sintesi: c'è una condizione di mean reversion?)

L'Orchestratore li chiama in ordine, passa lo snapshot a tutti e i report di
1 e 2 all'Agente 3, e invia il risultato unito (es. su Telegram) alle 05:05 UTC.
