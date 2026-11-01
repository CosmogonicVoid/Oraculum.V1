"""Reproducible CC0 historical input preparation. No live-data claims.
Usage: python scripts/prepare-history.py /path/to/download-cache
"""
import csv, datetime as dt, hashlib, io, json, pathlib, sys, urllib.request, zipfile
root=pathlib.Path(__file__).resolve().parents[1]
cache=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else root/'work'/'data-cache'
cache.mkdir(parents=True,exist_ok=True)
sources=[('nifty50-source.zip','rohanrao/nifty50-stock-market-data'),('nse-index-source.zip','vinay20/stock-market-nse-indices-daily-data2000')]
manifest=[]
for filename,ref in sources:
 p=cache/filename
 if not p.exists():
  with urllib.request.urlopen('https://www.kaggle.com/api/v1/datasets/download/'+ref,timeout=60) as response:p.write_bytes(response.read(50_000_000))
 manifest.append({'dataset':'https://www.kaggle.com/datasets/'+ref,'license':'CC0: Public Domain (declared by dataset publisher)','archive_sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
z=zipfile.ZipFile(cache/'nse-index-source.zip');bench={}
for r in csv.DictReader(io.TextIOWrapper(z.open('NSE_Daily_indices_data.csv'))):
 if r['SYMBOL']!='NIFTY':continue
 date=dt.datetime.strptime(r['DATETIME'],'%d-%m-%Y').date().isoformat()
 if '2017-01-01'<=date<='2021-04-30':bench[date]=float(r['CLOSE'])
z=zipfile.ZipFile(cache/'nifty50-source.zip')
meta={r['Symbol']:r for r in csv.DictReader(io.TextIOWrapper(z.open('stock_metadata.csv')))}
replay_dates=sorted(d for d in bench if d>='2021-01-04')
stocks=[];excluded=[]
for filename in z.namelist():
 if filename in ['NIFTY50_all.csv','stock_metadata.csv'] or not filename.endswith('.csv'):continue
 rows=list(csv.DictReader(io.TextIOWrapper(z.open(filename))))
 if not rows:excluded.append({'symbol':filename[:-4],'reason':'Empty source file'});continue
 symbol=rows[-1]['Symbol'];m=meta.get(symbol,{})
 bars=[]
 for r in rows:
  date=r['Date']
  if date not in bench:continue
  try:
   vals=[float(r[k]) for k in ['Open','High','Low','Close','Volume']]
   o,h,l,c,v=vals
   if min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c,h):continue
  except (ValueError,TypeError):continue
  bars.append([date,*vals,bench[date]])
 dates={r[0] for r in bars}
 if len(bars)<600 or any(d not in dates for d in replay_dates):excluded.append({'symbol':symbol,'reason':'Insufficient history or incomplete replay dates'});continue
 stocks.append({'symbol':symbol,'name':m.get('Company Name',symbol),'sector':m.get('Industry','Other').title(),'bars':bars})
stocks.sort(key=lambda x:x['symbol'])
(root/'data'/'history.json').write_text(json.dumps(stocks,separators=(',',':')))
info={'id':'nse-2021-cc0-v1','sources':manifest,'history_start':'2017-01-02','history_end':'2021-04-30','replay_start':'2021-01-04','replay_end':'2021-04-30','benchmark':'NIFTY 50 price index (NIFTY in source)','included_stocks':len(stocks),'excluded':excluded,'limitations':['2021-era constituent selection creates survivorship and selection bias.','Raw OHLC prices; dividends and corporate actions are not modeled. Large discontinuities are excluded from model windows, not repaired.','Historical simulation created now; these are not forecasts published in 2021.','No current market feed, no guaranteed predictive edge, no investment recommendations.']}
(root/'data'/'provenance.json').write_text(json.dumps(info,indent=2)+'\n')
print(json.dumps({'stocks':len(stocks),'replay_dates':len(replay_dates),'excluded':excluded,'first':stocks[0]['bars'][0],'last':stocks[0]['bars'][-1]},indent=2))
