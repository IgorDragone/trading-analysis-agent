"""
agent2.py
---------
Agente 2 - "Chi muove il prezzo".
Prende lo snapshot e produce il report di testo chiamando l'API Anthropic.

A differenza dell'Agente 1 (che DESCRIVE numeri), l'Agente 2 RAGIONA su flusso,
posizionamento e gamma: usa di default un modello piu' capace, non il piu'
economico. Si cambia con la variabile d'ambiente AGENT2_MODEL.

Richiede:
  - il pacchetto 'anthropic' (vedi requirements.txt)
  - la variabile d'ambiente ANTHROPIC_API_KEY impostata

VERSIONE 1 (attuale): funziona con i soli dati Binance gia' nello snapshot
(funding, open interest, taker ratio, CVD perp, Regola d'Oro). Le sezioni che
richiedono dati non ancora raccolti (CVD spot, premio Coinbase, gamma/GEX,
heatmap di liquidazione) vengono omesse dall'agente stesso, che lo segnala:
il prompt e' scritto per degradare con eleganza.

VERSIONE 2 (futura): quando il collector aggiungera' spot + Deribit, i campi
compariranno nello snapshot e le sezioni si popoleranno da sole. Nessuna
modifica necessaria qui.
"""

import os
import json
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-4-6"
PROMPT_PATH = Path(__file__).parent / "agent2_prompt.md"

# Campi dello snapshot che l'Agente 2 deve vedere. Gli altri (volume profile,
# livelli, semafori) sono compito dell'Agente 1 o dell'Agente 3: passarglieli
# lo tenterebbe a sconfinare, e il suo prompt glielo vieta esplicitamente.
RELEVANT_TOP = ("ts_utc", "symbol", "price", "price_24h_change_pct", "note")
RELEVANT_FLOW = ("funding_rate", "open_interest", "oi_change", "bsvr",
                 "cvd", "cvd_spot", "coinbase_premium", "golden_rule",
                 "golden_rule_long", "golden_rule_combined")
RELEVANT_METRICS = ("gamma", "liq_heatmap")


def _compact_gamma(gamma: dict) -> dict:
    """
    Riduce il blocco gamma per il modello: lo snapshot conserva tutta la curva,
    ma l'Agente 2 ha bisogno di aggregate, cliffs, expiry e significativita'.
    """
    profile = gamma.get("profile", {}) if isinstance(gamma, dict) else {}
    return {
        "as_of": gamma.get("as_of"),
        "source": gamma.get("source"),
        "spot_ref": gamma.get("spot_ref"),
        "dealer_convention": gamma.get("dealer_convention"),
        "aggregate": gamma.get("aggregate"),
        "profile": {
            "grid_step_pct": profile.get("grid_step_pct"),
            "range_pct": profile.get("range_pct"),
            "cliffs": profile.get("cliffs"),
        },
        "expiry": gamma.get("expiry"),
        "significance": gamma.get("significance"),
    }


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_agent2_view(snapshot: dict) -> dict:
    """
    Estrae dallo snapshot la sola porzione di competenza dell'Agente 2.
    I campi assenti semplicemente non compaiono: l'agente li segnala come
    "non disponibili in questo snapshot" e prosegue.
    """
    view = {k: snapshot[k] for k in RELEVANT_TOP if k in snapshot}

    flow = snapshot.get("flow", {})
    flow_view = {k: flow[k] for k in RELEVANT_FLOW if k in flow}
    if flow_view:
        view["flow"] = flow_view

    metrics = snapshot.get("metrics", {})
    metrics_view = {k: metrics[k] for k in RELEVANT_METRICS if k in metrics}
    if "gamma" in metrics_view:
        metrics_view["gamma"] = _compact_gamma(metrics_view["gamma"])
    if metrics_view:
        view["metrics"] = metrics_view

    return view


def run_agent2(snapshot: dict, model: str | None = None) -> str:
    """
    Genera il report dell'Agente 2 dallo snapshot.
    Ritorna il testo del report.
    """
    # import lazy: build_agent2_view() e i test devono funzionare anche senza
    # il pacchetto 'anthropic' installato (es. in --no-agent).
    from anthropic import Anthropic

    client = Anthropic()
    model = model or os.environ.get("AGENT2_MODEL", DEFAULT_MODEL)
    system_prompt = load_prompt()
    user_content = json.dumps(build_agent2_view(snapshot), indent=2, default=str)

    resp = client.messages.create(
        model=model,
        max_tokens=2500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
    return "\n".join(parts).strip()
