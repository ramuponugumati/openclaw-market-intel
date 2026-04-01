"""Full E2E test — 10 tickers, all 7 agents + options + Claude thesis + SMS + HTML email."""
import json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

import shared_memory_io
from agents.orchestrator.skills.score_combiner import combine
from agents.orchestrator.skills.pick_selector import select_options, select_stocks, enrich_options_picks, enrich_stock_picks
from notifier import send_morning_alert

TEST_TICKERS = ["NVDA", "AAPL", "MSFT", "AMD", "GOOGL", "META", "TSLA", "AMZN", "NFLX", "LLY"]
config = {"finnhub_api_key": os.environ.get("FINNHUB_API_KEY", ""), "fred_api_key": os.environ.get("FRED_API_KEY", "")}

print(f"\n{'='*50}")
print(f"🦀 Full E2E — 10 tickers, all agents + Claude")
print(f"{'='*50}\n")

agent_results = {}

print("1/7 Fundamentals...")
from agents.fundamentals.skills.fundamentals_analysis import run as run_fund
agent_results["fundamentals"] = {"results": run_fund(TEST_TICKERS)}

print("2/7 Sentiment (rate limited)...")
from agents.sentiment.skills.sentiment_analysis import run as run_sent
agent_results["sentiment"] = {"results": run_sent(TEST_TICKERS, config)}

print("3/7 Macro...")
from agents.macro.skills.macro_analysis import run as run_macro
agent_results["macro"] = {"results": run_macro(TEST_TICKERS, config)}

print("4/7 News (rate limited)...")
from agents.news.skills.news_analysis import run as run_news
agent_results["news"] = {"results": run_news(TEST_TICKERS, config)}

print("5/7 Technical...")
from agents.technical.skills.technical_analysis import run as run_tech
agent_results["technical"] = {"results": run_tech(TEST_TICKERS)}

print("6/7 Pre-Market...")
from agents.premarket.skills.premarket_analysis import run as run_pre
results = run_pre(TEST_TICKERS)
agent_results["premarket"] = {"results": [r for r in results if "ticker" in r]}

print("7/7 Congress...")
from agents.congress.skills.congress_analysis import run as run_cong
agent_results["congress"] = {"results": run_cong(TEST_TICKERS, config)}

print("\n📊 Combining scores...")
combined = combine(agent_results)

print("🎯 Selecting picks...")
options_picks = select_options(combined)
stock_picks = select_stocks(combined)

print(f"   Options: {len(options_picks)} picks")
print(f"   Stocks: {len(stock_picks)} picks")

# Enrich options with contracts + thesis
print("🔗 Enriching options with contracts + Claude thesis...")
options_picks = enrich_options_picks(options_picks)

# Enrich stocks with Claude thesis
print("📝 Generating Claude theses for stock picks...")
stock_picks = enrich_stock_picks(stock_picks)

# Show theses
for p in stock_picks[:3]:
    thesis = p.get("thesis", "")
    print(f"   {p['ticker']:6s} score={p['composite_score']:.1f} {p.get('action','?')} — {thesis[:80]}")

# Send real SMS + HTML email
print("\n📱 Sending SMS + HTML email via SES...")
send_morning_alert(options_picks, stock_picks)

print(f"\n{'='*50}")
print("✅ Full E2E complete — check phone + email")
print(f"{'='*50}\n")
