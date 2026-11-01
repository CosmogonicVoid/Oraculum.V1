/** Local-only, repeatable schema setup for the first two releases. */
import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
process.chdir(fileURLToPath(new URL('../',import.meta.url)));
if(!existsSync('dist/server/wrangler.json'))throw Error('Run npm run build before npm run db:local.');
function query(args){
 const r=spawnSync(process.execPath,['--import','./scripts/sites-env.mjs','./node_modules/wrangler/bin/wrangler.js','d1','execute','DB','--local','--config','dist/server/wrangler.json','--persist-to','.wrangler/state','--json',...args],{encoding:'utf8'});
 if(r.status!==0){process.stderr.write(r.stderr||r.stdout||'Local migration failed.');process.exit(r.status||1);}
 try{return JSON.parse(r.stdout);}catch{throw Error('Could not read the local database result. '+r.stdout.slice(0,100));}
}
const tables=new Set(query(['--command',"SELECT name FROM sqlite_master WHERE type='table'"]).flatMap(x=>x.results).map(x=>x.name));
const migrations=[['drizzle/0000_warm_wither.sql',['accounts','quotes']],['drizzle/0001_gorgeous_the_captain.sql',['replay_accounts','research_accounts']]];
for(const [file,names] of migrations){
 const existing=names.filter(n=>tables.has(n));
 if(existing.length===names.length){console.log(`Already present: ${file}`);continue;}
 if(existing.length)throw Error(`Partial schema for ${file}. Back up your local database and inspect it; no data has been reset.`);
 query(['--file',file]);for(const n of names)tables.add(n);console.log(`Applied locally: ${file}`);
}
console.log('Local database ready. Run npm run dev, then sign in on localhost.');
