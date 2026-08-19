# Trading Analysis Agent

Multi-agent BTC market analysis system built in Python.

The project collects market data, builds a coherent snapshot, computes trading
context metrics, and passes the result to specialized Anthropic-powered agents.

## What It Does

- Collects BTC futures market data from Binance.
- Optionally enriches snapshots with spot flow and Deribit gamma/GEX data.
- Computes VWAP bands, Volume Profile, naked POCs, CVD, Open Interest context,
  session context, volatility, regime classification, and operational semaphores.
- Generates structured reports through three separate agents:
  - Agent 1: market snapshot.
  - Agent 2: flow and positioning.
  - Agent 3: mean-reversion conditions and context.
- Provides a private Telegram bot interface for requesting reports from a VPS.

## Architecture

```text
Market APIs -> Collector -> Engine metrics -> Snapshot -> Agents -> Reports
```

Agents never call market APIs directly. They only read the snapshot produced by
the collector, which keeps all analysis aligned to the same data capture.

## Project Layout

```text
btc_system/
  collectors/      API clients and historical downloader
  engine/          deterministic metrics and market-context logic
  agents/          Anthropic agent wrappers and prompts
  storage/         JSON and SQLite snapshot persistence
  tests/           offline regression tests
  telegram_bot.py  Telegram long-polling interface
  run_agent*.py    CLI entry points for the three agents
```

## Quick Start

```bash
cd btc_system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For real agent runs:

```bash
export ANTHROPIC_API_KEY="..."
python3 run_agent1.py
```

Offline smoke tests without external APIs:

```bash
python3 tests/test_offline.py
python3 run_agent1.py --source synthetic --no-agent
python3 run_agent2.py --source synthetic --no-agent
python3 run_agent3.py --source synthetic --no-agent
```

Optional Telegram bot:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_ALLOWED_IDS="123456789"
export ANTHROPIC_API_KEY="..."
python3 telegram_bot.py
```

The bot uses long polling and only responds to whitelisted chat IDs.

## Notes

This is an analysis and reporting system, not an automated trading bot. It does
not place orders and should not be treated as financial advice.
