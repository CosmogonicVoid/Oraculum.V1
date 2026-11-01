"""Manual simulator forms; every mutation is an explicit confirmed POST."""
from .ui import document, esc, money, cards, link, time_text
from .demo_trading import paise, sign
from .contracts import ValidationError
from .dashboard_view import table


def page(report, account, csrf, *, symbol='', confirmation=None, secret=None, message=''):
    body='<div class="research-tabs"><a aria-current="page" href="/sandbox">Manual practice</a><a href="/forward">Automatic strategy</a></div>'
    body+='<div class="notice"><strong>Saved-close simulator · virtual money only.</strong> Trades execute immediately at the latest report’s closing price, even when that price is old. This is practice bookkeeping, not a live or next-session fill. Fees, slippage, dividends, splits and symbol changes are not applied. It does not measure strategy performance.</div>'
    if message:body+='<div class="notice">'+esc(message)+'</div>'
    values={a['symbol']:a.get('metrics',{}).get('close_inr') for a in report['assets']} if report else {}
    marked=0;missing=0;rows=[]
    for stock,pos in sorted(account['positions'].items()):
        try:price=paise(values.get(stock));value=price*pos['quantity'];marked+=value
        except ValidationError:price=None;value=None;missing+=1
        pnl=value-pos['basis'] if value is not None else None
        rows.append(f'<tr><td><a href="{link("/stock",symbol=stock)}">{esc(stock)}</a></td><td class="num">{pos["quantity"]:,}</td><td class="num">{money(pos["basis"]/pos["quantity"]/100)}</td><td class="num">{money(price/100) if price is not None else "Unavailable"}</td><td class="num">{money(pnl/100) if pnl is not None else "Unavailable"}</td><td><a href="{link("/sandbox",symbol=stock)}#ticket">Trade →</a></td></tr>')
    equity=account['cash']+marked
    body+=cards([('Virtual cash',money(account['cash']/100),'Initial virtual balance ₹1,00,000'),('Account equity',money(equity/100) if not missing else 'Incomplete marks','Cash + holdings at latest saved closes'),('Realized P/L',money(account['realized']/100),'Average-cost bookkeeping; no fees')])
    if report:body+=f'<p class="muted">Valuation price session: {esc(report["last_session"])} · report cutoff {esc(time_text(report["as_of"]))}. {missing} holdings lack a current price.</p>'
    if confirmation:
        q=confirmation
        body+='<section class="panel"><h2>Confirm virtual '+esc(q['side'])+'</h2>'
        body+=f'<p><strong>{q["quantity"]:,} × {esc(q["symbol"])} at {money(q["price"]/100)}</strong> · total {money(q["quantity"]*q["price"]/100)}.</p><p>Saved closing price from {esc(q["session"])}. This is not a current executable quote. Confirmation expires in 10 minutes.</p>'
        body+=f'<form method="post" action="/sandbox/confirm"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="quote" value="{esc(sign(q,secret))}"><button type="submit">Confirm virtual {esc(q["side"])}</button> <a href="/sandbox">Cancel</a></form></section>'
    body+='<section class="panel" id="ticket"><h2>Practice trade</h2>'
    if report:
        body+=f'<form method="post" action="/sandbox/preview"><input type="hidden" name="csrf" value="{esc(csrf)}"><div class="trade-fields"><label>Exchange symbol<input name="symbol" maxlength="50" required value="{esc(symbol)}" placeholder="e.g. RELIANCE"></label><label>Side<select name="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Whole shares<input type="number" name="quantity" min="1" max="1000000" step="1" value="1" required></label><button type="submit">Preview virtual trade</button></div></form>'
    else:body+='<p>Run research.cmd to create a saved report first. Your virtual account is created only when you confirm your first trade.</p>'
    body+='</section><section class="panel flush"><div class="section-heading"><h2>Manual holdings</h2></div>'
    body+=table(('Stock','Shares','Average cost','Saved close','Unrealized P/L','Action'),rows,'Manual demo holdings') if rows else '<p class="section-foot">No holdings yet. Preview and confirm a virtual buy above.</p>'
    body+='</section><section class="panel flush"><div class="section-heading"><h2>Trade history · latest 200</h2></div>'
    history=[]
    for t in account['trades']:
        history.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (time_text(t['recorded_at']),t['side'],t['symbol'],t['quantity'],money(t['price']/100),t['session'],money(t['realized']/100)))+'</tr>')
    body+=table(('Recorded','Side','Stock','Shares','Fill price','Price session','Realized P/L'),history,'Manual demo trade history') if history else '<p class="section-foot">No confirmed virtual trades.</p>'
    return document('Demo trading',body+'</section>',active='paper',subtitle='Your practice account · separate from the automatic strategy')
