# Theta Data Options/API Docs Aggregate

_Generated from Theta HTTP docs pages discoverable from the subscriptions page._

# Source: https://http-docs.thetadata.us/Articles/Getting-Started/Subscriptions.html

There are various subscriptions you can purchase, for the various data types sold by Theta Data. This page describes what each subscription entails.
REQUIRED
To access any data, you must have the Theta Terminal running. You should have a terminal open that looks something similar to the image below.
When you start the terminal, it will display the level of access you have for each type of data.
## Free Data â
1 year of free historical EOD (End of Day) data for US stocks and options is provided for free. There is a 30-requests/minute rate limit imposed on free accounts.
## Stock Data â
Theta Data has full historical coverage for the
UTP (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html)
tape going back to 2012-06-01. For symbols only available on the
CTA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html)
tape, the history is limited to 2017-01-01. This includes symbols like
SPY
and
GE
. Be sure to read our
Making Requests (https://http-docs.thetadata.us/Articles/Data-And-Requests/Making-Requests.html)
before purchasing a subscription.
### General Access â
Tier
Granularity
First Access Date
Server Threads
Delay
FREE
EOD
2023-06-01
30 reqs/min
1 day
VALUE
1 Minute
2021-01-01
1
15-minute
STANDARD
1 Minute
2016-01-01
2
Real-time
PRO
Tick Level
2012-06-01
4
Real time
### Historical Endpoint Access â
Endpoint
FREE
VALUE
STANDARD
PRO
EOD Report (https://http-docs.thetadata.us/operations/get-v2-hist-stock-eod.html)
â
â
â
â
Quote (https://http-docs.thetadata.us/operations/get-v2-hist-stock-quote.html)
â
â
â
OHLC (https://http-docs.thetadata.us/operations/get-v2-hist-stock-ohlc.html)
â
â
â
Splits (https://http-docs.thetadata.us/operations/get-v2-hist-stock-split.html)
â
â
Trades (https://http-docs.thetadata.us/operations/get-v2-hist-stock-trade.html)
â
â
Trade Quote (https://http-docs.thetadata.us/operations/get-get-v2-hist-stock-trade_quote.html)
â
â
### Real Time Endpoint Access â
Endpoint
FREE
VALUE
STANDARD
PRO
Quote Snapshot (https://http-docs.thetadata.us/operations/get-v2-snapshot-stock-quote.html)
Delayed (15min)
Real Time
Real Time
OHLC Snapshot (https://http-docs.thetadata.us/operations/get-v2-snapshot-stock-ohlc.html)
Delayed (15min)
Real Time
Real Time
Trade Snapshot (https://http-docs.thetadata.us/operations/get-v2-snapshot-stock-trade.html)
Real Time
Real Time
Bulk Quote Snapshot (https://http-docs.thetadata.us/operations/get-v2-bulk_snapshot-stock-quote.html)
Real Time
Real Time
### Real Time Streaming Access â
The number of contracts a tier can stream at the same time is defined below. All forms of equity streaming use real time data from the
Nasdaq Basic (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html)
feed.
Stream
FREE
VALUE
STANDARD
PRO
# of streamable contracts for quotes (https://http-docs.thetadata.us/Streaming/US-Stocks/Quote-Stream.html)
0
0
1,000
2,000
# of streamable contracts for trades (https://http-docs.thetadata.us/Streaming/US-Stocks/Trade-Stream.html)
0
0
1,000
20,000 (use the full trade stream)
## Options Data â
### General Access â
Tier
Granularity
First Access Date
Server Threads
Delay
FREE
EOD
2023-06-01
30 reqs/min
1 day
VALUE
1 Minute
2020-01-01
1
Real time
STANDARD
Tick Level
2016-01-01
2
Real time
PRO
Tick Level
2012-06-01
4
Real time
### Historical Endpoint Access â
Endpoint
FREE
VALUE
STANDARD
PRO
EOD (https://http-docs.thetadata.us/operations/hist-option-eod.html)
â
â
â
â
Quote (https://http-docs.thetadata.us/operations/get-hist-option-quote.html)
â
â
â
Open Interest (https://http-docs.thetadata.us/operations/get-hist-option-open_interest.html)
â
â
â
OHLC (https://http-docs.thetadata.us/operations/get-hist-option-ohlc.html)
â
â
â
Trade (https://http-docs.thetadata.us/operations/get-hist-option-trade.html)
â
â
Trade Quote (https://http-docs.thetadata.us/operations/get-hist-option-trade_quote.html)
â
â
Implied Volatility (https://http-docs.thetadata.us/operations/get-hist-option-implied_volatility.html)
â
â
Greeks 1st Order (https://http-docs.thetadata.us/operations/get-hist-option-greeks.html)
â
â
Greeks 2nd Order (https://http-docs.thetadata.us/operations/get-hist-option-greeks_second_order.html)
â
Greeks 3rd Order (https://http-docs.thetadata.us/operations/get-hist-option-greeks_third_order.html)
â
Trade Greeks 1st Order (https://http-docs.thetadata.us/operations/get-hist-option-trade_greeks.html)
â
Trade Greeks 2nd Order (https://http-docs.thetadata.us/operations/get-hist-option-trade_greeks_second_order.html)
â
Trade Greeks 3rd Order (https://http-docs.thetadata.us/operations/get-hist-option-trade_greeks_third_order.html)
â
### Bulk Historical Endpoint Access â
A bulk historical request allows you to request data every option contract to share the same symbol and expiration combination.
Endpoint
FREE
VALUE
STANDARD
PRO
Bulk EOD (https://http-docs.thetadata.us/operations/get-bulk_hist-option-eod.html)
â
â
Bulk Quote (https://http-docs.thetadata.us/operations/get-bulk_hist-option-quote.html)
â
â
Bulk Open Interest (https://http-docs.thetadata.us/operations/hist-option-open_interest.html)
â
â
Bulk Trade (https://http-docs.thetadata.us/operations/get-bulk_hist-option-trade.html)
â
â
Bulk Trade Quote (https://http-docs.thetadata.us/operations/get-bulk_hist-option-trade_quote.html)
â
â
Bulk EOD Greeks (https://http-docs.thetadata.us/operations/get-hist-option-eod_greeks.html)
â
â
### Real-Time Endpoint Access â
Endpoint
FREE
VALUE
STANDARD
PRO
Quote (https://http-docs.thetadata.us/operations/get-snapshot-option-quote.html)
â
â
â
Open Interest (https://http-docs.thetadata.us/operations/get-snapshot-option-open_interest.html)
â
â
â
OHLC (https://http-docs.thetadata.us/operations/get-snapshot-option-ohlc.html)
â
â
â
Trade (https://http-docs.thetadata.us/operations/get-snapshot-option-trade.html)
â
â
### Bulk Real-Time Endpoint Access â
A bulk snapshot allows you to request a snapshot every option contract to share the same symbol and expiration combination. The pro tier has the ability to specify
exp=0
in the request to
retrieve every option that shares the same symbol AKA an option root snapshot. (note: Any
exp=0
must be requested day by day)
Endpoint
FREE
VALUE
STANDARD
PRO
Bulk Quote (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-quote.html)
â
â
Bulk Open Interest (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-open_interest.html)
â
â
Bulk OHLC (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-ohlc.html)
â
â
Bulk Greeks First Order (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-greeks.html)
â
â
Bulk Greeks Second Order (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-greeks_second_order.html)
â
Bulk Greeks Third Order (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-greeks_third_order.html)
â
### Streaming Access â
The number of contracts that a tier can stream at the same time is defined below.
Stream
FREE
VALUE
STANDARD
PRO
# of streamable contracts for quotes (https://http-docs.thetadata.us/Streaming/US-Options/Quote-Stream.html)
0
0
10,000
15,000
# of streamable contracts for trades (https://http-docs.thetadata.us/Streaming/US-Options/Trade-Stream.html)
0
0
15,000
Unlimited (use the full trade stream)
Full trade Stream (https://http-docs.thetadata.us/Streaming/US-Options/Full-Trade-Stream.html)
â
## Index Data â
The resolution of the data is entirely dependent on the reporting exchange. For instance CBOE reports SPX every second. Indices from the Nasdaq Indices Feed are currently not supported. This includes
$NDX
.
If the previous reported price has not changed, there will be no new tick reported by Theta Data. For instance, if the price of SPX is $4000 at 9:31:00 and the price has not changed at 9:31:01, a new price message will not be available historically and in real-time. This is easy to work around as any "missing" historical price tick can be interpreted as the price did not change from the previous tick.
Tier
Granularity
First Access Date
Delay
Server Threads
FREE
EOD
2024-01-01
NO ACCESS
NO ACCESS
VALUE
15-minute
2023-01-01
15-minute
1
STANDARD
Lowest reported by venues
2022-01-01
real-time
2
PRO
Lowest reported by venues
2017-01-01
real-time
4
### Symbol Coverage â
Real-time / ongoing updates is available for all indices reported on the
CGIF (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html)
. This includes
SPX
and
VIX
. There is no support for NDX or any symbols on the Nasdaq Indices feed. Our near term plans are to generate synthetic indices data that will match the officially reported prices with a 99% accuracy. This synthetic pricing data will be available to indices data subscribers once available.
### Endpoint Access â
Endpoint
FREE
VALUE
STANDARD
PRO
EOD Report (https://http-docs.thetadata.us/operations/get-v2-hist-index-eod.html)
X
X
X
X
Price (https://http-docs.thetadata.us/operations/get-v2-hist-index-price.html)
X
X
X
Price Snapshot (https://http-docs.thetadata.us/operations/get-v2-hist-index-snapshot-price.html)
X
X
OHLC Snapshot (https://http-docs.thetadata.us/operations/get-v2-hist-index-snapshot-ohlc.html)
X
X
### Real Time Streaming Access â
The number of contracts a tier can stream at the same time is defined below. Indices price streaming uses real time data from the
CGIF (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html)
feed.
Stream
FREE
VALUE
STANDARD
PRO
# of streamable contracts for prices (https://http-docs.thetadata.us/Streaming/US-Indices/Price-Stream.html)
0
0
3
100


---

# Source: https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks.html

# Option-Greeks â
## Model â
Theta Data uses the Black Scholes for all Greeks calculations. More specifically, we use the formulas outlined
here (https://en.wikipedia.org/wiki/Greeks_(finance))
.
### Tick by Tick â
A tick is defined as a row of data. Theta Data calculates Greeks for each tick of data and uses the exact underlying tick (price) at the time of the option tick.
### Implied Volatility Guess â
We use a fast bisection method to calculate implied volatility. If a close to perfect solution does not exist, you will notice the
iv_error
value in Greeks requests will begin to increase. This happens with deep in the money or out of the money contracts. This behavior can be found with other models / data providers.
### Weird Values? â
Let us know, but before you do realize:
Rho & Vega must be divided by 100 to get their value.
We use the EU pricing model outlined above.
## Parameters â
### Dividends â
Theta Data currently ignores dividends, however you can specify
annual_div
parameter and Theta Data will use that as the annual dividend amount and calculate the dividend yield for each tick of data, which would then be plugged into the Black Scholes formula.
### Rates â
By default, Theta Data uses SOFR as its interest rate. SOFR is reported 1 day after the report date. Theta Data uses the last provided SOFR rate for current day data Greeks calculations. You can specify the
rate
parameter to override this behavior.


---

# Source: https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Quote-Conditions.html

## Quote Conditions â
Code
Name
Firm
Halted
0
REGULAR
x
1
BID_ASK_AUTO_EXEC
x
2
ROTATION
3
SPECIALIST_ASK
x
4
SPECIALIST_BID
x
5
LOCKED
x
6
FAST_MARKET
7
SPECIALIST_BID_ASK
x
8
ONE_SIDE
x
9
OPENING_QUOTE
10
CLOSING_QUOTE
11
MARKET_MAKER_CLOSED
12
DEPTH_ON_ASK
x
13
DEPTH_ON_BID
x
14
DEPTH_ON_BID_ASK
x
15
TIER_3
x
16
CROSSED
x
17
HALTED
x
18
OPERATIONAL_HALT
x
19
NEWS_OUT
x
20
NEWS_PENDING
x
21
NON_FIRM
22
DUE_TO_RELATED
x
23
RESUME
24
NO_MARKET_MAKERS
x
25
ORDER_IMBALANCE
x
26
ORDER_INFLUX
x
27
INDICATED
x
28
PRE_OPEN
29
IN_VIEW_OF_COMMON
x
30
RELATED_NEWS_OUT
x
32
ADDITIONAL_INFO
x
33
RELATED_ADD_INFO
x
34
NO_OPEN_RESUME
x
35
DELETED
x
36
REGULATORY_HALT
x
37
SEC_SUSPENSION
x
38
NON_COMLIANCE
x
39
FILINGS_NOT_CURRENT
x
40
CATS_HALTED
x
41
CATS
42
EX_DIV_OR_SPLIT
x
43
UNASSIGNED
44
INSIDE_OPEN
45
INSIDE_CLOSED
46
OFFER_WANTED
47
BID_WANTED
48
CASH
x
49
INACTIVE
x
50
NATIONAL_BBO
x
51
NOMINAL
x
52
CABINET
x
53
NOMINAL_CABINET
x
54
BLANK_PRICE
x
55
SLOW_BID_ASK
56
SLOW_LIST
x
57
SLOW_BID
58
SLOW_ASK
59
BID_OFFER_WANTED
60
SUBPENNY
61
NON_BBO
62
SPECIAL_OPEN
63
BENCHMARK
64
IMPLIED
65
EXCHANGE_BEST
66
MKT_WIDE_HALT_1
67
MKT_WIDE_HALT_2
68
MKT_WIDE_HALT_3
69
ON_DEMAND_AUCTION
70
NON_FIRM_BID
71
NON_FIRM_ASK
72
RETAIL_BID
73
RETAIL_ASK
74
RETAIL_QTE
Download as CSV (https://www.dropbox.com/scl/fi/w7ffjz81so3j2t2e587ag/QuoteConditions.csv?rlkey=l2nv6s01suswcxor3ljcqyq3d&dl=1)


---

# Source: https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html

## Trade Conditions â
Code
Name
Cancel
Late Report
Auto Executed
Open Report
Volume
High
Low
Last
Description
0
REGULAR
x
x
x
x
Regular Trade
1
FORM_T
x
Form T. Before and After Regular Hours. note: NYSE/AMEX previously used code 'T' for BurstBasket.
2
OUT_OF_SEQ
x
x
x
x
*
Report was sent Out Of Sequence. Updates last if it becomes only trade (if the trade reports before it are canceled, for example).
3
AVG_PRC
x
Average Price for a trade. NYSE/AMEX stocks. Nasdaq uses AvgPrc_Nasdaq-- main difference is NYSE/AMEX does not conditionally set high/low/last
4
AVG_PRC_NASDAQ
x
Average Price. Nasdaq stocks. Similar to AvgPrc, but does not set high/low/last.
5
OPEN_REPORT_LATE
x
x
x
x
*
NYSE/AMEX. Market opened Late. Here is the report. It may not be in sequence. Nasdaq uses OpenReportOutOfSeq. *update last if only trade.
6
OPEN_REPORT_OUT_OF_SEQ
x
x
x
x
Report IS out of sequence. Market was open, and now this report is just getting to us.
7
OPEN_REPORT_IN_SEQ
x
x
x
x
x
Opening report. This is the first price.
8
PRIOR_REFERENCE_PRICE
x
x
x
x
*
Trade references price established earlier. *Update last if this is the only trade report.
9
NEXT_DAY_SALE
x
NYSE/AMEX:Next Day Clearing. Nasdaq: Delivery of Securities and payment one to four days later.*As of September 5, 2017, the NYSE will no longer accept orders with Cash, Next Day or Seller's Option instructions.
10
BUNCHED
x
x
x
x
Aggregate of 2 or more Regular trades at same price within 60 seconds and each trade size not greater than 10,000.
11
CASH_SALE
x
Delivery of securities and payment on the same day.*As of September 5, 2017, the NYSE will no longer accept orders with Cash, Next Day or Seller's Option instructions.
12
SELLER
x
Stock can be delivered up to 60 days later as specified by the seller. After 1995, the number of days can be greater than 60. note: delivery of 3 days would be considered a regular trade.*As of September 5, 2017, the NYSE will no longer accept orders with Cash, Next Day or Seller's Option instructions.
13
SOLD_LAST
x
x
x
x
*
Late Reporting. *Sets Consolidated Last if no other qualifying Last, or same Exchange set previous Trade, or Exchange is Listed Exchange.
14
RULE_127
x
x
x
x
NYSE only. Rule 127 basically denotes the trade was executed as a block trade.
15
BUNCHED_SOLD
x
x
x
x
*
Several trades were bunched into one trade report, and the report is late. *Update last if this is first trade.
16
NON_BOARD_LOT
x
Size of trade is less than a board lot (oddlot). A board lot is usually 1,00 shares. Note this is Canadian markets.
17
POSIT
x
x
x
POSIT Canada is an electronic order matching system that prices trades at the mid-point of the bid and ask in the continuous market.
18
AUTO_EXECUTION
x
x
x
x
x
Transaction executed electronically. Soley for information. Only found in OPRA -- options trades, and quite common.
19
HALT
Temporary halt in trading in a particular security for one or more participants.
20
DELAYED
x
Indicates a delayed opening
21
REOPEN
x
x
x
x
Reopening of a contract that was previously halted.
22
ACQUISITION
x
x
x
x
Transaction on exchange as a result of an Exchange Acquisition
23
CASH_MARKET
x
x
x
x
Cash only Market. All trade reports for this session will be settled in cash. note: differs from CashSale in that the trade marked as CashSale is an exception -- that is, most trades are settled using regular conditions.
24
NEXT_DAY_MARKET
x
x
x
x
Next Day Only Market. All trades reports for this session will be settled the next day. Note: differs from NextDay in that the trade marked as NextDay is an exception -- that is, most trades are settled using regular conditions.
25
BURST_BASKET
x
x
x
x
Specialist bought or sold this stock as part of an execution of a specific basket of stocks.
26
OPEN_DETAIL
x
107-113, 130, 160 Deleted an existing Sale Condition (Note: the code may be repurposed at a future date): 'G' - 'Opening/Reopening Trade Detail'. This trade is one of several trades that made up the open report trade. Often the open report has a large size which was made up of orders placed overnight. After trading has commenced, the individual trades of the open report trade are sent with this condition. Note it doesn't update volume, high, low, or last because it's already been accounted for in the open report.
27
INTRA_DETAIL
x
This trade is one of several trades that made up a previous trade. Similar to OpenDetail but refers to a trade report that was not the opening trade report.
28
BASKET_ON_CLOSE
x
x
A trade consisting of a paired basket order to be executed based on the closing value of an index. These trades are reported after the close when the index closing value is known.
29
RULE_155
x
x
x
x
AMEX only rule 155. Sale of block at one
clean-up
 price.
30
DISTRIBUTION
x
x
x
x
Sale of a large block of stock in a way that price is not adversely affected.
31
SPLIT
x
x
x
x
Execution in 2 markets when the specialist or MM in the market first receiving the order agrees to execute a portion of it at whatever price is realized in another market to which the balance of the order is forwarded for execution.
32
REGULAR_SETTLE
x
x
x
x
RegularSettle
33
CUSTOM_BASKET_CROSS
x
One of two types:2 paired but seperate orders in which a market maker or member facilitates both sides of a remaining portion of a basket. A split basket plus an entire basket where the market maker or member facilitates the remaining shares of the split basket.
34
ADJ_TERMS
x
x
x
x
Terms have been adjusted to reflect stock split/dividend or similar event.
35
SPREAD
x
x
x
x
Spread between 2 options in the same options class.
36
STRADDLE
x
x
x
x
Straddle between 2 options in the same options class.
37
BUY_WRITE
x
x
x
x
This is the option part of a covered call.
38
COMBO
x
x
x
x
A buy and a sell in 2 or more options in the same class.
39
STPD
x
x
x
x
Traded at price agreed upon by the floor following a non-stopped trade of the same series at the same price.
40
CANC
x
Cancel a previously reported trade - it will not be the first or last trade record. note: If the most recent report is Out of seq, SoldLast, or a type that does not qualify to set the last, that report can be considered in processing the cancel.
41
CANC_LAST
x
Cancel the most recent trade report that is qualified to set the last.
42
CANC_OPEN
x
Cancel the opening trade report.
43
CANC_ONLY
x
Cancel the only trade report. There is only one trade report, cancel it.
44
CANC_STPD
x
Cancel the trade report that has the condition STPD.
45
MATCH_CROSS
x
x
x
x
CTS and UTP: Cross Trade. A Cross Trade a trade transaction resulting from a market center's crossing session.
46
FAST_MARKET
x
x
x
x
Term used to define unusually hectic market conditions.
47
NOMINAL
x
x
x
x
Nominal price. A calculated price primarily generated to represent the fair market value of an inactive instrument for the purpose of determining margin requirements and evaluating position risk. Common in futures and futures options.
48
CABINET
x
A trade in a deep out-of-the-money option priced at one-half the tick value. Used by options traders to liquidate positions.
49
BLANK_PRICE
Sent by an exchange to blank out the associated price (bid, ask or trade).
50
NOT_SPECIFIED
An unspecified (generalized) condition.
51
MC_OFFICIAL_CLOSE
The
Official
 closing value as determined by a Market Center.
52
SPECIAL_TERMS
x
x
x
x
Indicates that all trades executed will be settled in other than the regular manner.
53
CONTINGENT_ORDER
x
x
x
x
The result of an order placed by a Participating Organization on behalf of a client for one security and contingent on the execution of a second order placed by the same client for an offsetting volume of a related security.
54
INTERNAL_CROSS
x
x
x
x
A cross between two client accounts of a Participating Organization which are managed by a single firm acting as portfolio manager with discretionary authority to manage the investment portfolio granted by each of the clients. This was originally from Toronto Stock Exchange (TSX). Information located here.
55
STOPPED_REGULAR
x
x
x
x
Stopped Stock  Regular Trade.
56
STOPPED_SOLD_LAST
x
x
x
TStopped Stock  SoldLast Trade
57
STOPPED_OUT_OF_SEQ
x
x
x
Stopped Stock -- Out of Sequence.
58
BASIS
x
x
x
x
A transaction involving a basket of securities or an index participation unit that is transacted at prices achieved through the execution of related exchange-traded derivative instruments, which may include index futures, index options and index participation units in an amount that will correspond to an equivalent market exposure.
59
VWAP
x
Volume Weighted Average Price. A transaction for the purpose of executing trades at a volume-weighted average price of the security traded for a continuous period on or during a trading day on the exchange.
60
SPECIAL_SESSION
x
Occurs when an order is placed by a purchase order on behalf of a client for execution in the Special Trading Session at the last sale price.
61
NANEX_ADMIN
Used to make volume and price corrections to match official exchange values.
62
OPEN_REPORT
x
x
x
Indicates an opening trade report.
63
MARKET_ON_CLOSE
x
x
x
x
The
Official
 closing value as determined by a Market Center.
64
SETTLE_PRICE
Settlement Price
65
OUT_OF_SEQ_PRE_MKT
x
x
An out of sequence trade that exectuted in pre or post market -- a combination of FormT and OutOfSeq.
66
MC_OFFICIAL_OPEN
Indicates the 'Official' opening value as determined by a Market Center. This transaction report will contain the market center generated opening price.
67
FUTURES_SPREAD
x
x
x
x
Execution was part of a spread with another futures contract.
68
OPEN_RANGE
x
x
Two trade prices are used to indicate an opening range representing the high and low prices during the first 30 seconds or so of trading.
69
CLOSE_RANGE
x
x
Two trade prices are used to indicate an opening range representing the high and low prices during the last 30 seconds or so of trading.
70
NOMINAL_CABINET
Nominal Cabinet
71
CHANGING_TRANS
x
x
x
x
Changing Transaction
72
CHANGING_TRANS_CAB
Changing Cabinet Transaction
73
NOMINAL_UPDATE
Nominal price update
74
PIT_SETTLEMENT
Sent with a "pit session" settlement price to the electronic session, for the purpose of computing net change from the next day electronic session and the prior session settlement price.
75
BLOCK_TRADE
x
x
x
x
An executed trade of a large number of shares, typically 10,000 shares or more.
76
EXG_FOR_PHYSICAL
x
x
x
x
Exchange Future for Physical
77
VOLUME_ADJUSTMENT
x
An adjustment made to the cumulative trading volume for a trading session.
78
VOLATILITY_TRADE
x
x
x
x
Volatility trade
79
YELLOW_FLAG
x
x
x
x
Appears when reporting exchnge may be experiencing technical difficulties.
80
FLOOR_PRICE
x
x
x
x
Distinguishes a floor Bid/Ask from a member Bid Ask on LME
81
OFFICIAL_PRICE
x
x
x
x
Official bid/ask price used by LME.
82
UNOFFICIAL_PRICE
x
x
x
x
Unofficial bid/ask price used by LME.
83
MID_BID_ASK_PRICE
x
x
x
x
A price halfway between the bid and ask on LME.
84
END_SESSION_HIGH
x
End of Session High Price.
85
END_SESSION_LOW
x
End of Session Low Price.
86
BACKWARDATION
x
x
x
x
A condition where the immediate delivery price is higher than the future delivery price. Opposite of Contango.
87
CONTANGO
x
x
x
x
A condition where the future delivery price is higher than the immediate delivery price. Opposite of Backwardation.
88
HOLIDAY
x
x
x
x
In Development
89
PRE_OPENING
x
The period of time prior to the market opening time (7:00 A.M. - 9:30 A.M.) during which orders are entered into the market for the Opening.
90
POST_FULL
91
POST_RESTRICTED
92
CLOSING_AUCTION
93
BATCH
94
TRADING
95
INTERMARKET_SWEEP
x
x
x
x
A trade resulting from an Intermarket Sweep Order Execution. For more information on intermarket sweeps, please see the SEC NMS regulation (June 29, 2005 - PDF).From that report:"The intermarket sweep exception enables trading centers that receive sweep orders to execute those orders immediately, without waiting for betterpriced quotations in other markets to be updated."
96
DERIVATIVE
x
x
x
*
Derivatively priced.
97
REOPENING
x
x
x
x
Market center re-opening prints.
98
CLOSING
x
x
x
*
Market center closing prints. Can be used to get closing auction information for exchanges that report it, such as NYSE.
99
CAPELECTION
x
x
x
CTA Docs 78, 110, 111, 113 & 136 Redefined: Existing code 'I' in the Sale Condition field to denote the following change in value: From - Cap Election Trade To - Odd Lot Trade. A trade resulting from an sweep execution where CAP orders were elected and executed outside the best bid or affer and appear as repeat trades. DEL
100
SPOT_SETTLEMENT
x
x
x
x
101
BASIS_HIGH
x
x
x
102
BASIS_LOW
x
x
x
103
YIELD
Applies to bid and ask yield updates for Cantor Treasuries
104
PRICE_VARIATION
105
CONTINGENT_TRADE
x
Effective July 2015 ~ A Sale Condition used to identify a transaction where the execution of the transaction is contingent upon some event.SIAC Trader Update: February 25, 2015 (PDF) Previously: StockOption
106
STOPPED_IM
x
x
x
Transaction order which was stopped at a price that did not constitute a Trade-Through on another market. Valid trade do not update last
107
BENCHMARK
x
This condition will be assigned for Tapes A/B and UTP when no Trade Through Exempt reason is given, and the Trade Through Exempt indicator is set. For Tapes A/B and UTP, these trades are eligible to update O/H/L/L/V. For OPRA, these trades only update volume.
108
TRADE_THRU_EXEMPT
x
This condition will be assigned for Tapes A/B and UTP when no Trade Through Exempt reason is given, and the Trade Through Exempt indicator is set. For Tapes A/B and UTP, these trades are eligible to update O/H/L/L/V. For OPRA, these trades only update volume.
109
IMPLIED
x
These trades are result of a spread trade. The exchange sends a leg price on each future for spread transactions. These trades do not update O/H/L/L but they update volume. We are now sending these spread trades for Globex exchanges: CME, NYMEX, COMEX, CBOT, MGE, KCBT and DME.
110
OTC
111
MKT_SUPERVISION
112
RESERVED_77
113
RESERVED_91
114
CONTINGENT_UTP
115
ODD_LOT
x
This indicates any trade with size between 1-99.
116
RESERVED_89
117
CORRECTED_CS_LAST
x
x
x
This allows for a mechanism to correct the official close on the consolidated tape.
118
OPRA_EXT_HOURS
OPRA extended trading hours session. Equivalent to the OPRA "Session Indicator" with ASCII value of 'X' (Pre-Market extended hours trading session)(Obselete, see condition 148).
119
RESERVED_78
120
RESERVED_81
121
RESERVED_84
122
RESERVED_878
123
RESERVED_90
124
QUALIFIED_CONTINGENT_TRADE
x
Effective July 2015 ~ A transaction consisting of two or more component orders, executed as agent or principal, that meets each of the following elements: At least one component order is for an NMS stock. All components are effected with a product or price contingency that either has been agreed to by the respective counterparties or arranged for by a broker-dealer as principal or agent. The execution of one component is contingent upon the execution of all other components at or near the same time. The specific relationship between the component orders (e.g. the spread between the prices of the component orders) is determined at the time the contingent order is placed. The component orders bear a derivative relationship to one another, represent different classes of shares of the same issuer, or involve the securities of participants in mergers or with intentions to
125
SINGLE_LEG_AUCTION_NON_ISO
x
x
x
x
Transaction was the execution of an electronic order which was "stopped" at a price and traded in a two sided auction mechanism that goes through an exposure period. Such auctions mechanisms include and not limited to Price Improvement, Facilitation or Solicitation Mechanism.
126
SINGLE_LEG_AUCTION_ISO
x
x
x
x
Transaction was the execution of an Intermarket Sweep electronic order which was "stopped" at a price and traded in a two sided auction mechanism that goes through an exposure period. Suchauctions mechanisms include and not limited to Price Improvement, Facilitation or Solicitation Mechanism marked as ISO.
127
SINGLE_LEG_CROSS_NON_ISO
x
x
x
x
Transaction was the execution of an electronic order which was "stopped" at a price and traded in a two sided crossing mechanism that does not go through an exposure period. Such crossing mechanisms include and not limited to Customer to Customer Cross and QCC with a single option leg.
128
SINGLE_LEG_CROSS_ISO
x
x
x
x
Transaction was the execution of an Intermarket Sweep electronic order which was "stopped" at a price and traded in a two sided crossing mechanism that does not go through an exposure period. Such crossing mechanisms include and not limited to Customer to Customer Cross.
129
SINGLE_LEG_FLOOR_TRADE
x
x
x
x
Transaction represents a non-electronic trade executed on a trading floor. Execution of Paired and Non-Paired Auctions and Cross orders on an exchange floor are also included in this category.
130
MULTI_LEG_AUTOELEC_TRADE
x
x
x
x
Transactionrepresents an electronic execution of a multi leg order traded in a complex order book.
131
MULTI_LEG_AUCTION
x
x
x
x
Transaction was the execution of an electronic multi leg order which was "stopped" at a price and traded in a two sided auction mechanism that goes through an exposure period in a complex order book. Such auctions mechanisms include and not limited to Price Improvement, Facilitation or Solicitation Mechanism.
132
MULTI_LEG_CROSS
x
x
x
x
Transaction was the execution of an electronic multi leg order which was "stopped" at a price and traded in a two sided crossing mechanism that does not go through an exposure period. Such crossing mechanisms include and not limited to Customer to Customer Cross and QCC with two or more options legs.
133
MULTI_LEG_FLOOR_TRADE
x
x
x
x
Transaction represents a non-electronic multi leg order trade executed against other multi-leg order(s) on a trading floor. Execution of Paired and Non-Paired Auctions and Cross orders on an exchange floor are also included in this category.
134
ML_AUTO_ELEC_TRADE_AGSL
x
x
x
x
Transaction represents an electronic execution of a multi Leg order traded against single leg orders/quotes.
135
STOCK_OPTIONS_AUCTION
x
x
x
x
Transaction was the execution of an electronic multi leg stock/options order which was "stopped" at a price and traded in a two sided auction mechanism that goes through an exposure period in a complex order book. Such auctions mechanisms include and not limited to Price Improvement, Facilitation or Solicitation Mechanism.
136
ML_AUCTION_AGSL
x
x
x
x
Transaction was the execution of an electronic multi leg order which was "stopped" at a price and traded in a two sided auction mechanism that goes through an exposure period and trades against single leg orders/ quotes. Such auctions mechanisms include and not limited to Price Improvement, Facilitation or Solicitation Mechanism.
137
ML_FLOOR_TRADE_AGSL
x
x
x
x
Transaction represents a non-electronic multi leg order trade executed on a trading floor against single leg orders/ quotes. Execution of Paired and Non-Paired Auctions on an exchange floor are also included in this category.
138
STK_OPT_AUTO_ELEC_TRADE
x
x
x
x
Transaction represents an electronic execution of a multi leg stock/options order traded in a complex order book.
139
STOCK_OPTIONS_CROSS
x
x
x
x
Transaction was the execution of an electronic multi leg stock/options order which was "stopped" at a price and traded in a two sided crossing mechanism that does not go through an exposure period. Such crossing mechanisms include and not limited to Customer to Customer Cross.
140
STOCK_OPTIONS_FLOOR_TRADE
x
x
x
x
Transaction represents a non-electronic multi leg order stock/options trade executed on a trading floor in a Complex order book. Execution of Paired and Non-Paired Auctions and Cross orders on an exchange floor are also included in this category.
141
STK_OPT_AE_TRD_AGSL
x
x
x
x
Transaction represents an electronic execution of a multi Leg stock/options order traded against single leg orders/quotes.
142
STK_OPT_AUCTION_AGSL
x
x
x
x
Transaction was the execution of an electronic multi leg stock/options order which was "stopped" at a price and traded in a two sided auction mechanism that goes through an exposure periodand trades against single leg orders/ quotes. Such auctions mechanisms include and not limited to Price Improvement, Facilitation or Solicitation Mechanism.
143
STK_OPT_FLOOR_TRADE_AGSL
x
x
x
x
Transaction represents a non-electronic multi leg stock/options order trade executed on a trading floor against single leg orders/ quotes. Execution of Paired and Non-Paired Auctions on an exchange floor are also included in this category.
144
ML_FLOOR_TRADE_OF_PP
x
x
x
x
Transaction represents execution of a proprietary product non-electronic multi leg order with at least 3 legs. The trade price may be outside the current NBBO.
145
BID_AGGRESSOR
x
x
x
x
Aggressor of the trade is on the buy side.
146
ASK_AGGRESSOR
x
x
x
x
Aggressor of the trade is on the sell side.
147
MULTILAT_COMP_TR_PDP
x
Transaction represents an execution in a proprietary product done as part of a multilateral compression. Trades are executed outside of regular trading hours at prices derived from end of day markets.
148
EXTENDED_HOURS_TRADE
x
Transaction represents a trade that was executed outside of regular market hours.
Download as CSV (https://www.dropbox.com/scl/fi/3szkrv7970em6ejdkh85e/TradeConditions.csv?rlkey=br10yr3ikfkkjowchp4zo4ui1&dl=1)


---

# Source: https://http-docs.thetadata.us/Excel/Options.html

Fetch information about options from Theta Data.
Subscription Required
You must have a
Standard or Pro Theta Data subscription (https://www.thetadata.net/subscribe)
, and
Theta Data terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
running to use this Excel add-in!
## OPTIONS_SNAPSHOT â
Real-time options data.
Parameters
req_type
- The type of the request (see below).
root
- Optional ticker symbol for the security; all tickers if not provided.
[
exp
] - Expiration for the option. Defaults to all expirations if omitted.
[
strike
] The strike price of the underlying option. Defaults to all strikes if omitted.
[
right
] C for CALL; P for PUT.
### Snapshot Request Types â
quote
- Retrieve a real-time last NBBO quote of an option contract.
ohlc
- Retrieve a real-time last ohlc of an option contract for the trading day.
trade
- Retrieve the real-time last trade of an option contract.
open_interest
- Retrieve the last open interest message of an option contract.
greeks
- Retrieve a real-time last greeks calculation for all option contracts that lie on a provided expiration.
greeks_second_order
- Retrieve a real-time last second order greeks calculation for all option contracts that lie on a provided expiration.
greeks_third_order
- Retrieve a real-time last third order greeks calculation for all option contracts that lie on a provided expiration.
## OPTIONS_AT_TIME â
Stock data at a specific millisecond of the day.
Parameters
req_type
- The type of the request (see below).
start_date
- The start date (inclusive) of the request formatted as
YYYY-MM-DD
.
end_date
- The end date (inclusive) of the request formatted as
YYYY-MM-DD
.
ivl
- The milliseconds since
00:00:00.000
ET. The function will return the last row of data prior to this timestamp.
root
- Underlying ticker symbol for the security.
[
exp
] - Expiration for the option. Defaults to all expirations if omitted.
[
strike
] The strike price of the underlying option. Defaults to all strikes if omitted.
[
right
] C for CALL; P for PUT.
### At-Time Request Types â
quote
- Retrieve the last NBBO quote reported by OPRA at a specified millisecond of the day.
trade
- Retrieve the last trade reported by OPRA at a specified millisecond of the day.
greeks
- Retrieve the greeks calculated at the specified millisecond of the day.
greeks_second_order
- Retrieve the second order greeks calculated at the specified millisecond of the day.
greeks_third_order
- Retrieve the third order greeks calculated at the specified millisecond of the day.
## OPTIONS_HISTORY â
CAUTION
Requests for greeks or tick data using
ivl=0
may return too much data for Excel to handle.
Historic options data.
Parameters
req_type
- The type of the request (see below).
start_date
- The start date (inclusive) of the request formatted as
YYYY-MM-DD
.
end_date
- The end date (inclusive) of the request formatted as
YYYY-MM-DD
.
ivl
- The interval size in milliseconds. Setting it to 0 will provide tick-level data instead of aggregated data.
root
- Underlying ticker symbol for the security.
[
exp
] - Expiration for the option. Defaults to all expirations if omitted.
[
strike
] The strike price of the underlying option. Defaults to all strikes if omitted.
[
right
] C for CALL; P for PUT.
### History Request Types â
ohlc
- Aggregated OHLC bars that use SIP rules for each bar.
eod
- Theta Data generated national EOD report.
quote
- Retrieve every NBBO quote reported by OPRA.
open_interest
- Retrieve the open interest reported at the end of the previous trading day.
trade
- Retrieve every trade reported by OPRA.
trade_quote
- Retrieve every trade reported by OPRA paired with the last NBBO quote reported by OPRA at the time of trade.
all_greeks
- Retrieve the all greeks calculated using the option and underlying midpoint price.
eod_greeks
- Retrieve the greeks calculated using Theta Data's EOD report, and the option and underlying closing price.
implied_volatility
- Retrieve implied volatility calculated using the national best bid, mid, and ask price of the option respectively.
greeks
- Retrieve the greeks calculated using the option and underlying midpoint price.
greeks_second_order
- Retrieve the second order greeks calculated using the option and underlying midpoint price.
greeks_third_order
- Retrieve the third order greeks calculated using the option and underlying midpoint price.
trade_greeks_second_order
- Retrieve every trade reported by OPRA and the associated second order greeks.
trade_greeks_third_order
- Retrieve ever trade reported by OPRA and the associated third order greeks.


---

# Source: https://http-docs.thetadata.us/Streaming/Getting-Started.html

## Setup â
The Theta Terminal is required to use Theta Data's WebSockets. The Theta Terminal uses a highly compressed protocol to ensure minimal bandwidth consumption and low latency data transmission. Please follow the
getting started article (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html)
to get the Theta Terminal running.
A
Theta Data subscription (https://thetadata.net/subscribe)
is required to access data. Streaming requests won't return any data if you do not have permissions to stream the data.
## Prerequisites â
Familiarity with Websockets in the programming language of your choice. Sample code for some language may be provided.
Requests and event messages are in JSON. The ability to parse that data is required.
The Theta Terminal must be running.
## Dev FPSS for Development â
While you're developing, it is possible that the market may be closed. This means that there aren't any new trades or quotes are generated by the exchanges. You will not be able to test streaming effectively unless the market is open or you are using our dev server. We recommend switching to our dev environment for development since there are always messages being sent to the Theta Terminal. The dev server does an infinite loop replay of a single day of data. The replaying of the data is done as fast as possible, meaning there are more messages per second being sent to the Theta Terminal than there would be by streaming on the production server.
NOTES
The dev FPSS server replays data from a random trading day in the past. Some contracts might be expired or not exist yet that you attempt to stream.
### Switch to Dev FPSS â
Set the following value in your
config file (https://http-docs.thetadata.us/Articles/Performance-And-Tuning/The-Config-file.html)
:
Dev
```text
FPSS_REGION=FPSS_DEV_HOSTS
```
Production
```text
FPSS_REGION=FPSS_NJ_HOSTS
```
Stage
```text
FPSS_REGION=FPSS_STAGE_HOSTS
```
REQUIRED
Theta Terminal v1.6.0 (https://download-unstable.thetadata.us)
or higher is required to access the development server.
## Mechanics â
Theta Terminal connects to
FPSS (https://http-docs.thetadata.us/Articles/Getting-Started/Introduction.html#terminology)
to receive streamable messages. All stream messages will be sent to the endpoint below:
```text
ws://127.0.0.1:25520/v1/events
```
You must also connect to this same endpoint to send streaming requests. You cannot have multiple connections to this endpoint. There should be a single connection to this endpoint in which you receive all messages send by Theta Data. It is up to the user to distribute these messages to other threads or processes. There are plans to add terminal-side splitting of messages over different endpoints in the near future.
## Stream Messages â
### Header â
Each message received will contain a header object that describes the type of message and the connectivity status of the Theta Terminal to
FPSS (https://http-docs.thetadata.us/Articles/Getting-Started/Introduction.html#terminology)
.
json
```text
{

    "header"
: {

        "status"
:
"CONNECTED"
,

        "type"
:
"QUOTE"
,

...
```
### Status Messages â
A status messages is sent over the connection every second to keep the connection alive.
json
```text
{

  "header"
: {

    "status"
:
"CONNECTED"
,

    "type"
:
"STATUS"

  }

}
```
### Contract â
Stream messages that are of type
QUOTE
and
TRADE
will contain a contract object. For options, the strike price is in 1/10th of a cent. This means that a $140 strike price is represented as
140000
.
json
```text
{

    "header"
: {

        "status"
:
"CONNECTED"
,

        "type"
:
"QUOTE"

    },

    "contract"
: {

        "security_type"
:
"OPTION"
,

        "root"
:
"TTWO"
,

        "expiration"
:
20231103
,

        "strike"
:
140000
,

        "right"
:
"C"

    },

...
```


---

# Source: https://http-docs.thetadata.us/Streaming/Stop-All-Streams.html

# Stop-All-Streams â
REQUIRED
Theta Terminal 1.5.6 Revision A or higher is required.
You can stop all streaming subscriptions associated with your connection to FPSS by sending the payload below to
ws://127.0.0.1:25520/v1/events
.
json
```text
{

  "msg_type"
:
"STOP"

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Indices/Price-Stream.html

REQUIRED
A Theta Data
Index Standard Subscription (https://thetadata.net/subscribe)
is required to use this endpoint.
# Price Stream â
## Behavior â
This stream returns every price change for a specified symbol reported on the
CBOE CGIF (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#cboe-global-indices-feed)
feed. The Theta Terminal will continue to receive these messages unless it is terminated or you
unsubscribe (#unsubscribe-from-the-price-stream)
from the full price stream.
NOTE
The
trade object (#sample-output)
only the price field is updated and only reported if price has changed since last report. Indices are typically reported once every 1-second or few seconds. There is normally no 9:30:00 index price report, only 9:30:01.
## Subscribe to Price Stream â
The
id
field should be increased for each new stream request made. This ID is returned in a later message to verify that the request to stream trades was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
Failure to increment the ID for each request will prevent the terminal from automatically resubscribing to streams you previously requested.
### Contract Parameter â
The contract in the payload example below is subscribing to all prices for SPX stock.
### Payload â
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"INDEX"
,

  "req_type"
:
"TRADE"
,

  "add"
:
true
,

  "id"
:
0
,

  "contract"
: {

    "root"
:
"SPX"

  }

}
```
### Sample Code â
REQUIRED
The
Theta Terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
must be running for this code to work.
Python
```text
import
 asyncio

import
 websockets

# This code has only been tested on Python 3.11. Other versions might require adjustments.

async
 def
 stream_prices
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM'

        req[
'sec_type'
]
=
 'INDEX'

        req[
'req_type'
]
=
 'TRADE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        req[
'contract'
]
=
 {}

        req[
'contract'
][
'root'
]
=
 "SPX"

        await
 websocket.send(req.
__str__
())

        while
 True
:

            response
=
 await
 websocket.recv()

            print
(response)

asyncio.get_event_loop().run_until_complete(stream_prices())
```
## Unsubscribe from the Price Stream â
Changing the
add
field in the payload from
true
to
false
will end the price stream subscription.
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"INDEX"
,

  "req_type"
:
"TRADE"
,

  "add"
:
false
,

  "id"
:
1
,

  "contract"
: {

    "root"
:
"SPX"

  }

}
```
## Sample output â
The
condition (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
and
exchange (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Exchanges.html)
values correspond to their respective Enums.
We use the trade object to represent price reports and every other field aside from price can be ignored.
Download 1 minute sample data (https://http-docs.thetadata.us/index_price_sample.txt)
json
```text
{

  "header"
: {

    "type"
:
"TRADE"
,

    "status"
:
"CONNECTED"

  },

  "contract"
: {

    "security_type"
:
"INDEX"
,

    "root"
:
"SPX"

  },

  "trade"
: {

    "ms_of_day"
:
51952000
,

    "sequence"
:
0
,

    "size"
:
0
,

    "condition"
:
0
,

    "price"
:
5333.39
,

    "exchange"
:
5
,

    "date"
:
20240809

  }

}
```
json
```text
{

  "header"
: {

    "type"
:
"OHLC"
,

    "status"
:
"CONNECTED"

  },

  "contract"
: {

    "security_type"
:
"INDEX"
,

    "root"
:
"SPX"

  },

  "ohlc"
: {

    "ms_of_day"
:
51952000
,

    "open"
:
5314.66
,

    "high"
:
5358.67
,

    "low"
:
5300.84
,

    "close"
:
5333.39
,

    "volume"
:
0
,

    "count"
:
1135013
,

    "date"
:
20240809

  }

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Options/Full-Trade-Stream.html

REQUIRED
A Theta Data
Options Pro Subscription (https://thetadata.net/subscribe)
is required to use this endpoint.
# Full Trade Stream â
## Behavior â
This stream returns every US Option trade reported on the
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#options-opra)
feed. A quote (the last NBBO) and ohlc message for the contract that was traded is sent before the trade occurs. The next 2 NBBO quotes for that contract are also sent over the stream using the
QUOTE
stream message type after the contract is traded. The Theta Terminal will continue to receive these messages unless it is terminated or you
unsubscribe (#unsubscribe-from-the-full-trade-stream)
from the full trade stream.
## Subscribe to the Full Trade Stream â
The
id
field should be increased for each new stream request made. This ID is returned in a later message to verify that the request to stream trades was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
Failure to increment the ID for each request will prevent the terminal from automatically resubscribing to streams you previously requested.
### Payload â
json
```text
{

  "msg_type"
:
"STREAM_BULK"
,

  "sec_type"
:
"OPTION"
,

  "req_type"
:
"TRADE"
,

  "add"
:
true
,

  "id"
:
0

}
```
### Sample Code â
REQUIRED
The
Theta Terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
must be running for this code to work.
Python
```text
import
 asyncio

import
 websockets

# This code has only been tested on Python 3.11. Other versions might require adjustments.

async
 def
 stream_trades
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM_BULK'

        req[
'sec_type'
]
=
 'OPTION'

        req[
'req_type'
]
=
 'TRADE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        await
 websocket.send(req.
__str__
())

        while
 True
:

            response
=
 await
 websocket.recv()

            print
(response)

asyncio.get_event_loop().run_until_complete(stream_trades())
```
Go
```text
package
 main

import
 (

	"
encoding/json
"

	"
fmt
"

	"
log
"

	"
net/url
"

	"
os
"

	"
os/signal
"

	"
syscall
"

	"
github.com/gorilla/websocket
"

)

type
 InitialMessage
 struct
 {

	MsgType
string
 `json:"msg_type"`

	SecType
string
 `json:"sec_type"`

	ReqType
string
 `json:"req_type"`

	Add
bool
   `json:"add"`

	ID
int
    `json:"id"`

}

func
 main
() {

	interrupt
:=
 make
(
chan
 os
.
Signal
,
1
)

	signal.
Notify
(interrupt, os.Interrupt, syscall.SIGTERM)

	u
:=
 url
.
URL
{Scheme:
"ws"
, Host:
"127.0.0.1:25520"
, Path:
"/v1/events"
}

	log.
Printf
(
"connecting to
%s
"
, u.
String
())

	c, _, err
:=
 websocket.DefaultDialer.
Dial
(u.
String
(),
nil
)

	if
 err
!=
 nil
 {

		log.
Fatal
(
"dial:"
, err)

	}

	defer
 c.
Close
()

	done
:=
 make
(
chan
 struct
{})

	go
 func
() {

		defer
 close
(done)

		for
 {

			_, message, err
:=
 c.
ReadMessage
()

			if
 err
!=
 nil
 {

				log.
Println
(
"read:"
, err)

				return

			}

			fmt.
Printf
(
"
%s\n
"
, message)

		}

	}()

	initialMessage
:=
 InitialMessage
{

		MsgType:
"STREAM_BULK"
,

		SecType:
"OPTION"
,

		ReqType:
"TRADE"
,

		Add:
true
,

		ID:
0
,

	}

	msg, err
:=
 json.
Marshal
(initialMessage)

	if
 err
!=
 nil
 {

		log.
Println
(
"error in marshalling:"
, err)

		return

	}

	err
=
 c.
WriteMessage
(websocket.TextMessage, msg)

	if
 err
!=
 nil
 {

		log.
Println
(
"write:"
, err)

		return

	}

	for
 {

		select
 {

		case
 <-
done:

			return

		case
 <-
interrupt:

			log.
Println
(
"interrupt"
)

			err
:=
 c.
WriteMessage
(websocket.CloseMessage, websocket.
FormatCloseMessage
(websocket.CloseNormalClosure,
""
))

			if
 err
!=
 nil
 {

				log.
Println
(
"write close:"
, err)

				return

			}

			<-
done

			return

		}

	}

}
```
## Unsubscribe from the Full Trade Stream â
Changing the
add
field in the payload from
true
to
false
will end the full trade stream subscription.
json
```text
{

  "msg_type"
:
"STREAM_BULK"
,

  "sec_type"
:
"OPTION"
,

  "req_type"
:
"TRADE"
,

  "add"
:
false
,

  "id"
:
1

}
```
## Sample output â
The
right
field in the
contract
object will be set to
C
for a call and
P
for a put.
The
condition (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
and
exchange (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Exchanges.html)
values correspond to their respective Enums.
The strike price is in 1/10th of a cent. This means that a $140 strike price is represented as
140000
.
The
trade sequence (https://http-docs.thetadata.us/Articles/Data-And-Requests/Making-Requests.html#trade-sequences)
article might be a valuable resource.
Download 1 minute sample data (https://http-docs.thetadata.us/option_trade_sample.zip)
json
```text
{

  "header"
: {

    "status"
:
"CONNECTED"
,

    "type"
:
"TRADE"

  },

  "contract"
: {

    "security_type"
:
"OPTION"
,

    "root"
:
"QQQ"
,

    "expiration"
:
20231110
,

    "strike"
:
360000
,

    "right"
:
"P"

  },

  "trade"
: {

    "ms_of_day"
:
49531278
,

    "sequence"
:
-563040482
,

    "size"
:
5
,

    "condition"
:
18
,

    "price"
:
1.06
,

    "exchange"
:
65
,

    "date"
:
20231103

  }

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Options/Python-Example.html

# Full-Trade-Stream-Latency-Test â
This code assumes your machine is using the EST timezone. We also recommend syncing your system clock with a time server located somewhere in NJ/NY.
python
```text
import
 asyncio

import
 json

import
 time

import
 websockets

# This only works on Python 3.11, not 3.12!

async
 def
 stream_trades
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM_BULK'

        req[
'sec_type'
]
=
 'OPTION'

        req[
'req_type'
]
=
 'TRADE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        await
 websocket.send(req.
__str__
())

        count
=
 0

        while
 True
:

            response
=
 await
 websocket.recv()

            try
:

                count
+=
 1

                obj
=
 json.loads(response)

                if
 obj[
'header'
][
'type'
]
==
 "TRADE"
 and
 count
%
 100
 ==
 0
:

                    print
(
'latency: '
 +
 str
(get_ms_of_day()
-
 int
(obj[
'trade'
][
'ms_of_day'
])))

            except
 Exception
 as
 e:

                print
(e)

                print
(response)

                exit
(
1
)

            # print(response)

def
 get_ms_of_day
():

    # Add + 1000 to this return statement if you experience negative latencies in the 900s.

    return
 (
int
(time.time()
*
 1000
)
%
 86400000
)
-
 14400000

asyncio.get_event_loop().run_until_complete(stream_trades())
```
text
```text
latency: 3

latency: 47

latency: 25

latency: 16

latency: 4

latency: 20

latency: 18

latency: 17

latency: 37

latency: 21

latency: 5

latency: 48

latency: 26

latency: 38

latency: 47

latency: 1
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Options/Quote-Stream.html

REQUIRED
A Theta Data
Options Standard Subscription (https://thetadata.net/subscribe)
is required to use this endpoint.
# Quote Stream â
## Behavior â
This stream returns every US Option NBBO quote reported on the
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#options-opra)
feed for the specified contract. The Theta Terminal will continue to receive these messages unless it is terminated or you
unsubscribe (#unsubscribe-from-the-quote-stream)
from the quote stream.
## Subscribe to Quote Stream â
The
id
field should be increased for each new stream request made. This ID is returned in a later message to verify that the request to stream quotes was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
Failure to increment the ID for each request will prevent the terminal from automatically resubscribing to streams you previously requested.
### Contract Parameter â
The contract in the payload example below is the $4800 SPXW Call option expiring on 2024-03-15. Strike prices are formatted in 10th of a cent. This means the $4800 strike price is represented as
4800000
as seen below.
### Payload â
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"OPTION"
,

  "req_type"
:
"QUOTE"
,

  "add"
:
true
,

  "id"
:
0
,

  "contract"
: {

    "root"
:
"SPXW"
,

    "expiration"
:
20240315
,

    "strike"
:
4800000
,

    "right"
:
"C"

  }

}
```
### Sample Code â
REQUIRED
The
Theta Terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
must be running for this code to work.
Python
```text
import
 asyncio

import
 websockets

# This code has only been tested on Python 3.11. Other versions might require adjustments.

async
 def
 stream_quotes
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM'

        req[
'sec_type'
]
=
 'OPTION'

        req[
'req_type'
]
=
 'QUOTE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        req[
'contract'
]
=
 {}

        req[
'contract'
][
'root'
]
=
 "SPXW"

        req[
'contract'
][
'expiration'
]
=
 "20240315"

        req[
'contract'
][
'strike'
]
=
 "4800000"

        req[
'contract'
][
'right'
]
=
 "C"

        await
 websocket.send(req.
__str__
())

        while
 True
:

            response
=
 await
 websocket.recv()

            print
(response)

asyncio.get_event_loop().run_until_complete(stream_quotes())
```
## Unsubscribe from the Quote Stream â
Changing the
add
field in the payload from
true
to
false
will end the quote stream subscription.
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"OPTION"
,

  "req_type"
:
"QUOTE"
,

  "add"
:
false
,

  "id"
:
1
,

  "contract"
: {

    "root"
:
"SPXW"
,

    "expiration"
:
20240315
,

    "strike"
:
4800000
,

    "right"
:
"C"

  }

}
```
## Sample output â
The
right
field in the
contract
object will be set to
C
for a call and
P
for a put.
The
condition (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Quote-Conditions.html)
and
exchange (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Exchanges.html)
values correspond to their respective Enums.
The strike price is in 1/10th of a cent. This means that a $140 strike price is represented as
140000
.
Download 1 minute sample data (https://http-docs.thetadata.us/option_quote_sample.zip)
json
```text
{

  "header"
: {

    "status"
:
"CONNECTED"
,

    "type"
:
"QUOTE"

  },

  "contract"
: {

    "security_type"
:
"OPTION"
,

    "root"
:
"SPXW"
,

    "expiration"
:
20240315
,

    "strike"
:
4800000
,

    "right"
:
"C"

  },

  "quote"
: {

    "ms_of_day"
:
26622025
,

    "bid_size"
:
7
,

    "bid_exchange"
:
5
,

    "bid"
:
110.2
,

    "bid_condition"
:
50
,

    "ask_size"
:
7
,

    "ask_exchange"
:
5
,

    "ask"
:
110.5
,

    "ask_condition"
:
50
,

    "date"
:
20231219

  }

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Options/Trade-Stream.html

REQUIRED
A Theta Data
Options Standard Subscription (https://thetadata.net/subscribe)
is required to use this endpoint.
# Trade Stream â
## Behavior â
This stream returns every trade for a specified contract reported on the
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#options-opra)
feed. The Theta Terminal will continue to receive these messages unless it is terminated or you
unsubscribe (#unsubscribe-from-the-trade-stream)
from the full trade stream.
## Subscribe to Trade Stream â
The
id
field should be increased for each new stream request made. This ID is returned in a later message to verify that the request to stream trades was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
Failure to increment the ID for each request will prevent the terminal from automatically resubscribing to streams you previously requested.
### Contract Parameter â
The contract in the payload example below is the $4800 SPXW Call option expiring on 2024-03-15. Strike prices are formatted in 10th of a cent. This means the $4800 strike price is represented as
4800000
as seen below.
### Payload â
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"OPTION"
,

  "req_type"
:
"TRADE"
,

  "add"
:
true
,

  "id"
:
0
,

  "contract"
: {

    "root"
:
"SPXW"
,

    "expiration"
:
20240315
,

    "strike"
:
4800000
,

    "right"
:
"C"

  }

}
```
### Sample Code â
REQUIRED
The
Theta Terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
must be running for this code to work.
Python
```text
import
 asyncio

import
 websockets

# This code has only been tested on Python 3.11. Other versions might require adjustments.

async
 def
 stream_trades
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM'

        req[
'sec_type'
]
=
 'OPTION'

        req[
'req_type'
]
=
 'TRADE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        req[
'contract'
]
=
 {}

        req[
'contract'
][
'root'
]
=
 "SPXW"

        req[
'contract'
][
'expiration'
]
=
 "20240315"

        req[
'contract'
][
'strike'
]
=
 "4800000"

        req[
'contract'
][
'right'
]
=
 "C"

        await
 websocket.send(req.
__str__
())

        while
 True
:

            response
=
 await
 websocket.recv()

            print
(response)

asyncio.get_event_loop().run_until_complete(stream_trades())
```
## Unsubscribe from the Trade Stream â
Changing the
add
field in the payload from
true
to
false
will end the trade stream subscription.
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"OPTION"
,

  "req_type"
:
"TRADE"
,

  "add"
:
false
,

  "id"
:
1
,

  "contract"
: {

    "root"
:
"SPXW"
,

    "expiration"
:
20240315
,

    "strike"
:
4800000
,

    "right"
:
"C"

  }

}
```
## Sample output â
The
right
field in the
contract
object will be set to
C
for a call and
P
for a put.
The condition and exchange values correspond to their respective
Enums (https://http-docs.thetadata.us/Articles/Data-And-Requests/Value-Maps.html)
.
The strike price is in 1/10th of a cent. This means that a $140 strike price is represented as
140000
.
Download 1 minute sample data (https://http-docs.thetadata.us/option_trade_sample.zip)
json
```text
{

  "header"
: {

    "status"
:
"CONNECTED"
,

    "type"
:
"TRADE"

  },

  "contract"
: {

    "security_type"
:
"OPTION"
,

    "root"
:
"AAPL"
,

    "expiration"
:
20231222
,

    "strike"
:
200000
,

    "right"
:
"C"

  },

  "trade"
: {

    "ms_of_day"
:
34389945
,

    "sequence"
:
772942264
,

    "size"
:
10
,

    "condition"
:
18
,

    "price"
:
0.31
,

    "exchange"
:
31
,

    "date"
:
20231219

  }

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Stocks/Full-Trade-Stream.html

REQUIRED
A Theta Data
Stocks Pro Subscription (https://thetadata.net/subscribe)
is required to use this endpoint.
# Full Trade Stream â
## Behavior â
This stream returns every US Stock trade reported on the
Nasdaq Basic (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#nasdaq-basic)
feed. A quote (the last BBO) and ohlc message for the contract that was traded is sent before the trade occurs. The Theta Terminal will continue to receive these messages unless it is terminated or you
unsubscribe (#unsubscribe-from-the-full-trade-stream)
from the full trade stream.
## Subscribe to the Full Trade Stream â
The
id
field should be increased for each new stream request made. This ID is returned in a later message to verify that the request to stream trades was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
Failure to increment the ID for each request will prevent the terminal from automatically resubscribing to streams you previously requested.
### Payload â
json
```text
{

  "msg_type"
:
"STREAM_BULK"
,

  "sec_type"
:
"STOCK"
,

  "req_type"
:
"TRADE"
,

  "add"
:
true
,

  "id"
:
0

}
```
### Sample Code â
REQUIRED
The
Theta Terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
must be running for this code to work.
Python
```text
import
 asyncio

import
 websockets

# This code has only been tested on Python 3.11. Other versions might require adjustments.

async
 def
 stream_trades
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM_BULK'

        req[
'sec_type'
]
=
 'STOCK'

        req[
'req_type'
]
=
 'TRADE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        await
 websocket.send(req.
__str__
())

        while
 True
:

            response
=
 await
 websocket.recv()

            print
(response)

asyncio.get_event_loop().run_until_complete(stream_trades())
```
Go
```text
package
 main

import
 (

	"
encoding/json
"

	"
fmt
"

	"
log
"

	"
net/url
"

	"
os
"

	"
os/signal
"

	"
syscall
"

	"
github.com/gorilla/websocket
"

)

type
 InitialMessage
 struct
 {

	MsgType
string
 `json:"msg_type"`

	SecType
string
 `json:"sec_type"`

	ReqType
string
 `json:"req_type"`

	Add
bool
   `json:"add"`

	ID
int
    `json:"id"`

}

func
 main
() {

	interrupt
:=
 make
(
chan
 os
.
Signal
,
1
)

	signal.
Notify
(interrupt, os.Interrupt, syscall.SIGTERM)

	u
:=
 url
.
URL
{Scheme:
"ws"
, Host:
"127.0.0.1:25520"
, Path:
"/v1/events"
}

	log.
Printf
(
"connecting to
%s
"
, u.
String
())

	c, _, err
:=
 websocket.DefaultDialer.
Dial
(u.
String
(),
nil
)

	if
 err
!=
 nil
 {

		log.
Fatal
(
"dial:"
, err)

	}

	defer
 c.
Close
()

	done
:=
 make
(
chan
 struct
{})

	go
 func
() {

		defer
 close
(done)

		for
 {

			_, message, err
:=
 c.
ReadMessage
()

			if
 err
!=
 nil
 {

				log.
Println
(
"read:"
, err)

				return

			}

			fmt.
Printf
(
"
%s\n
"
, message)

		}

	}()

	initialMessage
:=
 InitialMessage
{

		MsgType:
"STREAM_BULK"
,

		SecType:
"STOCK"
,

		ReqType:
"TRADE"
,

		Add:
true
,

		ID:
0
,

	}

	msg, err
:=
 json.
Marshal
(initialMessage)

	if
 err
!=
 nil
 {

		log.
Println
(
"error in marshalling:"
, err)

		return

	}

	err
=
 c.
WriteMessage
(websocket.TextMessage, msg)

	if
 err
!=
 nil
 {

		log.
Println
(
"write:"
, err)

		return

	}

	for
 {

		select
 {

		case
 <-
done:

			return

		case
 <-
interrupt:

			log.
Println
(
"interrupt"
)

			err
:=
 c.
WriteMessage
(websocket.CloseMessage, websocket.
FormatCloseMessage
(websocket.CloseNormalClosure,
""
))

			if
 err
!=
 nil
 {

				log.
Println
(
"write close:"
, err)

				return

			}

			<-
done

			return

		}

	}

}
```
## Unsubscribe from the Full Trade Stream â
Changing the
add
field in the payload from
true
to
false
will end the full trade stream subscription.
json
```text
{

  "msg_type"
:
"STREAM_BULK"
,

  "sec_type"
:
"STOCK"
,

  "req_type"
:
"TRADE"
,

  "add"
:
false
,

  "id"
:
1

}
```
## Sample output â
The condition and exchange values correspond to their respective
Enums (https://http-docs.thetadata.us/Articles/Data-And-Requests/Value-Maps.html)
.
The strike price is in 1/10th of a cent. This means that a $140 strike price is represented as
140000
.
The
trade sequence (https://http-docs.thetadata.us/Articles/Data-And-Requests/Making-Requests.html#trade-sequences)
article might be a valuable resource.
Download 1 minute sample data (https://http-docs.thetadata.us/stock_trade_sample.zip)
json
```text
{

  "header"
: {

    "type"
:
"TRADE"
,

    "status"
:
"CONNECTED"

  },

  "contract"
: {

    "security_type"
:
"STOCK"
,

    "root"
:
"QQQ"

  },

  "trade"
: {

    "ms_of_day"
:
46843302
,

    "sequence"
:
30350622
,

    "size"
:
1
,

    "condition"
:
115
,

    "price"
:
461.535
,

    "exchange"
:
57
,

    "date"
:
20240801

  }

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Stocks/Quote-Stream.html

REQUIRED
A Theta Data
Stock Standard Subscription (https://thetadata.net/subscribe)
is required to use this endpoint.
# Quote Stream â
## Behavior â
This stream returns every BBO quote reported on the
Nasdaq Basic (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#nasdaq-basic)
feed for the specified symbol. The Theta Terminal will continue to receive these messages unless it is terminated or you
unsubscribe (#unsubscribe-from-the-quote-stream)
from the Quote stream.
## Subscribe to Quote Stream â
The
id
field should be increased for each new stream request made. This ID is returned in a later message to verify that the request to stream quotes was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
Failure to increment the ID for each request will prevent the terminal from automatically resubscribing to streams you previously requested.
### Contract Parameter â
The contract in the payload example below is subscribing to all quotes for AAPL stock.
### Payload â
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"STOCK"
,

  "req_type"
:
"QUOTE"
,

  "add"
:
true
,

  "id"
:
0
,

  "contract"
: {

    "root"
:
"AAPL"

  }

}
```
### Sample Code â
REQUIRED
The
Theta Terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
must be running for this code to work.
Python
```text
import
 asyncio

import
 websockets

# This code has only been tested on Python 3.11. Other versions might require adjustments.

async
 def
 stream_quotes
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM'

        req[
'sec_type'
]
=
 'STOCK'

        req[
'req_type'
]
=
 'QUOTE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        req[
'contract'
]
=
 {}

        req[
'contract'
][
'root'
]
=
 "AAPL"

        await
 websocket.send(req.
__str__
())

        while
 True
:

            response
=
 await
 websocket.recv()

            print
(response)

asyncio.get_event_loop().run_until_complete(stream_quotes())
```
## Unsubscribe from the Quote Stream â
Changing the
add
field in the payload from
true
to
false
will end the stream subscription.
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"STOCK"
,

  "req_type"
:
"QUOTE"
,

  "add"
:
false
,

  "id"
:
1
,

  "contract"
: {

    "root"
:
"AAPL"

  }

}
```
## Sample output â
The
condition (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Quote-Conditions.html)
and
exchange (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Exchanges.html)
values correspond to their respective Enums.
The strike price is in 1/10th of a cent. This means that a $140 strike price is represented as
140000
.
Download 1 minute sample data (https://http-docs.thetadata.us/stock_quote_sample.zip)
json
```text
{

  "header"
: {

    "type"
:
"QUOTE"
,

    "status"
:
"CONNECTED"

  },

  "contract"
: {

    "security_type"
:
"STOCK"
,

    "root"
:
"AAPL"

  },

  "quote"
: {

    "ms_of_day"
:
38437457
,

    "bid_size"
:
235
,

    "bid_exchange"
:
29
,

    "bid"
:
184.49
,

    "bid_condition"
:
0
,

    "ask_size"
:
100
,

    "ask_exchange"
:
29
,

    "ask"
:
184.5
,

    "ask_condition"
:
0
,

    "date"
:
20240503

  }

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/US-Stocks/Trade-Stream.html

REQUIRED
A Theta Data
Stock Standard Subscription (https://thetadata.net/subscribe)
is required to use this endpoint.
# Trade Stream â
## Behavior â
This stream returns every trade for a specified symbol reported on the
Nasdaq Basic (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#nasdaq-basic)
feed. The Theta Terminal will continue to receive these messages unless it is terminated or you
unsubscribe (#unsubscribe-from-the-trade-stream)
from the full trade stream.
## Subscribe to Trade Stream â
The
id
field should be increased for each new stream request made. This ID is returned in a later message to verify that the request to stream trades was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
Failure to increment the ID for each request will prevent the terminal from automatically resubscribing to streams you previously requested.
### Contract Parameter â
The contract in the payload example below is subscribing to all trades for AAPL stock.
### Payload â
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"STOCK"
,

  "req_type"
:
"TRADE"
,

  "add"
:
true
,

  "id"
:
0
,

  "contract"
: {

    "root"
:
"AAPL"

  }

}
```
### Sample Code â
REQUIRED
The
Theta Terminal (https://http-docs.thetadata.us/Articles/Getting-Started/Getting-Started.html#what-is-theta-terminal-and-why-do-i-need-it)
must be running for this code to work.
Python
```text
import
 asyncio

import
 websockets

# This code has only been tested on Python 3.11. Other versions might require adjustments.

async
 def
 stream_trades
():

    async
 with
 websockets.connect(
'ws://127.0.0.1:25520/v1/events'
)
as
 websocket:

        req
=
 {}

        req[
'msg_type'
]
=
 'STREAM'

        req[
'sec_type'
]
=
 'STOCK'

        req[
'req_type'
]
=
 'TRADE'

        req[
'add'
]
=
 True

        req[
'id'
]
=
 0

        req[
'contract'
]
=
 {}

        req[
'contract'
][
'root'
]
=
 "AAPL"

        await
 websocket.send(req.
__str__
())

        while
 True
:

            response
=
 await
 websocket.recv()

            print
(response)

asyncio.get_event_loop().run_until_complete(stream_trades())
```
## Unsubscribe from the Trade Stream â
Changing the
add
field in the payload from
true
to
false
will end the trade stream subscription.
json
```text
{

  "msg_type"
:
"STREAM"
,

  "sec_type"
:
"STOCK"
,

  "req_type"
:
"TRADE"
,

  "add"
:
false
,

  "id"
:
1
,

  "contract"
: {

    "root"
:
"AAPL"

  }

}
```
## Sample output â
The
condition (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
and
exchange (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Exchanges.html)
values correspond to their respective Enums.
Download 1 minute sample data (https://http-docs.thetadata.us/stock_trade_sample.zip)
json
```text
{

  "header"
: {

    "type"
:
"TRADE"
,

    "status"
:
"CONNECTED"

  },

  "contract"
: {

    "security_type"
:
"STOCK"
,

    "root"
:
"AAPL"

  },

  "trade"
: {

    "ms_of_day"
:
38437607
,

    "sequence"
:
12150295
,

    "size"
:
500
,

    "condition"
:
0
,

    "price"
:
184.5099
,

    "exchange"
:
57
,

    "date"
:
20240503

  }

}
```


---

# Source: https://http-docs.thetadata.us/Streaming/Verify-Stream-Requests.html

REQUIRED
Theta Terminal v1.6.0 or higher is required to utilize this behavior. You can grab the latest terminal build
here (https://download-unstable.thetadata.us)
# Verify Stream Requests â
## The request ID â
Every stream request you make to Theta Data should include the
id
field, which should be incremented for each new stream request made. This ID is returned in a later message to verify that the request to stream data was successful. This ID does not have any representation of contracts or unqiue streams. It only represents a way of tracking streaming requests made.
## Behavior â
The
type
field in the message header will be set to
REQ_RESPONSE
and the
id
will be set to the id of the stream request made by the client. Below is a sample response of a stream request that was sent with an id of zero that was successful.
json
```text
{

  "header"
: {

    "type"
:
"REQ_RESPONSE"
,

    "status"
:
"CONNECTED"
,

    "response"
:
"SUBSCRIBED"
,

    "req_id"
:
0

  }

}
```
## Response Types â
Request Response Type
Description
SUBSCRIBED
The request to subscribe to a stream was successful. This doesn't guarantee that the contract exists. It only means that if this contract exists, you will receive data for it.
ERROR
There was an unknown error subscribing to the stream.
MAX_STREAMS_REACHED
Returned when you are streaming too many contracts. You can unsubscribe from some of your streams,
upgrade (https://thetadata.net/subscribe)
your Theta Data subscription, and or
stop all streams (https://http-docs.thetadata.us/Streaming/Stop-All-Streams.html)
.
INVALID_PERMS
If you do not have permissions for the stream request. You might need to
upgrade (https://thetadata.net/subscribe)
your Theta Data subscription for the security type you are attempting to stream.


---

# Source: https://http-docs.thetadata.us/operations/get-at_time-option-quote.html

# Quote At Time â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/at_time/option/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the last NBBO quote reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at a specified millisecond of the day.
The
ivl
parameter represents the milliseconds since 00:00:00.000 ET that the quote should be provided for.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/at_time/option/quote?root=SPY&exp=20240119&strike=470000&right=C&start_date=20240116&end_date=20240116&ivl=44100000 (http://127.0.0.1:25510/v2/at_time/option/quote?root=SPY&exp=20240119&strike=470000&right=C&start_date=20240116&end_date=20240116&ivl=44100000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The number of milliseconds since 00:00:00.000 ET. Example: 09:30:00 ET =
34200000
& 16:00:00 ET =
57600000
.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
[
  44100000,
  302,
  1,
  5.71,
  50,
  300,
  1,
  5.79,
  50,
  20240116
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-at_time-option-trade.html

# Trade At Time â
Standard
Pro
GET
http://127.0.0.1:25510/v2/at_time/option/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the last trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at a specified millisecond of the day.
Trade condition mappings can be found
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
.
Extended trade conditions are not reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
for options, so they can be ignored.
The
ivl
parameter represents the milliseconds since 00:00:00.000 ET that the trade should be provided for.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/at_time/option/trade?root=SPY&exp=20240119&strike=470000&right=C&start_date=20240116&end_date=20240116&ivl=44100000 (http://127.0.0.1:25510/v2/at_time/option/trade?root=SPY&exp=20240119&strike=470000&right=C&start_date=20240116&end_date=20240116&ivl=44100000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The number of milliseconds since 00:00:00.000 ET. Example: 09:30:00 ET =
34200000
& 16:00:00 ET =
57600000
.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","date"]
Example
[
  43860664,
  602567584,
  255,
  255,
  255,
  255,
  125,
  1,
  43,
  5.84,
  0,
  1,
  0,
  0,
  20240116
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-at_time-stock-quote.html

# Quote At Time â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/at_time/stock/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
#### Real-time request behavior:
Subscription tier standard or higher will default to NQB.
Real-time last BBO quote at-ivl-time from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#nasdaq-basic)
if the account has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
15-minute delayed NBBO quote at-ivl-time from the
UTP & CTA feeds (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#equities-cta-utp)
account has the
stocks value subscription (https://www.thetadata.net/subscribe#stocks)
subscription.
#### Historical request behavior:
Returns the last NBBO quote reported by
UTP & CTA feeds (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#equities-cta-utp)
at a specified millisecond of the day.
The
ivl
parameter represents the milliseconds since 00:00:00.000 ET that the quote should be provided for.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/at_time/stock/quote?root=SPY&start_date=20240116&end_date=20240116&ivl=57600000 (http://127.0.0.1:25510/v2/at_time/stock/quote?root=SPY&start_date=20240116&end_date=20240116&ivl=57600000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The number of milliseconds since 00:00:00.000 ET. Example: 09:30:00 ET =
34200000
& 16:00:00 ET =
57600000
.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
venue
Â -
Used to specify the venue of the real time or historic request.
nqb
= Nasdaq Basic;
utp_cta
= merged UTP & CTA.
Type:
string
(Default: nqb)
Enum
nqb, utp_cta
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
[
  57600000,
  8,
  1,
  474.95,
  0,
  17,
  7,
  474.96,
  0,
  20240116
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-at_time-stock-trade.html

# Trade At Time â
Standard
Pro
GET
http://127.0.0.1:25510/v2/at_time/stock/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
#### Real-time request behavior:
Returns a real-time session from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#nasdaq-basic)
if the account has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
Returns a 15-minute delayed session from the
UTP & CTA feeds (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#equities-cta-utp)
account has the
stocks value subscription (https://www.thetadata.net/subscribe#stocks)
subscription.
#### Historical request behavior:
Returns the last trade reported by
UTP & CTA feeds (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#equities-cta-utp)
at a specified millisecond of the day.
Trade condition mappings can be found
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
.
The
ivl
parameter represents the milliseconds since 00:00:00.000 ET that the trade should be provided for.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/at_time/stock/trade?root=SPY&start_date=20240116&end_date=20240116&ivl=57600000 (http://127.0.0.1:25510/v2/at_time/stock/trade?root=SPY&start_date=20240116&end_date=20240116&ivl=57600000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The number of milliseconds since 00:00:00.000 ET. Example: 09:30:00 ET =
34200000
& 16:00:00 ET =
57600000
.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
venue
Â -
Used to specify the venue of the real time or historic request.
nqb
= Nasdaq Basic;
utp_cta
= merged UTP & CTA.
Type:
string
(Default: nqb)
Enum
nqb, utp_cta
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","date"]
Example
[
  57600000,
  10146941,
  32,
  255,
  255,
  255,
  0,
  560,
  1,
  474.95,
  0,
  1,
  0,
  0,
  20240116
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_at_time-option-quote.html

# Bulk Quote At Time â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_at_time/option/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Returns the last NBBO quote reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at
a specified millisecond of the day. The
ivl
parameter represents the milliseconds since
00:00:00.000 ET that the quote should be provided for.
Set
exp
to
0
if you want to retrieve data for every option that shares the same
root
.
Note: Any
exp=0
must be requested day by day
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_at_time/option/quote?root=SPY&exp=20240119&start_date=20240116&end_date=20240116&ivl=44100000 (http://127.0.0.1:25510/v2/bulk_at_time/option/quote?root=SPY&exp=20240119&start_date=20240116&end_date=20240116&ivl=44100000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The number of milliseconds since 00:00:00.000 ET. Example: 09:30:00 ET =
34200000
& 16:00:00 ET =
57600000
.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
{
  "ticks": [
    [
      44100000,
      75,
      5,
      294.61,
      50,
      75,
      5,
      295.01,
      50,
      20240116
    ]
  ],
  "contract": {
    "root": "SPY",
    "expiration": 20240119,
    "strike": 180000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      44100000,
      0,
      7,
      0,
      50,
      12287,
      42,
      0.01,
      50,
      20240116
    ]
  ],
  "contract": {
    "root": "SPY",
    "expiration": 20240119,
    "strike": 180000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_at_time-option-trade.html

# Bulk Trade At Time â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_at_time/option/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Returns the last trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at
a specified millisecond of the day. Trade condition
mappings can be found
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
. Extended trade conditions are
not reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
for options, so they can be ignored.
The
ivl
parameter represents the milliseconds since
00:00:00.000 ET that the trade should be provided for.
Set
exp
to
0
if you want to retrieve data for every option that shares the same
root
.
Note: Any
exp=0
must be requested day by day
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_at_time/option/trade?root=SPY&exp=20240119&start_date=20240116&end_date=20240116&ivl=44100000 (http://127.0.0.1:25510/v2/bulk_at_time/option/trade?root=SPY&exp=20240119&start_date=20240116&end_date=20240116&ivl=44100000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The number of milliseconds since 00:00:00.000 ET. Example: 09:30:00 ET =
34200000
& 16:00:00 ET =
57600000
.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details;["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","date"]
Example
{
  "ticks": [
    [
      36476240,
      325086878,
      255,
      255,
      255,
      255,
      18,
      1,
      69,
      294.62,
      0,
      3,
      0,
      0,
      20240116
    ]
  ],
  "contract": {
    "root": "SPY",
    "expiration": 20240119,
    "strike": 180000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34394294,
      235308063,
      255,
      255,
      255,
      255,
      130,
      1,
      43,
      0.01,
      0,
      7,
      0,
      0,
      20240116
    ]
  ],
  "contract": {
    "root": "SPY",
    "expiration": 20240119,
    "strike": 180000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-all_greeks.html

# Bulk All Greeks â
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/all_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Calculates greeks for every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/all_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110&ivl=900000 (http://127.0.0.1:25510/v2/bulk_hist/option/all_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","delta","theta","vega","rho","epsilon","lambda","gamma","vanna","charm","vomma","veta","vera","speed","zomma","color","ultima","d1","d2","dual_delta","dual_gamma","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      35100000,
      134.6,
      134.9,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0.0003,
      35100000,
      184.74,
      20231110
    ],
    [
      36000000,
      133.95,
      135.1,
      0.9933,
      -0.1531,
      0.4728,
      0.929,
      -3.5088,
      1.3601,
      0.0001,
      -0.008,
      0.9062,
      0.5085,
      0.0236,
      0,
      0,
      0.0009,
      -0.0179,
      0.1852,
      2.4774,
      1.8783,
      -0.9688,
      0.0008,
      4.3265,
      0,
      36000000,
      184.18,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 50000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34200000,
      0,
      0,
      -0.0002,
      -0.0006,
      0.0167,
      -0.0006,
      0.0006,
      -57.5498,
      0.0001,
      -0.0046,
      0.0595,
      0.4199,
      0.0013,
      0,
      0,
      0,
      -0.0001,
      8.0394,
      3.5808,
      3.5115,
      0.0002,
      0,
      0.5,
      100,
      34200000,
      183.89,
      20231110
    ],
    [
      35100000,
      0.01,
      0.02,
      -0.002,
      -0.0073,
      0.1624,
      -0.0072,
      0.007,
      -37.8591,
      0.0003,
      -0.0277,
      0.4578,
      2.0452,
      0.0086,
      0,
      0,
      0,
      -0.0008,
      16.1244,
      2.8776,
      2.7893,
      0.0026,
      0,
      0.6374,
      -0.0225,
      35100000,
      184.74,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 144000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-all_trade_greeks.html

# Bulk All Trade Greeks â
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/all_trade_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Calculates greeks for every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/all_trade_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110&ivl=900000 (http://127.0.0.1:25510/v2/bulk_hist/option/all_trade_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","delta","theta","vega","rho","epsilon","lambda","gamma","vanna","charm","vomma","veta","vera","speed","zomma","color","ultima","d1","d2","dual_delta","dual_gamma","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      57341102,
      387753922,
      255,
      255,
      255,
      255,
      18,
      5,
      7,
      0.01,
      0,
      7,
      0,
      0,
      -0.0014,
      -0.0079,
      0.1195,
      -0.0052,
      0.005,
      -26.351,
      0.0001,
      -0.0142,
      0.343,
      1.0946,
      0.008,
      0,
      0,
      0,
      -0.0008,
      6.4936,
      2.9852,
      2.8562,
      0.0021,
      0,
      0.9312,
      0.002,
      57341093,
      186.36,
      20231110
    ],
    [
      57341103,
      387753927,
      255,
      255,
      255,
      255,
      18,
      5,
      60,
      0.01,
      0,
      1,
      0,
      0,
      -0.0014,
      -0.0079,
      0.1195,
      -0.0052,
      0.005,
      -26.351,
      0.0001,
      -0.0142,
      0.343,
      1.0946,
      0.008,
      0,
      0,
      0,
      -0.0008,
      6.4936,
      2.9852,
      2.8562,
      0.0021,
      0,
      0.9312,
      0.002,
      57341103,
      186.36,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 128000,
    "right": "P"
  }
}
{
  "ticks": [
    [
      35917535,
      -1191835614,
      255,
      255,
      255,
      255,
      95,
      4,
      11,
      0.01,
      0,
      7,
      0,
      0,
      -0.0016,
      -0.0082,
      0.1329,
      -0.0059,
      0.0056,
      -27.8173,
      0.0002,
      -0.0168,
      0.3815,
      1.2643,
      0.0085,
      0,
      0,
      0,
      -0.0009,
      7.6819,
      2.9453,
      2.8242,
      0.0023,
      0,
      0.875,
      0.068,
      35917504,
      184.21,
      20231110
    ],
    [
      56519914,
      324561624,
      255,
      255,
      255,
      255,
      18,
      1,
      7,
      0.01,
      0,
      1,
      0,
      0,
      -0.0014,
      -0.0079,
      0.1257,
      -0.0055,
      0.0053,
      -27.3723,
      0.0002,
      -0.0155,
      0.3596,
      1.1874,
      0.0083,
      0,
      0,
      0,
      -0.0009,
      7.2255,
      2.9677,
      2.8439,
      0.0022,
      0,
      0.8937,
      0.0196,
      56519911,
      186.08,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 130000,
    "right": "C"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-eod.html

# Bulk EOD â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/eod
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Since
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
does not provide a national EOD
report for options, Theta Data generates a national EOD report at 17:15 ET each day.
ms_of_day
represents the time of day the report was generated and
ms_of_day2
represents the time of the last trade. The quote in the response
represents the last NBBO reported by OPRA at the time of report generation.
You can read more about EOD & OHLC data
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/OHLC-EOD)
.
Set
exp
to
0
if you want
to retrieve data for every option that shares the same
root
. (note: Any
exp=0
must be requested day by day)
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/eod?root=AAPL&exp=20231103&start_date=20231102&end_date=20231102 (http://127.0.0.1:25510/v2/bulk_hist/option/eod?root=AAPL&exp=20231103&start_date=20231102&end_date=20231102)
The quote fields (bid / ask info) may not be available prior to 2023-12-01. We will expose further history for the EOD quote in the near future.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","ms_of_day2","open","high","low","close","volume","count","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
{
  "ticks": [
    [
      62573163,
      55073367,
      126.35,
      127.6,
      126.2,
      127.6,
      14,
      10,
      6,
      47,
      126.6,
      50,
      1,
      7,
      129.65,
      50,
      20231102
    ],
    [
      63174002,
      55073367,
      126.35,
      127.6,
      126.2,
      127.6,
      14,
      10,
      6,
      47,
      126.6,
      50,
      1,
      7,
      129.65,
      50,
      20231102
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20240119,
    "strike": 50000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      62573163,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      22,
      0,
      50,
      1,
      7,
      0.01,
      50,
      20231102
    ],
    [
      63174002,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      22,
      0,
      50,
      1,
      7,
      0.01,
      50,
      20231102
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20240119,
    "strike": 50000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-greeks.html

# Bulk Greeks â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Calculated using the option and underlying midpoint price. If an interval size is specified (
highly recommended
), the option quote used in the calculation follows the same rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/greeks?root=AAPL&exp=20230915&start_date=20230911&end_date=20230911&ivl=90000 (http://127.0.0.1:25510/v2/bulk_hist/option/greeks?root=AAPL&exp=20230915&start_date=20230911&end_date=20230911&ivl=90000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","delta","theta","vega","rho","epsilon","lambda","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      34290000,
      114.95,
      115.05,
      0.9988,
      -0.0393,
      0.0708,
      0.7094,
      -1.9697,
      1.5629,
      3.3828,
      0,
      34289992,
      179.94,
      20230911
    ],
    [
      34380000,
      115.05,
      115.2,
      0.9988,
      -0.0392,
      0.0705,
      0.7094,
      -1.971,
      1.5623,
      3.3828,
      0,
      34379988,
      180.06,
      20230911
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20230915,
    "strike": 65000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34290000,
      109.95,
      110.05,
      0.9989,
      -0.0361,
      0.0671,
      0.7643,
      -1.9698,
      1.634,
      3.1015,
      0,
      34289992,
      179.94,
      20230911
    ],
    [
      34380000,
      110.05,
      110.15,
      1,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      34379988,
      180.06,
      20230911
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20230915,
    "strike": 70000,
    "right": "C"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-greeks_second_order.html

# Bulk Greeks Second Order â
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/greeks_second_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Calculated using the option and underlying midpoint price. If an interval size is specified (
highly recommended
), the option quote used in the calculation follows the same rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/greeks_second_order?root=AAPL&exp=20230915&start_date=20230911&end_date=20230911&ivl=90000 (http://127.0.0.1:25510/v2/bulk_hist/option/greeks_second_order?root=AAPL&exp=20230915&start_date=20230911&end_date=20230911&ivl=90000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","gamma","vanna","charm","vomma","veta","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      34290000,
      114.95,
      115.05,
      0,
      -0.003,
      0.4629,
      0.1727,
      0.0032,
      3.3828,
      0,
      34289992,
      179.94,
      20230911
    ],
    [
      34380000,
      115.05,
      115.2,
      0,
      -0.0029,
      0.4606,
      0.1721,
      0.0032,
      3.3828,
      0,
      34379988,
      180.06,
      20230911
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20230915,
    "strike": 65000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34290000,
      109.95,
      110.05,
      0,
      -0.0031,
      0.4459,
      0.1825,
      0.0031,
      3.1015,
      0,
      34289992,
      179.94,
      20230911
    ],
    [
      34380000,
      110.05,
      110.15,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      34379988,
      180.06,
      20230911
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20230915,
    "strike": 70000,
    "right": "C"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-greeks_third_order.html

# Bulk Greeks Third Order â
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/greeks_third_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Calculated using the option and underlying midpoint price. If an interval size is specified (
highly recommended
), the option quote used in the calculation follows the same rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/greeks_third_order?root=AAPL&exp=20230915&start_date=20230911&end_date=20230911&ivl=90000 (http://127.0.0.1:25510/v2/bulk_hist/option/greeks_third_order?root=AAPL&exp=20230915&start_date=20230911&end_date=20230911&ivl=90000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","speed","zomma","color","ultima","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      34290000,
      114.95,
      115.05,
      0,
      0.0001,
      -0.0011,
      0.2671,
      3.3828,
      0,
      34289992,
      179.94,
      20230911
    ],
    [
      34380000,
      115.05,
      115.2,
      0,
      0.0001,
      -0.0011,
      0.2667,
      3.3828,
      0,
      34379988,
      180.06,
      20230911
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20230915,
    "strike": 65000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34290000,
      109.95,
      110.05,
      0,
      0.0001,
      -0.001,
      0.3194,
      3.1015,
      0,
      34289992,
      179.94,
      20230911
    ],
    [
      34380000,
      110.05,
      110.15,
      0,
      0,
      0,
      0,
      0,
      0,
      34379988,
      180.06,
      20230911
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20230915,
    "strike": 70000,
    "right": "C"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-ohlc.html

# Bulk OHLC â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/ohlc
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration. Aggregated OHLC bars that use
SIP rules (https://http-docs.thetadata.us/Articles/Data-And-Requests/OHLC-EOD)
for each bar. Time timestamp of the bar represents the opening time of the bar. For a
trade to be part of the bar:
bar timestamp
<=
trade time
<
bar timestamp + ivl
, where ivl is the
specified interval size in milliseconds.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/ohlc?root=AAPL&exp=20231103&start_date=20231103&end_date=20231103&ivl=900000 (http://127.0.0.1:25510/v2/bulk_hist/option/ohlc?root=AAPL&exp=20231103&start_date=20231103&end_date=20231103&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Required
Â -
The interval size in milliseconds. 1 minute intervals is
60000
.
Type:
integer
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","open","high","low","close","volume","count","date"]
Example
{
  "ticks": [
    [
      34200000,
      14.3,
      14.8,
      13.5,
      14.3,
      50,
      18,
      20231103
    ],
    [
      35100000,
      15.5,
      15.61,
      15.38,
      15.51,
      26,
      10,
      20231103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231103,
    "strike": 160000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34200000,
      0.01,
      0.15,
      0.01,
      0.01,
      718,
      113,
      20231103
    ],
    [
      35100000,
      0.01,
      0.01,
      0.01,
      0.01,
      232,
      30,
      20231103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231103,
    "strike": 160000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-quote.html

# Bulk Quote â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Returns every NBBO quote reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
. If the
ivl
parameter is specified, the quote for each interval represents the last quote
at the interval's timestamp. We do not recommend omitting the
ivl
parameter
as tick-level quote responses are very large, which can produce undefined behavior. To request tick-level data, make
single contract requests. Any
ivl
under
60000
is not officially supported.
We also do not recommend using a date range over 1 day.
Set
exp
to
0
if you want
to retrieve data for every option that shares the same
root
. This is only supported for 1 minute intervals (
ivl=60000
) (note: Any
exp=0
must be requested day by day)
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/quote?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110&ivl=900000 (http://127.0.0.1:25510/v2/bulk_hist/option/quote?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
{
  "ticks": [
    [
      35100000,
      13,
      47,
      134.6,
      50,
      11,
      47,
      134.9,
      50,
      20231110
    ],
    [
      36000000,
      1,
      47,
      133.95,
      50,
      50,
      1,
      135.1,
      50,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 50000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      35100000,
      0,
      7,
      0,
      50,
      608,
      42,
      0.01,
      50,
      20231110
    ],
    [
      36000000,
      0,
      42,
      0,
      50,
      161,
      1,
      0.01,
      50,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 50000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-trade.html

# Bulk Trade â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Returns every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
. Trade condition
mappings can be found
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
. Extended trade conditions are
not reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
for options, so they can be ignored.
Set
exp
to
0
if you want
to retrieve data for every option that shares the same
root
. (note: Any
exp=0
must be requested day by day)
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/trade?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110 (http://127.0.0.1:25510/v2/bulk_hist/option/trade?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","date"]
Example
{
  "ticks": [
    [
      56167951,
      299720858,
      255,
      255,
      255,
      255,
      18,
      1,
      42,
      86.15,
      0,
      7,
      0,
      0,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 100000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      41064023,
      -745524183,
      255,
      255,
      255,
      255,
      125,
      1,
      43,
      79.9,
      0,
      7,
      0,
      0,
      20231110
    ],
    [
      43614362,
      -561477748,
      255,
      255,
      255,
      255,
      125,
      1,
      9,
      79.97,
      0,
      3,
      0,
      0,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 105000,
    "right": "C"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-trade_greeks.html

# Bulk Trade Greeks â
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/trade_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Calculates greeks for every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
perf_boost
can be specified to
true
to improve the speed of this request by using 1 second intervals for the underlying quotes instead of tick level quotes.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/trade_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110 (http://127.0.0.1:25510/v2/bulk_hist/option/trade_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
perf_boost
Â -
If true: 1 second intervals for the underlying equity will be used to calcualte the stock price at the time of each option trade instead of using  tick-level equity NBBO. This significantly improves performance as there are much less rows of data that have to be processed per request. This flag only works with the trade greeks endpoints.
Type:
boolean
(Default: false)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","delta","theta","vega","rho","epsilon","lambda","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      56167951,
      299720858,
      255,
      255,
      255,
      255,
      18,
      1,
      42,
      86.15,
      0,
      7,
      0,
      0,
      1,
      0,
      0,
      0,
      0,
      0,
      0,
      0.0004,
      56167951,
      186.09,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 100000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      41064023,
      -745524183,
      255,
      255,
      255,
      255,
      125,
      1,
      43,
      79.9,
      0,
      7,
      0,
      0,
      0.9997,
      -0.0172,
      0.023,
      2.0107,
      -3.543,
      2.3122,
      1.2,
      0,
      41064019,
      184.79,
      20231110
    ],
    [
      43614362,
      -561477748,
      255,
      255,
      255,
      255,
      125,
      1,
      9,
      79.97,
      0,
      3,
      0,
      0,
      1,
      0,
      0,
      0,
      0,
      0,
      0,
      0.0004,
      43614340,
      184.9,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 105000,
    "right": "C"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_hist-option-trade_quote.html

# Bulk Trade Quote â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/trade_quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Returns every
trade (https://http-docs.thetadata.us/operations/get-hist-option-trade)
reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
paired with the last NBBO quote
reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at the time of trade. A quote
is matched with a trade if its timestamp
<=
the trade timestamp. To
match trades with quotes timestamps that are
<
the trade timestamp, specify the
exclusive
parameter to
true
. After thorough testing, we have determined that using
exclusive=true
might yield better results for various applications.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/trade_quote?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110 (http://127.0.0.1:25510/v2/bulk_hist/option/trade_quote?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
exclusive
Â -
If you prefer to match quotes with timestamps that are < the trade timestamp, specify this  parameter to true. This parameter only works with the trade_quote endpoint.
Type:
boolean
(Default: false)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","ms_of_day2","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
{
  "ticks": [
    [
      56167951,
      299720858,
      255,
      255,
      255,
      255,
      18,
      1,
      42,
      86.15,
      0,
      7,
      0,
      0,
      56167951,
      12,
      47,
      86,
      50,
      1,
      47,
      86.2,
      50,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 100000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      41064023,
      -745524183,
      255,
      255,
      255,
      255,
      125,
      1,
      43,
      79.9,
      0,
      7,
      0,
      0,
      41051889,
      14,
      47,
      79.75,
      50,
      3,
      31,
      80,
      50,
      20231110
    ],
    [
      43614362,
      -561477748,
      255,
      255,
      255,
      255,
      125,
      1,
      9,
      79.97,
      0,
      3,
      0,
      0,
      43614362,
      13,
      7,
      79.85,
      50,
      13,
      7,
      80.1,
      50,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 105000,
    "right": "C"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-all_greeks.html

# Bulk All Greeks â
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/option/all_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last greeks calculation for all option contracts that lie on a provided expiration.
You might need to change the default expiration date to a different date if it is past the current date. Some quotes are omitted in the example to reduce the space of the sample output.
Make
exp
0 if you want to get the snapshot for every expiration chain for the underlying.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/option/all_greeks?root=AAPL&exp=20260116 (http://127.0.0.1:25510/v2/bulk_snapshot/option/all_greeks?root=AAPL&exp=20260116)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
under_price
Â -
The underlying price to be used in the Greeks calculation for a snapshot.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","delta","theta","vega","rho","epsilon","lambda","gamma","vanna","charm","vomma","veta","speed","zomma","color","ultima","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      50709357,
      316.2,
      319.5,
      0.889,
      -1.6478,
      254.9316,
      250.3638,
      -266.0386,
      16.9724,
      0.0007,
      -1.1576,
      2.1708,
      1905.5221,
      8.0136,
      0,
      0,
      -1.1273,
      -100,
      0.1926,
      0,
      50709000,
      6067.86,
      20250210
    ]
  ],
  "contract": {
    "root": "SPXW",
    "expiration": 20250228,
    "strike": 5770000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      50709677,
      10.5,
      10.7,
      -0.0932,
      -1.0769,
      224.7201,
      -28.4387,
      27.916,
      -53.401,
      0.0006,
      -1.2025,
      2.0802,
      2140.1218,
      7.3513,
      0,
      0,
      -0.9044,
      -100,
      0.1776,
      0,
      50709000,
      6067.86,
      20250210
    ]
  ],
  "contract": {
    "root": "SPXW",
    "expiration": 20250228,
    "strike": 5770000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-greeks.html

# Bulk Greeks â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last greeks calculation for all option contracts that lie on a provided expiration.
You might need to change the default expiration date to a different date if it is past the current date. Some quotes are omitted in the example to reduce the space of the sample output.
Make
exp
0 if you want to get the snapshot for every expiration chain for the underlying.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks?root=AAPL&exp=20260116 (http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks?root=AAPL&exp=20260116)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
under_price
Â -
The underlying price to be used in the Greeks calculation for a snapshot.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","delta","theta","vega","rho","epsilon","lambda","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      57599934,
      221.9,
      225.65,
      0.9999,
      -0.0011,
      0.0754,
      20.2037,
      -251.3314,
      1.0874,
      0.725,
      0,
      71985879,
      243.35,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34204994,
      0.02,
      0.04,
      -0.0004,
      -0.0004,
      0.3847,
      -0.1402,
      0.1088,
      -3.4606,
      0.8562,
      0.015,
      71985879,
      243.35,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-greeks_second_order.html

# Bulk Greeks Second Order â
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks_second_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last second order greeks calculation for all option contracts that lie on a provided expiration.
You might need to change the default expiration date to a different date if it is past the current date. Some quotes are omitted in the example to reduce the space of the sample output.
Make
exp
0 if you want to get the snapshot for every expiration chain for the underlying.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks_second_order?root=AAPL&exp=20260116 (http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks_second_order?root=AAPL&exp=20260116)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
under_price
Â -
The underlying price to be used in the Greeks calculation for a snapshot.
Type:
number
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","gamma","vanna","charm","vomma","veta","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      57599934,
      221.9,
      225.65,
      0,
      -0.0012,
      0.0004,
      1.2035,
      0.4814,
      0.725,
      0,
      71985879,
      243.35,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34204994,
      0.02,
      0.04,
      0,
      -0.0044,
      0.0018,
      3.6821,
      1.7959,
      0.8562,
      0.015,
      71985879,
      243.35,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-greeks_third_order.html

# Bulk Greeks Third Order â
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks_third_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last third order greeks calculation for all option contracts that lie on a provided expiration.
You might need to change the default expiration date to a different date if it is past the current date. Some quotes are omitted in the example to reduce the space of the sample output.
Make
exp
0 if you want to get the snapshot for every expiration chain for the underlying.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks_third_order?root=AAPL&exp=20260116 (http://127.0.0.1:25510/v2/bulk_snapshot/option/greeks_third_order?root=AAPL&exp=20260116)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
under_price
Â -
The underlying price to be used in the Greeks calculation for a snapshot.
Type:
number
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid","ask","speed","zomma","color","ultima","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      57599934,
      221.9,
      225.65,
      0,
      0,
      0.308,
      14.1321,
      0.725,
      0,
      71985879,
      243.35,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34204994,
      0.02,
      0.04,
      0,
      0,
      1.2627,
      21.9454,
      0.8562,
      0.015,
      71985879,
      243.35,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-ohlc.html

# Bulk OHLC â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/option/ohlc
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last
SIP (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
corrected session OHLC for all option contracts that share the same expiration and root.
Make
exp
0 if you want to get the snapshot for every expiration chain for the underlying.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/option/ohlc?root=AAPL&exp=20260116 (http://127.0.0.1:25510/v2/bulk_snapshot/option/ohlc?root=AAPL&exp=20260116)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","open","high","low","close","volume","count","date"]
Example
{
  "ticks": [
    [
      34200000,
      14.3,
      14.8,
      13.5,
      14.3,
      50,
      18,
      20231103
    ],
    [
      35100000,
      15.5,
      15.61,
      15.38,
      15.51,
      26,
      10,
      20231103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231103,
    "strike": 160000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34200000,
      0.01,
      0.15,
      0.01,
      0.01,
      718,
      113,
      20231103
    ],
    [
      35100000,
      0.01,
      0.01,
      0.01,
      0.01,
      232,
      30,
      20231103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231103,
    "strike": 160000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-open_interest.html

# Bulk Open Interest â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/option/open_interest
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve the last
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
reported open interest message for all option contracts that share the same expiration and root.
Open interest is reported around 06:30 ET every morning by OPRA and reflects the open interest at the end of the previou trading day.
You might need to change the default expiration date to a different date if it is past the current date.
Make
exp
0 if you want to get the snapshot for every expiration chain for the underlying.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/option/open_interest?root=AAPL&exp=20260116 (http://127.0.0.1:25510/v2/bulk_snapshot/option/open_interest?root=AAPL&exp=20260116)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","open_interest","date"]
Example
{
  "ticks": [
    [
      23400000,
      0,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 50000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      23404000,
      4910,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 50000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-quote.html

# Bulk Quotes â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/option/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last quote for all option contracts that share the same expiration and root.
Make
exp
0 if you want to get the snapshot for every expiration chain for the underlying.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/option/quote?root=AAPL&exp=20260116 (http://127.0.0.1:25510/v2/bulk_snapshot/option/quote?root=AAPL&exp=20260116)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
{
  "ticks": [
    [
      57599934,
      60,
      7,
      221.9,
      50,
      50,
      1,
      225.65,
      50,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      34204994,
      3,
      1,
      0.02,
      50,
      10,
      1,
      0.04,
      50,
      20250103
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20260116,
    "strike": 20000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-get-v2-hist-stock-trade_quote.html

# Trade Quote â
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/stock/trade_quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns every trade reported by
UTP & CTA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
paired with the
last BBO quote reported by
UTP or CTA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at the time of
trade. A quote is matched with a trade if its timestamp
<=
the trade timestamp.
If you prefer to match quotes with timestamps that are
<
the trade timestamp,
specify the
exclusive
parameter to
true
. Set the
venue
parameter to
nqb
to access
current-day real-time historic data from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if the account
has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/stock/trade_quote?root=AAPL&start_date=20240102&end_date=20240102 (http://127.0.0.1:25510/v2/hist/stock/trade_quote?root=AAPL&start_date=20240102&end_date=20240102)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
exclusive
Â -
If you prefer to match quotes with timestamps that are < the trade timestamp, specify this  parameter to true. This parameter only works with the trade_quote endpoint.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","ms_of_day2","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
[
  14400004,
  1,
  32,
  255,
  1,
  115,
  1,
  5,
  65,
  191.68,
  7,
  0,
  0,
  0,
  14400004,
  2,
  65,
  190.05,
  0,
  1,
  65,
  191.68,
  0,
  20240102
]
[
  14400004,
  2,
  32,
  255,
  1,
  115,
  1,
  20,
  65,
  191.68,
  7,
  0,
  0,
  0,
  14400004,
  2,
  65,
  190.05,
  0,
  1,
  65,
  191.68,
  0,
  20240102
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-all_greeks.html

# All Greeks â
Pro
GET
http://127.0.0.1:25510/v2/hist/option/all_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculated using the option and underlying midpoint price. If an interval size is specified
(
highly recommended
), the option quote used in the calculation follows the same
rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint. The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/all_greeks?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000 (http://127.0.0.1:25510/v2/hist/option/all_greeks?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","bid","ask","delta","theta","vega","rho","epsilon","lambda","gamma","vanna","charm","vomma","veta","vera","speed","zomma","color","ultima","d1","d2","dual_delta","dual_gamma","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  35100000,
  8.7,
  8.75,
  0.8848,
  -0.1968,
  3.6244,
  1.6325,
  -1.7281,
  18.0818,
  0.0269,
  -0.5823,
  10.02,
  13.032,
  -0.0149,
  0,
  0,
  0,
  -0.0075,
  -54.2783,
  1.1996,
  1.1591,
  -0.8762,
  0,
  0.3867,
  0.0001,
  35100000,
  178.21,
  20230911
]
[
  36000000,
  8.5,
  8.55,
  0.8816,
  -0.1979,
  3.6904,
  1.6265,
  -1.7198,
  18.4217,
  0.0277,
  -0.5923,
  10.0699,
  13.0622,
  -0.0157,
  0,
  0,
  0,
  -0.0076,
  -56.3025,
  1.1834,
  1.1434,
  -0.873,
  0,
  0.3823,
  0,
  36000000,
  178,
  20230911
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-all_trade_greeks.html

# All Trade Greeks â
Pro
GET
http://127.0.0.1:25510/v2/hist/option/all_trade_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculated using the option and underlying midpoint price. If an interval size is specified
(
highly recommended
), the option quote used in the calculation follows the same
rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint. The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/all_trade_greeks?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000 (http://127.0.0.1:25510/v2/hist/option/all_trade_greeks?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","delta","theta","vega","rho","epsilon","lambda","gamma","vanna","charm","vomma","veta","vera","speed","zomma","color","ultima","d1","d2","dual_delta","dual_gamma","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  34200178,
  2314473,
  255,
  255,
  255,
  255,
  130,
  1,
  6,
  10.45,
  0,
  7,
  0,
  0,
  0.9194,
  -0.1642,
  2.8179,
  1.6998,
  -1.8143,
  15.8416,
  0.0197,
  -0.5049,
  9.0809,
  13.3365,
  -0.0096,
  0,
  0,
  0,
  -0.006,
  -36.354,
  1.4011,
  1.359,
  -0.9124,
  0,
  0.4023,
  0,
  34200177,
  180.07,
  20230911
]
[
  34203290,
  3009866,
  255,
  255,
  255,
  255,
  134,
  3,
  42,
  10.55,
  0,
  3,
  0,
  0,
  0.9237,
  -0.1573,
  2.7052,
  1.7084,
  -1.824,
  15.7755,
  0.019,
  -0.4998,
  8.9046,
  13.4875,
  -0.0096,
  0,
  0,
  0,
  -0.0057,
  -34.338,
  1.4304,
  1.3887,
  -0.917,
  0,
  0.3984,
  0,
  34203274,
  180.19,
  20230911
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-eod_greeks.html

# Bulk EOD Greeks â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/eod_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Uses Theta Data's EOD reports that get generated at 17:15 ET each day. The closing option price and closing underlying price are used for the greeks calculation.
ms_of_day
represents the time of the last option trade and
ms_of_day2
represents the time of the last stock trade.
Set
exp
to
0
if you want to retrieve data for every option that shares the same
root
. (note: Any
exp=0
must be requested day by day)
Sample data contains partial output of the request as the full response to the request is too large to display on this webpage.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/eod_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110 (http://127.0.0.1:25510/v2/bulk_hist/option/eod_greeks?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110)
The quote fields (bid / ask info) may not be available prior to 2023-12-01. We are working to expose this over the coming months. Obtaining the quote at the end of the day requires much more processing than the trades, so we initially generated our history for trades.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
annual_div
Â -
The annualized expected dividend amount to be used in Greeks calculations.
Type:
number
rate
Â -
The interest rate type to be used in a Greeks calculation. Omitting this parameter will default to SOFR or 0 if no rate exists for the date in question.
Type:
string
Enum
SOFR, TREASURY_M1, TREASURY_M3, TREASURY_M6, TREASURY_Y1, TREASURY_Y2, TREASURY_Y3, TREASURY_Y5, TREASURY_Y7, TREASURY_Y10, TREASURY_Y20, TREASURY_Y30
rate_value
Â -
The annualized interest rate value to be used in a Greeks calculation. A 3.42% interest rate would be represented as .0342. This will override the
rate
parameter if it is specified.
Type:
number
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","open","high","low","close","volume","count","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","delta","theta","vega","rho","epsilon","lambda","gamma","vanna","charm","vomma","veta","vera","speed","zomma","color","ultima","d1","d2","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
{
  "ticks": [
    [
      43614362,
      79.9,
      79.97,
      79.9,
      79.97,
      2,
      2,
      50,
      7,
      80.85,
      50,
      50,
      60,
      82,
      50,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0.0192,
      43614362,
      186.4,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 105000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      56967501,
      0.01,
      0.01,
      0.01,
      0.01,
      73,
      8,
      100,
      7,
      0.01,
      50,
      98,
      7,
      0.02,
      50,
      -0.0014,
      -0.0075,
      0.1215,
      -0.0053,
      0.0051,
      -28.0651,
      0.0002,
      -0.0153,
      0.3489,
      1.1833,
      0.008,
      0,
      0,
      0,
      -0.0008,
      7.4596,
      2.9796,
      2.8584,
      0.875,
      -0.0417,
      56967501,
      186.4,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 131000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-greeks.html

# Greeks â
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculated using the option and underlying midpoint price. If an interval size is specified
(
highly recommended
), the option quote used in the calculation follows the same
rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint. The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/greeks?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=90000 (http://127.0.0.1:25510/v2/hist/option/greeks?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=90000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","bid","ask","delta","theta","vega","rho","epsilon","lambda","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  34290000,
  10.3,
  10.4,
  0.9135,
  -0.1739,
  2.9676,
  1.6881,
  -1.8015,
  15.8829,
  0.4086,
  0,
  34289992,
  179.94,
  20230911
]
[
  34380000,
  10.35,
  10.5,
  0.9231,
  -0.1566,
  2.7177,
  1.7074,
  -1.8216,
  15.9525,
  0.3945,
  0,
  34379988,
  180.06,
  20230911
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-greeks_second_order.html

# Greeks Second Order â
Pro
GET
http://127.0.0.1:25510/v2/hist/option/greeks_second_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculated using the option and underlying midpoint price. If an interval size is specified
(
highly recommended
), the option quote used in the calculation follows the same
rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint. The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/greeks_second_order?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000 (http://127.0.0.1:25510/v2/hist/option/greeks_second_order?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","bid","ask","gamma","vanna","charm","vomma","veta","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  35100000,
  8.7,
  8.75,
  0.0269,
  -0.5823,
  10.02,
  13.032,
  -0.0149,
  0.3867,
  0.0001,
  35100000,
  178.21,
  20230911
]
[
  36000000,
  8.5,
  8.55,
  0.0277,
  -0.5923,
  10.0699,
  13.0622,
  -0.0157,
  0.3823,
  0,
  36000000,
  178,
  20230911
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-greeks_third_order.html

# Greeks Third Order â
Pro
GET
http://127.0.0.1:25510/v2/hist/option/greeks_third_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculated using the option and underlying midpoint price. If an interval size is specified
(
highly recommended
), the option quote used in the calculation follows the same
rules as the
quote (https://http-docs.thetadata.us/operations/get-hist-option-quote)
endpoint. The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/greeks_third_order?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000 (http://127.0.0.1:25510/v2/hist/option/greeks_third_order?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","bid","ask","speed","zomma","color","ultima","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  36000000,
  8.5,
  8.55,
  0,
  0,
  -0.0076,
  -56.3025,
  0.3823,
  0,
  36000000,
  178,
  20230911
]
[
  36900000,
  8.2,
  8.25,
  0,
  0,
  -0.0077,
  -59.0901,
  0.3774,
  0,
  36900000,
  177.68,
  20230911
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-implied_volatility.html

# Implied Volatility â
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/implied_volatility
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns implied volatilies calculated using the national best bid, mid, and ask price
of the option respectively. The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/implied_volatility?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911 (http://127.0.0.1:25510/v2/hist/option/implied_volatility?root=AAPL&exp=20230915&strike=170000&right=C&start_date=20230911&end_date=20230911)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","bid","bid_implied_vol","midpoint","implied_vol","ask","ask_implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  35100000,
  8.7,
  0.3808,
  8.72,
  0.3867,
  8.75,
  0.3945,
  0,
  35100000,
  178.21,
  20230911
]
[
  36000000,
  8.5,
  0.3769,
  8.52,
  0.3823,
  8.55,
  0.3906,
  0,
  36000000,
  178,
  20230911
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-ohlc.html

# OHLC â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/ohlc
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Aggregated OHLC bars that use
SIP rules (https://http-docs.thetadata.us/Articles/Data-And-Requests/OHLC-EOD)
for each bar. Time timestamp of the bar represents the opening time of the bar. For a
trade to be part of the bar:
bar timestamp
<=
trade time
<
bar timestamp + ivl
, where ivl is the
specified interval size in milliseconds.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/ohlc?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103&ivl=900000 (http://127.0.0.1:25510/v2/hist/option/ohlc?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Required
Â -
The interval size in milliseconds. 1 minute intervals is
60000
.
Type:
integer
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","open","high","low","close","volume","count","date"]
Example
[
  45000000,
  6.4,
  6.4,
  6.05,
  6.35,
  47,
  14,
  20231103
]
[
  45900000,
  6.35,
  6.4,
  5.95,
  6.25,
  65,
  21,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-open_interest.html

# Open Interest â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/open_interest
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Open Interest is normally reported once per day by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at approximately
06:30 ET. A new open interest message might not be sent by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if there is no open interest for the option
contract. The reported open interest represents the open interest at the end of the previous
trading day.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/open_interest?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231015&end_date=20231103 (http://127.0.0.1:25510/v2/hist/option/open_interest?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231015&end_date=20231103)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","open_interest","date"]
Example
[
  23406000,
  1575,
  20231016
]
[
  23405000,
  1494,
  20231017
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-quote.html

# Quotes â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns every NBBO quote reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
. If the
ivl
parameter is specified, the quote for each interval represents the last quote
at the interval's timestamp.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/quote?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103&ivl=900000 (http://127.0.0.1:25510/v2/hist/option/quote?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103&ivl=900000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day", "bid_size", "bid_exchange", "bid", "bid_condition", "ask_size", "ask_exchange", "ask", "ask_condition", "date"]
Example
[
  35100000,
  38,
  69,
  5.4,
  50,
  21,
  69,
  5.6,
  50,
  20231103
]
[
  36000000,
  24,
  60,
  5.35,
  50,
  31,
  60,
  5.5,
  50,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-trade.html

# Trades â
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
. Trade condition
mappings can be found
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Trade-Conditions.html)
. Extended trade conditions are
not reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
for options, so they can be ignored.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/trade?root=AAPL&exp=20231103&strike=150000&right=C&start_date=20231103&end_date=20231103 (http://127.0.0.1:25510/v2/hist/option/trade?root=AAPL&exp=20231103&strike=150000&right=C&start_date=20231103&end_date=20231103)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","date"]
Example
[
  43860664,
  602567584,
  255,
  255,
  255,
  255,
  125,
  1,
  43,
  5.84,
  0,
  1,
  0,
  0,
  20240116
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-trade_greeks.html

# Trade Greeks â
Pro
GET
http://127.0.0.1:25510/v2/hist/option/trade_greeks
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculates greeks for every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
perf_boost
can be specified to
true
to improve the speed of this request by using 1 second intervals for the underlying quotes
instead of tick level quotes.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/trade_greeks?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103 (http://127.0.0.1:25510/v2/hist/option/trade_greeks?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
perf_boost
Â -
If true: 1 second intervals for the underlying equity will be used to calcualte the stock price at the time of each option trade instead of using  tick-level equity NBBO. This significantly improves performance as there are much less rows of data that have to be processed per request. This flag only works with the trade greeks endpoints.
Type:
boolean
(Default: false)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","delta","theta","vega","rho","epsilon","lambda","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  34200165,
  -705520992,
  255,
  255,
  255,
  255,
  130,
  2,
  6,
  4.48,
  0,
  7,
  0,
  0,
  0.8719,
  -2.6805,
  0.7393,
  0.0605,
  -0.0624,
  33.9135,
  1.0789,
  0,
  34200164,
  174.23,
  20231103
]
[
  34200166,
  -705520988,
  255,
  255,
  255,
  255,
  130,
  1,
  6,
  4.58,
  0,
  3,
  0,
  0,
  0.8458,
  -3.3902,
  0.8385,
  0.0586,
  -0.0605,
  32.1801,
  1.2054,
  0,
  34200164,
  174.23,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-trade_greeks_second_order.html

# Trade Greeks Second Order â
Pro
GET
http://127.0.0.1:25510/v2/hist/option/trade_greeks_second_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculates greeks for every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
perf_boost
can be specified to
true
to improve the speed of this request by using 1 second intervals for the underlying quotes
instead of tick level quotes.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/trade_greeks_second_order?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103 (http://127.0.0.1:25510/v2/hist/option/trade_greeks_second_order?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
perf_boost
Â -
If true: 1 second intervals for the underlying equity will be used to calcualte the stock price at the time of each option trade instead of using  tick-level equity NBBO. This significantly improves performance as there are much less rows of data that have to be processed per request. This flag only works with the trade greeks endpoints.
Type:
boolean
(Default: false)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","gamma","vanna","charm","vomma","veta","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  34200165,
  -705520992,
  255,
  255,
  255,
  255,
  130,
  2,
  6,
  4.48,
  0,
  7,
  0,
  0,
  0.0549,
  -0.2161,
  283.1678,
  0.8668,
  -0.0004,
  1.0789,
  0,
  34200164,
  174.23,
  20231103
]
[
  34200166,
  -705520988,
  255,
  255,
  255,
  255,
  130,
  1,
  6,
  4.58,
  0,
  3,
  0,
  0,
  0.0557,
  -0.1958,
  286.7181,
  0.7047,
  -0.0004,
  1.2054,
  0,
  34200164,
  174.23,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-trade_greeks_third_order.html

# Trade Greeks Third Order â
Pro
GET
http://127.0.0.1:25510/v2/hist/option/trade_greeks_third_order
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Calculates greeks for every trade reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
.
The underlying price represents whatever the last underlying price was at the
ms_of_day
field. You can read more about how Theta Data calculates greeks
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/Option-Greeks)
.
perf_boost
can be specified to
true
to improve the speed of this request by using 1 second intervals for the underlying quotes
instead of tick level quotes.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/trade_greeks_third_order?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103 (http://127.0.0.1:25510/v2/hist/option/trade_greeks_third_order?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231103&end_date=20231103)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
perf_boost
Â -
If true: 1 second intervals for the underlying equity will be used to calcualte the stock price at the time of each option trade instead of using  tick-level equity NBBO. This significantly improves performance as there are much less rows of data that have to be processed per request. This flag only works with the trade greeks endpoints.
Type:
boolean
(Default: false)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","speed","zomma","color","ultima","implied_vol","iv_error","ms_of_day2","underlying_price","date"]
Example
[
  34200165,
  -705520992,
  255,
  255,
  255,
  255,
  130,
  2,
  6,
  4.48,
  0,
  7,
  0,
  0,
  0,
  0,
  -0.0001,
  -1.3943,
  1.0789,
  0,
  34200164,
  174.23,
  20231103
]
[
  34200166,
  -705520988,
  255,
  255,
  255,
  255,
  130,
  1,
  6,
  4.58,
  0,
  3,
  0,
  0,
  0,
  0,
  -0.0002,
  -1.1619,
  1.2054,
  0,
  34200164,
  174.23,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-hist-option-trade_quote.html

# Trade Quote â
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/trade_quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns every
trade (https://http-docs.thetadata.us/operations/get-hist-option-trade)
reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
paired with the last NBBO quote
reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at the time of trade. A quote
is matched with a trade if its timestamp
<=
the trade timestamp. To
match trades with quotes timestamps that are
<
the trade timestamp, specify the
exclusive
parameter to
true
. After thorough testing, we have determined that using
exclusive=true
might yield better results for various applications.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/trade_quote?root=AAPL&exp=20231103&strike=150000&right=C&start_date=20231103&end_date=20231103 (http://127.0.0.1:25510/v2/hist/option/trade_quote?root=AAPL&exp=20231103&strike=150000&right=C&start_date=20231103&end_date=20231103)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
exclusive
Â -
If you prefer to match quotes with timestamps that are < the trade timestamp, specify this  parameter to true. This parameter only works with the trade_quote endpoint.
Type:
boolean
(Default: false)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","ms_of_day2","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
[
  34200150,
  -705522277,
  255,
  255,
  255,
  255,
  130,
  2,
  6,
  25.05,
  0,
  7,
  0,
  0,
  34200126,
  10,
  9,
  22.8,
  50,
  1,
  6,
  25.75,
  50,
  20231103
]
[
  34221163,
  -701980016,
  255,
  255,
  255,
  255,
  18,
  1,
  65,
  23.4,
  0,
  5,
  0,
  0,
  34221163,
  133,
  69,
  23.4,
  50,
  1,
  47,
  26.15,
  50,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-snapshot-option-ohlc.html

# OHLC â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/snapshot/option/ohlc
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last ohlc of an option contract for the trading day.
You might need to change the default expiration date to a different date if it is past the current date.
Want a snapshot for an entire chain? (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-ohlc)
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/snapshot/option/ohlc?root=AAPL&exp=20260116&right=C&strike=275000 (http://127.0.0.1:25510/v2/snapshot/option/ohlc?root=AAPL&exp=20260116&right=C&strike=275000)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","open","high","low","close","volume","count","date"]
Example
[
  57381579,
  14.25,
  14.25,
  13.9,
  14.15,
  2090,
  54,
  20250103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-snapshot-option-open_interest.html

# Open Interest â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/snapshot/option/open_interest
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve the last open interest message of an option contract.
Open interest is reported around 06:30 ET every morning by OPRA and reflects the open interest at the the of the previous trading day.
You might need to change the default expiration date to a different date if it is past the current date.
Want a snapshot for an entire chain? (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-open_interest)
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/snapshot/option/open_interest?root=AAPL&exp=20260116&right=C&strike=275000 (http://127.0.0.1:25510/v2/snapshot/option/open_interest?root=AAPL&exp=20260116&right=C&strike=275000)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","open_interest","date"]
Example
[
  23400000,
  3773,
  20250103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-snapshot-option-quote.html

# Quotes â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/snapshot/option/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve a real-time last NBBO quote of an option contract.
You might need to change the default expiration date to a different date if it is past the current date.
Want a snapshot for an entire chain? (https://http-docs.thetadata.us/operations/get-bulk_snapshot-option-quote)
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/snapshot/option/quote?root=AAPL&exp=20260116&right=C&strike=275000 (http://127.0.0.1:25510/v2/snapshot/option/quote?root=AAPL&exp=20260116&right=C&strike=275000)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day", "bid_size", "bid_exchange", "bid", "bid_condition", "ask_size", "ask_exchange", "ask", "ask_condition", "date"]
Example
[
  57599925,
  14,
  65,
  14.05,
  50,
  5,
  4,
  14.4,
  50,
  20250103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-snapshot-option-trade.html

# Trade â
Standard
Pro
GET
http://127.0.0.1:25510/v2/snapshot/option/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Retrieve the real-time last trade of an option contract.
You might need to change the default expiration date to a different date if it is past the current date.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/snapshot/option/trade?root=AAPL&exp=20260116&right=C&strike=275000 (http://127.0.0.1:25510/v2/snapshot/option/trade?root=AAPL&exp=20260116&right=C&strike=275000)
This endpoint will return no data if the market was closed for the day. Theta Data resets the snapshot cache at midnight ET every night.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","size","condition","price","date"]
Example
[
  57381579,
  846283647,
  3,
  18,
  14.15,
  20250103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-bulk_snapshot-stock-quote.html

# Bulk Quote Snapshot â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_snapshot/stock/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns a real-time last BBO quote for every stock from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if the account has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
Theta Data resets its snapshot cache at midnight ET every day. This endpoint may not work on a weekend where there were no eligible messages sent over exchange feeds. We recommend using historic requests during the weekend.
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_snapshot/stock/quote?root=0 (http://127.0.0.1:25510/v2/bulk_snapshot/stock/quote?root=0)
## Output Descriptions
Field
Description
ms_of_day
The time of the EOD report. Milliseconds since 00:00:00.000 (midnight) ET.
bid_size
The last BBO bid size.
bid_exchange
The last BBO bid
exchange (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Exchanges.html)
.
bid
The last BBO bid price.
bid_condition
The last BBO bid
condition (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Quote-Conditions.html)
.
ask_size
The last BBO ask size.
ask_exchange
The last BBO ask
exchange (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Exchanges.html)
.
ask
The last BBO ask price.
ask_condition
The last BBO ask
condition (https://http-docs.thetadata.us/Articles/Data-And-Requests/Values/Quote-Conditions.html)
.
date
The date formated as YYYYMMDD.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
venue
Â -
Used to specify the venue of the real time or historic request.
nqb
= Nasdaq Basic;
utp_cta
= merged UTP & CTA.
Type:
string
(Default: nqb)
Enum
nqb, utp_cta
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
{
  "ticks": [
    [
      70840632,
      100,
      29,
      469,
      0,
      100,
      29,
      571.5,
      0,
      20250129
    ]
  ],
  "contract": {
    "root": "CVCO"
  }
}
{
  "ticks": [
    [
      72000032,
      100,
      29,
      22.98,
      0,
      100,
      29,
      38.98,
      0,
      20250129
    ]
  ],
  "contract": {
    "root": "KLXY"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-flat-file-option-eod.html

# EOD â
Pro
GET
http://127.0.0.1:25510/v2/file/option/eod
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Since
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
does not provide a national EOD report for options, Theta Data generates a national EOD report at 17:15 ET each day.
ms_of_day
represents the time of day the report was generated and
ms_of_day2
represents the time of the last trade.
The quote in the response represents the last NBBO reported by OPRA at the time of report generation.
You can read more about EOD & OHLC data
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/OHLC-EOD)
.
Expected response time: ~1 minute
Expected File Size: ~150 MB
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/file/option/eod?start_date=20250512 (http://127.0.0.1:25510/v2/file/option/eod?start_date=20250512)
## Parameters â
### Query Parameters
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
## Responses â
200
OK
Content-Type
text/plain
Schema
string
Example
C:\Users\userName\ThetaData\ThetaTerminal\downloads\OPTION-EOD-20250512.csv
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-flat-file-option-open-interest.html

# Open Interest â
Pro
GET
http://127.0.0.1:25510/v2/file/option/open_interest
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Open Interest is reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at approximately 06:30 ET. A new open interest message might not be sent by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if there is no open interest for the option contract. The reported open interest represents the open interest at the end of the previous trading day.
Expected response time: ~1 minute
Expected File Size: ~50 MB
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/file/option/open_interest?start_date=20250512 (http://127.0.0.1:25510/v2/file/option/open_interest?start_date=20250512)
## Parameters â
### Query Parameters
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
## Responses â
200
OK
Content-Type
text/plain
Schema
string
Example
C:\Users\userName\ThetaData\ThetaTerminal\downloads\OPTION-OPEN_INTEREST-20250512.csv
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-flat-file-option-trade-quote.html

# Trade Quote â
Pro
GET
http://127.0.0.1:25510/v2/file/option/trade_quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Returns every
trade (https://http-docs.thetadata.us/operations/get-hist-option-trade)
reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
paired with the last NBBO quote reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at the time of trade.
A quote is matched with a trade if its timestamp
<
the trade timestamp.
Expected response time: ~3 minutes
Expected File Size: ~1.2 GB
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/file/option/trade_quote?start_date=20250512 (http://127.0.0.1:25510/v2/file/option/trade_quote?start_date=20250512)
## Parameters â
### Query Parameters
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
## Responses â
200
OK
Content-Type
text/plain
Schema
string
Example
C:\Users\userName\ThetaData\ThetaTerminal\downloads\OPTION-TRADE_QUOTE-20250512.csv
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-flat-file-stock-trade-quote.html

# Trade Quote â
Pro
GET
http://127.0.0.1:25510/v2/file/stock/trade_quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns every trade reported by
UTP & CTA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
paired with the last BBO quote reported by
UTP or CTA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at the time of trade.
A quote is matched with a trade if its timestamp
<
the trade timestamp.
Expected response time: ~30 minutes
Expected File Size: ~14 GB
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/file/stock/trade_quote?start_date=20250512 (http://127.0.0.1:25510/v2/file/stock/trade_quote?start_date=20250512)
## Parameters â
### Query Parameters
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
## Responses â
200
OK
Content-Type
text/plain
Schema
string
Example
C:\Users\userName\ThetaData\ThetaTerminal\downloads\STOCK-TRADE_QUOTE-20250512.csv
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-hist-stock-quote.html

# Quotes â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/stock/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns every NBBO quote reported by
UTP and CTA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
. If the
ivl
parameter is specified, the quote for each interval represents the last quote
prior to the interval's timestamp. Set the
venue
parameter to
nqb
to access
current-day real-time historic data from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if the account
has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/stock/quote?root=AAPL&start_date=20240102&end_date=20240102&ivl=60000 (http://127.0.0.1:25510/v2/hist/stock/quote?root=AAPL&start_date=20240102&end_date=20240102&ivl=60000)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
ivl
Â -
The interval size in milliseconds. 1 minute intervals is
60000
. Omitting this value or setting it to
0
will provide tick-level data instead of aggregated / intervalized data.
Type:
integer
(Default: 0)
rth
Â -
If this value is set to
false
and the request is for aggregated / intervalized data, the response will contain intervals from 00:00:000 ET to 23:59:999 ET. If the
ivl
is
0
or is unspecified, then rth will be forced to
false
. This means that all data for the day, even if it was outside regular trading hours would be returned.  The default behavior is to only return data during regular trading hours (09:30:00.000 ET to 16:00.000 ET).
Type:
boolean
(Default: true)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
venue
Â -
Used to specify the venue of the real time or historic request.
nqb
= Nasdaq Basic;
utp_cta
= merged UTP & CTA.
Type:
string
(Default: nqb)
Enum
nqb, utp_cta
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day", "bid_size", "bid_exchange", "bid", "bid_condition", "ask_size", "ask_exchange", "ask", "ask_condition", "date"]
Example
[
  35100000,
  38,
  69,
  5.4,
  50,
  21,
  69,
  5.6,
  50,
  20231103
]
[
  36000000,
  24,
  60,
  5.35,
  50,
  31,
  60,
  5.5,
  50,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-hist-stock-trade.html

# Trades â
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/stock/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns every trade reported by
UTP & CTA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
. Set the
venue
parameter to
nqb
to access
current-day real-time historic data from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if the account
has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/stock/trade?root=AAPL&start_date=20240102&end_date=20240102 (http://127.0.0.1:25510/v2/hist/stock/trade?root=AAPL&start_date=20240102&end_date=20240102)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
start_time
Â -
If specified, the response will include all ticks on or after this number of milliseconds since midnight ET.
Type:
string
end_time
Â -
If specified, the response will include all ticks on or before this number of milliseconds since midnight ET.
Type:
string
venue
Â -
Used to specify the venue of the real time or historic request.
nqb
= Nasdaq Basic;
utp_cta
= merged UTP & CTA.
Type:
string
(Default: nqb)
Enum
nqb, utp_cta
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","date"]
Example
[
  14400004,
  1,
  32,
  255,
  1,
  115,
  1,
  5,
  65,
  191.68,
  7,
  0,
  0,
  0,
  20240102
]
[
  14400004,
  2,
  32,
  255,
  1,
  115,
  1,
  20,
  65,
  191.68,
  7,
  0,
  0,
  0,
  20240102
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-list-contracts-option.html

# List Contracts â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/list/contracts/option/{req}
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Lists all contracts that were traded or quoted on a particular date.
List Contacts is updated real-time.
If the
root
parameter is specified, the returned contracts will be filtered to match the root.
Multiple roots can be specified by separating them with commas such as
root=AAPL,SPY,AMD
This endpoint is updated real-time.
Sample data contains partial output of the request as the full response to the request is too large to display on this webpage.
## Throttle
A mandatory 500 millisecond overhead is applied to this request
to limit bandwidth consumption. This type of request should increase your overall throughput as you will know exactly what is available for each trading day. If the 500 millisecond overhead is an issue, please contact support and they can remove it depending on the circumstances.
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
List all traded contracts
http://127.0.0.1:25510/v2/list/contracts/option/trade?start_date=20230512 (http://127.0.0.1:25510/v2/list/contracts/option/trade?start_date=20230512)
List all quoted contracts
http://127.0.0.1:25510/v2/list/contracts/option/quote?start_date=20230512 (http://127.0.0.1:25510/v2/list/contracts/option/quote?start_date=20230512)
List all quoted contracts with root filter
http://127.0.0.1:25510/v2/list/contracts/option/quote?start_date=20230512&root=AAPL,SPY (http://127.0.0.1:25510/v2/list/contracts/option/quote?start_date=20230512&root=AAPL,SPY)
List all open interest contracts
http://127.0.0.1:25510/v2/list/contracts/option/open_interest?start_date=20230512 (http://127.0.0.1:25510/v2/list/contracts/option/open_interest?start_date=20230512)
## Parameters â
### Path Parameters
req
Required
Â -
The request type.
Type:
string
Enum
trade, quote
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
start_date
Required
Â -
The date to list all contracts for. Formatted as YYYYMMDD.
Type:
string
(Default: 20230512)
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["root", "expiration", "strike", "right"].
Example
[
  "AAPL",
  20230616,
  260000,
  "P"
]
[
  "AAPL",
  20230616,
  260000,
  "C"
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-snapshot-stock-quote.html

# Quote Snapshot â
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/snapshot/stock/quote
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns a real-time last BBO quote from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if the account has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
Returns a 15-minute delayed NBBO quote from the
UTP & CTA feeds (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
account has the
stocks value subscription (https://www.thetadata.net/subscribe#stocks)
subscription.
Theta Data resets its snapshot cache at midnight ET every day. This endpoint may not work on a weekend where there were no eligible messages sent over exchange feeds. We recommend using historic requests during the weekend.
Want a snapshot for an entire chain? (https://http-docs.thetadata.us/operations/get-v2-bulk_snapshot-stock-quote)
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/snapshot/stock/quote?root=AAPL (http://127.0.0.1:25510/v2/snapshot/stock/quote?root=AAPL)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
venue
Â -
Used to specify the venue of the real time or historic request.
nqb
= Nasdaq Basic;
utp_cta
= merged UTP & CTA.
Type:
string
(Default: nqb)
Enum
nqb, utp_cta
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day", "bid_size", "bid_exchange", "bid", "bid_condition", "ask_size", "ask_exchange", "ask", "ask_condition", "date"]
Example
[
  35100000,
  38,
  69,
  5.4,
  50,
  21,
  69,
  5.6,
  50,
  20231103
]
[
  36000000,
  24,
  60,
  5.35,
  50,
  31,
  60,
  5.5,
  50,
  20231103
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/get-v2-snapshot-stock-trade.html

# Trade Snapshot â
Standard
Pro
GET
http://127.0.0.1:25510/v2/snapshot/stock/trade
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns a real-time last trade from the
Nasdaq Basic feed (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if the account has a
stocks standard or pro subscription (https://www.thetadata.net/subscribe#stocks)
.
Theta Data resets its snapshot cache at midnight ET every day. This endpoint may not work on a weekend where there were no eligible messages sent over exchange feeds. We recommend using historic requests during the weekend.
## Sample URL
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/snapshot/stock/trade?root=AAPL (http://127.0.0.1:25510/v2/snapshot/stock/trade?root=AAPL)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
venue
Â -
Used to specify the venue of the real time or historic request.
nqb
= Nasdaq Basic;
utp_cta
= merged UTP & CTA.
Type:
string
(Default: nqb)
Enum
nqb, utp_cta
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","sequence","ext_condition1","ext_condition2","ext_condition3","ext_condition4","condition","size","exchange","price","condition_flags","price_flags","volume_type","records_back","date"]
Example
[
  14400004,
  1,
  32,
  255,
  1,
  115,
  1,
  5,
  65,
  191.68,
  7,
  0,
  0,
  0,
  20240102
]
[
  14400004,
  2,
  32,
  255,
  1,
  115,
  1,
  20,
  65,
  191.68,
  7,
  0,
  0,
  0,
  20240102
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/hist-option-eod.html

# EOD Report â
Free
Value
Standard
Pro
GET
http://127.0.0.1:25510/v2/hist/option/eod
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Since
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
does not provide a national EOD
report for options, Theta Data generates a national EOD report at 17:15 ET each day.
ms_of_day
represents the time of day the report was generated and
ms_of_day2
represents the time of the last trade. The quote in the response
represents the last NBBO reported by OPRA at the time of report generation.
You can read more about EOD & OHLC data
here (https://http-docs.thetadata.us/Articles/Data-And-Requests/OHLC-EOD)
.
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/hist/option/eod?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231102&end_date=20231102 (http://127.0.0.1:25510/v2/hist/option/eod?root=AAPL&exp=20231103&strike=170000&right=C&start_date=20231102&end_date=20231102)
The quote fields (bid / ask info) may not be available prior to 2023-12-01. We will expose further history for the EOD quote in the near future.
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
strike
Required
Â -
The strike price in 1/10th of a cent. A $170.00 strike price would be 170000.
Type:
integer
right
Required
Â -
The right of the option. 'C' for call; 'P' for put.
Type:
string
(Default: C)
Enum
C, P
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contracts, where each item is an array of values matching the
header.format
; ["ms_of_day","ms_of_day2","open","high","low","close","volume","count","bid_size","bid_exchange","bid","bid_condition","ask_size","ask_exchange","ask","ask_condition","date"]
Example
[
  62573163,
  57590486,
  6.72,
  8.55,
  6.55,
  8.51,
  4684,
  1013,
  11,
  43,
  7.85,
  50,
  8,
  60,
  8.75,
  50,
  20231102
]
[
  63174002,
  57590486,
  6.72,
  8.55,
  6.55,
  8.51,
  4684,
  1013,
  11,
  43,
  7.85,
  50,
  8,
  60,
  8.75,
  50,
  20231102
]
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/operations/hist-option-open_interest.html

# Bulk Open Interest â
Standard
Pro
GET
http://127.0.0.1:25510/v2/bulk_hist/option/open_interest
REQUIRED
The Theta Terminal must be running to access data.
## Behavior
Returns the data for all contracts that share the same provided root and expiration.
Open Interest is reported by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
at approximately
06:30 ET. A new open interest message might not be sent by
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs)
if there is no open interest for the option
contract. The reported open interest represents the open interest at the end of the previous
trading day.
Set
exp
to
0
if you want
to retrieve data for every option that shares the same
root
. (note: Any
exp=0
must be requested day by day)
## Sample URL & Code
Paste the URL below into your browser while the Theta Terminal is running.
http://127.0.0.1:25510/v2/bulk_hist/option/open_interest?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110 (http://127.0.0.1:25510/v2/bulk_hist/option/open_interest?root=AAPL&exp=20231117&start_date=20231110&end_date=20231110)
## Parameters â
### Query Parameters
root
Required
Â -
The symbol of the security. Option underlyings for indices might have
special tickers (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs#index-option-symbology)
.
Type:
string
exp
Required
Â -
The expiration date of the option contract formatted as YYYYMMDD.
Type:
integer
start_date
Required
Â -
The start date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
end_date
Required
Â -
The end date (inclusive) of the request formatted as YYYYMMDD.
Type:
integer
use_csv
Â -
Output is in comma-separated values if
true
, legacy JSON if
false
.
Type:
boolean
(Default: false)
pretty_time
Â -
If this value is set to
true
, ms_of_day and date will take the format of 09:30:00.000 and 2020-01-01; if set to
false
, ms_of_day will return the timestamp in milliseconds since midnight EST.
Type:
boolean
(Default: false)
## Responses â
200
OK
Content-Type
application/json
Schema
JSON
header
object
The response to the request made. If there is a caught error, the error_type field won't be null.
response
array
A list of contract objects, each containing tick data and contract details; ["ms_of_day","open_interest","date"]
Example
{
  "ticks": [
    [
      23400000,
      0,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 50000,
    "right": "C"
  }
}
{
  "ticks": [
    [
      23404000,
      4910,
      20231110
    ]
  ],
  "contract": {
    "root": "AAPL",
    "expiration": 20231117,
    "strike": 50000,
    "right": "P"
  }
}
## Sample Code
Python
JavaScript
py


---

# Source: https://http-docs.thetadata.us/Articles/Data-And-Requests/Making-Requests.html#trade-sequences

# Data Availability â
TIP
Check our website as we are continually adding more data for customers!
## Historical Greeks (options) & Equities Availability â
Equities data is split up into 3 feeds (see
The SIPs (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html)
for more information):
CTA-A (Administered by NYSE)
CTA-B (Administered by NYSE)
UTP-C (Administered by Nasdaq)
Theta Data receives market data for all of these feeds listed above. The 10 years of history in the system is only for the
UTP-C
tape, which covers most, but not all tickers. Data prior to
2020-01-01
for some tickers does not exist. For instance,
$SPY
is not included in the UTP tape, so there is no historical stock data or greeks data prior to
2020-01-01
for it. We are continually adding more data, so check back soon or contact
Support (mailto:support@thetadata.net)
.
## Historical Greeks Availability: Index Options â
Nasdaq indices are currently not included, but will be added at a later date. Similar to equities, our Greeks data on index options (v2 requests must be used) goes back to
2017-01-01
. At the moment there are no ongoing updates or history for the Nasdaq Indices Feed, which includes $NDX. This means that $NDX Greeks aren't available, however you can supply the
under_price
parameter to greeks snapshots, which will force Theta Data to use your supplied price.
## Historical Trades, EOD, OHLC: Options â
Trades, EOD, and OHLC options data is available as far back at
2012-06-01
.
## Listing bulk dates â
At this time bulk date listing is only supported for quotes / trades. Most requests use the same exact dates as quotes or trades, so there shouldn't be a reason to list dates for other request types.
## Historical ETH OPRA data â
Extended Trading hours trades (impacts EOD data as well) and quotes are available from 2015 until 2018. However, from 2019 until December 2022, there is no ETH data for quotes and trades. After January 2022, Theta Data has full GTH / ETH coverage. Unfortunately this is a limitation of the data vendor we purchased from. ETH quotes & trades are only for SPX, VIX, DJI, and RUT options.
NOTE
This has no impact on equity options.
## Error-Handling â
When there is an error making a request, a text response is returned that describes the error. The http response code of the response will correspond to the errors defined below. If the request was successful, the http code
200
is returned. It is imperative that your application properly handles error codes like
DISCONNECTED
and
NO_DATA
.
Http Code
Error Name
Description
200
OKAY, NO ERROR
No error.
404
NO_IMPL
There is no implementation of this request. Either the request you are making is invalid or you are using an outdated Theta Terminal version.
429
OS_LIMIT
The operating system is throttlting your requests. This happens when making a large amount of small low latency requests. An easy solution to this error is to retry the request until you no longer get this error code.
470
GENERAL
A general error.
471
PERMISSION
Your account does not have the permissions required to execute the request.
472
NO_DATA
There was no data found for the specified request.
473
INVALID_PARAMS
The parameters / syntax of the request is invalid. Sometimes updating your Theta Terminal to the
latest version (https://download-unstable.thetadata.us)
could resolve this.
474
DISCONNECTED
Connection has been lost to Theta Data MDDS.
475
TERMINAL_PARSE
There was an issue parsing the request after it was received.
476
WRONG_IP
The IP address does not match the IP address that the first request was made on. Make sure you use the same ip to make requests while the terminal is running. You cannot switch between
127.0.0.1
and
localhost
.
477
NO_PAGE_FOUND
The page does not exist or expired.
570
LARGE_REQUEST
The request asking for too much data. Follow these
guidelines (https://http-docs.thetadata.us/Articles/Performance-And-Tuning/Request-Sizing.html)
.
571
SERVER_STARTING
The server is forcibly and intentionally restarting.
572
UNCAUGHT_ERROR
Reach out to support with the exact request you made.
Download as CSV (https://www.dropbox.com/scl/fi/c1zbaq8e45djf5zb8cy26/ErrorCodes.csv?rlkey=ryepbxvk6zmtcwq3n2s3wrf0h&dl=1)
## Trade Sequences â
The trade
sequence
overflows once it reaches 2,147,483,647 (maximum value of a signed 32-bit integer). When the exchange sequence reaches -1, that means the sequence is 4,294,967,294. Once the sequence reaches 0 for a second time (it starts at 0), that means the
exchange sequence has overflowed (https://cdn.cboe.com/resources/release_notes/2020/Cboe-Options-Exchanges-Introduce-Sequence-Rollover-Capability-for-Multicast-Depth-of-Book-PITCH-Feeds.pdf)
.


---

# Source: https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#options-opra

A SIP (Securities Information Processor) is a regulated entity that consolidates all trades and quotes from all exchanges. This allows brokers to execute orders at the National Best Bid and Offer (NBBO).
## Options: OPRA â
OPRA (Options Price Reporting Authority) provides a nationally consolidated quote and trade feed for US equity and index options. OPRA is administered by CBOE. OPRA data vendors are required to pay redistribution fees. Theta Data receives every NBBO quote and trade from the OPRA feed all in real-time with latencies averaging under 3ms. Most OPRA data vendors filter NBBO quotes because they cannot handle the incredible amount of data coming in. There are millions of quotes sent by OPRA in the first second of the market opening.
### OPRA GTH â
As part of the
OPRA (https://http-docs.thetadata.us/Articles/Data-And-Requests/The-SIPs.html#options-opra)
Global Trading Hours (GTH), options for
SPX
,
VIX
and
XSP
are traded outside regular trading hours (RTH). All times are eastern time. The last OPRA GTH session of the week starts at 20:15 ET every Sunday.
OPRA Global Trading Hours (GTH) will extend its daily ending hours of operation effective trade date Monday, August 26, 2024 (starting hours of operation for Sunday night session, August 25, 2024), by 10 minutes, to 9:25 A.M from 9:15 A.M., ET.
Session
Start Time
End Time
Begin GTH Order Acceptance (SPX, VIX, XSP)
20:00
n/a
Global Trading Hours (SPX, VIX, XSP)
20:15
09:25 (next day)
Begin RTH Order Acceptance
07:30
n/a
Regular Trading Hours (RTH)
09:30
16:15
Curb
16:15
17:00
Source: CBOE Hours & Holidays (https://www.cboe.com/about/hours/us-options/)
### OPRA Extended Trading Hours: â
As part of extended trading hours the following symbols are traded until 16:15 ET.
```text
AUM, AUX, BACD, BPX, BRB, BSZ, BVZ, CDD, CITD, DBA, DBB, DBC, DBO, DBS, DIA, DJX, EEM, EFA, EUI, EUU, GAZ, GBP, GSSD, IWM, IWN, IWO, IWV, JJC, JPMD, KBE, KRE, MDY, MLPN, MNX, MOO, MRUT, MSTD, NDO, NDX, NZD, OEF, OEX, OIL, PZO, QQQ, RUT, RVX, SFC, SKA, SLX, SPX, SPX (PM Expiration), SPY, SVXY, UNG, UUP, UVIX, UVXY, VIIX, VIX, VIXM, VIXY, VXEEM, VXST, VXX, VXZ, XEO, XHB, XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY, XME, XRT, XSP, XSP (AM Expiration), & YUK
```
## Equities: CTA & UTP â
US Equities data has 2 SIPs and 3 different SIP networks.
CTA Network A (Administered by NYSE)
CTA Network B (Administered by NYSE)
UTP Network C (Administered by Nasdaq)
Theta Data receives a 15-minute delayed feed from all of these networks. Theta Data receives a real-time feed from Nasdaq Basic.
CTA Tape A has the following trading hours:
Session
Start Time
End Time
Pre-Opening
06:30
9:30
Core Open Auction
09:30
15:50
123(c) Closing Imbalance Period
15:50
16:00
## Nasdaq Basic â
Nasdaq Basic provides a BBO that is within 1% of the NBBO 99.22% of the time. They also publish a time and sales data feed in real-time. The time and sales information is for orders executed within the Nasdaq execution system as well as trades reported to the FINRA/Nasdaq TRF.
## CBOE Global Indices Feed â
Theta Data is a real-time recipient of the CGIF. Indices such as SPX and VIX are included in this feed.


---

# Source: https://http-docs.thetadata.us/option_trade_sample.zip

_No readable body found._


---

# Source: https://http-docs.thetadata.us/option_quote_sample.zip

_No readable body found._


---

# Source: https://http-docs.thetadata.us/stock_trade_sample.zip

_No readable body found._


---

# Source: https://http-docs.thetadata.us/stock_quote_sample.zip

_No readable body found._
