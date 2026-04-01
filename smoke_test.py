"""Quick smoke test — runs 6 agents on 3 tickers with real APIs."""
import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Setup
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

TEST_TICKERS = ["NVDA", "AAPL", "MSFT"]
config = {
    "finnhub_api_key": os.environ.get("FINNHUB_API_KEY", ""),
    "fred_api_key": os.environ.get("FRED_API_KEY", ""),
}

print(f"\n{'='*60}")
print(f"OpenClaw Market Intel — Smoke Test (3 tickers)")
print(f"{'='*60}\n")

# 1. Fundamentals (yfinance — no key needed)
print("🔍 Agent 1: Fundamentals...")
from agents.fundamentals.skills.fundamentals_analysis import run as run_fundamentals
results = run_fundamentals(TEST_TICKERS)
for r in results:
    print(f"  {r['ticker']}: score={r['score']} dir={r['direction']} pe={r.get('pe','N/A')}")

# 2. Sentiment (Finnhub)
print("\n🔍 Agent 2: Sentiment...")
from agents.sentiment.skills.sentiment_analysis import run as run_sentiment
results = run_sentiment(TEST_TICKERS, config)
for r in results:
    print(f"  {r['ticker']}: score={r['score']} dir={r['direction']} pos={r.get('social_positive_pct','N/A')} mentions={r.get('social_mentions',0)}")

# 3. Macro (FRED)
print("\n🔍 Agent 3: Macro/Fed...")
from agents.macro.skills.macro_analysis import run as run_macro
results = run_macro(TEST_TICKERS, config)
for r in results:
    reasons = r.get('macro_reasons', [])
    print(f"  {r['ticker']}: score={r['score']} dir={r['direction']} reasons={reasons}")

# 4. News (Finnhub)
print("\n🔍 Agent 4: News...")
from agents.news.skills.news_analysis import run as run_news
results = run_news(TEST_TICKERS, config)
for r in results:
    print(f"  {r['ticker']}: score={r['score']} dir={r['direction']} articles={r.get('news_count',0)}")

# 5. Technical (yfinance)
print("\n🔍 Agent 5: Technical...")
from agents.technical.skills.technical_analysis import run as run_technical
results = run_technical(TEST_TICKERS)
for r in results:
    print(f"  {r['ticker']}: score={r['score']} dir={r['direction']} rsi={r.get('rsi','N/A')} sma20={r.get('sma_20','N/A')}")

# 6. Pre-Market (yfinance)
print("\n🔍 Agent 6: Pre-Market...")
from agents.premarket.skills.premarket_analysis import run as run_premarket
results = run_premarket(TEST_TICKERS)
scored = [r for r in results if "ticker" in r]
for r in scored:
    print(f"  {r['ticker']}: score={r['score']} dir={r['direction']} reasons={r.get('premarket_reasons',[])}")

print(f"\n{'='*60}")
print("✅ Smoke test complete — 6 agents ran successfully")
print(f"{'='*60}\n")
