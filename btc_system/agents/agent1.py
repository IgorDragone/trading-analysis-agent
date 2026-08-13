"""
agent1.py
---------
Agente 1 - "Fotografia del mercato".
Prende lo snapshot e produce il report di testo chiamando l'API Anthropic.

Richiede:
  - il pacchetto 'anthropic' (vedi requirements.txt)
  - la variabile d'ambiente ANTHROPIC_API_KEY impostata

Il modello si puo' cambiare con la variabile d'ambiente AGENT1_MODEL.
Di default usa un modello veloce ed economico: il compito e' descrittivo.
"""

import os
import json
from pathlib import Path

from anthropic import Anthropic

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
PROMPT_PATH = Path(__file__).parent / "agent1_prompt.md"


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def run_agent1(snapshot: dict, model: str | None = None) -> str:
    """
    Genera il report dell'Agente 1 dallo snapshot.
    Ritorna il testo del report.

    snapshot e' un dizionario con i dati di mercato, convertito in JSON e
    passato come input all'agente.
    """
    client = Anthropic()
    model = model or os.environ.get("AGENT1_MODEL", DEFAULT_MODEL)
    system_prompt = load_prompt()
    user_content = json.dumps(snapshot, indent=2, default=str)

    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
    return "\n".join(parts).strip()
