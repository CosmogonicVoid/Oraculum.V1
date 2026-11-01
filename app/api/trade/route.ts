import {identity,ensureAccount,saveAccount,database,body,json,failure,HttpError} from '../../../lib/server';
import {findStock} from '../../../lib/market';
import {makeQuote,applyTrade,type Quote} from '../../../lib/trading';
export async function POST(req:Request){try{
 const u=await identity();const b=await body(req);const {account,revision}=await ensureAccount(u.userId);const db=database();
 if(b.action==='preview'){
 const stock=typeof b.symbol==='string'?findStock(b.symbol):null;if(!stock)throw new HttpError(400,'Choose a training stock. Live NSE trading is not connected.');
 let quote:Quote;try{quote=makeQuote(stock.symbol,b.side,b.quantity,stock.price,revision,b.note);applyTrade(account,quote);}catch(e){throw new HttpError(400,(e as Error).message);}
 await db.prepare('DELETE FROM quotes WHERE user_id=? AND expires<?').bind(u.userId,Date.now()).run();
 const count=await db.prepare('SELECT COUNT(*) AS n FROM quotes WHERE user_id=?').bind(u.userId).first<{n:number}>();if((count?.n||0)>=20)throw new HttpError(429,'Too many previews. Wait two minutes and try again.');
 await db.prepare('INSERT INTO quotes(id,user_id,payload,expires) VALUES(?,?,?,?)').bind(quote.id,u.userId,JSON.stringify(quote),quote.expires).run();return json({quote});
 }
 if(b.action!=='confirm'||typeof b.quoteId!=='string'||b.quoteId.length>50)throw new HttpError(400,'Invalid order.');
 if(account.trades.some(t=>t.id===b.quoteId))return json({account,revision,duplicate:true});
 const row=await db.prepare('SELECT payload FROM quotes WHERE id=? AND user_id=?').bind(b.quoteId,u.userId).first<{payload:string}>();if(!row)throw new HttpError(404,'Quote unavailable. Preview again.');
 const q=JSON.parse(row.payload) as Quote;if(q.revision!==revision)throw new HttpError(409,'Portfolio changed. Preview again.');
 let next;try{next=applyTrade(account,q);}catch(e){throw new HttpError(400,(e as Error).message);}
 await saveAccount(u.userId,next,revision);return json({account:next,revision:revision+1});
 }catch(e){return failure(e);}}
