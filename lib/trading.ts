export const INITIAL_CASH=10_000_000;
export type Position={quantity:number;basis:number};
export type Trade={id:string;symbol:string;side:'buy'|'sell';quantity:number;price:number;fee:number;total:number;realized:number;at:string;note:string};
export type Account={cash:number;realized:number;positions:Record<string,Position>;watchlist:string[];trades:Trade[]};
export type Quote={id:string;symbol:string;side:'buy'|'sell';quantity:number;price:number;fee:number;total:number;revision:number;expires:number;note:string;mode:'training'};
export const freshAccount=():Account=>({cash:INITIAL_CASH,realized:0,positions:{},watchlist:[],trades:[]});
export function makeQuote(symbol:string,side:unknown,quantity:unknown,price:number,revision:number,note:unknown,now=Date.now()):Quote{
 if(side!=='buy'&&side!=='sell')throw Error('Choose buy or sell.');
 if(!Number.isSafeInteger(quantity)||Number(quantity)<1||Number(quantity)>100000)throw Error('Enter 1–100,000 whole shares.');
 if(!Number.isSafeInteger(price)||price<=0)throw Error('A valid price is unavailable.');
 if(note!==undefined&&(typeof note!=='string'||note.length>300))throw Error('Keep your trade note under 300 characters.');
 const fill=side==='buy'?Math.ceil(price*10010/10000):Math.floor(price*9990/10000);const gross=fill*Number(quantity);const fee=Math.ceil(gross/1000);const total=side==='buy'?gross+fee:gross-fee;
 if(!Number.isSafeInteger(total))throw Error('Order exceeds the supported amount.');
 return{id:crypto.randomUUID(),symbol,side,quantity:Number(quantity),price:fill,fee,total,revision,expires:now+120000,note:(note as string)||'',mode:'training'};
}
export function applyTrade(account:Account,q:Quote,now=Date.now()):Account{
 if(account.trades.some(t=>t.id===q.id))return account;
 if(now>=q.expires)throw Error('Quote expired. Preview again.');
 if(account.trades.length>=2000)throw Error('This training account has reached its 2,000-trade limit.');
 const a=structuredClone(account);const old=a.positions[q.symbol]||{quantity:0,basis:0};let realized=0;
 if(q.side==='buy'){
 if(q.total>a.cash)throw Error('Not enough virtual cash.');
 a.cash-=q.total;a.positions[q.symbol]={quantity:old.quantity+q.quantity,basis:old.basis+q.total};
 }else{
 if(q.quantity>old.quantity)throw Error('Not enough shares. Short selling is disabled.');
 const removed=q.quantity===old.quantity?old.basis:Math.floor(old.basis*q.quantity/old.quantity);
 realized=q.total-removed;a.cash+=q.total;a.realized+=realized;
 a.positions[q.symbol]={quantity:old.quantity-q.quantity,basis:old.basis-removed};
 if(!a.positions[q.symbol].quantity)delete a.positions[q.symbol];
 }
 a.trades.push({id:q.id,symbol:q.symbol,side:q.side,quantity:q.quantity,price:q.price,fee:q.fee,total:q.total,realized,at:new Date(now).toISOString(),note:q.note});return a;
}
