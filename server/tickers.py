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
    # Sovereign silicon / specialty foundry (Apr 19 @Venu_7_ diagram)
    "GFS",   # GlobalFoundries — SiPh roadmap + CHIPS Act + auto + capital return
    # IBD "best of the best" leaders screen (Apr 20, Comp 96+ AND RS 96+)
    "AMKR",  # Amkor Technology — packaging, CoWoS adjacent, Group #7
    "KEYS",  # Keysight — measurement/test, Group #9 Scientific
    "MPWR",  # Monolithic Power — power mgmt for data centers, Group #38
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
    "LASR",  # nLIGHT — lasers/photonics, Group #6 Electronic-Parts leader
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
    "AEIS",  # Advanced Energy Industries — semi equipment power, Group #3
    # Space (SpaceX IPO catalyst)
    "ASTS", "RKLB",
    "SATS",  # EchoStar — spectrum/satellite/Boost Mobile, RS 93, liquid leader
    "VSAT",  # Viasat — defense/gov satcom + multi-orbit connectivity (GPT Apr 19)
    "GSAT",  # Globalstar — AMZN deal catalyst, 52w high, satellite operator
    # Signal integrity / comms semis breakout (GPT Apr 19)
    "SMTC",  # Semtech — data center interconnect, comms infra, +36% 1M
    # Aerospace & defense specialty metals
    "ATI",   # ATI Inc — titanium/Ni alloys for jet engines + DoD, RS 99
    # Drone / electronic warfare / autonomous defense (Grok Apr 19 gap analysis)
    "AVAV",  # AeroVironment — Switchblade loitering munitions, drone warfare pure-play
    "KTOS",  # Kratos Defense — unmanned aerial, tactical drones, hypersonics
    # Power transmission infrastructure (the real gap — we had generation, not transmission)
    "PWR",   # Quanta Services — grid/transmission onshoring, AI data center power backbone
    "MYRG",  # MYR Group — mid-cap T&D pure-play, higher-beta PWR alternative
    "FLR",   # Fluor — diversified EPC, $25.5B backlog, TeraWulf 480MW DC contract
    # Rare earth / critical minerals onshoring (Pentagon stockpile thesis)
    "MP",    # MP Materials — US rare earth miner, only scaled domestic NdPr producer
    "USAR",  # USA Rare Earth — Oklahoma magnet plant, DoD-adjacent (Perplexity Apr 19)
    # Drone defense — Army Program of Record pure-play
    "RCAT",  # Red Cat Holdings — Short Range Reconnaissance PoR, drone pure-play
    # ADAS / autonomous silicon (beyond NVDA)
    "MBLY",  # Mobileye — EyeQ6/Chauffeur ramp, dominant global ADAS supplier
    # Stablecoin / crypto infrastructure (beyond MSTR/COIN)
    "CRCL",  # Circle Internet Group — USDC issuer, pure stablecoin rail
    # Warehouse robotics / industrial automation
    "SYM",   # Symbotic — warehouse automation at scale, Walmart backlog
    # Cyber data resilience (fastest-growing post-IPO cyber)
    "RBRK",  # Rubrik — data security / backup, AI-era cyber pure-play
    # AI / Momentum
    "NBIS", "OKLO", "IREN",
    "CRWV",  # CoreWeave — #1 neocloud, NVDA-reference customer (Apr 19 Gemini research)
    "APLD",  # Applied Digital — data center / AI hosting REIT; Neocloud thematic
    # Edge AI / Robotics vision (Apr 19 — China humanoid theme +94% YoY)
    "AMBA",  # Ambarella — edge AI vision silicon, robotics/autonomous/security cam
    # Quantum Computing (theme heating up Apr 19 — IONQ significant qubits progress)
    "IONQ",   # IonQ — trapped-ion, most liquid pure-play quantum
    "RGTI",   # Rigetti — superconducting, NVDA partnership
    "QBTS",   # D-Wave Quantum — annealing, was in Stockbee scan 20%+ week
    # Nuclear / SMR (added 2026-04-16 — White House space nuclear directive Apr 14)
    "SMR", "NNE", "UUUU",
    # EVs & clean energy
    "FSLR", "ENPH", "SEDG", "RUN", "PLUG", "CHPT", "BLNK",
    "AMPX",  # Amprius Technologies — silicon anode batteries (Airbus, DoD, eVTOL)
    # Biotech / pharma
    "XBI", "MRNA", "BNTX", "NVAX", "BIIB", "ILMN", "ZTS", "SYK", "EW", "BSX", "BDX",
    "BAX", "RMD", "DXCM", "IDXX", "A",
    # Crypto-related (MSTR = BTC proxy, Qullamaggie + Stockbee momentum leader)
    "MARA", "RIOT", "MSTR", "CLSK", "HUT", "BITF",
    "CIFR",  # Cipher Mining — BTC miner pivoted to AI hosting (Fluidstack/Google deal)
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
    # Event-trade / FDA catalyst (specific binary: July 23-24 peptide advisory mtg)
    "HIMS",  # Hims & Hers — peptide facility + 35% SI + FDA July 23-24 committee
    # IBD Sector Leaders — Industrials + Financials
    "FIX",   # Comfort Systems — 77% YTD, IBD Group #20 HVAC
    "ROAD",  # Construction Partners — 16% YTD, IBD Group #15 heavy construction
    "FUTU",  # Futu — 2% YTD, finance-investment banking
    "MRX",   # Marex — 34% YTD, finance-investment banking
    # IBD leaders screen Apr 20 — power + thermal + EMS (AI infra beneficiaries)
    "MOD",   # Modine Manufacturing — thermal mgmt for AI racks, Group #20 HVAC
    "VICR",  # Vicor — power conversion / 800VDC thesis, Group #6 Elec-Parts
    "CLS",   # Celestica — EMS for hyperscalers, Group #13 Contract Mfg
    "BE",    # Bloom Energy — fuel cells for data center power, Group #22 Alt
    # Mir's focus list Apr 19 — filling gaps
    "ALAB",  # Astera Labs — AI connectivity/CXL silicon, Group #38 specialty
    "CRDO",  # Credo Technology — AEC/retimer silicon for AI racks, ALAB peer (@SRxTrades Apr 19)
    "PL",    # Planet Labs — earth observation satellites, space adjacent
    "FLY",   # Firefly Aerospace — space launch, momentum (Stockbee scan)
    "POWL",  # Powell Industries — DC electrical distribution, Group #29
    "TTMI",  # TTM Technologies — PCBs/EMS, Group #13 Contract Mfg
    "LWLG",  # Lightwave Logic — polymer photonics/modulators, optical speculative
    # Mir Monis top-20 "trade without looking at anything else" list (Apr 19)
    # 19/20 already covered — TSEM was the only gap
    "TSEM",  # Tower Semiconductor — Israeli specialty foundry, RF/analog/SiGe, 86% YTD
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
