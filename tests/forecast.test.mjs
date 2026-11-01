import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,writeFileSync,mkdirSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';
const out=mkdtempSync(path.join(tmpdir(),'oraculum-forecast-'));
const files=['lib/forecast.ts','lib/replay.ts','lib/research.ts','lib/server.ts','lib/trading.ts','lib/market.ts','app/api/lab/route.ts','app/api/research/route.ts'];
for(const file of files){
 let source=readFileSync(file,'utf8').replace("import { env } from 'cloudflare:workers';","const env=globalThis.__forecastEnv;").replace(/import \{\s*getChatGPTUser\s*\} from ['"][^'"]*chatgpt-auth['"];?/g,'async function getChatGPTUser(){return globalThis.__forecastUser;}');
 source=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText.replace(/from ['"]([.][^'"]+)['"]/g,(_,p)=>`from '${p.endsWith('.json')?p+'.mjs':p+'.mjs'}'`);
 const dest=path.join(out,file.replace('.ts','.mjs'));mkdirSync(path.dirname(dest),{recursive:true});writeFileSync(dest,source);
}
mkdirSync(path.join(out,'lib/server-data'),{recursive:true});writeFileSync(path.join(out,'lib/server-data/replay.json.mjs'),'export default '+readFileSync('lib/server-data/replay.json','utf8'));
const sqlite=new DatabaseSync(':memory:');for(const file of ['drizzle/0000_warm_wither.sql','drizzle/0001_gorgeous_the_captain.sql'])sqlite.exec(readFileSync(file,'utf8'));
const DB={prepare(sql){let params=[];return{bind(...p){params=p;return this;},async first(){return sqlite.prepare(sql).get(...params)||null;},async run(){const r=sqlite.prepare(sql).run(...params);return{meta:{changes:Number(r.changes)}};}}}};
globalThis.__forecastEnv={DB};globalThis.__forecastUser={userId:'alice'};
const module=async p=>import(pathToFileURL(path.join(out,p+'.mjs')));
const {forecast,validateBars,parseCSV}=await module('lib/forecast');
const {freshReplay,applyReplay,snapshot}=await module('lib/replay');
const {importResearch}=await module('lib/research');
const lab=await module('app/api/lab/route'),research=await module('app/api/research/route');
const raw=JSON.parse(readFileSync('data/history.json','utf8')),archive=JSON.parse(readFileSync('lib/server-data/replay.json','utf8'));
const keys=['date','open','high','low','close','volume','benchmark'];
const history=raw.find(s=>s.symbol==='RELIANCE').bars.map(r=>Object.fromEntries(keys.map((k,i)=>[k,r[i]])));
const request=(data,origin='https://test.local')=>new Request('https://test.local/api/lab',{method:'POST',headers:{'Content-Type':'application/json',Origin:origin},body:JSON.stringify(data)});
const get=()=>new Request('https://test.local/api/lab');
let sequence=0;
const call=async(data)=>{const r=await lab.POST(request({requestId:`test-request-${++sequence}`,selected:'RELIANCE',...data}));return {status:r.status,body:await r.json()};};
test('archived forecasts reproduce from only the cutoff history; clean temporal gap and probability bounds',()=>{
 for(const cursor of [0,20,60]){
  const until=history.filter(b=>b.date<=archive.dates[cursor]);const f=forecast(validateBars(until));
  assert.deepEqual(f,archive.stocks.find(s=>s.symbol==='RELIANCE').predictions[cursor]);
  assert.ok(f.probability>0&&f.probability<1);assert.ok(f.low<=f.high);assert.equal(f.asOf,archive.dates[cursor]);
  assert.equal(f.calibrationSamples,6);assert.ok(f.trainingSamples>=120);
 }
});
test('CSV validation refuses future, duplicate, non-finite and inconsistent OHLC inputs',()=>{
 assert.equal(parseCSV(readFileSync('public/example-reliance-history.csv','utf8')).length,history.length);
 for(const mutate of [b=>b[3].date=b[2].date,b=>b[20].high=1,b=>b[10].benchmark=0,b=>b[10].volume=NaN,b=>b.at(-1).date='2099-12-01']){const b=structuredClone(history);mutate(b);assert.throws(()=>validateBars(b));}
 assert.throws(()=>validateBars(history.slice(0,419)));
 const broken=structuredClone(history);for(const b of broken.slice(-10)){b.close*=.5;b.open*=.5;b.high*=.5;b.low*=.5;}assert.throws(()=>forecast(broken),/25%/);
});
test('replay hides future observations and settles forecasts at exactly 20 revealed sessions',()=>{
 let s=applyReplay(freshReplay(),{action:'start'}),v=snapshot(s);assert.equal(v.records.length,5);assert.equal(v.metrics.resolved,0);
 assert.ok(v.chart.bars.every(b=>b.date<=v.date));assert.ok(v.market.every(m=>!m.forecast||m.forecast.asOf===v.date));assert.ok(v.records.every(r=>!r.result));
 for(let i=0;i<19;i++)s=applyReplay(s,{action:'advance',steps:1});assert.equal(snapshot(s).metrics.resolved,0);
 s=applyReplay(s,{action:'advance',steps:1});v=snapshot(s);assert.equal(v.metrics.resolved,5);assert.ok(v.records.filter(r=>r.result).every(r=>r.result.date===v.date));
 const record=v.records.find(r=>r.result),series=archive.stocks.find(s=>s.symbol===record.symbol).bars;
 assert.equal(record.result.actual,series.find(b=>b.date===v.date).close/series.find(b=>b.date===record.asOf).close-1);
 for(let i=0;i<3;i++)s=applyReplay(s,{action:'advance',steps:20});assert.equal(s.cursor,78);assert.ok(snapshot(s).records.some(r=>r.status==='outside archive'));assert.throws(()=>applyReplay(s,{action:'advance',steps:1}),/end/);
});
test('orders fill next open with costs, preserve integer cash and cost basis, cancel or reject responsibly',()=>{
 let s=applyReplay(freshReplay(),{action:'start'});
 s=applyReplay(s,{action:'order',symbol:'RELIANCE',side:'buy',quantity:3,note:'Test thesis',requestId:'order-buy-1'});assert.equal(s.cash,10000000);assert.deepEqual(s.positions,{});
 s=applyReplay(s,{action:'advance',steps:1});const o=s.orders[0],next=archive.stocks.find(s=>s.symbol==='RELIANCE').bars.find(b=>b.date===archive.dates[1]);
 assert.equal(o.price,Math.round(next.open*100*1.001));assert.equal(o.fee,Math.round(o.price*3*.001));assert.equal(s.cash,10000000-o.total);assert.equal(o.fillDate,archive.dates[1]);assert.equal(s.positions.RELIANCE.cost,o.total);
 assert.throws(()=>applyReplay(s,{action:'order',symbol:'RELIANCE',side:'sell',quantity:4,note:'',requestId:'too-many'}),/unreserved shares/);
 s=applyReplay(s,{action:'order',symbol:'RELIANCE',side:'sell',quantity:1,note:'Reduce',requestId:'sell-one'});s=applyReplay(s,{action:'advance',steps:1});assert.equal(s.positions.RELIANCE.quantity,2);assert.equal(s.positions.RELIANCE.cost,o.total-Math.round(o.total/3));
 s=applyReplay(s,{action:'order',symbol:'RELIANCE',side:'sell',quantity:2,note:'',requestId:'sell-all'});s=applyReplay(s,{action:'advance',steps:1});assert.equal(s.positions.RELIANCE,undefined);assert.ok(Number.isSafeInteger(s.cash));
 s=applyReplay(s,{action:'order',symbol:'RELIANCE',side:'buy',quantity:1,note:'',requestId:'cancel-me'});s=applyReplay(s,{action:'cancel',orderId:'cancel-me'});s=applyReplay(s,{action:'advance',steps:1});assert.equal(s.orders.at(-1).status,'cancelled');
 const poor=applyReplay(freshReplay(),{action:'start'});poor.cash=1;poor.orders=[{id:'gap',symbol:'RELIANCE',side:'buy',quantity:1,note:'',submitted:archive.dates[0],status:'queued'}];const rejected=applyReplay(poor,{action:'advance',steps:1});assert.equal(rejected.cash,1);assert.equal(rejected.orders[0].status,'rejected');
});
test('saved research deduplicates, verifies data fingerprints and scores appended sessions',async()=>{
 const i=history.findIndex(b=>b.date===archive.dates[0]),prefix=history.slice(0,i+1),base={symbol:'RELIANCE',source:'Verified test fixture',benchmarkName:'NIFTY 50'};
 let s=await importResearch({runs:[]},{...base,bars:prefix});assert.equal(s.runs.length,1);assert.equal(s.runs[0].kind,'retrospective forecast');const id=s.runs[0].id;
 assert.deepEqual(await importResearch(s,{...base,bars:prefix}),s);
 const altered=structuredClone(history.slice(0,i+21));altered[10].benchmark*=1.01;const changed=await importResearch(s,{...base,bars:altered});assert.equal(changed.runs.find(r=>r.id===id).status,'history changed');assert.equal(changed.runs.find(r=>r.id===id).result,null);
 s=await importResearch(s,{...base,bars:history.slice(0,i+21)});assert.equal(s.runs.find(r=>r.id===id).status,'resolved');assert.equal(s.runs.find(r=>r.id===id).result.date,archive.dates[20]);assert.equal(s.runs.find(r=>r.id===id).forecast.asOf,archive.dates[0]);
});
test('actual HTTP routes enforce ownership, CSRF, revisions, idempotency and server prices',async()=>{
 globalThis.__forecastUser=null;assert.equal((await lab.GET(get())).status,200);assert.equal((await lab.POST(request({}))).status,401);assert.equal((await research.GET()).status,401);
 globalThis.__forecastUser={userId:'alice'};
 assert.equal((await lab.POST(request({action:'start'},'https://evil.local'))).status,403);
 let r=await call({action:'start',revision:0});assert.equal(r.status,200);assert.equal(r.body.state.cash,10000000);
 const queued=await call({action:'order',revision:1,requestId:'same-order-uuid',symbol:'RELIANCE',side:'buy',quantity:1,note:'HTTP thesis',price:1,userId:'bob'});assert.equal(queued.status,200);assert.equal(queued.body.state.orders.length,1);assert.equal(queued.body.state.cash,10000000);
 const duplicate=await call({action:'order',revision:1,requestId:'same-order-uuid'});assert.equal(duplicate.status,200);assert.equal(duplicate.body.state.orders.length,1);
 const race=await Promise.all([call({action:'advance',revision:2,steps:1}),call({action:'advance',revision:2,steps:1})]);assert.deepEqual(race.map(r=>r.status).sort(),[200,409]);const won=race.find(r=>r.status===200);assert.equal(won.body.state.cursor,1);assert.ok(won.body.state.orders[0].price>1);assert.equal(won.body.state.cash,10000000-won.body.state.orders[0].total);
 globalThis.__forecastUser={userId:'bob'};r=await(await lab.GET(get())).json();assert.equal(r.state.cash,10000000);assert.equal(r.state.started,false);assert.equal(r.state.orders.length,0);
 assert.equal((await lab.POST(new Request('https://test.local/api/lab',{method:'POST',headers:{Origin:'https://test.local','Content-Type':'application/json'},body:'x'.repeat(9000)}))).status,413);
 const imported=await research.POST(request({revision:0,symbol:'RELIANCE',source:'Fixture',benchmarkName:'NIFTY 50',bars:history}));assert.equal(imported.status,200);assert.equal((await imported.json()).state.runs.length,1);
 globalThis.__forecastUser={userId:'alice'};assert.equal((await(await research.GET()).json()).state.runs.length,0);
 assert.equal((await research.POST(request({revision:0,bars:history},'https://evil.local'))).status,403);
});
test.after(()=>{sqlite.close();rmSync(out,{recursive:true,force:true});});
