# OpenClaw Market Intel

Multi-agent market intelligence and trading system built on the OpenClaw framework.

## Overview

8 specialized sub-agents + orchestrator analyze market data across fundamentals, sentiment, macro, news, technical indicators, options chains, pre-market conditions, and congressional trades. The orchestrator combines weighted scores to produce daily Top 5 options plays and Top 10 stock trades, delivered via Telegram.

## Architecture

- **Agents**: 8 sub-agents + 1 orchestrator, each with dedicated workspace, memory, and skills
- **Communication**: Shared memory (markdown files on EFS) using staggered heartbeat pattern
- **Interface**: Telegram bot for receiving picks, confirming trades, and ad-hoc commands
- **Broker**: Alpaca (paper trading first, then live)
- **Scheduling**: EventBridge + Lambda (5:30 AM PST morning picks, 1:15 PM PST EOD recap)
- **Compute**: Fargate (always-on Telegram bot) + Lambda (scheduled analysis)
- **Learning**: Self-adjusting agent weights based on historical accuracy

## Setup

1. Copy `.env.example` to `.env` and fill in API keys
2. Install dependencies: `pip install -r requirements.txt`
3. Run locally: `python -m agents.orchestrator.skills.fleet_launcher`

## Project Structure

```
openclaw-market-intel/
├── openclaw.yaml          # Fleet config
├── agents/                # 9 OpenClaw agents
├── shared_memory/         # EFS-mounted shared state
├── telegram_bot/          # Telegram bot listener
├── broker/                # Alpaca integration
├── lambda_handlers/       # AWS Lambda entry points
└── infra/                 # CloudFormation template
```

## Agents

| Agent | Data Source | Function |
|-------|-----------|----------|
| Fundamentals | yfinance | PE, earnings growth, analyst targets |
| Sentiment | Finnhub | Social sentiment, analyst upgrades/downgrades |
| Macro | FRED | Treasury yields, CPI, VIX, Fed funds |
| News | Finnhub | Breaking news, earnings surprises |
| Technical | yfinance | RSI, SMA, volume analysis |
| Options Chain | yfinance | Strike selection, contract ranking |
| Pre-Market | yfinance | Futures, global markets, overnight gaps |
| Congress | Quiver/Capitol | Congressional trade disclosures |
| Orchestrator | All agents | Score combination, pick selection, Telegram delivery |
