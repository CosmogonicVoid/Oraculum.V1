import raw from './server-data/replay.json';
import {outcome, type Bar, type Forecast} from './forecast';
export const INITIAL_CASH=10_000_000; // Integer paise, never floating-point cash.
type Stock={symbol:string;name:string;sector:string;bars:Bar[];predictions:(Forecast|null)[]};
const archive=raw as unknown as {id:string;dates:string[];stocks:Stock[]};
export type ReplayOrder={id:string;symbol:string;side:'buy'|'sell';quantity:number;note:string;submitted:string;status:'queued'|'filled'|'rejected'|'cancelled';fillDate?:string;price?:number;fee?:number;total?:number;message?:string};
export type ReplayState={dataset:string;started:boolean;cursor:number;cash:number;positions:Record<string,{quantity:number;cost:number}>;orders:ReplayOrder[];watchlist:string[];forecastSessions:number[];equity:{date:string;value:number;benchmark:number}[];requests:string[]};
export type MarketRow={symbol:string;name:string;sector:string;close:number;change:number;volume:number;spark:number[];forecast:Forecast|null};
export type PredictionRecord={symbol:string;asOf:string;horizon:number;forecast:Forecast;status:'pending'|'resolved'|'outside archive';result:ReturnType<typeof outcome>|null};
export type ReplaySnapshot={revision:number;state:ReplayState;date:string;endDate:string;totalSessions:number;market:MarketRow[];chart:{symbol:string;bars:Bar[]};holdings:{symbol:string;quantity:number;cost:number;value:number;gain:number}[];equity:number;records:PredictionRecord[];metrics:{resolved:number;mae:number|null;brier:number|null;coverage:number|null;beatRate:number|null;baselineMAE:number|null};};
export function freshReplay():ReplayState{return {dataset:archive.id,started:false,cursor:0,cash:INITIAL_CASH,positions:{},orders:[],watchlist:[],forecastSessions:[],equity:[],requests:[]};}
const findStock=(s:string)=>archive.stocks.find(x=>x.symbol===s);
function bar(stock:Stock,cursor:number){const b=stock.bars.find(x=>x.date===archive.dates[cursor]);if(!b)throw Error('A required historical observation is missing.');return b;}
function equity(s:ReplayState){return s.cash+Object.entries(s.positions).reduce((sum,[symbol,p])=>sum+Math.round(bar(findStock(symbol)!,s.cursor).close*100)*p.quantity,0);}
function checkpoint(s:ReplayState){const date=archive.dates[s.cursor];if(!s.forecastSessions.includes(s.cursor))s.forecastSessions.push(s.cursor);if(!s.equity.some(x=>x.date===date))s.equity.push({date,value:equity(s),benchmark:Math.round(INITIAL_CASH*bar(archive.stocks[0],s.cursor).benchmark/bar(archive.stocks[0],0).benchmark)});}
export function applyReplay(current:ReplayState,input:Record<string,unknown>):ReplayState{
 const s=structuredClone(current);if(s.dataset!==archive.id)throw Error('This account uses a different archive. Export it before migrating.');
 if(input.action==='start'){if(!s.started){s.started=true;checkpoint(s);}return s;}
 if(!s.started)throw Error('Start your forecast challenge first.');
 if(input.action==='watch'){
  if(typeof input.symbol!=='string'||!findStock(input.symbol)||typeof input.saved!=='boolean')throw Error('Choose a valid stock.');
  s.watchlist=s.watchlist.filter(x=>x!==input.symbol);if(input.saved)s.watchlist.push(input.symbol);return s;
 }
 if(input.action==='cancel'){
  const order=s.orders.find(o=>o.id===input.orderId&&o.status==='queued');if(!order)throw Error('That order is no longer queued.');order.status='cancelled';return s;
 }
 if(input.action==='order'){
  if(s.cursor>=archive.dates.length-1)throw Error('The archive has ended; there is no next opening price.');
  const stock=typeof input.symbol==='string'?findStock(input.symbol):null;
  if(!stock||!['buy','sell'].includes(String(input.side))||typeof input.quantity!=='number'||!Number.isSafeInteger(input.quantity)||input.quantity<1||input.quantity>100000)throw Error('Choose a valid stock, side and whole-share quantity.');
  if(typeof input.note!=='string'||input.note.length>400)throw Error('Keep your thesis under 400 characters.');
  if(s.orders.length>=250)throw Error('This challenge has reached its 250-order limit.');
  const queued=s.orders.filter(o=>o.status==='queued');if(queued.length>=10)throw Error('At most 10 orders can be queued at once.');
  if(input.side==='sell'){
   const reserved=queued.filter(o=>o.side==='sell'&&o.symbol===stock.symbol).reduce((n,o)=>n+o.quantity,0);
   if(input.quantity>(s.positions[stock.symbol]?.quantity||0)-reserved)throw Error('You do not have that many unreserved shares.');
  }else{
   const reserved=queued.filter(o=>o.side==='buy').reduce((n,o)=>n+Math.ceil(bar(findStock(o.symbol)!,s.cursor).close*100*1.002001)*o.quantity,0);
   if(Math.ceil(bar(stock,s.cursor).close*100*1.002001)*input.quantity>s.cash-reserved)throw Error('Not enough unreserved virtual cash at the latest close.');
  }
  s.orders.push({id:String(input.requestId),symbol:stock.symbol,side:input.side as 'buy'|'sell',quantity:input.quantity,note:input.note.trim(),submitted:archive.dates[s.cursor],status:'queued'});return s;
 }
 if(input.action==='advance'){
  if(![1,5,20].includes(Number(input.steps)))throw Error('Advance 1, 5 or 20 sessions.');
  if(s.cursor>=archive.dates.length-1)throw Error('You have reached the end of this archive.');
  const target=Math.min(archive.dates.length-1,s.cursor+Number(input.steps));
  while(s.cursor<target){
   s.cursor++;
   for(const o of s.orders.filter(x=>x.status==='queued')){
    const next=bar(findStock(o.symbol)!,s.cursor),buy=o.side==='buy';
    const price=Math.round(next.open*100*(buy?1.001:.999)),gross=price*o.quantity,fee=Math.round(gross*.001),total=buy?gross+fee:gross-fee;
    const p=s.positions[o.symbol]||{quantity:0,cost:0};
    if((buy&&total>s.cash)||(!buy&&p.quantity<o.quantity)){o.status='rejected';o.fillDate=next.date;o.message='Opening-price gap or reserved holdings prevented this fill.';continue;}
    if(buy){s.cash-=total;p.quantity+=o.quantity;p.cost+=total;s.positions[o.symbol]=p;}
    else{const allocated=o.quantity===p.quantity?p.cost:Math.round(p.cost*o.quantity/p.quantity);s.cash+=total;p.quantity-=o.quantity;p.cost-=allocated;if(!p.quantity)delete s.positions[o.symbol];}
    Object.assign(o,{status:'filled',fillDate:next.date,price,fee,total});
   }
   // Equity is recorded daily even when the player skips ahead.
   s.equity.push({date:archive.dates[s.cursor],value:equity(s),benchmark:Math.round(INITIAL_CASH*bar(archive.stocks[0],s.cursor).benchmark/bar(archive.stocks[0],0).benchmark)});
  }
  checkpoint(s);return s;
 }
 throw Error('Unknown challenge action.');
}
export function snapshot(state:ReplayState,revision=0,selected?:string):ReplaySnapshot{
 const date=archive.dates[state.cursor];
 const market:MarketRow[]=archive.stocks.map(s=>{const b=bar(s,state.cursor),past=s.bars.filter(b=>b.date<=date);return {symbol:s.symbol,name:s.name,sector:s.sector,close:b.close,change:b.close/past[past.length-2].close-1,volume:b.volume,spark:past.slice(-20).map(x=>x.close),forecast:s.predictions[state.cursor]};}).sort((a,b)=>(b.forecast?.score??-Infinity)-(a.forecast?.score??-Infinity));
 const selectedStock=findStock(selected||'')||findStock(market[0].symbol)!;
 const records:PredictionRecord[]=state.forecastSessions.flatMap(cursor=>archive.stocks.filter(s=>s.predictions[cursor]).sort((a,b)=>b.predictions[cursor]!.score-a.predictions[cursor]!.score).slice(0,5).map(s=>{
  const f=s.predictions[cursor]!,target=cursor+20;
  return {symbol:s.symbol,asOf:f.asOf,horizon:20,forecast:f,status:target>=archive.dates.length?'outside archive':target<=state.cursor?'resolved':'pending',result:target<archive.dates.length&&target<=state.cursor?outcome(f,bar(s,cursor),bar(s,target)):null} as PredictionRecord;
 }));
 const resolved=records.filter(r=>r.result),n=resolved.length,avg=(fn:(r:PredictionRecord)=>number)=>n?resolved.reduce((sum,r)=>sum+fn(r),0)/n:null;
 return {revision,state,date,endDate:archive.dates.at(-1)!,totalSessions:archive.dates.length,market,chart:{symbol:selectedStock.symbol,bars:selectedStock.bars.filter(b=>b.date<=date).slice(-90)},holdings:Object.entries(state.positions).map(([symbol,p])=>{const value=Math.round(bar(findStock(symbol)!,state.cursor).close*100)*p.quantity;return {symbol,...p,value,gain:value-p.cost};}),equity:equity(state),records,metrics:{resolved:n,mae:avg(r=>r.result!.error),brier:avg(r=>r.result!.brier),coverage:avg(r=>Number(r.result!.inRange)),beatRate:avg(r=>Number(r.result!.excess>0)),baselineMAE:avg(r=>Math.abs(r.result!.actual))}};
}
