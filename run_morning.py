"""
Full Morning Analysis — runs all 7 agents on the complete 35-ticker watchlist,
combines scores, selects Top 5 options + Top 10 stocks, and prints the
formatted Telegram message.

No broker needed — use picks as signals for manual trading on Robinhood.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Setup
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("morning_analysis")

import shared_memory_io
from agents.orchestrator.skills.score_combiner import combine
from agents.orchestrator.skills.pick_selector import select_options, select_stocks
from agents.orchestrator.skills.message_formatter import format_morning_analysis
from tracker import log_morning_picks
from horizon_manager import get_current_mode

# Load watchlist
watchlist_data = shared_memory_io.load_watchlist()
TICKERS = watchlist_data.get("all_tickers", [])
config = {
    "finnhub_api_key": os.environ.get("FINNHUB_API_KEY", ""),
    "fred_api_key": os.environ.get("FRED_API_KEY", ""),
}

run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
print(f"\n{'='*60}")
print(f"🦀 OpenClaw Morning Analysis — {len(TICKERS)} tickers")
print(f"Run ID: {run_id}")
print(f"{'='*60}\n")

# Run each agent sequentially (no asyncio needed for local testing)
agent_results = {}

# 1. Fundamentals
print("🔍 Running Fundamentals agent...")
from agents.fundamentals.skills.fundamentals_analysis import run as run_fund, write_to_shared_memory as write_fund
results = run_fund(TICKERS)
write_fund(run_id, results)
agent_results["fundamentals"] = {"results": results}
print(f"   ✅ {len(results)} tickers scored")

# 2. Sentiment
print("🔍 Running Sentiment agent...")
from agents.sentiment.skills.sentiment_analysis import run as run_sent, write_to_shared_memory as write_sent
results = run_sent(TICKERS, config)
write_sent(run_id, results)
agent_results["sentiment"] = {"results": results}
print(f"   ✅ {len(results)} tickers scored")

# 3. Macro
print("🔍 Running Macro/Fed agent...")
from agents.macro.skills.macro_analysis import run as run_macro, write_to_shared_memory as write_macro
results = run_macro(TICKERS, config)
write_macro(run_id, results)
agent_results["macro"] = {"results": results}
print(f"   ✅ {len(results)} tickers scored")

# 4. News
print("🔍 Running News agent...")
from agents.news.skills.news_analysis import run as run_news, write_to_shared_memory as write_news
results = run_news(TICKERS, config)
write_news(run_id, results)
agent_results["news"] = {"results": results}
print(f"   ✅ {len(results)} tickers scored")

# 5. Technical
print("🔍 Running Technical agent...")
from agents.technical.skills.technical_analysis import run as run_tech, write_to_shared_memory as write_tech
results = run_tech(TICKERS)
write_tech(run_id, results)
agent_results["technical"] = {"results": results}
print(f"   ✅ {len(results)} tickers scored")

# 6. Pre-Market
print("🔍 Running Pre-Market agent...")
from agents.premarket.skills.premarket_analysis import run as run_pre, write_to_shared_memory as write_pre
results = run_pre(TICKERS)
write_pre(run_id, results)
agent_results["premarket"] = {"results": [r for r in results if "ticker" in r]}
print(f"   ✅ Done")

# 7. Congress
print("🔍 Running Congressional Trades agent...")
from agents.congress.skills.congress_analysis import run as run_cong, write_to_shared_memory as write_cong
results = run_cong(TICKERS, config)
write_cong(run_id, results)
agent_results["congress"] = {"results": results}
print(f"   ✅ {len(results)} tickers scored")

# Combine scores
print("\n📊 Combining weighted scores...")
combined = combine(agent_results)
print(f"   ✅ {len(combined)} tickers combined")

# Select picks
options_picks = select_options(combined)
stock_picks = select_stocks(combined)

# Log picks
horizon = get_current_mode()
log_morning_picks(options_picks, stock_picks, run_id=run_id, horizon=horizon)

# Format the Telegram message
message_data = {
    "options_picks": options_picks,
    "stock_picks": stock_picks,
    "premarket_data": [],
    "run_id": run_id,
    "combined": combined,
    "timed_out": [],
}
message = format_morning_analysis(message_data)

print(f"\n{'='*60}")
print("📱 MORNING ANALYSIS MESSAGE")
print(f"{'='*60}\n")
print(message)
print(f"\n{'='*60}")
print(f"✅ Analysis complete — {len(options_picks)} options + {len(stock_picks)} stock picks")
print(f"   Mode: {horizon} | Run: {run_id}")
print(f"{'='*60}\n")
