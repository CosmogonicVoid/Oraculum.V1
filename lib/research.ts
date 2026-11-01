import {forecast,outcome,validateBars,type Forecast,type Bar} from './forecast';
export type ResearchRun={id:string;symbol:string;source:string;benchmarkName:string;createdAt:string;kind:'recent-data forecast'|'retrospective forecast';start:string;count:number;digest:string;forecast:Forecast;result:ReturnType<typeof outcome>|null;status:'awaiting data'|'resolved'|'history changed';};
export type ResearchState={runs:ResearchRun[]};
export async function digestBars(bars:Bar[]){const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(bars)));return Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');}
export async function importResearch(state:ResearchState,input:Record<string,unknown>,now=new Date()):Promise<ResearchState>{
 const label=(v:unknown,max:number)=>typeof v==='string'&&v.trim().length>0&&v.trim().length<=max?v.trim():null;
 const symbol=label(input.symbol,20)?.toUpperCase(),source=label(input.source,160),benchmarkName=label(input.benchmarkName,60);
 if(!symbol||!/^[-A-Z0-9&.]+$/.test(symbol)||!source||!benchmarkName)throw Error('Provide a symbol, data source and benchmark name.');
 const bars=validateBars(input.bars),digest=await digestBars(bars),next=structuredClone(state);
 if(next.runs.some(r=>r.symbol===symbol&&r.digest===digest&&r.benchmarkName===benchmarkName))return next;
 for(const r of next.runs.filter(r=>r.symbol===symbol&&r.source===source&&r.benchmarkName===benchmarkName&&!r.result)){
  const i=bars.findIndex(b=>b.date===r.forecast.asOf);
  if(i<0||bars[0].date!==r.start||i+1!==r.count||await digestBars(bars.slice(0,i+1))!==r.digest){r.status='history changed';continue;}
  r.status='awaiting data';
  if(bars[i+20]){r.result=outcome(r.forecast,bars[i],bars[i+20]);r.status='resolved';}
 }
 if(next.runs.length>=40)return next; // Existing predictions can still settle at the storage cap.
 const f=forecast(bars),age=(now.getTime()-Date.parse(f.asOf))/86400000;
 next.runs.unshift({id:crypto.randomUUID(),symbol,source,benchmarkName,createdAt:now.toISOString(),kind:age<=7?'recent-data forecast':'retrospective forecast',start:bars[0].date,count:bars.length,digest,forecast:f,result:null,status:'awaiting data'});
 return next;
}
