// Deliberately fictional training assets. Never presented as NSE quotes.
export type Candle = {session:number;open:number;high:number;low:number;close:number;volume:number};
export type Stock = {symbol:string;name:string;sector:string;history:Candle[];price:number;change:number;score:number;momentum:number;volumeRatio:number;volatility:number;reasons:string[]};
const definitions:[string,string,string,number,number][]=[['ORBIT','Orbit Technologies','Technology',124000,.0028],['AURORA','Aurora Bank','Financials',84500,.0017],['VERDANT','Verdant Energy','Energy',32600,.0031],['NORTH','Northstar Industries','Industrials',218000,-.0004],['KINETIC','Kinetic Motors','Automotive',68200,.001],['HELIX','Helix Healthcare','Healthcare',154600,.0019],['HARVEST','Harvest Consumer','Consumer',43200,-.0011],['ATLAS','Atlas Infrastructure','Infrastructure',96500,.0014]];
export const stocks:Stock[]=definitions.map(([symbol,name,sector,base,drift],k)=>{
 let seed=1234+k*991;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};let p=base;
 const history=Array.from({length:120},(_,i)=>{const open=p;const close=Math.max(100,Math.round(open*(1+drift+(random()-.5)*.032)));const high=Math.round(Math.max(open,close)*(1+random()*.012));const low=Math.round(Math.min(open,close)*(1-random()*.012));p=close;return{session:i+1,open,high,low,close,volume:Math.round(150000+random()*1000000)};});
 const last=history.at(-1)!;const previous=history.at(-2)!;const momentum=(last.close/history.at(-21)!.close-1)*100;
 const meanVolume=history.slice(-21,-1).reduce((s,c)=>s+c.volume,0)/20;const volumeRatio=last.volume/meanVolume;
 const returns=history.slice(-20).map((c,i)=>(c.close/history[99+i].close-1)*100);const mean=returns.reduce((a,b)=>a+b,0)/20;const volatility=Math.sqrt(returns.reduce((a,b)=>a+(b-mean)**2,0)/20);
 const score=Math.round(Math.max(0,Math.min(100,50+momentum*2+Math.min(2,volumeRatio)*10-volatility*5)));
 return{symbol,name,sector,history,price:last.close,change:(last.close/previous.close-1)*100,score,momentum,volumeRatio,volatility,reasons:[`20-session momentum is ${momentum.toFixed(2)}%.`,`Volume is ${volumeRatio.toFixed(2)}× the prior 20-session average.`,`Daily return volatility is ${volatility.toFixed(2)}% over 20 sessions.`]};
});
export const market={mode:'training',source:'Oraculum deterministic training dataset v1',live:false,asOf:null,session:120};
export function findStock(symbol:string){return stocks.find(s=>s.symbol===symbol);}
