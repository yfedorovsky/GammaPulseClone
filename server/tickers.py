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
    "TLT",   # 20+ Year Treasury Bond ETF — duration / long-rate macro hedge.
             # Added 5/19: UW flagged TLT $84C 6/26 (4,499 contracts on
             # the ASK, $405K premium, 94% chain bid/ask). Major macro-flow
             # gap before now — institutions hedge rate cuts via TLT calls.
    # Leveraged ETFs — institutional front-run vehicles (added 5/13).
    # Buddy's hypothesis: NVDL flow yesterday signaled today's Trump-China-
    # NVDA-CEO news before it broke. Levered ETFs let funds front-run a
    # catalyst without showing in single-name flow optics.
    "NVDL",  # 2x NVDA long — the canonical NVDA front-run signal
    "TSLL",  # 1.5x TSLA long — TSLA proxy without single-name attention
    "SOXL",  # 3x semis long — semi-thesis amplifier
    "SOXS",  # 3x semis short — semi hedge tracker
    "TQQQ",  # 3x QQQ long
    "SQQQ",  # 3x QQQ short — broad-tech hedge tracker
    "SPXL",  # 3x SPY long
    "SPXU",  # 3x SPY short
    "TECL",  # 3x tech sector long
    "MSTU",  # 2x MSTR long — crypto/BTC proxy via MSTR
    # Sector SPDRs (only SMH was covered; rest were gaps per 5/13 audit)
    "XLK",   # Tech sector
    "XLF",   # Financials
    "XLE",   # Energy
    "XLV",   # Healthcare
    "XLY",   # Consumer discretionary
    "XLP",   # Consumer staples
    "XLI",   # Industrials
    "XLU",   # Utilities
    "XLB",   # Materials
    "XLRE",  # Real estate
    "XLC",   # Communications
    "KRE",   # Regional banks (financials sub-sector)
    # VIX/vol ETPs — flow signal for vol regime shifts
    "VXX",   # VIX short-term futures ETN
    # Mega caps
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "AVGO", "LLY", "UNH", "V", "JPM", "XOM", "JNJ", "PG", "MA", "HD",
    # High-activity movers
    "AMD", "COIN", "PLTR", "NFLX", "CRM", "ORCL", "ADBE", "INTC", "MU", "UVXY",
    "BAC", "WMT", "COST", "DIS", "CSCO", "PEP", "KO", "T", "VZ", "SMCI",
    # AI silicon / connectivity — promoted to TIER_1 Apr 21 (live signal priority).
    # All four hit the Finviz breakout + RS-pullback screens the same session;
    # ANET also fired SOE MAGNET BREAKOUT A-grade live. Every-cycle refresh
    # matters because these can trigger intraday GEX transitions.
    "ALAB",  # Astera Labs — PCIe/CXL retimers, Tier-1 AI silicon
    "CRDO",  # Credo — AEC/retimer silicon, ALAB peer (correlated move)
    "AEHR",  # Aehr Test Systems — semi equipment, dual-screen hit
    "ANET",  # Arista Networks — AI connectivity backbone
    # Memory / NAND cycle — promoted Apr 21 on group-wide breakout
    # (WDC +$10, STX +$16 today; SNDK already leading; user's thesis:
    # whole group to new highs). DRAM ETF fresh breakout confirms the cycle.
    "WDC",   # Western Digital — NAND, breakout Apr 21
    "STX",   # Seagate — HDD/NAND, breakout Apr 21
    "SNDK",  # Sandisk — NAND leader, already extended
]

TIER_2 = [
    # Tech / semis
    "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "ASML", "TSM", "ARM", "MRVL", "SMH", "SOXX",
    "NOW", "SHOP", "SNOW", "DDOG", "NET", "CRWD", "ZS", "PANW", "MDB",
    "UBER", "LYFT", "ABNB", "PYPL", "XYZ", "HOOD", "RBLX", "U", "DELL", "HPE",
    "IBM",   # Added 2026-04-22 — blind spot; Discord friend flagged as bearish setup, -2.7% day
    # IBD adds (Apr 20) — large-cap Sector Leaders + Data Storage leaders
    # WDC / STX / SNDK promoted to TIER_1 Apr 21 (group breakout day).
    "APH",   # Amphenol — IBD Sector Leader, Electronic-Connectors
    # Gemini weekend research (Apr 19) — data center power thesis
    "GEV",   # GE Vernova — grid, turbines, nuclear, wind; "power is the new real estate"
    # Sovereign silicon / specialty foundry (Apr 19 @Venu_7_ diagram)
    "GFS",   # GlobalFoundries — SiPh roadmap + CHIPS Act + auto + capital return
    # IBD "best of the best" leaders screen (Apr 20, Comp 96+ AND RS 96+)
    "AMKR",  # Amkor Technology — packaging, CoWoS adjacent, Group #7
    "KEYS",  # Keysight — measurement/test, Group #9 Scientific
    "MPWR",  # Monolithic Power — power mgmt for data centers, Group #38
    # Added Apr 27 — Mir flagged in Q1 cascade thesis but missing from universe.
    # RMBS dropped -10% AH on its print without any system warning, validating
    # the gap. Memory-systems IP company; sympathy-trades with MU/SNDK earnings.
    "RMBS",  # Rambus — high-perf memory IP, sympathy-trades semis cycle
    # Breadth / concentration proxies (added Apr 27 — macro regime layer).
    # QQQE = equal-weight Nasdaq-100. Compared to QQQ (cap-weighted) it
    # surfaces narrow-leadership tape: QQQ up + QQQE flat = "only mega-caps
    # working." XMAG = large-cap ex-Magnificent-7. RSP = equal-weight S&P 500.
    # Used by macro_regime.py to compute participation/concentration tilt.
    "QQQE",  # Direxion Nasdaq-100 Equal Weight ETF
    "XMAG",  # Roundhill Magnificent Seven ex-mag-7 (large-cap minus FAANG)
    "RSP",   # Invesco S&P 500 Equal Weight ETF
    # Financials
    # BRK/B uses Tradier's slash convention (not BRK.B); the dot form returns
    # no quotes/expirations. Confirmed 5/13 via probe (P1 closing audit).
    "WFC", "C", "GS", "MS", "SCHW", "AXP", "BLK", "SPGI", "BRK/B", "ICE",
    "CME", "PNC", "USB", "COF", "TFC",
    # Energy
    "CVX", "COP", "SLB", "OXY", "EOG", "MPC", "PSX", "VLO", "HAL",
    # Health
    "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "MDT", "BMY", "AMGN", "GILD",
    "REGN", "VRTX", "ISRG", "ELV", "CI", "HUM", "CVS",
    "CNC",  # Centene — added 5/12 after Cheddar's #2 bullish flow ($49.8M
            # premium) missed by universe gap. Managed care, CMS exposure.
    # Consumer
    "MCD", "SBUX", "NKE", "LOW", "TGT", "TJX", "BKNG", "MAR", "F", "GM",
    "RIVN", "LCID", "CMG", "CAT", "DE", "BA", "LMT", "RTX", "NOC", "GD",
    "HON", "GE", "UPS", "FDX", "UNP", "CSX", "NSC", "LUV", "DAL", "UAL", "AAL",
    # Retail / consumer
    # JWN removed 5/13 (P1 audit): Nordstrom taken private Dec 2024, only LEAP
    # remaining — effectively no options coverage.
    "WBA", "KR", "DG", "DLTR", "BBY", "ROST", "BURL", "M", "KSS",
    # Industrials & materials
    # X removed 5/13 (P1 audit): US Steel acquired by Nippon Steel Jun 2025;
    # Tradier still returns stale expirations but no real liquidity.
    "LIN", "APD", "SHW", "ECL", "NUE", "FCX", "CLF", "AA",
    # Paper / packaging cyclicals (added 2026-04-22 after IP bear miss)
    # Classic cyclical shorts that we had zero coverage on. Mid-caps,
    # liquid options chains, trade well in risk-off tapes.
    "IP",    # International Paper — Discord friend flagged as bear today
    "PKG",   # Packaging Corp of America — direct IP peer
    # WRK removed 5/13 (P1 audit): WestRock merged with Smurfit Kappa
    # July 2024 to form SW (Smurfit Westrock plc). WRK ticker dead; SW
    # is the live ticker — add SW separately if needed.
    # Real estate / REITs
    "PLD", "AMT", "EQIX", "CCI", "PSA", "O", "SPG", "WELL", "DLR",
    "CBRS",  # CBRE Group — commercial real estate services. Added 5/19:
             # UW flagged CBRS 340C 7/17 ($118K, ASK-side); also surfaced
             # in our Mir signal cache yesterday as WATCH HIGH from
             # TraderMir. Two-source confirmation, no prior coverage.
    # Utilities
    "NEE", "DUK", "SO", "AEP", "EXC", "D", "SRE", "XEL", "PEG",
]

TIER_3 = [
    # China ADRs
    # TCEHY removed 5/13 (P1 audit): Tencent OTC ADR has zero listed US options
    # (sanctions / OFAC overhang pulled MM liquidity); stock quotes fine but
    # expirations() returns 0 dates. No options = nothing to scan.
    "BABA", "PDD", "JD", "BIDU", "NIO", "XPEV", "LI", "BILI", "TME",
    # Photonics / Fiber / AI Infra (Mir's top themes 2026)
    # ANET promoted to TIER_1 Apr 21.
    "AAOI", "COHR", "GLW", "CIEN", "VRT", "AXTI", "LITE",
    "POET",  # POET Technologies — photonics integration. Added 5/19 after
             # UW flagged POET $17C 7/17 as the #1 contract by volume
             # across the entire UW universe today (131K vol, OI 62K, V/OI 2.09).
             # Mr. Whale also flagged it as "under-the-radar bullish" with
             # +115% / 30 days. Was on our radar via PUT loss; now flipped.
    "NOK",  # Nokia — networking + telecom infra. Added 5/13 after
            # 5/13 NOK 1/15/27 $27C LEAP whale ($1.69M premium, 13.5K
            # contracts, peak 2,379/min at 11:36) AND NOK was #7
            # most-traded options name today (499K contracts). Telecom
            # exposure missing from universe.
    "VIAV",  # Apr 20 IBD add — Fiber Optics Group #1 (144% YTD)
    "LASR",  # nLIGHT — lasers/photonics, Group #6 Electronic-Parts leader
    # Semi Equipment (Mir's basket + Apr 20 IBD Group #3 expansion)
    # AEHR promoted to TIER_1 Apr 21.
    "TER",
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
    "NVTS",  # Navitas Semiconductor — GaN power ICs, AI-DC power infra.
             # Added 5/13: Mir called 18JUN 20C @ $4 entry; buddy flagged
             # it earlier same day. 7-day Mir backfill audit showed NVTS
             # as one of only 2 universe gaps (HIMX was the other).
    # Space (SpaceX IPO catalyst)
    "ASTS", "RKLB",
    "SATS",  # EchoStar — spectrum/satellite/Boost Mobile, RS 93, liquid leader
    "VSAT",  # Viasat — defense/gov satcom + multi-orbit connectivity (GPT Apr 19)
    "GSAT",  # Globalstar — AMZN deal catalyst, 52w high, satellite operator
    "BKSY",  # BlackSky — geospatial intel / sat imaging; defense-adjacent (Apr 21 breakout screen +4%)
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
    "QUBT",   # Quantum Computing Inc — added 6/8 (coverage gap)
    "SOUN",   # SoundHound AI — added 6/8: high-flow AI voice name (coverage gap)
    "OSCR",   # Oscar Health — added 6/8: liquid health-fintech flow name (coverage gap)
    # Nuclear / SMR (added 2026-04-16 — White House space nuclear directive Apr 14)
    "SMR", "NNE", "UUUU",
    # EVs & clean energy
    "FSLR", "ENPH", "SEDG", "RUN", "PLUG", "CHPT", "BLNK",
    "AMPX",  # Amprius Technologies — silicon anode batteries (Airbus, DoD, eVTOL)
    "FCEL", "BE", "BLDP",  # fuel-cell trio (added 5/12 after FCEL 6/26 $19C
                            # $1.3M sweep missed — Will Meade flagged but
                            # FCEL wasn't in scanner universe at all)
    # Biotech / pharma
    "XBI", "MRNA", "BNTX", "NVAX", "BIIB", "ILMN", "ZTS", "SYK", "EW", "BSX", "BDX",
    "BAX", "RMD", "DXCM", "IDXX", "A",
    # Crypto-related (MSTR = BTC proxy, Qullamaggie + Stockbee momentum leader)
    "MARA", "RIOT", "MSTR", "CLSK", "HUT", "BITF",
    "GLXY",  # Galaxy Digital — added 6/8: FL0WG0D $3M 31C 6/26 ASK whale (303%)
             # was a coverage gap (not in universe → 0 alerts). Crypto/digital-asset.
    "BMNR",  # Bitmine Immersion — ETH-treasury proxy (added 6/8, coverage gap)
    "CIFR",  # Cipher Mining — BTC miner pivoted to AI hosting (Fluidstack/Google deal)
    "WULF",  # TeraWulf — BTC miner. Added 5/19: UW unusual-flow tape showed
             # WULF $27C 7/17 with 78% bullish premium skew (most lopsided
             # bullish on the day), AND Mr. Whale flagged it as "under-the-
             # radar bullish speculation". Same theme as MARA/RIOT/CLSK.
    # Speculatives / meme
    # WISH removed 5/13 (P1 audit): ContextLogic delisted from NASDAQ 2023;
    # no options chain on Tradier.
    "GME", "AMC", "RDDT", "BB", "SOFI", "CLOV", "PTON", "BYND", "FUBO",
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
    # Memory / DRAM cycle macro proxies (Apr 21 — group breakout thesis)
    "EWY",   # iShares MSCI Korea — Samsung + SK Hynix HBM exposure
    "DRAM",  # DRAM/memory supply-chain ETF — fresh breakout Apr 21
    # Semiconductors second tier
    "ON", "MCHP", "ADI", "NXPI", "STM", "SWKS", "QRVO", "WOLF", "CRUS",
    # Software second tier
    "TEAM", "WDAY", "INTU", "CDNS", "SNPS", "FTNT", "OKTA", "ZM", "DOCU",
    "TWLO", "PINS", "SNAP", "SPOT", "ROKU", "MTCH", "YELP", "TRIP",
    "ZETA",  # Zeta Global — AI marketing software. Added 5/19: UW unusual
             # flow showed ZETA 19.5C 6/18 with 2,421 contracts (98% chain
             # bid/ask), AND Mr. Whale flagged it under "less crowded bullish
             # speculation". Fits the small/mid-cap growth bucket.
    "PAYC",  # Paycom Software — HR/payroll SaaS. Added 5/19: UW showed
             # PAYC 135P 6/18 (222 contracts, $111K, 98% bearish). Active
             # options flow on a name not previously in universe.
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
    # ALAB + CRDO promoted to TIER_1 Apr 21.
    "PL",    # Planet Labs — earth observation satellites, space adjacent
    "FLY",   # Firefly Aerospace — space launch, momentum (Stockbee scan)
    "POWL",  # Powell Industries — DC electrical distribution, Group #29
    "TTMI",  # TTM Technologies — PCBs/EMS, Group #13 Contract Mfg
    "LWLG",  # Lightwave Logic — polymer photonics/modulators, optical speculative
    # Mir Monis top-20 "trade without looking at anything else" list (Apr 19)
    # 19/20 already covered — TSEM was the only gap
    "TSEM",  # Tower Semiconductor — Israeli specialty foundry, RF/analog/SiGe, 86% YTD
    # Qullamaggie x Minervini screener (Sat Apr 25) — adds filling 3 thematic gaps:
    # specialty chemicals, lithium revival, semi-equip peer. Oilfield-services
    # block (AESI/PUMP/RES/PTEN/NBR) intentionally limited to AESI (most liquid
    # frac leader) — others can be added if the OFS theme persists.
    "CAMT",  # Camtek — semi inspection/metrology, direct peer to ICHR/UCTT/NVMI
    "LAR",   # Lithium Argentina — A-setup, lithium cycle revival after 2-yr drawdown
    "TROX",  # Tronox — TiO2 chemicals leader, A- setup, +60% 63d
    "AESI",  # Atlas Energy Solutions — frac sand leader, OFS pure-play (gap fill)
    # ── 5/28 morning watchlist coverage gaps (added 2026-05-27 PM) ─────
    # Cross-referenced trader's morning watchlist against universe; 13
    # names were uncovered. Added all to TIER_3 (every-4-cycle refresh).
    # Promote individual names to TIER_2 if they show repeated edge.
    # Drone / defense (Trump admin financing deal news):
    "UMAC",  # Unusual Machines — drone
    "ONDS",  # Ondas — drone communications
    "SWMR",  # Salmar / Swarm? — drone
    "DPRO",  # Draganfly — drone manufacturer
    # Mid-caps with discrete catalysts:
    "ASTC",  # Astrotech — lunar mining + quantum + semis announcement
    "DASH",  # DoorDash — DLTR partnership news
    # Sideways setup names (Mir watchlist 5/28):
    "DOCN",  # DigitalOcean — cloud infra
    "MXL",   # MaxLinear — semis / connectivity
    # Memory / photonics — user thesis name:
    "SIMO",  # Silicon Motion — NAND controllers, memory cycle play
    # Space cohort:
    "LUNR",  # Intuitive Machines — lunar lander
    "RDW",   # Redwire Space — satellite infra
    "SPCE",  # Virgin Galactic — space tourism
    # Quantum cohort:
    "INFQ",  # Infleqtion (or similar) — quantum
    # ── 5/28 PM TraderMir robotics theme (added 2026-05-28) ───────────
    # Mir's go-to robotics names for "next month" (June). Both have
    # actively-traded options chains. SERV is autonomous delivery,
    # RR is Richtech (service robots in food service / hospitality).
    "SERV",  # Serve Robotics — autonomous sidewalk delivery, ~$9 small-cap
    "RR",    # Richtech Robotics — F&B service robots, ~$3 microcap
    # Robotics theme expansion (5/28 PM): adds June-conference exposure.
    # Mir's research mapped: Boston (TER, already covered), Tokyo (TSLA/NVDA
    # already covered), Vienna ICRA (NVDA), Munich EMEA (Schaeffler/Siemens
    # ADRs have no listed options — can't add). KOID is the cleanest ETF
    # proxy but has no options. Only CGNX has a real chain.
    "CGNX",  # Cognex — machine vision for industrial robotics
    # OG GammaPulse scorecard audit gap (5/28 PM): only ticker from their
    # recurring winners list NOT in our universe. AppLovin = adtech +
    # AI ad-targeting story.
    "APP",   # AppLovin — adtech/AI ads, OG recurring still-open + winner
    # ─── Universe-audit adds (2026-06-04 PM) — chain scanner coverage ─
    # Subscription_plan_dryrun.py verified these were missing from the
    # chain scanner universe too, which means they would have been
    # invisible to BOTH the OPRA stream path AND the slow chain-snapshot
    # path. The 6/4 NEE 77.5C $10.6M whale catch validated the
    # AI-power-utility thesis — adding these closes the slow-path gap.
    "CEG",   # Constellation nuclear baseload — AI power thesis
    "VST",   # Vistra nuclear + coal-to-data-center — AI power thesis
    "FXI",   # China broad ETF — $36M flow 6/4
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
