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

## Entry Points

Operational workflows are exposed through executable scripts in `btc_system/`:

- `run_agent1.py`: generates the market snapshot report.
- `run_agent2.py`: generates the flow and positioning report.
- `run_agent3.py`: runs the full three-agent briefing.
- `telegram_bot.py`: starts the private Telegram long-polling bot.
- `collect_snapshot.py`: collects and stores a snapshot without generating reports.
- `download_history.py`: downloads historical Binance futures candles.
- `check_sources.py`: checks optional spot and Deribit/GEX data sources.
- `run_regime.py`: runs a quick regime detector check.
- `run_semaphores.py`: runs a quick operational semaphores check.

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

## Deployment

The Telegram interface is designed to run as a long-lived process on a VPS. It
uses long polling, so it does not require public webhooks, open inbound ports, a
domain, or SSL certificates. Runtime secrets and access control are configured
through environment variables, and access is restricted to whitelisted Telegram
chat IDs.

## Notes

This is an analysis and reporting system, not an automated trading bot. It does
not place orders and should not be treated as financial advice.
