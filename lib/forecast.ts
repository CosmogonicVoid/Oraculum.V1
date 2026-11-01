/** Deterministic, past-only research model. No LLM or paid API required. */
export const MODEL = 'oraculum-ridge-1';
export const HORIZON = 20;
export type Bar = {date:string;open:number;high:number;low:number;close:number;volume:number;benchmark:number};
export type Forecast = {
 model:string; asOf:string; horizon:number; close:number; expectedReturn:number; excessReturn:number;
 low:number; high:number; probability:number; score:number; trainingSamples:number; calibrationSamples:number;
 validationMAE:number; baselineMAE:number; features:number[]; reasons:string[]; risks:string[];
};
const mean=(a:number[])=>a.reduce((s,x)=>s+x,0)/a.length;
const clamp=(x:number,a:number,b:number)=>Math.min(b,Math.max(a,x));
const quantile=(a:number[],q:number)=>{const b=[...a].sort((x,y)=>x-y),p=(b.length-1)*q,i=Math.floor(p);return b[i]+(b[Math.min(i+1,b.length-1)]-b[i])*(p-i);};
const pct=(x:number)=>`${x>=0?'+':''}${(100*x).toFixed(1)}%`;
export function validateBars(value:unknown):Bar[]{
 if(!Array.isArray(value)||value.length<420||value.length>2500)throw Error('Supply 420–2,500 daily observations, with a benchmark close on every date.');
 let prev='';
 const today=new Date().toISOString().slice(0,10);
 return value.map((v)=>{
  if(!v||typeof v!=='object')throw Error('Each row must be a daily price observation.');
  const b=v as Bar;
  if(typeof b.date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(b.date)||!Number.isFinite(Date.parse(b.date))||new Date(b.date).toISOString().slice(0,10)!==b.date||b.date<=prev||b.date>today)throw Error('Dates must be valid, unique, ascending ISO dates, without future rows.');
  prev=b.date;
  for(const k of ['open','high','low','close','volume','benchmark'] as const)if(typeof b[k]!=='number'||!Number.isFinite(b[k])||b[k]>(k==='volume'?1e13:1e8)||b[k]<(k==='volume'?0:0.000001))throw Error(`Invalid ${k} on ${b.date}.`);
  if(b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close,b.high))throw Error(`OHLC values are inconsistent on ${b.date}.`);
  return {date:b.date,open:b.open,high:b.high,low:b.low,close:b.close,volume:b.volume,benchmark:b.benchmark};
 });
}
export function parseCSV(text:string):Bar[]{
 const lines=text.replace(/^\uFEFF/,'').trim().split(/\r?\n/);
 const names=lines.shift()?.trim().toLowerCase().split(',').map(x=>x.trim());
 const keys=['date','open','high','low','close','volume','benchmark'];
 if(!names||keys.some(k=>!names.includes(k))||new Set(names).size!==names.length)throw Error('CSV headers must include date,open,high,low,close,volume,benchmark. Use unformatted numbers.');
 return validateBars(lines.filter(l=>l.trim()).map(l=>{const values=l.split(',').map(x=>x.trim());if(values.length!==names.length)throw Error('Each CSV row must have the same number of fields.');return Object.fromEntries(keys.map(k=>[k,k==='date'?values[names.indexOf(k)]:Number(values[names.indexOf(k)]||NaN)]));}));
}
function features(b:Bar[],i:number){
 const c=b[i].close,r=(n:number)=>c/b[i-n].close-1,window=b.slice(i-19,i+1);
 const daily=window.map((v,j)=>v.close/b[i-20+j].close-1),m=mean(daily);
 const vol=Math.sqrt(mean(daily.map(x=>(x-m)**2)));
 const benchmark=b[i].benchmark/b[i-20].benchmark-1;
 return [r(5),r(20),r(60),c/mean(b.slice(i-49,i+1).map(x=>x.close))-1,Math.log((b[i].volume+1)/(mean(window.map(x=>x.volume))+1)),vol,benchmark,r(20)-benchmark];
}
function discontinuity(b:Bar[],from:number,to:number){for(let i=Math.max(1,from);i<=to;i++)if(Math.abs(b[i].close/b[i-1].close-1)>.25)return true;return false;}
type Row={x:number[];y:number[]};
function fit(rows:Row[]){
 const d=8,m=Array.from({length:d},(_,j)=>mean(rows.map(r=>r.x[j]))),s=m.map((v,j)=>Math.sqrt(mean(rows.map(r=>(r.x[j]-v)**2)))||1);
 const a=Array.from({length:d+1},()=>Array(d+3).fill(0) as number[]);
 for(const row of rows){const x=[1,...row.x.map((v,j)=>clamp((v-m[j])/s[j],-6,6))];for(let i=0;i<=d;i++){for(let j=0;j<=d;j++)a[i][j]+=x[i]*x[j];for(let k=0;k<2;k++)a[i][d+1+k]+=x[i]*row.y[k];}}
 for(let i=1;i<=d;i++)a[i][i]+=10; // Fixed ridge penalty; no hindsight tuning.
 for(let i=0;i<=d;i++){
  let pivot=i;for(let j=i+1;j<=d;j++)if(Math.abs(a[j][i])>Math.abs(a[pivot][i]))pivot=j;
  [a[pivot],a[i]]=[a[i],a[pivot]];
  if(Math.abs(a[i][i])<1e-10)throw Error('Insufficient variation to fit this history.');
  const div=a[i][i];for(let k=i;k<d+3;k++)a[i][k]/=div;
  for(let j=0;j<=d;j++)if(j!==i){const z=a[j][i];for(let k=i;k<d+3;k++)a[j][k]-=z*a[i][k];}
 }
 return (v:number[])=>{const x=[1,...v.map((n,j)=>clamp((n-m[j])/s[j],-6,6))];return [0,1].map(k=>x.reduce((sum,n,j)=>sum+n*a[j][d+1+k],0));};
}
/** Caller supplies only the history available at its cutoff. */
export function forecast(b:Bar[]):Forecast{
 if(b.length<420)throw Error('At least 420 sessions are required.');
 const end=b.length-1,calStart=end-120;
 if(discontinuity(b,end-59,end))throw Error('A move above 25% appears in the recent history. Verify corporate-action adjustments before forecasting.');
 const row=(i:number):Row=>{const stock=b[i+20].close/b[i].close-1,bench=b[i+20].benchmark/b[i].benchmark-1;return {x:features(b,i),y:[stock,stock-bench]};};
 const train:Row[]=[];
 for(let i=60;i<=calStart-21;i++)if(!discontinuity(b,i-59,i+20))train.push(row(i));
 if(train.length<120)throw Error('Too few clean training observations after excluding large price discontinuities.');
 const model=fit(train),residuals:number[]=[],alphaResiduals:number[]=[],errors:number[]=[],baseline:number[]=[];
 // Six non-overlapping 20-session validation targets; small sample is made explicit.
 for(let i=calStart;i<=end-20;i+=20)if(!discontinuity(b,i-59,i+20)){
  const r=row(i),p=model(r.x);residuals.push(r.y[0]-p[0]);alphaResiduals.push(r.y[1]-p[1]);errors.push(Math.abs(r.y[1]-p[1]));baseline.push(Math.abs(r.y[1]));
 }
 if(residuals.length<4)throw Error('Not enough clean validation periods. Supply more carefully adjusted history.');
 const f=features(b,end),p=model(f),low=Math.max(-.99,p[0]+quantile(residuals,.1)),high=Math.max(low,p[0]+quantile(residuals,.9));
 const alphaLow=p[1]+quantile(alphaResiduals,.1),alphaHigh=p[1]+quantile(alphaResiduals,.9);
 const probability=(1+alphaResiduals.filter(r=>p[1]+r>0).length)/(alphaResiduals.length+2);
 const score=p[1]-.004-.5*Math.max(0,-alphaLow)-.1*(alphaHigh-alphaLow);
 return {model:MODEL,asOf:b[end].date,horizon:20,close:b[end].close,expectedReturn:Math.max(-.99,p[0]),excessReturn:p[1],low,high,probability,score,trainingSamples:train.length,calibrationSamples:residuals.length,validationMAE:mean(errors),baselineMAE:mean(baseline),features:f,
  reasons:[`20-session momentum is ${pct(f[1])}; relative momentum against the benchmark is ${pct(f[7])}.`,`Price is ${pct(f[3])} from its 50-session average.`,`Latest volume is ${Math.exp(f[4]).toFixed(2)}× its 20-session average.`],
  risks:[`The probability and range use only ${residuals.length} held-out periods; they are rough estimates, not validated confidence.`,mean(errors)>mean(baseline)?'The model missed by more than the zero-excess-return baseline in its small validation set.':'A small validation advantage is not evidence of a reliable investing edge.','Price and volume only. Earnings, news, valuation and corporate-action verification are not included.']};
}
export function outcome(f:Forecast,origin:Bar,target:Bar){const actual=target.close/origin.close-1,benchmark=target.benchmark/origin.benchmark-1;return {date:target.date,actual,benchmark,excess:actual-benchmark,error:Math.abs(actual-f.expectedReturn),inRange:actual>=f.low&&actual<=f.high,brier:(f.probability-(actual>benchmark?1:0))**2};}
