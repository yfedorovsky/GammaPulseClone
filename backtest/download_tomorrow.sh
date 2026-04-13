# Run at 11:32 AM ET on April 14, 2026
# Step 1: Finish LITE (partial, ended Aug 2025) + remaining 15 tickers
python -m backtest.download_eodhd --tickers LITE,COHR,AAOI,GLW,CIEN,TSEM,AXTI,ASTS,VOYG,RKLB,SATL,ANET,VRT,NET,SNOW,PLTR --start 2025-01-01 --end 2026-04-14 --delay 0.3 --append

# Step 2: Top up ALL 34 tickers to April 14 (incremental, last few days only)
python -m backtest.download_eodhd --tickers SPY,QQQ,NVDA,TSLA,AAPL,MSFT,AMZN,META,GOOGL,SMH,MU,AMD,AVGO,MRVL,TSM,INTC,LRCX,AMAT,LITE,COHR,AAOI,GLW,CIEN,TSEM,AXTI,ASTS,VOYG,RKLB,SATL,ANET,VRT,NET,SNOW,PLTR --start 2026-04-11 --end 2026-04-14 --delay 0.3 --append

# Step 3: Rebuild spots from Yahoo (free, all 34 tickers, full history)
python -c "
import yfinance as yf; import csv
tickers = ['SPY','QQQ','NVDA','TSLA','AAPL','MSFT','AMZN','META','GOOGL','SMH','MU','AMD','AVGO','MRVL','TSM','INTC','LRCX','AMAT','LITE','COHR','AAOI','GLW','CIEN','TSEM','AXTI','ASTS','VOYG','RKLB','SATL','ANET','VRT','NET','SNOW','PLTR']
with open('data/spots.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['date','ticker','open','high','low','close'])
    for t in tickers:
        try:
            df=yf.download(t,start='2024-04-01',end='2026-04-15',progress=False,auto_adjust=True)
            for idx in df.index:
                o=float(df.loc[idx,'Open'].iloc[0]) if hasattr(df.loc[idx,'Open'],'iloc') else float(df.loc[idx,'Open'])
                h=float(df.loc[idx,'High'].iloc[0]) if hasattr(df.loc[idx,'High'],'iloc') else float(df.loc[idx,'High'])
                l=float(df.loc[idx,'Low'].iloc[0]) if hasattr(df.loc[idx,'Low'],'iloc') else float(df.loc[idx,'Low'])
                c=float(df.loc[idx,'Close'].iloc[0]) if hasattr(df.loc[idx,'Close'],'iloc') else float(df.loc[idx,'Close'])
                w.writerow([idx.strftime('%Y-%m-%d'),t,round(o,2),round(h,2),round(l,2),round(c,2)])
        except: pass
print('Spots rebuilt')
"

# Step 4: Run full 34-ticker grid search
python -m backtest.grid_search --data ./data --tickers SPY,QQQ,NVDA,TSLA,AAPL,MSFT,AMZN,META,GOOGL,SMH,MU,AMD,AVGO,MRVL,TSM,INTC,LRCX,AMAT,LITE,COHR,AAOI,GLW,CIEN,TSEM,AXTI,ASTS,VOYG,RKLB,SATL,ANET,VRT,NET,SNOW,PLTR --start 2024-04-01 --end 2026-04-14 --output grid_full_universe.json
