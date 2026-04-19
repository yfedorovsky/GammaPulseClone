"""The scanner universe. Each ticker is assigned a tier that controls scan frequency.

Tier 1 = majors (refreshed every cycle)
Tier 2 = actives (refreshed every 2 cycles)
Tier 3 = long tail (refreshed every 4 cycles)
"""

TIER_1 = [
    # Indexes & index ETFs
    "SPY", "QQQ", "IWM", "DIA", "VIX", "SPX", "NDX", "RUT", "IBIT",
    # Commodity ETFs (high options liquidity, macro-hedge exposure)
    "USO",   # United States Oil Fund — Hormuz / OPEC / supply shocks
    "GLD",   # SPDR Gold Shares — safe-haven flows / real-rate regime
    "SLV",   # iShares Silver Trust — gold proxy + industrial demand beta
    # Mega caps
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "AVGO", "LLY", "UNH", "V", "JPM", "XOM", "JNJ", "PG", "MA", "HD",
    # High-activity movers
    "AMD", "COIN", "PLTR", "NFLX", "CRM", "ORCL", "ADBE", "INTC", "MU", "UVXY",
    "BAC", "WMT", "COST", "DIS", "CSCO", "PEP", "KO", "T", "VZ", "SMCI",
]

TIER_2 = [
    # Tech / semis
    "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "ASML", "TSM", "ARM", "MRVL", "SMH", "SOXX",
    "NOW", "SHOP", "SNOW", "DDOG", "NET", "CRWD", "ZS", "PANW", "MDB",
    "UBER", "LYFT", "ABNB", "PYPL", "XYZ", "HOOD", "RBLX", "U", "DELL", "HPE", "SNDK",
    # IBD adds (Apr 20) — large-cap Sector Leaders + Data Storage leaders
    "APH",   # Amphenol — IBD Sector Leader, Electronic-Connectors
    "WDC",   # Western Digital — IBD Group #2 Data Storage
    "STX",   # Seagate — IBD Group #2 Data Storage
    # Gemini weekend research (Apr 19) — data center power thesis
    "GEV",   # GE Vernova — grid, turbines, nuclear, wind; "power is the new real estate"
    # Financials
    "WFC", "C", "GS", "MS", "SCHW", "AXP", "BLK", "SPGI", "BRK.B", "ICE",
    "CME", "PNC", "USB", "COF", "TFC",
    # Energy
    "CVX", "COP", "SLB", "OXY", "EOG", "MPC", "PSX", "VLO", "HAL",
    # Health
    "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "MDT", "BMY", "AMGN", "GILD",
    "REGN", "VRTX", "ISRG", "ELV", "CI", "HUM", "CVS",
    # Consumer
    "MCD", "SBUX", "NKE", "LOW", "TGT", "TJX", "BKNG", "MAR", "F", "GM",
    "RIVN", "LCID", "CMG", "CAT", "DE", "BA", "LMT", "RTX", "NOC", "GD",
    "HON", "GE", "UPS", "FDX", "UNP", "CSX", "NSC", "LUV", "DAL", "UAL", "AAL",
    # Retail / consumer
    "WBA", "KR", "DG", "DLTR", "BBY", "ROST", "BURL", "M", "KSS", "JWN",
    # Industrials & materials
    "LIN", "APD", "SHW", "ECL", "NUE", "FCX", "X", "CLF", "AA",
    # Real estate / REITs
    "PLD", "AMT", "EQIX", "CCI", "PSA", "O", "SPG", "WELL", "DLR",
    # Utilities
    "NEE", "DUK", "SO", "AEP", "EXC", "D", "SRE", "XEL", "PEG",
]

TIER_3 = [
    # China ADRs
    "BABA", "PDD", "JD", "BIDU", "NIO", "XPEV", "LI", "TCEHY", "BILI", "TME",
    # Photonics / Fiber / AI Infra (Mir's top themes 2026)
    "AAOI", "COHR", "GLW", "CIEN", "ANET", "VRT", "AXTI", "LITE",
    "VIAV",  # Apr 20 IBD add — Fiber Optics Group #1 (144% YTD)
    # Semi Equipment (Mir's basket + Apr 20 IBD Group #3 expansion)
    "AEHR", "TER",
    "ICHR",  # Ichor Holdings — 222% YTD, IBD Group #3 top-3 member
    "UCTT",  # Ultra Clean Holdings — 191% YTD
    "FORM",  # FormFactor — 131% YTD
    "MKSI",  # MKS Inc — 65% YTD
    "KLIC",  # Kulicke & Soffa — 69% YTD
    "ONTO",  # Onto Innovation — 75% YTD
    "NVMI",  # Nova — 52% YTD
    "ENTG",  # Entegris — 63% YTD
    "PLAB",  # Photronics — 45% YTD
    # Space (SpaceX IPO catalyst)
    "ASTS", "RKLB",
    # AI / Momentum
    "NBIS", "OKLO", "IREN",
    "CRWV",  # CoreWeave — #1 neocloud, NVDA-reference customer (Apr 19 Gemini research)
    # Edge AI / Robotics vision (Apr 19 — China humanoid theme +94% YoY)
    "AMBA",  # Ambarella — edge AI vision silicon, robotics/autonomous/security cam
    # Quantum (added 2026-04-16 — NVDA Ising model catalyst, IONQ most liquid)
    "IONQ", "RGTI",
    # Nuclear / SMR (added 2026-04-16 — White House space nuclear directive Apr 14)
    "SMR", "NNE", "UUUU",
    # EVs & clean energy
    "FSLR", "ENPH", "SEDG", "RUN", "PLUG", "CHPT", "BLNK",
    # Biotech / pharma
    "XBI", "MRNA", "BNTX", "NVAX", "BIIB", "ILMN", "ZTS", "SYK", "EW", "BSX", "BDX",
    "BAX", "RMD", "DXCM", "IDXX", "A",
    # Crypto-related
    "MARA", "RIOT", "MSTR", "CLSK", "HUT", "BITF",
    # Speculatives / meme
    "GME", "AMC", "RDDT", "BB", "SOFI", "WISH", "CLOV", "PTON", "BYND", "FUBO",
    # Cyclicals / other
    "F", "GM", "CAT", "DE", "PCAR", "CMI", "ITW", "ROK", "DOV", "EMR",
    "ETN", "PH", "ROP", "AME", "FTV", "IR", "OTIS", "CARR",
    # Consumer staples
    "CL", "KMB", "GIS", "K", "HSY", "MKC", "CLX", "SJM", "CAG", "CPB",
    # Media
    "CMCSA", "PSKY", "WBD", "FOX", "FOXA", "NWS", "NWSA",
    # Telecom / cable
    "TMUS", "CHTR", "LBRDK",
    # Others
    "CHWY", "ETSY", "EBAY", "W", "RH", "DKS", "ULTA", "LULU", "DECK",
    "CROX", "PVH", "TPR", "RL", "CPRI", "URBN", "ANF", "AEO",
    # Semiconductors second tier
    "ON", "MCHP", "ADI", "NXPI", "STM", "SWKS", "QRVO", "WOLF", "CRUS",
    # Software second tier
    "TEAM", "WDAY", "INTU", "CDNS", "SNPS", "FTNT", "OKTA", "ZM", "DOCU",
    "TWLO", "PINS", "SNAP", "SPOT", "ROKU", "MTCH", "YELP", "TRIP",
    # IBD Sector Leaders — Precious Metals (Apr 20, bull regime commodities)
    "AGI",   # Alamos Gold — 28% YTD, Sector Leader
    "GFI",   # Gold Fields — 14% YTD, Sector Leader
    "KGC",   # Kinross Gold — 24% YTD, Sector Leader
    "TFPM",  # Triple Flag Precious — 9% YTD, Sector Leader
    "WPM",   # Wheaton Precious — 30% YTD, Sector Leader
    "PAAS",  # Pan American Silver — major silver miner, IBD Mining-Gold/Silver
    # IBD Sector Leaders — Industrials + Financials
    "FIX",   # Comfort Systems — 77% YTD, IBD Group #20 HVAC
    "ROAD",  # Construction Partners — 16% YTD, IBD Group #15 heavy construction
    "FUTU",  # Futu — 2% YTD, finance-investment banking
    "MRX",   # Marex — 34% YTD, finance-investment banking
]


def all_tickers() -> list[str]:
    seen = set()
    out: list[str] = []
    for bucket in (TIER_1, TIER_2, TIER_3):
        for t in bucket:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


def tier_of(ticker: str) -> int:
    if ticker in TIER_1:
        return 1
    if ticker in TIER_2:
        return 2
    return 3
