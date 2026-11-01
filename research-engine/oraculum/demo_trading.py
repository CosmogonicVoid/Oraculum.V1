"""Explicit manual, saved-close practice trades. Separate from strategy evaluation."""
import base64
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
from .contracts import ValidationError

INITIAL = 10_000_000  # paise: INR 100,000


def paise(value):
    try:
        v=Decimal(str(value))
        if not v.is_finite() or v <= 0 or v > 10**9:raise ValueError()
        amount=int((v*100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if amount<=0:raise ValueError()
        return amount
    except (ValueError,ArithmeticError):
        raise ValidationError('No valid saved price for this stock')


def state(folder):
    path=Path(folder)/'manual_demo.sqlite3'
    if not path.is_file():return {'cash':INITIAL,'realized':0,'revision':0,'positions':{},'trades':[]}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA user_version').fetchone()[0]!=83:raise ValidationError('Unrecognized demo account database')
        return _state(db)


def _state(db):
    cash,realized,revision=db.execute('SELECT cash,realized,revision FROM account WHERE id=1').fetchone()
    positions={s:{'quantity':q,'basis':b} for s,q,b in db.execute('SELECT symbol,quantity,basis FROM positions WHERE quantity>0')}
    trades=[dict(zip(('id','recorded_at','side','symbol','quantity','price','session','report','realized'),r)) for r in db.execute('SELECT id,recorded_at,side,symbol,quantity,price,session,report,realized FROM trades ORDER BY rowid DESC LIMIT 200')]
    return dict(cash=cash,realized=realized,revision=revision,positions=positions,trades=trades)


def quote(report, symbol, side, quantity, revision):
    if not report:raise ValidationError('Run research.cmd before practising a trade')
    if side not in ('buy','sell'):raise ValidationError('Choose Buy or Sell')
    if not str(quantity).isdigit() or not 1<=int(quantity)<=1_000_000:raise ValidationError('Quantity must be 1–1,000,000 whole shares')
    asset=next((a for a in report['assets'] if a['symbol']==symbol),None)
    if asset is None:raise ValidationError('Stock is not in the latest saved report')
    return dict(symbol=symbol,side=side,quantity=int(quantity),price=paise(asset.get('metrics',{}).get('close_inr')),session=report['last_session'],report=report['report_id'],revision=revision,id=secrets.token_hex(16),expires=int(time.time())+600)


def validate(account, q):
    if account['revision']!=q['revision']:raise ValidationError('Account changed. Preview this trade again.')
    if q['side']=='buy' and q['quantity']*q['price']>account['cash']:raise ValidationError('Not enough virtual cash')
    if q['side']=='sell' and q['quantity']>account['positions'].get(q['symbol'],{}).get('quantity',0):raise ValidationError('Not enough shares; short selling is disabled')


def sign(q, secret):
    body=base64.urlsafe_b64encode(json.dumps(q,sort_keys=True,separators=(',',':')).encode()).decode()
    return body+'.'+hmac.new(secret,body.encode(),hashlib.sha256).hexdigest()


def verify(token, secret):
    try:
        body,sig=token.split('.')
        if not hmac.compare_digest(sig,hmac.new(secret,body.encode(),hashlib.sha256).hexdigest()):raise ValueError()
        q=json.loads(base64.urlsafe_b64decode(body))
        if q['expires']<time.time():raise ValueError()
        return q
    except (ValueError,KeyError,TypeError):raise ValidationError('Confirmation expired or invalid. Preview again.')


def execute(folder, q, report):
    # Confirm against the latest report; the server never accepts a client-supplied price.
    fresh=quote(report,q['symbol'],q['side'],q['quantity'],q['revision'])
    if any(q[k]!=fresh[k] for k in ('price','session','report')):raise ValidationError('Saved prices changed. Preview this trade again.')
    path=Path(folder)/'manual_demo.sqlite3'
    if not path.is_file():validate(state(folder),q)
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        version=db.execute('PRAGMA user_version').fetchone()[0]
        tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not tables and version==0:
            db.execute('CREATE TABLE account(id INTEGER PRIMARY KEY,cash INTEGER,realized INTEGER,revision INTEGER)')
            db.execute('CREATE TABLE positions(symbol TEXT PRIMARY KEY,quantity INTEGER,basis INTEGER)')
            db.execute('CREATE TABLE trades(id TEXT UNIQUE,recorded_at TEXT,side TEXT,symbol TEXT,quantity INTEGER,price INTEGER,session TEXT,report TEXT,realized INTEGER)')
            db.execute('INSERT INTO account VALUES(1,?,0,0)',(INITIAL,));db.execute('PRAGMA user_version=83')
        elif version!=83:raise ValidationError('Unrecognized demo account database')
        if db.execute('SELECT 1 FROM trades WHERE id=?',(q['id'],)).fetchone():return False
        account=_state(db);validate(account,q)
        old=account['positions'].get(q['symbol'],{'quantity':0,'basis':0});qty=q['quantity'];total=qty*q['price'];gain=0
        if q['side']=='buy':
            cash=account['cash']-total;newqty=old['quantity']+qty;basis=old['basis']+total
        else:
            removed=old['basis'] if qty==old['quantity'] else old['basis']*qty//old['quantity']
            cash=account['cash']+total;newqty=old['quantity']-qty;basis=old['basis']-removed;gain=total-removed
        db.execute('INSERT OR REPLACE INTO positions VALUES(?,?,?)',(q['symbol'],newqty,basis))
        db.execute('UPDATE account SET cash=?,realized=?,revision=revision+1 WHERE id=1',(cash,account['realized']+gain))
        db.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?)',(q['id'],datetime.now(timezone.utc).isoformat(),q['side'],q['symbol'],qty,q['price'],q['session'],q['report'],gain))
        return True
