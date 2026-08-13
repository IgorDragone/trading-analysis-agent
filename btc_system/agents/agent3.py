"""
agent3.py
---------
Agente 3 - "Condizioni mean reversion intraday".
E' l'unico agente che esprime un verdetto (di CONDIZIONI, mai di ordini
operativi). Non raccoglie dati: incrocia lo snapshot con i report gia'
prodotti dagli Agenti 1 e 2.

Input:
  - snapshot (dict)           -> i livelli precisi (VWAP, bande, VP, naked POC,
                                 regime, session; gamma e confluence_zones
                                 quando il collector li produrra')
  - report_agente1 (str|None) -> "Fotografia del mercato"
  - report_agente2 (str|None) -> "Chi muove il prezzo"

MODALITA' DEGRADATA (by design): se mancano input (confluence_zones, gamma,
uno dei report), l'agente NON si ferma: il suo prompt gli impone di abbassare
la fiducia del verdetto e dichiarare cosa manca. Questo modulo rende la
degradazione ESPLICITA elencando gli input assenti in coda al messaggio utente,
cosi' il modello non deve indovinare.

E' il ragionamento piu' delicato dei tre: usa il modello piu' capace di cui
disponi (variabile d'ambiente AGENT3_MODEL per cambiarlo; per la massima
qualita' valutare un modello di fascia superiore, es. Opus).
"""

import os
import json
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-4-6"
PROMPT_PATH = Path(__file__).parent / "agent3_prompt.md"

# Campi dello snapshot di competenza dell'Agente 3: i LIVELLI e il CONTESTO.
# Il flusso (funding, OI, CVD...) NON si passa come numeri: arriva gia'
# interpretato dal report dell'Agente 2: dargli anche i numeri grezzi lo
# tenterebbe a rifare il lavoro dell'Agente 2 invece di incrociarlo.
RELEVANT_TOP = ("ts_utc", "symbol", "price", "price_24h_change_pct", "note")
RELEVANT_METRICS = ("vwap_session", "volume_profile", "naked_pocs",
                    "volatility", "gamma", "confluence_zones")
RELEVANT_CONTEXT = ("regime", "session")


def _compact_gamma(gamma: dict) -> dict:
    """Passa all'agente i dati gamma interpretativi, non tutta la curva."""
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


def build_agent3_view(snapshot: dict) -> dict:
    """Estrae la porzione di snapshot di competenza dell'Agente 3."""
    view = {k: snapshot[k] for k in RELEVANT_TOP if k in snapshot}
    metrics = snapshot.get("metrics", {})
    m = {k: metrics[k] for k in RELEVANT_METRICS if k in metrics}
    if "gamma" in m:
        m["gamma"] = _compact_gamma(m["gamma"])
    if m:
        view["metrics"] = m
    for k in RELEVANT_CONTEXT:
        if k in snapshot:
            view[k] = snapshot[k]
    return view


def missing_inputs(snapshot: dict, report1: str | None, report2: str | None) -> list[str]:
    """Elenco esplicito degli input assenti (per la modalita' degradata)."""
    metrics = snapshot.get("metrics", {})
    out = []
    if not report1:
        out.append("report Agente 1 (fotografia del mercato)")
    if not report2:
        out.append("report Agente 2 (chi muove il prezzo)")
    if "confluence_zones" not in metrics:
        out.append("zone di confluenza (modulo engine non ancora attivo)")
    if "gamma" not in metrics:
        out.append("campo gamma/GEX (collector Deribit non ancora attivo)")
    return out


def build_user_message(snapshot: dict, report1: str | None, report2: str | None) -> str:
    """Compone il messaggio utente: snapshot + report etichettati + input assenti."""
    parts = [
        "=== SNAPSHOT (livelli e contesto) ===",
        json.dumps(build_agent3_view(snapshot), indent=2, default=str),
        "",
        "=== REPORT AGENTE 1 - Fotografia del mercato ===",
        report1.strip() if report1 else "(non disponibile)",
        "",
        "=== REPORT AGENTE 2 - Chi muove il prezzo ===",
        report2.strip() if report2 else "(non disponibile)",
    ]
    assenti = missing_inputs(snapshot, report1, report2)
    if assenti:
        parts += [
            "",
            "=== INPUT NON DISPONIBILI IN QUESTO RUN ===",
            "\n".join(f"- {a}" for a in assenti),
            "(Come da istruzioni: abbassa la fiducia del verdetto e dichiara cosa manca.)",
        ]
    return "\n".join(parts)


def run_agent3(snapshot: dict, report1: str | None = None,
               report2: str | None = None, model: str | None = None) -> str:
    """Genera il report dell'Agente 3. Ritorna il testo."""
    from anthropic import Anthropic  # import lazy: i test girano senza il pacchetto

    client = Anthropic()
    model = model or os.environ.get("AGENT3_MODEL", DEFAULT_MODEL)

    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=load_prompt(),
        messages=[{"role": "user",
                   "content": build_user_message(snapshot, report1, report2)}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()
