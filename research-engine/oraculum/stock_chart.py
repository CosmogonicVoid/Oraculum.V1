"""Receipt-pinned raw OHLCV charts. Reads only; missing sessions remain gaps."""
from datetime import date
from pathlib import Path
from .contracts import ValidationError, timestamp
from .local_data import MarketStore
from .ui import esc, link, number, money


def series(folder, report, asset):
    path = Path(folder) / 'market.sqlite3'
    if not path.is_file():
        return {'rows': [], 'missing': 0, 'message': 'No local price cache. Run research.cmd to collect history.'}
    sources = {s['session']: s for s in report['sources']}
    snapshots = MarketStore(path).research_snapshots(start=report['history_start'], end=report['last_session'])
    mapped = {s['session']: s for s in snapshots}
    rows = []
    for session, source in sorted(sources.items()):
        snap = mapped.get(session)
        row = None
        if snap:
            if snap['sha256'] != source['sha256'] or snap['source_id'] != source['source_id'] or snap['received_at'] != source['received_at'] or timestamp(snap['received_at'],'receipt') > timestamp(report['as_of'],'cutoff'):
                raise ValidationError('Chart receipt does not match the saved report')
            row = next((r for r in snap['rows'] if r['symbol'] == asset['symbol']), None)
            if row and asset.get('isin') and row.get('isin') and row['isin'] != asset['isin']:
                row = None
        rows.append({'session': session, **({k: row[k] for k in ('open','high','low','close','volume')} if row else {})})
    tail = []
    for row in rows:
        if 'close' not in row:
            tail = []
            row.update(ma20=None, ma50=None)
            continue
        tail.append(float(row['close']))
        row['ma20'] = sum(tail[-20:])/20 if len(tail)>=20 else None
        row['ma50'] = sum(tail[-50:])/50 if len(tail)>=50 else None
    return {'rows':rows, 'missing':sum('close' not in r for r in rows), 'message':''}


def panel(data, report, asset, *, period='60', kind='candles'):
    if period not in ('20','60','all') or kind not in ('candles','line'):
        raise ValidationError('Invalid chart timeframe or type')
    rows = data['rows'] if period == 'all' else data['rows'][-int(period):]
    body = '<section class="panel flush"><div class="section-heading"><div><h2>Price &amp; volume</h2><p>Raw exchange prices · INR · daily sessions</p></div><div class="actions">'
    for value, label in (('20','20 sessions'),('60','60 sessions'),('all','All saved')):
        body += f'<a class="button {"" if period==value else "secondary"}" href="{link("/stock",report=report["report_id"],symbol=asset["symbol"],period=value,chart=kind)}#price-chart">{label}</a>'
    for value,label in (('candles','Candles'),('line','Close line')):
        body += f'<a class="button {"" if kind==value else "secondary"}" href="{link("/stock",report=report["report_id"],symbol=asset["symbol"],period=period,chart=value)}#price-chart">{label}</a>'
    body += '</div></div><div id="price-chart" class="stock-chart-wrap">'
    valid=[r for r in rows if 'close' in r]
    if not valid:
        return body + '<p class="muted">'+esc(data['message'] or 'No matching history for this stock and report. No prices have been invented.')+'</p></div></section>'
    lows = [float(r['low']) for r in valid]+[r[k] for r in valid for k in ('ma20','ma50') if r[k] is not None]
    highs = [float(r['high']) for r in valid]+[r[k] for r in valid for k in ('ma20','ma50') if r[k] is not None]
    low, high = min(lows), max(highs)
    pad=max((high-low)*.07, high*.005);low-=pad;high+=pad
    maximum=max(r['volume'] for r in valid) or 1
    step=790/max(len(rows),1)
    def x(i):return 65+(i+.5)*step
    def y(v):return 268-(float(v)-low)/(high-low)*235
    body += '<svg class="stock-price-chart" viewBox="0 0 980 400" role="img" aria-labelledby="stock-chart-title stock-chart-desc"><title id="stock-chart-title">'+esc(asset['symbol'])+' daily price and volume</title><desc id="stock-chart-desc">Raw prices and raw volume. Moving averages use 20 or 50 consecutive available sessions. Missing sessions break lines. Exact values are in the table below.</desc>'
    for i in range(5):
        value=low+(high-low)*i/4;py=y(value)
        body+=f'<line x1="65" x2="855" y1="{py:.2f}" y2="{py:.2f}" stroke="#444953"/><text x="866" y="{py+4:.2f}" fill="#c0c6d2" font-size="11">{number(value,2)}</text>'
    for key,color in (('close','#c9d7ff'),('ma20','#e4c285'),('ma50','#a7cdbb')):
        if key=='close' and kind!='line':continue
        segments=[];points=[]
        for i,row in enumerate(rows):
            v=row.get(key)
            if v is None:
                if points:segments.append(points);points=[]
            else:points.append(f'{x(i):.2f},{y(v):.2f}')
        if points:segments.append(points)
        for points in segments:
            if len(points)>1:body+=f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.8"/>'
            else:
                px,py=points[0].split(',');body+=f'<circle cx="{px}" cy="{py}" r="2" fill="{color}"/>'
    for i,row in enumerate(rows):
        if 'close' not in row:continue
        color='#94d7b4' if float(row['close'])>=float(row['open']) else '#f2a1aa'
        px=x(i);w=max(2,min(9,step*.6));vh=row['volume']/maximum*65
        title=esc(f"{row['session']} | O {row['open']} H {row['high']} L {row['low']} C {row['close']} | Volume {row['volume']:,}")
        body+=f'<g tabindex="0" aria-label="{title}"><title>{title}</title>'
        if kind=='candles':
            body+=f'<line x1="{px:.2f}" x2="{px:.2f}" y1="{y(row["high"]):.2f}" y2="{y(row["low"]):.2f}" stroke="{color}"/>'
            top=min(y(row['open']),y(row['close']));height=max(1,abs(y(row['open'])-y(row['close'])))
            body+=f'<rect x="{px-w/2:.2f}" y="{top:.2f}" width="{w:.2f}" height="{height:.2f}" fill="{color}"/>'
        else:body+=f'<circle cx="{px:.2f}" cy="{y(row["close"]):.2f}" r="2.5" fill="{color}"/>'
        body+=f'<rect x="{px-w/2:.2f}" y="{355-vh:.2f}" width="{w:.2f}" height="{vh:.2f}" fill="{color}" opacity=".6"/></g>'
    body+='<text x="65" y="287" fill="#c0c6d2" font-size="11">Volume (shares)</text>'
    body+=f'<text x="866" y="302" fill="#c0c6d2" font-size="10">{maximum:,}</text>'
    for i in sorted({0,len(rows)//2,len(rows)-1}):
        body+=f'<text x="{x(i):.2f}" y="380" text-anchor="middle" fill="#c0c6d2" font-size="11">{esc(rows[i]["session"])}</text>'
    body+='</svg><p class="chart-key"><span>Price</span><span>MA20 · amber</span><span>MA50 · green</span></p></div>'
    body+=f'<div class="section-foot">{len(valid)} observations in {len(rows)} saved sessions. Raw prices are not split/dividend adjusted and may differ from ranking metrics. Missing sessions and symbol/identity changes remain gaps. Available history is limited to this report’s cached receipts.</div>'
    body+='<details><summary>Exact chart values</summary><div class="scroll"><table><thead><tr><th>Session</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>MA20</th><th>MA50</th></tr></thead><tbody>'
    for row in reversed(rows):
        body+='<tr><td>'+esc(row['session'])+'</td>'+''.join('<td class="num">'+(number(row.get(k),0 if k=='volume' else 2) if row.get(k) is not None else '—')+'</td>' for k in ('open','high','low','close','volume','ma20','ma50'))+'</tr>'
    return body+'</tbody></table></div></details></section>'
