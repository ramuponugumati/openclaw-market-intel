"""
Company Name + Fortune 500 Rank Lookup

Static mapping of ticker → (company_name, fortune_rank).
Fortune rank is 0 if not in Fortune 500.
"""

# Source: Fortune 500 (2025 list) + additional watchlist companies
COMPANY_DATA: dict[str, tuple[str, int]] = {
    "AAPL": ("Apple", 3),
    "ABBV": ("AbbVie", 46),
    "ABT": ("Abbott Laboratories", 75),
    "ADBE": ("Adobe", 213),
    "AMAT": ("Applied Materials", 194),
    "AMD": ("AMD", 135),
    "AMGN": ("Amgen", 119),
    "AMT": ("American Tower", 385),
    "AMZN": ("Amazon", 2),
    "APTV": ("Aptiv", 276),
    "ARE": ("Alexandria Real Estate", 0),
    "ARKK": ("ARK Innovation ETF", 0),
    "AVGO": ("Broadcom", 109),
    "AXP": ("American Express", 62),
    "BA": ("Boeing", 35),
    "BLK": ("BlackRock", 229),
    "BMY": ("Bristol-Myers Squibb", 71),
    "BRK-B": ("Berkshire Hathaway", 6),
    "C": ("Citigroup", 23),
    "CAT": ("Caterpillar", 55),
    "CMCSA": ("Comcast", 25),
    "COIN": ("Coinbase", 0),
    "COP": ("ConocoPhillips", 86),
    "COST": ("Costco", 11),
    "CRM": ("Salesforce", 136),
    "CRWD": ("CrowdStrike", 0),
    "CVX": ("Chevron", 15),
    "DE": ("John Deere", 69),
    "DIA": ("Dow Jones ETF", 0),
    "DIS": ("Walt Disney", 53),
    "ENPH": ("Enphase Energy", 0),
    "EOG": ("EOG Resources", 168),
    "FSLR": ("First Solar", 0),
    "GE": ("GE Aerospace", 60),
    "GOOGL": ("Alphabet/Google", 8),
    "GS": ("Goldman Sachs", 56),
    "HD": ("Home Depot", 18),
    "HON": ("Honeywell", 88),
    "HOOD": ("Robinhood", 0),
    "ICE": ("Intercontinental Exchange", 0),
    "INTC": ("Intel", 83),
    "INTU": ("Intuit", 260),
    "IWM": ("Russell 2000 ETF", 0),
    "JNJ": ("Johnson & Johnson", 36),
    "JPM": ("JPMorgan Chase", 1),
    "KLAC": ("KLA Corp", 0),
    "KO": ("Coca-Cola", 87),
    "LCID": ("Lucid Motors", 0),
    "LLY": ("Eli Lilly", 77),
    "LMT": ("Lockheed Martin", 44),
    "LOW": ("Lowe's", 27),
    "LRCX": ("Lam Research", 196),
    "LW": ("Lamb Weston", 0),
    "LYB": ("LyondellBasell", 117),
    "MA": ("Mastercard", 171),
    "MCD": ("McDonald's", 110),
    "META": ("Meta Platforms", 26),
    "MRNA": ("Moderna", 0),
    "MRVL": ("Marvell Technology", 0),
    "MS": ("Morgan Stanley", 57),
    "MSFT": ("Microsoft", 13),
    "MU": ("Micron Technology", 104),
    "NEE": ("NextEra Energy", 174),
    "NEM": ("Newmont", 0),
    "NFLX": ("Netflix", 115),
    "NKE": ("Nike", 76),
    "NOW": ("ServiceNow", 0),
    "NVDA": ("NVIDIA", 97),
    "ORCL": ("Oracle", 80),
    "PANW": ("Palo Alto Networks", 0),
    "PEP": ("PepsiCo", 41),
    "PFE": ("Pfizer", 42),
    "PG": ("Procter & Gamble", 22),
    "PLD": ("Prologis", 0),
    "PLTR": ("Palantir", 0),
    "PM": ("Philip Morris", 90),
    "PVH": ("PVH Corp", 0),
    "PYPL": ("PayPal", 143),
    "QCOM": ("Qualcomm", 114),
    "QQQ": ("Nasdaq 100 ETF", 0),
    "RIVN": ("Rivian", 0),
    "RTX": ("RTX (Raytheon)", 37),
    "SBUX": ("Starbucks", 99),
    "SCHW": ("Charles Schwab", 0),
    "SHOP": ("Shopify", 0),
    "SLB": ("Schlumberger", 148),
    "SNOW": ("Snowflake", 0),
    "SOFI": ("SoFi Technologies", 0),
    "SOXX": ("Semiconductor ETF", 0),
    "SPY": ("S&P 500 ETF", 0),
    "STX": ("Seagate", 0),
    "TMO": ("Thermo Fisher", 100),
    "TSLA": ("Tesla", 39),
    "TXN": ("Texas Instruments", 175),
    "UNH": ("UnitedHealth Group", 5),
    "UPS": ("UPS", 38),
    "V": ("Visa", 79),
    "WBD": ("Warner Bros Discovery", 0),
    "WDC": ("Western Digital", 0),
    "WMT": ("Walmart", 1),
    "XLE": ("Energy Select ETF", 0),
    "XLF": ("Financial Select ETF", 0),
    "XLK": ("Technology Select ETF", 0),
    "XLV": ("Health Care Select ETF", 0),
    "XOM": ("ExxonMobil", 4),
}


def get_company_name(ticker: str) -> str:
    """Return company name for a ticker, or the ticker itself if unknown."""
    data = COMPANY_DATA.get(ticker)
    return data[0] if data else ticker


def get_fortune_rank(ticker: str) -> int:
    """Return Fortune 500 rank (0 if not in Fortune 500)."""
    data = COMPANY_DATA.get(ticker)
    return data[1] if data else 0


def get_display_name(ticker: str) -> str:
    """Return 'Company Name (TICKER)' format for display."""
    name = get_company_name(ticker)
    return f"{name} ({ticker})" if name != ticker else ticker


def get_fortune_badge(ticker: str) -> str:
    """Return Fortune rank badge like 'F500 #3' or empty string."""
    rank = get_fortune_rank(ticker)
    if rank > 0:
        return f"F500 #{rank}"
    return ""
