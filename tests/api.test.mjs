import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,mkdirSync,writeFileSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';
const root=process.cwd();const out=mkdtempSync(path.join(tmpdir(),'oraculum-test-'));
for(const file of ['lib/server.ts','lib/trading.ts','lib/market.ts','app/api/account/route.ts','app/api/trade/route.ts','app/api/watchlist/route.ts']){
 let source=readFileSync(file,'utf8').replace("import { env } from 'cloudflare:workers';","const env = globalThis.__testEnv;").replace("import { getChatGPTUser } from '../app/chatgpt-auth';","async function getChatGPTUser(){return globalThis.__testUser;}");
 source=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText.replace(/from ['"]([.][^'"]+)['"]/g,"from '$1.mjs'");
 const dest=path.join(out,file.replace('.ts','.mjs'));mkdirSync(path.dirname(dest),{recursive:true});writeFileSync(dest,source);
}
const sqlite=new DatabaseSync(':memory:');sqlite.exec(readFileSync('drizzle/0000_warm_wither.sql','utf8'));
const DB={prepare(sql){let params=[];return{bind(...p){params=p;return this;},async first(){return sqlite.prepare(sql).get(...params)||null;},async run(){const r=sqlite.prepare(sql).run(...params);return{meta:{changes:Number(r.changes)}};}}}};
globalThis.__testEnv={DB};globalThis.__testUser={userId:'alice'};
const trade=await import(pathToFileURL(path.join(out,'app/api/trade/route.mjs')));const account=await import(pathToFileURL(path.join(out,'app/api/account/route.mjs')));const watch=await import(pathToFileURL(path.join(out,'app/api/watchlist/route.mjs')));
const request=(data,origin='https://test.local')=>new Request('https://test.local/api/trade',{method:'POST',headers:{'Content-Type':'application/json',Origin:origin},body:JSON.stringify(data)});
const call=async(data)=>{const r=await trade.POST(request(data));return {status:r.status,body:await r.json()};};
test('HTTP handlers enforce identity, ownership, server pricing, idempotency and CAS',async()=>{
 globalThis.__testUser=null;assert.equal((await account.GET()).status,401);assert.equal((await trade.POST(request({}))).status,401);
 globalThis.__testUser={userId:'alice'};let a=await(await account.GET()).json();assert.equal(a.account.cash,10000000);
 assert.equal((await trade.POST(request({action:'preview'},'https://evil.local'))).status,403);
 assert.equal((await call({action:'preview',symbol:'RELIANCE',side:'buy',quantity:1})).status,400);
 const p=await call({action:'preview',symbol:'ORBIT',side:'buy',quantity:1,price:1,userId:'bob'});assert.equal(p.status,200);assert.ok(p.body.quote.price>1);
 const q=p.body.quote;globalThis.__testUser={userId:'bob'};assert.equal((await call({action:'confirm',quoteId:q.id})).status,404);
 globalThis.__testUser={userId:'alice'};const r=await call({action:'confirm',quoteId:q.id,price:1});assert.equal(r.status,200);assert.equal(r.body.account.cash,10000000-q.total);
 const duplicate=await call({action:'confirm',quoteId:q.id});assert.equal(duplicate.body.account.trades.length,1);assert.equal(duplicate.body.duplicate,true);
 const q1=(await call({action:'preview',symbol:'ORBIT',side:'buy',quantity:1})).body.quote;
 const q2=(await call({action:'preview',symbol:'ORBIT',side:'buy',quantity:1})).body.quote;
 const pair=await Promise.all([call({action:'confirm',quoteId:q1.id}),call({action:'confirm',quoteId:q2.id})]);assert.deepEqual(pair.map(x=>x.status).sort(),[200,409]);
 assert.equal((await watch.POST(request({symbol:'ORBIT',saved:true}))).status,200);
 globalThis.__testUser={userId:'bob'};a=await(await account.GET()).json();assert.equal(a.account.cash,10000000);assert.deepEqual(a.account.watchlist,[]);
 assert.equal((await trade.POST(new Request('https://test.local/api/trade',{method:'POST',headers:{Origin:'https://test.local','Content-Type':'application/json'},body:'a'.repeat(9000)}))).status,413);
});
test.after(()=>{sqlite.close();rmSync(out,{recursive:true,force:true});});
