"""Debug NFLX — why did agents say BUY when it went down?"""
import sys, os
from pathlib import Path
from dotenv import load_dotenv
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")

print("=== NFLX Deep Dive ===\n")

# Fundamentals
from agents.fundamentals.skills.fundamentals_analysis import analyze_ticker as fund_analyze
r = fund_analyze("NFLX")
print(f"FUNDAMENTALS: score={r['score']} dir={r['direction']}")
for k, v in r.items():
    if k not in ("ticker", "score", "direction"):
        print(f"  {k}={v}")

# Technical
print()
from agents.technical.skills.technical_analysis import analyze_ticker as tech_analyze
r = tech_analyze("NFLX")
print(f"TECHNICAL: score={r['score']} dir={r['direction']}")
for k, v in r.items():
    if k not in ("ticker", "score", "direction"):
        print(f"  {k}={v}")

# News
print()
config = {"finnhub_api_key": os.environ.get("FINNHUB_API_KEY", "")}
from agents.news.skills.news_analysis import analyze_ticker as news_analyze
r = news_analyze("NFLX", config.get("finnhub_api_key", ""))
print(f"NEWS: score={r['score']} dir={r['direction']}")
print(f"  articles={r.get('news_count')}, avg_sentiment={r.get('avg_sentiment')}")
for h in r.get("headlines", []):
    print(f"  {h.get('sentiment','')} {h.get('headline','')}")

# Price history
print()
import yfinance as yf
hist = yf.Ticker("NFLX").history(period="5d")
if not hist.empty:
    print("PRICE HISTORY (last 5 days):")
    for idx, row in hist.iterrows():
        chg = ((row["Close"] - row["Open"]) / row["Open"] * 100)
        print(f"  {idx.strftime('%Y-%m-%d')}: open=${row['Open']:.2f} close=${row['Close']:.2f} change={chg:+.2f}%")

print("\n=== DIAGNOSIS ===")
print("The fundamentals agent scores based on trailing earnings/revenue growth")
print("and analyst targets — these are backward-looking. Today's drop is likely")
print("driven by macro/tariff fears or sector rotation that the technical agent")
print("should have caught via RSI/SMA signals.")
