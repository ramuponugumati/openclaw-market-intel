"""
Web News + Reddit Scraper

Sources (priority order):
1. Reddit (r/wallstreetbets, r/investing, r/stocks) — HIGHEST weight, retail sentiment driver
2. CNBC/MarketWatch RSS — mainstream financial news
3. Reuters — global macro context

Reddit posts with high upvotes on WSB have historically moved stocks (GME, AMC, etc).
Reddit sentiment gets 2x weight multiplier vs news RSS.
"""

from __future__ import annotations
import json
import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIMEOUT = 10
USER_AGENT = "OpenClaw/1.0 (market-intel bot)"

# Reddit subs — public JSON API, no auth needed
REDDIT_SUBS = {
    "wallstreetbets": "https://www.reddit.com/r/wallstreetbets/hot.json?limit=30",
    "investing": "https://www.reddit.com/r/investing/hot.json?limit=25",
    "stocks": "https://www.reddit.com/r/stocks/hot.json?limit=25",
}

# RSS feeds
RSS_FEEDS = {
    "cnbc_top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "cnbc_market": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
}

POSITIVE_WORDS = {
    "surge", "surges", "rally", "rallies", "soar", "soars", "jump", "jumps",
    "beat", "beats", "record", "boom", "bullish", "upgrade", "upgraded",
    "outperform", "strong", "growth", "profit", "gain", "gains", "rise",
    "rises", "breakout", "momentum", "optimistic", "expansion", "buyback",
    "moon", "mooning", "rocket", "tendies", "diamond hands", "calls",
    "yolo", "squeeze", "short squeeze", "gamma squeeze", "to the moon",
}

NEGATIVE_WORDS = {
    "crash", "crashes", "plunge", "plunges", "drop", "drops", "fall", "falls",
    "miss", "misses", "layoff", "layoffs", "cut", "cuts", "downgrade",
    "bearish", "recession", "tariff", "tariffs", "war", "sanctions",
    "investigation", "fraud", "bankruptcy", "default", "slump", "decline",
    "warning", "weak", "loss", "losses", "sell-off", "selloff", "tumble",
    "puts", "bag holding", "bagholding", "rug pull", "rugpull", "dump",
}

TICKER_PATTERNS = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "meta": "META", "facebook": "META", "tesla": "TSLA",
    "nvidia": "NVDA", "netflix": "NFLX", "amd": "AMD", "intel": "INTC",
    "boeing": "BA", "disney": "DIS", "walmart": "WMT", "costco": "COST",
    "jpmorgan": "JPM", "goldman": "GS", "berkshire": "BRK-B",
    "exxon": "XOM", "chevron": "CVX", "pfizer": "PFE", "moderna": "MRNA",
    "eli lilly": "LLY", "unitedhealth": "UNH", "salesforce": "CRM",
    "broadcom": "AVGO", "qualcomm": "QCOM", "micron": "MU",
    "palantir": "PLTR", "coinbase": "COIN", "robinhood": "HOOD",
    "starbucks": "SBUX", "nike": "NKE", "home depot": "HD",
    "gamestop": "GME", "amc": "AMC", "sofi": "SOFI", "rivian": "RIVN",
    "lucid": "LCID", "shopify": "SHOP", "snowflake": "SNOW",
    "crowdstrike": "CRWD", "palo alto": "PANW", "servicenow": "NOW",
}


# ---------------------------------------------------------------------------
# Reddit scraper — highest priority source
# ---------------------------------------------------------------------------

def _fetch_reddit(sub_name: str, url: str) -> list[dict]:
    """Fetch hot posts from a Reddit subreddit via public JSON API."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        if not resp.ok:
            logger.debug("Reddit %s returned %d", sub_name, resp.status_code)
            return []
        data = resp.json()
        posts = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            if post.get("stickied"):
                continue  # skip pinned mod posts
            title = post.get("title", "")
            selftext = post.get("selftext", "")[:300]
            upvotes = post.get("ups", 0)
            num_comments = post.get("num_comments", 0)
            flair = post.get("link_flair_text", "") or ""

            posts.append({
                "title": title,
                "summary": selftext,
                "source": f"reddit/{sub_name}",
                "upvotes": upvotes,
                "comments": num_comments,
                "flair": flair,
                "is_reddit": True,
            })
        logger.info("Reddit r/%s: %d posts fetched", sub_name, len(posts))
        return posts
    except Exception as exc:
        logger.warning("Reddit r/%s fetch failed: %s", sub_name, exc)
        return []


def _fetch_rss(url: str) -> list[dict]:
    """Fetch and parse an RSS feed."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        if not resp.ok:
            return []
        soup = BeautifulSoup(resp.content, "xml")
        articles = []
        for item in soup.find_all("item")[:15]:
            title = item.find("title")
            desc = item.find("description")
            articles.append({
                "title": title.get_text(strip=True) if title else "",
                "summary": desc.get_text(strip=True)[:200] if desc else "",
                "source": url.split("/")[2] if "/" in url else "unknown",
                "is_reddit": False,
            })
        return articles
    except Exception as exc:
        logger.debug("RSS fetch failed for %s: %s", url, exc)
        return []


def _score_text(text: str) -> float:
    """Score text for sentiment."""
    words = set(text.lower().split())
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    return pos - neg


def _extract_tickers(text: str) -> list[str]:
    """Extract ticker symbols from text."""
    text_lower = text.lower()
    found = set()
    for name, ticker in TICKER_PATTERNS.items():
        if name in text_lower:
            found.add(ticker)
    # $TICKER pattern
    for match in re.findall(r'\$([A-Z]{2,5})\b', text):
        found.add(match)
    # ALL-CAPS words that look like tickers (2-5 chars, common in WSB)
    for match in re.findall(r'\b([A-Z]{2,5})\b', text):
        if match in {"AAPL", "MSFT", "NVDA", "TSLA", "AMD", "GOOGL", "AMZN",
                      "META", "NFLX", "GME", "AMC", "PLTR", "SOFI", "COIN",
                      "HOOD", "RIVN", "LCID", "BA", "DIS", "JPM", "GS",
                      "INTC", "MU", "AVGO", "QCOM", "CRM", "SHOP", "SNOW",
                      "CRWD", "PANW", "NOW", "SPY", "QQQ", "IWM"}:
            found.add(match)
    return list(found)


# ---------------------------------------------------------------------------
# Main fetch function
# ---------------------------------------------------------------------------

def fetch_market_news() -> dict:
    """
    Fetch from all sources. Reddit gets 2x sentiment weight.

    Returns:
        {
            "articles": [...],
            "market_sentiment": float,
            "ticker_mentions": {ticker: [articles]},
            "top_headlines": [...],
            "reddit_buzz": {ticker: {mentions, avg_upvotes, sentiment}},
            "total_articles": int,
        }
    """
    all_articles = []

    # Reddit first — highest priority
    for sub_name, url in REDDIT_SUBS.items():
        posts = _fetch_reddit(sub_name, url)
        for p in posts:
            p["sentiment"] = _score_text(p["title"] + " " + p.get("summary", ""))
            p["tickers"] = _extract_tickers(p["title"] + " " + p.get("summary", ""))
            # Reddit sentiment gets 2x weight based on upvotes
            upvote_mult = min(3.0, 1.0 + p.get("upvotes", 0) / 1000)
            p["weighted_sentiment"] = p["sentiment"] * upvote_mult * 2.0
        all_articles.extend(posts)

    # RSS feeds
    for feed_name, url in RSS_FEEDS.items():
        articles = _fetch_rss(url)
        for a in articles:
            a["feed"] = feed_name
            a["sentiment"] = _score_text(a["title"] + " " + a.get("summary", ""))
            a["tickers"] = _extract_tickers(a["title"] + " " + a.get("summary", ""))
            a["weighted_sentiment"] = a["sentiment"] * 1.0  # 1x weight for news
        all_articles.extend(articles)

    # Deduplicate
    seen = set()
    unique = []
    for a in all_articles:
        key = a["title"][:40].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    all_articles = unique

    # Overall market sentiment (weighted)
    total_weighted = sum(a.get("weighted_sentiment", 0) for a in all_articles)
    market_sentiment = total_weighted / max(len(all_articles), 1)

    # Per-ticker mentions with Reddit buzz tracking
    ticker_mentions: dict[str, list] = {}
    reddit_buzz: dict[str, dict] = {}

    for a in all_articles:
        for tk in a.get("tickers", []):
            if tk not in ticker_mentions:
                ticker_mentions[tk] = []
            ticker_mentions[tk].append({
                "headline": a["title"][:120],
                "sentiment": a.get("weighted_sentiment", 0),
                "source": a.get("source", ""),
                "is_reddit": a.get("is_reddit", False),
                "upvotes": a.get("upvotes", 0),
            })

    # Build Reddit buzz summary per ticker
    for tk, mentions in ticker_mentions.items():
        reddit_mentions = [m for m in mentions if m.get("is_reddit")]
        if reddit_mentions:
            reddit_buzz[tk] = {
                "mention_count": len(reddit_mentions),
                "avg_upvotes": sum(m.get("upvotes", 0) for m in reddit_mentions) / len(reddit_mentions),
                "avg_sentiment": sum(m.get("sentiment", 0) for m in reddit_mentions) / len(reddit_mentions),
                "top_post": max(reddit_mentions, key=lambda x: x.get("upvotes", 0))["headline"],
            }

    # Top headlines by weighted sentiment
    top_headlines = sorted(all_articles, key=lambda x: abs(x.get("weighted_sentiment", 0)), reverse=True)[:10]

    reddit_count = sum(1 for a in all_articles if a.get("is_reddit"))
    news_count = len(all_articles) - reddit_count

    logger.info(
        "Web news: %d Reddit posts + %d news articles, market_sentiment=%.2f, %d tickers mentioned, %d with Reddit buzz",
        reddit_count, news_count, market_sentiment, len(ticker_mentions), len(reddit_buzz),
    )

    return {
        "articles": all_articles,
        "market_sentiment": round(market_sentiment, 3),
        "ticker_mentions": ticker_mentions,
        "reddit_buzz": reddit_buzz,
        "top_headlines": [
            {"headline": h["title"][:120], "sentiment": h.get("weighted_sentiment", 0),
             "source": h.get("source", ""), "upvotes": h.get("upvotes", 0)}
            for h in top_headlines
        ],
        "total_articles": len(all_articles),
    }


def score_ticker_from_web_news(ticker: str, web_news: dict) -> dict:
    """
    Score a ticker based on web news + Reddit mentions.
    Reddit buzz gets highest weight — a trending WSB ticker with high upvotes
    gets a significant score boost.
    """
    mentions = web_news.get("ticker_mentions", {}).get(ticker, [])
    market_sent = web_news.get("market_sentiment", 0.0)
    buzz = web_news.get("reddit_buzz", {}).get(ticker)

    if not mentions and not buzz:
        adj = market_sent * 0.2
        return {
            "web_news_adj": round(adj, 2),
            "web_headlines": [],
            "web_mention_count": 0,
            "reddit_buzz": None,
            "market_sentiment": round(market_sent, 2),
        }

    # Average weighted sentiment of all mentions
    avg_sent = sum(m.get("sentiment", 0) for m in mentions) / max(len(mentions), 1)

    # Reddit buzz bonus — WSB trending tickers get extra weight
    reddit_adj = 0.0
    if buzz:
        reddit_sent = buzz.get("avg_sentiment", 0)
        mention_count = buzz.get("mention_count", 0)
        avg_upvotes = buzz.get("avg_upvotes", 0)

        # More mentions + higher upvotes = stronger signal
        volume_mult = min(2.0, 1.0 + mention_count * 0.15)
        upvote_mult = min(1.5, 1.0 + avg_upvotes / 2000)
        reddit_adj = reddit_sent * volume_mult * upvote_mult * 0.3

    # Combine: Reddit (highest) + news + market
    adj = (avg_sent * 0.3) + reddit_adj + (market_sent * 0.1)
    adj = max(-3.0, min(3.0, adj))  # cap at ±3.0

    return {
        "web_news_adj": round(adj, 2),
        "web_headlines": mentions[:5],
        "web_mention_count": len(mentions),
        "reddit_buzz": buzz,
        "market_sentiment": round(market_sent, 2),
    }
