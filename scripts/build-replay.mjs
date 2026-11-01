import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {forecast} from '../lib/forecast.ts';
const source=JSON.parse(readFileSync(new URL('../data/history.json',import.meta.url),'utf8'));
const metadata=JSON.parse(readFileSync(new URL('../data/provenance.json',import.meta.url),'utf8'));
const keys=['date','open','high','low','close','volume','benchmark'];
const dates=source[0].bars.map(r=>r[0]).filter(d=>d>='2021-01-04');
const stocks=[];let missing=0;
for(const s of source){
 const bars=s.bars.map(row=>Object.fromEntries(keys.map((k,i)=>[k,row[i]])));
 const predictions=dates.map(date=>{const i=bars.findIndex(b=>b.date===date);try{return forecast(bars.slice(0,i+1));}catch{missing++;return null;}});
 stocks.push({symbol:s.symbol,name:s.name,sector:s.sector,bars:bars.filter(b=>b.date>='2020-09-01'),predictions});
}
mkdirSync(new URL('../lib/server-data/',import.meta.url),{recursive:true});
writeFileSync(new URL('../lib/server-data/replay.json',import.meta.url),JSON.stringify({id:metadata.id,dates,stocks}));
const example=source.find(s=>s.symbol==='RELIANCE');
writeFileSync(new URL('../public/example-reliance-history.csv',import.meta.url),keys.join(',')+'\n'+example.bars.map(row=>row.join(',')).join('\n')+'\n');
console.log(`${stocks.length} stocks × ${dates.length} replay dates; ${missing} unavailable forecasts honestly omitted.`);
