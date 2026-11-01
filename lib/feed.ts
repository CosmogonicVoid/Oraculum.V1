/** Provider-neutral quote boundary. An adapter must supply verified exchange timestamps.
 * No provider, token, polling job or public redistribution permission is implied.
 */
export type ExchangeQuote={symbol:string;last:number;bid:number|null;ask:number|null;exchangeTime:string;receivedTime:string;session:string;marketState:'open'|'closed';officialOpen:number|null;officialClose:number|null;source:string};
export function validateExchangeQuote(q:ExchangeQuote,now=Date.now()){
 if(!q||typeof q.symbol!=='string'||!/^[-A-Z0-9.&]{1,40}$/.test(q.symbol))throw Error('Invalid exchange symbol');
 for(const k of ['last','bid','ask','officialOpen','officialClose'] as const){const v=q[k];if(v===null&&k!=='last')continue;if(!Number.isSafeInteger(v)||Number(v)<=0)throw Error('Prices must be positive integer paise');}
 if(q.bid!==null&&q.ask!==null&&q.bid>q.ask)throw Error('Crossed quote');
 if(!q.source||!/^\d{4}-\d{2}-\d{2}$/.test(q.session))throw Error('Missing provenance');
 const exchange=Date.parse(q.exchangeTime),received=Date.parse(q.receivedTime);
 if(!Number.isFinite(exchange)||!Number.isFinite(received)||exchange>now+5000||received>now+5000||exchange>received+5000)throw Error('Invalid quote timestamps');
 if(q.marketState!=='open'&&q.marketState!=='closed')throw Error('Unknown session state');
 return{...q,status:q.marketState==='closed'?'closed':now-exchange>60000||now-received>60000?'stale':'fresh'};
}
export function requireExecutableQuote(q:ExchangeQuote,side:'buy'|'sell',now=Date.now()){
 const validated=validateExchangeQuote(q,now);if(validated.status!=='fresh')throw Error('Market closed or quote stale; execution paused');
 const price=side==='buy'?q.ask:q.bid;if(price===null)throw Error('Executable side of quote is missing');return price;
}
